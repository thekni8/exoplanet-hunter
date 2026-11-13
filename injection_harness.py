#!/usr/bin/env python
"""Injection-recovery (completeness) harness for Exoplanet Hunter.

MEASUREMENT ONLY — imports hunter.py read-only; never edits production
code, never calls the production entry points that render PNGs or log to
discoveries.csv (those side effects live in hunter._run_pipeline, which
this harness deliberately does NOT call).

Method
------
Substrate: for each sample star, the healed production fetch path
(hunter._with_download_self_heal + hunter._download_products, first 2
sectors — the Scanner configuration) stitched with the production
corrector (per-sector normalize) and NaN-cleaned. This is exactly
hunter._fetch_stitched's construction minus its final remove_outliers
step, which the harness instead applies AFTER injection — mirroring
production's ordering, where the (real) signal is already in the data
when the outlier clip runs.

Pipeline (mirrored step-for-step from hunter._run_pipeline, Scanner
settings): remove_outliers(sigma=5) -> flatten(window_length=101) ->
BLS (periods linspace(0.5, 25, 10000), durations linspace(0.03, 0.25,
14), production SDE formula copied verbatim from the _bls_best closure)
-> transit-masked re-flatten + identical second BLS when the pass-1
mask covers <= 50% of the curve. All reported metrics come from pass 2
when it runs, exactly as in production.

Injection: trapezoid transits (flat bottom 70% of duration, linear
ingress/egress 15% of duration each side), duration_hours =
2.0 * P_days^(1/3), epochs drawn from numpy default_rng(SEED) in plan
order. Plan is fixed up front; nothing is re-drawn after seeing results.
"""

import argparse
import json
import os
import sys
import time

import numpy as np

PROJECT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT)

SUB_DIR = "/tmp/injection_substrate"
RESULTS_JSON = os.path.join(PROJECT, "injection_results.json")
PLAN_JSON = "/tmp/injection_plan.json"
SEED = 20261103

# Quiet-star sample (all measured 0 hits by the app itself):
# - first five: sweep job bf3e0cb5938a473f (RA 345.992 / Dec -22.568,
#   "Sweep complete: 0 hit(s) ... out of 5 target(s)")
# - last three: first three targets of Stage-4 scan job fbadf15236df4533
#   (RA 124.456 / Dec -67.568, "0 hit(s) ... out of 20 target(s)")
STARS = [
    {"tic": "204317981", "radius": 1.30, "tmag": 15.4, "patch": "RA 345.992 Dec -22.568"},
    {"tic": "204316124", "radius": 0.82, "tmag": 14.8, "patch": "RA 345.992 Dec -22.568"},
    {"tic": "204317973", "radius": 0.73, "tmag": 14.0, "patch": "RA 345.992 Dec -22.568"},
    {"tic": "204316103", "radius": 0.71, "tmag": 15.4, "patch": "RA 345.992 Dec -22.568"},
    {"tic": "204317967", "radius": 1.37, "tmag": 15.1, "patch": "RA 345.992 Dec -22.568"},
    {"tic": "307164903", "radius": 0.88, "tmag": 15.1, "patch": "RA 124.456 Dec -67.568"},
    {"tic": "307164915", "radius": 1.20, "tmag": 15.1, "patch": "RA 124.456 Dec -67.568"},
    {"tic": "307164924", "radius": 1.40, "tmag": 15.1, "patch": "RA 124.456 Dec -67.568"},
]
STAR_BY_TIC = {s["tic"]: s for s in STARS}

DEPTHS_PCT = [1.2, 0.8, 0.5, 0.35, 0.25, 0.15]
PERIODS_D = [1.5, 4.0, 8.0, 13.0]
REPS = 2
SDE_THRESHOLD = 8.5  # the app's discovery threshold (discoveries logged >= 8.5)
BLS_POINTS = 10000   # Scanner sweep setting
MIN_P, MAX_P = 0.5, 25.0
DETREND_WINDOW = 101
MAX_SECTORS = 2      # Scanner sector cap


# ---------------------------------------------------------------------------
# Plan (fixed up front, seeded)
# ---------------------------------------------------------------------------

def build_plan():
    rng = np.random.default_rng(SEED)
    trials = []
    k = 0
    for d in DEPTHS_PCT:
        for p in PERIODS_D:
            for _rep in range(REPS):
                star = STARS[k % len(STARS)]
                trials.append({
                    "kind": "inject",
                    "trial_index": k,
                    "star_tic": star["tic"],
                    "depth_pct": d,
                    "period_d": p,
                    "epoch_offset_d": float(rng.uniform(0.0, p)),
                })
                k += 1
    for star in STARS:
        trials.append({
            "kind": "control",
            "trial_index": k,
            "star_tic": star["tic"],
            "depth_pct": 0.0,
            "period_d": None,
            "epoch_offset_d": None,
        })
        k += 1
    return trials


# ---------------------------------------------------------------------------
# Substrate fetch — production healed path, Scanner configuration
# ---------------------------------------------------------------------------

def fetch_substrate(tic):
    import hunter as H
    import lightkurve as lk

    def _search():
        # Verbatim copy of the search step inside hunter._fetch_stitched
        # (its _emit progress line is cosmetic and omitted here).
        search = lk.search_lightcurve(f"TIC {tic}", author=["SPOC", "TESS-SPOC", "QLP"])
        if len(search) == 0:
            search = lk.search_lightcurve(f"TIC {tic}")
        if len(search) == 0:
            raise RuntimeError(f"No mission data found for TIC {tic}.")
        return search

    search = H._with_download_self_heal(_search, None)
    sectors_to_fetch = search[:MAX_SECTORS]
    collection = H._download_products(sectors_to_fetch, tic, None)
    n_products = len(collection)
    # Identical stitch to hunter._fetch_stitched / _run_pipeline, stopping
    # after remove_nans(): the remove_outliers step is applied later, after
    # injection, to mirror production ordering.
    lc = collection.stitch(corrector_func=lambda x: x.normalize()).remove_nans()
    t = np.asarray(lc.time.value, dtype=float)
    f = np.asarray(lc.flux.value, dtype=float)
    if lc.flux_err is not None:
        ferr = np.asarray(lc.flux_err.value, dtype=float)
    else:
        ferr = np.full_like(f, np.nan)
    del collection, lc
    return t, f, ferr, n_products


def substrate_path(tic):
    return os.path.join(SUB_DIR, f"substrate_{tic}.npz")


def cmd_fetch():
    os.makedirs(SUB_DIR, exist_ok=True)
    meta = {}
    for star in STARS:
        tic = star["tic"]
        path = substrate_path(tic)
        if os.path.exists(path):
            d = np.load(path)
            meta[tic] = json.loads(str(d["meta_json"]))
            print(f"[fetch] TIC {tic}: cached ({meta[tic]['n_points']} pts)", flush=True)
            continue
        t0 = time.time()
        t, f, ferr, n_products = fetch_substrate(tic)
        cadence_min = float(np.median(np.diff(t)) * 1440.0) if len(t) > 1 else None
        m = {
            "tic": tic, "radius": star["radius"], "tmag": star["tmag"],
            "patch": star["patch"], "n_products": int(n_products),
            "n_points": int(len(t)),
            "t_start": float(t.min()), "t_end": float(t.max()),
            "baseline_d": float(t.max() - t.min()),
            "median_cadence_min": cadence_min,
            "flux_std_pct": float(np.std(f) * 100.0),
            "fetch_wall_s": time.time() - t0,
        }
        np.savez_compressed(path, t=t, f=f, ferr=ferr,
                            meta_json=json.dumps(m))
        meta[tic] = m
        print(f"[fetch] TIC {tic}: {n_products} product(s), {len(t)} pts, "
              f"cadence {cadence_min:.1f} min, baseline {m['baseline_d']:.1f} d "
              f"({m['fetch_wall_s']:.0f}s)", flush=True)
    with open("/tmp/injection_substrate_meta.json", "w") as fh:
        json.dump(meta, fh, indent=2)
    print("[fetch] done", flush=True)


def load_substrate(tic):
    d = np.load(substrate_path(tic))
    return d["t"], d["f"], d["ferr"], json.loads(str(d["meta_json"]))


# ---------------------------------------------------------------------------
# Injection
# ---------------------------------------------------------------------------

def inject_transit(t, f, depth_frac, period_d, epoch_abs):
    """Trapezoid transit train multiplied into flux f.

    duration_hours = 2.0 * P_days^(1/3); flat bottom spans the central
    70% of the duration, linear ingress/egress take 15% each side.
    Returns (injected_flux, duration_days).
    """
    duration_d = (2.0 * period_d ** (1.0 / 3.0)) / 24.0
    phase = ((t - epoch_abs + 0.5 * period_d) % period_d) - 0.5 * period_d
    a = np.abs(phase)
    half_tot = duration_d / 2.0
    half_flat = 0.7 * half_tot
    mult = np.ones_like(f)
    in_flat = a <= half_flat
    in_ramp = (a > half_flat) & (a < half_tot)
    mult[in_flat] = 1.0 - depth_frac
    mult[in_ramp] = 1.0 - depth_frac * (half_tot - a[in_ramp]) / (half_tot - half_flat)
    return f * mult, duration_d


# ---------------------------------------------------------------------------
# Production pipeline, mirrored on in-memory arrays
# (hunter._run_pipeline minus its PNG-render and discoveries.csv side
# effects; BLS grid + SDE formula copied verbatim from its _bls_best
# closure; Scanner settings: bls_points=10000, sectors<=2, window=101)
# ---------------------------------------------------------------------------

def run_pipeline_mirror(t, f, ferr):
    import astropy.units as u
    import lightkurve as lk
    from astropy.timeseries import BoxLeastSquares

    lc_raw = lk.LightCurve(time=t, flux=f, flux_err=ferr).remove_outliers(sigma=5.0)

    periods = np.linspace(MIN_P, MAX_P, BLS_POINTS) * u.day
    durations = np.linspace(0.03, 0.25, 14) * u.day

    def _bls_best(tt, ff):
        _bls = BoxLeastSquares(tt * u.day, ff)
        _res = _bls.power(periods, durations)
        _i = int(np.argmax(_res.power))
        return (_res, float(_res.period[_i].value), float(_res.depth[_i]),
                float(_res.duration[_i].value),
                float(_res.transit_time[_i].value),
                float((_res.power[_i] - np.median(_res.power))
                      / (np.std(_res.power) + 1e-12)))

    lc_flat, _trend = lc_raw.flatten(window_length=DETREND_WINDOW, return_trend=True)
    tt = np.asarray(lc_flat.time.value, dtype=float)
    ff = np.asarray(lc_flat.flux.value, dtype=float)
    _res, best_period, best_depth, best_duration, t0, sde = _bls_best(tt, ff)

    pass2_ran = False
    _phase1 = ((tt - t0 + 0.5 * best_period) % best_period) - 0.5 * best_period
    _transit_mask = np.abs(_phase1) <= (best_duration / 2.0 + 0.02)
    if _transit_mask.mean() <= 0.50:
        lc_flat, _trend = lc_raw.flatten(window_length=DETREND_WINDOW,
                                         return_trend=True, mask=_transit_mask)
        tt = np.asarray(lc_flat.time.value, dtype=float)
        ff = np.asarray(lc_flat.flux.value, dtype=float)
        _res, best_period, best_depth, best_duration, t0, sde = _bls_best(tt, ff)
        pass2_ran = True

    return {
        "period_d": best_period,
        "depth_frac": best_depth,
        "duration_d": best_duration,
        "t0": t0,
        "sde": sde,
        "pass2_ran": pass2_ran,
        "n_points_cleaned": int(len(lc_raw)),
    }


# ---------------------------------------------------------------------------
# Trial execution + scoring
# ---------------------------------------------------------------------------

def run_trial(trial):
    tic = trial["star_tic"]
    star = STAR_BY_TIC[tic]
    t, f, ferr, meta = load_substrate(tic)
    wall0 = time.time()
    rec = {
        "trial_index": trial["trial_index"],
        "kind": trial["kind"],
        "star_tic": tic,
        "star_radius_rsun": star["radius"],
        "star_tmag": star["tmag"],
        "star_n_points": meta["n_points"],
        "star_n_products": meta["n_products"],
        "star_cadence_min": meta["median_cadence_min"],
        "injected_depth_pct": trial["depth_pct"],
        "injected_period_d": trial["period_d"],
        "injected_duration_h": None,
        "injected_epoch_btjd": None,
        "recovered": False,
        "aliased": False,
        "false_alarm": False,
        "recovered_period_d": None,
        "recovered_depth_pct": None,
        "depth_error_pct": None,
        "sde": None,
        "pass2_ran": None,
    }
    if trial["kind"] == "inject":
        epoch_abs = float(t.min()) + trial["epoch_offset_d"]
        depth_frac = trial["depth_pct"] / 100.0
        f_inj, duration_d = inject_transit(t, f, depth_frac,
                                           trial["period_d"], epoch_abs)
        rec["injected_duration_h"] = duration_d * 24.0
        rec["injected_epoch_btjd"] = epoch_abs
    else:
        f_inj = f
    out = run_pipeline_mirror(t, f_inj, ferr)
    rec.update({
        "recovered_period_d": out["period_d"],
        "recovered_depth_pct": out["depth_frac"] * 100.0,
        "sde": out["sde"],
        "pass2_ran": out["pass2_ran"],
        "n_points_cleaned": out["n_points_cleaned"],
        "wall_s": time.time() - wall0,
    })
    if trial["kind"] == "inject":
        p_inj = trial["period_d"]
        p_rec = out["period_d"]
        if out["sde"] >= SDE_THRESHOLD:
            if abs(p_rec - p_inj) / p_inj <= 0.01:
                rec["recovered"] = True
            elif (abs(p_rec - p_inj / 2.0) / (p_inj / 2.0) <= 0.01
                  or abs(p_rec - 2.0 * p_inj) / (2.0 * p_inj) <= 0.01):
                rec["aliased"] = True
        rec["depth_error_pct"] = (
            (out["depth_frac"] - trial["depth_pct"] / 100.0)
            / (trial["depth_pct"] / 100.0) * 100.0)
    else:
        rec["false_alarm"] = bool(out["sde"] >= SDE_THRESHOLD)
    return rec


def _worker(trial):
    rec = run_trial(trial)
    tag = "CTRL" if rec["kind"] == "control" else \
        f"d={rec['injected_depth_pct']:.2f}% P={rec['injected_period_d']}d"
    print(f"[trial {rec['trial_index']:2d}] TIC {rec['star_tic']} {tag}: "
          f"SDE={rec['sde']:.1f} Prec={rec['recovered_period_d']:.4f}d "
          f"rec={rec['recovered']} alias={rec['aliased']} "
          f"fa={rec['false_alarm']} ({rec['wall_s']:.0f}s)", flush=True)
    return rec


def cmd_run():
    from multiprocessing import Pool
    plan = build_plan()
    with open(PLAN_JSON, "w") as fh:
        json.dump({"seed": SEED, "trials": plan}, fh, indent=2)
    print(f"[run] {len(plan)} trials, seed {SEED}", flush=True)
    with Pool(processes=2) as pool:
        records = pool.map(_worker, plan)
    records.sort(key=lambda r: r["trial_index"])
    payload = {
        "seed": SEED,
        "generated_for": "Exoplanet Hunter injection-recovery test",
        "stars": STARS,
        "settings": {
            "bls_points": BLS_POINTS, "min_p": MIN_P, "max_p": MAX_P,
            "detrend_window": DETREND_WINDOW, "max_sectors": MAX_SECTORS,
            "sde_threshold": SDE_THRESHOLD,
        },
        "trials": records,
    }
    with open(RESULTS_JSON, "w") as fh:
        json.dump(payload, fh, indent=2)
    n_rec = sum(r["recovered"] for r in records)
    n_alias = sum(r["aliased"] for r in records)
    n_fa = sum(r["false_alarm"] for r in records)
    print(f"[run] done: recovered {n_rec}/48, aliased {n_alias}, "
          f"control false alarms {n_fa}/8", flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["fetch", "run", "trial"])
    ap.add_argument("--index", type=int, default=0)
    args = ap.parse_args()
    if args.mode == "fetch":
        cmd_fetch()
    elif args.mode == "run":
        cmd_run()
    else:
        plan = build_plan()
        print(json.dumps(_worker(plan[args.index]), indent=2))
