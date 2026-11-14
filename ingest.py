"""One float64 ingest, shared by every path that reads light curves.

Phase 1.2, item C-4, found the failure: FITS flux is typically
float32 while the offline fixtures store float64, and scipy's
savgol accumulates in the input dtype — so the live and fixture
paths detrended to trends differing by ~4e-7, which flipped the
BLS argmax one grid step on a near-tie. The C-4 fix normalised
to float64 inside hunter._run_pipeline only; the gauntlet fetch
paths (_fetch_stitched, _fetch_flattened, _fetch_raw) and the
bulk screen's FITS read each did their own conversion (or none).
Phase 1.2 follow-up F-4 unifies them: every path normalises
time/flux/flux_err to float64 through this module, at the
FITS-read boundary.

Upcasting is exact (every float32 value is representable in
float64), so normalisation changes no value — it only makes the
numerics independent of whichever dtype MAST served.

Call sites:
  * hunter._fetch_stitched — the downloaded collection is
    normalised before stitching (the gauntlet fetchers'
    boundary), and the stitched curve is normalised again at
    return (idempotent, defensive).
  * hunter._run_pipeline — the C-4 block, replaced by one call
    to normalise_lightcurve at the same position. The position
    is deliberate: the C-4 live/fixture hash test pins the
    post-stitch normalisation, so _run_pipeline keeps it there
    rather than moving it to the download.
  * bulk_screen._screen_one — the FITS TIME/flux columns go
    through as_float64 at the read.

assert_float64 is the tripwire at detrend/BLS entry: if a
future refactor bypasses ingest, the pipeline fails loudly
with the step named, instead of silently searching
dtype-dependent arrays.
"""
import numpy as np


def as_float64(t, f, flux_err=None):
    """(time, flux, flux_err) as float64 arrays.

    `flux_err` may be None (no error column) — it comes back
    None. Anything array-like goes in; float64 ndarrays come
    out. The upcast is exact.
    """
    t64 = np.asarray(t, dtype=np.float64)
    f64 = np.asarray(f, dtype=np.float64)
    if flux_err is None:
        return t64, f64, None
    return t64, f64, np.asarray(flux_err, dtype=np.float64)


def normalise_lightcurve(lc):
    """A lightkurve LightCurve with float64 time/flux/flux_err.

    Rebuilds a plain LightCurve — the pipeline uses the curve
    for time/flux/len/flatten only (C-4), so no metadata the
    pipeline needs is dropped. flux_err is preserved when the
    input carries it (normalised to float64); a curve without
    flux_err comes back without one.
    """
    import lightkurve as lk
    t, f, ferr = as_float64(lc.time.value, lc.flux.value,
                            getattr(lc, "flux_err", None))
    kwargs = {"time": t, "flux": f}
    if ferr is not None:
        kwargs["flux_err"] = ferr
    return lk.LightCurve(**kwargs)


def assert_float64(t, f, where):
    """Fail loudly unless t and f are float64 arrays.

    Call at detrend/BLS entry: a float32 array reaching this
    point means a path bypassed ingest, and the search would
    silently depend on the storage dtype. Raises TypeError
    naming the step.
    """
    t = np.asarray(t)
    f = np.asarray(f)
    bad = []
    if t.dtype != np.float64:
        bad.append(f"time ({t.dtype})")
    if f.dtype != np.float64:
        bad.append(f"flux ({f.dtype})")
    if bad:
        raise TypeError(
            f"{where}: expected float64 arrays, got "
            f"{', '.join(bad)} — the data bypassed ingest "
            f"(ingest.as_float64 / normalise_lightcurve)")
