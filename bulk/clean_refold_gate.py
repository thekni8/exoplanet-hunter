"""Clean-data re-fold gate for bulk-screen handoffs (v1.4).

Lesson (S97 gauntlet, 2026-11-14): TIC 344334378's "detection" lived
entirely in quality-bit-30 flagged cadences that the screen's 17087
bitmask keeps and a quality==0 mask drops -- in clean data there was
no signal at any phase. The gauntlet raw-refuted it after the handoff;
this gate catches that class BEFORE handoff.

Method: for each recalibrated candidate, load its sector FITS from the
cache, take the raw (unflattened) flux column the screen used
(KSPSAP_FLUX -> SYS_RM_FLUX -> DET_FLUX), keep ONLY quality==0
cadences, and fold at the candidate ephemeris (period, t0_btjd,
duration). Depth is median-based (robust to the raw-flux outliers
that explode mean-based folds); noise is the MAD-based scatter of
out-of-transit points. Verdicts:
  PASS         clean dip SNR >= --sigma-min (default 3) with enough
               clean in-transit cadences (>= 20, >= 2 events)
  FAIL         enough clean data but no dip -- artifact, dropped
  INSUFFICIENT too few clean in-transit cadences to test -- passes
               through flagged for the desk (never silently dropped)
  MISSING      FITS not in the cache -- passes through flagged

Validation (2026-11-14, S97 FITS):
  TIC 344334378 (raw-refuted): screen mask 0.538% @ SNR 46.2,
    clean -0.041% @ SNR -2.4 -> FAIL (gate catches it)
  TIC 139526205 (real signal, blend): clean 0.593% @ SNR 66.6 -> PASS
  TIC 382069441 (real persistent signal): clean 1.266% @ SNR 71.7 -> PASS

Usage: python clean_refold_gate.py --survivors run_s0096/recalibrated/survivors_v13.jsonl \
    --sector 96 --out run_s0096/recalibrated/survivors_gated.jsonl
"""
import argparse
import json
import os

import numpy as np
from astropy.io import fits

FLUX_COLS = ("KSPSAP_FLUX", "SYS_RM_FLUX", "DET_FLUX")
MIN_IN = 20          # min clean in-transit cadences for a testable verdict
MIN_EVENTS = 2       # min distinct transit events with clean cadences


def mad_sigma(x):
    return 1.4826 * np.median(np.abs(x - np.median(x)))


def load_fits(path):
    with fits.open(path) as hdul:
        d = hdul[1].data
        t = np.array(d["TIME"], dtype=float)
        q = np.array(d["QUALITY"], dtype=np.int64)
        for col in FLUX_COLS:
            if col in d.columns.names:
                return t, np.array(d[col], dtype=float), q, col
    raise ValueError(f"no flux column in {path}")


def clean_fold(t, f, q, period, t0, dur_h):
    """Fold raw flux on quality==0 cadences only. Returns dict."""
    m = (q == 0) & np.isfinite(t) & np.isfinite(f) & (f > 0)
    tt, ff = t[m], f[m]
    if len(tt) == 0:
        return {"n_clean": 0, "n_in": 0, "n_events": 0,
                "depth_percent": None, "snr": None}
    ff = ff / np.median(ff)
    phase = ((tt - t0) / period + 0.5) % 1.0 - 0.5
    dur_frac = dur_h / 24.0 / period
    in_tr = np.abs(phase) < dur_frac / 2
    n_in = int(in_tr.sum())
    ev = np.unique(np.floor((tt[in_tr] - t0) / period).astype(int)) \
        if n_in else []
    out = {"n_clean": int(len(tt)), "n_in": n_in,
           "n_events": int(len(ev)),
           "depth_percent": None, "snr": None}
    if n_in < 2 or (~in_tr).sum() < 10:
        return out
    depth = 1 - np.median(ff[in_tr]) / np.median(ff[~in_tr])
    sig = mad_sigma(ff[~in_tr]) * 1.2533 / np.sqrt(n_in)
    out["depth_percent"] = float(depth * 100)
    out["snr"] = float(depth / sig) if sig and np.isfinite(sig) else None
    return out


def verdict_for(fold, sigma_min):
    if fold["n_in"] < MIN_IN or fold["n_events"] < MIN_EVENTS:
        return "INSUFFICIENT"
    if fold["snr"] is None or fold["snr"] < sigma_min:
        return "FAIL"
    return "PASS"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--survivors", required=True)
    ap.add_argument("--sector", type=int, required=True)
    ap.add_argument("--cache-dir", default=None,
                    help="default: bulk/cache next to this script")
    ap.add_argument("--sigma-min", type=float, default=3.0)
    ap.add_argument("--out", required=True,
                    help="gated survivors jsonl (PASS/INSUFFICIENT/MISSING)")
    args = ap.parse_args()

    root = os.path.dirname(os.path.abspath(__file__))
    cache = args.cache_dir or os.path.join(root, "cache")
    sdir = os.path.join(cache, f"s{args.sector:04d}")

    recs = [json.loads(l) for l in open(args.survivors)]
    gated, report = [], []
    for r in recs:
        tic = str(r["tic"])
        path = os.path.join(sdir, f"{tic}.fits")
        if not os.path.exists(path):
            v = {"tic": tic, "verdict": "MISSING", "fold": None}
            r["clean_gate"] = "MISSING"
            gated.append(r)
        else:
            t, f, q, col = load_fits(path)
            fold = clean_fold(t, f, q, r["period_days"], r["t0_btjd"],
                              r["duration_hours"])
            v = {"tic": tic, "verdict": verdict_for(fold, args.sigma_min),
                 "flux_col": col, "fold": fold}
            r["clean_gate"] = v["verdict"]
            r["clean_fold"] = fold
            if v["verdict"] != "FAIL":
                gated.append(r)
        report.append(v)
        f = v["fold"]
        detail = (f"clean depth={f['depth_percent']:.3f}% snr={f['snr']:.1f} "
                  f"n_in={f['n_in']} events={f['n_events']}"
                  if f and f["depth_percent"] is not None else "untestable")
        print(f"  TIC {tic}: {v['verdict']} ({detail})")

    with open(args.out, "w") as fh:
        for r in gated:
            fh.write(json.dumps(r) + "\n")
    report_path = args.out.replace(".jsonl", "_gate_report.json")
    with open(report_path, "w") as fh:
        json.dump(report, fh, indent=2)
    n_pass = sum(1 for v in report if v["verdict"] == "PASS")
    n_fail = sum(1 for v in report if v["verdict"] == "FAIL")
    print(f"gate: {len(recs)} in, {len(gated)} out "
          f"({n_pass} PASS, {n_fail} FAIL, "
          f"{len(recs) - n_pass - n_fail} flagged-through)")


if __name__ == "__main__":
    main()
