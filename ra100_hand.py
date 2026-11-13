#!/usr/bin/env python
"""RA100 vet, hand checks for TIC 167367406 (independent of the
machine stamp): (a) odd/even folds at P on the flattened curve,
(b) 2P eclipse pair + ellipsoidal wave (Q-S on the raw fold and a
sine fit at P with eclipses masked), (f) duration sanity +
physical-window fold, (4) Lomb-Scargle context + harmonic fit at
2P, (d) raw-flux fixed-ephemeris per-sector era split (closing-test
convention: first product per distinct sector, sector's own
out-of-transit mean). History suppressed in-process."""
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
from astropy.timeseries import LombScargle  # noqa: E402

hunter.log_candidate = lambda *a, **k: None

TIC = "167367406"
RSTAR = 0.38876
MSTAR = 0.378736
P = 0.6519151915191519
P2 = 2.0 * P
T0 = 2144.665741058755
DUR_H = 2.376
DUR = DUR_H / 24.0


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def depth_stats(f_in, f_out):
    """(depth_pct, sigma_pct) of mean(out)-mean(in), relative to out."""
    mo, mi = float(np.mean(f_out)), float(np.mean(f_in))
    so = float(np.std(f_out, ddof=1) / np.sqrt(len(f_out)))
    si = float(np.std(f_in, ddof=1) / np.sqrt(len(f_in)))
    return (mo - mi) / mo * 100.0, float(np.hypot(so, si) / mo * 100.0)


def main():
    out = {"tic": TIC, "stage": "hand_checks",
           "ephemeris": {"period_days": P, "period_2p_days": P2,
                         "t0_btjd": T0, "duration_hours": DUR_H}}

    # ---------- Part 1: flattened curve ----------
    t, f, nsec, npts = hunter._fetch_flattened(TIC, max_sectors=20)
    log(f"flattened: {npts} pts, {nsec} sectors")
    out["flattened_points"] = npts
    phase = ((t - T0 + 0.5 * P) % P) - 0.5 * P
    cyc = np.round((t - T0) / P).astype(np.int64)
    in_tr = np.abs(phase) <= DUR / 2.0
    out_tr = ~in_tr

    # (a) odd/even at P
    res_a = {}
    for name, m in (("odd", in_tr & (cyc % 2 == 1)), ("even", in_tr & (cyc % 2 == 0))):
        d, s = depth_stats(f[m], f[out_tr])
        res_a[name] = {"depth_pct": d, "sigma_pct": s, "n_in": int(m.sum())}
    do, de = res_a["odd"], res_a["even"]
    diff = do["depth_pct"] - de["depth_pct"]
    sdiff = float(np.hypot(do["sigma_pct"], de["sigma_pct"]))
    res_a["difference_pct"] = diff
    res_a["difference_sigma"] = sdiff
    res_a["difference_significance"] = diff / sdiff if sdiff else None
    res_a["ratio_even_over_odd"] = de["depth_pct"] / do["depth_pct"]
    out["hand_odd_even_at_P"] = res_a
    log(f"(a) odd {do['depth_pct']:.3f}+-{do['sigma_pct']:.3f}%  "
        f"even {de['depth_pct']:.3f}+-{de['sigma_pct']:.3f}%  "
        f"diff {diff:+.3f}% = {res_a['difference_significance']:.2f} sigma")

    # (f) duration sanity
    G = 6.674e-11
    Msun, Rsun = 1.98847e30, 6.957e8
    a_m = (G * MSTAR * Msun * (P * 86400.0) ** 2 / (4 * np.pi ** 2)) ** (1.0 / 3.0)
    a_rsun = a_m / Rsun
    a_over_r = a_rsun / RSTAR
    k_bls = float(np.sqrt(0.2073998190176795))
    dur_max_kbls = (P / np.pi) * np.arcsin(min(1.0, RSTAR * (1 + k_bls) / a_rsun)) * 24.0
    dur_max_k0 = (P / np.pi) * np.arcsin(min(1.0, RSTAR / a_rsun)) * 24.0
    # physical-window fold: half-width = dur_max(k=0)/2 around phase 0
    hw = (dur_max_k0 / 24.0) / 2.0
    dphys, sphys = depth_stats(f[np.abs(phase) <= hw], f[out_tr])
    out["duration_sanity"] = {
        "a_rsun": float(a_rsun), "a_over_rstar": float(a_over_r),
        "k_from_bls_depth": k_bls,
        "max_central_duration_h_k0": float(dur_max_k0),
        "max_central_duration_h_k_blsdepth": float(dur_max_kbls),
        "bls_duration_h": DUR_H,
        "bls_over_max_k0": DUR_H / float(dur_max_k0),
        "depth_in_physical_window_pct": dphys, "sigma_pct": sphys}
    log(f"(f) a/R*={a_over_r:.2f} max dur k=0 {dur_max_k0:.2f} h, "
        f"k=bls {dur_max_kbls:.2f} h vs BLS {DUR_H:.2f} h; "
        f"physical-window depth {dphys:.2f}+-{sphys:.2f}%")
    del phase, cyc, in_tr, out_tr
    gc.collect()

    # ---------- Part 2: raw curve — 2P fold, wave, Fourier ----------
    tr, fr, nsec_r, npts_r = hunter._fetch_raw(TIC, max_sectors=20)
    log(f"raw: {npts_r} pts")
    ph2 = ((tr - T0) % P2) / P2  # 0..1, eclipses at 0.0 and 0.5
    ph2c = np.where(ph2 > 0.5, ph2 - 1.0, ph2)  # centered on eclipse A
    half_dur_ph = (DUR / 2.0) / P2
    eclA = np.abs(ph2c) <= half_dur_ph
    eclB = np.abs(ph2 - 0.5) <= half_dur_ph
    out_ecl = ~(eclA | eclB)
    dA, sA = depth_stats(fr[eclA], fr[out_ecl])
    dB, sB = depth_stats(fr[eclB], fr[out_ecl])
    diffB = dA - dB
    sdiffB = float(np.hypot(sA, sB))
    # Q-S: quadratures at 0.25/0.75 (+-0.06), shoulders just outside eclipses
    q = (np.abs(ph2 - 0.25) <= 0.06) | (np.abs(ph2 - 0.75) <= 0.06)
    sh = (((np.abs(ph2c) > half_dur_ph + 0.02) & (np.abs(ph2c) <= half_dur_ph + 0.10))
          | ((np.abs(ph2 - 0.5) > half_dur_ph + 0.02) & (np.abs(ph2 - 0.5) <= half_dur_ph + 0.10)))
    qs = (float(np.mean(fr[q])) - float(np.mean(fr[sh]))) / float(np.mean(fr[sh])) * 100.0
    qs_sig = float(np.hypot(np.std(fr[q], ddof=1) / np.sqrt(q.sum()),
                            np.std(fr[sh], ddof=1) / np.sqrt(sh.sum()))
                   / float(np.mean(fr[sh])) * 100.0)
    out["hand_double_period_raw"] = {
        "eclipseA_depth_pct": dA, "eclipseA_sigma_pct": sA,
        "eclipseB_depth_pct": dB, "eclipseB_sigma_pct": sB,
        "pair_difference_pct": diffB, "pair_difference_sigma": sdiffB,
        "pair_difference_significance": diffB / sdiffB if sdiffB else None,
        "quadrature_minus_shoulder_pct": qs, "qs_sigma_pct": qs_sig,
        "qs_significance": qs / qs_sig if qs_sig else None}
    log(f"(b) pair A {dA:.3f}+-{sA:.3f}%  B {dB:.3f}+-{sB:.3f}%  "
        f"diff {diffB:+.3f}% ({diffB/sdiffB:.2f} sigma); "
        f"Q-S {qs:+.3f}+-{qs_sig:.3f}% ({qs/qs_sig:.1f} sigma)")

    # sine fit at P (ellipsoidal semi-amplitude), eclipses masked
    mfit = out_ecl
    w = 2 * np.pi / P
    X = np.column_stack([np.ones(mfit.sum()),
                         np.cos(w * tr[mfit]), np.sin(w * tr[mfit])])
    yv = fr[mfit]
    coef, *_ = np.linalg.lstsq(X, yv, rcond=None)
    resid = yv - X @ coef
    dof = max(1, mfit.sum() - 3)
    s2 = float(resid @ resid) / dof
    cov = s2 * np.linalg.inv(X.T @ X)
    amp = float(np.hypot(coef[1], coef[2])) / float(coef[0]) * 100.0
    amp_sig = float(np.sqrt((coef[1] ** 2 * cov[1, 1] + coef[2] ** 2 * cov[2, 2])
                            / max(coef[1] ** 2 + coef[2] ** 2, 1e-30))) \
        / float(coef[0]) * 100.0
    out["ellipsoidal_sine_fit_at_P"] = {
        "semi_amplitude_pct": amp, "sigma_pct": amp_sig,
        "significance": amp / amp_sig if amp_sig else None,
        "note": "sinusoid at the candidate period P (the ellipsoidal "
                "frequency for an orbit at 2P), eclipses masked, raw curve"}
    log(f"(b) sine at P: semi-amp {amp:.3f}+-{amp_sig:.3f}% "
        f"({amp/amp_sig:.1f} sigma)")

    # (4) Lomb-Scargle context on raw curve
    ls = LombScargle(tr, fr, normalization="standard")
    freq, power = ls.autopower(minimum_frequency=1.0 / 30.0,
                               maximum_frequency=1.0 / 0.1,
                               samples_per_peak=10)
    per = 1.0 / freq
    top_idx = np.argsort(power)[::-1][:400]
    peaks, used = [], []
    for i in top_idx:
        if any(abs(per[i] - u_) / per[i] < 0.01 for u_ in used):
            continue
        used.append(float(per[i]))
        peaks.append({"period_days": float(per[i]), "power": float(power[i])})
        if len(peaks) >= 6:
            break
    out["lomb_scargle_raw_top_peaks"] = peaks
    for lab, pc in (("P", P), ("2P", P2)):
        j = int(np.argmin(np.abs(per - pc)))
        out[f"lomb_scargle_power_near_{lab}"] = {
            "period_days": float(per[j]), "power": float(power[j])}
    # harmonic fit at base 2P: A1 (freq 1/P2) and A2 (freq 2/P2 = 1/P)
    w1 = 2 * np.pi / P2
    Xh = np.column_stack([np.ones(len(tr)), np.cos(w1 * tr), np.sin(w1 * tr),
                          np.cos(2 * w1 * tr), np.sin(2 * w1 * tr)])
    ch, *_ = np.linalg.lstsq(Xh, fr, rcond=None)
    base = float(ch[0])
    out["harmonic_fit_base_2P"] = {
        "A1_pct": float(np.hypot(ch[1], ch[2])) / base * 100.0,
        "A2_pct": float(np.hypot(ch[3], ch[4])) / base * 100.0,
        "note": "A2 (ellipsoidal harmonic) vs A1 at the 2P base period, raw curve, eclipses included"}
    log(f"(4) LS top: {[(round(p['period_days'],4), round(p['power'],3)) for p in peaks[:4]]}; "
        f"A1 {out['harmonic_fit_base_2P']['A1_pct']:.3f}%  "
        f"A2 {out['harmonic_fit_base_2P']['A2_pct']:.3f}%")
    del tr, fr, ph2, ph2c, eclA, eclB, out_ecl, q, sh, X, Xh, ls, freq, power, per
    gc.collect()

    # ---------- Part 3: raw per-sector era split ----------
    def _search():
        s = lk.search_lightcurve(f"TIC {TIC}", author=["SPOC", "TESS-SPOC", "QLP"])
        if len(s) == 0:
            s = lk.search_lightcurve(f"TIC {TIC}")
        return s

    search = hunter._with_download_self_heal(_search, None)
    coll = hunter._download_products(search, TIC, None)
    log(f"era split: {len(coll)} products downloaded")
    seen, sec_rows = set(), []
    for lc in coll:
        sec = lc.meta.get("SECTOR")
        if sec is None:
            continue
        sec = int(sec)
        if sec in seen:
            continue
        seen.add(sec)
        tt = np.asarray(lc.time.value, dtype=float)
        ff = np.asarray(lc.flux.value, dtype=float)
        ok = np.isfinite(tt) & np.isfinite(ff)
        tt, ff = tt[ok], ff[ok]
        med = float(np.median(ff))
        ff = ff / med
        ph = ((tt - T0 + 0.5 * P) % P) - 0.5 * P
        i_m = np.abs(ph) <= DUR / 2.0
        o_m = (np.abs(ph) > DUR) & (np.abs(ph) < P - DUR)
        if i_m.sum() >= 20 and o_m.sum() >= 100:
            d, s = depth_stats(ff[i_m], ff[o_m])
            sec_rows.append({"sector": sec,
                             "author": str(lc.meta.get("AUTHOR", "?")),
                             "depth_pct": d, "sigma_pct": s,
                             "signif": d / s if s else None,
                             "n_in": int(i_m.sum()), "n_out": int(o_m.sum())})
        del tt, ff, ph, i_m, o_m
    del coll
    gc.collect()
    sec_rows.sort(key=lambda r: r["sector"])
    out["raw_flux_per_sector"] = sec_rows

    def agg(rows):
        if not rows:
            return {"n_sectors": 0, "weighted_mean_depth_pct": None,
                    "weighted_mean_sigma_pct": None, "significance_sigma": None}
        d = np.array([r["depth_pct"] for r in rows])
        sg = np.array([max(r["sigma_pct"], 1e-6) for r in rows])
        wgt = 1.0 / sg ** 2
        wm = float(np.sum(wgt * d) / np.sum(wgt))
        ws = float(1.0 / np.sqrt(np.sum(wgt)))
        return {"n_sectors": len(rows), "weighted_mean_depth_pct": wm,
                "weighted_mean_sigma_pct": ws,
                "significance_sigma": wm / ws if ws else None}

    eras = {"le_26": [r for r in sec_rows if r["sector"] <= 26],
            "27_59": [r for r in sec_rows if 27 <= r["sector"] <= 59],
            "ge_60": [r for r in sec_rows if r["sector"] >= 60]}
    out["raw_flux_era_split"] = {k: agg(v) for k, v in eras.items()}
    out["raw_flux_overall"] = agg(sec_rows)
    for k, v in out["raw_flux_era_split"].items():
        log(f"(d) era {k}: n={v['n_sectors']} wmean={v['weighted_mean_depth_pct']} "
            f"+-{v['weighted_mean_sigma_pct']} ({v['significance_sigma']} sigma)")
    log(f"(d) overall raw: {out['raw_flux_overall']}")

    (OUTDIR / f"{TIC}_hand.json").write_text(json.dumps(out, indent=2, default=str))
    log("hand checks DONE")


if __name__ == "__main__":
    main()
