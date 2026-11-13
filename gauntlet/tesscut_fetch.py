#!/usr/bin/env python3
"""Download TESSCut FFI cutouts and record the WCS identity.

For stars with no 2-minute data (no SPOC TPFs), TESSCut cutouts are
the imaging substrate. For each requested sector this downloads a
cutout (15x15 px default) via lightkurve's TESSCut search, checks the
target is actually on-silicon, and records the WCS pixel positions of
the target and (optionally) a neighbour, plus a flux-centroid
cross-check of the identity.

Writes <outdir>/tesscut_s<NNN>.fits and an identity JSON with the
stage5a schema (target/neighbour blocks, cutout_size_px, per-sector
shape / cadences / cadence / time span / target_px / neighbour_px /
separation_px / whole-cutout flux centroid / centroid-target offset /
median total flux / file), plus additive fields: status (OK/NO-DATA),
on_silicon, and a LOCAL 5x5 flux centroid (the whole-cutout centroid
is pulled off-target by any bright star in the cutout — the local
centroid is the honest identity check).

Sectors where TESSCut has no cutout, the download fails after the
retry ladder, or the target is off-CCD are recorded as NO-DATA with a
reason — never silently skipped.

Usage:
  tesscut_fetch.py TIC --ra RA --dec DEC --sectors 32 98 107 \\
      --outdir tesscut/ [--neighbour-tic T --neighbour-ra RA \\
      --neighbour-dec DEC] [--size 15] [--identity-out identity.json]

Generalised from stage5a_tesscut.py + newsectors_download.py
(2026-11-13): hardcoded coordinates/sectors became CLI arguments; the
download retry ladder (30/60/120/300 s) is from
newsectors_download.py; the identity schema is stage5a's, with the
newsectors additions (cadence_min, tmin/tmax) and the additive
status/on-silicon/local-centroid fields.
"""
import argparse
import json
import os
import time
import warnings

warnings.filterwarnings('ignore')
import numpy as np


def fetch_sector(tic, sector, outdir, size=15, retries=(30, 60, 120, 300)):
    """Download one sector's cutout (lightkurve TESSCut) with a retry
    ladder. Returns (tpf, path), or (None, reason) if TESSCut has
    nothing or the download fails."""
    import lightkurve as lk
    path = os.path.join(outdir, f'tesscut_s{sector:03d}.fits')
    if os.path.exists(path):
        print(f'S{sector}: cached {path}', flush=True)
        return lk.read(path), path
    print(f'S{sector}: querying TESSCut ...', flush=True)
    sr = lk.search_tesscut(f'TIC {tic}', sector=sectortor)
    print(f'S{sector}: {len(sr)} cutout(s) found', flush=True)
    if len(sr) == 0:
        return None, 'no TESSCut cutout found'
    tpf = None
    for attempt, wait in enumerate(retries):
        try:
            tpf = sr.download(cutout_size=size)
            break
        except Exception as e:
            print(f'S{sector}: download attempt {attempt + 1} failed '
                  f'({type(e).__name__}: {str(e)[:120]}); '
                  f'retry in {wait}s', flush=True)
            time.sleep(wait)
    if tpf is None:
        return None, 'download failed after 4 attempts (MAST 504/timeout)'
    tpf.to_fits(path, overwrite=True)
    print(f'S{sector}: saved {path} ({os.path.getsize(path) / 1e6:.1f} MB)',
          flush=True)
    return tpf, path


def identity_for(tpf, path, ra, dec, neighbour=None):
    """WCS identity record for one cutout (stage5a schema + additions).
    Uses the full (unfiltered) TPF, as stage5a did."""
    from astropy.coordinates import SkyCoord
    wcs = tpf.wcs
    c_t = SkyCoord(ra, dec, unit='deg')
    x_t, y_t = wcs.world_to_pixel(c_t)
    x_t, y_t = float(x_t), float(y_t)
    med = np.nanmedian(tpf.flux.value, axis=0)
    bg = np.nanmedian(med)
    w = np.clip(med - bg, 0, None)
    yy, xx = np.mgrid[0:med.shape[0], 0:med.shape[1]]
    cx = float((w * xx).sum() / w.sum())
    cy = float((w * yy).sum() / w.sum())
    dt = np.median(np.diff(np.sort(np.asarray(tpf.time.value))))
    ny, nx = med.shape
    on_silicon = (2 <= x_t < nx - 2) and (2 <= y_t < ny - 2)
    rec = {'shape': list(tpf.flux.shape),
           'n_cadences': int(len(tpf.time)),
           'cadence_min': float(dt * 24 * 60),
           'tmin_btjd': float(tpf.time.value.min()),
           'tmax_btjd': float(tpf.time.value.max()),
           'target_px': [float(x_t), float(y_t)],
           'flux_centroid_px': [cx, cy],
           'centroid_target_offset_px': float(np.hypot(cx - x_t,
                                                       cy - y_t)),
           'median_flux_total_e_per_s': float(np.nansum(med - bg)),
           'file': path,
           'on_silicon': bool(on_silicon),
           'status': 'OK' if on_silicon else 'NO-DATA'}
    if not on_silicon:
        rec['reason'] = 'target off-CCD (not on-silicon)'
    if neighbour is not None:
        c_n = SkyCoord(neighbour[0], neighbour[1], unit='deg')
        x_n, y_n = wcs.world_to_pixel(c_n)
        x_n, y_n = float(x_n), float(y_n)
        rec['neighbour_px'] = [float(x_n), float(y_n)]
        rec['separation_px'] = float(np.hypot(x_n - x_t, y_n - y_t))
    # local 5x5 flux centroid (additive): the honest identity check
    # when a bright star sits in the cutout.
    if on_silicon:
        xi, yi = int(round(x_t)), int(round(y_t))
        sub = med[max(yi - 2, 0):yi + 3, max(xi - 2, 0):xi + 3]
        yy5, xx5 = np.mgrid[max(yi - 2, 0):yi + 3, max(xi - 2, 0):xi + 3]
        w5 = np.clip(sub - np.median(med), 0, None)
        if w5.sum() > 0:
            cx5 = float((xx5 * w5).sum() / w5.sum())
            cy5 = float((yy5 * w5).sum() / w5.sum())
            rec['flux_centroid_5x5_px'] = [cx5, cy5]
            rec['centroid_5x5_target_offset_px'] = float(
                np.hypot(cx5 - x_t, cy5 - y_t))
    return rec


def main(argv=None):
    ap = argparse.ArgumentParser(
        description='Download TESSCut FFI cutouts for given sectors and '
                    'record the WCS identity (target/neighbour pixel '
                    'positions + flux-centroid cross-check).')
    ap.add_argument('tic')
    ap.add_argument('--ra', type=float, required=True)
    ap.add_argument('--dec', type=float, required=True)
    ap.add_argument('--gaia', default=None, help='target Gaia DR3 id')
    ap.add_argument('--tmag', type=float, default=None,
                    help='target Tmag')
    ap.add_argument('--sectors', type=int, nargs='+', required=True)
    ap.add_argument('--neighbour-tic', default=None)
    ap.add_argument('--neighbour-ra', type=float, default=None)
    ap.add_argument('--neighbour-dec', type=float, default=None)
    ap.add_argument('--neighbour-gaia', default=None)
    ap.add_argument('--neighbour-tmag', type=float, default=None)
    ap.add_argument('--size', type=int, default=15,
                    help='cutout side in pixels (default 15)')
    ap.add_argument('--outdir', required=True,
                    help='directory for tesscut_s<NNN>.fits')
    ap.add_argument('--identity-out', default=None,
                    help='identity JSON path (default: '
                         '<outdir>/identity.json)')
    args = ap.parse_args(argv)
    neighbour = None
    if args.neighbour_ra is not None and args.neighbour_dec is not None:
        neighbour = (args.neighbour_ra, args.neighbour_dec)

    os.makedirs(args.outdir, exist_ok=True)
    target = {'tic': int(args.tic), 'ra': args.ra, 'dec': args.dec,
              'gaia': args.gaia, 'tmag': args.tmag}
    neigh_rec = None
    if neighbour is not None:
        neigh_rec = {'tic': (int(args.neighbour_tic)
                             if args.neighbour_tic else None),
                     'ra': args.neighbour_ra, 'dec': args.neighbour_dec,
                     'gaia': args.neighbour_gaia,
                     'tmag': args.neighbour_tmag}
    rec = {'target': target, 'neighbour': neigh_rec,
           'cutout_size_px': args.size, 'sectors': {}}
    for sec in args.sectors:
        tpf, path_or_reason = fetch_sector(args.tic, sec, args.outdir,
                                           size=args.size)
        if tpf is None:
            rec['sectors'][sec] = {'status': 'NO-DATA',
                                   'error': path_or_reason}
            print(f'S{sec}: NO-DATA ({path_or_reason})', flush=True)
            continue
        srec = identity_for(tpf, path_or_reason, args.ra, args.dec,
                            neighbour)
        rec['sectors'][sec] = srec
        print(f"S{sec}: shape {srec['shape']}, cadences "
              f"{srec['n_cadences']}, cadence {srec['cadence_min']:.1f} min, "
              f"time {srec['tmin_btjd']:.1f}-{srec['tmax_btjd']:.1f} BTJD, "
              f"target px ({srec['target_px'][0]:.2f},"
              f"{srec['target_px'][1]:.2f}), "
              f"centroid-target offset "
              f"{srec['centroid_target_offset_px']:.2f} px, "
              f"status {srec['status']}", flush=True)

    out = args.identity_out or os.path.join(args.outdir, 'identity.json')
    with open(out, 'w') as fh:
        json.dump(rec, fh, indent=2, default=str)
    print(f'wrote {out}', flush=True)


if __name__ == '__main__':
    main()
