#!/usr/bin/env python
"""VSX filing-packet measurements for TIC 167367406 (EW contact binary).

Standalone: reads the cached QLP FITS directly (no hunter.py import),
per-sector median-normalizes exactly like the vetting stitch, then:
  * harmonic (k=1..4) period refinement around P_orb = 0.43461013 d
  * epoch of the primary minimum nearest mid-baseline (BJD_TDB)
  * orbital-fold window depths + harmonic-model extrema
  * TESS magnitudes anchored on the TIC Tmag (mean-flux convention)
  * phase-fold supporting plot (TIC167367406_fold.png)
Outputs vetting_results/167367406_vsx_packet.json.
"""
import gc
import glob
import json
import time
import warnings
from pathlib import Path

import numpy as np

warnings.filterwarnings("ignore")
BASE = Path(__file__).resolve().parent
OUTDIR = BASE / "vetting_results"
CACHE = Path.home() / ".cache/lightkurve/mastDownload/HLSP"

TIC = "167367406"
TMAG = 14.2054            # TIC Tmag (catalog sidecar)
GMEAN_TIC = 15.3689       # TIC GAIAmag
GMEAN_DR3 = 15.353328     # Gaia DR3 phot_g_mean_mag (cross-check JSON)
P_ORB0 = 2.0 * (0.6519151915191519 / 3.0)   # 0.4346101276794346
NHARM = 4


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def load_curve():
    files = sorted(glob.glob(str(CACHE / "*167367406*_llc" / "*_llc.fits")))
    assert len(files) == 18, f"expected 18 cached sectors, found {len(files)}"
    from astropy.io import fits
    ts, fs, es, secs = [], [], [], []
    for fp in files:
        sec = int(Path(fp).name.split("_s")[1][:4])
        with fits.open(fp) as h:
            d = h[1].data
            cols = [c.name for c in d.columns]
            fcol = next(c for c in ("KSPSAP_FLUX", "DET_FLUX", "PDCSAP_FLUX",
                                    "SAP_FLUX") if c in cols)
            ecol = fcol + "_ERR" if fcol + "_ERR" in cols else None
            t = np.asarray(d["TIME"], dtype=np.float64)
            f = np.asarray(d[fcol], dtype=np.float32)
            e = (np.asarray(d[ecol], dtype=np.float32) if ecol
                 else np.full(len(t), np.nan, dtype=np.float32))
            q = np.asarray(d["QUALITY"])
        m = np.isfinite(t) & np.isfinite(f) & (q == 0)
        t, f, e = t[m], f[m], e[m]
        med = np.median(f)
        f = (f / med).astype(np.float32)
        e = (e / med).astype(np.float32)
        ts.append(t); fs.append(f); es.append(e); secs.append(sec)
        log(f"sector {sec}: {len(t)} pts")
        del d, m
        gc.collect()
    t = np.concatenate(ts); f = np.concatenate(fs); e = np.concatenate(es)
    order = np.argsort(t)
    t, f, e = t[order], f[order], e[order]
    # global 5-sigma clip (std inflated by the signal itself; kills rays only)
    med = np.median(f); sd = np.std(f)
    keep = np.abs(f - med) < 5.0 * sd
    log(f"stitched {len(t)} pts, clip removed {int((~keep).sum())}")
    return t[keep], f[keep], e[keep], secs


def design(t, P, tc, nharm=NHARM):
    x = (t - tc) / P
    cols = [np.ones_like(x)]
    for k in range(1, nharm + 1):
        cols.append(np.cos(2 * np.pi * k * x))
        cols.append(np.sin(2 * np.pi * k * x))
    return np.column_stack(cols)


def fit_chi2(t, y, P, tc):
    X = design(t, P, tc)
    XtX = X.T @ X
    Xty = X.T @ y
    coef = np.linalg.solve(XtX, Xty)
    r = y - X @ coef
    return float(r @ r), coef, XtX


def scan_period(t, y, tc, lo, hi, n):
    best = (np.inf, None)
    grid = np.linspace(lo, hi, n)
    chis = np.empty(n)
    for i, P in enumerate(grid):
        c, _, _ = fit_chi2(t, y, P, tc)
        chis[i] = c
        if c < best[0]:
            best = (c, P)
    return grid, chis, best


def main():
    out = {"tic": TIC, "stage": "vsx_filing_packet_measurements"}
    t, f, e, secs = load_curve()
    out["sectors"] = secs
    out["n_points"] = int(len(t))
    out["baseline_btjd"] = [float(t.min()), float(t.max())]
    out["baseline_days"] = float(t.max() - t.min())
    tc = 0.5 * (t.min() + t.max())
    out["tc_btjd"] = float(tc)
    fmean = float(np.mean(f))
    out["mean_flux_norm"] = fmean
    log(f"baseline BTJD {t.min():.2f}..{t.max():.2f} ({out['baseline_days']:.1f} d), "
        f"mean flux {fmean:.5f}")

    # ---- period refinement: two-stage harmonic chi2 scan
    g1, c1, (chi1, p1) = scan_period(t, f, tc, P_ORB0 * 0.998, P_ORB0 * 1.002, 201)
    step1 = g1[1] - g1[0]
    g2, c2, (chi2, p2) = scan_period(t, f, tc, p1 - 2 * step1, p1 + 2 * step1, 201)
    step2 = g2[1] - g2[0]
    # uncertainty: parabola on chi2 near min, scaled so reduced chi2 = 1
    i0 = int(np.argmin(c2))
    dof = len(t) - (2 * NHARM + 1)
    scale = chi2 / dof
    # find where chi2 - min = scale (delta chi2 = 1 after scaling)
    target = chi2 + scale
    il = i0
    while il > 0 and c2[il] < target:
        il -= 1
    ir = i0
    while ir < len(c2) - 1 and c2[ir] < target:
        ir += 1
    sig_p = 0.5 * (g2[ir] - g2[il]) if ir > il else step2
    P = float(p2)
    out["period"] = {"value_d": P, "sigma_d": float(sig_p),
                     "method": "two-stage chi2 scan, harmonic k=1..4 fit, "
                               "unweighted, per-sector median-normalized QLP KSPSAP",
                     "scan_chi2_min": float(chi2), "dof": int(dof),
                     "photometric_cycle_d": P / 2.0}
    log(f"P_orb = {P:.8f} +- {sig_p:.2e} d (photo cycle {P/2:.8f})")

    # ---- final fit at P, phase referenced to tc
    chi, coef, XtX = fit_chi2(t, f, P, tc)
    resid = f - design(t, P, tc) @ coef
    s2 = float(resid @ resid) / dof
    cov = s2 * np.linalg.inv(XtX)
    out["fit"] = {"coef": [float(c) for c in coef], "resid_rms": float(np.sqrt(s2))}

    phg = np.linspace(0, 1, 20001, endpoint=False)

    def model(ph, cf):
        m = np.full(ph.shape, cf[0])
        for k in range(1, NHARM + 1):
            m = m + cf[2 * k - 1] * np.cos(2 * np.pi * k * ph) \
                  + cf[2 * k] * np.sin(2 * np.pi * k * ph)
        return m

    mg = model(phg, coef)
    imin = int(np.argmin(mg))
    phi_I = float(phg[imin])
    # secondary minimum: deepest point within +-0.15 phase of phi_I+0.5
    dphi = np.abs(((phg - (phi_I + 0.5) + 0.5) % 1.0) - 0.5)
    cand = np.where(dphi < 0.15)[0]
    phi_II = float(phg[cand[int(np.argmin(mg[cand]))]])
    imax = int(np.argmax(mg))
    phi_max = float(phg[imax])
    out["model_extrema_flux"] = {
        "min_I": float(mg[imin]), "phi_I": phi_I,
        "min_II": float(model(np.array([phi_II]), coef)[0]), "phi_II": phi_II,
        "max": float(mg[imax]), "phi_max": phi_max}

    # ---- Monte Carlo over coefficient covariance (+ period jitter)
    rng = np.random.default_rng(20261106)
    draws = rng.multivariate_normal(coef, cov, size=300)
    pj = rng.normal(P, sig_p, size=300)
    phiI_d, minI_d, minII_d, max_d = [], [], [], []
    for cf, pp in zip(draws, pj):
        mm = model(phg, cf)
        ii = int(np.argmin(mm))
        pI = float(phg[ii])
        dd = np.abs(((phg - (pI + 0.5) + 0.5) % 1.0) - 0.5)
        cc = np.where(dd < 0.15)[0]
        phiI_d.append(pI); minI_d.append(float(mm[ii]))
        minII_d.append(float(mm[cc[int(np.argmin(mm[cc]))]]))
        max_d.append(float(mm.max()))
    phiI_d = np.array(phiI_d)
    # unwrap phase draws around the median
    med_phi = np.median(phiI_d)
    phiI_u = med_phi + ((phiI_d - med_phi + 0.5) % 1.0 - 0.5)
    sig_phi = float(np.std(phiI_u))
    out["mc"] = {"n": 300, "sigma_phi_I": sig_phi,
                 "min_I_flux_sigma": float(np.std(minI_d)),
                 "min_II_flux_sigma": float(np.std(minII_d)),
                 "max_flux_sigma": float(np.std(max_d))}

    # ---- epoch: primary minimum nearest tc THAT HAS DATA COVERAGE
    n_cyc = int(round(-phi_I))
    epoch_btjd, n_use = None, n_cyc
    for dn in range(0, 40):
        for nn in ((n_cyc,) if dn == 0 else (n_cyc + dn, n_cyc - dn)):
            e0 = tc + (phi_I + nn) * P
            if np.sum(np.abs(t - e0) < 0.25 * P) >= 50:
                epoch_btjd, n_use = float(e0), int(nn)
                break
        if epoch_btjd is not None:
            break
    assert epoch_btjd is not None, "no covered primary minimum near mid-baseline"
    sig_epoch = float(np.hypot(sig_phi * P, abs(n_use) * sig_p))
    out["epoch"] = {"btjd": epoch_btjd, "bjd_tdb": epoch_btjd + 2457000.0,
                    "sigma_d": sig_epoch, "cycle_offset_from_tc": n_use}
    log(f"epoch primary min: BTJD {epoch_btjd:.5f} (BJD {epoch_btjd+2457000:.5f}) "
        f"+- {sig_epoch:.5f} (cycle {n_use:+d} from tc)")

    # direct check: observed data in the cycle of the epoch, parabola on binned bottom
    tt = t - epoch_btjd
    sel = np.abs(tt) < 0.30 * P
    if sel.sum() > 50:
        phn = (tt[sel] / P)
        bins = np.linspace(-0.3, 0.3, 31)
        idx = np.digitize(phn, bins)
        bc, bf = [], []
        for b in range(1, len(bins)):
            m_ = idx == b
            if m_.sum() > 5:
                bc.append(0.5 * (bins[b - 1] + bins[b])); bf.append(np.median(f[sel][m_]))
        bc = np.array(bc); bf = np.array(bf)
        if len(bc) >= 4:
            bot = np.argsort(bf)[:6]
            A = np.polyfit(bc[bot], bf[bot], 2)
            obs_c = -A[1] / (2 * A[0])
            out["epoch"]["observed_cycle0_min_phase_offset"] = float(obs_c)
            log(f"observed epoch-cycle minimum offset from fitted epoch: "
                f"{obs_c:+.4f} cycles")
        else:
            out["epoch"]["observed_cycle0_min_phase_offset"] = None

    # ---- binned orbital profile (phase 0 = primary minimum)
    ph = ((t - epoch_btjd) % P) / P
    nb = 100
    prof = []
    for i in range(nb):
        lo, hi = i / nb, (i + 1) / nb
        m_ = (ph >= lo) & (ph < hi)
        prof.append({"phase_c": 0.5 * (lo + hi),
                     "mean": float(np.mean(f[m_])),
                     "se": float(np.std(f[m_]) / np.sqrt(m_.sum())),
                     "n": int(m_.sum())})
    out["profile_100bins"] = prof

    def window(c, halfw=0.06):
        dd = np.abs(((np.array([p["phase_c"] for p in prof]) - c + 0.5) % 1.0) - 0.5)
        sel = [prof[i] for i in range(nb) if dd[i] <= halfw]
        w = np.array([1.0 / s["se"] ** 2 for s in sel])
        v = np.array([s["mean"] for s in sel])
        return float(np.sum(w * v) / np.sum(w)), float(np.sqrt(1.0 / np.sum(w)))

    fmax_w = None
    # maxima plateaus: windows centred 0.25 and 0.75, averaged
    a = window(0.25, 0.07); b = window(0.75, 0.07)
    fmax_w = 0.5 * (a[0] + b[0]); fmax_w_se = 0.5 * float(np.hypot(a[1], b[1]))
    fI_w, fI_w_se = window(0.0)
    fII_w, fII_w_se = window(0.5)
    out["window_flux"] = {"max_plateau": fmax_w, "max_plateau_se": fmax_w_se,
                          "min_I": fI_w, "min_I_se": fI_w_se,
                          "min_II": fII_w, "min_II_se": fII_w_se}
    for lab, fv, fse in (("I", fI_w, fI_w_se), ("II", fII_w, fII_w_se)):
        dep = 1.0 - fv / fmax_w
        dse = float(np.hypot(fse / fmax_w, fv * fmax_w_se / fmax_w ** 2))
        out[f"depth_window_min_{lab}"] = {"depth_frac": float(dep),
                                          "depth_pct": float(dep * 100),
                                          "sigma_pct": float(dse * 100)}
        log(f"window depth min {lab}: {dep*100:.3f} +- {dse*100:.3f} %")
    # model depths (vs model max)
    mx = out["model_extrema_flux"]
    for lab, key in (("I", "min_I"), ("II", "min_II")):
        dep = 1.0 - mx[key] / mx["max"]
        out[f"depth_model_min_{lab}"] = {"depth_frac": float(dep),
                                         "depth_pct": float(dep * 100)}
        log(f"model depth min {lab}: {dep*100:.3f} %")

    # ---- magnitudes: mean-flux anchored on TIC Tmag
    def mag(flux, f_sig=0.0):
        m = TMAG - 2.5 * np.log10(flux / fmean)
        s = 2.5 / np.log(10) * f_sig / flux if f_sig else 0.0
        return float(m), float(s)
    mags = {}
    mmax, smax = mag(mx["max"], out["mc"]["max_flux_sigma"])
    mI, smI = mag(mx["min_I"], out["mc"]["min_I_flux_sigma"])
    mII, smII = mag(mx["min_II"], out["mc"]["min_II_flux_sigma"])
    mags["TESS"] = {"max": mmax, "max_sigma": smax,
                    "min_I": mI, "min_I_sigma": smI,
                    "min_II": mII, "min_II_sigma": smII,
                    "convention": "phase-averaged (mean) flux set equal to TIC "
                                  "Tmag 14.2054; extrema from the k=1..4 harmonic "
                                  "model of the orbital fold"}
    for band_mean, lab in ((GMEAN_TIC, "G_est_from_TIC_GAIAmag"),
                           (GMEAN_DR3, "G_est_from_DR3_phot_g_mean")):
        mags[lab] = {"mean": band_mean,
                     "max": band_mean + (mmax - TMAG),
                     "min_I": band_mean + (mI - TMAG),
                     "min_II": band_mean + (mII - TMAG),
                     "caveat": "assumes the same fractional amplitude as in the "
                               "TESS band; G is bluer, true G amplitude may differ"}
    out["magnitudes"] = mags
    log(f"TESS mags: max {mmax:.3f}  minI {mI:.3f}  minII {mII:.3f}")

    # ---- supporting plot
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    rng2 = np.random.default_rng(7)
    sub = rng2.choice(len(t), size=min(25000, len(t)), replace=False)
    fig, ax = plt.subplots(figsize=(9, 5.2))
    ax.plot(ph[sub], f[sub], ".", ms=1.5, color="0.75", alpha=0.35, zorder=1)
    pc = np.array([p["phase_c"] for p in prof]); pm = np.array([p["mean"] for p in prof])
    ax.plot(np.concatenate([pc - 1, pc, pc + 1]),
            np.concatenate([pm, pm, pm]), "o-", ms=3.5, lw=1.2,
            color="black", zorder=3, label="binned profile (100 bins)")
    phx = np.linspace(-0.05, 1.05, 600)
    # model coefficients are tc-referenced; epoch-referenced phase ph has
    # model argument u = ph + phi_I (epoch = tc + phi_I * P, cycle 0)
    ax.plot(phx, model((phx + phi_I) % 1.0, coef), "-", lw=1.4, color="firebrick",
            zorder=4, label="harmonic model (k=1–4)")
    ax.axvline(0.0, color="steelblue", lw=0.9, ls="--")
    ax.axvline(0.5, color="steelblue", lw=0.9, ls=":")
    ax.axvline(1.0, color="steelblue", lw=0.9, ls="--")
    ax.text(0.0, ax.get_ylim()[0], " Min I", color="steelblue", fontsize=9,
            va="bottom", ha="left")
    ax.text(0.5, ax.get_ylim()[0], " Min II", color="steelblue", fontsize=9,
            va="bottom", ha="left")
    ax.set_xlim(-0.05, 1.05)
    ax.set_xlabel("Phase (0 = primary minimum)")
    ax.set_ylabel("Relative flux (per-sector median-normalized)")
    ax.set_title(f"TIC 167367406 — EW contact binary, P = {P:.5f} d\n"
                 f"TESS QLP, 18 sectors; epoch BJD_TDB {epoch_btjd + 2457000:.4f}")
    ax.legend(loc="upper center", fontsize=9)
    fig.tight_layout()
    png = BASE / "TIC167367406_fold.png"
    fig.savefig(png, dpi=150)
    out["plot_png"] = str(png)
    log(f"plot saved: {png}")

    (OUTDIR / f"{TIC}_vsx_packet.json").write_text(json.dumps(out, indent=2, default=str))
    log("packet measurements DONE")


if __name__ == "__main__":
    main()
