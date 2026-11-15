#!/usr/bin/env python3
"""Fold a NEIGHBOUR star's light curve at the target's ephemeris.

The blend test: if the neighbour shows the same dip at the same
ephemeris — especially a much deeper one — the signal lives on the
neighbour, not the target, and the target's dip is a photocopy
(TIC 31054247 / TIC 14174515: neighbours at 42-49" with 5-14% eclipses
explaining ~1% target dips).

Tries QLP first, then an unfiltered search (eleanor-lite/TASOC HLSP)
for faint neighbours. Downloads with retries, picks the first
available flux column (sap_flux / kspsap_flux / pca_flux / raw_flux /
flux), and folds at the target's refined ephemeris. Writes the
neighbour's npz files under WORKDIR/neighbour_<tic>/ (nb_s<NNN>.npz).

Quality handling (DF-3, 2026-11-15): the QLP-first search means a
neighbour light curve CAN carry QLP bits 29/30, so the downloaded
curve is masked with the pipeline's quality mask (default deep_v2)
before any processing — the M-8 pattern, mirroring
gauntlet/common.py:load_tpf. Without it the blend test would
compare the target's masked fold against the neighbour's unmasked
fold, and a flagged-only artifact on the neighbour could read as
a deep eclipse (a false blend kill) or vice versa.

Usage:
  neighbour_fold.py TARGET_TIC NEIGHBOUR_TIC --period P --t0 T0 \\
      --duration DUR --workdir work/TIC [--max-sectors 6]

With --target-npz <npz> (a target light curve with time/flux
arrays), the script also runs the blend verdict
(gauntlet/blend.py:check_blend) on the target + combined
neighbour folds and records it in the output JSON.

Generalised from archive/scripts/neighbour_fold_s98.py (2026-11-13): the hardcoded
REFINED dict became CLI arguments; fold_depth moved to common.py.
The search order, sector dedupe, retry ladder, flux-column selection
and output schema are unchanged.
"""
import argparse
import json
import os
import sys
import time
import warnings

warnings.filterwarnings('ignore')
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from gauntlet.common import fold_depth
    from gauntlet.blend import check_blend
except ImportError:  # run as a plain script from the gauntlet dir
    from common import fold_depth
    from blend import check_blend


def _masked_keep(lc, quality_mask):
    """Boolean keep-mask for a downloaded neighbour light curve:
    (q & mask) == 0, with the quality array cast to int64 first
    (SPOC 16-bit QUALITY overflows a bare bitwise AND — DF-5).
    Returns None when the product carries no quality column
    (some HLSP products) — the caller then keeps all cadences,
    as before."""
    if 'quality' not in lc.colnames:
        return None
    q = np.asarray(lc['quality'].value, dtype=np.int64)
    return (q & int(quality_mask)) == 0


def fetch_neighbour(tic, outdir, max_sectors=6, quality_mask=None):
    """QLP first, then an unfiltered search. Returns
    {sector: (t, f)} (possibly empty). The downloaded curve is
    masked with the pipeline's quality mask (default deep_v2)
    before extraction, so the neighbour fold compares against
    the target's masked fold on equal terms (DF-3)."""
    import lightkurve as lk
    import netbound as _net
    if quality_mask is None:
        from quality_flags import DEEP_V2_MASK
        quality_mask = DEEP_V2_MASK
    os.makedirs(outdir, exist_ok=True)
    lcs = {}
    for author in ('QLP', None):
        try:
            # C-1: lightkurve takes no timeout — watch the call.
            if author:
                sr = _net.mast_call(
                    lambda: lk.search_lightcurve(f'TIC {tic}',
                                                 author=author),
                    name=f"neighbour search TIC {tic} ({author})")
            else:
                sr = _net.mast_call(
                    lambda: lk.search_lightcurve(f'TIC {tic}'),
                    name=f"neighbour search TIC {tic} (all)")
        except Exception as e:
            print(f'  search {author or "all"} failed: {e}', flush=True)
            continue
        if len(sr) == 0:
            print(f"  search {author or 'all'}: no products", flush=True)
            continue
        print(f"  search {author or 'all'}: {len(sr)} rows", flush=True)
        try:
            tbl = sr.table
            by_sec = {}
            for i in range(len(tbl)):
                s = int(tbl['sequence_number'][i])
                by_sec.setdefault(s, i)
            rows = [by_sec[s] for s in sorted(by_sec)][:max_sectors]
            sr = sr[rows]
        except Exception:
            sr = sr[:max_sectors]
        for i in range(len(sr)):
            row = sr[i]
            sec = None
            try:
                sec = int(row.table['sequence_number'][0])
            except Exception:
                pass
            lc = None
            for attempt in range(3):
                try:
                    # C-1: watch the download too — a hung row
                    # download retries like any other failure.
                    lc = _net.mast_call(
                        lambda: row.download(),
                        name=f"neighbour download TIC {tic} s{sec}")
                    break
                except Exception as e:
                    print(f'    download s{sec} attempt {attempt + 1} '
                          f'failed: {e}', flush=True)
                    time.sleep(5 * (attempt + 1))
                    lc = None
            if lc is None:
                continue
            try:
                col = None
                for c in ('sap_flux', 'kspsap_flux', 'pca_flux',
                          'raw_flux', 'flux'):
                    if c in lc.colnames:
                        col = c
                        break
                t = np.asarray(lc.time.value, float)
                f = np.asarray(lc[col].value, float)
                keep = _masked_keep(lc, quality_mask)
                n_masked = 0
                if keep is not None:
                    n_masked = int((~keep).sum())
                    t, f = t[keep], f[keep]
                m = np.isfinite(t) & np.isfinite(f) & (f > 0)
                t, f = t[m], f[m]
                if sec is None:
                    sec = int(round(np.median(t) // 27))  # fallback, unused
                lcs[sec] = (t, f)
                np.savez(os.path.join(outdir, f'nb_s{sec:03d}.npz'),
                         time=t, flux=f)
                print(f'    s{sec}: {len(t)} pts ({col})'
                      + (f', {n_masked} masked'
                         if n_masked else ''), flush=True)
            except Exception as e:
                print(f'    s{sec} process failed: {e}', flush=True)
        if lcs:
            return lcs
    return lcs


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Fold a neighbour star's light curve at the target's "
                    'ephemeris — a deep dip on the neighbour means the '
                    "target's dip is a photocopy (blend).")
    ap.add_argument('target', help='target TIC id')
    ap.add_argument('neighbour', help='neighbour TIC id')
    ap.add_argument('--period', type=float, required=True,
                    help='target refined period in days')
    ap.add_argument('--t0', type=float, required=True,
                    help='target refined T0 in BTJD')
    ap.add_argument('--duration', type=float, required=True,
                    help='transit duration in days')
    ap.add_argument('--workdir', required=True,
                    help='output directory (neighbour_<tic>/ + '
                         'neighbour_<tic>_fold.json)')
    ap.add_argument('--max-sectors', type=int, default=6)
    ap.add_argument('--target-npz', default=None,
                    help='target light curve npz (time/flux) — '
                         'when given, run the blend verdict on '
                         'the target + combined neighbour folds')
    args = ap.parse_args(argv)

    R = {'P': args.period, 'T0': args.t0, 'DUR': args.duration}
    outdir = os.path.join(args.workdir, f'neighbour_{args.neighbour}')
    print(f"== neighbour {args.neighbour} of target {args.target} "
          f"(P={R['P']}, T0={R['T0']}, DUR={R['DUR']})", flush=True)
    lcs = fetch_neighbour(args.neighbour, outdir,
                          max_sectors=args.max_sectors)
    out_path = os.path.join(args.workdir,
                            f"neighbour_{args.neighbour}_fold.json")
    if not lcs:
        print('  NO LIGHT CURVE AVAILABLE for neighbour', flush=True)
        out = {'target': str(args.target),
               'neighbour': str(args.neighbour),
               'available': False}
        if args.target_npz:
            out['blend'] = {
                'verdict': 'unmeasured',
                'reason': 'no neighbour light curve available'}
        with open(out_path, 'w') as fh:
            json.dump(out, fh, indent=1)
        return
    res = {'target': str(args.target), 'neighbour': str(args.neighbour),
           'available': True, 'ephemeris': R, 'per_sector': {}}
    ts, fs = [], []
    for s in sorted(lcs):
        t, f = lcs[s]
        f = f / np.median(f)
        r = fold_depth(t, f, R['P'], R['T0'], R['DUR'])
        res['per_sector'][s] = r
        print(f"  s{s}: depth {r['depth_pct']:.3f}% "
              f"(white {r['signif_white']:.1f}σ, red "
              f"{r['signif_red'] if r['signif_red'] is None else round(r['signif_red'], 1)}σ)",
              flush=True)
        ts.append(t)
        fs.append(f)
    t = np.concatenate(ts)
    f = np.concatenate(fs)
    res['combined'] = fold_depth(t, f, R['P'], R['T0'], R['DUR'])
    c = res['combined']
    print(f"  COMBINED: depth {c['depth_pct']:.3f}% "
          f"(white {c['signif_white']:.1f}σ, red "
          f"{c['signif_red'] if c['signif_red'] is None else round(c['signif_red'], 1)}σ, "
          f"n_in={c['n_in']})", flush=True)
    if args.target_npz:
        z = np.load(args.target_npz)
        tt = np.asarray(z['time'], float)
        tf = np.asarray(z['flux'], float)
        tf = tf / np.median(tf)
        verdict = check_blend(tt, tf, t, f, R['P'], R['T0'],
                              R['DUR'],
                              neighbour_tic=args.neighbour)
        res['blend'] = verdict
        print(f"  BLEND VERDICT: {verdict['verdict']} — "
              f"{verdict['reason']}", flush=True)
    with open(out_path, 'w') as fh:
        json.dump(res, fh, indent=1)


if __name__ == '__main__':
    main()
