#!/usr/bin/env python
"""Injection-recovery into REAL S96 light curves, deep pipeline
(deep_v2 sensitivity re-measurement, 2026-11-15).

The bulk M-6 mirror (bulk/inject_real_s96.py): one
injection-recovery into real S96 light curves carrying bits
29/30 flags, deep_v1 vs deep_v2, committed with seeds. The
synthetic regression tests (tests/test_deep_quality_mask.py)
prove the mask removes a flagged-only artifact and keeps a
bit-12 transit; this script tests real flag patterns — the
hosts' actual QUALITY columns, real noise, real systematics —
and asks whether deep_v2 loses any injected transit deep_v1
finds.

Method: for each host TIC, download its sector-96 QLP light
curve from MAST through lightkurve (the deep pipeline's own
download path — the returned curve is exactly what hunter.py
sees, default-masked rows already removed, QUALITY surviving
on the rest), inject a trapezoid transit (the repo's shared
model, injection_harness.inject_transit) into the real flux,
keeping TIME and QUALITY untouched, write an injected fixture
(t, f, q, meta_json) to the work dir, and run the REAL deep
pipeline (hunter._run_pipeline, via the EXHUNT_FIXTURE_DIR
seam) under deep_v1 and deep_v2. Recovery = headline Period
within 1% of the injected period AND SDE >= 8.5 (HIT_SDE).

Trials (fixed, recorded in summary.json — these ARE the seeds;
the injection itself is deterministic given them):
  A: 2.0% depth @ 5.123 d, first transit t_min + 2.0 d
  B: 1.0% depth @ 3.317 d, first transit t_min + 1.0 d
Same trials as the bulk M-6 run, so the two measurements are
comparable. Trial A is strong enough to dominate the hosts'
pre-existing signals (several hosts are v1 finalists with weak
real signals in them); trial B probes a shallower transit.

Hosts: the same six M-6 TICs (bulk/inject_real_s96_summary.json).
The hosts' flag coverage (bit 29 / bit 30 / any-flag fractions)
is recorded per star, so the run shows its hosts do carry the
flags under test.

Outputs (in --out-dir, default /tmp/inject_deep_real_s96):
  injections.jsonl   one record per (star, trial, calibration)
  summary.json       the trials + per-star v1/v2 recovery table
  reports/ + discoveries.csv  _run_pipeline's per-call PNG + CSV
    row (original behaviour, preserved deliberately) — the
    script chdirs into --out-dir so they land there, not in
    the repo.
The run's summary is ALSO committed as
bulk/inject_deep_real_s96_summary.json (the clip_grid_summary.json
precedent: small analysis evidence lives in the repo).

Usage:
  python bulk/inject_deep_real_s96.py [--tics 31852076 382069441]
      [--out-dir DIR]
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import hunter  # noqa: E402
import injection_harness as ih  # noqa: E402

# The six M-6 hosts (bulk/inject_real_s96_summary.json).
HOST_TICS = ["231011325", "231852754", "234510264", "237911080",
             "31852076", "382069441"]
SECTOR = 96
# (label, depth_frac, period_d, epoch_offset_d from t_min)
TRIALS = [
    ("A", 0.020, 5.123, 2.0),
    ("B", 0.010, 3.317, 1.0),
]
CALIBRATIONS = ("deep_v1", "deep_v2")
RECOVERY_TOL = 0.01  # headline period within 1% of injected


def download_host_qlp(tic, sector=SECTOR):
    """The host's sector light curve as the deep pipeline sees
    it: lightkurve download (default bitmask applied at read,
    passed explicitly — DF-11), TIME / flux / QUALITY arrays of
    the surviving rows. The substrate design DEPENDS on the
    default reader mask: the v1-vs-v2 comparison measures what
    the v2 mask adds on top of the rows v1's reader already
    kept, so the download must not apply the v2 mask (that would
    make the v1 half vacuous) nor "none" (that would change the
    published sensitivity substrates)."""
    import lightkurve as lk
    sr = lk.search_lightcurve(f"TIC {tic}", author="QLP")
    if len(sr) == 0:
        raise RuntimeError(f"TIC {tic}: no QLP products on MAST")
    tbl = sr.table
    rows = [i for i in range(len(sr))
            if int(tbl["sequence_number"][i]) == sector]
    if not rows:
        raise RuntimeError(
            f"TIC {tic}: no QLP sector-{sector} product on MAST")
    lc = sr[rows[0]].download(quality_bitmask="default")
    if lc is None:
        raise RuntimeError(f"TIC {tic}: QLP download returned None")
    t = np.asarray(lc.time.value, dtype=float)
    f = np.asarray(lc.flux.value, dtype=float)
    q = (np.asarray(lc.quality, dtype=np.int64)
         if "quality" in lc.columns
         else np.zeros(len(t), dtype=np.int64))
    return t, f, q


def flag_stats(q):
    """Host flag coverage: fractions carrying bit 29, bit 30,
    and any flag at all."""
    n = len(q)
    return {
        "n_cadences": int(n),
        "frac_bit29": float((((q >> 29) & 1).sum()) / n) if n else 0.0,
        "frac_bit30": float((((q >> 30) & 1).sum()) / n) if n else 0.0,
        "frac_any_flag": float(((q != 0).sum()) / n) if n else 0.0,
    }


def write_fixture(fixture_dir, tic, t, f, q):
    """An EXHUNT_FIXTURE_DIR fixture (t, f, q, meta_json)."""
    meta = {"tic": str(tic), "max_sectors": 1, "star_radius": 1.0,
            "n_sectors": 1, "n_points": int(len(t))}
    np.savez_compressed(
        Path(fixture_dir) / f"TIC_{tic}.npz",
        t=np.asarray(t, dtype=float),
        f=np.asarray(f, dtype=float),
        q=np.asarray(q, dtype=np.int64),
        meta_json=json.dumps(meta))


def run_star(tic, fixture_dir):
    """Download one host; inject both trials; run each under v1
    and v2. Returns the star's record (host stats + trials)."""
    t, f, q = download_host_qlp(tic)
    rec = {"tic": tic, "sector": SECTOR, "product": "QLP",
           "flags": flag_stats(q), "trials": {}}
    for label, depth, period, epoch_off in TRIALS:
        epoch = float(np.nanmin(t)) + epoch_off
        f_inj, duration_d = ih.inject_transit(t, f, depth, period,
                                              epoch)
        write_fixture(fixture_dir, tic, t, f_inj, q)
        trial = {"depth_frac": depth, "period_d": period,
                 "epoch_btjd": epoch, "duration_d": duration_d}
        for cal in CALIBRATIONS:
            with hunter.calibration_context(cal):
                full = hunter._run_pipeline(
                    tic, star_radius=1.0, max_sectors=None)
                found = full.get("Period")
                recovered = (
                    found is not None
                    and abs(found - period) / period < RECOVERY_TOL
                    and full.get("SDE", 0.0) >= hunter.HIT_SDE)
                trial[cal] = {"period_days": found,
                              "sde": full.get("SDE"),
                              "depth_percent":
                                  full.get("Depth", 0.0) * 100.0
                                  if full.get("Depth") is not None
                                  else None,
                              "recovered": bool(recovered)}
        rec["trials"][label] = trial
    return rec


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Inject transits into real S96 light curves; "
                    "run the deep pipeline under v1 vs v2 (see "
                    "module docstring).")
    ap.add_argument("--tics", nargs="*", default=None,
                    help="subset of host TICs (default: all six "
                         "M-6 hosts)")
    ap.add_argument("--out-dir", default="/tmp/inject_deep_real_s96",
                    help="output directory (injections.jsonl + "
                         "summary.json); the script chdirs here "
                         "so _run_pipeline's PNGs + discoveries.csv "
                         "land here, not in the repo")
    args = ap.parse_args(argv)
    tics = args.tics or HOST_TICS
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    fixture_dir = out_dir / "fixtures"
    fixture_dir.mkdir(exist_ok=True)
    # _run_pipeline saves its diagnostic PNG to reports/ (it does
    # not create the dir — the repo has one; a fresh out-dir does
    # not).
    (out_dir / "reports").mkdir(exist_ok=True)
    # _run_pipeline writes reports/ + discoveries.csv relative
    # to the cwd (original behaviour) — keep them out of the repo.
    os.chdir(out_dir)
    os.environ["EXHUNT_FIXTURE_DIR"] = str(fixture_dir)
    t0 = time.time()
    records = []
    # No manual calibration save/restore here: run_star switches
    # through hunter.calibration_context, which restores in a
    # finally block even if a run raises.
    with open(out_dir / "injections.jsonl", "w") as fh:
        for i, tic in enumerate(tics):
            rec = run_star(tic, fixture_dir)
            records.append(rec)
            fh.write(json.dumps(rec) + "\n")
            fh.flush()
            fs = rec["flags"]
            print(f"[inject-deep] {i + 1}/{len(tics)} "
                  f"TIC {tic}: bit29 {fs['frac_bit29']:.1%} "
                  f"bit30 {fs['frac_bit30']:.1%} any-flag "
                  f"{fs['frac_any_flag']:.1%}", flush=True)
            for label, trial in rec["trials"].items():
                v1 = trial["deep_v1"]
                v2 = trial["deep_v2"]
                print(f"    trial {label} "
                      f"({trial['depth_frac']:.1%} @ "
                      f"{trial['period_d']} d): v1 "
                      f"P={v1['period_days']:.4f} "
                      f"SDE {v1['sde']:.1f} "
                      f"recovered={v1['recovered']} | v2 "
                      f"P={v2['period_days']:.4f} "
                      f"SDE {v2['sde']:.1f} "
                      f"recovered={v2['recovered']}",
                      flush=True)
    n_trials = len(records) * len(TRIALS)
    summary = {
        "tool": "inject_deep_real_s96",
        "sector": SECTOR,
        "trials": [{"label": label, "depth_frac": depth,
                    "period_d": period, "epoch_offset_d": epoch_off}
                   for label, depth, period, epoch_off in TRIALS],
        "calibrations": list(CALIBRATIONS),
        "recovery_tol": RECOVERY_TOL,
        "recovery_bar_sde": hunter.HIT_SDE,
        "n_stars": len(records),
        "n_trials": n_trials,
        "recovered_v1": sum(
            1 for r in records for tr in r["trials"].values()
            if tr["deep_v1"]["recovered"]),
        "recovered_v2": sum(
            1 for r in records for tr in r["trials"].values()
            if tr["deep_v2"]["recovered"]),
        "stars": records,
        "wall_seconds": time.time() - t0,
    }
    (out_dir / "summary.json").write_text(
        json.dumps(summary, indent=2))
    print(f"[inject-deep] done: {len(records)} stars x "
          f"{len(TRIALS)} trials in "
          f"{summary['wall_seconds']:.0f}s; recovered v1 "
          f"{summary['recovered_v1']}/{n_trials}, v2 "
          f"{summary['recovered_v2']}/{n_trials}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
