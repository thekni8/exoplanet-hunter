"""Big-fish gauntlet — fold-shape photocopy test for TIC 309760851.

Folds the target's TGLC light curve and the RR Lyrae neighbour's own
light curve (TIC 733257403) at the VSX period 0.70817 d, plus the target
at twice the driver period. A photocopy shows the same asymmetric
profile shape at scaled depth; a true EB at 2P shows two flat-bottomed
minima. Phase-binned profiles (24 bins) saved to JSON; per-sector
processing, float32, nothing big held in memory.
Output: vetting_results/bf851_folds.json
"""
import json

import numpy as np
import lightkurve as lk

P_VSX = 0.70817
P_DRV = 0.7082708270827083
T0_DRV = 1325.865474336618
NB = 24


def get_curve(tic, author_pref=("TGLC", "GSFC-ELEANOR-LITE", "T16")):
    sr = None
    for attempt in range(3):
        try:
            sr = lk.search_lightcurve(f"TIC {tic}")
            break
        except Exception as e:
            print(f"search TIC {tic} attempt {attempt + 1} failed: "
                  f"{type(e).__name__}", flush=True)
            import time as _t
            _t.sleep(20)
    if sr is None or len(sr) == 0:
        return None, None
    t = sr.table
    authors = [str(a) for a in t["author"]]
    for want in author_pref:
        idx = [i for i, a in enumerate(authors) if a == want]
        if idx:
            sub = sr[idx]
            lcs = None
            for attempt in range(3):
                try:
                    lcs = sub.download_all()
                    break
                except Exception as e:
                    print(f"download TIC {tic}/{want} attempt "
                          f"{attempt + 1} failed: {type(e).__name__}",
                          flush=True)
                    import time as _t
                    _t.sleep(20)
            if lcs is None:
                continue
            curves = []
            for lc in lcs:
                lc = lc.remove_nans()
                if len(lc) > 100:
                    curves.append(lc.flatten(window_length=101)
                                  .normalize(unit="ppm"))
            if curves:
                stitched = lk.LightCurveCollection(curves).stitch()
                return stitched, want
    return None, None


def profile(time, flux_ppm, period, t0):
    ph = ((time - t0) / period) % 1.0
    bins = np.linspace(0, 1, NB + 1)
    idx = np.digitize(ph, bins) - 1
    prof = np.array([np.median(flux_ppm[idx == i]) if np.any(idx == i)
                     else np.nan for i in range(NB)])
    return ph, prof


def describe(prof, label):
    prof = prof - np.nanmedian(prof)
    imin = int(np.nanargmin(prof))
    depth = -prof[imin]
    half = -depth / 2
    # width below half depth: contiguous run around imin
    below = prof < half
    width = int(np.sum(below))
    # asymmetry: bins from min to half-depth crossing on each side
    left = 0
    i = imin
    while prof[i % NB] < half and left <= NB:
        left += 1
        i -= 1
    right = 0
    i = imin
    while prof[i % NB] < half and right <= NB:
        right += 1
        i += 1
    out = {"label": label, "depth_ppm": float(depth),
           "min_bin": imin, "width_below_half_bins": width,
           "left_run_bins": left, "right_run_bins": right,
           "profile_ppm": [None if not np.isfinite(x) else float(x)
                           for x in prof]}
    print(f"{label}: depth {depth:.0f} ppm, min bin {imin}, "
          f"width<half {width} bins, left run {left}, right run {right}",
          flush=True)
    print("   profile:", " ".join(
        f"{x/1000:+.2f}" if x is not None else "  nan" for x in
        (np.array([p if p is not None else np.nan for p in out['profile_ppm']]))),
        flush=True)
    return out


res = {}
for tic, label in ((309760851, "target_309760851"),
                   (733257403, "rrlab_733257403")):
    lc, author = get_curve(tic)
    if lc is None:
        res[label] = {"error": "no products"}
        print(label, ": NO PRODUCTS", flush=True)
        continue
    tt = np.asarray(lc.time.value, dtype=np.float64)
    ff = np.asarray(lc.flux.value, dtype=np.float64)
    print(f"{label}: author {author}, {tt.size} cadences, "
          f"span {tt.min():.1f}..{tt.max():.1f}", flush=True)
    ent = {"author": author, "n_cadences": int(tt.size)}
    _, prof = profile(tt, ff, P_VSX, T0_DRV)
    ent["fold_vsx_period"] = describe(prof, f"{label} @ VSX P")
    res[label] = ent
    del lc, tt, ff

lc, author = get_curve(309760851)
tt = np.asarray(lc.time.value, dtype=np.float64)
ff = np.asarray(lc.flux.value, dtype=np.float64)
_, prof2 = profile(tt, ff, 2 * P_DRV, T0_DRV)
res["target_fold_2P"] = describe(prof2, "target @ 2x driver P")

with open("vetting_results/bf851_folds.json", "w") as f:
    json.dump(res, f, indent=1, default=str)
print("wrote vetting_results/bf851_folds.json", flush=True)
