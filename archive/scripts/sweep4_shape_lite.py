#!/usr/bin/env python
"""Shape-lite for TIC 277313805: fold-shape on the CAP-20 stitch (the
sweep's own data treatment), plus a repaired Lomb-Scargle on the same
curve. Merges results into vetting_results/277313805_foldshape.json
under 'shape_cap20_stitch' / 'lomb_scargle_cap20_stitch'.
"""
import json
import math
import sys
import warnings
from pathlib import Path

import numpy as np

warnings.filterwarnings("ignore")
BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
import hunter  # noqa: E402
from sweep4_shape import binned_fold, fourier_amps, duty_cycle  # noqa: E402

tic = "277313805"
out_path = BASE / "vetting_results" / f"{tic}_foldshape.json"
out = json.loads(out_path.read_text())

full = hunter._run_pipeline(tic, star_radius=0.26, bls_points=10000,
                            max_sectors=20, progress_callback=None)
ft = np.asarray(full["flat_time"], dtype=float)
ff = np.asarray(full["flat_flux"], dtype=float)
P, T0 = float(full["Period"]), float(full["T0"])
ok = np.isfinite(ft) & np.isfinite(ff)
ft, ff = ft[ok], ff[ok]

fold_p = binned_fold(ft, ff, P, T0)
fold_2p = binned_fold(ft, ff, 2 * P, T0)
fa = fourier_amps(ft, ff, P)
depth_est = 1.0 - min(fold_p["flux"])
out["shape_cap20_stitch"] = {
    "period_days": P, "t0_days": T0,
    "pipeline_depth_frac": float(full["Depth"]),
    "pipeline_duration_hours": float(full["Duration_Days"]) * 24.0,
    "fold_at_P": fold_p, "fold_at_2P": fold_2p, "fourier": fa,
    "fold_min_flux": float(min(fold_p["flux"])),
    "fold_max_flux": float(max(fold_p["flux"])),
    "duty_cycle_below_half_depth": duty_cycle(fold_p, depth_est),
    "fold_2P_min_flux": float(min(fold_2p["flux"])),
    "fold_2P_max_flux": float(max(fold_2p["flux"])),
}
print(f"cap20 stitch: A1={fa['a1_frac'] * 100:.3f}% A2={fa['a2_frac'] * 100:.3f}% "
      f"duty={out['shape_cap20_stitch']['duty_cycle_below_half_depth']:.3f} "
      f"fold range {min(fold_p['flux']):.4f}..{max(fold_p['flux']):.4f}")

# repaired Lomb-Scargle (median-subtracted, finite-only)
from astropy.timeseries import LombScargle
y = ff - np.median(ff)
ls = LombScargle(ft, y, normalization="standard")
freq, power = ls.autopower(minimum_frequency=1 / 5.0,
                           maximum_frequency=1 / 0.1,
                           samples_per_peak=10)
periods = 1 / freq
order = np.argsort(power)[::-1]
peaks, used = [], []
for i in order:
    p = float(periods[i])
    if any(abs(p - u) / u < 0.01 for u in used):
        continue
    used.append(p)
    peaks.append({"period_days": p, "power": float(power[i])})
    if len(peaks) >= 8:
        break
out["lomb_scargle_cap20_stitch"] = peaks
print("LS cap20:", [(round(p["period_days"], 4), round(p["power"], 3)) for p in peaks[:5]])
out_path.write_text(json.dumps(out, indent=2, default=str))
print("merged into", out_path.name)
