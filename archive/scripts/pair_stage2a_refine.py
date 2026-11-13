"""Pair vetting stage 2a: independent period refinement per star.

Stitches a 4-sector subset per star (QLP-era sectors spanning both
observing eras), runs astropy BLS on a 0.40-0.90 d grid, and reports each
star's own best period near the sweep/VSX period — three independent
refinements that must agree if one signal drives all three light curves.
Also fixes the common fold ephemeris (P_common, T0) from TIC 31315574
(the VSX-catalogued variable WISE J055308.1-700059).
Output: pair_stage2a.json. Read-only; light curves cached by lightkurve.
"""
import json
import numpy as np
import lightkurve as lk
from astropy.timeseries import BoxLeastSquares

SUBSETS = {
    31315594: [35, 62, 88, 96],     # A (deep sweep hit) — its QLP sectors
    31315605: [2, 8, 11, 32],       # B (shallow sweep hit) — its QLP sectors
    31315574: [35, 62, 2, 8],       # C (VSX variable) — spans both eras
}
SWEEP_P = {31315594: 0.5711, 31315605: 0.5735}
VSX_P = 0.5725948


def fetch(tic, sectors):
    ts, fs, used = [], [], []
    for sec in sectors:
        sr = lk.search_lightcurve(f"TIC {tic}",
                                  author=["SPOC", "TESS-SPOC", "QLP"],
                                  sector=sec)
        if len(sr) == 0:
            continue
        lc = sr[0].download()
        t = np.asarray(lc.time.value, dtype=np.float64)
        f = np.asarray(lc.flux.value, dtype=np.float64)
        q = np.asarray(lc.quality)
        m = (q == 0) & np.isfinite(f) & np.isfinite(t)
        t, f = t[m], f[m]
        if t.size < 100:
            continue
        f = f / np.median(f)
        ts.append(t)
        fs.append(f)
        used.append({"sector": sec, "author": str(sr[0].table["author"][0])
                     if "author" in sr[0].table.colnames else "?"})
        del lc
    if not ts:
        return None, None, used
    t = np.concatenate(ts)
    f = np.concatenate(fs)
    order = np.argsort(t)
    return t[order], f[order], used


def bls_scan(t, f):
    # gentle sigma clip to tame flares/outliers, keep the eclipses
    med = np.median(f)
    sd = 1.4826 * np.median(np.abs(f - med)) + 1e-9
    m = np.abs(f - med) < 6 * sd
    t2, f2 = t[m], f[m]
    model = BoxLeastSquares(t2, f2)
    periods = np.linspace(0.40, 0.90, 25000)
    durations = np.array([0.04, 0.07, 0.10, 0.15, 0.20])
    res = model.power(periods, durations)
    i = int(np.argmax(res.power))
    sde = float((res.power[i] - np.median(res.power)) / (np.std(res.power) + 1e-12))
    return {
        "best_period": float(res.period[i]),
        "best_depth": float(res.depth[i]),
        "best_duration_d": float(res.duration[i]),
        "t0_btjd": float(res.transit_time[i]),
        "sde_like": sde,
        "n_points": int(t2.size),
    }


out = {}
curves = {}
for tic, secs in SUBSETS.items():
    t, f, used = fetch(tic, secs)
    if t is None:
        out[str(tic)] = {"error": "no data", "used": used}
        continue
    r = bls_scan(t, f)
    r["sectors_used"] = used
    out[str(tic)] = r
    curves[tic] = (t, f)
    print(f"TIC {tic}: BLS P={r['best_period']:.6f} d depth={100 * r['best_depth']:.2f}% "
          f"dur={r['best_duration_d']:.3f} d SDE~{r['sde_like']:.1f} "
          f"T0={r['t0_btjd']:.4f} n={r['n_points']}", flush=True)

# common ephemeris from C (the catalogued variable)
c = out[str(31315574)]
p_bls = c["best_period"]
cands = [p_bls, 2 * p_bls, p_bls / 2]
p_common = min(cands, key=lambda p: abs(p - VSX_P) / VSX_P)
out["common_ephemeris"] = {
    "P_common_d": p_common,
    "T0_btjd": c["t0_btjd"],
    "chosen_from_C_bls": p_bls,
    "vsx_period_d": VSX_P,
    "frac_diff_vs_vsx": abs(p_common - VSX_P) / VSX_P,
}
print("common ephemeris:", out["common_ephemeris"], flush=True)

with open("pair_stage2a.json", "w") as fh:
    json.dump(out, fh, indent=1)
print("wrote pair_stage2a.json")
