"""P4-1a: oracle-informed K=2 mask-and-re-search PROTOTYPE.

Phase 4, item 4-1a (build brief DB-1/DB-2). The PB-1 oracle bound (45/451
recovered) was measured with ephemerides from a FRESH pass-1 BLS run on the
injected curve. This prototype must NOT use a fresh pass-1 measurement: it
estimates the contaminant ephemeris from the data, starting only from the
RECORDED pass-1 period (the frozen P3-10 record carries period + depth, no
epoch, no duration — PB-6 section 2c) and a fold-based fit on the
preprocessed light curve. The estimation error is the lossy step that
justifies the pre-registered bar of 23 rescues (50% of the oracle bound).

Estimation (fold-based, NOT a re-search):
  1. Local period refinement: scan frequencies within +/-1 BLS grid step of
     the recorded period (quarter-step resolution), maximizing the folded
     box depth SNR at a mid-grid duration. Accept the refinement only if it
     improves the SNR by >= 10%; otherwise keep the recorded period. This is
     a refinement around a known period, not a search — it cannot move to a
     harmonic (thousands of grid steps away) and it never runs BLS.
  2. T0 / duration fit at the refined period: scan phase (400 steps over
     [-0.5, 0.5)) x the 6 BLS durations, maximizing folded depth / noise.
     T0 is the transit centre nearest the sector midpoint (t_mid), which
     minimizes fold-smear bias from any residual period error.

Mask rules (brief A19-A22 / IB-1 guardrails, implemented verbatim):
  - Width: max(1.25*D, D + 2*drift), drift from the LIVE BLS grid
    (shared helper in bulk/oracle_run.py — the same code the oracle used).
  - 1.75x width buffer when the recorded pass-1 depth > 0.5%.
  - Conditional phase-scanned secondary co-mask, ONLY if recorded depth
    > 1% OR secondary SNR >= 3.0; the secondary phase comes from a scan of
    phi in [0.15, 0.85] at the estimated duration (unlike the oracle's fixed
    phi = 0.5).
  - Cumulative masked duty-cycle cap: <= 25% of VALID cadences (finite t/f
    and passing the quality mask). Above it the trial is STOPPED
    (STOPPED_MASK_DUTY_CYCLE) and gets no pass 2.
  - Anti-alias veto on the pass-2 result: pass-2 period a harmonic of the
    masked contaminant period (m, n in {1..4}, eps = 0.012) AND pass-2
    transit epochs coinciding with the masked windows -> VETOED (not a
    rescue). Disjoint epochs -> kept (true MMR exception): a planet whose
    transits coincided with the contaminant's would have been masked away,
    so a coincident-epoch harmonic "recovery" is leakage.

Epoch rule (PB-6 section 11 — UNPINNED there, defined and pre-registered
HERE by P4-1a, before the measurement run):
  - delta_T0 = ((T0_found - epoch_btjd) mod P_inj), wrapped to [-P/2, +P/2].
  - Epoch match iff |delta_T0| <= 0.5 * D_inj.
  - Empirical basis (epoch-rule groundwork, 2026-11-17): on the PB-1 oracle
    run, 44/45 oracle-recovered trials have |delta_T0| <= 0.128*D_inj; the
    single failure (TIC 308208247 s96 planet04, 23.05*D) is a demonstrably
    false rescue — a different 2-event dip pair at a coincidentally similar
    period — which the rule correctly removes. Any tolerance in
    (0.13, 23.05)*D gives identical results on that dataset, so 0.5*D sits
    mid-gap with 4x headroom above the largest genuine value. Joint
    period+epoch false-positive count among pass-2 survivors is 0. A missing
    found epoch (null t0) is an epoch-rule FAIL, not a skip.
  - The P4-1a GATE is M-6 (period-only, >= 23 rescues). The epoch rule is
    measured alongside (how many M-6 rescues also pass it) and restates the
    oracle bound as 44/451 genuine; it does not change the gate verdict.

Runtime-order law (brief): pre-mask only confirmed contaminants per sector
-> stitch -> K=3 on the stitched curve. K=3 is 4-1b's; this module is K=2
only. The oracle mask + artifact mask COMBINED is a 4-1b input, not built
here.

Offline and pure: no downloads, no BLS search. Depends on bulk_screen for
_fold_depth and the grid constants, and on bulk/oracle_run for the shared
mask_half_width helper.
"""

import numpy as np

import bulk_screen as bs

from bulk.oracle_run import mask_half_width

# --------------------------------------------------------------------------
# Pre-registered constants (P4-1a). Do not tune on outcomes.
# --------------------------------------------------------------------------

# Epoch rule: |delta_T0| <= EPOCH_TOL_DUR_FRAC * D_inj. See module docstring.
EPOCH_TOL_DUR_FRAC = 0.5

# Anti-alias veto: harmonic ratio tolerance (brief: eps ~= 0.01-0.015).
ALIAS_EPS = 0.012
ALIAS_MN = (1, 2, 3, 4)

# Duty-cycle cap on VALID cadences (brief: <= 25%).
DUTY_CYCLE_CAP = 0.25

# 1.75x width buffer when recorded pass-1 depth > 0.5%.
BUFFER_DEPTH_PCT = 0.5
BUFFER_FACTOR = 1.75

# Secondary co-mask: trigger if recorded depth > 1% OR secondary SNR >= 3.0;
# phase scanned over [0.15, 0.85].
COMASK_DEPTH_PCT = 1.0
COMASK_SNR = 3.0
COMASK_PHASE_LO = 0.15
COMASK_PHASE_HI = 0.85

# Fold estimator: local refinement within +/-1 grid step, quarter-step
# resolution; accept only on >= 10% SNR improvement over the recorded period.
REFINE_HALF_STEPS = 4
REFINE_STEP_FRAC = 0.25
REFINE_MIN_GAIN = 0.10
REFINE_DURATION_D = 0.13
N_PHASE_COARSE = 100
N_PHASE_FINE = 400
N_PHASE_COMASK = 70

# SNR below which the fold fit is flagged unreliable (recorded, not fatal).
LOW_SNR_FLAG = 2.0


# --------------------------------------------------------------------------
# Grid helpers
# --------------------------------------------------------------------------

def grid_df():
    """Live BLS frequency step (1/d), from the loaded calibration."""
    return ((1.0 / bs.MIN_PERIOD_D) - (1.0 / bs.MAX_PERIOD_D)) / (
        bs.BLS_GRID_POINTS - 1)


# --------------------------------------------------------------------------
# Fold-based ephemeris estimation
# --------------------------------------------------------------------------

def _best_phase_snr(t, f, period, t_ref, duration, n_phase):
    """Best folded depth SNR over a phase scan at one period/duration.

    Returns (best_phase, best_depth, best_snr) with phase in [-0.5, 0.5).
    Phase 0 is the transit centre at t_ref; the returned phase is the dip
    centre relative to t_ref.
    """
    phases = np.linspace(-0.5, 0.5, n_phase, endpoint=False)
    best_snr = -np.inf
    best_phase = 0.0
    best_depth = 0.0
    for ph in phases:
        depth, n_in, noise = bs._fold_depth(t, f, period, t_ref, duration,
                                            phase_center=float(ph))
        if n_in < 2 or noise <= 0 or not np.isfinite(depth):
            continue
        snr = depth / noise
        if snr > best_snr:
            best_snr = snr
            best_phase = float(ph)
            best_depth = float(depth)
    if not np.isfinite(best_snr):
        return 0.0, 0.0, 0.0
    return best_phase, best_depth, float(best_snr)


def estimate_ephemeris(t, f, period_recorded):
    """Estimate (period, T0, duration) for the contaminant at a known period.

    t, f are the PREPROCESSED arrays as they enter BLS (quality-masked,
    normalized, clipped, flattened — see bulk/oracle_run.preprocess_arrays).
    period_recorded is the frozen P3-10 recorded pass-1 period. No BLS run,
    no fresh pass-1 measurement: the period is refined locally and T0/D come
    from the fold.

    Returns a dict with period_ref, t0_est, duration_est, depth_est,
    snr_est, t_ref, refined (bool), refine_snr_gain, and diagnostics.
    """
    t = np.asarray(t, dtype=float)
    f = np.asarray(f, dtype=float)
    t_mid = 0.5 * (float(np.nanmin(t)) + float(np.nanmax(t)))

    # --- Step 1: local period refinement (+/-1 grid step, quarter steps).
    df = grid_df()
    f0 = 1.0 / float(period_recorded)
    _, _, snr_at_recorded = _best_phase_snr(
        t, f, float(period_recorded), t_mid, REFINE_DURATION_D,
        N_PHASE_COARSE)
    best_period = float(period_recorded)
    best_snr = snr_at_recorded
    tried = []
    for j in range(-REFINE_HALF_STEPS, REFINE_HALF_STEPS + 1):
        if j == 0:
            continue
        fj = f0 + j * REFINE_STEP_FRAC * df
        if fj <= 0:
            continue
        pj = 1.0 / fj
        _, _, snr_j = _best_phase_snr(t, f, pj, t_mid, REFINE_DURATION_D,
                                      N_PHASE_COARSE)
        tried.append({"period_d": float(pj), "snr": float(snr_j)})
        if snr_j > best_snr:
            best_snr = snr_j
            best_period = float(pj)
    # The best found across the scan is reported as-is (diagnostic);
    # the ACCEPTED period only moves when the gain clears the gate.
    if snr_at_recorded > 0:
        gain = (best_snr - snr_at_recorded) / snr_at_recorded
    else:
        gain = 0.0 if best_snr <= 0 else float("inf")
    refined = bool(best_period != float(period_recorded)
                   and gain >= REFINE_MIN_GAIN)
    if not refined:
        best_period = float(period_recorded)

    # --- Step 2: (phase x duration) box fit at the refined period.
    durations = list(bs.BLS_DURATIONS_D)
    phases = np.linspace(-0.5, 0.5, N_PHASE_FINE, endpoint=False)
    best = {"snr": -np.inf, "phase": 0.0, "duration": durations[0],
            "depth": 0.0}
    for dur in durations:
        for ph in phases:
            depth, n_in, noise = bs._fold_depth(
                t, f, best_period, t_mid, float(dur),
                phase_center=float(ph))
            if n_in < 2 or noise <= 0 or not np.isfinite(depth):
                continue
            snr = depth / noise
            if snr > best["snr"]:
                best = {"snr": float(snr), "phase": float(ph),
                        "duration": float(dur), "depth": float(depth)}
    if not np.isfinite(best["snr"]):
        best = {"snr": 0.0, "phase": 0.0, "duration": durations[0],
                "depth": 0.0}

    t0_est = t_mid + best["phase"] * best_period
    return {
        "period_recorded_d": float(period_recorded),
        "period_ref_d": float(best_period),
        "period_refined": bool(refined),
        "refine_snr_at_recorded": float(snr_at_recorded),
        "refine_snr_best": float(best_snr),
        "refine_snr_gain": float(gain),
        "refine_tried": tried,
        "t_ref_btjd": float(t_mid),
        "t0_est_btjd": float(t0_est),
        "phase_est": float(best["phase"]),
        "duration_est_d": float(best["duration"]),
        "depth_est_frac": float(best["depth"]),
        "snr_est": float(best["snr"]),
        "low_snr": bool(best["snr"] < LOW_SNR_FLAG),
    }


def scan_secondary(t, f, period, t0, duration):
    """Scan phi in [0.15, 0.85] for a secondary dip at the given ephemeris.

    Returns (phase, depth_frac, snr) with phase in [0.15, 0.85] — the phase
    of the deepest secondary dip. t, f are preprocessed arrays.
    """
    phases = np.linspace(COMASK_PHASE_LO, COMASK_PHASE_HI, N_PHASE_COMASK)
    best_snr = -np.inf
    best_phase = 0.5
    best_depth = 0.0
    for ph in phases:
        pc = float(ph) if ph < 0.5 else float(ph) - 1.0
        depth, n_in, noise = bs._fold_depth(t, f, period, t0, duration,
                                            phase_center=pc)
        if n_in < 2 or noise <= 0 or not np.isfinite(depth):
            continue
        snr = depth / noise
        if snr > best_snr:
            best_snr = snr
            best_phase = float(ph)
            best_depth = float(depth)
    if not np.isfinite(best_snr):
        return 0.5, 0.0, 0.0
    return best_phase, float(best_depth), float(best_snr)


# --------------------------------------------------------------------------
# Mask construction (IB-1 rules)
# --------------------------------------------------------------------------

def _drop_windows(t, centres, half_width):
    """Boolean keep-mask: False for cadences within half_width of a centre."""
    keep = np.ones(len(t), dtype=bool)
    for c in centres:
        keep &= ~((t >= c - half_width) & (t <= c + half_width))
    return keep


def _centres_in_span(t0, period, t_min, t_max, phase=0.0):
    """Transit centres (at the given phase) covering [t_min, t_max]."""
    anchor = t0 + phase * period
    k_min = int(np.floor((t_min - anchor) / period)) - 1
    k_max = int(np.ceil((t_max - anchor) / period)) + 1
    return [anchor + k * period for k in range(k_min, k_max + 1)]


def build_k2_mask(t, f, q, ephemeris, recorded_depth_pct, secondary=None,
                  duty_cap=DUTY_CYCLE_CAP, depth_trigger=True):
    """Build the K=2 prototype mask for one trial.

    t, f, q are the RAW arrays (pre-quality-mask). ephemeris is the dict
    from estimate_ephemeris. recorded_depth_pct is the frozen recorded
    pass-1 depth (percent). secondary is the (phase, depth, snr) tuple from
    scan_secondary, or None if the scan was not run.

    P4-1b extension (optional parameters; defaults preserve P4-1a
    behaviour exactly): duty_cap overrides the 25% cumulative cap
    (e.g. the period-aware cap arm, or 1.0 to bypass the internal
    check when the caller applies the cap to a UNION mask itself);
    depth_trigger=False disables the recorded-depth > 1% co-mask
    trigger (the depth-trigger ablation arm) while keeping the
    secondary-SNR trigger.

    Returns (keep, stats): keep is a boolean array over the raw arrays
    (True = keep); stats carries the mask parameters, the duty cycle, the
    co-mask trigger, and stopped/stop_reason when the duty-cycle cap fires
    (keep is then all-True — the trial is recorded as stopped, no pass 2).
    """
    t = np.asarray(t, dtype=float)
    f = np.asarray(f, dtype=float)
    q = np.asarray(q)
    t_span = float(np.nanmax(t) - np.nanmin(t))
    period = float(ephemeris["period_ref_d"])
    t0 = float(ephemeris["t0_est_btjd"])
    duration = float(ephemeris["duration_est_d"])

    half, drift = mask_half_width(period, duration, t_span)
    width = 2.0 * half
    buffer_applied = False
    if recorded_depth_pct is not None and recorded_depth_pct > BUFFER_DEPTH_PCT:
        width *= BUFFER_FACTOR
        half = width / 2.0
        buffer_applied = True

    # Secondary co-mask trigger (brief A21): recorded depth > 1% OR
    # secondary SNR >= 3.0, phase from the scan (not fixed at 0.5).
    comask = False
    comask_phase = None
    comask_trigger = None
    sec_snr = None
    sec_depth = None
    if secondary is not None:
        comask_phase, sec_depth, sec_snr = (float(secondary[0]),
                                            float(secondary[1]),
                                            float(secondary[2]))
        if depth_trigger and recorded_depth_pct is not None and recorded_depth_pct > COMASK_DEPTH_PCT:
            comask = True
            comask_trigger = "depth_gt_1pct"
        elif sec_snr >= COMASK_SNR:
            comask = True
            comask_trigger = "secondary_snr_gte_3"
        if not comask:
            comask_phase = None

    t_min = float(np.nanmin(t))
    t_max = float(np.nanmax(t))
    centres = _centres_in_span(t0, period, t_min, t_max)
    keep = _drop_windows(t, centres, half)
    n_primary_centres = len(centres)
    n_comask_centres = 0
    if comask:
        centres2 = _centres_in_span(t0, period, t_min, t_max,
                                    phase=comask_phase)
        keep &= _drop_windows(t, centres2, half)
        n_comask_centres = len(centres2)

    # Duty cycle on VALID cadences (finite t/f, passing the quality mask).
    valid = (np.isfinite(t) & np.isfinite(f)
             & ((q & bs.QUALITY_MASK) == 0))
    n_valid = int(valid.sum())
    n_dropped_valid = int((valid & ~keep).sum())
    duty = (n_dropped_valid / n_valid) if n_valid > 0 else 0.0

    stats = {
        "mask_half_width_d": float(half),
        "mask_width_d": float(width),
        "grid_drift_d": float(drift),
        "buffer_applied": bool(buffer_applied),
        "buffer_factor": BUFFER_FACTOR if buffer_applied else 1.0,
        "secondary_phase": comask_phase,
        "secondary_depth_frac": sec_depth,
        "secondary_snr": sec_snr,
        "secondary_comasked": bool(comask),
        "comask_trigger": comask_trigger,
        "n_primary_centres": n_primary_centres,
        "n_comask_centres": n_comask_centres,
        "n_cadences_dropped": int((~keep).sum()),
        "n_valid_cadences": n_valid,
        "n_valid_dropped": n_dropped_valid,
        "duty_cycle": float(duty),
        "duty_cap": float(duty_cap),
        "depth_trigger": bool(depth_trigger),
        "stopped": False,
        "stop_reason": None,
    }
    if duty > duty_cap:
        stats["stopped"] = True
        stats["stop_reason"] = "STOPPED_MASK_DUTY_CYCLE"
        keep = np.ones(len(t), dtype=bool)
    return keep, stats


# --------------------------------------------------------------------------
# Anti-alias veto (brief: m, n in {1..4}, eps ~= 0.01-0.015)
# --------------------------------------------------------------------------

def _wrapped_phase_diff(t_a, t_b, period):
    """(t_a - t_b) mod period, wrapped to [-period/2, +period/2]."""
    d = (t_a - t_b) % period
    if d > period / 2.0:
        d -= period
    return d


def alias_veto(p2_period, p2_t0, p1_period, p1_t0, mask_half_width_d,
               comask_phase=None):
    """Anti-alias veto for a pass-2 result against the masked contaminant.

    VETOED iff the pass-2 period is a harmonic of the masked period
    (m, n in {1..4} within ALIAS_EPS) AND the pass-2 transit epochs
    coincide with the masked windows (primary, or the co-masked secondary
    phase when one was masked). Disjoint epochs -> kept (true MMR
    exception). A null pass-2 epoch cannot establish coincidence, so the
    veto cannot fire on it (recorded as coincident=False).
    """
    out = {"is_alias": False, "harmonic_m": None, "harmonic_n": None,
           "period_ratio": None, "delta_primary_d": None,
           "delta_secondary_d": None, "coincident": False, "vetoed": False}
    if p2_period is None or p1_period is None:
        return out
    ratio = float(p2_period) / float(p1_period)
    out["period_ratio"] = ratio
    for m in ALIAS_MN:
        for n in ALIAS_MN:
            target = m / n
            if abs(ratio - target) / target <= ALIAS_EPS:
                out["is_alias"] = True
                out["harmonic_m"] = m
                out["harmonic_n"] = n
                break
        if out["is_alias"]:
            break
    if not out["is_alias"]:
        return out
    if p2_t0 is None or p1_t0 is None:
        return out
    d1 = _wrapped_phase_diff(p2_t0, p1_t0, p1_period)
    out["delta_primary_d"] = float(d1)
    coincident = abs(d1) < mask_half_width_d
    if comask_phase is not None:
        t_sec = p1_t0 + comask_phase * p1_period
        d2 = _wrapped_phase_diff(p2_t0, t_sec, p1_period)
        out["delta_secondary_d"] = float(d2)
        coincident = coincident or (abs(d2) < mask_half_width_d)
    out["coincident"] = bool(coincident)
    out["vetoed"] = bool(coincident)
    return out


# --------------------------------------------------------------------------
# Epoch rule (P4-1a pre-registration — see module docstring)
# --------------------------------------------------------------------------

def epoch_delta(t0_found, epoch_inj, period_inj):
    """Wrapped epoch difference (d): ((T0_found - epoch) mod P) in [-P/2, P/2].

    Returns None when the found epoch is missing (null t0).
    """
    if t0_found is None:
        return None
    return _wrapped_phase_diff(float(t0_found), float(epoch_inj),
                               float(period_inj))


def epoch_match(delta_d, duration_inj, tol_frac=EPOCH_TOL_DUR_FRAC):
    """Epoch match iff |delta_T0| <= tol_frac * D_inj. None delta -> False."""
    if delta_d is None or duration_inj is None:
        return False
    return abs(float(delta_d)) <= tol_frac * float(duration_inj)
