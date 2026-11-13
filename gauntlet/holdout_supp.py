#!/usr/bin/env python3
"""Supplementary holdout analyses for stars with too few sectors.

The canonical holdout (holdout_test.py, repo root) needs >= 3 sector
folds; a star with only 2 sectors stamps HOLDOUT-INSUFFICIENT-DATA by
design. These supplementary tests answer the questions the canonical
test cannot, honestly labelled:

  A. INDEPENDENT SINGLE-SECTOR BLS: run BLS on each sector's
     flattened flux alone. If both sectors independently yield the
     same period, the two eras see the same clock without either
     being fit to the other. (The phase offset between the two
     independent ephemerides is expected to be large — a single
     sector cannot phase-connect across a multi-year gap — so PERIOD
     agreement is the meaningful number.)

  B. WITHIN-SECTOR SPLIT-HALF HOLDOUT: per sector, split transits by
     parity (odd/even transit index). Refit the ephemeris by BLS on
     the TRAIN half's flattened flux only (narrow grid, same
     machinery as holdout_test._refine_ephemeris), then measure the
     predicted transits in the TEST half's RAW flux with
     hunter._raw_fold_depth. Test transits are interleaved with
     train transits (max gap ~1 P), so period-error smearing is
     negligible. This tests predictive periodicity WITHIN each era,
     not cross-era coherence — stated plainly in any report.

  C. CROSS-ERA PHASE-COHERENCE BUDGET: the period precision a blind
     cross-era prediction would need (duration / 2N cycles) vs the
     single-sector precision actually achieved — quantifying WHY a
     blind holdout across the era gap is impossible with 2 sectors,
     and what a phase-scan coherence does and does not prove.

Usage:
  holdout_supp.py TIC --period P --t0 T0 --duration DUR \\
      --data-dir data/ --prefix qlp --sectors 32 98 \\
      [--bulk-period-error E] [--out holdout_supp.json]

Generalised from holdout_supp.py (TIC 423498314, 2026-11-13):
hardcoded star/sectors became CLI arguments; the flatten recipe
(transit-masked Savitzky-Golay, 1.5 d window), BLS grids and the
split-half machinery are unchanged.
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


def load(data_dir, prefix, sectors):
    out = {}
    for sec in sectors:
        z = np.load(os.path.join(data_dir, f'{prefix}_s{sec:03d}.npz'))
        t = np.asarray(z['time'], float)
        f = np.asarray(z['flux'], float)
        ok = np.isfinite(t) & np.isfinite(f)
        out[sec] = (t[ok], f[ok])
    return out


def flatten(t, f, period, t0, duration_d, window=1.5):
    """Transit-masked Savitzky-Golay detrend (the holdout_supp recipe):
    an unmasked pass (computed, then discarded) followed by a
    transit-masked second pass whose trend is applied."""
    from scipy.signal import savgol_filter
    order = np.argsort(t)
    t, f = t[order], f[order]
    dt = np.median(np.diff(t))
    w = int(window / dt)
    w = w if w % 2 == 1 else w + 1
    w = max(w, 51)
    trend = savgol_filter(f, w, 3)
    flat = f / trend  # noqa: F841  (first pass, kept for parity)
    ph = (((t - t0) / period + 0.5) % 1.0) - 0.5
    m = np.abs(ph) < (duration_d / period)
    f2 = np.where(m, np.nan, f)
    good = np.isfinite(f2)
    f_fill = np.interp(t, t[good], f2[good])
    trend2 = savgol_filter(f_fill, w, 3)
    return t, f / trend2, f  # time, flattened, raw


def bls_top(t, f, duration_d, p_lo=0.5, p_hi=1.2):
    import astropy.units as u
    from astropy.timeseries import BoxLeastSquares
    bls = BoxLeastSquares(t * u.day, f)
    periods = np.linspace(p_lo, p_hi, 20000) * u.day
    durations = np.array([0.6, 1.0, 1.5]) * duration_d * u.day
    res = bls.power(periods, durations)
    i = int(np.argmax(res.power))
    return (float(res.period[i].value), float(res.transit_time[i].value),
            float(res.power[i]))


def main(argv=None):
    ap = argparse.ArgumentParser(
        description='Supplementary holdout analyses for stars with too '
                    'few sectors for the canonical holdout: independent '
                    'single-sector BLS, within-sector split-half '
                    'holdout, cross-era coherence budget.')
    ap.add_argument('tic')
    ap.add_argument('--period', type=float, required=True,
                    help='refined period in days')
    ap.add_argument('--t0', type=float, required=True,
                    help='refined T0 in BTJD')
    ap.add_argument('--duration', type=float, required=True,
                    help='transit duration in days')
    ap.add_argument('--data-dir', required=True)
    ap.add_argument('--prefix', default='qlp',
                    help='npz prefix (default qlp)')
    ap.add_argument('--sectors', type=int, nargs='+', required=True)
    ap.add_argument('--bulk-period-error', type=float, default=None,
                    help='bulk-screen period error in days (for the '
                         'coherence budget note)')
    ap.add_argument('--out', default='holdout_supp.json')
    args = ap.parse_args(argv)

    P_REF, T0_REF, DUR = args.period, args.t0, args.duration
    data = load(args.data_dir, args.prefix, args.sectors)
    out = {'tic': str(args.tic), 'P_refined': P_REF,
           'T0_refined': T0_REF, 'duration_d': DUR}

    # ---- A. independent single-sector BLS ----
    indep = {}
    for sec, (t, f) in sorted(data.items()):
        tf, ff, _ = flatten(t, f, P_REF, T0_REF, DUR)
        p, t0, power = bls_top(tf, ff, DUR)
        indep[sec] = {'period_days': p, 't0_btjd': t0,
                      'bls_power': power,
                      'n_points': int(len(t)),
                      'baseline_d': float(t.max() - t.min()),
                      'period_minus_refined_d': p - P_REF}
        print(f'[A] S{sec}: P={p:.6f} (refined {P_REF}, '
              f'dP={p - P_REF:+.2e}) t0={t0:.4f} power={power:.2f} '
              f'n={len(t)}', flush=True)
    out['independent_single_sector_bls'] = indep

    # ---- C. cross-era phase-coherence budget ----
    secs_sorted = sorted(data)
    t_first = data[secs_sorted[0]][0]
    t_last = data[secs_sorted[-1]][0]
    dt_eras = float(np.median(t_last) - np.median(t_first))
    n_cycles = dt_eras / P_REF
    need = DUR / (2.0 * n_cycles)
    out['cross_era_budget'] = {
        'era_gap_d': dt_eras, 'cycles_between_eras': n_cycles,
        'period_precision_needed_for_blind_phase_connection_d': need,
        'bulk_period_error_d': args.bulk_period_error,
        'note': (f'A blind s{secs_sorted[-1]}->s{secs_sorted[0]} '
                 f'prediction needs the period to ~{need:.1e} d; '
                 'single-sector BLS achieves ~1e-4 d at best, so the '
                 'phase drifts across the gap and the fold washes out. '
                 'A phase scan that finds the dip at full depth at ONE '
                 'corrected period shows phase coherence across the '
                 f'gap (~{dt_eras:.0f} d) — but the correction was fit '
                 'using both eras, so it is not a blind prediction.'),
    }
    print(f'[C] era gap {dt_eras:.0f} d = {n_cycles:.0f} cycles; blind '
          f'phase-connection needs dP < {need:.2e} d', flush=True)

    # ---- B. within-sector split-half holdout ----
    import hunter  # for _raw_fold_depth (same machinery as the gate)
    from holdout_test import _refine_ephemeris
    folds = []
    for sec, (t, f) in sorted(data.items()):
        tf, ff, rf = flatten(t, f, P_REF, T0_REF, DUR)
        k = np.round((t - T0_REF) / P_REF).astype(int)
        for parity, train_par in ((0, 0), (1, 1)):
            train_m = (k % 2 == train_par)
            test_m = ~train_m
            ref = _refine_ephemeris(tf[train_m], ff[train_m], P_REF, DUR)
            fold = {'sector': sec, 'train_parity': train_par,
                    'n_train_points': int(train_m.sum()),
                    'n_test_points': int(test_m.sum())}
            if ref is None:
                fold['usable'] = False
                fold['reason'] = 'refinement lost on train half'
                folds.append(fold)
                print(f'[B] S{sec} train parity {train_par}: REFIT LOST',
                      flush=True)
                continue
            p_ref, t0_ref = ref
            fold['refined_period_days'] = p_ref
            fold['refined_t0_btjd'] = t0_ref
            depth, signif = hunter._raw_fold_depth(
                t[test_m], rf[test_m], p_ref, t0_ref, DUR)
            fold['depth_pct'] = float(depth)
            fold['signif'] = float(signif)
            fold['usable'] = True
            folds.append(fold)
            print(f'[B] S{sec} train parity {train_par}: P\'={p_ref:.6f} '
                  f'test depth {depth:+.3f}% at {signif:+.1f} sigma',
                  flush=True)
    out['split_half_holdout'] = folds
    usable = [f for f in folds if f.get('usable')]
    if usable:
        sig = np.array([f['signif'] for f in usable])
        dep = np.array([f['depth_pct'] for f in usable])
        sg = np.array([abs(f['depth_pct'] / f['signif']) if f['signif'] != 0
                       else np.nan for f in usable])
        ok = np.isfinite(sg) & (sg > 0)
        w = 1.0 / sg[ok] ** 2
        comb_d = float(np.sum(w * dep[ok]) / np.sum(w))
        comb_s = float(1.0 / np.sqrt(np.sum(w)))
        out['split_half_combined'] = {
            'n_usable_folds': len(usable),
            'folds_at_or_above_3sigma': int((sig >= 3.0).sum()),
            'folds_opposite_le_-3sigma': int((sig <= -3.0).sum()),
            'combined_depth_pct': comb_d,
            'combined_signif': comb_d / comb_s,
        }
        print(f"[B] combined: {comb_d:+.3f}% at {comb_d / comb_s:+.1f} "
              f"sigma; folds >=3sigma: {(sig >= 3).sum()}/{len(usable)}",
              flush=True)

    with open(args.out, 'w') as fh:
        json.dump(out, fh, indent=2, default=str)
    print(f'wrote {args.out}', flush=True)


if __name__ == '__main__':
    main()
