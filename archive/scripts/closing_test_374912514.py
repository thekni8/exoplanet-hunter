#!/usr/bin/env python
"""Closing test for TIC 374912514 — the late-era loophole.

The full Mac Sweep A vet convicted the 18.822932 d signal as
era-confined (raw fixed-ephemeris era split over 44 DISTINCT
sectors: +0.218% <=26, +0.235% 27-59, +0.040% @ 0.6 sigma >=60).
Loophole: if the period were fractionally off, the fixed-ephemeris
fold would smear late sectors first, mimicking a switch-off. This
script settles it with a LATE-ERA-ONLY free search:

  1. Free BLS over the late-era (distinct sectors >= 60) light
     curve alone, production grid (0.5-25 d, 10,000 points) and
     production two-pass flatten; report the global best period /
     SDE and the local peak within +-0.5% of 18.822932 d.
  2. Free-phase fold at exactly P = 18.822932 d on the late era:
     depth and phase offset both free (vet hand-fold convention:
     per-event depths vs the sector's own out-of-transit mean,
     fully-covered events only, mean +- std/sqrt(n)).
  3. Control: the identical fold on the MIDDLE era (27-59), where
     the raw signal measured +0.235%; it must recover a clear
     depth near phase 0 or the late-era null is meaningless.

Sector sets are the vet's usable DISTINCT sectors (de-duplication
forensically matched to the vet's distinct-sector aggregates:
first usable product per distinct sector in collection order;
38 usable distinct sectors overall):
  late >= 60 (16): 61-69, 87, 89, 90, 93, 96, 97, 98
  mid 27-59 (11): 27-35, 37, 39
(Sectors 88, 94, 95 have products but were not usable in the vet's
raw measurement and are excluded, as are duplicate-pipeline ranges
of every sector.)

Conventions mirror hunter._run_pipeline exactly: author-filtered
search [SPOC, TESS-SPOC, QLP], _download_products, stitch with
_stitch_corrector, remove_nans, remove_outliers(5 sigma),
flatten(window_length=101), pass-1 BLS, transit-masked re-flatten
when the mask covers <= 50%, pass-2 BLS; SDE = (peak - median) /
std of the BLS power. History logging suppressed in-process;
data/hunter.db and discoveries.csv md5-guarded by the parent.

Memory discipline: eras processed sequentially, arrays freed and
gc between stages; one process throughout.
"""
import gc
import json
import sys
import time
import warnings
from pathlib import Path

import numpy as np

warnings.filterwarnings("ignore")

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
OUTDIR = BASE / "vetting_results"

import hunter  # noqa: E402
import lightkurve as lk  # noqa: E402
from astropy.timeseries import BoxLeastSquares  # noqa: E402
import astropy.units as u  # noqa: E402

hunter.log_candidate = lambda *a, **k: None  # history guard

TIC = "374912514"
RADIUS = 0.27
P_FIX = 18.82293229322932
T0 = 1334.4213516145987
DUR_H = 0.72
DUR = DUR_H / 24.0

LATE_SECTORS = [61, 62, 63, 64, 65, 66, 67, 68, 69, 87, 89, 90, 93, 96, 97, 98]
MID_SECTORS = [27, 28, 29, 30, 31, 32, 33, 34, 35, 37, 39]

PERIODS = np.linspace(0.5, 25.0, 10000)
DURATIONS = np.linspace(0.03, 0.25, 14)
SCAN_STEP_D = 0.01


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# ---------------------------------------------------------------------------
# Data: search + download once (cached), first product per distinct sector
# ---------------------------------------------------------------------------

def fetch_first_per_sector():
    def _search():
        s = lk.search_lightcurve(f"TIC {TIC}",
                                 author=["SPOC", "TESS-SPOC", "QLP"])
        if len(s) == 0:
            s = lk.search_lightcurve(f"TIC {TIC}")
        if len(s) == 0:
            raise RuntimeError(f"No mission data found for TIC {TIC}.")
        return s

    search = hunter._with_download_self_heal(_search, None)
    log(f"search: {len(search)} products")
    coll = hunter._download_products(search, TIC, None)
    by_sector = {}
    n_no_sector = 0
    for lc in coll:
        sec = lc.meta.get("SECTOR")
        if sec is None:
            n_no_sector += 1
            continue
        sec = int(sec)
        if sec not in by_sector:
            t = np.asarray(lc.time.value, dtype=float)
            t = t[np.isfinite(t)]
            by_sector[sec] = {
                "lc": lc,
                "tmin": float(t.min()), "tmax": float(t.max()),
                "author": str(lc.meta.get("AUTHOR", "?")),
                "n_points_raw": int(len(t)),
            }
    del coll
    gc.collect()
    log(f"distinct sectors downloaded: {len(by_sector)} "
        f"(no-SECTOR products skipped: {n_no_sector})")
    return by_sector


# ---------------------------------------------------------------------------
# Era curve: production stitch + two-pass flatten/BLS (mirrors _run_pipeline)
# ---------------------------------------------------------------------------

def bls_best(t, f):
    bls = BoxLeastSquares(t * u.day, f)
    res = bls.power(PERIODS * u.day, DURATIONS * u.day)
    power = np.asarray(res.power, dtype=float)
    med = float(np.median(power))
    std = float(np.std(power)) + 1e-12
    i = int(np.argmax(power))
    out = {
        "period_days": float(res.period[i].value),
        "depth": float(res.depth[i]),
        "duration_days": float(res.duration[i].value),
        "t0_days": float(res.transit_time[i].value),
        "sde": float((power[i] - med) / std),
        "_power": power, "_med": med, "_std": std,
    }
    return out


def bls_local_peak(bls_out, p_center, frac=0.005):
    power = bls_out["_power"]
    m = (PERIODS >= p_center * (1 - frac)) & (PERIODS <= p_center * (1 + frac))
    idx = np.where(m)[0]
    j = idx[int(np.argmax(power[idx]))]
    return {"period_days": float(PERIODS[j]),
            "sde": float((power[j] - bls_out["_med"]) / bls_out["_std"]),
            "depth": None, "n_grid_in_window": int(len(idx))}


def build_era(by_sector, sector_list):
    """Stitch the era's first-per-sector products and run the
    production two-pass flatten+BLS. Returns (t, f, info) with the
    pass-2 flattened curve and per-sector time ranges for folds."""
    lcs = [by_sector[s]["lc"] for s in sector_list]
    ranges = {s: (by_sector[s]["tmin"], by_sector[s]["tmax"])
              for s in sector_list}
    authors = {s: by_sector[s]["author"] for s in sector_list}
    coll = lk.LightCurveCollection(lcs)
    lc_raw = (coll.stitch(corrector_func=hunter._stitch_corrector)
              .remove_nans().remove_outliers(sigma=5.0))
    del coll
    gc.collect()

    lc_flat, _tr = lc_raw.flatten(window_length=101, return_trend=True)
    t = np.asarray(lc_flat.time.value, dtype=float)
    f = np.asarray(lc_flat.flux.value, dtype=float)
    del lc_flat, _tr
    b1 = bls_best(t, f)
    pass1 = {k: v for k, v in b1.items() if not k.startswith("_")}
    pass1["local_peak_near_pfix"] = bls_local_peak(b1, P_FIX)
    log(f"  pass1 BLS: P={b1['period_days']:.5f} SDE={b1['sde']:.2f} "
        f"depth={b1['depth']*100:.3f}% dur={b1['duration_days']*24:.2f}h | "
        f"near {P_FIX:.4f}: P={pass1['local_peak_near_pfix']['period_days']:.5f} "
        f"SDE={pass1['local_peak_near_pfix']['sde']:.2f}")
    del b1
    gc.collect()

    ph = ((t - pass1["t0_days"] + 0.5 * pass1["period_days"])
          % pass1["period_days"]) - 0.5 * pass1["period_days"]
    mask = np.abs(ph) <= (pass1["duration_days"] / 2.0 + 0.02)
    del ph
    pass2 = None
    if mask.mean() <= 0.50:
        lc_flat2, _tr2 = lc_raw.flatten(window_length=101,
                                        return_trend=True, mask=mask)
        t = np.asarray(lc_flat2.time.value, dtype=float)
        f = np.asarray(lc_flat2.flux.value, dtype=float)
        del lc_flat2, _tr2
        b2 = bls_best(t, f)
        pass2 = {k: v for k, v in b2.items() if not k.startswith("_")}
        pass2["local_peak_near_pfix"] = bls_local_peak(b2, P_FIX)
        log(f"  pass2 BLS: P={b2['period_days']:.5f} SDE={b2['sde']:.2f} "
            f"depth={b2['depth']*100:.3f}% dur={b2['duration_days']*24:.2f}h | "
            f"near {P_FIX:.4f}: P={pass2['local_peak_near_pfix']['period_days']:.5f} "
            f"SDE={pass2['local_peak_near_pfix']['sde']:.2f}")
        del b2
    else:
        log(f"  pass2 skipped (mask fraction {mask.mean():.2f} > 0.50)")
    del mask, lc_raw
    gc.collect()
    info = {"sectors": sector_list, "authors_first_product": authors,
            "ranges": {str(s): list(ranges[s]) for s in sector_list},
            "n_points_final": int(len(t)),
            "bls_pass1": pass1, "bls_pass2": pass2}
    return t, f, ranges, info


# ---------------------------------------------------------------------------
# Free-phase fold at fixed P (vet hand-fold convention, per sector)
# ---------------------------------------------------------------------------

def sector_slices(t, f, ranges, sector_list):
    out = []
    for s in sector_list:
        lo, hi = ranges[s]
        m = (t >= lo) & (t <= hi)
        ts, fs = t[m], f[m]
        if len(ts) < 50:
            continue
        med_dt = float(np.median(np.diff(np.sort(ts))))
        out.append((s, ts, fs, med_dt))
    return out


def fold_at_offset(slices, phi):
    """Event depths at phase offset phi (days, added to T0).
    Returns (depth_pct, se_pct, n_events) or (None, None, 0)."""
    depths = []
    for _s, ts, fs, med_dt in slices:
        rel = ts - (T0 + phi)
        eid = np.round(rel / P_FIX)
        in_mask = np.abs(rel - eid * P_FIX) <= DUR / 2.0
        if not in_mask.any() or in_mask.all():
            continue
        out_mean = float(np.mean(fs[~in_mask]))
        ids = np.unique(eid[in_mask])
        for e in ids:
            wm = in_mask & (eid == e)
            coverage = wm.sum() * med_dt / DUR if DUR > 0 else 0.0
            if coverage >= 0.8:
                depths.append((out_mean - float(np.mean(fs[wm]))) * 100.0)
    if len(depths) < 2:
        return None, None, len(depths)
    d = np.asarray(depths, dtype=float)
    return float(np.mean(d)), float(np.std(d, ddof=1) / np.sqrt(len(d))), len(d)


def fold_scan(slices):
    offsets = np.round(np.arange(0.0, P_FIX, SCAN_STEP_D), 10)
    rows = []
    for phi in offsets:
        dep, se, n = fold_at_offset(slices, float(phi))
        rows.append({"phi_days": float(phi),
                     "depth_pct": dep, "se_pct": se, "n_events": n,
                     "signif": (dep / se if (dep is not None and se) else None)})
    valid = [r for r in rows if r["depth_pct"] is not None]
    at0 = next(r for r in rows if abs(r["phi_days"]) < 1e-9)
    best_sig = max(valid, key=lambda r: r["signif"])
    best_depth = max(valid, key=lambda r: r["depth_pct"])
    return {"step_days": SCAN_STEP_D, "n_offsets": len(rows),
            "at_phi0": at0, "best_by_signif": best_sig,
            "best_by_depth": best_depth, "scan": rows}


# ---------------------------------------------------------------------------

def main():
    t_start = time.time()
    results = {"tic": TIC, "test": "late-era-only closing test",
               "ephemeris_fixed": {"period_days": P_FIX, "t0_btjd": T0,
                                   "duration_hours": DUR_H},
               "method_note": "Production stitch/flatten conventions "
                              "(hunter._run_pipeline mirror); first product "
                              "per distinct sector in collection order; "
                              "sectors = vet's usable distinct sets."}
    by_sector = fetch_first_per_sector()
    results["distinct_sectors_available"] = sorted(by_sector.keys())

    for era_name, sector_list in (("late_ge60", LATE_SECTORS),
                                  ("middle_27_59", MID_SECTORS)):
        log(f"=== era {era_name}: {len(sector_list)} sectors ===")
        t, f, ranges, info = build_era(by_sector, sector_list)
        slices = sector_slices(t, f, ranges, sector_list)
        info["n_sector_slices_used"] = len(slices)
        log(f"  fold scan over {len(slices)} sector slices, "
            f"{info['n_points_final']} points")
        scan = fold_scan(slices)
        info["fold_scan_summary"] = {k: scan[k] for k in
                                     ("step_days", "n_offsets", "at_phi0",
                                      "best_by_signif", "best_by_depth")}
        results[era_name] = info
        (OUTDIR / f"{TIC}_latefold_scan_{era_name}.json").write_text(
            json.dumps(scan["scan"], indent=1, default=str))
        log(f"  fold phi0: depth={scan['at_phi0']['depth_pct']} "
            f"se={scan['at_phi0']['se_pct']} n={scan['at_phi0']['n_events']} | "
            f"best-sig phi={scan['best_by_signif']['phi_days']:.2f} d "
            f"depth={scan['best_by_signif']['depth_pct']:.3f}% "
            f"+- {scan['best_by_signif']['se_pct']:.3f}% "
            f"({scan['best_by_signif']['signif']:.1f} sigma, "
            f"n={scan['best_by_signif']['n_events']})")
        del t, f, slices, scan
        gc.collect()

    results["elapsed_s"] = round(time.time() - t_start, 1)
    (OUTDIR / f"{TIC}_closing_test_stage.json").write_text(
        json.dumps(results, indent=2, default=str))
    log(f"DONE in {results['elapsed_s']}s -> "
        f"vetting_results/{TIC}_closing_test_stage.json")


if __name__ == "__main__":
    main()
