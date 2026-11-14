"""Synthetic QLP-style FITS builders for offline tests.

The golden suite's download tests prove the pipeline on real stars;
these builders prove the SCREEN's logic (vetoes, tiers, gates,
resume, corrupt-data handling) without any network. Each builder
writes a minimal QLP-like FITS with TIME / KSPSAP_FLUX / QUALITY
columns — exactly the columns bulk_screen._screen_one reads — plus
a transit signal with known properties, from a fixed seed.

Noise/depth ratios are chosen to survive the screen's own 5-sigma
MAD clip (a transit deeper than 5x the per-point noise is clipped
as an outlier before BLS ever sees it — real QLP noise at Tmag
12-13 is ~0.3-1%, so 1% transits survive there; a synthetic with
0.1% noise and a 1% transit would be clipped and the test would
assert on an empty curve). Depths here stay under ~4 sigma.
"""
import numpy as np
from astropy.io import fits

DEFAULT_META = {"ra": 100.0, "dec": -65.0, "tmag": 12.0, "radius": 0.7}


def make_qlp_fits(path, *, n_points=1296, cadence_min=30.0,
                  t_start=1500.0, period_d=None, depth_frac=0.01,
                  duration_d=0.1, t0=None, noise_pct=0.003, seed=42,
                  quality=None, odd_even_ratio=1.0,
                  secondary_depth_frac=0.0, flagged_only_frac=None,
                  flag_bit=30):
    """Write a synthetic QLP FITS to `path` and return the Path.

    period_d=None means pure noise (no transit). odd_even_ratio
    scales alternate transits (an EB at twice the period has
    odd/even depths that differ). secondary_depth_frac adds a
    secondary eclipse at phase 0.5. `quality` is either an int
    array of QUALITY flags or a callable (t, in_transit_mask) ->
    flags array — used to put a signal on flagged cadences only.
    flagged_only_frac (e.g. 0.7) builds the TIC 344334378 class:
    the dip exists ONLY on that fraction of in-transit cadences,
    and exactly those cadences carry quality bit `flag_bit`
    (default 30 — the S96 gauntlet artifacts live in bits 29/30;
    pass flag_bit=29 for the bit-29 variant) — the screen
    (bitmask 17087) keeps them and sees the signal, but the
    clean-data gate (v3 mask excludes bits 29/30) sees no dip
    at all.
    """
    rng = np.random.default_rng(seed)
    t = t_start + np.arange(n_points) * cadence_min / 1440.0
    f = 1.0 + rng.normal(0.0, noise_pct, n_points)
    in_transit = np.zeros(n_points, dtype=bool)
    flagged = np.zeros(n_points, dtype=bool)
    if period_d is not None:
        t0 = t_start + 2.0 if t0 is None else t0
        # Transits are CENTRED at t0 + k*P (the pipeline's T0
        # convention: BLS transit_time is a transit centre, and
        # the gauntlet folds symmetric windows around it).
        phase = ((t - t0 + 0.5 * period_d) % period_d) - 0.5 * period_d
        event = np.round((t - t0) / period_d).astype(int)
        in_transit = np.abs(phase) < duration_d / 2.0
        depth = np.where(event % 2 == 0, depth_frac,
                         depth_frac * odd_even_ratio)
        if flagged_only_frac is not None:
            # The dip lives only on flagged cadences: choose the
            # flagged subset of in-transit cadences first, dip only
            # those, and flag exactly those with bit 30.
            idx = np.where(in_transit)[0]
            n_flag = int(round(flagged_only_frac * len(idx)))
            chosen = rng.choice(idx, size=n_flag, replace=False)
            flagged[chosen] = True
            dip_at = np.zeros(n_points, dtype=bool)
            dip_at[chosen] = True
            f = np.where(dip_at, f - depth, f)
        else:
            f = np.where(in_transit, f - depth, f)
        if secondary_depth_frac:
            sec = (np.abs(phase - 0.5 * period_d) < duration_d / 2.0) | \
                  (np.abs(phase + 0.5 * period_d) < duration_d / 2.0)
            f = np.where(sec, f - secondary_depth_frac, f)
            in_transit = in_transit | sec
    if quality is None:
        q = np.zeros(n_points, dtype=np.int32)
    elif callable(quality):
        q = np.asarray(quality(t, in_transit), dtype=np.int32)
    else:
        q = np.asarray(quality, dtype=np.int32)
    if flagged.any():
        q = q | np.where(flagged, np.int32(1 << flag_bit),
                         np.int32(0)).astype(np.int32)
    cols = [
        fits.Column(name="TIME", format="D", array=t),
        fits.Column(name="KSPSAP_FLUX", format="D", array=f),
        fits.Column(name="QUALITY", format="J", array=q),
    ]
    hdul = fits.HDUList([fits.PrimaryHDU(),
                         fits.BinTableHDU.from_columns(cols)])
    hdul.writeto(path, overwrite=True)
    return path


def screen_job(path, tic="999999999", sector=1, meta=None):
    """The _screen_one job tuple for a synthetic FITS."""
    return (str(tic), str(path), sector, dict(meta or DEFAULT_META))
