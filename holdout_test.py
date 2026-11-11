#!/usr/bin/env python
"""Leave-one-sector-out HOLDOUT prediction test (2026-11-11).

Adopted from the Pavel Rabtsevich / TIC 4206066 playbook (TOI-7930):
his candidate survived because an ephemeris derived from SOME years of
TESS data predicted the transits in the HELD-OUT years, blind. Our
persistence stamp (persistence.py) only ever re-measures the filed
ephemeris on data that includes the sectors the ephemeris was derived
from; this test asks the harder question — does the signal PREDICT
data it has never seen?

Method (per fold):
  * The star's sectors (same download path and product data as the
    production pipeline: hunter._run_pipeline's stitched fluxes, split
    back into sectors exactly as persistence.py does) are partitioned
    into folds — one sector per fold when there are <= 6 usable
    sectors, otherwise contiguous eras targeting 5 folds.
  * HOLD OUT the fold. Refit the ephemeris by BLS on the TRAINING
    sectors' flattened flux only, on a narrow grid around the filed
    period (+/- 1.5%). If the refit wanders > 1% from the filed period
    the fold is marked "refinement lost" and counts as unusable.
  * Predict the transit windows in the held-out fold from the refined
    ephemeris and measure them in the fold's RAW (unflattened,
    outlier-cleaned only) flux with hunter._raw_fold_depth — the same
    median-depth / guard-band / chunked-red-noise machinery and the
    same 3-sigma bar as the pass-2 raw-flux gate.

Verdict (set in advance, do not tune per target):
  * HOLDOUT-INSUFFICIENT-DATA — fewer than 3 usable folds, or fewer
    than 3 fully-covered held-out transit windows in total. The test
    could not run honestly; it says nothing either way.
  * HOLDOUT-PASS — usable folds >= 3 AND a strict majority of usable
    folds show the predicted dip at >= 3 sigma in held-out raw flux
    AND the inverse-variance combined held-out significance is
    >= 3 sigma AND no usable fold shows a significant OPPOSITE
    signal (<= -3 sigma).
  * HOLDOUT-FAIL — the test ran with enough folds and the predictions
    were not borne out (majority of folds below 3 sigma, combined
    significance < 3 sigma, or a significant opposite fold).

WHAT THIS TEST PROVES — AND WHAT IT DOES NOT:
  A pass proves PREDICTIVE PERIODICITY only: a strictly periodic dip
  really is present in data the ephemeris never touched. A clean
  eclipsing binary passes it trivially (regression control
  TIC 308851365, a confirmed EB, is EXPECTED to stamp HOLDOUT-PASS).
  The holdout test complements the existing gates — raw-flux depth,
  odd/even, double-period shape, centroid / difference imaging — and
  NEVER replaces them. A HOLDOUT-PASS is not a planet, not a
  validation, and not a filing argument on its own.

Usage (desk check):
  python holdout_test.py TIC PERIOD T0_BTJD DURATION_HOURS \
      [--sector-cap 20] [--radius 1.0] [--max-folds 5] [--out JSON]
"""
import argparse
import gc
import json
import math
import sys
import warnings

import numpy as np

warnings.filterwarnings("ignore")

import hunter  # noqa: E402
import persistence  # noqa: E402

# --- Verdict constants (set in advance; see header) ------------------------
MIN_USABLE_FOLDS = 3
MIN_TOTAL_FULL_EVENTS = 3
FOLD_SIGNIF_BAR = 3.0        # the house raw-flux bar (pass-2 gate)
OPPOSITE_BAR = -3.0
MAX_FOLDS_SINGLE_SECTOR = 6  # <= this many sectors -> one fold per sector
REFINE_PERIOD_TOL_FRAC = 0.01
REFINE_GRID_HALF_FRAC = 0.015


def _refine_ephemeris(t, f, period_in, duration_d):
    """BLS refit on TRAINING flux only, narrow grid around the filed
    period. Returns (period, t0) or None if the refit fails or lands
    outside +/- REFINE_PERIOD_TOL_FRAC of the filed period."""
    import astropy.units as u
    from astropy.timeseries import BoxLeastSquares

    t = np.asarray(t, dtype=float)
    f = np.asarray(f, dtype=float)
    ok = np.isfinite(t) & np.isfinite(f)
    t, f = t[ok], f[ok]
    if len(t) < 500 or period_in <= 0 or duration_d <= 0:
        return None
    baseline = float(t.max() - t.min())
    if baseline <= 0:
        return None
    f_lo = 1.0 / (period_in * (1.0 + REFINE_GRID_HALF_FRAC))
    f_hi = 1.0 / (period_in * (1.0 - REFINE_GRID_HALF_FRAC))
    n_freq = int(min(20000, max(2000, 5.0 * baseline * (f_hi - f_lo) + 500)))
    periods = (1.0 / np.linspace(f_lo, f_hi, n_freq)) * u.day
    durations = np.unique(np.clip(
        np.array([0.6, 1.0, 1.5]) * duration_d, 0.02, 0.35)) * u.day
    try:
        bls = BoxLeastSquares(t * u.day, f)
        res = bls.power(periods, durations)
        i = int(np.argmax(res.power))
        p_ref = float(res.period[i].value)
        t0_ref = float(res.transit_time[i].value)
    except Exception:
        return None
    if not np.isfinite(p_ref) or abs(p_ref - period_in) > (
            REFINE_PERIOD_TOL_FRAC * period_in):
        return None
    return p_ref, t0_ref


def _window_coverage(t, tmin, tmax, period, t0, duration_d):
    """Predicted windows intersecting [tmin, tmax]: how many are fully
    covered (points x median cadence >= 80% of the window — the
    persistence.py convention). Returns (n_span, n_full, med_cadence)."""
    if len(t) < 2:
        return 0, 0, None
    med_dt = float(np.median(np.diff(np.sort(t))))
    k0 = int(np.floor((tmin - duration_d - t0) / period))
    k1 = int(np.ceil((tmax + duration_d - t0) / period))
    n_span = n_full = 0
    for k in range(k0, k1 + 1):
        tc = t0 + k * period
        w0, w1 = tc - duration_d / 2.0, tc + duration_d / 2.0
        if w1 < tmin or w0 > tmax:
            continue
        n_span += 1
        wm = (t >= w0) & (t <= w1)
        coverage = wm.sum() * med_dt / duration_d if duration_d > 0 else 0.0
        if coverage >= 0.8:
            n_full += 1
    return n_span, n_full, med_dt


def _chunk_count(t_out, duration_d):
    """Out-of-transit chunks at the transit-duration timescale with
    >= 3 points — mirrors hunter._raw_fold_depth's noise bookkeeping,
    exposed here so a fold's usability is auditable."""
    if len(t_out) == 0 or duration_d <= 0:
        return 0
    cid = np.floor((t_out - t_out.min()) / duration_d).astype(np.int64)
    cnt = np.bincount(cid)
    return int((cnt >= 3).sum())


def holdout_test(tic_id, period_days, t0_days, duration_hours,
                 sector_cap=20, star_radius=1.0, max_folds=5,
                 progress_callback=None):
    """Run the holdout prediction test at a filed ephemeris.

    Returns a JSON-able dict with verdict in {HOLDOUT-PASS,
    HOLDOUT-FAIL, HOLDOUT-INSUFFICIENT-DATA} and the per-fold record.
    """
    tic_id = str(tic_id)
    P = float(period_days)
    T0 = float(t0_days)
    DUR = float(duration_hours) / 24.0

    full = hunter._run_pipeline(
        tic_id, star_radius=star_radius, bls_points=10000,
        max_sectors=sector_cap, progress_callback=progress_callback)
    ranges = persistence._sector_ranges(tic_id, sector_cap,
                                        progress_callback)
    # _sector_ranges returns one entry per PRODUCT, and a sector with
    # both 120 s and 20 s products appears twice with overlapping
    # ranges. persistence.py tolerates that (it grades each product's
    # range separately); a holdout partition may not — the same
    # photons would sit on both sides of a fold boundary and the
    # "blind" prediction would have seen them at the other cadence.
    # Merge to one (widest) range per sector before folding.
    merged = {}
    for rng in ranges:
        cur = merged.get(rng["sector"])
        if cur is None:
            merged[rng["sector"]] = dict(rng)
        else:
            cur["tmin"] = min(cur["tmin"], rng["tmin"])
            cur["tmax"] = max(cur["tmax"], rng["tmax"])
    ranges = list(merged.values())

    ft = np.asarray(full["flat_time"], dtype=float)
    ff = np.asarray(full["flat_flux"], dtype=float)
    rt = np.asarray(full["raw_time"], dtype=float)
    rf = np.asarray(full["raw_flux"], dtype=float)

    # Per-sector splits, chronological (same split as persistence.py).
    sectors = []
    for rng in sorted(ranges, key=lambda r: r["tmin"]):
        m = (ft >= rng["tmin"]) & (ft <= rng["tmax"])
        mr = (rt >= rng["tmin"]) & (rt <= rng["tmax"])
        if m.sum() < 50 or mr.sum() < 50:
            continue
        sectors.append({"sector": rng["sector"],
                        "tmin": rng["tmin"], "tmax": rng["tmax"],
                        "ft": ft[m], "ff": ff[m],
                        "rt": rt[mr], "rf": rf[mr]})
    del full
    gc.collect()

    result = {
        "tic": tic_id, "period_days": P, "t0_btjd": T0,
        "duration_hours": float(duration_hours),
        "n_sectors_total": len(sectors),
        "sectors": [s["sector"] for s in sectors],
        "criteria": {
            "min_usable_folds": MIN_USABLE_FOLDS,
            "min_total_full_events": MIN_TOTAL_FULL_EVENTS,
            "fold_signif_bar": FOLD_SIGNIF_BAR,
            "opposite_bar": OPPOSITE_BAR,
            "pass_rule": "strict majority of usable folds >= bar AND "
                         "combined >= bar AND no fold <= opposite bar",
        },
        "folds": [],
    }
    n = len(sectors)
    if n < MIN_USABLE_FOLDS:
        result["verdict"] = "HOLDOUT-INSUFFICIENT-DATA"
        result["reason"] = (f"only {n} usable sector(s); cannot form "
                            f"{MIN_USABLE_FOLDS} honest folds")
        return result

    # Fold partition: one sector per fold when sectors are few,
    # otherwise contiguous eras targeting max_folds folds.
    if n <= MAX_FOLDS_SINGLE_SECTOR:
        groups = [[i] for i in range(n)]
    else:
        per = int(math.ceil(n / float(max_folds)))
        groups = [list(range(i, min(i + per, n)))
                  for i in range(0, n, per)]

    for gi, group in enumerate(groups):
        gset = set(group)
        train_t = np.concatenate([sectors[i]["ft"]
                                  for i in range(n) if i not in gset])
        train_f = np.concatenate([sectors[i]["ff"]
                                  for i in range(n) if i not in gset])
        fold_t = np.concatenate([sectors[i]["rt"] for i in group])
        fold_f = np.concatenate([sectors[i]["rf"] for i in group])
        fold = {
            "fold": gi,
            "held_out_sectors": [sectors[i]["sector"] for i in group],
            "tmin": float(min(sectors[i]["tmin"] for i in group)),
            "tmax": float(max(sectors[i]["tmax"] for i in group)),
            "n_raw_points": int(len(fold_t)),
            "usable": False, "reason": None,
            "refined_period_days": None, "refined_t0_btjd": None,
            "events_in_span": None, "full_events": None,
            "depth_pct": None, "signif": None, "n_chunks_out": None,
        }
        ref = _refine_ephemeris(train_t, train_f, P, DUR)
        if ref is None:
            fold["reason"] = ("refinement lost: training BLS found no "
                              "peak within 1% of the filed period")
            result["folds"].append(fold)
            continue
        p_ref, t0_ref = ref
        fold["refined_period_days"] = p_ref
        fold["refined_t0_btjd"] = t0_ref

        # Window bookkeeping per member sector, summed: an era's
        # convex time hull spans the inter-sector gaps, and windows
        # "in span" of the hull but inside a gap are not predictions
        # the data could have answered.
        n_span = n_full = 0
        for i in group:
            s_span, s_full, _ = _window_coverage(
                sectors[i]["rt"], sectors[i]["tmin"], sectors[i]["tmax"],
                p_ref, t0_ref, DUR)
            n_span += s_span
            n_full += s_full
        fold["events_in_span"] = n_span
        fold["full_events"] = n_full

        # Measurability pre-check (mirrors hunter._raw_fold_depth's
        # minimums) so a returned 0.0 is never confused with a
        # measured zero.
        phase = ((fold_t - t0_ref + 0.5 * p_ref) % p_ref) - 0.5 * p_ref
        in_m = np.abs(phase) <= DUR / 2.0
        out_m = np.abs(phase) > DUR
        n_chunks = _chunk_count(fold_t[out_m], DUR)
        fold["n_chunks_out"] = n_chunks
        if n_full < 1:
            fold["reason"] = "no fully-covered predicted window held out"
        elif in_m.sum() < 20 or out_m.sum() < 50:
            fold["reason"] = ("too few held-out points "
                              f"(in {int(in_m.sum())}, out {int(out_m.sum())})")
        elif n_chunks < 2:
            fold["reason"] = "fewer than 2 out-of-transit noise chunks"
        else:
            depth_pct, signif = hunter._raw_fold_depth(
                fold_t, fold_f, p_ref, t0_ref, DUR)
            fold["depth_pct"] = float(depth_pct)
            fold["signif"] = float(signif)
            fold["sigma_pct"] = (float(depth_pct / signif)
                                 if signif not in (0.0, -0.0) else None)
            fold["usable"] = True
        result["folds"].append(fold)

    usable = [f for f in result["folds"] if f["usable"]]
    total_full = int(sum(f["full_events"] or 0 for f in usable))
    result["n_folds"] = len(result["folds"])
    result["n_usable_folds"] = len(usable)
    result["total_full_events_held_out"] = total_full

    if len(usable) < MIN_USABLE_FOLDS or total_full < MIN_TOTAL_FULL_EVENTS:
        result["verdict"] = "HOLDOUT-INSUFFICIENT-DATA"
        result["reason"] = (f"{len(usable)} usable fold(s), {total_full} "
                            "fully-covered held-out window(s); the test "
                            "could not run honestly")
        return result

    sig = np.array([f["signif"] for f in usable], dtype=float)
    dep = np.array([f["depth_pct"] for f in usable], dtype=float)
    sg = np.array([abs(f["depth_pct"] / f["signif"]) if f["signif"] != 0
                   else np.nan for f in usable], dtype=float)
    ok = np.isfinite(sg) & (sg > 0)
    comb_signif = None
    comb_depth = None
    if ok.sum() >= 1 and np.all(np.isfinite(dep[ok])):
        w = 1.0 / sg[ok] ** 2
        comb_depth = float(np.sum(w * dep[ok]) / np.sum(w))
        comb_sigma = float(1.0 / np.sqrt(np.sum(w)))
        comb_signif = comb_depth / comb_sigma if comb_sigma > 0 else None
    n_pos = int((sig >= FOLD_SIGNIF_BAR).sum())
    n_neg = int((sig <= OPPOSITE_BAR).sum())
    result.update({
        "folds_at_or_above_bar": n_pos,
        "folds_opposite": n_neg,
        "combined_depth_pct": comb_depth,
        "combined_signif": comb_signif,
    })
    if (n_pos > len(usable) / 2.0 and comb_signif is not None
            and comb_signif >= FOLD_SIGNIF_BAR and n_neg == 0):
        result["verdict"] = "HOLDOUT-PASS"
    else:
        result["verdict"] = "HOLDOUT-FAIL"
    return result


def main():
    ap = argparse.ArgumentParser(
        description="Leave-one-sector-out holdout prediction test.")
    ap.add_argument("tic")
    ap.add_argument("period_days", type=float)
    ap.add_argument("t0_btjd", type=float)
    ap.add_argument("duration_hours", type=float)
    ap.add_argument("--sector-cap", type=int, default=20)
    ap.add_argument("--radius", type=float, default=1.0,
                    help="star radius in Rsun (provenance only)")
    ap.add_argument("--max-folds", type=int, default=5)
    ap.add_argument("--out", default=None, help="write the JSON record here")
    args = ap.parse_args()

    res = holdout_test(args.tic, args.period_days, args.t0_btjd,
                       args.duration_hours, sector_cap=args.sector_cap,
                       star_radius=args.radius, max_folds=args.max_folds,
                       progress_callback=lambda m: print(f"  .. {m}",
                                                         flush=True))
    print(f"\nTIC {res['tic']}  P {res['period_days']} d  "
          f"T0 {res['t0_btjd']}  dur {res['duration_hours']} h")
    print(f"sectors: {res['n_sectors_total']}  folds: "
          f"{res.get('n_folds')}  usable: {res.get('n_usable_folds')}")
    for f in res["folds"]:
        secs = ",".join(str(s) for s in f["held_out_sectors"])
        if f["usable"]:
            print(f"  fold {f['fold']} [S{secs}] P' {f['refined_period_days']:.5f} "
                  f"windows {f['full_events']}/{f['events_in_span']} "
                  f"depth {f['depth_pct']:+.4f}%  {f['signif']:+.1f} sigma")
        else:
            print(f"  fold {f['fold']} [S{secs}] UNUSABLE — {f['reason']}")
    if res.get("combined_signif") is not None:
        print(f"combined held-out depth {res['combined_depth_pct']:+.4f}% "
              f"at {res['combined_signif']:+.1f} sigma; "
              f"folds >= 3 sigma: {res['folds_at_or_above_bar']}, "
              f"opposite: {res['folds_opposite']}")
    print(f"STAMP: {res['verdict']}"
          + (f" — {res['reason']}" if res.get("reason") else ""))
    print("NOTE: a pass proves predictive periodicity only — an "
          "eclipsing binary passes this test. It never replaces the "
          "raw-flux, shape or imaging gates.")
    if args.out:
        with open(args.out, "w") as fh:
            json.dump(res, fh, indent=2, default=str)
        print(f"JSON written to {args.out}")
    return 0 if res["verdict"] != "HOLDOUT-INSUFFICIENT-DATA" else 1


if __name__ == "__main__":
    sys.exit(main())
