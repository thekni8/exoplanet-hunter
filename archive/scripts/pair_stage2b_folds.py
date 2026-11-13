"""Pair vetting stage 2b: full QLP folds for A (31315594), B (31315605),
C (31315574) at the common ephemeris from stage 2a, plus wide-BLS
independence check and copy tests.

Per star: 100-bin profile accumulated sector-by-sector (nothing big held),
per-sector Min I / Min II window depths (packet estimator), sweep-subset
profile for A/B, 2P-fold minima depths (orbital-frame odd/even), profile
minimum phase. Copy tests: dip-profile Pearson r + least-squares scale
(best integer bin shift), per-sector depth correlation + median ratio on
shared sectors. Output: pair_stage2.json. Read-only.
"""
import json
import numpy as np
import lightkurve as lk
from astropy.timeseries import BoxLeastSquares

with open("pair_stage2a.json") as f:
    ref = json.load(f)
P = ref["common_ephemeris"]["P_common_d"]
T0 = ref["common_ephemeris"]["T0_btjd"]
NB = 100

SECTORS = {
    31315594: [31, 35, 36, 37, 39, 61, 62, 63, 64, 65, 67, 68, 69, 87, 88,
               90, 95, 96, 97, 98],
    31315605: [1, 2, 4, 5, 6, 7, 8, 9, 10, 11, 12, 32],
    31315574: sorted(set([31, 35, 36, 37, 39, 61, 62, 63, 64, 65, 67, 68, 69,
                          87, 88, 90, 95, 96, 97, 98]) |
                     set([1, 2, 4, 5, 6, 7, 8, 9, 10, 11, 12, 32])),
}
SWEEP_SUBSET = {31315594: {31, 35}, 31315605: {1, 2}}
WIDE_SUBSET = {31315594: [35, 62, 88, 96], 31315574: [35, 62, 2, 8]}


def win_mask(ph, centre, half=0.06):
    d = np.abs(((ph - centre + 0.5) % 1.0) - 0.5)
    return d <= half


def profile_stats(phase, flux):
    mI = win_mask(phase, 0.0)
    mII = win_mask(phase, 0.5)
    plat = np.concatenate([flux[win_mask(phase, 0.25)],
                           flux[win_mask(phase, 0.75)]])
    return {
        "plateau": float(np.mean(plat)),
        "depthI_window_pct": float(100 * (1 - np.mean(flux[mI]) / np.mean(plat))),
        "depthII_window_pct": float(100 * (1 - np.mean(flux[mII]) / np.mean(plat))),
        "n": int(flux.size),
    }


def fetch_sector(tic, sec):
    sr = lk.search_lightcurve(f"TIC {tic}",
                              author=["SPOC", "TESS-SPOC", "QLP"], sector=sec)
    if len(sr) == 0:
        return None, None, None
    lc = sr[0].download()
    t = np.asarray(lc.time.value, dtype=np.float64)
    f = np.asarray(lc.flux.value, dtype=np.float64)
    q = np.asarray(lc.quality)
    m = (q == 0) & np.isfinite(f) & np.isfinite(t)
    t, f = t[m], f[m]
    author = "?"
    try:
        author = str(sr[0].table["author"][0])
    except Exception:
        pass
    del lc
    if t.size < 100:
        return None, None, author
    return t, f / np.median(f), author


def wide_bls(tic, sectors):
    ts, fs = [], []
    for sec in sectors:
        t, f, _ = fetch_sector(tic, sec)
        if t is not None:
            ts.append(t)
            fs.append(f)
    t = np.concatenate(ts)
    f = np.concatenate(fs)
    med = np.median(f)
    sd = 1.4826 * np.median(np.abs(f - med)) + 1e-9
    m = np.abs(f - med) < 6 * sd
    t2, f2 = t[m], f[m]
    model = BoxLeastSquares(t2, f2)
    periods = np.linspace(0.25, 10.0, 60000)
    res = model.power(periods, [0.04, 0.07, 0.10, 0.15, 0.20])
    order = np.argsort(res.power)[::-1]
    peaks = []
    for i in order:
        p = float(res.period[i])
        if all(abs(p - q["period"]) / q["period"] > 0.02 for q in peaks):
            peaks.append({"period": p, "depth": float(res.depth[i]),
                          "power": float(res.power[i])})
        if len(peaks) >= 5:
            break
    return {"top_peaks": peaks, "n_points": int(t2.size)}


results = {}
profiles = {}
for tic, secs in SECTORS.items():
    binsum = np.zeros(NB)
    bincnt = np.zeros(NB)
    binsum_sw = np.zeros(NB)
    bincnt_sw = np.zeros(NB)
    binsum2 = np.zeros(NB)
    bincnt2 = np.zeros(NB)
    per_sector = {}
    allph, allfl = [], []
    for sec in secs:
        t, f, author = fetch_sector(tic, sec)
        if t is None:
            per_sector[str(sec)] = {"error": "no product/data"}
            continue
        ph = ((t - T0) / P) % 1.0
        idx = np.minimum((ph * NB).astype(int), NB - 1)
        np.add.at(binsum, idx, f)
        np.add.at(bincnt, idx, 1.0)
        ph2 = ((t - T0) / (2 * P)) % 1.0
        idx2 = np.minimum((ph2 * NB).astype(int), NB - 1)
        np.add.at(binsum2, idx2, f)
        np.add.at(bincnt2, idx2, 1.0)
        if sec in SWEEP_SUBSET.get(tic, set()):
            np.add.at(binsum_sw, idx, f)
            np.add.at(bincnt_sw, idx, 1.0)
        ps = profile_stats(ph, f)
        per_sector[str(sec)] = {"author": author,
                                "depthI_pct": ps["depthI_window_pct"],
                                "depthII_pct": ps["depthII_window_pct"],
                                "n": ps["n"]}
        allph.append(ph)
        allfl.append(f)
        print(f"  TIC {tic} s{sec}: depthI {ps['depthI_window_pct']:.2f}% "
              f"depthII {ps['depthII_window_pct']:.2f}% n={ps['n']}", flush=True)
        del t, f, ph, ph2
    phase = np.concatenate(allph)
    flux = np.concatenate(allfl)
    stats = profile_stats(phase, flux)
    binned = binsum / np.maximum(bincnt, 1)
    centres = (np.arange(NB) + 0.5) / NB
    # smoothed minimum phase (5-bin rolling mean)
    sm = np.convolve(np.concatenate([binned[-2:], binned, binned[:2]]),
                     np.ones(5) / 5, mode="same")[2:-2]
    stats["profile_min_phase"] = float(centres[int(np.argmin(sm))])
    stats["profile_max"] = float(np.max(binned))
    stats["profile_min"] = float(np.min(binned))
    stats["amplitude_mag_binned"] = float(
        -2.5 * np.log10(np.min(binned) / np.max(binned)))
    stats["profile_100bin"] = [float(x) for x in binned]
    stats["per_sector"] = per_sector
    stats["sectors_used"] = [int(s) for s, v in per_sector.items()
                             if "error" not in v]
    if bincnt_sw.sum() > 0:
        binned_sw = binsum_sw / np.maximum(bincnt_sw, 1)
        plat_sw = float(np.mean(np.concatenate(
            [binned_sw[win_mask(centres, 0.25)], binned_sw[win_mask(centres, 0.75)]])))
        stats["sweep_subset_minI_pct"] = float(
            100 * (1 - np.mean(binned_sw[win_mask(centres, 0.0)]) / plat_sw))
    # 2P fold: minima at phase 0 and 0.5 of the doubled period
    binned2 = binsum2 / np.maximum(bincnt2, 1)
    plat2 = float(np.mean(np.concatenate(
        [binned2[win_mask(centres, 0.25)], binned2[win_mask(centres, 0.75)]])))
    stats["fold2P_depth_at_0_pct"] = float(
        100 * (1 - np.mean(binned2[win_mask(centres, 0.0)]) / plat2))
    stats["fold2P_depth_at_0.5_pct"] = float(
        100 * (1 - np.mean(binned2[win_mask(centres, 0.5)]) / plat2))
    stats["profile_2P_100bin"] = [float(x) for x in binned2]
    results[str(tic)] = stats
    profiles[tic] = binned
    print(f"TIC {tic}: FULL fold depthI {stats['depthI_window_pct']:.2f}% "
          f"depthII {stats['depthII_window_pct']:.2f}% "
          f"minPhase {stats['profile_min_phase']:.2f} "
          f"ampl {stats['amplitude_mag_binned']:.3f} mag n={stats['n']}",
          flush=True)
    del phase, flux, binsum, bincnt, allph, allfl

# ------------------------------------------------------------- copy tests
def dip_profile(binned):
    centres = (np.arange(NB) + 0.5) / NB
    plat = np.mean(np.concatenate([binned[win_mask(centres, 0.25)],
                                   binned[win_mask(centres, 0.75)]]))
    return plat - binned


def copy_test(tic1, tic2):
    d1 = dip_profile(profiles[tic1])
    d2 = dip_profile(profiles[tic2])
    best = None
    for shift in range(-8, 9):
        dd = np.roll(d2, shift)
        if np.std(d1) == 0 or np.std(dd) == 0:
            continue
        r = float(np.corrcoef(d1, dd)[0, 1])
        if best is None or r > best["r"]:
            scale = float(np.sum(d1 * dd) / np.sum(dd * dd))
            best = {"r": r, "shift_bins": shift, "scale_1_per_2": scale}
    return best


copy = {}
for a, b in ((31315594, 31315574), (31315605, 31315574), (31315594, 31315605)):
    copy[f"{a}_vs_{b}"] = copy_test(a, b)
    print(f"copy {a} vs {b}: {copy[f'{a}_vs_{b}']}", flush=True)


def sector_corr(tic1, tic2):
    s1 = results[str(tic1)]["per_sector"]
    s2 = results[str(tic2)]["per_sector"]
    shared = [s for s in s1 if s in s2 and "depthI_pct" in s1[s]
              and "depthI_pct" in s2[s]]
    if len(shared) < 3:
        return {"shared_sectors": shared, "note": "too few shared sectors"}
    x = np.array([s1[s]["depthI_pct"] for s in shared])
    y = np.array([s2[s]["depthI_pct"] for s in shared])
    return {
        "shared_sectors": [int(s) for s in shared],
        "pearson_r_depthI": float(np.corrcoef(x, y)[0, 1]),
        "median_ratio_1_per_2": float(np.median(x / y)),
        "depths_1": [float(v) for v in x],
        "depths_2": [float(v) for v in y],
    }


sc = {}
for a, b in ((31315594, 31315574), (31315605, 31315574)):
    sc[f"{a}_vs_{b}"] = sector_corr(a, b)
    print(f"sector corr {a} vs {b}: r={sc[f'{a}_vs_{b}'].get('pearson_r_depthI')} "
          f"ratio={sc[f'{a}_vs_{b}'].get('median_ratio_1_per_2')} "
          f"n={len(sc[f'{a}_vs_{b}']['shared_sectors'])}", flush=True)
results["copy_tests"] = {"profile": copy, "per_sector": sc}

# ------------------------------------------------- wide BLS independence
wb = {}
for tic, secs in WIDE_SUBSET.items():
    wb[str(tic)] = wide_bls(tic, secs)
    print(f"wide BLS TIC {tic}: " +
          ", ".join(f"{p['period']:.4f} d ({100 * p['depth']:.2f}%)"
                    for p in wb[str(tic)]["top_peaks"]), flush=True)
results["wide_bls"] = wb
results["ephemeris"] = {"P_common_d": P, "T0_btjd": T0}

with open("pair_stage2.json", "w") as fh:
    json.dump(results, fh, indent=1)
print("wrote pair_stage2.json")
