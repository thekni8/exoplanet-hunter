"""4.1-10 deep-sample curve: campaign + null driver (Phase 4.1, Stage 4).

Runs the 4.1-10 manifests through the SHARED P4-3/P4-5 harness:
the single leg is bulk/k3_run.py, the stitched leg is
bulk/p43_run.py -- the same leg functions BP-1 and P4-5 ran,
unchanged. This driver only builds per-host-sector jobs (the
4.1-10 hosts have 2/3/4 sectors in nine combos -- see
p43_run._build_jobs sectors_by_host) and applies the settled
MES gate.

The gate hookup (the POST-SWEEP gate):
- --mes-gate G (default 9.0, the current gate) is applied
  in-process via bulk_screen.set_mes_gate AFTER set_calibration,
  in every worker (Pool initializer) and on the serial path.
  It moves the tier-A MES bar (and the two-event combined bar,
  which reuses tier_a_mes by design). NO calibration file
  changes: bulk_v5 stays ACTIVE, bulk_v4 byte-frozen.
- The gate is recorded in every host file (mes_gate) and in
  p4110_summary.json, and it is part of the resume check: a
  host file written at gate 9 is NEVER resumed by a run at
  gate 7 (tiers differ) -- it re-runs. A smoke run at 9.0
  therefore never poisons a campaign at 7.0.
- Valid range [7.0, 9.0] (the 4.1-2 sweep steps); anything
  else fails loudly before any work starts.

Modes:
- campaign: --manifest must be the FINALISED manifest
  (trials carry `recorded` -- the P4-3b pre-mask seeds from
  the frozen recorded period). Running on a pre-manifest is
  refused (the fallback would silently change the mask rule).
- null: --manifest must be the null manifest (dummy trials,
  kind null_placeholder). One uninjected run per null host.

Legs: --leg single | stitched | both (default both). The
curve is the STITCHED leg; the single leg is the P4-5-pattern
comparability point (the stacking gain).

Scoring is separate (bulk/p4110_score.py --mes-threshold G
--run-gate G): the scorer re-derives recovery at the gate
from the recorded fields and cross-checks against the
runner's tiers.

Usage (Mac, post-sweep gate -- the campaign spawn):
  python bulk/p4110_run.py --mode campaign --leg both \
      --manifest <p4110_manifest.json> --cache <bulk/cache> \
      --out-dir <phase41-4110/run> --workers 6 \
      --calibration bulk_v5 --mes-gate <SETTLED>
  python bulk/p4110_run.py --mode null --leg both \
      --manifest <p4110_null_manifest.json> --cache <bulk/cache> \
      --out-dir <phase41-4110/run> --workers 6 \
      --calibration bulk_v5 --mes-gate <SETTLED>
"""
import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))

import bulk_screen as bs  # noqa: E402
from bulk import k3_run  # noqa: E402
from bulk import oracle_run as orc  # noqa: E402
from bulk import p43_run  # noqa: E402

DEFAULT_MES_GATE = 9.0


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
        raise SystemExit("[p4110-run] manifest has no trials")
    if mode == "campaign":
        missing = [t for t in trials if "recorded" not in t]
        if missing:
            raise SystemExit(
                f"[p4110-run] REFUSING: {len(missing)} campaign "
                f"trials carry no `recorded` peak -- this is a "
                f"PRE-manifest. Run fresh_pass1 + "
                f"bulk/p4110_finalise.py first; the P4-3b "
                f"pre-mask seeds from the frozen recorded "
                f"period and must not silently fall back.")
        if any(t.get("kind") == "null_placeholder"
               for t in trials):
            raise SystemExit(
                "[p4110-run] REFUSING: null-placeholder trials "
                "in a campaign manifest -- wrong manifest.")
    else:  # null
        bad = [t for t in trials
               if t.get("kind") != "null_placeholder"]
        if bad:
            raise SystemExit(
                f"[p4110-run] REFUSING: {len(bad)} null-manifest "
                f"trials are not null_placeholder -- the null "
                f"leg must never see injection parameters.")


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="4.1-10 campaign + null driver (shared "
                    "P4-3/P4-5 harness, parameterised MES gate).")
    ap.add_argument("--mode", choices=("campaign", "null"),
                    default="campaign")
    ap.add_argument("--leg", choices=("single", "stitched", "both"),
                    default="both")
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--cache", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--calibration", default="bulk_v5")
    ap.add_argument("--mes-gate", type=float,
                    default=DEFAULT_MES_GATE,
                    help="settled MES gate from the 4.1-2 sweep "
                         "(default 9.0, the current gate; valid "
                         "range [7.0, 9.0])")
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
            f"[p4110-run] REFUSING: manifest calibration "
            f"{manifest.get('calibration')!r} != CLI "
            f"{args.calibration!r} -- the run must use the "
            f"manifest's calibration.")
    _validate_manifest(manifest, args.mode)
    if args.mode == "null":
        work_p43 = out_dir / "null_injected-p43"
        work_single = out_dir / "null_injected"
    else:
        work_p43 = out_dir / "injected-p43"
        work_single = out_dir / "injected"
    single_jobs, stitched_jobs, missing = p43_run._build_jobs(
        manifest, cache, out_dir, work_p43,
        work_single, args.keep_fits,
        args.calibration, args.tics, args.limit_hosts,
        mes_gate=args.mes_gate)
    if args.mode == "null":
        for j in single_jobs:
            j.pop("trials", None)
        for j in stitched_jobs:
            j.pop("trials", None)
    print(f"[p4110-run] {args.mode}: {len(single_jobs)} single "
          f"jobs, {len(stitched_jobs)} stitched jobs, "
          f"{len(missing)} missing FITS; mes_gate="
          f"{args.mes_gate} calibration={args.calibration}",
          flush=True)
    if missing:
        for tic, sec in missing[:10]:
            print(f"[p4110-run] MISSING TIC {tic} s{sec:04d}",
                  flush=True)
    if args.dry_run:
        return 0
    (out_dir / "hosts").mkdir(parents=True, exist_ok=True)
    (out_dir / "hosts-p43").mkdir(parents=True, exist_ok=True)
    (out_dir / "null_hosts").mkdir(parents=True, exist_ok=True)
    (out_dir / "null-p43").mkdir(parents=True, exist_ok=True)
    (out_dir / "injected").mkdir(parents=True, exist_ok=True)
    (out_dir / "injected-p43").mkdir(parents=True, exist_ok=True)
    (out_dir / "null_injected").mkdir(parents=True, exist_ok=True)
    (out_dir / "null_injected-p43").mkdir(parents=True,
                                          exist_ok=True)
    t0 = time.time()
    if args.mode == "campaign":
        fns = ((k3_run.run_host_campaign_k3, single_jobs)
               if args.leg in ("single", "both") else (None, []),
               (p43_run.run_host_campaign_p43, stitched_jobs)
               if args.leg in ("stitched", "both") else (None, []))
    else:
        fns = ((k3_run.run_host_null_k3, single_jobs)
               if args.leg in ("single", "both") else (None, []),
               (p43_run.run_host_null_p43, stitched_jobs)
               if args.leg in ("stitched", "both") else (None, []))
    results = []
    for fn, leg_jobs in fns:
        if fn is None:
            continue
        if args.workers <= 1:
            results += [fn(j) for j in leg_jobs]
        else:
            from multiprocessing import Pool
            with Pool(args.workers, initializer=_init_worker,
                      initargs=(args.calibration,
                                args.mes_gate)) as pool:
                results += pool.map(fn, leg_jobs)
    done = sum(1 for r in results if r["status"] == "done")
    skipped = sum(1 for r in results if r["status"] == "skipped")
    failures = [r for r in results if r["status"] == "error"]
    for r in failures:
        print(f"[p4110-run] ERROR TIC {r['tic']}: "
              f"{r.get('error')}", flush=True)
    wall = time.time() - t0
    summary = {
        "tool": "bulk/p4110_run.py",
        "item": "4.1-10 deep-sample curve",
        "mode": args.mode, "leg": args.leg,
        "mes_gate": args.mes_gate,
        "calibration": args.calibration,
        "manifest": str(args.manifest),
        "manifest_sha256": manifest["_sha256"],
        "n_single_jobs": len(single_jobs),
        "n_stitched_jobs": len(stitched_jobs),
        "n_missing_fits": len(missing),
        "missing": [[t, s] for t, s in missing],
        "n_done": done, "n_skipped": skipped,
        "n_failed": len(failures),
        "failures": failures,
        "wall_s": round(wall, 1),
        "workers": args.workers,
    }
    (out_dir / f"p4110_summary_{args.mode}.json").write_text(
        json.dumps(summary, indent=2))
    # The scorer reads p4110_summary.json for the run gate; the
    # campaign and null runs share the gate, so the latest write
    # is correct for either leg.
    (out_dir / "p4110_summary.json").write_text(
        json.dumps(summary, indent=2))
    print(f"[p4110-run] done: {done} run, {skipped} skipped, "
          f"{len(failures)} failed; {wall:.0f}s wall; summary in "
          f"{out_dir / 'p4110_summary.json'}", flush=True)
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
