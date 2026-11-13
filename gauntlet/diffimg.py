#!/usr/bin/env python3
"""Difference imaging + host localisation (gauntlet step 5).

Mandatory before any discovery claim or filing: a dip that doesn't
come from the target's pixels is a blend, whatever the folds say.

Method (stage 5c v2 + stage 5d, merged):
  * per-cadence background = median of background pixels, subtracted
    from every pixel; per-pixel OLS regression (const + transit +
    background + linear time) gives a difference image per sector;
    null-phase controls (+0.25, +0.50) quantify the empirical
    systematics floor — significances are quoted against that floor,
    not white noise;
  * centroid of the difference image (pixels >2 sigma within 3 px of
    the target) + split-half jackknife for the error;
  * two-source PSF fits (target + nearest neighbour) at sigma 0.7/0.9/1.1;
  * single-source PSF comparison (target-only vs neighbour-only chi2);
  * aperture test: detrended light curves from Gaussian-weighted
    sub-pixel apertures centred exactly on target vs neighbour;
  * neighbour-exclusion arithmetic: the maximum dip each census
    neighbour could produce (flux fraction x 100% eclipse) vs the
    observed depth.

FIXES vs the 423498314 scripts (Gemini gauntlet review, 2026-11-13):
  * the per-pixel OLS used to compute (X^T X)^-1 ONCE on the full
    design matrix and apply it to the NaN-masked subset — a mismatched
    inverse. Each pixel now inverts its own masked design matrix.
  * sector stacking used to be an integer np.roll, which ignores the
    roll-angle difference between sectors (s32 vs s98 differ by ~3.3
    degrees — a ~0.4 px smear at the cutout edge). Stacking now
    resamples each sector's map onto the reference sector's frame
    through the WCS (bilinear, depth + variance), and records the
    rotation difference.

Inputs: TESSCut cutouts + the identity JSON from tesscut_fetch.py.
Optional: a census JSON (stage0 schema: target Tmag + tic_cone_60arcsec
list) for the exclusion arithmetic; without one, the TIC cone is
queried live (60", Tmag < 18.5).

Usage:
  diffimg.py TIC --period P --t0 T0 --duration DUR \\
      --identity identity.json --tesscut-dir tesscut/ \\
      --sectors 32 98 --outdir work/TIC \\
      [--exclude-xy 14,5.5] [--depth-pct 1.03] [--census-json census.json]

Writes diffmap_s<NN>.npz, diffmap_stack.npz, diffimg_results.json.
"""
import argparse
import json
import os
import sys
import warnings

warnings.filterwarnings('ignore')
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from gauntlet.common import (background_pixels, gauss_weights,
                                 load_tpf)
except ImportError:  # run as a plain script from the gauntlet dir
    from common import (background_pixels, gauss_weights, load_tpf)


# ---------------------------------------------------------------- core

def transit_mask(t, period, t0, duration_d, phase_shift=0.0):
    ph = (((t - t0) / period + 0.5 - phase_shift) % 1.0) - 0.5
    return np.abs(ph) < (duration_d / period) / 2.0


def per_pixel_regression(t, flux, bg, period, t0, duration_d,
                         phase_shift=0.0, min_in_transit=20):
    """OLS per pixel: flux = a + b*transit + c*bg + d*(t-tmid).

    Returns depth map (-b, positive = dip) and noise map (OLS standard
    error on the transit coefficient).

    BUG FIX vs the 423498314 scripts: the inverse (X^T X)^-1 is computed
    PER PIXEL on that pixel's finite-cadence subset. The old code
    computed it once on the full design matrix and applied it to the
    masked subset — a mismatched inverse, so the coefficients were not
    the OLS solution on the data actually used.
    """
    n, ny, nx = flux.shape
    tr = transit_mask(t, period, t0, duration_d, phase_shift).astype(float)
    tc = t - np.median(t)
    bgc = bg - np.median(bg)
    X = np.column_stack([np.ones(n), tr, bgc, tc])
    med = np.nanmedian(flux, axis=0)
    mad = np.nanmedian(np.abs(flux - med), axis=0) * 1.4826
    bad = np.abs(flux - med) > 5 * np.maximum(mad, 1e-6)
    flux_c = np.where(bad, np.nan, flux)
    depth = np.full((ny, nx), np.nan)
    noise = np.full((ny, nx), np.nan)
    for j in range(ny):
        for i in range(nx):
            y = flux_c[:, j, i]
            ok = np.isfinite(y)
            if ok.sum() < 100 or tr[ok].sum() < min_in_transit:
                continue
            Xok = X[ok]
            XtX_inv = np.linalg.pinv(Xok.T @ Xok)
            beta = XtX_inv @ (Xok.T @ y[ok])
            resid = y[ok] - Xok @ beta
            dof = max(ok.sum() - 4, 1)
            s2 = float((resid ** 2).sum() / dof)
            depth[j, i] = -beta[1]
            noise[j, i] = np.sqrt(s2 * XtX_inv[1, 1])
    return depth, noise


def centroid_of(dmap, nmap, cx, cy, r=3.0, thresh=2.0):
    yy, xx = np.mgrid[0:dmap.shape[0], 0:dmap.shape[1]]
    r2 = (xx - cx) ** 2 + (yy - cy) ** 2
    sig = dmap / np.maximum(nmap, 1e-9)
    m = (r2 <= r * r) & (sig > thresh) & np.isfinite(sig)
    if m.sum() < 2:
        return None
    w = np.clip(dmap[m], 0, None)
    if w.sum() <= 0:
        return None
    return (float((w * xx[m]).sum() / w.sum()),
            float((w * yy[m]).sum() / w.sum()),
            int(m.sum()), float(w.sum()))


def psf_fit(dmap, nmap, sources, sigma=0.9, r=3.5, cx=None, cy=None):
    """Two-source (or N-source) fixed-position Gaussian PSF fit + const.
    Returns (beta, err, column_corr, npix). column_corr is the
    target-neighbour correlation for a 2-source fit, else None."""
    yy, xx = np.mgrid[0:dmap.shape[0], 0:dmap.shape[1]]
    m = ((xx - cx) ** 2 + (yy - cy) ** 2 <= r * r) & np.isfinite(dmap) \
        & np.isfinite(nmap) & (nmap > 0)
    cols = []
    for (sx, sy) in sources:
        g = np.exp(-((xx - sx) ** 2 + (yy - sy) ** 2) / (2 * sigma ** 2))
        cols.append(g[m])
    cols.append(np.ones(int(m.sum())))
    A = np.column_stack(cols)
    w = 1.0 / nmap[m]
    Aw = A * w[:, None]
    yw = dmap[m] * w
    beta, *_ = np.linalg.lstsq(Aw, yw, rcond=None)
    cov = np.linalg.inv(Aw.T @ Aw)
    err = np.sqrt(np.diag(cov))
    corr = None
    if len(sources) == 2:
        corr = float(cov[0, 1] / np.sqrt(cov[0, 0] * cov[1, 1]))
    return beta, err, corr, int(m.sum())


def psf_fit_single(dmap, nmap, src, sigma=0.9, r=3.5, cx=None, cy=None):
    """Single-source PSF fit + const. Returns (beta, err, chi2, npix)."""
    yy, xx = np.mgrid[0:dmap.shape[0], 0:dmap.shape[1]]
    m = ((xx - cx) ** 2 + (yy - cy) ** 2 <= r * r) & np.isfinite(dmap) \
        & np.isfinite(nmap) & (nmap > 0)
    g = np.exp(-((xx - src[0]) ** 2 + (yy - src[1]) ** 2)
               / (2 * sigma ** 2))
    A = np.column_stack([g[m], np.ones(int(m.sum()))])
    w = 1.0 / nmap[m]
    Aw = A * w[:, None]
    yw = dmap[m] * w
    beta, *_ = np.linalg.lstsq(Aw, yw, rcond=None)
    resid = yw - Aw @ beta
    chi2 = float((resid ** 2).sum())
    cov = np.linalg.inv(Aw.T @ Aw)
    err = np.sqrt(np.diag(cov))
    return beta, err, chi2, int(m.sum())


# ---------------------------------------------------------------- WCS stack

def rotation_angle_deg(wcs):
    """Position angle of the WCS x-axis, in degrees (from the CD matrix)."""
    cd = wcs.wcs.get_pc() * wcs.wcs.cdelt[:, None]
    return float(np.degrees(np.arctan2(cd[1, 0], cd[0, 0])))


def wcs_resample(depth, var, wcs_src, wcs_tgt, shape_tgt):
    """Bilinear-resample a depth map + variance map from the source
    frame onto the target frame through the WCS. Out-of-frame or
    NaN-corner pixels become NaN. (Variance is interpolated linearly —
    an approximation that slightly underestimates the correlated noise
    of resampled pixels; the stack's significances are therefore
    upper bounds by a small factor.)"""
    yy, xx = np.mgrid[0:shape_tgt[0], 0:shape_tgt[1]]
    ra, dec = wcs_tgt.all_pix2world(xx, yy, 0)
    xs, ys = wcs_src.all_world2pix(ra, dec, 0)
    x0 = np.floor(xs).astype(int)
    y0 = np.floor(ys).astype(int)
    fx = xs - x0
    fy = ys - y0
    ny, nx = depth.shape
    valid = (x0 >= 0) & (x0 < nx - 1) & (y0 >= 0) & (y0 < ny - 1)
    d_out = np.full(shape_tgt, np.nan)
    v_out = np.full(shape_tgt, np.nan)
    for (arr, out) in ((depth, d_out), (var, v_out)):
        c00 = np.where(valid, arr[np.clip(y0, 0, ny - 1),
                                  np.clip(x0, 0, nx - 1)], np.nan)
        c01 = np.where(valid, arr[np.clip(y0, 0, ny - 1),
                                  np.clip(x0 + 1, 0, nx - 1)], np.nan)
        c10 = np.where(valid, arr[np.clip(y0 + 1, 0, ny - 1),
                                  np.clip(x0, 0, nx - 1)], np.nan)
        c11 = np.where(valid, arr[np.clip(y0 + 1, 0, ny - 1),
                                  np.clip(x0 + 1, 0, nx - 1)], np.nan)
        corners_ok = (np.isfinite(c00) & np.isfinite(c01)
                      & np.isfinite(c10) & np.isfinite(c11))
        val = ((c00 * (1 - fx) + c01 * fx) * (1 - fy)
               + (c10 * (1 - fx) + c11 * fx) * fy)
        out[:] = np.where(valid & corners_ok, val, np.nan)
    return d_out, v_out


# ---------------------------------------------------------------- apertures

def detrend(t, f, period, t0, duration_d, window_d=1.5):
    from scipy.signal import savgol_filter
    order = np.argsort(t)
    t, f = t[order], f[order]
    dt = np.median(np.diff(t))
    w = int(window_d / dt)
    w = w if w % 2 == 1 else w + 1
    w = max(w, 51)
    ph = (((t - t0) / period + 0.5) % 1.0) - 0.5
    m = np.abs(ph) < (duration_d / period)
    f2 = np.where(m, np.nan, f)
    good = np.isfinite(f2)
    f_fill = np.interp(t, t[good], f2[good])
    trend = savgol_filter(f_fill, w, 3)
    return t, f / trend


def fold_depth_simple(t, f, period, t0, duration_d):
    ph = (((t - t0) / period + 0.5) % 1.0) - 0.5
    hw = 0.5 * duration_d / period
    in_m = np.abs(ph) < hw
    out_m = ~in_m
    if in_m.sum() < 5 or out_m.sum() < 50:
        return None
    depth = (np.median(f[out_m]) - np.median(f[in_m])) * 100.0
    sig = np.std(f[out_m]) / np.sqrt(in_m.sum()) * 100.0
    return {'depth_pct': float(depth), 'sigma_pct': float(sig),
            'signif': float(depth / sig) if sig > 0 else None,
            'n_in': int(in_m.sum())}


# ---------------------------------------------------------------- census

def tic_cone_census(ra, dec, target_tmag, radius_arcsec=60.0,
                    tmag_limit=18.5):
    """TIC cone census around a position: [{tic_id, sep_arcsec, Tmag,
    is_target}]. Used for the neighbour-exclusion arithmetic when no
    saved census JSON is given."""
    from astroquery.mast import Catalogs
    import astropy.units as u
    from astropy.coordinates import SkyCoord
    coord = SkyCoord(ra, dec, unit='deg')
    rows = Catalogs.query_region(coord, catalog='TIC',
                                 radius=radius_arcsec * u.arcsec)
    out = []
    for r in rows:
        if r['Tmag'] is None or r['Tmag'] > tmag_limit:
            continue
        sep = float(coord.separation(
            SkyCoord(r['ra'], r['dec'], unit='deg')).arcsec)
        out.append({'tic_id': int(r['ID']),
                    'sep_arcsec': sep,
                    'Tmag': float(r['Tmag']),
                    'is_target': bool(abs(sep) < 1.0
                                      and abs(float(r['Tmag']) - target_tmag) < 0.05)})
    return sorted(out, key=lambda d: d['sep_arcsec'])


# ---------------------------------------------------------------- main

def parse_exclude_xy(values):
    pts = []
    for v in values or []:
        x, y = v.split(',')
        pts.append((float(x), float(y)))
    return pts


def main(argv=None):
    ap = argparse.ArgumentParser(
        description='Difference imaging + host localisation: per-pixel '
                    'transit regression, centroid, PSF fits, aperture '
                    'test, jackknife, neighbour exclusion.')
    ap.add_argument('tic')
    ap.add_argument('--period', type=float, required=True)
    ap.add_argument('--t0', type=float, required=True)
    ap.add_argument('--duration', type=float, required=True,
                    help='transit duration in days')
    ap.add_argument('--identity', required=True,
                    help='identity JSON from tesscut_fetch.py')
    ap.add_argument('--tesscut-dir', required=True)
    ap.add_argument('--sectors', type=int, nargs='+', required=True)
    ap.add_argument('--outdir', required=True)
    ap.add_argument('--exclude-xy', action='append', default=[],
                    help='bright-star pixel position to exclude from the '
                         'background mask, "x,y" (repeatable)')
    ap.add_argument('--exclude-bright-decile', action='store_true',
                    help='also exclude the brightest decile of '
                         'background pixels')
    ap.add_argument('--depth-pct', type=float, default=None,
                    help='observed transit depth in percent, for the '
                         'neighbour-exclusion arithmetic')
    ap.add_argument('--census-json', default=None,
                    help='saved census JSON (stage0 schema); without it '
                         'the TIC cone is queried live')
    ap.add_argument('--ra', type=float, default=None,
                    help='target RA (needed for a live census query)')
    ap.add_argument('--dec', type=float, default=None,
                    help='target Dec (needed for a live census query)')
    ap.add_argument('--tmag', type=float, default=None,
                    help='target Tmag (needed for a live census query)')
    ap.add_argument('--skip-jackknife', action='store_true')
    ap.add_argument('--skip-aperture', action='store_true')
    args = ap.parse_args(argv)

    ident = json.load(open(args.identity))
    os.makedirs(args.outdir, exist_ok=True)
    exclude_xy = parse_exclude_xy(args.exclude_xy)
    P, T0, DUR = args.period, args.t0, args.duration

    out = {'tic': str(args.tic),
           'method': 'v2: background-subtracted + common-mode regressor '
                     '+ null-phase floor; per-pixel masked OLS; '
                     'WCS-aligned stack',
           'ephemeris': {'period_d': P, 't0_btjd': T0, 'duration_d': DUR},
           'sectors': {}}
    maps = {}
    wcs_by_sector = {}
    for sec in args.sectors:
        path = os.path.join(args.tesscut_dir, f'tesscut_s{sec:03d}.fits')
        t, flux, tpf = load_tpf(path)
        wcs_by_sector[sec] = tpf.wcs
        isec = ident['sectors'][str(sec)]
        xt, yt = isec['target_px']
        xn, yn = isec['neighbour_px']
        med = np.nanmedian(flux, axis=0)
        bgm = background_pixels(med, xt, yt, exclude_xy=exclude_xy,
                                exclude_bright_decile=args.exclude_bright_decile)
        bg = np.nanmedian(flux[:, bgm], axis=1)
        print(f'S{sec}: background pixels {int(bgm.sum())}, bg median '
              f'{np.median(bg):.0f} e-/s, range '
              f'{np.percentile(bg, 1):.0f}-{np.percentile(bg, 99):.0f}',
              flush=True)
        flux_bs = flux - bg[:, None, None]
        d, n = per_pixel_regression(t, flux_bs, bg, P, T0, DUR, 0.0)
        d25, _ = per_pixel_regression(t, flux_bs, bg, P, T0, DUR, 0.25)
        d50, _ = per_pixel_regression(t, flux_bs, bg, P, T0, DUR, 0.50)
        maps[sec] = (d, n, d25, d50)
        np.savez(os.path.join(args.outdir, f'diffmap_s{sec:02d}.npz'),
                 depth=d, noise=n, null25=d25, null50=d50)
        floor_null = float(np.nanstd(np.concatenate([d25[bgm], d50[bgm]])))
        floor_real_bg = float(np.nanstd(d[bgm]))
        j0, i0 = int(round(yt)), int(round(xt))
        cen = centroid_of(d, n, xt, yt)
        print(f'S{sec}: floor null {floor_null:.2f} e-/s, floor real-bg '
              f'{floor_real_bg:.2f} e-/s; target-px depth '
              f'{d[j0, i0]:+.2f} (white {d[j0, i0] / n[j0, i0]:+.1f}s, '
              f'floor {d[j0, i0] / floor_null:+.1f}s); centroid {cen}',
              flush=True)
        out['sectors'][sec] = {
            'floor_null_e_per_s': floor_null,
            'floor_real_bg_e_per_s': floor_real_bg,
            'target_px_depth': float(d[j0, i0]),
            'target_px_white_noise': float(n[j0, i0]),
            'centroid': cen,
        }

    # ---- WCS-aligned stack (reference = last sector) ----
    ref_sec = args.sectors[-1]
    d_ref, n_ref, _, _ = maps[ref_sec]
    wcs_ref = wcs_by_sector[ref_sec]
    angles = {s: rotation_angle_deg(wcs_by_sector[s])
              for s in args.sectors}
    dstack = d_ref.copy()
    nstack = n_ref.copy()
    stack_info = {'reference_sector': ref_sec,
                  'rotation_angles_deg': angles,
                  'method': 'WCS bilinear resample onto the reference '
                            'frame, inverse-variance combine'}
    for sec in args.sectors[:-1]:
        d_s, n_s, _, _ = maps[sec]
        d_res, v_res = wcs_resample(d_s, n_s ** 2, wcs_by_sector[sec],
                                    wcs_ref, d_ref.shape)
        n_res = np.sqrt(v_res)
        d_ang = angles[sec] - angles[ref_sec]
        print(f'stack: resampling s{sec} onto s{ref_sec} frame '
              f'(rotation difference {d_ang:+.2f} deg)', flush=True)
        if abs(d_ang) > 5.0:
            print(f'  WARNING: rotation difference {d_ang:+.2f} deg is '
                  f'large — the WCS resample handles it, but check the '
                  f'stack centroid against the per-sector centroids.',
                  flush=True)
        w1 = 1.0 / np.maximum(n_res, 1e-9) ** 2
        w2 = 1.0 / np.maximum(nstack, 1e-9) ** 2
        ok = np.isfinite(d_res) & np.isfinite(dstack)
        dstack = np.where(ok, (d_res * w1 + dstack * w2) / (w1 + w2),
                          np.where(np.isfinite(dstack), dstack, d_res))
        nstack = np.where(ok, 1.0 / np.sqrt(w1 + w2),
                          np.where(np.isfinite(nstack), nstack, n_res))
    np.savez(os.path.join(args.outdir, 'diffmap_stack.npz'),
             depth=dstack, noise=nstack)
    isec_ref = ident['sectors'][str(ref_sec)]
    xt, yt = isec_ref['target_px']
    xn, yn = isec_ref['neighbour_px']
    med_ref = np.nanmedian(load_tpf(os.path.join(
        args.tesscut_dir, f'tesscut_s{ref_sec:03d}.fits'))[1], axis=0)
    bgm = background_pixels(med_ref, xt, yt, exclude_xy=exclude_xy,
                            exclude_bright_decile=args.exclude_bright_decile)
    floor_stack = float(np.nanstd(dstack[bgm]))
    cen = centroid_of(dstack, nstack, xt, yt)
    print(f'STACK: floor {floor_stack:.2f} e-/s; centroid {cen}',
          flush=True)
    out['stack'] = {'floor_e_per_s': floor_stack, 'centroid': cen,
                    'target_px': [xt, yt], 'neighbour_px': [xn, yn],
                    **stack_info}
    if cen:
        out['stack']['dist_to_target_px'] = float(
            np.hypot(cen[0] - xt, cen[1] - yt))
        out['stack']['dist_to_neighbour_px'] = float(
            np.hypot(cen[0] - xn, cen[1] - yn))
        print(f"     centroid-target "
              f"{out['stack']['dist_to_target_px']:.2f} px, "
              f"centroid-neighbour "
              f"{out['stack']['dist_to_neighbour_px']:.2f} px",
              flush=True)

    # ---- PSF fits on corrected maps ----
    for label, (dd, nn, cx_, cy_, nx_, ny_) in [
            ('stack', (dstack, nstack, xt, yt, xn, yn))] + [
            (f's{sec}', (maps[sec][0], maps[sec][1],
                         ident['sectors'][str(sec)]['target_px'][0],
                         ident['sectors'][str(sec)]['target_px'][1],
                         ident['sectors'][str(sec)]['neighbour_px'][0],
                         ident['sectors'][str(sec)]['neighbour_px'][1]))
            for sec in args.sectors]:
        for sig in (0.7, 0.9, 1.1):
            beta, err, corr, npix = psf_fit(
                dd, nn, [(cx_, cy_), (nx_, ny_)], sigma=sig,
                cx=cx_, cy=cy_)
            print(f'PSF {label} sigma={sig}: target '
                  f'{beta[0]:+.2f}+-{err[0]:.2f} '
                  f'({beta[0] / err[0]:+.1f}s) neighbour '
                  f'{beta[1]:+.2f}+-{err[1]:.2f} '
                  f'({beta[1] / err[1]:+.1f}s) const {beta[2]:+.2f} '
                  f'corr {corr:+.2f}', flush=True)
            out.setdefault('psf_fits', {})[f'{label}_sigma{sig}'] = {
                'target_amp': float(beta[0]), 'target_err': float(err[0]),
                'target_signif': float(beta[0] / err[0]),
                'neighbour_amp': float(beta[1]),
                'neighbour_err': float(err[1]),
                'neighbour_signif': float(beta[1] / err[1]),
                'const': float(beta[2]), 'column_corr': corr,
                'npix': npix}

    # ---- single-source PSF comparison on the stack ----
    for label, src in [('target-only', (xt, yt)),
                       ('neighbour-only', (xn, yn))]:
        beta, err, chi2, npix = psf_fit_single(dstack, nstack, src,
                                               cx=xt, cy=yt)
        print(f'{label}: amp {beta[0]:+.2f}+-{err[0]:.2f} '
              f'({beta[0] / err[0]:+.1f}s) const {beta[1]:+.2f} '
              f'chi2 {chi2:.1f} ({npix} px, dof {npix - 2})', flush=True)
        out[label] = {'amp': float(beta[0]), 'err': float(err[0]),
                      'signif': float(beta[0] / err[0]), 'chi2': chi2,
                      'npix': npix}
    yy, xx = np.mgrid[0:dstack.shape[0], 0:dstack.shape[1]]
    m3 = (xx - xt) ** 2 + (yy - yt) ** 2 <= 9.0
    tot = float(np.nansum(dstack[m3]))
    print(f'total difference flux within 3 px of target: {tot:+.2f} e-/s',
          flush=True)
    out['total_diff_flux_3px_e_per_s'] = tot

    # ---- split-half jackknife centroids ----
    if not args.skip_jackknife:
        cents = []
        for sec in args.sectors:
            path = os.path.join(args.tesscut_dir,
                                f'tesscut_s{sec:03d}.fits')
            t, flux, _tpf = load_tpf(path)
            isec = ident['sectors'][str(sec)]
            xts, yts = isec['target_px']
            xns, yns = isec['neighbour_px']
            med = np.nanmedian(flux, axis=0)
            bgm = background_pixels(med, xts, yts, exclude_xy=exclude_xy,
                                    exclude_bright_decile=args.exclude_bright_decile)
            bg = np.nanmedian(flux[:, bgm], axis=1)
            flux_bs = flux - bg[:, None, None]
            tmid = np.median(t)
            for half, km in [('first', t < tmid), ('second', t >= tmid)]:
                d, n = per_pixel_regression(
                    t[km], flux_bs[km], bg[km], P, T0, DUR, 0.0,
                    min_in_transit=10)
                c = centroid_of(d, n, xts, yts)
                if c:
                    d_t = float(np.hypot(c[0] - xts, c[1] - yts))
                    d_n = float(np.hypot(c[0] - xns, c[1] - yns))
                    cents.append({'sector': sec, 'half': half,
                                  'centroid': c[:2], 'dist_target': d_t,
                                  'dist_neighbour': d_n})
                    print(f'S{sec} {half}: centroid ({c[0]:.2f},{c[1]:.2f}) '
                          f'd_target {d_t:.2f} px d_neigh {d_n:.2f} px',
                          flush=True)
        out['split_half_centroids'] = cents
        if cents:
            ct = np.array([c['centroid'] for c in cents])
            print(f"centroid scatter: x std {ct[:, 0].std():.2f} px, "
                  f"y std {ct[:, 1].std():.2f} px over {len(cents)} halves",
                  flush=True)
            out['centroid_scatter_px'] = {
                'x_std': float(ct[:, 0].std()),
                'y_std': float(ct[:, 1].std()), 'n': len(cents)}

    # ---- aperture test: detrended LCs, Gaussian-weighted sub-px apertures ----
    if not args.skip_aperture:
        print('APERTURE TEST (detrended, Gaussian-weighted):', flush=True)
        ap_res = {}
        for sec in args.sectors:
            path = os.path.join(args.tesscut_dir,
                                f'tesscut_s{sec:03d}.fits')
            t, flux, _tpf = load_tpf(path)
            isec = ident['sectors'][str(sec)]
            xts, yts = isec['target_px']
            xns, yns = isec['neighbour_px']
            med = np.nanmedian(flux, axis=0)
            bgm = background_pixels(med, xts, yts, exclude_xy=exclude_xy,
                                    exclude_bright_decile=args.exclude_bright_decile)
            bg = np.nanmedian(flux[:, bgm], axis=1)
            flux_bs = flux - bg[:, None, None]
            for name, (cx_, cy_) in [('target', (xts, yts)),
                                     ('neighbour', (xns, yns))]:
                for sig in (0.8, 1.2):
                    w = gauss_weights(flux.shape[1:], cx_, cy_, sig)
                    lc = np.nansum(flux_bs * w[None, :, :], axis=(1, 2))
                    ok = np.isfinite(lc) & (lc > 0)
                    tt, ff = detrend(t[ok], lc[ok], P, T0, DUR)
                    r = fold_depth_simple(tt, ff, P, T0, DUR)
                    ap_res[f's{sec}_{name}_sig{sig}'] = r
                    print(f"  S{sec} {name} sig={sig}: depth "
                          f"{r['depth_pct']:+.3f}% "
                          f"+-{r['sigma_pct']:.3f} ({r['signif']:+.1f}s) "
                          f"n_in {r['n_in']}", flush=True)
            j0, i0 = int(round(yts)), int(round(xts))
            lc = np.nansum(flux_bs[:, j0 - 1:j0 + 2, i0 - 1:i0 + 2],
                           axis=(1, 2))
            ok = np.isfinite(lc) & (lc > 0)
            tt, ff = detrend(t[ok], lc[ok], P, T0, DUR)
            r = fold_depth_simple(tt, ff, P, T0, DUR)
            ap_res[f's{sec}_target_3x3_detrended'] = r
            print(f"  S{sec} target 3x3 detrended: "
                  f"{r['depth_pct']:+.3f}% ({r['signif']:+.1f}s)",
                  flush=True)
        out['aperture_depths'] = ap_res

    # ---- neighbour exclusion arithmetic ----
    if args.depth_pct is not None:
        if args.census_json:
            census = json.load(open(args.census_json))
            tmag_t = census['target']['Tmag']
            cone = census['tic_cone_60arcsec']
        elif args.ra is not None and args.dec is not None \
                and args.tmag is not None:
            tmag_t = args.tmag
            cone = tic_cone_census(args.ra, args.dec, args.tmag)
        else:
            cone = None
        if cone is not None:
            print('NEIGHBOUR EXCLUSION (max dip if the neighbour '
                  'vanished entirely):', flush=True)
            excl = []
            for nb in cone:
                if nb.get('is_target'):
                    continue
                fr = 10 ** (-(nb['Tmag'] - tmag_t) / 2.5)
                maxdip = fr * 100.0
                excl.append({'tic': nb['tic_id'],
                             'sep_arcsec': nb['sep_arcsec'],
                             'tmag': nb['Tmag'],
                             'flux_fraction_of_target': fr,
                             'max_dip_pct_if_total_eclipse': maxdip,
                             'can_produce_depth': bool(
                                 maxdip >= args.depth_pct)})
                print(f"  TIC {nb['tic_id']} sep {nb['sep_arcsec']:.1f}'' "
                      f"Tmag {nb['Tmag']:.2f} flux frac {fr:.4f} max dip "
                      f"{maxdip:.2f}% "
                      f"{'CAN' if maxdip >= args.depth_pct else 'cannot'} "
                      f"produce {args.depth_pct}%", flush=True)
            out['neighbour_exclusion'] = excl

    path = os.path.join(args.outdir, 'diffimg_results.json')
    with open(path, 'w') as fh:
        json.dump(out, fh, indent=2, default=str)
    print(f'wrote {path}', flush=True)


if __name__ == '__main__':
    main()
