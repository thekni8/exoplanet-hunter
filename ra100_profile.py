#!/usr/bin/env python
"""RA100 vet, fold-profile arbitration for TIC 167367406: binned
median profiles of the RAW curve folded at 2P and at P (ground truth
behind the Q-S statistics), machine-window medians recomputed on
this fold, and phased sine fits at P and 2P (eclipses masked)."""
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

hunter.log_candidate = lambda *a, **k: None

TIC = "167367406"
P = 0.6519151915191519
P2 = 2.0 * P
T0 = 2144.665741058755
DUR = 2.376 / 24.0


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def binned_profile(t, f, period, nbins=25):
    ph = ((t - T0) % period) / period
    rows = []
    for i in range(nbins):
        lo, hi = i / nbins, (i + 1) / nbins
        m = (ph >= lo) & (ph < hi)
        if m.sum() > 10:
            rows.append({"phase_lo": lo, "phase_hi": hi,
                         "median": float(np.median(f[m])),
                         "mean": float(np.mean(f[m])),
                         "se_median_approx": float(np.std(f[m]) / np.sqrt(m.sum())),
                         "n": int(m.sum())})
    return rows


def win_stats(ph, f, windows, stat="median"):
    mask = np.zeros(ph.shape, dtype=bool)
    for lo, hi in windows:
        mask |= (ph >= lo) & (ph <= hi)
    v = f[mask]
    c = float(np.median(v)) if stat == "median" else float(np.mean(v))
    return c, float(np.std(v) / np.sqrt(len(v))), int(len(v))


def main():
    out = {"tic": TIC, "stage": "fold_profile_arbitration"}
    t, f, nsec, npts = hunter._fetch_raw(TIC, max_sectors=20)
    log(f"raw: {npts} pts")

    prof2 = binned_profile(t, f, P2)
    out["profile_2P_25bins"] = prof2
    for r in prof2:
        log(f"  2P ph {r['phase_lo']:.2f}-{r['phase_hi']:.2f} med {r['median']:.4f} "
            f"mean {r['mean']:.4f} n {r['n']}")
    prof1 = binned_profile(t, f, P)
    out["profile_P_25bins"] = prof1
    for r in prof1:
        log(f"  P  ph {r['phase_lo']:.2f}-{r['phase_hi']:.2f} med {r['median']:.4f} "
            f"mean {r['mean']:.4f} n {r['n']}")

    ph2 = ((t - T0) % P2) / P2
    QW = [(0.19, 0.31), (0.69, 0.81)]
    SW = [(0.08, 0.17), (0.58, 0.67), (0.83, 0.92), (0.33, 0.42)]
    for stat in ("median", "mean"):
        qv, qse, _ = win_stats(ph2, f, QW, stat)
        sv, sse, _ = win_stats(ph2, f, SW, stat)
        delta = (qv - sv) / sv * 100.0
        dse = float(np.hypot(qse, sse)) / sv * 100.0
        out[f"machine_windows_on_this_fold_{stat}"] = {
            "Q": qv, "S": sv, "delta_pct": delta, "delta_sigma_pct": dse,
            "significance": delta / dse if dse else None}
        log(f"machine windows ({stat}): Q={qv:.5f} S={sv:.5f} "
            f"delta={delta:+.3f}+-{dse:.3f}% ({delta/dse:.1f} sigma)")

    # phased sine fits, eclipse cores masked (2P phase within DUR of 0/0.5)
    ph2c = np.minimum(ph2, 1.0 - ph2)
    dist_ecl = np.minimum(ph2c, np.abs(ph2 - 0.5))
    mfit = dist_ecl > (DUR / P2) * 1.3
    for lab, per in (("P", P), ("2P", P2)):
        w = 2 * np.pi / per
        X = np.column_stack([np.ones(mfit.sum()), np.cos(w * t[mfit]),
                             np.sin(w * t[mfit])])
        yv = f[mfit]
        coef, *_ = np.linalg.lstsq(X, yv, rcond=None)
        resid = yv - X @ coef
        dof = max(1, mfit.sum() - 3)
        s2 = float(resid @ resid) / dof
        cov = s2 * np.linalg.inv(X.T @ X)
        amp = float(np.hypot(coef[1], coef[2])) / float(coef[0]) * 100.0
        amp_var = (coef[1] ** 2 * cov[1, 1] + coef[2] ** 2 * cov[2, 2]) / \
            max(coef[1] ** 2 + coef[2] ** 2, 1e-30)
        amp_sig = float(np.sqrt(amp_var)) / float(coef[0]) * 100.0
        # phase of maximum relative to T0 ephemeris, in cycles of `per`
        phmax = float((np.arctan2(-coef[2], coef[1]) / (2 * np.pi)) % 1.0)
        out[f"sine_fit_{lab}"] = {"semi_amplitude_pct": amp,
                                  "sigma_pct": amp_sig,
                                  "significance": amp / amp_sig if amp_sig else None,
                                  "phase_of_max_cycles_from_T0": phmax}
        log(f"sine {lab}: amp {amp:.3f}+-{amp_sig:.3f}% ({amp/amp_sig:.1f} sigma), "
            f"max at phase {phmax:.3f}")
    (OUTDIR / f"{TIC}_profile.json").write_text(json.dumps(out, indent=2, default=str))
    log("profile DONE")


if __name__ == "__main__":
    main()
