#!/usr/bin/env python3
"""Canonical holdout test over an EXTENDED sector set.

holdout_test.py (repo root) fetches data via the production pipeline —
for a QLP-only star with 2 sectors that stamps
HOLDOUT-INSUFFICIENT-DATA, and it cannot see TESSCut-extracted sectors
at all. This driver runs the SAME fold loop verbatim — same partition
rule, same holdout_test._refine_ephemeris, same _window_coverage /
_chunk_count pre-checks, same hunter._raw_fold_depth measurement,
same verdict constants (MIN_USABLE_FOLDS=3, majority >= 3 sigma,
combined >= 3 sigma, no opposite <= -3 sigma) — over a sector set
given on the command line, mixing pipeline npz files (qlp/spoc/tspc)
and TESSCut-extracted npz files.

Two flux variants are run and BOTH stamps reported:
  * plain raw — background-subtracted aperture flux, unflattened
    (verbatim "raw"; FFI scattered-light trends make the red-noise
    bar very harsh);
  * bgreg raw — raw + background-light-curve regressor (out-of-
    transit fit only; still unflattened, no Savitzky-Golay, no
    transit masking). This is the stage-5c common-mode recipe, and
    the primary stamp: QLP raw flux is already systematics-corrected,
    TESSCut raw pixels are not, and the regressor makes them
    comparable. The deviation is stated, not hidden.

Train flux (for the BLS refit) is transit-masked Savitzky-Golay
flattened in both variants.

Usage:
  holdout_extended.py TIC --period P --t0 T0 --duration DUR \\
      --data-dir data/ --sectors qlp:32 qlp:98 tesscut:107 tesscut:108 \\
      [--variants bgreg raw] [--out holdout_extended.json]

Generalised from holdout_new_sectors.py (TIC 423498314, 2026-11-13):
the hardcoded sector list became CLI arguments; the fold loop,
flatten recipe and verdict logic are unchanged.
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

import hunter  # noqa: E402
import holdout_test as ht  # noqa: E402


def flatten(t, f, period, t0, duration_d, window=1.5):
    """Transit-masked Savitzky-Golay flatten (the holdout recipe):
    sorts, drops non-finite points, caps the window at len//2*2-1,
    masks |phase| < DUR/P and interpolates over it."""
    from scipy.signal import savgol_filter
    order = np.argsort(t)
    t, f = t[order], f[order]
    ok = np.isfinite(t) & np.isfinite(f)
    t, f = t[ok], f[ok]
    dt = np.median(np.diff(t))
    w = int(window / dt)
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


def parse_sectors(specs):
    """'qlp:32' -> (32, 'qlp'); bare '32' defaults to 'qlp'."""
    out = []
    for s in specs:
        if ':' in s:
            kind, sec = s.split(':', 1)
        else:
            kind, sec = 'qlp', s
        out.append((int(sec), kind))
    return out


def load_sectors(data_dir, sector_specs, period, t0, duration_d, variant):
    """Returns chronological sector list with flat (train) and raw
    (held-out measurement) flux. variant: 'raw' or 'bgreg'.
    For tesscut sectors, 'bgreg' reads flux_bgreg and 'raw' reads
    flux; pipeline sectors read flux in both variants (their raw flux
    is already systematics-corrected)."""
    secs = []
    for sec, kind in sector_specs:
        z = np.load(os.path.join(data_dir, f'{kind}_s{sec:03d}.npz'))
        t = np.asarray(z['time'], float)
        if kind == 'tesscut' and variant == 'bgreg':
            raw = np.asarray(z['flux_bgreg'], float)
        else:
            raw = np.asarray(z['flux'], float)
        if kind != 'tesscut':
            raw = raw / np.median(raw)
        ok = np.isfinite(t) & np.isfinite(raw)
        t, raw = t[ok], raw[ok]
        ft, ff = flatten(t, raw, period, t0, duration_d)
        secs.append({'sector': sec, 'tmin': float(t.min()),
                     'tmax': float(t.max()), 'ft': ft, 'ff': ff,
                     'rt': t, 'rf': raw})
    secs.sort(key=lambda s: s['tmin'])
    return secs


def run_holdout(tic, period, t0, duration_d, sectors, variant):
    n = len(sectors)
    result = {
        'tic': str(tic), 'period_days': period, 't0_btjd': t0,
        'duration_hours': duration_d * 24.0, 'flux_variant': variant,
        'n_sectors_total': n,
        'sectors': [s['sector'] for s in sectors],
        'criteria': {
            'min_usable_folds': ht.MIN_USABLE_FOLDS,
            'min_total_full_events': ht.MIN_TOTAL_FULL_EVENTS,
            'fold_signif_bar': ht.FOLD_SIGNIF_BAR,
            'opposite_bar': ht.OPPOSITE_BAR,
            'pass_rule': 'strict majority of usable folds >= bar AND '
                         'combined >= bar AND no fold <= opposite bar',
        },
        'folds': [],
    }
    if n < ht.MIN_USABLE_FOLDS:
        result['verdict'] = 'HOLDOUT-INSUFFICIENT-DATA'
        result['reason'] = f'only {n} usable sector(s)'
        return result
    # canonical partition: n <= 6 -> one fold per sector
    groups = [[i] for i in range(n)]
    for gi, group in enumerate(groups):
        gset = set(group)
        train_t = np.concatenate([sectors[i]['ft']
                                  for i in range(n) if i not in gset])
        train_f = np.concatenate([sectors[i]['ff']
                                  for i in range(n) if i not in gset])
        fold_t = np.concatenate([sectors[i]['rt'] for i in group])
        fold_f = np.concatenate([sectors[i]['rf'] for i in group])
        fold = {
            'fold': gi,
            'held_out_sectors': [sectors[i]['sector'] for i in group],
            'tmin': float(min(sectors[i]['tmin'] for i in group)),
            'tmax': float(max(sectors[i]['tmax'] for i in group)),
            'n_raw_points': int(len(fold_t)),
            'usable': False, 'reason': None,
            'refined_period_days': None, 'refined_t0_btjd': None,
            'events_in_span': None, 'full_events': None,
            'depth_pct': None, 'signif': None, 'n_chunks_out': None,
        }
        ref = ht._refine_ephemeris(train_t, train_f, period, duration_d)
        if ref is None:
            fold['reason'] = ('refinement lost: training BLS found no '
                              'peak within 1% of the filed period')
            result['folds'].append(fold)
            continue
        p_ref, t0_ref = ref
        fold['refined_period_days'] = p_ref
        fold['refined_t0_btjd'] = t0_ref
        n_span = n_full = 0
        for i in group:
            s_span, s_full, _ = ht._window_coverage(
                sectors[i]['rt'], sectors[i]['tmin'], sectors[i]['tmax'],
                p_ref, t0_ref, duration_d)
            n_span += s_span
            n_full += s_full
        fold['events_in_span'] = n_span
        fold['full_events'] = n_full
        phase = ((fold_t - t0_ref + 0.5 * p_ref) % p_ref) - 0.5 * p_ref
        in_m = np.abs(phase) <= duration_d / 2.0
        out_m = np.abs(phase) > duration_d
        n_chunks = ht._chunk_count(fold_t[out_m], duration_d)
        fold['n_chunks_out'] = n_chunks
        if n_full < 1:
            fold['reason'] = 'no fully-covered predicted window held out'
        elif in_m.sum() < 20 or out_m.sum() < 50:
            fold['reason'] = ('too few held-out points '
                              f'(in {int(in_m.sum())}, '
                              f'out {int(out_m.sum())})')
        elif n_chunks < 2:
            fold['reason'] = 'fewer than 2 out-of-transit noise chunks'
        else:
            depth_pct, signif = hunter._raw_fold_depth(
                fold_t, fold_f, p_ref, t0_ref, duration_d)
            fold['depth_pct'] = float(depth_pct)
            fold['signif'] = float(signif)
            fold['sigma_pct'] = (float(depth_pct / signif)
                                 if signif not in (0.0, -0.0) else None)
            fold['usable'] = True
        result['folds'].append(fold)

    usable = [f for f in result['folds'] if f['usable']]
    total_full = int(sum(f['full_events'] or 0 for f in usable))
    result['n_folds'] = len(result['folds'])
    result['n_usable_folds'] = len(usable)
    result['total_full_events_held_out'] = total_full
    if (len(usable) < ht.MIN_USABLE_FOLDS
            or total_full < ht.MIN_TOTAL_FULL_EVENTS):
        result['verdict'] = 'HOLDOUT-INSUFFICIENT-DATA'
        result['reason'] = (f'{len(usable)} usable fold(s), {total_full} '
                            'fully-covered held-out window(s)')
        return result
    sig = np.array([f['signif'] for f in usable], dtype=float)
    dep = np.array([f['depth_pct'] for f in usable], dtype=float)
    sg = np.array([abs(f['depth_pct'] / f['signif']) if f['signif'] != 0
                   else np.nan for f in usable], dtype=float)
    ok = np.isfinite(sg) & (sg > 0)
    comb_signif = None
    comb_depth = None
    if ok.sum() >= 1 and np.all(np.isfinite(dep[ok])):
        w = 1.0 / sg[ok] ** 2
        comb_depth = float(np.sum(w * dep[ok]) / np.sum(w))
        comb_sigma = float(1.0 / np.sqrt(np.sum(w)))
        comb_signif = comb_depth / comb_sigma if comb_sigma > 0 else None
    n_pos = int((sig >= ht.FOLD_SIGNIF_BAR).sum())
    n_neg = int((sig <= ht.OPPOSITE_BAR).sum())
    result.update({
        'folds_at_or_above_bar': n_pos,
        'folds_opposite': n_neg,
        'combined_depth_pct': comb_depth,
        'combined_signif': comb_signif,
    })
    if (n_pos > len(usable) / 2.0 and comb_signif is not None
            and comb_signif >= ht.FOLD_SIGNIF_BAR and n_neg == 0):
        result['verdict'] = 'HOLDOUT-PASS'
    else:
        result['verdict'] = 'HOLDOUT-FAIL'
    return result


def main(argv=None):
    ap = argparse.ArgumentParser(
        description='Canonical holdout test over an extended sector set '
                    '(pipeline + TESSCut sectors), both flux variants.')
    ap.add_argument('tic')
    ap.add_argument('--period', type=float, required=True)
    ap.add_argument('--t0', type=float, required=True)
    ap.add_argument('--duration', type=float, required=True,
                    help='transit duration in days')
    ap.add_argument('--data-dir', required=True)
    ap.add_argument('--sectors', nargs='+', required=True,
                    help='sector specs like qlp:32 tesscut:107 '
                         '(bare numbers default to qlp)')
    ap.add_argument('--variants', nargs='+', default=['bgreg', 'raw'],
                    help='flux variants to run (default: bgreg raw)')
    ap.add_argument('--out', default='holdout_extended.json')
    args = ap.parse_args(argv)

    specs = parse_sectors(args.sectors)
    out = {}
    for variant in args.variants:
        print(f'\n===== flux variant: {variant} =====', flush=True)
        sectors = load_sectors(args.data_dir, specs, args.period,
                               args.t0, args.duration, variant)
        res = run_holdout(args.tic, args.period, args.t0,
                          args.duration, sectors, variant)
        out[variant] = res
        print(f"sectors: {res['n_sectors_total']}  folds: "
              f"{res.get('n_folds')}  usable: {res.get('n_usable_folds')}",
              flush=True)
        for f in res['folds']:
            secs = ','.join(str(s) for s in f['held_out_sectors'])
            if f['usable']:
                print(f"  fold {f['fold']} [S{secs}] P' "
                      f"{f['refined_period_days']:.6f} "
                      f"windows {f['full_events']}/{f['events_in_span']} "
                      f"depth {f['depth_pct']:+.4f}%  {f['signif']:+.1f} "
                      f'sigma', flush=True)
            else:
                print(f"  fold {f['fold']} [S{secs}] UNUSABLE — "
                      f"{f['reason']}", flush=True)
        if res.get('combined_signif') is not None:
            print(f"combined held-out depth "
                  f"{res['combined_depth_pct']:+.4f}% at "
                  f"{res['combined_signif']:+.1f} sigma; "
                  f"folds >= 3 sigma: {res['folds_at_or_above_bar']}, "
                  f"opposite: {res['folds_opposite']}", flush=True)
        print(f"STAMP [{variant}]: {res['verdict']}"
              + (f" — {res['reason']}" if res.get('reason') else ''),
              flush=True)
    with open(args.out, 'w') as fh:
        json.dump(out, fh, indent=2, default=str)
    print(f'\nwrote {args.out}', flush=True)


if __name__ == '__main__':
    main()
