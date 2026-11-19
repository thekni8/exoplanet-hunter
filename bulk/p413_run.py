"""4.1-3 stacked-floor measurement: campaign + null driver.

Runs the 4.1-3 manifests through the SHARED P4-3/P4-5 harness:
the stitched leg is bulk/p43_run.py -- the same leg function
BP-1, P4-5, 4.1-10 and the bright-star curve ran, unchanged
except for the flag-gated pass-1 recording (see below). This
driver only builds per-host jobs and applies the settled MES
gate + the interval's sector set.

4.1-3 has NO single-sector leg: this driver runs the STITCHED
leg only, at one interval per invocation (--interval 2|3|4).
The three intervals re-read the SAME finalised manifest (same
trials, same seeds, same absolute epochs); only the sector
set changes. Each interval runs into its own out-dir, so host
files never collide across intervals.

Intervals (pre-reg section 2.3):
- 2: S95+S96
- 3: S95+S96+S97
- 4: S95+S96+S97+S98

The gate hookup (the POST-SWEEP gate):
- --mes-gate G (default 9.0, the settled gate) is applied
  in-process via bulk_screen.set_mes_gate AFTER set_calibration,
  in every worker (Pool initializer) and on the serial path.
  NO calibration file changes: bulk_v5 stays ACTIVE, bulk_v4
  byte-frozen.
- The gate is recorded in every host file (mes_gate) and in
  p413_summary.json, and it is part of the resume check.

Stitched pass-1 recording (PIPE50-9c):
- --record-pass1-stitched sets job["record_pass1_stitched"]
  on the campaign jobs: the stitched leg additionally screens
  the UNMASKED stitch per trial and records it as r["pass1"]
  (a diagnostic -- it does not feed pass 2/3 and does not
  change any pipeline decision). The null leg already records
  its stitched pass-1 screen unconditionally, so the flag is
  a campaign-only concern.

Modes:
- campaign: --manifest must be the FINALISED manifest
  (trials carry `recorded`). Running on a pre-manifest is
  refused.
- null: --manifest must be the null manifest (dummy trials,
  kind null_placeholder). The runner filters to the hosts
  whose `intervals` list includes --interval, then overrides
  their sector set. One uninjected run per null host per
  interval.

Scoring is separate (bulk/p413_score.py): the scorer
re-derives recovery at the gate from the recorded fields and
cross-checks against the runner's tiers.

Usage (Mac, post-sweep gate -- the campaign spawn):
  python bulk/p413_run.py --mode campaign --interval 4 \
      --manifest <p413_manifest.json> --cache <bulk/cache> \
      --out-dir <phase41-413/run/interval4> --workers 6 \
      --calibration bulk_v5 --mes-gate 9 \
      --record-pass1-stitched
  python bulk/p413_run.py --mode null --interval 2 \
      --manifest <p413_null_manifest.json> --cache <bulk/cache> \
      --out-dir <phase41-413/run/interval2> --workers 6 \
      --calibration bulk_v5 --mes-gate 9
"""
import argparse
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))

import bulk_screen as bs  # noqa: E402
from bulk import oracle_run as orc  # noqa: E402
from bulk import p43_run  # noqa: E402

DEFAULT_MES_GATE = 9.0
INTERVAL_SECTORS = {2: [95, 96], 3: [95, 96, 97],
                    4: [95, 96, 97, 98]}


def _init_worker(calibration, mes_gate):
    """Pool initializer: calibration first, then the MES-gate
    override (set_calibration would undo it -- order matters)."""
    bs.set_calibration(calibration)
    if mes_gate is not None:
        bs.set_mes_gate(mes_gate)


def _validate_manifest(manifest, mode):
    """Refuse the wrong manifest for the mode, loudly."""
    trials = manifest.get("trials", [])
    if not trials:
        raise SystemExit("[p413-run] manifest has no trials")
    if mode == "campaign":
        missing = [t for t in trials if "recorded" not in t]
        if missing:
            raise SystemExit(
                f"[p413-run] REFUSING: {len(missing)} campaign "
                f"trials carry no `recorded` peak -- this is a "
                f"PRE-manifest. Run fresh_pass1 + "
                f"bulk/p413_finalise.py first; the P4-3b "
                f"pre-mask seeds from the frozen recorded "
                f"period and must not silently fall back.")
        if any(t.get("kind") == "null_placeholder"
               for t in trials):
            raise SystemExit(
                "[p413-run] REFUSING: null-placeholder trials "
                "in a campaign manifest -- wrong manifest.")
    else:  # null
        bad = [t for t in trials
               if t.get("kind") != "null_placeholder"]
        if bad:
            raise SystemExit(
                f"[p413-run] REFUSING: {len(bad)} null-manifest "
                f"trials are not null_placeholder -- the null "
                f"leg must never see injection parameters.")


def apply_interval(manifest, interval, mode):
    """Return a manifest copy restricted to one interval:
    trials filtered (null mode: hosts whose `intervals`
    includes this interval) and sectors_by_host overridden
    to the interval's sector set. The original manifest dict
    is NOT modified. The _sha256 (the manifest file's hash)
    is preserved -- the jobs record the manifest they came
    from."""
    sectors = INTERVAL_SECTORS[interval]
    man = dict(manifest)
    trials = list(manifest["trials"])
    if mode == "null":
        trials = [t for t in trials
                  if interval in t.get("intervals", [])]
        if not trials:
            raise SystemExit(
                f"[p413-run] no null hosts are eligible for "
                f"interval {interval}")
    man["trials"] = trials
    sbh = {}
    for t in trials:
        tic = t["tic"]
        have = sorted(int(s) for s in t.get(
            "sectors", manifest.get("sectors_by_host", {}).get(
                tic, sectors)))
        use = [s for s in sectors if s in have]
        if use != sectors:
            raise SystemExit(
                f"[p413-run] TIC {tic} lacks sectors for "
                f"interval {interval}: has {have}, needs "
                f"{sectors}")
        sbh[tic] = list(sectors)
    man["sectors_by_host"] = sbh
    return man


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="4.1-3 campaign + null driver (shared "
                    "P4-3/P4-5 harness, stitched leg only, one "
                    "interval per invocation).")
    ap.add_argument("--mode", choices=("campaign", "null"),
                    default="campaign")
    ap.add_argument("--interval", type=int, required=True,
                    choices=(2, 3, 4),
                    help="sector-count interval: 2 = S95+S96, "
                         "3 = S95+S96+S97, 4 = S95+S96+S97+S98")
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--cache", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--calibration", default="bulk_v5")
    ap.add_argument("--mes-gate", type=float,
                    default=DEFAULT_MES_GATE,
                    help="settled MES gate from the 4.1-2 sweep "
                         "(default 9.0; valid range [7.0, 9.0])")
    ap.add_argument("--record-pass1-stitched", action="store_true",
                    help="campaign only: record the unmasked "
                         "stitched pass-1 screen per trial "
                         "(PIPE50-9c)")
    ap.add_argument("--tics", nargs="*", default=None)
    ap.add_argument("--limit-hosts", type=int, default=None)
    ap.add_argument("--keep-fits", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    # Fail fast on a bad gate -- before any work starts.
    bs.set_calibration(args.calibration)
    bs.set_mes_gate(args.mes_gate)
    out_dir = Path(args.out_dir)
    cache = Path(args.cache)
    manifest = orc._load_manifest(args.manifest)
    if manifest.get("calibration") != args.calibration:
        raise SystemExit(
            f"[p413-run] REFUSING: manifest calibration "
            f"{manifest.get('calibration')!r} != CLI "
            f"{args.calibration!r} -- the run must use the "
            f"manifest's calibration.")
    _validate_manifest(manifest, args.mode)
    manifest = apply_interval(manifest, args.interval, args.mode)
    if args.mode == "null":
        work_p43 = out_dir / "null_injected-p43"
        work_single = out_dir / "null_injected"
    else:
        work_p43 = out_dir / "injected-p43"
        work_single = out_dir / "injected"
    _single_jobs, stitched_jobs, missing = p43_run._build_jobs(
        manifest, cache, out_dir, work_p43,
        work_single, args.keep_fits,
        args.calibration, args.tics, args.limit_hosts,
        mes_gate=args.mes_gate)
    if args.mode == "null":
        for j in stitched_jobs:
            j.pop("trials", None)
    elif args.record_pass1_stitched:
        for j in stitched_jobs:
            j["record_pass1_stitched"] = True
    print(f"[p413-run] {args.mode} interval {args.interval}: "
          f"{len(stitched_jobs)} stitched jobs, "
          f"{len(missing)} missing FITS; mes_gate="
          f"{args.mes_gate} calibration={args.calibration} "
          f"record_pass1_stitched="
          f"{bool(args.record_pass1_stitched and args.mode == 'campaign')}",
          flush=True)
    if missing:
        for tic, sec in missing[:10]:
            print(f"[p413-run] MISSING TIC {tic} s{sec:04d}",
                  flush=True)
    if args.dry_run:
        return 0
    (out_dir / "hosts-p43").mkdir(parents=True, exist_ok=True)
    (out_dir / "null-p43").mkdir(parents=True, exist_ok=True)
    (out_dir / "injected-p43").mkdir(parents=True, exist_ok=True)
    (out_dir / "null_injected-p43").mkdir(parents=True,
                                          exist_ok=True)
    t0 = time.time()
    fn = (p43_run.run_host_campaign_p43
          if args.mode == "campaign"
          else p43_run.run_host_null_p43)
    if args.workers <= 1:
        results = [fn(j) for j in stitched_jobs]
    else:
        from multiprocessing import Pool
        with Pool(args.workers, initializer=_init_worker,
                  initargs=(args.calibration,
                            args.mes_gate)) as pool:
            results = pool.map(fn, stitched_jobs)
    done = sum(1 for r in results if r["status"] == "done")
    skipped = sum(1 for r in results if r["status"] == "skipped")
    failures = [r for r in results if r["status"] == "error"]
    for r in failures:
        print(f"[p413-run] ERROR TIC {r['tic']}: "
              f"{r.get('error')}", flush=True)
    wall = time.time() - t0
    summary = {
        "tool": "bulk/p413_run.py",
        "item": "4.1-3 stacked-floor measurement",
        "mode": args.mode, "interval": args.interval,
        "sectors": INTERVAL_SECTORS[args.interval],
        "leg": "stitched",
        "mes_gate": args.mes_gate,
        "calibration": args.calibration,
        "record_pass1_stitched": bool(
            args.record_pass1_stitched
            and args.mode == "campaign"),
        "manifest": str(args.manifest),
        "manifest_sha256": manifest["_sha256"],
        "n_stitched_jobs": len(stitched_jobs),
        "n_missing_fits": len(missing),
        "missing": [[t, s] for t, s in missing],
        "n_done": done, "n_skipped": skipped,
        "n_failed": len(failures),
        "failures": failures,
        "wall_s": round(wall, 1),
        "workers": args.workers,
    }
    (out_dir / f"p413_summary_{args.mode}_interval"
     f"{args.interval}.json").write_text(
        json.dumps(summary, indent=2))
    (out_dir / "p413_summary.json").write_text(
        json.dumps(summary, indent=2))
    print(f"[p413-run] done: {done} run, {skipped} skipped, "
          f"{len(failures)} failed; {wall:.0f}s wall; summary in "
          f"{out_dir / 'p413_summary.json'}", flush=True)
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
