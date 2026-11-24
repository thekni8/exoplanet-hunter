"""5.7 two-pass transit-masked detrending (DESIGN_5_7.md Rev 1).

Pure functions for the 5.7 detrend. The orchestration (BLS ->
refine-for-mask -> masked re-flatten -> second BLS -> adoption
gate) lives in bulk_screen._screen_one, where the BLS lives;
this module holds the pieces that are testable without a screen:

  savgol_trend        segment-wise SavGol trend at a window in days
  masked_savgol_trend SavGol trend with transit cadences masked out
  transit_mask        the D-mask (|dt_fold| <= D/2 + pad, in days)
  raw_fold_depth      hunter.py's raw-flux gate measurement, verbatim
  measure_cdpp        the ONE frozen CDPP pipeline (protocol §3)

Standalone: imports only numpy/scipy (no bulk_screen, no hunter),
so bulk_screen can import it at top level without a cycle.

Flag values: "v6" is the current behaviour (2.0 d unmasked SavGol,
single pass); "v7" is the 5.7 detrend (1.0 d window, transit-masked
second pass). The flag defaults to "v6" everywhere; flag-off output
is byte-identical (D10 regression test: tests/test_detrend_57.py).
"""

import math

import numpy as np

DETREND_V6 = "v6"
DETREND_V7 = "v7"

WINDOW_V6_D = 2.0   # the current flatten window (hardcoded in v6)
WINDOW_V7_D = 1.0   # D2, ratified (OQ-1 (a), both legs)

GAP_D = 0.05        # jump between valid cadences that breaks a
                    # segment (the production segment rule;
                    # oracle_run.GAP_D / EVENT_GAP_D default)

MASK_PAD_D = 0.02   # D3 mask pad: ingress/egress smearing
MASK_MAX_FRAC = 0.50  # D4 guard: skip the second pass above this

# D6 adoption: the SDE condition mirrors J1 (DESIGN_5_6 §2.2 step 3)
# and the raw-flux gate uses hunter.py's EXISTING threshold — do not
# invent a new one. tests/test_detrend_57.py pins this constant
# equal to hunter._PASS2_GATE_MIN_SIGNIF.
ADOPT_SDE_DROP = 1.0
PASS2_GATE_MIN_SIGNIF = 3.0

# Record keys the v7 screen attaches (bulk_screen._screen_one).
# oracle_run._subset copies the ones PRESENT into campaign subsets
# (flag-off records never carry them, so flag-off subsets are
# byte-identical). None of these is in bulk_screen._EMIT_KEYS:
# they are campaign diagnostics, not gauntlet inputs.
DETREND_RECORD_KEYS = (
    "detrend",
    "detrend_pass1_period_days", "detrend_pass1_sde",
    "detrend_pass1_depth_percent", "detrend_pass1_duration_hours",
    "detrend_pass1_t0_btjd",
    "detrend_pass2_period_days", "detrend_pass2_sde",
    "detrend_pass2_depth_percent", "detrend_pass2_duration_hours",
    "detrend_pass2_t0_btjd",
    "detrend_adopted", "detrend_gate_passed",
    "detrend_gate_raw_depth_pct", "detrend_gate_raw_signif",
    "detrend_sde_jump", "detrend_mask_fraction",
    "detrend_refined_period_days", "detrend_refined_t0_btjd",
    "detrend_refined_duration_hours",
    "detrend_pass2_skip_reason", "detrend_pass2_failed",
    "detrend_seconds",
)


def window_points(dt, window_d, n):
    """SavGol window in points for a window in days: round(window/dt),
    forced odd, clamped to [31, n//2*2-1]. Returns None when no valid
    window exists (n too small). The v6 inline arithmetic, factored
    out verbatim (bulk_screen._screen_one / oracle_run.preprocess_
    arrays use the same expressions with window_d = 2.0)."""
    win = int(round(window_d / dt)) if dt > 0 else 97
    win += (win % 2 == 0)
    win = int(min(max(win, 31), n // 2 * 2 - 1))
    return win if win >= 31 else None


def segments_from_times(t, gap_d=GAP_D):
    """Contiguous valid segments: list of (start_idx, end_idx)
    (end exclusive) split wherever consecutive times jump more
    than gap_d. The bulk_screen.segments_from_times rule,
    standalone (this module must not import bulk_screen)."""
    t = np.asarray(t, dtype=float)
    if len(t) == 0:
        return []
    breaks = np.where(np.diff(t) > gap_d)[0]
    bounds = [0] + [int(b) + 1 for b in breaks] + [len(t)]
    return [(bounds[i], bounds[i + 1])
            for i in range(len(bounds) - 1)]


def savgol_trend(t, f, window_d, gap_d=GAP_D):
    """Segment-wise Savitzky-Golay trend (poly order 2) at a window
    in days. The filter runs per contiguous segment (split at gaps
    > gap_d) so index-space SavGol never bridges a multi-day
    downlink or inter-sector gap (D5). Each segment gets its own
    window from its own median cadence and length; a segment too
    short for a valid window keeps trend 1.0 (no flatten there).
    Zero-valued trend points are replaced by 1.0 (the v6 guard).
    Returns the trend array (same length as f); the caller divides.
    """
    from scipy.signal import savgol_filter
    t = np.asarray(t, dtype=float)
    f = np.asarray(f, dtype=float)
    trend = np.ones_like(f)
    for a, b in segments_from_times(t, gap_d=gap_d):
        seg_t = t[a:b]
        if len(seg_t) < 2:
            continue
        dt = float(np.median(np.diff(seg_t)))
        win = window_points(dt, window_d, len(seg_t))
        if win is None:
            continue
        tr = savgol_filter(f[a:b], win, 2)
        tr[tr == 0] = 1.0
        trend[a:b] = tr
    return trend


def masked_savgol_trend(t, f, mask, window_d, gap_d=GAP_D):
    """SavGol trend with transit cadences masked out of the fit (D5).

    Masked cadences are filled by LINEAR INTERPOLATION IN TIME
    (np.interp on t) between the nearest unmasked cadences;
    edge-masked cadences take the nearest unmasked value
    (np.interp's default end behaviour). savgol_filter then runs
    on the FILLED series, segment-wise; the returned trend divides
    the ORIGINAL (unfilled) flux, so the trend at masked cadences
    is interpolated from unmasked neighbours and cannot sag into
    the transit. t must be sorted ascending (the screen path
    guarantees it). Raises ValueError when every cadence is
    masked (nothing to anchor the trend); with no masked cadences
    this is exactly savgol_trend.
    """
    t = np.asarray(t, dtype=float)
    f = np.asarray(f, dtype=float)
    mask = np.asarray(mask, dtype=bool)
    if bool(mask.all()):
        raise ValueError("all cadences masked: no trend support")
    if not bool(mask.any()):
        return savgol_trend(t, f, window_d, gap_d=gap_d)
    filled = np.interp(t, t[~mask], f[~mask])
    return savgol_trend(t, filled, window_d, gap_d=gap_d)


def folded_time_offset(t, period, t0):
    """Folded time offset in DAYS: ((t - T0 + P/2) mod P) - P/2.
    No dimensionless phase appears anywhere in the mask spec (D3).
    """
    return ((np.asarray(t, dtype=float) - t0 + 0.5 * period)
            % period) - 0.5 * period


def transit_mask(t, period, t0, duration, pad_d=MASK_PAD_D):
    """The D-mask (D3): cadences with |dt_fold| <= D/2 + pad_d,
    where D is the transit duration in days. The ephemeris is the
    REFINED pass-1 headline (the refinement is the caller's job).
    """
    return (np.abs(folded_time_offset(t, period, t0))
            <= duration / 2.0 + pad_d)


def raw_fold_depth(t, f, period, t0, duration):
    """Depth of a candidate ephemeris in UNFLATTENED flux.

    VERBATIM from hunter.py::_raw_fold_depth (the pass-2 raw-flux
    gate, 2026-11-10, TIC 294873918 post-mortem) — copied, not
    imported, so the bulk path stays self-contained (hunter.py is
    heavy and the bulk screen must not import it). Any change here
    must be mirrored in hunter.py; tests/test_detrend_57.py asserts
    the two functions agree on synthetic data and the thresholds
    are equal.

    Returns (depth_pct, signif). In-transit = |phase| <= duration/2;
    baseline = |phase| > duration (a one-duration guard band keeps
    ingress/egress wings out of the baseline). Depth is the median
    difference, in percent (the stitched flux is ~1-normalised).
    Signif uses a chunked red-noise sigma: out-of-transit points are
    chunked at the transit-duration timescale and
    sigma = chunk_sigma * sqrt(1/n_events + 1/n_chunks).
    Unmeasurable configurations return (0.0, 0.0) — the gate then
    fails closed and pass 1 stands.
    """
    t = np.asarray(t, dtype=float)
    f = np.asarray(f, dtype=float)
    ok = np.isfinite(t) & np.isfinite(f)
    t, f = t[ok], f[ok]
    if len(t) < 200 or period <= 0 or duration <= 0:
        return 0.0, 0.0
    phase = ((t - t0 + 0.5 * period) % period) - 0.5 * period
    in_m = np.abs(phase) <= duration / 2.0
    out_m = np.abs(phase) > duration
    if in_m.sum() < 20 or out_m.sum() < 50:
        return 0.0, 0.0
    depth_pct = (float(np.median(f[out_m]))
                 - float(np.median(f[in_m]))) * 100.0
    t_out, f_out = t[out_m], f[out_m]
    cid = np.floor((t_out - t_out.min()) / duration).astype(np.int64)
    cnt = np.bincount(cid)
    sums = np.bincount(cid, weights=f_out)
    good = cnt >= 3
    if good.sum() < 2:
        return depth_pct, 0.0
    chunk_means = sums[good] / cnt[good]
    chunk_sigma_pct = float(np.std(chunk_means, ddof=1)) * 100.0
    n_events = max(1, len(np.unique(np.round((t[in_m] - t0) / period))))
    sigma_pct = chunk_sigma_pct * math.sqrt(1.0 / n_events
                                            + 1.0 / float(good.sum()))
    signif = depth_pct / sigma_pct if sigma_pct > 0 else 0.0
    return depth_pct, float(signif)


def measure_cdpp(t, f, duration_d, gap_d=GAP_D):
    """The ONE frozen CDPP pipeline (protocol §3, [R12]).

    For host h under detrend leg L, on the SINGLE-PASS stitched
    curve (the per-sector-detrended, stitched curve entering
    pass-1 BLS — NOT the post-D-mask curve). The caller supplies
    the already-detrended, already-stitched (t, f); this function
    only chunks and measures. It is NOT _rescore's CDPP (which
    needs an ephemeris to define in/out-of-transit) — on an
    uninjected host there is no transit to exclude, so the whole
    curve is the noise sample.

    Procedure (frozen):
    - Chunks are split at gaps > gap_d (0.05 d); segments never
      span a gap, and each chunk is chunked independently from
      its own start.
    - Segments are consecutive non-overlapping duration_d windows
      from each chunk's first cadence.
    - A trailing partial window with <50% of the expected
      cadences (duration_d / median cadence) is DISCARDED; one
      with >=50% fill is kept, its mean over available cadences.
    - Mid-chunk windows keep their mean over available cadences
      only (no filling), whatever their fill.
    - CDPP = std of the segment means (ddof=0), requiring >=5
      segments; 1.4826 * MAD of the segment means is logged
      alongside (diagnostic, not a bar).

    Paired identity: the segment boundaries are computed from the
    host's time array and gap structure alone (identical for both
    legs — the time array does not change between legs), and are
    returned so the scorer can assert them identical between legs.

    Returns a dict: cdpp_ppm (None when <5 segments), mad_ppm,
    n_segments, segment_bounds (list of (start_idx, end_idx) into
    the FINITE-filtered arrays), segment_counts, dt_d (median
    cadence in days). Units are ppm throughout (x 1e6), matching
    the 4.1-10 manifest's stitched_cdpp_ppm_2p39h.
    """
    t = np.asarray(t, dtype=float)
    f = np.asarray(f, dtype=float)
    ok = np.isfinite(t) & np.isfinite(f)
    t, f = t[ok], f[ok]
    out = {"cdpp_ppm": None, "mad_ppm": None, "n_segments": 0,
           "segment_bounds": [], "segment_counts": [], "dt_d": None}
    if len(t) < 2 or duration_d <= 0:
        return out
    dt = float(np.median(np.diff(t)))
    out["dt_d"] = dt
    if dt <= 0:
        return out
    expected = duration_d / dt  # cadences per full segment
    means, bounds, counts = [], [], []
    for a, b in segments_from_times(t, gap_d=gap_d):
        seg_t, seg_f = t[a:b], f[a:b]
        start0 = float(seg_t[0])
        k_max = int((float(seg_t[-1]) - start0) // duration_d)
        for k in range(k_max + 1):
            lo = start0 + k * duration_d
            hi = lo + duration_d
            m = (seg_t >= lo) & (seg_t < hi)
            n_in = int(m.sum())
            if n_in == 0:
                continue
            if k == k_max and n_in < 0.5 * expected:
                # Trailing partial window below 50% fill: discard.
                continue
            idx = np.where(m)[0]
            means.append(float(np.mean(seg_f[m])))
            bounds.append((a + int(idx[0]), a + int(idx[-1]) + 1))
            counts.append(n_in)
    out["n_segments"] = len(means)
    out["segment_bounds"] = bounds
    out["segment_counts"] = counts
    if len(means) >= 5:
        arr = np.asarray(means, dtype=float)
        out["cdpp_ppm"] = float(np.std(arr)) * 1e6
        med = float(np.median(arr))
        out["mad_ppm"] = float(
            1.4826 * np.median(np.abs(arr - med))) * 1e6
    return out
