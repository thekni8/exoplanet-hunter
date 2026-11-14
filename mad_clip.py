"""One MAD-sigma clip, shared by the bulk screen and the gauntlet.

Phase 1.2, item B-2: the clip logic lived in three places — the
bulk screen's symmetric 5-sigma clip (bulk_screen._screen_one),
and the gauntlet's floored asymmetric clip duplicated in
gauntlet/rawflux_check.py and gauntlet/transit_fit.py. The
screen's version had no depth floor, so it ate deep transits on
quiet stars: a 1.5% transit on a 0.3%-noise star scored LOWER
than a 1.0% one. There is now one function; the clip OPTION
comes from the calibration profile (v1: symmetric; v2: chosen
by the pre-registered grid — see bulk/CLIP_GRID_CRITERIA.md).

Options
-------
symmetric          keep |f - med| < 5 sigma, both sides (v1)
upward_only        clip only positive outliers; every dip survives
isolated_low_only  clip a low point only when neither neighbour
                   is also low (transits come in runs; isolated
                   dips are glitches)
floor_10pct        lower cut floored at 10% below the median
                   (the gauntlet's clip since 2026-11-14)
none               keep everything — grid reference only, never a
                   profile option (bulk_screen.set_calibration
                   rejects it in a profile)

sigma is the MAD-sigma of the flux (1.4826 * median |f - med|).
When sigma is 0 (constant flux) nothing is clipped.
"""
import numpy as np

# Options a calibration profile may declare.
PROFILE_OPTIONS = ("symmetric", "upward_only", "isolated_low_only",
                   "floor_10pct")
# Measurement-only options (the grid's unclipped reference).
GRID_ONLY_OPTIONS = ("none",)
ALL_OPTIONS = PROFILE_OPTIONS + GRID_ONLY_OPTIONS

DEFAULT_SIGMA = 5.0
DEFAULT_FLOOR_FRAC = 0.10


def mad_sigma(f):
    """(median, MAD-sigma) of a flux array."""
    f = np.asarray(f, dtype=float)
    med = float(np.median(f))
    sig = float(1.4826 * np.median(np.abs(f - med)))
    return med, sig


def mad_clip_mask(f, option, sigma=DEFAULT_SIGMA,
                  floor_frac=DEFAULT_FLOOR_FRAC):
    """Boolean keep-mask for flux array f under the clip option.

    Raises ValueError on an unknown option. The mask is the same
    shape as f; True keeps the point.
    """
    f = np.asarray(f, dtype=float)
    if option not in ALL_OPTIONS:
        raise ValueError(
            f"unknown clip option {option!r} — expected one of "
            f"{', '.join(ALL_OPTIONS)}")
    if option == "none":
        return np.ones(f.shape, dtype=bool)
    med, sig = mad_sigma(f)
    if sig <= 0:
        return np.ones(f.shape, dtype=bool)
    hi = f < med + sigma * sig
    if option == "symmetric":
        return hi & (f > med - sigma * sig)
    if option == "upward_only":
        return hi
    if option == "floor_10pct":
        return hi & (f > med - max(sigma * sig, floor_frac))
    # isolated_low_only: a low point survives when a neighbour is
    # also low (a transit is a run of low points; a lone low
    # point is a glitch). Edge points have one neighbour.
    low = f < med - sigma * sig
    neigh_low = np.zeros(low.shape, dtype=bool)
    neigh_low[1:] |= low[:-1]
    neigh_low[:-1] |= low[1:]
    return hi & (~low | neigh_low)
