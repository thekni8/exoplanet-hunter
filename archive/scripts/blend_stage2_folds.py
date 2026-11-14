"""Blend check stage 2: per-star QLP folds for TIC 167367406 (target) and
TIC 167367400 (the ASASSN-V star), same 18 sectors, same estimator as the
filing packet: per-sector median normalisation, quality==0, fold at
P = 0.4346134307164049 d, epoch BTJD 3095.3776324363.
Accumulates 100-bin profiles + window stats; nothing held in memory per sector.
"""
import json
import numpy as np
import lightkurve as lk

P = 0.4346134307164049
T0 = 3095.3776324363  # BTJD, primary minimum
SECTORS = [31, 35, 36, 39, 61, 62, 63, 64, 65, 66, 67, 69, 87, 88, 89, 93, 96, 98]
NB = 100

def win_mask(ph, centre, half=0.06):
    d = np.abs(((ph - centre + 0.5) % 1.0) - 0.5)
    return d <= half

def profile_stats(phase, flux):
    """Window-mean depths + levels from unbinned points."""
    mI = win_mask(phase, 0.0); mII = win_mask(phase, 0.5)
    mP1 = win_mask(phase, 0.25); mP2 = win_mask(phase, 0.75)
    plat = np.concatenate([flux[mP1], flux[mP2]])
    out = {
        "plateau": float(np.mean(plat)),
        "minI_level": float(np.mean(flux[mI])),
        "minII_level": float(np.mean(flux[mII])),
        "depthI_window_pct": float(100 * (1 - np.mean(flux[mI]) / np.mean(plat))),
        "depthII_window_pct": float(100 * (1 - np.mean(flux[mII]) / np.mean(plat))),
        "n": int(flux.size),
    }
    return out

def vertex_depth(binned_phase, binned_flux, plateau, centre):
    """Parabola vertex on the 5 bins around the minimum nearest centre."""
    d = np.abs(((binned_phase - centre + 0.5) % 1.0) - 0.5)
    i0 = int(np.argmin(np.where(d < 0.06, binned_flux, np.inf)))
    idx = [(i0 + k) % NB for k in (-2, -1, 0, 1, 2)]
    x = np.array([((binned_phase[i] - centre + 0.5) % 1.0) - 0.5 for i in idx])
    y = np.array([binned_flux[i] for i in idx])
    A = np.vstack([x**2, x, np.ones_like(x)]).T
    coef, *_ = np.linalg.lstsq(A, y, rcond=None)
    if coef[0] <= 0:
        return None
    xv = -coef[1] / (2 * coef[0])
    yv = coef[0] * xv**2 + coef[1] * xv + coef[2]
    return float(100 * (1 - yv / plateau))

results = {}
for tic in (167367406, 167367400):
    binsum = np.zeros(NB); bincnt = np.zeros(NB)
    per_sector = {}
    allph, allfl = [], []
    for sec in SECTORS:
        sr = lk.search_lightcurve(f"TIC {tic}", author="QLP", sector=sec)
        if len(sr) == 0:
            per_sector[str(sec)] = {"error": "no QLP product"}
            continue
        lc = sr.download()
        t = np.asarray(lc.time.value, dtype=np.float64)
        f = np.asarray(lc.flux.value, dtype=np.float64)
        q = np.asarray(lc.quality)
        m = (q == 0) & np.isfinite(f) & np.isfinite(t)
        t, f = t[m], f[m]
        med = np.median(f)
        f = f / med
        ph = ((t - T0) / P) % 1.0
        idx = np.minimum((ph * NB).astype(int), NB - 1)
        np.add.at(binsum, idx, f)
        np.add.at(bincnt, idx, 1.0)
        ps = profile_stats(ph.astype(np.float64), f.astype(np.float64))
        per_sector[str(sec)] = {k: ps[k] for k in ("depthI_window_pct", "depthII_window_pct", "n")}
        allph.append(ph); allfl.append(f)
        del lc, t, f, ph
    phase = np.concatenate(allph); flux = np.concatenate(allfl)
    stats = profile_stats(phase, flux)
    binned = binsum / np.maximum(bincnt, 1)
    centres = (np.arange(NB) + 0.5) / NB
    plat_bins = binned[(np.abs(((centres - 0.25 + 0.5) % 1) - 0.5) <= 0.06) |
                       (np.abs(((centres - 0.75 + 0.5) % 1) - 0.5) <= 0.06)]
    plateau_b = float(np.mean(plat_bins))
    stats["vertex_depthI_pct"] = vertex_depth(centres, binned, plateau_b, 0.0)
    stats["vertex_depthII_pct"] = vertex_depth(centres, binned, plateau_b, 0.5)
    stats["profile_max"] = float(np.max(binned))
    stats["profile_min"] = float(np.min(binned))
    stats["amplitude_mag_binned"] = float(-2.5 * np.log10(np.min(binned) / np.max(binned)))
    stats["sectors_used"] = [int(s) for s, v in per_sector.items() if "error" not in v]
    stats["per_sector"] = per_sector
    results[str(tic)] = stats
    print(f"TIC {tic}: plateau {stats['plateau']:.4f} "
          f"winDepths I/II {stats['depthI_window_pct']:.2f}%/{stats['depthII_window_pct']:.2f}% "
          f"vertex I/II {stats['vertex_depthI_pct']:.2f}%/{stats['vertex_depthII_pct']:.2f}% "
          f"ampl {stats['amplitude_mag_binned']:.3f} mag, n={stats['n']}")
    del phase, flux, binsum, bincnt

with open("blend_check_stage2.json", "w") as fh:
    json.dump(results, fh, indent=1)
print("wrote blend_check_stage2.json")
