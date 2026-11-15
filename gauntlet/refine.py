"""Period refinement (Phase 2, 2A).

Promoted verbatim from holdout_test._refine_ephemeris (2026-11-15):
the narrow-grid BLS refit around a filed period. The vetting
manual (§2) requires the period to be refined BEFORE any fixed-
ephemeris fold — bulk-screen periods carry +0.0004 to -0.0036 d
errors, enough to smear a fold over a multi-sector baseline.

The desk driver (gauntlet/desk.py) calls refine_ephemeris on the
stitched flattened flux to produce the `refine` stage native;
holdout_test keeps _refine_ephemeris as an alias so its existing
callers (holdout_test, holdout_extended, holdout_supp) are
unchanged. Semantics are byte-identical to the 2026-11-13
original: same grid, same tolerance, same failure modes.
"""
import numpy as np

REFINE_PERIOD_TOL_FRAC = 0.01
REFINE_GRID_HALF_FRAC = 0.015


def refine_ephemeris(t, f, period_in, duration_d):
    """BLS refit on TRAINING flux only, narrow grid around the filed
    period. Returns (period, t0) or None if the refit fails or lands
    outside +/- REFINE_PERIOD_TOL_FRAC of the filed period."""
    import astropy.units as u
    from astropy.timeseries import BoxLeastSquares

    t = np.asarray(t, dtype=float)
    f = np.asarray(f, dtype=float)
    ok = np.isfinite(t) & np.isfinite(f)
    t, f = t[ok], f[ok]
    if len(t) < 500 or period_in <= 0 or duration_d <= 0:
        return None
    baseline = float(t.max() - t.min())
    if baseline <= 0:
        return None
    f_lo = 1.0 / (period_in * (1.0 + REFINE_GRID_HALF_FRAC))
    f_hi = 1.0 / (period_in * (1.0 - REFINE_GRID_HALF_FRAC))
    n_freq = int(min(20000, max(2000, 5.0 * baseline * (f_hi - f_lo) + 500)))
    periods = (1.0 / np.linspace(f_lo, f_hi, n_freq)) * u.day
    durations = np.unique(np.clip(
        np.array([0.6, 1.0, 1.5]) * duration_d, 0.02, 0.35)) * u.day
    try:
        bls = BoxLeastSquares(t * u.day, f)
        res = bls.power(periods, durations)
        i = int(np.argmax(res.power))
        p_ref = float(res.period[i].value)
        t0_ref = float(res.transit_time[i].value)
    except Exception:
        return None
    if not np.isfinite(p_ref) or abs(p_ref - period_in) > (
            REFINE_PERIOD_TOL_FRAC * period_in):
        return None
    return p_ref, t0_ref


def refine_native(t, f, period_in, t0_in, duration_d, n_eras=1):
    """Run the refit and build the `refine` stage native.

    Native shape (runner.py): {"period_d", "t0", "duration_d",
    "converged", "rms_resid_d", "n_eras"}. On a failed refit the
    native is unconverged and carries the filed ephemeris, so the
    runner keeps the bulk ephemeris and the stage reads
    UNMEASURED (never a silent substitution).
    """
    ref = refine_ephemeris(t, f, period_in, duration_d)
    if ref is None:
        return {"period_d": float(period_in), "t0": float(t0_in),
                "duration_d": float(duration_d), "converged": False,
                "rms_resid_d": None, "n_eras": int(n_eras)}
    p_ref, t0_ref = ref
    return {"period_d": float(p_ref), "t0": float(t0_ref),
            "duration_d": float(duration_d), "converged": True,
            "rms_resid_d": None, "n_eras": int(n_eras)}
