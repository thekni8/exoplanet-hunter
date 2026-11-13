#!/usr/bin/env python3
"""Extract aperture light curves from TESSCut cutouts and fold them.

For each sector: per-cadence background subtraction (median of
background pixels), Gaussian aperture photometry (sigma 1.2 primary,
0.8 cross-check) plus a 3x3 box, then three flux variants per aperture:

  * raw        = background-subtracted, normalised, undetrended;
  * raw_bgreg  = raw + background light curve regressed out
                 (out-of-transit fit only, so the transit cannot leak
                 into the correction; still unflattened — no
                 Savitzky-Golay, no transit masking). Raw FFI flux
                 carries strong scattered-light trends, so the
                 plain-raw fold's red-noise sigma is large; raw_bgreg
                 is the raw-equivalent used for the holdout's held-out
                 measurement (QLP raw flux is already
                 systematics-corrected, TESSCut raw pixels are not —
                 the regressor makes them comparable; the deviation
                 must be stated in any report);
  * detrended  = transit-masked Savitzky-Golay, 1.0 d window.

All three variants are folded (primary + secondary on bgreg) via
hunter._raw_fold_depth, and a full-period phase scan on the detrended
curve refines the epoch offset per sector (with a bgreg gate fold at
the best offset).

Degenerate cutouts (median TARGET-pixel flux < 10 e-/s — TESSCut
serving all-zero flux, as in TIC 423498314 s5/s106, or the target
off-CCD as in s109) are recorded as NO-DATA and produce no light
curve: a zero cutout is not a non-detection.

Usage:
  tesscut_extract.py TIC --period P --t0 T0 --duration DUR \\
      --identity identity.json --tesscut-dir tesscut/ \\
      --data-dir data/ --sectors 107 108 [--out results.json]

Writes data/tesscut_s<NNN>.npz (usable sectors only) + the results JSON.

Generalised from newsectors_extract_fold2.py (2026-11-13): hardcoded
ephemeris/sectors became CLI arguments; the identity record comes from
tesscut_fetch.py (the same schema as stage5a_identity.json). The
extraction, regression, detrend, fold and phase-scan recipes are
unchanged.
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
    from gauntlet.common import background_pixels, load_tpf
except ImportError:  # run as a plain script from the gauntlet dir
    from common import background_pixels, load_tpf


def detrend_v2(t, f, period, t0, duration_d, window_d=1.0):
    """Transit-masked Savitzky-Golay detrend (the v2 recipe): sorts,
    drops non-finite points, caps the window at len//2*2-1, masks
    |phase| < DUR/P around transit centre and interpolates over it."""
    from scipy.signal import savgol_filter
    order = np.argsort(t)
    t, f = t[order], f[order]
    ok = np.isfinite(t) & np.isfinite(f)
    t, f = t[ok], f[ok]
    if len(t) < 100:
        return t, f
    dt = np.median(np.diff(t))
    w = int(window_d / dt)
    w = w if w % 2 == 1 else w + 1
    w = max(w, 51)
    w = min(w, len(t) // 2 * 2 - 1)
    ph = (((t - t0) / period + 0.5) % 1.0) - 0.5
    m = np.abs(ph) < (duration_d / period)
    f2 = np.where(m, np.nan, f)
    good = np.isfinite(f2)
    f_fill = np.interp(t, t[good], f2[good])
    trend = savgol_filter(f_fill, w, 3)
    return t, f / trend


def regress_bg(t, f, bg, period, t0, duration_d):
    """Regress the background LC out of the aperture LC, fitting on
    out-of-transit points only (|phase| > 2*DUR/P). Returns the
    corrected, normalised LC (still unflattened)."""
    ph = (((t - t0) / period + 0.5) % 1.0) - 0.5
    out_m = np.abs(ph) > 2 * (duration_d / period)
    b = bg - np.median(bg[out_m])
    A = np.column_stack([np.ones(out_m.sum()), b[out_m]])
    beta, *_ = np.linalg.lstsq(A, f[out_m], rcond=None)
    corr = f - beta[1] * b
    return corr / np.median(corr[out_m])


def phase_scan(t, f, period, t0, duration_d, step_d=0.002):
    """Full-period phase scan on a light curve: median in/out depth +
    white sigma at each offset. Returns (best_offset, depth, signif)."""
    offs = np.arange(-period / 2, period / 2 + 1e-9, step_d)
    best = (np.nan, np.nan, -np.inf)
    for off in offs:
        ph = (((t - (t0 + off)) / period + 0.5) % 1.0) - 0.5
        hw = 0.5 * duration_d / period
        in_m = np.abs(ph) < hw
        out_m = np.abs(ph) > 2 * hw
        if in_m.sum() < 5 or out_m.sum() < 50:
            continue
        d = (np.median(f[out_m]) - np.median(f[in_m])) * 100.0
        s = np.std(f[out_m]) / np.sqrt(in_m.sum()) * 100.0
        z = d / s if s > 0 else np.nan
        if np.isfinite(z) and z > best[2]:
            best = (float(off), float(d), float(z))
    return best


def main(argv=None):
    ap = argparse.ArgumentParser(
        description='Extract aperture light curves from TESSCut cutouts '
                    'and fold them at an ephemeris (raw / bg-regressed / '
                    'detrended variants, full-period phase scan).')
    ap.add_argument('tic')
    ap.add_argument('--period', type=float, required=True,
                    help='period in days')
    ap.add_argument('--t0', type=float, required=True,
                    help='T0 in BTJD')
    ap.add_argument('--duration', type=float, required=True,
                    help='transit duration in days')
    ap.add_argument('--identity', required=True,
                    help='identity JSON from tesscut_fetch.py')
    ap.add_argument('--tesscut-dir', required=True,
                    help='directory of tesscut_s<NNN>.fits')
    ap.add_argument('--data-dir', required=True,
                    help='directory for tesscut_s<NNN>.npz outputs')
    ap.add_argument('--sectors', type=int, nargs='+', required=True)
    ap.add_argument('--out', default='newsectors_results.json',
                    help='output JSON path')
    args = ap.parse_args(argv)

    import hunter  # repo root, for _raw_fold_depth
    P, T0, DUR = args.period, args.t0, args.duration
    ident = json.load(open(args.identity))
    os.makedirs(args.data_dir, exist_ok=True)
    out = {'tic': str(args.tic), 'P_refined': P, 'T0_refined': T0,
           'duration_d': DUR, 'sectors': {}}

    def fold(t, f, t0_shift=0.0):
        return hunter._raw_fold_depth(t, f, P, T0 + t0_shift, DUR)

    for sec in args.sectors:
        path = os.path.join(args.tesscut_dir, f'tesscut_s{sec:03d}.fits')
        sec_ident = ident['sectors'].get(str(sec)) or \
            ident['sectors'].get(sec)
        if sec_ident is None or not os.path.exists(path):
            out['sectors'][sec] = {
                'status': 'NO-DATA',
                'reason': 'no identity record or cutout FITS missing'}
            print(f'S{sec}: NO-DATA (identity/cutout missing)',
                  flush=True)
            continue
        if sec_ident.get('status') == 'NO-DATA':
            out['sectors'][sec] = {
                'status': 'NO-DATA',
                'reason': sec_ident.get('reason', 'fetch-stage NO-DATA')}
            print(f"S{sec}: NO-DATA ({sec_ident.get('reason')})",
                  flush=True)
            continue
        t, flux, _tpf = load_tpf(path)
        xt, yt = sec_ident['target_px']
        med = np.nanmedian(flux, axis=0)
        j0, i0 = int(round(yt)), int(round(xt))
        tgt_med = float(med[j0, i0])
        bgm = background_pixels(med, xt, yt,
                                exclude_bright_decile=True)
        bg = np.nanmedian(flux[:, bgm], axis=1)
        print(f'S{sec}: target-px median flux {tgt_med:.1f} e-/s, '
              f'bg median {np.median(bg):.1f} e-/s', flush=True)
        if tgt_med < 10.0:
            # degenerate cutout: no usable pixels at the target
            out['sectors'][sec] = {
                'status': 'NO-DATA',
                'reason': ('TESSCut cutout degenerate: median '
                           f'target-pixel flux {tgt_med:.1f} e-/s '
                           '(healthy sectors read ~120-280).'),
                'target_px_median_flux_e_per_s': tgt_med,
                'n_cadences_q0': int(len(t)),
            }
            print(f'S{sec}: NO-DATA — skipping', flush=True)
            continue
        flux_bs = flux - bg[:, None, None]
        yy, xx = np.mgrid[0:flux.shape[1], 0:flux.shape[2]]
        w12 = np.exp(-((xx - xt) ** 2 + (yy - yt) ** 2) / (2 * 1.2 ** 2))
        w08 = np.exp(-((xx - xt) ** 2 + (yy - yt) ** 2) / (2 * 0.8 ** 2))
        lc12 = np.nansum(flux_bs * w12[None, :, :], axis=(1, 2))
        lc08 = np.nansum(flux_bs * w08[None, :, :], axis=(1, 2))
        lc33 = np.nansum(flux_bs[:, j0 - 1:j0 + 2, i0 - 1:i0 + 2],
                         axis=(1, 2))
        rec = {'status': 'USABLE', 'n_cadences_q0': int(len(t)),
               'bg_pixels': int(bgm.sum()),
               'target_px_median_flux_e_per_s': tgt_med,
               'apertures': {}}
        primary = None
        for name, lc in (('gauss1.2', lc12), ('gauss0.8', lc08),
                         ('3x3', lc33)):
            ok = (np.isfinite(lc) & (lc > 0) & np.isfinite(t)
                  & np.isfinite(bg))
            tt, ff, bb = t[ok], lc[ok], bg[ok]
            ff = ff / np.median(ff)
            fb = regress_bg(tt, ff, bb, P, T0, DUR)
            _, fd = detrend_v2(tt, ff, P, T0, DUR)
            d, s = fold(tt, ff)
            db, sb = fold(tt, fb)
            dd, sd = fold(tt, fd)
            d2, s2 = fold(tt, fb, t0_shift=P / 2.0)
            rec['apertures'][name] = {
                'n_points': int(len(tt)),
                'raw_primary': {'depth_pct': float(d),
                                'signif': float(s)},
                'raw_bgreg_primary': {'depth_pct': float(db),
                                      'signif': float(sb)},
                'detrended_primary': {'depth_pct': float(dd),
                                      'signif': float(sd)},
                'raw_bgreg_secondary': {'depth_pct': float(d2),
                                        'signif': float(s2)},
            }
            print(f'S{sec} {name}: raw {d:+.3f}% @ {s:+.1f}s; '
                  f'raw-bgreg {db:+.3f}% @ {sb:+.1f}s; detrended '
                  f'{dd:+.3f}% @ {sd:+.1f}s; secondary (bgreg) '
                  f'{d2:+.3f}% @ {s2:+.1f}s', flush=True)
            if name == 'gauss1.2':
                primary = (tt, ff, fb, fd, bb)
        tt, ff, fb, fd, bb = primary
        off, od, oz = phase_scan(tt, fd, P, T0, DUR)
        d_off, s_off = fold(tt, fb, t0_shift=off)
        rec['phase_scan_detrended'] = {
            'best_offset_d': off, 'scan_depth_pct': od,
            'scan_signif_white': oz,
            'bgreg_gate_depth_at_best_offset_pct': float(d_off),
            'bgreg_gate_signif_at_best_offset': float(s_off),
        }
        print(f'S{sec} phase scan (detrended): best offset {off:+.4f} d '
              f'({od:+.3f}% @ {oz:+.1f}s white; bgreg gate at offset '
              f'{d_off:+.3f}% @ {s_off:+.1f}s)', flush=True)
        k0 = int(np.floor((tt.min() - T0) / P))
        k1 = int(np.ceil((tt.max() - T0) / P))
        rec['n_transit_windows_in_span'] = k1 - k0 + 1
        rec['tmin_btjd'] = float(tt.min())
        rec['tmax_btjd'] = float(tt.max())
        out['sectors'][sec] = rec
        np.savez(os.path.join(args.data_dir, f'tesscut_s{sec:03d}.npz'),
                 time=tt, flux=ff, flux_bgreg=fb, flux_detrended=fd,
                 bg=bb, aperture='gauss1.2_bg-subtracted')
        print(f"S{sec}: saved data/tesscut_s{sec:03d}.npz "
              f"({len(tt)} points)", flush=True)

    with open(args.out, 'w') as fh:
        json.dump(out, fh, indent=2, default=str)
    print(f'wrote {args.out}', flush=True)


if __name__ == '__main__':
    main()
