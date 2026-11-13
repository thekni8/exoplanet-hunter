#!/usr/bin/env python3
"""Refined-ephemeris verification folds (gauntlet step 3).

Takes a REFINED ephemeris — the bulk-screen period refined by phase
scan, or the sweep's filed ephemeris — and verifies it on the raw flux
in every product and era:

  1. verification folds at the refined ephemeris (per product, per
     sector), plus the secondary-eclipse fold at phase 0.5;
  2. odd/even split by NEAREST event (floor parity mixes the halves of
     every eclipse and erases a real difference);
  3. optional P/2 alias test (--half): at half the period, even events
     are the primary and odd events the secondary — two comparable
     minima mean the filed period is the P/2 alias of an EB;
  4. optional free BLS + Lomb-Scargle over 0.1-1.2 d (--bls): looks for
     an independent sub-0.5 d fundamental the pipeline's 0.5 d floor
     could not see (the TIC 29780280 lesson: a 0.62 d "transit" that
     was the 3rd harmonic of a 0.207 d rotation).

Input: per-sector light curves as <pfx>_s<NNN>.npz files (t, f) in a
data directory — the same files rawflux_check.py writes.

Usage:
  desk_finish.py TIC --period P --t0 T0 --duration DUR --data-dir data/ \\
      --out finish_results.json [--bls] [--half] [--bulk-period P --bulk-t0 T0]

Generalised from desk_finish_s98.py (sector-98 bulk gauntlet, 2026-11-13):
the hardcoded REFINED dict became CLI arguments; fold_depth and
event_parity_depths moved to common.py unchanged.
"""
import argparse
import glob
import json
import os
import sys
import warnings

warnings.filterwarnings('ignore')
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from gauntlet.common import concat_sets, event_parity_depths, fold_depth
except ImportError:  # run as a plain script from the gauntlet dir
    from common import concat_sets, event_parity_depths, fold_depth


def load_star(data_dir, prefixes=None):
    """Load all <pfx>_s<NNN>.npz in data_dir into {pfx: {sector: (t, f)}}.
    House npz convention: time/flux keys (rawflux_check.py writes them;
    tesscut npz files also carry flux_bgreg / flux_detrended / bg).
    prefixes optionally restricts which product prefixes are loaded."""
    sets = {}
    for path in sorted(glob.glob(os.path.join(data_dir, "*_s*.npz"))):
        name = os.path.basename(path)[:-4]
        pfx, sec = name.split("_s")
        if prefixes and pfx not in prefixes:
            continue
        sec = int(sec)
        d = np.load(path)
        sets.setdefault(pfx, {})[sec] = (
            np.asarray(d["time"], dtype=float),
            np.asarray(d["flux"], dtype=float))
    return sets


def main(argv=None):
    ap = argparse.ArgumentParser(
        description='Refined-ephemeris verification folds: per-product / '
                    'per-sector raw depths, secondary, odd/even, P/2 '
                    'alias and sub-floor fundamental checks.')
    ap.add_argument('tic')
    ap.add_argument('--period', type=float, required=True,
                    help='refined period in days')
    ap.add_argument('--t0', type=float, required=True,
                    help='refined T0 in BTJD')
    ap.add_argument('--duration', type=float, required=True,
                    help='transit duration in days')
    ap.add_argument('--bulk-period', type=float, default=None,
                    help='unrefined (bulk-screen) period, for the '
                         'harmonics table')
    ap.add_argument('--bulk-t0', type=float, default=None,
                    help='unrefined T0 (provenance only)')
    ap.add_argument('--data-dir', required=True,
                    help='directory of <pfx>_s<NNN>.npz light curves')
    ap.add_argument('--prefixes', nargs='+', default=None,
                    help='product prefixes to load (default: all, e.g. '
                         '--prefixes qlp)')
    ap.add_argument('--out', default='finish_results.json',
                    help='output JSON path')
    ap.add_argument('--half', action='store_true',
                    help='run the P/2 alias test')
    ap.add_argument('--bls', action='store_true',
                    help='run the free BLS + Lomb-Scargle sub-floor check')
    args = ap.parse_args(argv)

    R = {'P': args.period, 'T0': args.t0, 'DUR': args.duration,
         'bulk_P': args.bulk_period, 'bulk_T0': args.bulk_t0}
    sets = load_star(args.data_dir, prefixes=args.prefixes)
    out = {'tic': str(args.tic), 'refined': R}
    print(f"== {args.tic}: sets:",
          {k: sorted(v) for k, v in sets.items()}, flush=True)

    # 1. Verification folds at the REFINED ephemeris, per product and era.
    ver = {}
    for pfx in sorted(sets):
        t, f = concat_sets(sets, pfx)
        ver[pfx] = {'combined': fold_depth(t, f, R['P'], R['T0'], R['DUR']),
                    'secondary_0.5': fold_depth(t, f, R['P'], R['T0'],
                                                R['DUR'], centre_phase=0.5)}
        per_sec = {}
        for s in sorted(sets[pfx]):
            tt, ff = sets[pfx][s]
            per_sec[s] = fold_depth(tt, ff / np.median(ff), R['P'],
                                    R['T0'], R['DUR'])
        ver[pfx]['per_sector'] = per_sec
    out['verify_refined'] = ver
    for pfx, v in ver.items():
        c = v['combined']
        print(f"  {pfx} combined: depth {c['depth_pct']:.3f}% "
              f"white {c['signif_white']:.1f}σ "
              f"red {c['signif_red'] if c['signif_red'] is None else round(c['signif_red'], 1)}σ "
              f"| secondary {v['secondary_0.5']['depth_pct']:.3f}% "
              f"({v['secondary_0.5']['signif_white']:.1f}σ white)", flush=True)
        for s, r in v['per_sector'].items():
            print(f"    s{s}: {r['depth_pct']:.3f}% "
                  f"({r['signif_white']:.1f}σ white)", flush=True)

    # 2. Odd/even at refined ephemeris (best product = most sectors).
    best = max(sets, key=lambda p: len(sets[p]))
    t, f = concat_sets(sets, best)
    odd, even = event_parity_depths(t, f, R['P'], R['T0'], R['DUR'])
    out['odd_even_refined'] = {'product': best, 'odd': odd, 'even': even}
    print(f"  odd/even ({best}): odd {odd['depth_pct']:.3f}% "
          f"({odd['signif_white']:.1f}σ) even {even['depth_pct']:.3f}% "
          f"({even['signif_white']:.1f}σ)", flush=True)

    # 3. P/2 alias test: at half period, even events = primary, odd = secondary.
    if args.half:
        Ph = R['P'] / 2.0
        half = {}
        for pfx in sorted(sets):
            tt, ff = concat_sets(sets, pfx)
            o, e = event_parity_depths(tt, ff, Ph, R['T0'], R['DUR'])
            half[pfx] = {'odd_at_Phalf_secondary': o,
                         'even_at_Phalf_primary': e}
            print(f"  P/2 {pfx}: even(primary) {e['depth_pct']:.3f}% "
                  f"({e['signif_white']:.1f}σ) odd(secondary) "
                  f"{o['depth_pct']:.3f}% ({o['signif_white']:.1f}σ)",
                  flush=True)
        out['half_period_test'] = half

    # 4. Free BLS + Lomb-Scargle over 0.1-1.2 d (sub-floor fundamental check).
    if args.bls:
        from astropy.timeseries import BoxLeastSquares, LombScargle
        t, f = concat_sets(sets, best)
        # light detrend: per-sector median already applied; remove slow
        # trend with 2-d binned medians
        order = np.argsort(t)
        ts, fs = t[order], f[order]
        bins = np.arange(ts.min(), ts.max() + 2.0, 2.0)
        idx = np.digitize(ts, bins)
        trend = np.array([np.median(fs[idx == b]) if np.any(idx == b)
                          else 1.0 for b in range(1, len(bins))])
        trend_full = trend[np.clip(idx - 1, 0, len(trend) - 1)]
        fd = fs / trend_full
        # NOTE: astropy BoxLeastSquares.power takes PERIODS, not frequencies.
        # Build a frequency-linear grid, then pass periods = 1/f.
        freqs = np.linspace(1 / 1.2, 1 / 0.1, 50000)
        periods = 1.0 / freqs
        bls = BoxLeastSquares(ts, fd, dy=np.std(fd))
        res = bls.power(periods, [0.02, 0.04, 0.08], objective='snr')
        power = np.asarray(res.power)
        med, mad = (np.median(power),
                    np.median(np.abs(power - np.median(power))) * 1.4826)
        sde = (power - med) / mad
        peaks = []
        s = sde.copy()
        for _ in range(8):
            i = int(np.argmax(s))
            peaks.append({'period_d': float(periods[i]),
                          'sde': float(sde[i]),
                          'duration_d': float(res.duration[i])})
            m = np.abs(periods - periods[i]) / periods[i] < 0.02
            s[m] = -np.inf

        def sde_at(P):
            j = int(np.argmin(np.abs(periods - P)))
            return float(sde[j])

        harm = {f'P/{k}': {'period_d': R['P'] / k, 'sde': sde_at(R['P'] / k)}
                for k in (1, 2, 3, 4)}
        if R['bulk_P']:
            harm['P_filed'] = {'period_d': R['bulk_P'],
                               'sde': sde_at(R['bulk_P'])}
        ls = LombScargle(ts, fd, normalization='standard')
        lf = np.linspace(1 / 2.0, 1 / 0.1, 30000)
        lp = ls.power(lf)
        lper = 1 / lf
        lpeaks = []
        l = lp.copy()
        for _ in range(5):
            i = int(np.argmax(l))
            lpeaks.append({'period_d': float(lper[i]),
                           'power': float(lp[i])})
            m = np.abs(lper - lper[i]) / lper[i] < 0.02
            l[m] = -np.inf
        out['free_bls'] = {'product': best, 'n_points': len(ts),
                           'top_peaks': peaks, 'harmonics': harm}
        out['lomb_scargle'] = {'top_peaks': lpeaks}
        print('  BLS top peaks:',
              [(p['period_d'], round(p['sde'], 1)) for p in peaks],
              flush=True)
        print('  BLS harmonics:',
              {k: round(v['sde'], 1) for k, v in harm.items()}, flush=True)
        print('  LS top peaks:',
              [(p['period_d'], round(p['power'], 3)) for p in lpeaks],
              flush=True)

    with open(args.out, 'w') as fh:
        json.dump(out, fh, indent=1)
    print(f'wrote {args.out}', flush=True)


if __name__ == '__main__':
    main()
