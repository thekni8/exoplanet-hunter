"""Bright-star curve: manifest finalisation.

Attaches the pass-1 `recorded` peak to every pre-manifest trial
(4.1-10 / BP-1 / P4-5 pattern). The campaign's P4-3b pre-mask
seeds the non-original sectors from the FROZEN recorded period,
so the campaign cannot run on the pre-manifest -- it runs on
the finalised manifest.

This step performs NO selection and NO classification: every
pre-manifest trial runs in the campaign. The only checks are
completeness checks (every trial has a pass-1 record, the
injection epoch/duration match, no errors) -- a failure here
is a broken establishment run, not a trial to drop.

Gate note: fresh_pass1 runs at the CURRENT 9.0 gate (bulk_v5
as-is, no override). That is correct here: the campaign
consumes only the recorded PERIOD and DEPTH (gate-independent
measurements) from this step; the recorded status/tier/mes
are diagnostics, never read by the campaign. The settled MES
gate applies to the CAMPAIGN legs (bulk/p4110_run.py
--mes-gate), not to establishment.

Usage (Mac, after fresh_pass1; or VM on copied host files):
  python bulk/brightstar_finalise.py \
      --pre-manifest <brightstar_premanifest.json> \
      --pass1-dir <phase41-brightstar-curve/pass1> \
      --out <brightstar_manifest.json>
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bulk.brightstar_manifest import (  # noqa: E402
    BLOCK_END,
    BLOCK_START,
    assert_manifest,
)


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def finalise(pre_manifest_path, pass1_dir):
    """Attach `recorded` to every trial. Returns the final
    manifest dict. Fails loudly on any establishment gap."""
    pre_path = Path(pre_manifest_path)
    pre = json.loads(pre_path.read_text())
    pre_sha = _sha(pre_path)
    # No hardcoded pre-manifest sha assert lives here -- the
    # lock is enforced by the per-host-file pre_manifest_sha
    # linkage below (a wrong pre-manifest matches zero host
    # files, so the first trial fails "no pass-1 record").
    p1_dir = Path(pass1_dir)
    summary_path = p1_dir / "pass1_summary.json"
    p1_summary = (json.loads(summary_path.read_text())
                  if summary_path.exists() else None)
    p1 = {}
    n_files = 0
    for path in sorted((p1_dir / "hosts").glob("*.json")):
        rec = json.loads(path.read_text())
        if rec.get("pre_manifest_sha") != pre_sha:
            continue  # belongs to another pre-manifest
        n_files += 1
        assert rec["complete"] is True, f"{path} incomplete"
        assert rec["calibration"] == "bulk_v5", (
            f"{path} calibration {rec['calibration']} != bulk_v5")
        for tr in rec["trials"]:
            assert "error" not in tr, (
                f"{path} {tr['trial_id']}: {tr.get('error')}")
            key = (tr["tic"], int(tr["sector"]), tr["trial_id"])
            assert key not in p1, f"duplicate pass-1 record {key}"
            p1[key] = tr
    trials = []
    n_pass1_recovered = 0
    for tr in pre["trials"]:
        key = (tr["tic"], int(tr["sector"]), tr["trial_id"])
        assert key in p1, f"no pass-1 record for {key}"
        r = p1[key]
        assert abs(r["inject_epoch_delta_d"]) < 1e-9, key
        assert abs(r["inject_dur_delta_d"]) < 1e-9, key
        assert abs(r["epoch_btjd"] - tr["epoch_btjd"]) < 1e-9, key
        assert abs(r["duration_d"] - tr["duration_d"]) < 1e-9, key
        s = r["screen"]
        if r.get("recovered"):
            n_pass1_recovered += 1
        out = dict(tr)
        out["recorded"] = {
            "status": s["status"], "tier": s.get("tier"),
            "period_days": s.get("period_days"),
            "depth_percent": s.get("depth_percent"),
            "sde": s.get("sde"),
            "mes_pink": s.get("mes_pink"),
            "flags": s.get("flags", []),
            "n_events_found": s.get("n_events_found"),
            "n_strong_events": s.get("n_strong_events"),
            "max_event_snr": s.get("max_event_snr"),
        }
        trials.append(out)
    assert len(trials) == len(pre["trials"]), (
        f"finalised {len(trials)} != pre-manifest "
        f"{len(pre['trials'])}")
    manifest = dict(pre)
    manifest["item"] = ("bright-star curve (campaign manifest, "
                        "pass-1 established)")
    manifest["seed_block"] = f"{BLOCK_START}-{BLOCK_END}"
    manifest["block_bounds"] = [BLOCK_START, BLOCK_END]
    manifest["trial_index_span"] = [0, 799]
    manifest["pre_manifest_sha256"] = pre_sha
    manifest["pass1_summary"] = p1_summary
    manifest["pass1_host_files"] = n_files
    manifest["pass1_recovered"] = {
        "n_recovered": n_pass1_recovered,
        "n_trials": len(trials),
        "note": ("Original-sector K=1 pass-1 recovery -- a "
                 "diagnostic, not a gate and not the curve. "
                 "The curve is measured on the stitched leg.")}
    manifest["trials"] = trials
    assert_manifest(manifest)
    return manifest


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Finalise the bright-star manifest with "
                    "pass-1 recorded peaks.")
    ap.add_argument("--pre-manifest", required=True)
    ap.add_argument("--pass1-dir", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    manifest = finalise(args.pre_manifest, args.pass1_dir)
    out = Path(args.out)
    out.write_text(json.dumps(manifest, indent=1, sort_keys=True))
    print(f"wrote {out}: {len(manifest['trials'])} trials, "
          f"pass-1 recovered "
          f"{manifest['pass1_recovered']['n_recovered']}/"
          f"{manifest['pass1_recovered']['n_trials']}")
    print("sha256:", _sha(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
