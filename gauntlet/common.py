#!/usr/bin/env python3
"""Shared helpers for the vetting gauntlet.

One copy of each recipe, used by the gauntlet tools instead of being
re-implemented per script. Nothing here is star-specific.

Conventions (house rules, earned the hard way):
  * Times are BTJD (BJD - 2457000) unless a name says otherwise.
  * Phases are CENTRED: phase in [-0.5, +0.5), transit at phase 0.
    (The old uncentred frame put the transit at phase ~0.5 and once
    inverted a fold-profile diagnostic — see the 2026-11-13 phase fix.)
  * Odd/even splits assign each point to its NEAREST event (round, not
    floor): a floor-parity split mixes the two halves of every eclipse
    across parities and erases a real odd/even difference.
  * astropy BoxLeastSquares.power takes PERIODS, not frequencies.
  * Bulk-screen single-sector periods are NOT valid fold anchors over
    multi-year baselines — phase-scan + period refinement first.
"""
import os
import sys

import numpy as np

# ---------------------------------------------------------------- paths

def repo_root():
    """Absolute path of the repo root (parent of gauntlet/)."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def ensure_repo_path():
    """Put the repo root (hunter.py, holdout_test.py, persistence.py) and
    the gauntlet dir itself on sys.path, so tools work both as
    `python gauntlet/tool.py` and `python -m gauntlet.tool`."""
    root = repo_root()
    here = os.path.dirname(os.path.abspath(__file__))
    for p in (root, here):
        if p not in sys.path:
            sys.path.insert(0, p)


# ---------------------------------------------------------------- phases

def phase_days(t, period, t0):
    """Centred phase in days: 0 at transit centre, in [-P/2, +P/2)."""
    return (((np.asarray(t) - t0) / period + 0.5) % 1.0 - 0.5) * period


def phase_frac(t, period, t0):
    """Centred phase in cycles: 0 at transit centre, in [-0.5, +0.5)."""
    return ((np.asarray(t) - t0) / period + 0.5) % 1.0 - 0.5


# ---------------------------------------------------------------- flatten

def flatten_transit_masked(t, f, period, t0, duration_d, window_d=2.0,
                           polyorder=2):
    """Transit-masked Savitzky-Golay flatten (the pipeline's recipe).

    Masks the transit (widened 1.5x), interpolates over it, and applies an
    SG filter with a ~window_d window. Returns the flattened flux
    (median-normalised). The mask is what keeps a real transit from being
    absorbed into the trend — the pass-2 guard exists because an
    unmasked second pass can manufacture a dip out of broad variability.
    """
    from scipy.signal import savgol_filter

    t = np.asarray(t, dtype=float)
    f = np.asarray(f, dtype=float)
    dt = np.median(np.diff(np.sort(t)))
    if dt <= 0 or not np.isfinite(dt):
        dt = 0.001
    win = max(int(window_d / dt) // 2 * 2 + 1, 51)
    in_tr = np.abs(phase_days(t, period, t0)) < duration_d * 0.75
    f_f = f.copy()
    if in_tr.any() and (~in_tr).sum() > 10:
        f_f[in_tr] = np.interp(t[in_tr], t[~in_tr], f[~in_tr])
    trend = savgol_filter(f_f, win, polyorder, mode="interp")
    return f / trend


# ---------------------------------------------------------------- folding

def fold_depth(t, f, period, t0, duration_d, centre_phase=0.0):
    """Depth (%) of a box of width dur centred at centre_phase (phase
    units). Returns depth, white sigma, red-noise sigma from 24 control
    windows at other phases, n_in. (Exact port of desk_finish_s98.py:
    the phase is wrapped around the centre, so centre_phase=0.5 — the
    secondary — works; control windows draw c ~ U(-0.45, 0.45) with
    seed 0 and measure against their own complement.)

    Flux is assumed median-normalised (depths are in percent of the
    out-of-transit median, i.e. ~percent of unity). The red sigma is
    the honest one for FFI data with correlated noise; the white sigma
    is the floor. Returns None if fewer than 5 in-transit or 50
    out-of-transit points.
    """
    t = np.asarray(t, dtype=float)
    f = np.asarray(f, dtype=float)
    ph = (((t - t0) / period - centre_phase + 0.5) % 1.0) - 0.5
    hw = 0.5 * duration_d / period
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
        ph2 = (((t - t0) / period - c + 0.5) % 1.0) - 0.5
        m = np.abs(ph2) < hw
        if m.sum() >= 5:
            ctrls.append((np.median(f[~m]) - np.median(f[m])) * 100.0)
    sig_red = float(np.std(ctrls)) if len(ctrls) >= 8 else float('nan')
    return {'depth_pct': float(depth),
            'sig_white_pct': float(sig_white),
            'sig_red_pct': sig_red,
            'n_in': int(in_tr.sum()),
            'signif_white': float(depth / sig_white),
            'signif_red': float(depth / sig_red)
            if sig_red == sig_red and sig_red > 0 else None}


def event_parity_depths(t, f, period, t0, duration_d):
    """Split IN-TRANSIT points by nearest-event index parity (round,
    not floor — a floor-parity split mixes the two halves of every
    eclipse across parities and erases a real odd/even difference).
    Baseline = points far from any event centre (> 3 durations).
    Returns (odd, even) depth dicts. (Exact port of desk_finish_s98.py.)
    """
    t = np.asarray(t, dtype=float)
    f = np.asarray(f, dtype=float)
    n_ev = np.round((t - t0) / period).astype(int)
    dt = t - (t0 + n_ev * period)
    in_tr = np.abs(dt) < duration_d / 2.0
    out = np.abs(dt) > 3 * duration_d
    base = np.median(f[out])
    res = []
    for parity in (1, 0):
        m = in_tr & (n_ev % 2 == parity)
        if m.sum() < 5:
            res.append(None)
            continue
        depth = (base - np.median(f[m])) * 100.0
        sig = np.std(f[out]) / np.sqrt(m.sum()) * 100.0
        res.append({'depth_pct': float(depth),
                    'sig_white_pct': float(sig),
                    'signif_white': float(depth / sig),
                    'n_in': int(m.sum()),
                    'n_events': int(len(np.unique(n_ev[m])))})
    return res[0], res[1]


# ---------------------------------------------------------------- TIC

def tic_lookup(tic_id):
    """TIC catalog row via astroquery (ra, dec, radius, mass, Teff, Tmag).
    Raises on failure — callers that can proceed without a row should
    catch and fall back to CLI values."""
    from astroquery.mast import Catalogs
    rows = Catalogs.query_object(f"TIC {tic_id}", catalog="TIC")
    if len(rows) == 0:
        raise ValueError(f"TIC {tic_id} not found in the TIC catalog")
    r = rows[0]
    return {"ra": float(r["ra"]), "dec": float(r["dec"]),
            "radius_rsun": float(r["rad"]) if r["rad"] else None,
            "mass_msun": float(r["mass"]) if r["mass"] else None,
            "teff_k": float(r["Teff"]) if r["Teff"] else None,
            "tmag": float(r["Tmag"]) if r["Tmag"] else None,
            "gaia_id": int(r["GAIA"]) if r["GAIA"] else None,
            "contratio": (float(r["contratio"]) if r["contratio"] is not None
                          and np.isfinite(r["contratio"]) else None)}


def tic_density(tic_id, radius_rsun=None, mass_msun=None):
    """Stellar density in solar units from the TIC row (or CLI values).
    Returns None if radius/mass are unavailable."""
    if radius_rsun is None or mass_msun is None:
        row = tic_lookup(tic_id)
        radius_rsun = radius_rsun if radius_rsun is not None else row["radius_rsun"]
        mass_msun = mass_msun if mass_msun is not None else row["mass_msun"]
    if radius_rsun is None or mass_msun is None or radius_rsun <= 0:
        return None
    return mass_msun / radius_rsun ** 3


def t14_max_hours(period_d, radius_rsun, mass_msun, rp_over_rstar=0.0):
    """Maximum central-transit duration (hours) for a circular orbit:
    T14,max = (P/pi) * asin((1 + Rp/R*) / (a/R*)), a/R* from Kepler's law.
    With rp_over_rstar=0 this is the Rp=0 limit; the paper convention
    includes the (1 + Rp/R*) factor."""
    a_over_r = 4.2083 * (mass_msun ** (1.0 / 3.0)) * (period_d ** (2.0 / 3.0)) / radius_rsun
    x = min((1.0 + rp_over_rstar) / a_over_r, 1.0)
    return period_d / np.pi * np.arcsin(x) * 24.0


# ---------------------------------------------------------------- pixels

def load_tpf(path):
    """Load a TESSCut/SPOC TPF, quality==0 only. Returns (t, flux, tpf)
    with flux as float ndarray (cadence, y, x)."""
    import lightkurve as lk
    tpf = lk.read(path)
    q = np.asarray(tpf.quality)
    m = (q == 0)
    t = np.asarray(tpf.time.value)[m]
    flux = np.asarray(tpf.flux.value)[m].astype(float)
    return t, flux, tpf


def wcs_xy(tpf, ra, dec):
    """Pixel (x, y) of a sky position in a TPF's WCS."""
    x, y = tpf.wcs.world_to_pixel_values(ra, dec)
    return float(x), float(y)


def background_pixels(med, xt, yt, exclude_xy=None, exclude_bright_decile=False):
    """Background-pixel mask for a cutout median image.

    Pixels >4 px from the target. Optionally also >3 px from named bright
    stars (exclude_xy = [(x, y), ...]) and/or excluding the brightest
    decile of the remaining pixels (the decile cut is the general rule;
    named exclusions reproduce a hand-tuned mask).
    """
    yy, xx = np.mgrid[0:med.shape[0], 0:med.shape[1]]
    m = (xx - xt) ** 2 + (yy - yt) ** 2 > 16.0
    for (bx, by) in (exclude_xy or []):
        m &= (xx - bx) ** 2 + (yy - by) ** 2 > 9.0
    if exclude_bright_decile:
        # brightest decile of the WHOLE median image (the v2 recipe)
        m &= med <= np.nanpercentile(med, 90)
    return m


def gauss_weights(shape, cx, cy, sigma):
    """Normalised 2-D Gaussian aperture weights over an image of shape."""
    yy, xx = np.mgrid[0:shape[0], 0:shape[1]]
    w = np.exp(-((xx - cx) ** 2 + (yy - cy) ** 2) / (2 * sigma ** 2))
    return w / w.sum()


def aperture_lc(flux, weights):
    """Weighted-mean light curve from a flux cube and aperture weights."""
    return np.einsum("tij,ij->t", flux, weights)


# ---------------------------------------------------------------- npz LCs

def load_npz_lc(path):
    """Load a saved light curve npz (t, f, and any extra keys)."""
    d = np.load(path)
    return {k: d[k] for k in d.files}


def concat_sets(sets, pfx):
    """Concatenate per-sector (t, f) dicts for one product prefix, each
    sector median-normalised first. Returns (t, f) sorted by time."""
    tt, ff = [], []
    for s in sorted(sets[pfx]):
        t, f = sets[pfx][s]
        med = np.median(f)
        tt.append(t)
        ff.append(f / med)
    t = np.concatenate(tt)
    f = np.concatenate(ff)
    order = np.argsort(t)
    return t[order], f[order]
