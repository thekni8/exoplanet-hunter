#!/usr/bin/env python3
"""Raw-flux desk check for one filed persistent hit (gauntlet step 2).

Method = the raw-flux stage of the TIC 294873918 vetting:
* download every product family that exists (ELEANOR-lite / QLP / SPOC /
  TESS-SPOC) sector by sector, raw product flux, quality==0 only;
* replicate the sweep's own chain (SG flatten ~2.0 d + BLS v2 + pass-2
  transit-masked re-flatten, stage8-style) on the pipeline-selected
  product set (the _select_products rule: most sectors wins, priority
  SPOC > TESS-SPOC > QLP, earliest N) to recover the FILED ephemeris
  (t0, duration at the filed period) and the pass-1 vs pass-2 behaviour;
* fold the RAW flux (per-sector median-normalised, asymmetric 5-sigma
  clip with the lower cut floored at 10% below the median so deep
  transits on quiet stars survive, NO transit-scale detrend) at the
  filed period + recovered ephemeris
  and measure the dip: primary = filed-duration window, medians,
  chunked red-noise significance (persistence.py style); secondary =
  stage2-style 0.15-phase window for comparability with the 294873918
  numbers;
* verdict vs the filed depth: RAW-CONFIRMED (raw >= 50% of filed at
  >= 3 sigma), RAW-WEAK (real but much shallower / marginal),
  RAW-REFUTED (no dip — pipeline artefact).
* shape gate (2026-11-13): a symmetric trapezoid fit to the folded
  raw flux measures the flat-bottom fraction T23/T14 (V vs U) and
  the true first-to-fourth-contact duration T14, and checks the
  circular-orbit stellar density implied by (P, T14) against the TIC
  density. A V-shaped transit with a density mismatch is a grazing
  EB suspect, not a planet — this is the test that would have caught
  TIC 423498314 at the desk instead of after publication.

Usage:
  # sweep hit (filed ephemeris recovered by replication):
  rawflux_check.py TIC --result-json result.json --workdir work/TIC
  # bulk survivor / ad-hoc (explicit ephemeris, no replication):
  rawflux_check.py TIC --period P --depth D --t0 T0 --duration DUR \
      --skip-replication --workdir work/TIC
  # cached data only (no MAST downloads):
  rawflux_check.py TIC --result-json result.json --workdir work/TIC \
      --data-dir data/ --no-download

Writes WORKDIR/data/*.npz, WORKDIR/rawflux_results.json, WORKDIR/folds.png

Environment: RAWF_RHO_STAR overrides the TIC stellar density (solar
units) used by the shape gate's density check.

Generalised from the canonical desk check (2026-11-10, trapezoid gate +
phase fix 2026-11-13). The computational functions are unchanged; only
the inputs moved from positional argv to argparse.
"""
import argparse
import gc
import json
import math
import os
import sys
import warnings

warnings.filterwarnings('ignore')
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Module globals set by main() and read by the download helpers.
TIC = None
DATA = None

import lightkurve as lk  # noqa: E402

AUTHORS = [('GSFC-ELEANOR-LITE', 'elc'), ('QLP', 'qlp'),
           ('SPOC', 'spoc'), ('TESS-SPOC', 'tspc')]
PRIO = {'spoc': 0, 'tspc': 1, 'qlp': 2}  # production priority order


def download_author(author, pfx, no_download=False):
    """One npz per sector (earliest products; SPOC prefers 120 s rows)."""
    if no_download:
        # cached-only mode: never touch MAST, just inventory DATA
        import glob as _glob
        got = sorted(int(os.path.basename(p)[len(pfx) + 2:-4])
                     for p in _glob.glob(os.path.join(DATA, f'{pfx}_s*.npz')))
        print(f'{author}: cached sectors {got}', flush=True)
        return got
    try:
        sr = lk.search_lightcurve(f'TIC {TIC}', author=author)
    except Exception as e:
        print(f'{author}: search failed {e}', flush=True)
        return []
    if len(sr) == 0:
        print(f'{author}: no rows', flush=True)
        return []
    tbl = sr.table
    by_sector = {}
    for i in range(len(sr)):
        try:
            sec = int(tbl['sequence_number'][i])
            exp = float(tbl['exptime'][i])
        except Exception:
            continue
        cur = by_sector.get(sec)
        if cur is None or (exp == 120.0 and float(tbl['exptime'][cur]) != 120.0):
            by_sector[sec] = i
    got = []
    for sec in sorted(by_sector):
        fn = os.path.join(DATA, f'{pfx}_s{sec:03d}.npz')
        if os.path.exists(fn):
            got.append(sec)
            continue
        lc = None
        for attempt in range(3):
            try:
                lc = sr[by_sector[sec]].download()
                if lc is not None:
                    break
            except Exception as e:
                print(f'{author} s{sec}: download attempt {attempt} failed '
                      f'{type(e).__name__}', flush=True)
                lc = None
        if lc is None:
            print(f'{author} s{sec}: NO DATA', flush=True)
            continue
        t_all = np.asarray(lc.time.value, dtype=float)
        f_all = np.asarray(lc.flux.value, dtype=float)
        q = getattr(lc, 'quality', None)
        m = np.isfinite(t_all) & np.isfinite(f_all)
        if q is not None:
            try:
                m &= (np.asarray(q) == 0)
            except Exception:
                pass
        if m.sum() < 100:
            print(f'{author} s{sec}: too few good points', flush=True)
            continue
        np.savez_compressed(fn, time=t_all[m], flux=f_all[m].astype(np.float32))
        got.append(sec)
        print(f'{author} s{sec}: ok {int(m.sum())} pts', flush=True)
        del lc
        gc.collect()
    print(f'{author}: sectors {got}', flush=True)
    return got


def load_stitched(pfx, secs):
    ts, fs, spans = [], [], []
    for s in secs:
        z = np.load(os.path.join(DATA, f'{pfx}_s{s:03d}.npz'))
        t = np.asarray(z['time'], dtype=float)
        f = np.asarray(z['flux'], dtype=float)
        f = f / np.median(f)
        ts.append(t); fs.append(f)
        spans.append((s, float(t.min()), float(t.max())))
    t = np.concatenate(ts); f = np.concatenate(fs)
    o = np.argsort(t); t, f = t[o], f[o]
    med = np.median(f); sig = 1.4826 * np.median(np.abs(f - med))
    # Asymmetric clip (2026-11-14, TIC 139526205): the lower cut is
    # floored at 10% below the median. A symmetric 5-sigma cut deletes
    # real transits on quiet stars — a 6% eclipse on a 0.08%-MAD star
    # is 75 sigma, so every in-transit point was clipped and the star
    # read as refuted; even a 0.5% transit loses most of its points.
    # Genuine outliers (excursions >> 10%) are still clipped both sides.
    keep = (f < med + 5 * sig) & (f > med - max(5 * sig, 0.10))
    return t[keep], f[keep], spans


# ---------------- BLS replication (stage8) on the pipeline set ------------
SYST = (13.7, 6.85, 27.4)


def robust_sde(powers, pv):
    keepm = np.ones(len(powers), dtype=bool)
    for s_ in SYST:
        keepm &= np.abs(pv - s_) > 0.03 * s_
    base = powers[keepm]
    m_ = float(np.median(base))
    mad = float(np.median(np.abs(base - m_))) * 1.4826
    return m_, (mad if mad > 0 else float(np.std(base)))


def bls(tt, ff, period_at, n_grid=30000):
    import astropy.units as u
    from astropy.timeseries import BoxLeastSquares
    periods = (1.0 / np.linspace(1.0 / 25.0, 1.0 / 0.5, n_grid)) * u.day
    durations = np.linspace(0.03, 0.25, 14) * u.day
    model = BoxLeastSquares(tt * u.day, ff)
    res = model.power(periods, durations)
    pv = np.asarray(res.period.value, dtype=float)
    pw = np.asarray(res.power, dtype=float)
    m_, sc = robust_sde(pw, pv)
    sde = (pw - m_) / sc
    i = int(np.argmax(sde))
    j = int(np.argmin(np.abs(pv - period_at)))
    return {
        'best_period': float(pv[i]), 'best_sde': float(sde[i]),
        'best_depth_pct': float(res.depth[i]) * 100,
        'best_dur_d': float(res.duration[i].value),
        'best_t0': float(res.transit_time[i].value),
        'at_filed_period': float(pv[j]), 'sde_at_filed': float(sde[j]),
        'depth_at_filed_pct': float(res.depth[j]) * 100,
        'dur_at_filed_d': float(res.duration[j].value),
        't0_at_filed': float(res.transit_time[j].value),
    }


def flatten_with(tt, ff, target_days, mask=None):
    dt = float(np.median(np.diff(tt)))
    win = int(round(target_days / dt))
    win += (win % 2 == 0)
    win = int(min(max(win, 31), 4001))
    lc = lk.LightCurve(time=tt, flux=ff)
    flat = lc.flatten(window_length=win, mask=mask) if mask is not None \
        else lc.flatten(window_length=win)
    return (np.asarray(flat.time.value), np.asarray(flat.flux.value), win)


def phase_days(t, P, T0):
    return ((t - T0 + 0.5 * P) % P) - 0.5 * P


def raw_measure(pfx, secs, P, T0, DUR):
    """Primary (filed-duration window, chunked red-noise sigma) +
    stage2-style (0.15 phase window) raw depths for one product set."""
    t, f, spans = load_stitched(pfx, secs)
    ph = phase_days(t, P, T0)
    out_d = {'pfx': pfx, 'sectors': secs, 'n_points': int(len(t))}
    # primary: filed-duration window
    inm = np.abs(ph) <= DUR / 2.0
    outm = np.abs(ph) > DUR
    if inm.sum() >= 20 and outm.sum() >= 50:
        dep = (np.median(f[outm]) - np.median(f[inm])) * 100.0
        # chunked red-noise sigma: chunks of width DUR within each sector
        chunk_means = []
        for _s, t0s, t1s in spans:
            sm = (t >= t0s) & (t <= t1s) & outm
            tt, fv = t[sm], f[sm]
            if len(tt) < 3:
                continue
            idx = np.floor((tt - t0s) / DUR).astype(int)
            for c in np.unique(idx):
                v = fv[idx == c]
                if len(v) >= 3:
                    chunk_means.append(float(np.mean(v)))
        n_events = len(np.unique(np.round((t[inm] - T0) / P))) if inm.any() else 0
        if len(chunk_means) > 1 and n_events >= 1:
            csig = float(np.std(chunk_means, ddof=1)) * 100.0
            sig = csig * np.sqrt(1.0 / n_events + 1.0 / len(chunk_means))
            out_d.update({'depth_pct': float(dep), 'sigma_pct': float(sig),
                          'signif': float(dep / sig) if sig > 0 else None,
                          'n_events': int(n_events),
                          'n_chunks': len(chunk_means)})
        else:
            out_d.update({'depth_pct': float(dep), 'sigma_pct': None,
                          'signif': None})
    # secondary: stage2-style 0.15-phase window, white-noise sigma
    inn2 = np.abs(ph) < 0.15 * P
    out2 = (np.abs(ph) > 0.36 * P) & (np.abs(ph) < 0.5 * P)
    if inn2.sum() >= 20 and out2.sum() >= 50:
        d2 = (np.median(f[out2]) - np.median(f[inn2])) * 100.0
        s2 = np.std(f[inn2]) / np.sqrt(inn2.sum()) * 100.0
        out_d.update({'depth15_pct': float(d2),
                      'signif15': float(d2 / s2) if s2 > 0 else None})
    # per-sector primary depths (pipeline set gets the full table)
    rows = []
    for s in secs:
        z = np.load(os.path.join(DATA, f'{pfx}_s{s:03d}.npz'))
        tt = np.asarray(z['time'], dtype=float)
        fv0 = np.asarray(z['flux'], dtype=float)
        fv = fv0 / np.median(fv0)
        phs = phase_days(tt, P, T0)
        im = np.abs(phs) <= DUR / 2.0
        om = np.abs(phs) > DUR
        if im.sum() >= 10 and om.sum() >= 30:
            dd = (np.median(fv[om]) - np.median(fv[im])) * 100.0
            ss = np.std(fv[im]) / np.sqrt(im.sum()) * 100.0
            rows.append({'sector': s, 'depth_pct': round(float(dd), 3),
                         'signif_white': round(float(dd / ss), 1) if ss > 0 else None})
        else:
            rows.append({'sector': s, 'depth_pct': None, 'signif_white': None})
    out_d['per_sector'] = rows
    # fold profile (60 bins) for the record — CENTRED phase frame.
    # (2026-11-13 fix: the old [0,1) binning put the transit at bins
    # 0/59 while folds.png and self_anchor assumed a [-0.5,0.5) frame
    # with the transit at phase 0 — the plot showed the transit split
    # across the edges and a correctly-anchored transit read as ~0.5
    # off. Bin i now spans [-0.5+i/60, -0.5+(i+1)/60), so its centre
    # is exactly the plot axis xs and the self_anchor formula below.
    # Diagnostic-only: depth/signif above use phase_days masks and
    # are untouched by this change.)
    bins = np.linspace(-0.5, 0.5, 61)
    phr = ((t - T0 + 0.5 * P) % P) / P - 0.5
    idx = np.digitize(phr, bins) - 1
    prof = [None if (idx == i).sum() <= 20 else
            round(float((np.median(f[idx == i]) - 1) * 100), 3)
            for i in range(60)]
    out_d['fold_profile_pct'] = prof
    del t, f
    gc.collect()
    return out_d


# ---------------- trapezoid shape gate (2026-11-13, Gemini fix #1) -----
# TIC 423498314 post-mortem: the desk's shape test compared box vs
# sinusoid and called a V-shaped grazing transit a "clean box", because
# a V is not a wave. The gate below fits a symmetric trapezoid to the
# folded RAW flux and measures (a) the flat-bottom fraction T23/T14
# and (b) the true first-to-fourth-contact duration T14 — the BLS box
# width is only the FWHM of a V, ~0.5-0.7 x T14 — then checks the
# circular-orbit stellar density implied by (P, T14) against the TIC
# density. A transit longer than any central transit on its star is
# either eccentric (implausible at P < a few days) or on a different
# star — the grazing-EB-on-companion signature.
#
# Thresholds (justified, not tuned): for a central transit,
# T23/T14 = (1-rp)/(1+rp) >= 0.67 for rp <= 0.2, and grazing drives
# T23/T14 -> 0 (423498314's formal fit: 0.25). So frac <= 0.30 is
# firmly grazing territory and frac >= 0.50 requires a substantial
# full-transit phase; the 0.30-0.50 band is genuinely ambiguous.
# The density flag has two clauses, both bound arguments: (1)
# rho_circ/rho_star < 0.80, i.e. the transit exceeds the rp->0
# central maximum duration by >7.7% — a gross mismatch, any shape;
# (2) V-shaped AND rho_circ/rho_star < 1.0 — for a grazing transit
# the b=0 density is an UPPER bound on the true density (lower by
# ~(sqrt((1+rp)^2-b^2))^3, about 1/3 at b~0.87), so even the bound
# falling below the star's density rules out a circular planet on
# this star unless the object is very large (rp>~0.2), which the
# rp-corrected ratio quantifies — and an rp>0.2 object is itself
# EB-sized for this survey. The flag is a prompt for the formal
# fit, never a verdict on its own.

_G_SI = 6.67430e-11       # m^3 kg^-1 s^-2
_RHO_SUN = 1408.0         # kg/m^3


def _trap_model(x, depth, t14, frac, dt0):
    """Symmetric trapezoid in flux units; depth is a fraction (0-1)."""
    t23 = t14 * frac
    ax = np.abs(np.asarray(x, dtype=float) - dt0)
    y = np.zeros_like(ax)
    flat = ax <= t23 / 2.0
    y[flat] = 1.0
    ramp = (~flat) & (ax <= t14 / 2.0)
    denom = (t14 - t23) / 2.0
    if denom > 0:
        y[ramp] = (t14 / 2.0 - ax[ramp]) / denom
    return 1.0 - depth * y


def _fit_trap(x, y, e, dur, depth0, frac_fixed=None):
    """Least-squares trapezoid fit to a binned fold. Returns
    (depth, t14, frac, dt0, chi2, perr) or None on failure (the
    exception text is left in _FIT_ERROR['msg'] for the caller)."""
    from scipy.optimize import least_squares
    hw = float(np.max(np.abs(x)))
    if frac_fixed is None:
        p0 = [depth0, 1.3 * dur, 0.5, 0.0]
        lo = [1e-5, 0.3 * dur, 0.0, -0.25 * dur]
        hi = [0.5, 1.8 * hw, 0.98, 0.25 * dur]

        def resid(p):
            return (_trap_model(x, *p) - y) / e
    else:
        p0 = [depth0, 1.3 * dur, 0.0]
        lo = [1e-5, 0.3 * dur, -0.25 * dur]
        hi = [0.5, 1.8 * hw, 0.25 * dur]

        def resid(p):
            return (_trap_model(x, p[0], p[1], frac_fixed, p[2]) - y) / e
    # Clip the initial guess strictly inside the bounds: a shallow
    # signal (TOI-700 c, depth ~0.004%) can otherwise start below
    # the depth floor and scipy raises instead of fitting.
    p0 = [min(max(p, l + 1e-9 * (h - l)), h - 1e-9 * (h - l))
          for p, l, h in zip(p0, lo, hi)]
    try:
        sol = least_squares(resid, p0, bounds=(lo, hi))
    except Exception as ex:
        _FIT_ERROR['msg'] = f'{type(ex).__name__}: {ex}'
        return None
    chi2 = float(np.sum(sol.fun ** 2))
    dof = max(len(x) - len(sol.x), 1)
    perr = [None] * len(sol.x)
    try:
        jtj_inv = np.linalg.inv(sol.jac.T @ sol.jac)
        raw = [float(np.sqrt(max(jtj_inv[i, i], 0.0) * chi2 / dof))
               for i in range(len(sol.x))]
        # Sanitise: on a parameter bound the Jacobian is degenerate
        # and the covariance is garbage (0.0 or absurd) — record
        # None (unknown) instead of a misleading number.
        caps = [1.0, 10.0 * abs(sol.x[1]) if len(sol.x) > 1 else 1.0,
                1.0, 1.0]
        perr = [r if (np.isfinite(r) and 0.0 < r <= caps[i]) else None
                for i, r in enumerate(raw)]
    except Exception:
        pass
    if frac_fixed is None:
        return (float(sol.x[0]), float(sol.x[1]), float(sol.x[2]),
                float(sol.x[3]), chi2, perr)
    return (float(sol.x[0]), float(sol.x[1]), frac_fixed,
            float(sol.x[2]), chi2, perr)


_FIT_ERROR = {'msg': None}


def tic_density(tic_id):
    """Stellar density in solar units from the TIC (M/R^3), or None.
    Env RAWF_RHO_STAR overrides (for validation / TIC outages)."""
    env = os.environ.get('RAWF_RHO_STAR')
    if env:
        try:
            return float(env), 'env RAWF_RHO_STAR'
        except ValueError:
            pass
    try:
        from astroquery.mast import Catalogs
        cat = Catalogs.query_criteria(catalog='Tic', ID=int(tic_id))
        if len(cat) == 0:
            return None, 'TIC row not found'
        row = cat[0]
        rad = float(row['rad'])
        mass = float(row['mass'])
        if not (np.isfinite(rad) and np.isfinite(mass)) or rad <= 0:
            return None, 'TIC rad/mass missing'
        return mass / rad ** 3, 'TIC M/R^3'
    except Exception as e:
        return None, f'TIC query failed: {type(e).__name__}'


def _bin_profile(ph, f, hw, bw):
    """Median-binned fold profile over +-hw at bin width bw.
    Returns (xs, ys, es) arrays; bins with < 8 points are dropped."""
    win = np.abs(ph) <= hw
    edges = np.arange(-hw, hw + bw, bw)
    xs, ys, es = [], [], []
    for i in range(len(edges) - 1):
        m = win & (ph >= edges[i]) & (ph < edges[i + 1])
        if m.sum() < 8:
            continue
        v = f[m]
        med = float(np.median(v))
        mad = float(np.median(np.abs(v - med))) * 1.4826
        xs.append(0.5 * (edges[i] + edges[i + 1]))
        ys.append(med)
        es.append(max(mad / math.sqrt(m.sum()), 1e-5))
    return np.array(xs), np.array(ys), np.array(es)


def _recentre(xs, ys, DUR):
    """Shift the profile so x = 0 sits on the dip: the deepest
    3-bin-smoothed bin within +-DUR/2 of T0. The BLS t0 the desk
    check inherits can be off by ~0.05 d (TOI-700 c: 0.049 d early
    of the archive centre), wider than the fit's dt0 range — without
    re-centring the fit pins dt0 at its bound and distorts. Returns
    (xs_shifted, x0) or (None, None) if no bins sit near T0."""
    kern = np.ones(3) / 3.0
    sm = np.convolve(ys, kern, mode='same')
    near = np.abs(xs) <= 0.5 * DUR
    if near.sum() < 3:
        return None, None
    idx_near = np.where(near)[0]
    x0 = float(xs[idx_near[int(np.argmin(sm[near]))]])
    return xs - x0, x0


def trapezoid_shape_gate(t, f, P, T0, DUR, rho_star):
    """Fit a symmetric trapezoid to the folded raw flux and judge
    shape + density. Two passes: a coarse pass at DUR/10 bins
    measures T14, then a fine pass re-bins at ~T14/12 so the
    shape fit resolves the transit even when the BLS box width
    (DUR) is several times the true duration (TOI-700 c: DUR
    0.183 d vs true T14 0.058 d — DUR/10 bins put only ~3 bins
    across the transit, which no fit can shape). Returns a
    JSON-able dict."""
    out = {'method': 'symmetric trapezoid on binned raw fold'}
    ph = phase_days(t, P, T0)
    hw = min(3.5 * DUR, 0.30 * P)  # half-window; capped so the window
    # never wraps into the neighbouring transit (short P, wide DUR)
    if (np.abs(ph) <= hw).sum() < 200:
        out.update({'verdict': 'unmeasured',
                    'reason': 'too few points in fit window'})
        return out
    # ---- pass 1: coarse bins, rough T14 ------------------------------
    xs, ys, es = _bin_profile(ph, f, hw, DUR / 10.0)
    if len(xs) < 15:
        out.update({'verdict': 'unmeasured',
                    'reason': 'too few populated bins'})
        return out
    xs1, x0_1 = _recentre(xs, ys, DUR)
    if xs1 is None:
        out.update({'verdict': 'unmeasured',
                    'reason': 'no bins near T0'})
        return out
    core = np.abs(xs1) <= DUR / 4.0
    base = np.abs(xs1) > 2.0 * DUR
    if core.sum() < 2 or base.sum() < 2:
        out.update({'verdict': 'unmeasured',
                    'reason': 'no core/baseline bins'})
        return out
    depth0 = float(np.median(ys[base]) - np.median(ys[core]))
    if depth0 <= 0:
        out.update({'verdict': 'unmeasured',
                    'reason': 'no dip in binned fold'})
        return out
    fit1 = _fit_trap(xs1, ys, es, DUR, depth0)
    t14_1 = fit1[1] if fit1 else DUR
    out['T14_pass1_d'] = float(t14_1)
    # ---- pass 2: fine bins at ~T14/12, the shape fit -----------------
    bw2 = min(max(t14_1 / 12.0, DUR / 40.0), DUR / 5.0)
    xs, ys, es = _bin_profile(ph, f, hw, bw2)
    out['n_bins'] = int(len(xs))
    out['bin_width_d'] = float(bw2)
    if len(xs) < 15:
        out.update({'verdict': 'unmeasured',
                    'reason': 'too few populated fine bins'})
        return out
    xs, x0 = _recentre(xs, ys, DUR)
    if xs is None:
        out.update({'verdict': 'unmeasured',
                    'reason': 'no bins near T0'})
        return out
    out['centre_offset_d'] = x0
    # initial depth: median outside +-2 DUR minus median inside
    # +-DUR/4 (a narrow core — DUR can overstate the true width,
    # which would dilute a +-DUR/2 core with baseline), with a
    # profile-based significance so we never judge the shape of a
    # dip the binned fold itself cannot see (< 3 sigma).
    core = np.abs(xs) <= DUR / 4.0
    base = np.abs(xs) > 2.0 * DUR
    if core.sum() < 2 or base.sum() < 2:
        out.update({'verdict': 'unmeasured',
                    'reason': 'no core/baseline bins'})
        return out
    depth0 = float(np.median(ys[base]) - np.median(ys[core]))
    se = math.sqrt(1.0 / np.sum(1.0 / es[core] ** 2)
                   + 1.0 / np.sum(1.0 / es[base] ** 2))
    out['depth0_signif'] = float(depth0 / se) if se > 0 else None
    if depth0 <= 0 or (se > 0 and depth0 / se < 3.0):
        out.update({'verdict': 'unmeasured',
                    'reason': 'no >= 3 sigma dip in binned fold'})
        return out
    fit = _fit_trap(xs, ys, es, DUR, depth0)
    if fit is None:
        out.update({'verdict': 'unmeasured',
                    'reason': 'trap fit failed: '
                              + str(_FIT_ERROR.get('msg'))})
        return out
    depth, t14, frac, dt0, chi2, perr = fit
    out['dt0_total_d'] = float(x0 + dt0)  # fit centre vs T0_USED
    tri = _fit_trap(xs, ys, es, DUR, depth0, frac_fixed=0.0)
    box = _fit_trap(xs, ys, es, DUR, depth0, frac_fixed=0.98)
    out.update({
        'depth_frac': depth, 'depth_err': perr[0],
        'T14_d': t14, 'T14_err_d': perr[1],
        'T14_h': t14 * 24.0,
        'T23_d': t14 * frac, 'T23_T14': frac, 'frac_err': perr[2],
        'dt0_d': dt0, 'chi2_trap': chi2,
        'chi2_triangle': tri[4] if tri else None,
        'chi2_box': box[4] if box else None,
        't14_at_bound': bool(t14 >= 1.8 * hw * 0.999),
    })
    # shape verdict from the flat-bottom fraction
    if frac <= 0.30:
        shape = 'V-shaped'
    elif frac >= 0.50:
        shape = 'U-shaped'
    else:
        shape = 'ambiguous'
    out['shape_verdict'] = shape
    # density check: circular-orbit density implied by (P, T14),
    # b = 0, rp -> 0 form: a/R* = P/(pi*T14),
    # rho = 3*pi*(a/R*)^3 / (G*P^2).
    a_R = P / (math.pi * t14)
    rho_circ = (3.0 * math.pi * a_R ** 3
                / (_G_SI * (P * 86400.0) ** 2) / _RHO_SUN)
    out['rho_circ_solar'] = float(rho_circ)
    out['rho_star_solar'] = rho_star
    if rho_star is not None and rho_star > 0:
        rp_est = math.sqrt(max(depth, 0.0))
        ratio0 = rho_circ / rho_star
        ratio_corr = ratio0 * (1.0 + rp_est) ** 3
        # T14max: longest central transit on this star, from the TIC
        # density: (a/R*)^3 = rho_star * G * P^2 / (3*pi), then
        # T14max = (P/pi) * arcsin((1+rp) / (a/R*)).
        a_R_star = (rho_star * _RHO_SUN * _G_SI * (P * 86400.0) ** 2
                    / (3.0 * math.pi)) ** (1.0 / 3.0)
        t14max_h = (P / math.pi
                    * math.asin(min((1.0 + rp_est) / a_R_star, 1.0))
                    * 24.0)
        if ratio0 < 0.80:
            dflag = True
            dreason = 'rho_circ/rho_star < 0.80'
        elif shape == 'V-shaped' and ratio0 < 1.0:
            dflag = True
            dreason = ('V-shaped and rho_circ/rho_star < 1.0 '
                       '(b=0 upper bound already below the star)')
        else:
            dflag = False
            dreason = ''
        out.update({
            'rp_est_from_depth': rp_est,
            'rho_ratio': float(ratio0),
            'rho_ratio_rp_corrected': float(ratio_corr),
            'T14max_h': float(t14max_h),
            'density_flag': bool(dflag),
            'density_reason': dreason,
        })
    else:
        out.update({'rho_ratio': None,
                    'rho_ratio_rp_corrected': None,
                    'T14max_h': None, 'density_flag': None,
                    'density_note': 'no TIC density available'})
    return out



def main(argv=None):
    global TIC, DATA
    ap = argparse.ArgumentParser(
        description='Raw-flux desk check + trapezoid shape gate for one '
                    'filed hit. Folds UNFLATTENED flux at the filed '
                    'ephemeris; a dip that exists only in flattened flux '
                    'is a pipeline artefact, not a planet.')
    ap.add_argument('tic', help='TIC id, e.g. 423498314')
    ap.add_argument('--result-json',
                    help='sweep result.json holding the filed hit '
                         '(period/depth/SDE come from it)')
    ap.add_argument('--period', type=float,
                    help='filed period in days (alternative to '
                         '--result-json)')
    ap.add_argument('--depth', type=float,
                    help='filed depth in percent (alternative to '
                         '--result-json)')
    ap.add_argument('--sde', type=float, default=None,
                    help='filed SDE (provenance only)')
    ap.add_argument('--t0', type=float, default=None,
                    help='ephemeris T0 in BTJD (required with '
                         '--skip-replication)')
    ap.add_argument('--duration', type=float, default=None,
                    help='transit duration in days (required with '
                         '--skip-replication)')
    ap.add_argument('--workdir', required=True,
                    help='output directory (data/*.npz, '
                         'rawflux_results.json, folds.png)')
    ap.add_argument('--data-dir', default=None,
                    help='use this directory for the per-sector npz '
                         'files instead of WORKDIR/data (e.g. a cached '
                         'data set)')
    ap.add_argument('--sector-cap', type=int, default=20,
                    help='pipeline-set sector cap (default 20)')
    ap.add_argument('--skip-replication', action='store_true',
                    help='use --t0/--duration as the ephemeris instead '
                         'of replicating the sweep chain to recover them')
    ap.add_argument('--no-download', action='store_true',
                    help='never touch MAST; use only npz files already '
                         'in the data directory')
    args = ap.parse_args(argv)

    TIC = str(args.tic)
    WORK = args.workdir
    DATA = args.data_dir or os.path.join(WORK, 'data')
    os.makedirs(DATA, exist_ok=True)
    os.makedirs(WORK, exist_ok=True)
    SECTOR_CAP = args.sector_cap

    if args.result_json:
        hit = None
        _rj = json.load(open(args.result_json))
        for h in _rj['hits']:
            if str(h['tic_id']) == str(TIC):
                hit = h
                break
        assert hit is not None, f'TIC {TIC} not in {args.result_json}'
        P_FILED = float(hit['period_days'])
        DEPTH_FILED = float(hit['persistence']['weighted_mean_depth_pct'])
        SDE_FILED = float(hit['sde'])
    elif args.period is not None and args.depth is not None:
        P_FILED = float(args.period)
        DEPTH_FILED = float(args.depth)
        SDE_FILED = args.sde if args.sde is not None else float('nan')
    else:
        ap.error('need either --result-json or --period + --depth')
    if args.skip_replication and (args.t0 is None or args.duration is None):
        ap.error('--skip-replication requires --t0 and --duration')
    print(f'TIC {TIC}: filed P={P_FILED:.7f} d, depth={DEPTH_FILED:.3f}%, '
          f'SDE={SDE_FILED:.1f}', flush=True)

    sets = {}
    for author, pfx in AUTHORS:
        secs = download_author(author, pfx, no_download=args.no_download)
        if secs:
            sets[pfx] = secs

    # pipeline-selected set: most sectors (cap 20), priority breaks ties
    cand = []
    for pfx in ('spoc', 'tspc', 'qlp'):
        if pfx in sets:
            cand.append((len(sets[pfx][:SECTOR_CAP]), -PRIO[pfx], pfx))
    PIPE_PFX = max(cand)[2] if cand else None
    PIPE_SECS = sets[PIPE_PFX][:SECTOR_CAP] if PIPE_PFX else []
    print(f'pipeline set: {PIPE_PFX} sectors {PIPE_SECS}', flush=True)


    replication = {}
    T0_USED = None
    DUR_USED = None
    EPH_SOURCE = None
    if args.skip_replication:
        T0_USED = args.t0
        DUR_USED = args.duration
        EPH_SOURCE = 'cli'
        replication['ephemeris_source'] = 'cli'
    elif PIPE_PFX:
        t_raw, f_raw, _spans = load_stitched(PIPE_PFX, PIPE_SECS)
        tf, ff, win = flatten_with(t_raw, f_raw, 2.0)
        r1 = bls(tf, ff, P_FILED)
        replication['detrend_win_points'] = win
        replication['pass1'] = r1
        print('PASS1:', json.dumps(r1), flush=True)
        Pb, T0b, DURb = r1['best_period'], r1['best_t0'], r1['best_dur_d']
        ph1 = ((t_raw - T0b + 0.5 * Pb) % Pb) - 0.5 * Pb
        # mask on flattened timebase (same times as raw here)
        ph1f = ((tf - T0b + 0.5 * Pb) % Pb) - 0.5 * Pb
        mask = np.abs(ph1f) <= (DURb / 2.0 + 0.02)
        replication['pass2_mask_fraction'] = float(mask.mean())
        r2 = None
        if mask.mean() <= 0.50:
            try:
                tf2, ff2, _w2 = flatten_with(t_raw, f_raw, 2.0, mask=mask)
                r2 = bls(tf2, ff2, P_FILED)
                replication['pass2'] = r2
                print('PASS2:', json.dumps(r2), flush=True)
            except Exception as e:
                replication['pass2_error'] = f'{type(e).__name__}: {e}'
        # filed ephemeris: pass-2's t0/duration AT the filed period (production
        # adopted pass 2); fall back to pass 1's.
        src = r2 if r2 else r1
        T0_USED = src['t0_at_filed']
        DUR_USED = src['dur_at_filed_d']
        replication['ephemeris_source'] = 'pass2' if r2 else 'pass1'
        EPH_SOURCE = replication['ephemeris_source']
        del tf, ff
        gc.collect()

    # ---------------- raw folds ------------------------------------------------

# ---------------- raw folds ------------------------------------------------
    folds = {}
    if T0_USED is not None:
        for pfx, secs in sets.items():
            use = secs[:SECTOR_CAP] if pfx == PIPE_PFX else secs
            folds[pfx] = raw_measure(pfx, use, P_FILED, T0_USED, DUR_USED)
            m = folds[pfx]
            print(f'RAW {pfx}: depth={m.get("depth_pct")} signif={m.get("signif")} '
                  f'd15={m.get("depth15_pct")} sig15={m.get("signif15")}', flush=True)
        # self-anchor cross-check on the pipeline set: phase of the raw fold's
        # deepest 60-bin vs the ephemeris phase 0 (t0 anchoring sanity)
        prof = folds[PIPE_PFX]['fold_profile_pct']
        vals = [(i, v) for i, v in enumerate(prof) if v is not None]
        imin, vmin = min(vals, key=lambda kv: kv[1])
        folds['self_anchor'] = {'deepest_bin': imin,
                                'deepest_bin_phase': round((imin + 0.5) / 60 - 0.5, 3),
                                'deepest_bin_depth_pct': vmin}

    # ---------------- shape gate (trapezoid V-vs-U + density) -------------
    shape_gate = None
    if PIPE_PFX and T0_USED is not None:
        _rho_star, _rho_src = tic_density(TIC)
        print(f'TIC density: {_rho_star} ({_rho_src})', flush=True)
        try:
            _t, _f, _sp = load_stitched(PIPE_PFX, PIPE_SECS)
            shape_gate = trapezoid_shape_gate(_t, _f, P_FILED, T0_USED,
                                              DUR_USED, _rho_star)
            del _t, _f
            gc.collect()
        except Exception as e:
            shape_gate = {'verdict': 'unmeasured',
                          'reason': f'{type(e).__name__}: {e}'}
        shape_gate['rho_star_source'] = _rho_src
        folds[PIPE_PFX]['shape_gate'] = shape_gate
        print('SHAPE:', json.dumps(shape_gate), flush=True)

    # ---------------- verdict ---------------------------------------------------

# ---------------- verdict ---------------------------------------------------
    def confirmed(m):
        return (m is not None and m.get('depth_pct') is not None
                and m.get('signif') is not None
                and m['depth_pct'] >= 0.5 * DEPTH_FILED and m['signif'] >= 3.0)

    verdict = 'UNMEASURED'
    vnote = ''
    if PIPE_PFX and PIPE_PFX in folds:
        pm = folds[PIPE_PFX]
        if confirmed(pm):
            verdict = 'RAW-CONFIRMED'
        elif pm.get('depth_pct') is None or pm['depth_pct'] <= 0 or \
                (pm.get('signif') is not None and pm['signif'] < 2.0):
            others = [p for p in folds if p != PIPE_PFX and confirmed(folds[p])]
            if others:
                verdict = 'RAW-CONFIRMED'
                vnote = (f'pipeline set ({PIPE_PFX}) refutes but {others} '
                         f'confirm(s) at filed depth — cross-product conflict, '
                         f'counted confirmed with this note')
            else:
                verdict = 'RAW-REFUTED'
        else:
            verdict = 'RAW-WEAK'

    result = {
        'tic': str(TIC), 'filed': {'period_days': P_FILED,
                                   'depth_pct': DEPTH_FILED, 'sde': SDE_FILED},
        'pipeline_pfx': PIPE_PFX, 'pipeline_sectors': PIPE_SECS,
        'sets': sets, 'replication': replication,
        'ephemeris_used': {'t0': T0_USED, 'duration_d': DUR_USED,
                           'period_d': P_FILED, 'source': EPH_SOURCE},
        'folds': folds, 'shape_gate': shape_gate,
        'verdict': verdict, 'verdict_note': vnote,
    }
    json.dump(result, open(os.path.join(WORK, 'rawflux_results.json'), 'w'), indent=1)

    # plot: pipeline-set fold profile
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        prof = folds[PIPE_PFX]['fold_profile_pct']
        xs = np.linspace(-0.5, 0.5, 60, endpoint=False) + 0.5 / 60
        ys = [np.nan if v is None else v for v in prof]
        fig, ax = plt.subplots(figsize=(9, 3.6))
        ax.plot(xs, ys, '.-')
        ax.axhline(0, color='grey', lw=0.7)
        ax.set_title(f'TIC {TIC} raw fold at filed P={P_FILED:.5f} d '
                     f'({PIPE_PFX}) — filed depth {DEPTH_FILED:.3f}%')
        ax.set_xlabel('phase'); ax.set_ylabel('rel flux %'); ax.grid(alpha=0.3)
        fig.tight_layout(); fig.savefig(os.path.join(WORK, 'folds.png'), dpi=110)
        plt.close(fig)
    except Exception as e:
        print('plot failed', e)
    print('VERDICT:', verdict, vnote)
    print('DONE')

if __name__ == '__main__':
    main()
