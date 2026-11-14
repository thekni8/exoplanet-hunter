#!/usr/bin/env python
"""Build a durable per-sector ledger (Phase 1.2, item C-3).

``discoveries.csv`` is gitignored and full run data (``bulk/run_*``)
lives only on the Mac — one dead Mac makes "0 in ~111,000"
unauditable. The ledger is the compact derived artifact that
fixes that: counts + survivor TICs + calibration + run
fingerprint, in one committable JSON file per sector. It does
NOT un-ignore raw run data, and it does NOT duplicate the
committed ``bulk/RECALIBRATION_S00*.md`` reports — those are the
narrative analyses (funnel rules, MES gap tables, finalist
write-ups, gauntlet notes); the ledger is the machine-readable
run record (counts, the full survivor TIC list, calibration
content hashes, the code fingerprint, conservation buckets).
The two complement each other; neither repeats the other.

Usage (run on the Mac, where the run dirs live — Dev-only step,
brief section 6, D-3):
  python bulk/build_ledger.py --sector 96 --run-dir bulk/run_s0096 \
      --out ledger-s96.json
Commit the ledger to the repo (or attach it to a GitHub Release).

--rescore <dir> merges a bulk_v2 rescore's output into the
ledger (brief section 6, D-2): survivors the rescore re-screened
gain ``superseded_by: bulk_v2`` on their ledger entry, and stars
v1 missed but v2 found are added as new entries with
``calibration: bulk_v2`` and ``found_by: rescore_v2``. Records
not re-scored keep the run's calibration plus the run's
``known_defects`` (bulk_v1 carries ``mad_clip_no_floor``).
The merge lives HERE, not in rescore_v2.py: that tool's
boundary (B-2) forbids it writing outside its own --out dir,
and the ledger is this tool's artifact.

The ledger is deterministic except for ``generated_at`` (the
generation timestamp): survivors are sorted by TIC, keys are
sorted, and every number comes from the run's own summary /
manifest / checkpoint — no recomputation, no downloads.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import provenance as _prov  # noqa: E402
from atomic_io import atomic_write_json as _atomic_write_json  # noqa: E402

LEDGER_SCHEMA_VERSION = "1.0"

# Known defects per calibration version, keyed by subsystem then
# bare version. bulk_v1's MAD clip has no depth floor (B-2) — a
# ledger built from a v1 run carries that defect on its face, so
# nobody reads "0 planets" without the asterisk.
KNOWN_DEFECTS = {"bulk": {"v1": ["mad_clip_no_floor"]}}


def _known_defects(calibration_versions):
    defects = []
    for sub, ver in sorted((calibration_versions or {}).items()):
        defects.extend(KNOWN_DEFECTS.get(sub, {}).get(ver, []))
    return defects


def _load_json(path):
    with open(path) as fh:
        return json.load(fh)


def _read_survivor_entries(run_dir, summary):
    """Per-survivor ledger entries: {"tic", "tier"}, sorted by
    TIC. Tiers come from survivors.jsonl; if it is missing (an
    old run dir), the summary's survivor_tics list is used with
    tier null — the TIC list is the durable part."""
    path = run_dir / "survivors.jsonl"
    entries = {}
    if path.exists():
        with open(path) as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                entries[rec["tic"]] = {
                    "tic": rec["tic"],
                    "tier": rec.get("tier")}
    for tic in summary.get("survivor_tics", []):
        entries.setdefault(tic, {"tic": tic, "tier": None})
    return [entries[tic] for tic in sorted(entries)]


def _merge_rescore(ledger, rescore_dir, sector):
    """Merge a rescore_v2 output dir into the ledger (D-2).
    Returns the updated ledger. Raises SystemExit on a missing
    or mismatched rescore dir."""
    rescore_dir = Path(rescore_dir)
    summary_path = rescore_dir / "summary.json"
    jsonl_path = (rescore_dir
                  / f"rescore_v2_s{int(sector):04d}.jsonl")
    if not summary_path.exists():
        raise SystemExit(
            f"rescore dir has no summary.json: {rescore_dir}")
    if not jsonl_path.exists():
        raise SystemExit(
            f"rescore dir has no {jsonl_path.name}: {rescore_dir}")
    rsummary = _load_json(summary_path)
    if rsummary.get("sector") != sector:
        raise SystemExit(
            f"rescore sector {rsummary.get('sector')} != "
            f"ledger sector {sector}")
    if rsummary.get("dry_run"):
        raise SystemExit(
            "cannot merge a --dry-run rescore (no survivors "
            "were re-screened)")
    by_tic = {e["tic"]: e for e in ledger["survivors"]}
    n_superseded = n_new = 0
    with open(jsonl_path) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            tic = rec["tic"]
            if tic in by_tic:
                by_tic[tic]["superseded_by"] = "bulk_v2"
                n_superseded += 1
            else:
                entry = {"tic": tic, "tier": rec.get("tier"),
                         "calibration": "bulk_v2",
                         "found_by": "rescore_v2"}
                ledger["survivors"].append(entry)
                by_tic[tic] = entry
                n_new += 1
    ledger["survivors"].sort(key=lambda e: e["tic"])
    ledger["rescore"] = {
        "calibration": rsummary.get("calibration_version",
                                    "bulk_v2"),
        "run_id": rsummary.get("run_id"),
        "n_candidates": rsummary.get("n_candidates"),
        "n_rescreened": rsummary.get("n_rescreened"),
        "n_survivors": rsummary.get("n_survivors"),
        "n_errors": rsummary.get("n_errors"),
        "n_superseded": n_superseded,
        "n_new_survivors": n_new,
    }
    return ledger


def _download_counts(run_dir, summary):
    """Download stats for the ledger. The chunked driver's
    summary has no download block (the per-slice summaries do),
    so aggregate chunk_*/summary.json when present; a
    single-screen summary carries its own download block."""
    dl = summary.get("download")
    if dl:
        return {"downloaded": dl.get("downloaded"),
                "cached": dl.get("cached"),
                "no_product": dl.get("no_product"),
                "errors": dl.get("errors")}
    agg = {"downloaded": 0, "cached": 0, "no_product": 0,
           "errors": 0}
    n_chunks = 0
    for chunk in sorted(run_dir.glob("chunk_*/summary.json")):
        s = _load_json(chunk)
        d = s.get("download") or {}
        for k in agg:
            agg[k] += d.get(k, 0) or 0
        n_chunks += 1
    return agg if n_chunks else {}


def _known_counts(summary):
    """Known-source removals, in either summary shape: the
    chunked driver records known_filter.{toi,vsx,zooniverse}_
    removed; a single screen records skipped_known.{toi,vsx}
    counts plus a zooniverse_known_survivors list."""
    kf = summary.get("known_filter") or {}
    skipped = summary.get("skipped_known") or {}
    zoo = summary.get("zooniverse_known_survivors")
    return {
        "known_toi": kf.get("toi_removed", skipped.get("toi")),
        "known_vsx": kf.get("vsx_removed", skipped.get("vsx")),
        "known_zooniverse": kf.get(
            "zooniverse_removed",
            len(zoo) if isinstance(zoo, list) else None),
    }


def _ledger_fingerprint(manifest, checkpoint, prov, summary):
    """The ledger's fingerprint block (C-8): the full run
    fingerprint when the manifest carries it (C-8 runs), else the
    components a pre-C-8 run recorded (code fingerprint from the
    checkpoint, recipe hash + git SHA from the provenance
    header). Either way `mixed_pipeline` is recorded — a mixed
    run's fingerprint is the fingerprint of its LAST resume, and
    the flag is what says the run is not one pipeline."""
    block = manifest.get("fingerprint")
    if isinstance(block, dict) and block.get("full"):
        return {
            "full": block["full"],
            "resume": block.get("resume"),
            "components": block.get("components"),
            "mixed_pipeline": bool(summary.get("mixed_pipeline")),
        }
    return {
        "full": None,
        "resume": checkpoint.get("resume_fingerprint"),
        "code_fingerprint": checkpoint.get("code_fingerprint"),
        "recipe_hash": prov.get("recipe_hash"),
        "git_sha": prov.get("pipeline_git_sha"),
        "mixed_pipeline": bool(summary.get("mixed_pipeline")),
    }


def build_ledger(sector, run_dir, rescore_dir=None):
    """Build the ledger dict for one sector's run dir. Pure
    except for reading the run dir (summary / manifest /
    checkpoint / survivors.jsonl)."""
    run_dir = Path(run_dir)
    summary_path = run_dir / "summary.json"
    if not summary_path.exists():
        raise SystemExit(
            f"run dir has no summary.json: {run_dir}")
    summary = _load_json(summary_path)
    if summary.get("sector") != sector:
        raise SystemExit(
            f"summary sector {summary.get('sector')} != "
            f"--sector {sector} — refusing to ledger the wrong "
            f"sector")
    manifest = {}
    manifest_path = run_dir / "manifest.json"
    if manifest_path.exists():
        manifest = _load_json(manifest_path)
    checkpoint = {}
    checkpoint_path = run_dir / "checkpoint.json"
    if checkpoint_path.exists():
        checkpoint = _load_json(checkpoint_path)

    prov = summary.get("provenance", {})
    cal_versions = prov.get("calibration_version") or {}
    if isinstance(cal_versions, str):
        # Legacy 1.1 records stamp a bare string ("bulk_v1");
        # normalise to the 1.2 per-subsystem map.
        cal_versions = {"bulk": cal_versions.replace("bulk_", "")}
    cal_manifest = manifest.get("calibration", {})
    known = _known_counts(summary)
    ledger = {
        "schema_version": LEDGER_SCHEMA_VERSION,
        "ledger_tool": "bulk/build_ledger.py",
        "sector": sector,
        "run_id": prov.get("run_id"),
        "run_status": (manifest.get("execution", {})
                       .get("status")),
        "generated_at": _prov.utc_now_iso(),
        "counts": {
            "window": summary.get("stars_in"),
            "known_toi": known["known_toi"],
            "known_vsx": known["known_vsx"],
            "known_zooniverse": known["known_zooniverse"],
            "searched": summary.get("stars_searched"),
            # F-13: stars MEASURED (searched minus watchdog
            # timeouts) is the number to quote as "N screened".
            # The summary records it when the screen wrote it;
            # old summaries yield it from searched - unmeasured.
            "measured": (
                summary.get("stars_measured")
                if summary.get("stars_measured") is not None
                else (summary.get("stars_searched") or 0)
                - (summary.get("screen_counts") or {})
                .get("unmeasured", 0)),
            "hits_recorded": summary.get("hits_recorded"),
            "survivors": summary.get("survivors"),
            "survivor_tiers": summary.get("survivor_tiers"),
            "screen_counts": summary.get("screen_counts"),
            "download": _download_counts(run_dir, summary),
        },
        "survivors": _read_survivor_entries(run_dir, summary),
        "calibration": {
            "versions": cal_versions,
            "hashes": cal_manifest.get("hashes", {}),
            "sha256": (cal_manifest.get("sha256")
                       or prov.get("calibration_sha256")),
        },
        "known_defects": _known_defects(cal_versions),
        "fingerprint": _ledger_fingerprint(manifest, checkpoint,
                                           prov, summary),
        "conservation": summary.get("conservation"),
        "rescore": None,
    }
    if rescore_dir is not None:
        _merge_rescore(ledger, rescore_dir, sector)
    return ledger


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Build a durable per-sector ledger from a "
                    "screen run directory.")
    ap.add_argument("--sector", type=int, required=True)
    ap.add_argument("--run-dir", required=True,
                    help="run directory holding summary.json "
                         "(+ manifest.json, checkpoint.json, "
                         "survivors.jsonl when present)")
    ap.add_argument("--out", required=True,
                    help="ledger JSON file to write")
    ap.add_argument("--rescore", default=None,
                    help="rescore_v2 output dir to merge (D-2): "
                         "re-scored survivors are marked "
                         "superseded_by bulk_v2, new v2 survivors "
                         "are added")
    args = ap.parse_args(argv)
    ledger = build_ledger(args.sector, args.run_dir,
                          rescore_dir=args.rescore)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_json(out, ledger)
    n = len(ledger["survivors"])
    print(f"ledger: sector {args.sector}, "
          f"{ledger['counts']['window']} window stars, "
          f"{n} survivors -> {out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
