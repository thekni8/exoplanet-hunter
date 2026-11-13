#!/usr/bin/env python3
"""Finish desk checks for sector-98 bulk-screen survivors.

Verifies the previous worker's refined-ephemeris folds from the local npz
data, runs the P/2 alias test (14081980), and the free-BLS sub-floor
fundamental check (sub-day stars 31054247, 423498314).

Usage: desk_finish_s98.py <tic> [--bls] [--half]
Results written to the star's candidates-vetting folder.
"""
import json, sys, os
import numpy as np

BASE = os.path.expanduser("~/workspace/goals/exoplanet-hunter/hidden_files/candidates-vetting")

REFINED = {
    "14081980": {"P": 2.9192743, "T0": 3990.30947, "DUR": 0.092, "bulk_P": 2.9195002372291636, "bulk_T0": 3990.3058908852186},
    "31054247": {"P": 0.8738713, "T0": 3989.25839, "DUR": 0.04, "bulk_P": 0.8737220749716018, "bulk_T0": 3989.2647745344793},
    "423498314": {"P": 0.827048, "T0": 3988.91522, "DUR": 0.04, "bulk_P": 0.8269868291371741, "bulk_T0": 3988.9172845404414},
    "14174515": {"P": 3.0891062, "T0": 3989.24348, "DUR": 0.092, "bulk_P": 3.089539748953975, "bulk_T0": 3989.2378607336946},
}


def load_star(tic):
    d = os.path.join(BASE, tic, "data")
    sets = {}
    for f in sorted(os.listdir(d)):
        if not f.endswith(".npz"):
            continue
        pfx, sec = f[:-4].split("_s")
        z = np.load(os.path.join(d, f))
        sets.setdefault(pfx, {})[int(sec)] = (np.asarray(z["time"], float), np.asarray(z["flux"], float))
    return sets


def fold_depth(t, f, P, T0, dur, centre_phase=0.0):
    """Depth (%) of a box of width dur centred at centre_phase (phase units).
    Returns depth, white sigma, red-noise sigma from control windows, n_in."""
    ph = (((t - T0) / P - centre_phase + 0.5) % 1.0) - 0.5
    hw = 0.5 * dur / P
    in_tr = np.abs(ph) < hw
    out = ~in_tr
    if in_tr.sum() < 5 or out.sum() < 50:
        return None
    depth = (np.median(f[out]) - np.median(f[in_tr])) * 100.0
    sig_white = np.std(f[out]) / np.sqrt(in_tr.sum()) * 100.0
    # red-noise sigma: depths in 24 control windows at other phases
    rng = np.random.default_rng(0)
    ctrls = []
    for _ in range(24):
        c = rng.uniform(-0.45, 0.45)
        if abs(c - centre_phase) < 3 * hw + 0.02:
            continue
        ph2 = (((t - T0) / P - c + 0.5) % 1.0) - 0.5
        m = np.abs(ph2) < hw
        if m.sum() >= 5:
            ctrls.append((np.median(f[~m]) - np.median(f[m])) * 100.0)
    sig_red = float(np.std(ctrls)) if len(ctrls) >= 8 else float("nan")
    return {"depth_pct": float(depth), "sig_white_pct": float(sig_white),
            "sig_red_pct": sig_red, "n_in": int(in_tr.sum()),
            "signif_white": float(depth / sig_white),
            "signif_red": float(depth / sig_red) if sig_red == sig_red and sig_red > 0 else None}


def event_parity_depths(t, f, P, T0, dur):
    """Split IN-TRANSIT points by nearest-event index parity.
    Returns (odd_depth_dict, even_depth_dict). Baseline = points far from
    any event centre (shared)."""
    n_ev = np.round((t - T0) / P).astype(int)
    dt = t - (T0 + n_ev * P)
    in_tr = np.abs(dt) < dur / 2.0
    out = np.abs(dt) > 3 * dur
    base = np.median(f[out])
    res = []
    for parity in (1, 0):
        m = in_tr & (n_ev % 2 == parity)
        if m.sum() < 5:
            res.append(None)
            continue
        depth = (base - np.median(f[m])) * 100.0
        sig = np.std(f[out]) / np.sqrt(m.sum()) * 100.0
        res.append({"depth_pct": float(depth), "sig_white_pct": float(sig),
                    "signif_white": float(depth / sig), "n_in": int(m.sum()),
                    "n_events": int(len(np.unique(n_ev[m])))})
    return res[0], res[1]


def concat(sets, pfx, sectors=None):
    ts, fs = [], []
    for s in sorted(sets.get(pfx, {})):
        if sectors is not None and s not in sectors:
            continue
        t, f = sets[pfx][s]
        med = np.median(f)
        ts.append(t)
        fs.append(f / med)
    if not ts:
        return None, None
    return np.concatenate(ts), np.concatenate(fs)


def main():
    tic = sys.argv[1]
    do_bls = "--bls" in sys.argv
    do_half = "--half" in sys.argv
    R = REFINED[tic]
    sets = load_star(tic)
    out = {"tic": tic, "refined": R}
    print(f"== {tic}: sets:", {k: sorted(v) for k, v in sets.items()}, flush=True)

    # 1. Verification folds at the REFINED ephemeris, per product and era.
    ver = {}
    for pfx in sorted(sets):
        t, f = concat(sets, pfx)
        ver[pfx] = {"combined": fold_depth(t, f, R["P"], R["T0"], R["DUR"]),
                    "secondary_0.5": fold_depth(t, f, R["P"], R["T0"], R["DUR"], centre_phase=0.5)}
        per_sec = {}
        for s in sorted(sets[pfx]):
            tt, ff = sets[pfx][s]
            per_sec[s] = fold_depth(tt, ff / np.median(ff), R["P"], R["T0"], R["DUR"])
        ver[pfx]["per_sector"] = per_sec
    out["verify_refined"] = ver
    for pfx, v in ver.items():
        c = v["combined"]
        print(f"  {pfx} combined: depth {c['depth_pct']:.3f}% white {c['signif_white']:.1f}σ red {c['signif_red'] if c['signif_red'] is None else round(c['signif_red'],1)}σ | secondary {v['secondary_0.5']['depth_pct']:.3f}% ({v['secondary_0.5']['signif_white']:.1f}σ white)", flush=True)
        for s, r in v["per_sector"].items():
            print(f"    s{s}: {r['depth_pct']:.3f}% ({r['signif_white']:.1f}σ white)", flush=True)

    # 2. Odd/even at refined ephemeris (best product = most sectors).
    # NOTE: assign each point to its NEAREST event (round, not floor):
    # a floor-parity split mixes the two halves of every eclipse across
    # parities and would erase a real odd/even difference.
    best = max(sets, key=lambda p: len(sets[p]))
    t, f = concat(sets, best)
    odd, even = event_parity_depths(t, f, R["P"], R["T0"], R["DUR"])
    out["odd_even_refined"] = {"product": best, "odd": odd, "even": even}
    print(f"  odd/even ({best}): odd {odd['depth_pct']:.3f}% ({odd['signif_white']:.1f}σ) even {even['depth_pct']:.3f}% ({even['signif_white']:.1f}σ)", flush=True)

    # 3. P/2 alias test: at half period, even events = primary, odd = secondary.
    if do_half:
        Ph = R["P"] / 2.0
        half = {}
        for pfx in sorted(sets):
            tt, ff = concat(sets, pfx)
            o, e = event_parity_depths(tt, ff, Ph, R["T0"], R["DUR"])
            half[pfx] = {"odd_at_Phalf_secondary": o, "even_at_Phalf_primary": e}
            print(f"  P/2 {pfx}: even(primary) {e['depth_pct']:.3f}% ({e['signif_white']:.1f}σ) odd(secondary) {o['depth_pct']:.3f}% ({o['signif_white']:.1f}σ)", flush=True)
        out["half_period_test"] = half

    # 4. Free BLS + Lomb-Scargle over 0.1-1.2 d (sub-floor fundamental check).
    if do_bls:
        from astropy.timeseries import BoxLeastSquares, LombScargle
        t, f = concat(sets, best)
        # light detrend: per-sector median already applied; remove slow trend with 2-d median filter
        from scipy.ndimage import median_filter
        order = np.argsort(t)
        ts, fs = t[order], f[order]
        # resample-free approach: subtract a running median over ~2 d via binned medians
        bins = np.arange(ts.min(), ts.max() + 2.0, 2.0)
        idx = np.digitize(ts, bins)
        trend = np.array([np.median(fs[idx == b]) if np.any(idx == b) else 1.0 for b in range(1, len(bins))])
        trend_full = trend[np.clip(idx - 1, 0, len(trend) - 1)]
        fd = fs / trend_full
        # NOTE: astropy BoxLeastSquares.power takes PERIODS, not frequencies.
        # Build a frequency-linear grid, then pass periods = 1/f.
        freqs = np.linspace(1 / 1.2, 1 / 0.1, 50000)
        periods = 1.0 / freqs
        bls = BoxLeastSquares(ts, fd, dy=np.std(fd))
        res = bls.power(periods, [0.02, 0.04, 0.08], objective="snr")
        power = np.asarray(res.power)
        med, mad = np.median(power), np.median(np.abs(power - np.median(power))) * 1.4826
        sde = (power - med) / mad
        # top peaks (greedy, suppress +-2% around each)
        peaks = []
        s = sde.copy()
        for _ in range(8):
            i = int(np.argmax(s))
            peaks.append({"period_d": float(periods[i]), "sde": float(sde[i]),
                          "duration_d": float(res.duration[i])})
            m = np.abs(periods - periods[i]) / periods[i] < 0.02
            s[m] = -np.inf
        # power at filed period and at P/k harmonics
        def sde_at(P):
            j = int(np.argmin(np.abs(periods - P)))
            return float(sde[j])
        harm = {f"P/{k}": {"period_d": R["P"] / k, "sde": sde_at(R["P"] / k)} for k in (1, 2, 3, 4)}
        harm["P_filed"] = {"period_d": R["bulk_P"], "sde": sde_at(R["bulk_P"])}
        ls = LombScargle(ts, fd, normalization="standard")
        lf = np.linspace(1 / 2.0, 1 / 0.1, 30000)
        lp = ls.power(lf)
        lper = 1 / lf
        lpeaks = []
        l = lp.copy()
        for _ in range(5):
            i = int(np.argmax(l))
            lpeaks.append({"period_d": float(lper[i]), "power": float(lp[i])})
            m = np.abs(lper - lper[i]) / lper[i] < 0.02
            l[m] = -np.inf
        out["free_bls"] = {"product": best, "n_points": len(ts), "top_peaks": peaks,
                           "harmonics": harm}
        out["lomb_scargle"] = {"top_peaks": lpeaks}
        print("  BLS top peaks:", [(p["period_d"], round(p["sde"], 1)) for p in peaks], flush=True)
        print("  BLS harmonics:", {k: round(v["sde"], 1) for k, v in harm.items()}, flush=True)
        print("  LS top peaks:", [(p["period_d"], round(p["power"], 3)) for p in lpeaks], flush=True)

    with open(os.path.join(BASE, tic, "finish_results.json"), "w") as fh:
        json.dump(out, fh, indent=1)
    print("wrote finish_results.json", flush=True)


if __name__ == "__main__":
    main()
