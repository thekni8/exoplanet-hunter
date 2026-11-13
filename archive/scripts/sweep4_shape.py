#!/usr/bin/env python
"""Fold-shape diagnostic for TIC 277313805 (sweep-4 priority 1).

Usage: sweep4_shape.py TIC RADIUS MASS_MSUN P_REF T0_REF DUR_H_REF

Runs the production pipeline twice (cap 20 = the sweep configuration,
and uncapped = all sectors), capturing progress lines to settle whether
the depth-refinement pass ran, then characterizes the folded signal's
SHAPE on the uncapped flattened curve: Lomb-Scargle peaks, Fourier
amplitudes at the fold period and its first harmonic, binned folds at
P and 2P, duty cycle, and the physical maximum transit duration for
the star (Kepler + TIC mass) vs the BLS-fitted duration.
Writes vetting_results/{tic}_foldshape.json.
"""
import json
import math
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


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def binned_fold(t, f, period, t0, nbins=60):
    ph = ((t - t0) % period) / period  # 0..1, transit centred near 0/1
    ph = np.where(ph > 0.5, ph - 1.0, ph)  # centre at 0
    idx = np.clip(((ph + 0.5) * nbins).astype(int), 0, nbins - 1)
    centres, means, sems, counts = [], [], [], []
    for b in range(nbins):
        m = idx == b
        if m.sum() == 0:
            continue
        centres.append(float(np.mean(ph[m])))
        means.append(float(np.mean(f[m])))
        sems.append(float(np.std(f[m], ddof=1) / math.sqrt(m.sum())) if m.sum() > 1 else 0.0)
        counts.append(int(m.sum()))
    return {"phase": centres, "flux": means, "sem": sems, "counts": counts}


def fourier_amps(t, f, period):
    """Least-squares sinusoid amplitudes (fraction) at 1/P and 2/P."""
    w = 2 * np.pi / period
    X = np.column_stack([np.ones_like(t),
                         np.cos(w * t), np.sin(w * t),
                         np.cos(2 * w * t), np.sin(2 * w * t)])
    coef, *_ = np.linalg.lstsq(X, f, rcond=None)
    resid = f - X @ coef
    dof = max(1, len(t) - 5)
    s2 = float(np.sum(resid ** 2) / dof)
    cov = s2 * np.linalg.inv(X.T @ X)
    a1 = math.hypot(coef[1], coef[2])
    a2 = math.hypot(coef[3], coef[4])
    e1 = math.sqrt(max(cov[1, 1] + cov[2, 2], 0) / 2)
    e2 = math.sqrt(max(cov[3, 3] + cov[4, 4], 0) / 2)
    return {"a1_frac": a1, "a1_sigma": e1, "a2_frac": a2, "a2_sigma": e2,
            "mean_level": float(coef[0])}


def duty_cycle(fold, depth_frac):
    """Fraction of phase bins sitting below (baseline - depth/2)."""
    fl = np.array(fold["flux"])
    base = np.median(fl)
    if depth_frac <= 0:
        return None
    return float(np.mean(fl < base - 0.5 * depth_frac))


def main():
    tic, radius, mass = sys.argv[1], float(sys.argv[2]), float(sys.argv[3])
    p_ref, t0_ref, dur_h_ref = float(sys.argv[4]), float(sys.argv[5]), float(sys.argv[6])
    out = {"tic": tic, "star_radius_rsun": radius, "star_mass_msun_tic": mass,
           "reference_ephemeris_cap20": {"period_days": p_ref, "t0_days": t0_ref,
                                         "duration_hours": dur_h_ref}}
    out_path = OUTDIR / f"{tic}_foldshape.json"

    def save():
        out_path.write_text(json.dumps(out, indent=2, default=str))

    # --- physical maximum transit duration (central transit, Rp << R*) ---
    G = 6.67430e-11
    msun, rsun = 1.98847e30, 6.957e8
    P_s = p_ref * 86400.0
    a_m = (G * mass * msun * P_s ** 2 / (4 * math.pi ** 2)) ** (1 / 3)
    r_m = radius * rsun
    tmax_h = (P_s / math.pi) * math.asin(min(1.0, r_m / a_m)) / 3600.0
    out["physical_max_transit_duration_hours"] = tmax_h
    out["semimajor_axis_over_rstar"] = a_m / r_m
    log(f"physical max transit duration: {tmax_h:.2f} h (a/R* = {a_m / r_m:.1f}) "
        f"vs BLS duration {dur_h_ref:.2f} h")
    save()

    # --- pipeline runs with progress capture (refinement-pass evidence) ---
    for label, cap in (("cap20", 20), ("uncapped", None)):
        lines = []
        log(f"pipeline run ({label}) start")
        full = hunter._run_pipeline(
            tic, star_radius=radius, bls_points=10000, max_sectors=cap,
            progress_callback=lambda m: lines.append(m))
        out[f"pipeline_{label}"] = {
            "period_days": float(full["Period"]), "sde": float(full["SDE"]),
            "depth_frac": float(full["Depth"]),
            "duration_hours": float(full["Duration_Days"]) * 24.0,
            "t0_days": float(full["T0"]),
            "sectors_analyzed": int(full["Sectors_Analyzed"]),
            "total_points": int(full["Total_Points"]),
            "refining_depth_line_present": any("Refining depth" in ln for ln in lines),
            "progress_lines": lines,
        }
        # pass-1 mask fraction implied IF the reported duration were the
        # pass-1 duration: mask = |phase| <= dur/2 + 0.02 d over one period
        dur_d = float(full["Duration_Days"])
        out[f"pipeline_{label}"]["mask_fraction_if_pass1_duration"] = (
            (dur_d + 0.04) / float(full["Period"]))
        log(f"({label}) P={full['Period']:.5f} SDE={full['SDE']:.1f} "
            f"dur={dur_d * 24:.2f}h refining_line="
            f"{out[f'pipeline_{label}']['refining_depth_line_present']}")
        if label == "uncapped":
            ft = np.asarray(full["flat_time"], dtype=float)
            ff = np.asarray(full["flat_flux"], dtype=float)
        save()

    # --- Lomb-Scargle on the uncapped flattened curve ---
    from astropy.timeseries import LombScargle
    log("Lomb-Scargle start")
    ls = LombScargle(ft, ff, normalization="standard")
    freq, power = ls.autopower(minimum_frequency=1 / 5.0,
                               maximum_frequency=1 / 0.1,
                               samples_per_peak=20)
    periods = 1 / freq
    order = np.argsort(power)[::-1]
    peaks = []
    used = []
    for i in order:
        p = float(periods[i])
        if any(abs(p - u) / u < 0.01 for u in used):
            continue
        used.append(p)
        peaks.append({"period_days": p, "power": float(power[i])})
        if len(peaks) >= 8:
            break
    out["lomb_scargle_top_peaks"] = peaks
    log(f"LS top peaks: {[(round(p['period_days'], 4), round(p['power'], 3)) for p in peaks[:4]]}")
    save()

    # --- folds + shape at the cap-20 reference ephemeris and at the
    #     uncapped pipeline's own period ---
    for tag, (pp, tt) in {
        "at_cap20_ephemeris": (p_ref, t0_ref),
        "at_uncapped_ephemeris": (out["pipeline_uncapped"]["period_days"],
                                  out["pipeline_uncapped"]["t0_days"]),
    }.items():
        fold_p = binned_fold(ft, ff, pp, tt)
        fold_2p = binned_fold(ft, ff, 2 * pp, tt)
        fa = fourier_amps(ft, ff, pp)
        depth_est = 1.0 - min(fold_p["flux"])
        out[f"shape_{tag}"] = {
            "period_days": pp,
            "fold_at_P": fold_p, "fold_at_2P": fold_2p,
            "fourier": fa,
            "fold_min_flux": float(min(fold_p["flux"])),
            "fold_max_flux": float(max(fold_p["flux"])),
            "duty_cycle_below_half_depth": duty_cycle(fold_p, depth_est),
            "fold_2P_min_flux": float(min(fold_2p["flux"])),
            "fold_2P_max_flux": float(max(fold_2p["flux"])),
        }
        log(f"shape {tag}: A1={fa['a1_frac'] * 100:.3f}% A2={fa['a2_frac'] * 100:.3f}% "
            f"duty={out[f'shape_{tag}']['duty_cycle_below_half_depth']}")
        save()
    log("SHAPE DONE")


if __name__ == "__main__":
    main()
