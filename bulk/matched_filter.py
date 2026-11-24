"""5.8 whitened matched filter (DESIGN_5_8_AS_VOTED.md Rev 1).

Pure functions for the 5.8 search. The orchestration (whiten ->
BLS -> rescore on the UNWHITENED curve) lives in
bulk_screen._screen_one, where the BLS lives; this module holds
the pieces that are testable without a screen:

  estimate_psd          Welch PSD + log-frequency median smoothing
                        + Nyquist-safe white floor, per segment
  whiten_curve          the frozen whitening pipeline (M5-M10):
                        segment split, uniform gridding, PSD
                        interpolation onto the FFT grid, filter,
                        inverse-FFT, crop, extract at observed t
  matched_filter_search whiten + astropy BLS on the whitened curve
  gate_depth_pct        the depth a gate reads: the unwhitened
                        depth when the record carries it (an MF
                        record), else the record's depth_percent

Standalone: imports only numpy/scipy (no bulk_screen, no hunter),
so bulk_screen can import it at top level without a cycle.

Flag values: "bls" is the current behaviour (white-noise BLS);
"mf" is the 5.8 search (whitened BLS replacing BLS at every
screen). The flag defaults to "bls" everywhere; flag-off output
is byte-identical (D10-pattern regression test:
tests/test_matched_filter_58.py).

Frozen parameters (M5-M10, as ratified — COMPARISON_5_8.md
§7 item 2): the parameters are in PHYSICAL TIME, converted via
the median segment dt — never hardcoded cadence counts (the
draft's cadence-hardcoded M5-M10 assumed 2-min cadence while
S95-S98 QLP curves are 200-s FFI cadence, shifting every
parameter by 1.67x).

  T_WELCH_D = 2.0 d (Welch window; df = 0.5/day, ~25 overlapping
    Hann windows per 27 d sector)
  T_MIN_SEG_D = 4.0 d (segments shorter than this are left
    unwhitened; 4.0 d ensures >= 3 overlapping Welch windows per
    whitened segment)
  LOG_SMOOTH_DEX = 0.175 (log-frequency running-median width;
    the frozen range is 0.15-0.20 dex — the midpoint is the
    frozen value, recorded here; minimum 3 bins)
  WHITE_FLOOR_MIN_D = 100.0 (the white floor band is
    f in [min(100/d, 0.5 f_Nyq), 0.9 f_Nyq])
  PAD_FRAC = 0.10 (median-extension padding per side before
    the FFT, cropped after — the guard against circular
    wrap-around)

The whitened curve keeps the segment's level: the median is
subtracted before the FFT and added back after the inverse FFT,
so the whitened flux sits at ~1.0 like the input (BLS is
offset-invariant, but every downstream consumer assumes flux
~1). W(0) is therefore moot (the DC bin of a median-subtracted
segment is ~0) and is set to W(f1), the clamped value the
design allows.
"""

import math

import numpy as np
from scipy.signal import welch

SEARCH_BLS = "bls"
SEARCH_MF = "mf"

T_WELCH_D = 2.0
T_MIN_SEG_D = 4.0
LOG_SMOOTH_DEX = 0.175
LOG_SMOOTH_MIN_BINS = 3
WHITE_FLOOR_MIN_D = 100.0
PAD_FRAC = 0.10

GAP_D = 0.05        # jump between valid cadences that breaks a
                    # segment (the production segment rule;
                    # bulk_screen.segments_from_times default)

# Record keys the MF screen attaches (bulk_screen._screen_one).
# oracle_run._subset copies the ones PRESENT into campaign subsets
# (flag-off records never carry them, so flag-off subsets are
# byte-identical). None of these is in bulk_screen._EMIT_KEYS:
# they are campaign diagnostics, not gauntlet inputs.
MF_RECORD_KEYS = (
    "search",
    "mf_seconds",
    "mf_unwhitened_cadence_frac",
    "mf_psd_floor_ratio",
    "mf_unwhitened_depth_percent",
    "mf_whiten_failed",
)

# The key carrying the judged (unwhitened) depth on an MF record.
# Depth gates read this via gate_depth_pct when present.
MF_DEPTH_KEY = "mf_unwhitened_depth_percent"


def gate_depth_pct(record):
    """The depth (percent) a gate reads for a screen record.

    An MF record carries the unwhitened fold depth under
    MF_DEPTH_KEY; every depth gate (the _screen_one vetoes, the
    tier-B cap, the K=2 mask gate / eligibility / buffer /
    co-mask triggers, pass-3 eligibility, derive_tier) reads
    THAT, never the whitened BLS depth_percent (R6: the
    depth-gate isolation rule). A record without the key (any
    flag-off record, any frozen recorded row) reads
    depth_percent, exactly as before.
    """
    if record is None:
        return None
    depth = record.get(MF_DEPTH_KEY)
    if depth is not None:
        return depth
    return record.get("depth_percent")


def _segments_from_times(t, gap_d=GAP_D):
    """Contiguous segments: list of (start_idx, end_idx) (end
    exclusive) split wherever consecutive times jump more than
    gap_d. The same predicate as bulk_screen.segments_from_times
    (reimplemented here so this module stays standalone; the
    agreement is asserted by tests/test_matched_filter_58.py)."""
    if len(t) == 0:
        return []
    breaks = np.where(np.diff(t) > gap_d)[0]
    bounds = [0] + [int(b) + 1 for b in breaks] + [len(t)]
    return [(bounds[i], bounds[i + 1]) for i in range(len(bounds) - 1)]


def _log_median_smooth(freqs, psd, dex=LOG_SMOOTH_DEX,
                       min_bins=LOG_SMOOTH_MIN_BINS):
    """Log-frequency running median of a PSD.

    freqs/psd are the POSITIVE frequencies f >= f1 (DC bin 0 is
    never included). For each bin, the median of the PSD over
    bins within +-dex/2 in log10(f). The window holds at least
    min_bins bins (widened symmetrically where the log window is
    narrower); at the edges the PSD is REFLECTED (never
    zero-padded), so edge bins get a full window without DC
    leakage. Returns the smoothed PSD on the same grid.
    """
    freqs = np.asarray(freqs, dtype=float)
    psd = np.asarray(psd, dtype=float)
    n = len(freqs)
    if n == 0:
        return psd
    if n == 1:
        return psd.copy()
    logf = np.log10(freqs)
    half = dex / 2.0
    # Window half-width in bins, per bin (log width -> more bins
    # at high frequency). The reflection pad covers the widest.
    lo = np.searchsorted(logf, logf - half, side="left")
    hi = np.searchsorted(logf, logf + half, side="right") - 1
    # Widen windows narrower than min_bins, symmetrically, in
    # index space. The bounds are NOT clamped to the grid: the
    # reflection pad below supplies out-of-grid bins, so edge
    # bins get a full window without DC leakage or zero-padding.
    width = hi - lo + 1
    need = np.maximum(0, min_bins - width)
    lo = lo - (need + 1) // 2
    hi = hi + need // 2
    pad = int(max(1, -int(lo.min()), int(hi.max()) - (n - 1)))
    padded = np.pad(psd, pad, mode="reflect")
    out = np.empty(n, dtype=float)
    for i in range(n):
        # Window [lo[i], hi[i]] in the original grid, shifted by
        # the pad; reflection supplies out-of-grid bins.
        out[i] = float(np.median(padded[lo[i] + pad:hi[i] + pad + 1]))
    return out


def estimate_psd(t_seg, f_seg):
    """Welch PSD + log-frequency median smoothing + white floor
    for one contiguous segment (uniform-ish cadence).

    t_seg/f_seg are the segment's times/fluxes (the caller maps
    them onto a uniform grid first — see whiten_curve). Returns
    (freqs, psd_smooth, p_white, info): freqs/psd_smooth on the
    Welch grid (INCLUDING the DC bin 0 in freqs; psd_smooth[0]
    is the raw DC value, never smoothed — the smoother never
    includes DC), p_white the Nyquist-safe white floor, and info
    a JSON-safe dict (nperseg, n_windows, delta_f_per_day,
    f_nyq_per_day, n_bins).

    Raises ValueError on a non-finite PSD or an empty white-floor
    band (the M15 fallback catches it at the screen level).
    """
    t_seg = np.asarray(t_seg, dtype=float)
    f_seg = np.asarray(f_seg, dtype=float)
    if len(t_seg) < 8:
        raise ValueError("segment too short for a PSD estimate")
    dt = float(np.median(np.diff(t_seg)))
    if not (dt > 0) or not np.isfinite(dt):
        raise ValueError("non-positive median dt")
    fs = 1.0 / dt  # samples per day
    nperseg = int(round(T_WELCH_D / dt))
    nperseg = max(8, nperseg)
    if nperseg > len(f_seg):
        raise ValueError("segment shorter than one Welch window")
    freqs, psd = welch(f_seg, fs=fs, window="hann",
                       nperseg=nperseg, noverlap=nperseg // 2,
                       detrend="constant")
    if not np.all(np.isfinite(psd)):
        raise ValueError("non-finite Welch PSD")
    if len(freqs) < 3:
        raise ValueError("too few Welch bins")
    # Smooth the positive frequencies only (f >= f1); DC bin 0
    # keeps its raw value and is never part of the smoother.
    psd_smooth = psd.copy()
    psd_smooth[1:] = _log_median_smooth(freqs[1:], psd[1:])
    if not np.all(np.isfinite(psd_smooth)):
        raise ValueError("non-finite smoothed PSD")
    f_nyq = 0.5 * fs
    lo = min(WHITE_FLOOR_MIN_D, 0.5 * f_nyq)
    hi = 0.9 * f_nyq
    band = (freqs >= lo) & (freqs <= hi)
    if not np.any(band):
        raise ValueError("empty white-floor band")
    p_white = float(np.median(psd_smooth[band]))
    if not (p_white > 0) or not np.isfinite(p_white):
        raise ValueError("non-positive white floor")
    n_windows = int((len(f_seg) - nperseg) // (nperseg // 2) + 1)
    info = {"nperseg": int(nperseg), "n_windows": n_windows,
            "delta_f_per_day": float(freqs[1] - freqs[0]),
            "f_nyq_per_day": float(f_nyq),
            "n_bins": int(len(freqs))}
    return freqs, psd_smooth, p_white, info


def _uniform_grid(t_seg, f_seg, dt):
    """Map a segment onto a uniform grid at step dt.

    Returns (t_grid, f_grid, obs_index): t_grid spans the
    segment at step dt; f_grid takes the observed flux at grid
    points coinciding with an observed cadence (within half a
    step) and the segment median elsewhere (the internal
    quality/MAD gaps <= GAP_D, median-filled); obs_index maps
    each observed cadence to its grid index, so the whitened
    values extract back at exactly the observed timestamps.
    """
    med = float(np.median(f_seg))
    span = float(t_seg[-1] - t_seg[0])
    n_grid = int(round(span / dt)) + 1
    n_grid = max(n_grid, 2)
    t_grid = t_seg[0] + np.arange(n_grid) * dt
    # Nearest observed cadence per grid point (searchsorted on
    # both neighbours — the observed times are sorted).
    pos = np.searchsorted(t_seg, t_grid)
    pos_clip = np.clip(pos, 0, len(t_seg) - 1)
    pos_lo = np.clip(pos - 1, 0, len(t_seg) - 1)
    d_hi = np.abs(t_seg[pos_clip] - t_grid)
    d_lo = np.abs(t_seg[pos_lo] - t_grid)
    nearest = np.where(d_hi <= d_lo, pos_clip, pos_lo)
    dist = np.minimum(d_hi, d_lo)
    f_grid = np.full(n_grid, med, dtype=float)
    hit = dist <= 0.5 * dt
    f_grid[hit] = f_seg[nearest[hit]]
    # Observed cadence -> grid index (round to the nearest grid
    # point; every observed cadence is within half a step of one
    # by construction of the grid step = median dt).
    obs_index = np.clip(
        np.round((t_seg - t_seg[0]) / dt).astype(int),
        0, n_grid - 1)
    return t_grid, f_grid, obs_index


def _whiten_segment(t_seg, f_seg):
    """Whiten one contiguous segment (>= T_MIN_SEG_D span).

    Returns (f_whitened, seg_info): the whitened flux at the
    observed timestamps, and a JSON-safe dict (nperseg,
    n_windows, delta_f_per_day, psd_floor_ratio — the median
    smoothed PSD over f in [f1, 15/day] over the white floor,
    the red-noise excess the filter attenuates; None when no
    bin falls in that band).
    """
    dt = float(np.median(np.diff(t_seg)))
    t_grid, f_grid, obs_index = _uniform_grid(t_seg, f_seg, dt)
    freqs, psd_smooth, p_white, info = estimate_psd(t_grid, f_grid)
    # Median-subtract before the FFT (the level is added back
    # after); pad with the median (= 0 after subtraction).
    med = float(np.median(f_grid))
    centred = f_grid - med
    n_pad = max(1, int(round(PAD_FRAC * len(centred))))
    padded = np.concatenate(
        (np.zeros(n_pad), centred, np.zeros(n_pad)))
    n_fft = len(padded)
    fft_freqs = np.fft.rfftfreq(n_fft, d=dt)
    # Log-linear interpolation of P_smooth onto the FFT grid,
    # clamped flat to P_smooth(f1) below f1 (np.interp's left);
    # W(0) = W(f1) by the same clamp (the DC bin of a
    # median-subtracted segment is ~0, so its weight is moot).
    log_f = np.log10(freqs[1:])
    log_p = np.log10(psd_smooth[1:])
    pos = fft_freqs > 0
    log_p_fft = np.empty(len(fft_freqs), dtype=float)
    log_p_fft[0] = log_p[0]
    log_p_fft[pos] = np.interp(np.log10(fft_freqs[pos]), log_f,
                               log_p, left=log_p[0],
                               right=log_p[-1])
    p_fft = np.exp(log_p_fft * math.log(10.0))
    w = np.sqrt(p_white / p_fft)
    w = np.minimum(w, 1.0)  # the never-amplify cap (M8)
    if not np.all(np.isfinite(w)):
        raise ValueError("non-finite whitening filter")
    spec = np.fft.rfft(padded)
    whitened_padded = np.fft.irfft(spec * w, n=n_fft)
    whitened = whitened_padded[n_pad:n_pad + len(centred)] + med
    if not np.all(np.isfinite(whitened)):
        raise ValueError("non-finite whitened segment")
    out = whitened[obs_index]
    # PSD floor ratio: the red-noise excess over the white floor
    # in the post-SavGol red-noise band (f ~ 1-15/day).
    band = (freqs >= freqs[1]) & (freqs <= 15.0)
    if np.any(band):
        floor_ratio = float(np.median(psd_smooth[band]) / p_white)
    else:
        floor_ratio = None
    seg_info = {"nperseg": info["nperseg"],
                "n_windows": info["n_windows"],
                "delta_f_per_day": info["delta_f_per_day"],
                "psd_floor_ratio": floor_ratio}
    return out, seg_info


def whiten_curve(t, f, gap_d=GAP_D):
    """The frozen whitening pipeline (M5-M10) on a flattened
    curve (t, f).

    Splits (t, f) into contiguous segments at gaps > gap_d;
    segments shorter than T_MIN_SEG_D are left UNWHITENED;
    longer segments are whitened per _whiten_segment. Returns
    (f_whitened, info): f_whitened has the same shape as f, and
    info is a JSON-safe dict (unwhitened_cadence_frac,
    psd_floor_ratio — the median across whitened segments, None
    when no segment was whitened — n_segments, n_whitened).

    Raises ValueError on any whitening failure (non-finite PSD,
    a segment too short after padding, an FFT failure) — the
    caller (bulk_screen._screen_one) falls back to the
    unwhitened curve for that screen (M15) and records it.
    """
    t = np.asarray(t, dtype=float)
    f = np.asarray(f, dtype=float)
    if len(t) != len(f):
        raise ValueError("t/f length mismatch")
    out = f.copy()
    segments = _segments_from_times(t, gap_d)
    n_unwhitened = 0
    ratios = []
    n_whitened = 0
    for (a, b) in segments:
        span = float(t[b - 1] - t[a]) if b - a > 1 else 0.0
        if span < T_MIN_SEG_D or b - a < 8:
            n_unwhitened += b - a
            continue
        seg_out, seg_info = _whiten_segment(t[a:b], f[a:b])
        out[a:b] = seg_out
        n_whitened += 1
        if seg_info["psd_floor_ratio"] is not None:
            ratios.append(seg_info["psd_floor_ratio"])
    info = {
        "unwhitened_cadence_frac": (
            float(n_unwhitened / len(t)) if len(t) else 0.0),
        "psd_floor_ratio": (float(np.median(ratios))
                            if ratios else None),
        "n_segments": int(len(segments)),
        "n_whitened": int(n_whitened),
    }
    return out, info


def matched_filter_search(t, f, periods, durations):
    """Whiten (t, f) and run the identical astropy BLS on the
    whitened curve (same grid, same durations — the caller
    passes the pipeline's periods/durations; the robust SDE is
    the caller's, so the SDE computation is shared with the BLS
    branch by construction).

    Returns (bls_result, f_whitened, info): bls_result is the
    astropy BoxLeastSquares power result on the whitened curve,
    f_whitened the whitened flux, info the whiten_curve info
    dict. Raises on whitening failure (the M15 fallback is the
    caller's — _screen_one falls back to unwhitened BLS).
    """
    from astropy.timeseries import BoxLeastSquares
    f_w, info = whiten_curve(t, f)
    bls = BoxLeastSquares(t, f_w)
    res = bls.power(periods, list(durations))
    return res, f_w, info
