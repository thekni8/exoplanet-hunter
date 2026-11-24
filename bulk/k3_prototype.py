"""P4-1b: K=3 mask-and-re-search on the stitched curve.

Phase 4, item 4-1b (build brief DB-1/DB-2; PB-6 A1-A4, A18-A22).
P4-1a PASSED its gate (52/451 genuine vs the bar of 23) with the K=2
prototype (bulk/k2_prototype.py). This module adds the third search
pass:

  pass 1 (fresh, validation only) -> K=2 mask (prototype rules,
  unchanged) -> pass 2 -> [if pass 2 does not rescue AND its peak is
  an eligible "confirmed contaminant"] pass-3 mask (same IB-1 rules,
  built from the pass-2 peak's estimated ephemeris) unioned with the
  K=2 mask -> pass 3.

Runtime-order law (brief): pre-mask only confirmed contaminants per
sector -> stitch -> K=3 on the stitched curve. The campaign trials
are single-sector, so in this measurement the stitch is the identity
on one sector — the code implements an explicit stitch_sectors
function and the driver calls it, so the K=3 code path IS the
stitched-curve path. True multi-sector stitching (signal present
across sectors) is P4-3's scope.

Pre-registration: the design in this module (eligibility rule §0.3,
cap rule §0.4, combined mask §0.5, arms §0.8 of P41B_RECORD.md) was
written BEFORE any P4-1b measurement. The epoch rule is P4-1a's
(|delta_T0| <= 0.5 * D_inj) — reused from k2_prototype, NOT
redefined here.

Pass-3 mask eligibility ("confirmed contaminant", pre-registered):
  (i) pass 2 did NOT rescue;
  (ii) pass 2 returned a found period;
  (iii) pass-2 depth_percent > 1.0% OR pass-2 status == "survivor"
        (depth > 1% is the pipeline's own planet-like boundary —
        tier B requires depth <= 1.0%, PB-6 A23);
  (iv) the pass-2 peak is not coincident-harmonic leakage of the
       pass-1 masked contaminant (the alias veto did not fire).
Capped secondary queue: at most ONE secondary mask per trial
(SECONDARY_QUEUE_CAP = 1) — the single best eligible pass-2 peak.

Cap rule (pre-registered): the trial cap is fixed once from the
pass-1 recorded contaminant period — 25% for P >= 5 d; 75% for
P < 5 d in the cap-aware arm (the primary arm keeps 25% for all).
The 75% cap guarantees >= 25% of valid cadences remain unmasked.
"""

import numpy as np

import bulk_screen as bs

from bulk import k2_prototype as k2
from bulk import matched_filter as _mf  # 5.8: gate_depth_pct (standalone)

# --------------------------------------------------------------------------
# Pre-registered constants (P4-1b). Do not tune on outcomes.
# --------------------------------------------------------------------------

# Capped secondary queue: at most one secondary (pass-2) mask per trial.
SECONDARY_QUEUE_CAP = 1

# Period-aware duty-cycle cap (cap-aware arm): the 5 d threshold
# separates the binding regime (all 68 P4-1a stops were P < 5 d) from
# the non-binding regime. The 75% short-period cap guarantees >= 25%
# of valid cadences remain unmasked for the re-search.
CAP_SHORT_P_D = 5.0
CAP_SHORT = 0.75
CAP_LONG = 0.25

# Primary-arm cap (frozen, PB-6 A19).
CAP_PRIMARY = 0.25

# Arms (P41B_RECORD.md §0.8).
ARMS = ("prototype", "combined", "cap-aware", "no-depth-trigger")


def trial_cap(arm, period_recorded_d):
    """Duty-cycle cap for one trial under the given arm.

    Primary/combined/no-depth-trigger arms: 0.25 for all trials.
    Cap-aware arm: 0.25 for P >= 5 d, 0.75 for P < 5 d (the
    period-aware rule, pre-registered in P41B_RECORD.md §0.4).
    """
    if arm == "cap-aware" and period_recorded_d is not None \
            and float(period_recorded_d) < CAP_SHORT_P_D:
        return CAP_SHORT
    return CAP_LONG


# --------------------------------------------------------------------------
# Stitch (runtime-order law: pre-mask per sector -> stitch -> K=3)
# --------------------------------------------------------------------------

def stitch_sectors(sectors):
    """Stitch per-sector (t, f, q) curves into one time-sorted curve.

    sectors is a list of (t, f, q) array triples, one per sector.
    Returns (t, f, q) concatenated and sorted by time. A single-sector
    input returns that sector's arrays unchanged (identity) — which is
    the campaign case (one FITS file per host-sector).
    """
    if len(sectors) == 0:
        return (np.array([], dtype=float), np.array([], dtype=float),
                np.array([], dtype=int))
    if len(sectors) == 1:
        t, f, q = sectors[0]
        return (np.asarray(t, dtype=float), np.asarray(f, dtype=float),
                np.asarray(q))
    t = np.concatenate([np.asarray(s[0], dtype=float) for s in sectors])
    f = np.concatenate([np.asarray(s[1], dtype=float) for s in sectors])
    q = np.concatenate([np.asarray(s[2]) for s in sectors])
    order = np.argsort(t, kind="stable")
    return t[order], f[order], q[order]


# --------------------------------------------------------------------------
# Artifact spans (PB-2 T0-derived glitch-epoch spans, combined arm)
# --------------------------------------------------------------------------

def artifact_keep_mask(t, spans):
    """Boolean keep-mask for the artifact spans (mirror of
    bulk.oracle_run.apply_artifact_mask's drop logic, which returns
    masked arrays instead of the keep array).

    t is the raw time array; spans is a list of [lo, hi] BTJD pairs.
    True = keep the cadence.
    """
    t = np.asarray(t, dtype=float)
    keep = np.ones(len(t), dtype=bool)
    for (lo, hi) in spans:
        keep &= ~((t >= lo) & (t <= hi))
    return keep


def combined_duty_cycle(t, f, q, keep):
    """Fraction of VALID cadences dropped by keep (same valid
    definition as k2.build_k2_mask: finite t/f, passing the quality
    mask)."""
    t = np.asarray(t, dtype=float)
    f = np.asarray(f, dtype=float)
    q = np.asarray(q)
    keep = np.asarray(keep, dtype=bool)
    valid = (np.isfinite(t) & np.isfinite(f)
             & ((q & bs.QUALITY_MASK) == 0))
    n_valid = int(valid.sum())
    if n_valid == 0:
        return 0.0
    return float((valid & ~keep).sum() / n_valid)


def apply_union_cap(t, f, q, keep_a, keep_b, cap):
    """Union two keep-masks and apply the duty-cycle cap to the union.

    Returns (keep_union, duty, stopped): keep_union is keep_a & keep_b
    unless the union duty exceeds cap, in which case keep_union is
    all-True and stopped is True (the trial is recorded as stopped,
    no pass 3 — mirroring k2.build_k2_mask's stopped behaviour).
    """
    keep_union = np.asarray(keep_a, dtype=bool) & np.asarray(
        keep_b, dtype=bool)
    duty = combined_duty_cycle(t, f, q, keep_union)
    stopped = bool(duty > cap)
    if stopped:
        keep_union = np.ones(len(np.asarray(t)), dtype=bool)
    return keep_union, duty, stopped


# --------------------------------------------------------------------------
# Pass-3 mask eligibility ("confirmed contaminant", pre-registered)
# --------------------------------------------------------------------------

def pass3_eligible(p2, veto, p2_rescued):
    """Whether a pass-2 result earns a pass-3 mask.

    p2 is the pass-2 screen-record subset (status, period_days,
    depth_percent, ...). veto is the k2.alias_veto output for pass 2
    vs the pass-1 masked contaminant. p2_rescued is the pass-2 M-6
    rescue flag (veto-excluded).

    Returns (eligible, reason). Reasons are stable strings recorded
    per trial.
    """
    if p2_rescued:
        return False, "pass2-rescued"
    if p2 is None or p2.get("period_days") is None:
        return False, "no-pass2-period"
    if (veto or {}).get("vetoed"):
        return False, "alias-leakage"
    # 5.8 (R6): the eligibility depth is the JUDGED depth — the
    # unwhitened fold depth on an MF pass-2 record, never the
    # whitened BLS depth_percent.
    depth = _mf.gate_depth_pct(p2)
    status = p2.get("status")
    if status == "survivor":
        return True, "eligible-survivor"
    if depth is not None and float(depth) > 1.0:
        return True, "eligible-depth-gt-1pct"
    return False, "not-confirmed-contaminant"


def pass3_veto(p3_period, p3_t0, contaminants):
    """Combined alias veto for a pass-3 result against ALL masked
    contaminants.

    contaminants is a list of dicts, each with period_d, t0_btjd,
    mask_half_width_d, comask_phase (or None). Returns a dict with
    vetoed (bool) and the per-contaminant veto outputs. Vetoed iff
    ANY contaminant's veto fires (harmonic + coincident epochs).
    """
    outs = []
    vetoed = False
    for c in contaminants:
        v = k2.alias_veto(p3_period, p3_t0, c["period_d"], c["t0_btjd"],
                          c["mask_half_width_d"],
                          comask_phase=c.get("comask_phase"))
        outs.append(v)
        vetoed = vetoed or bool(v.get("vetoed"))
    return {"vetoed": bool(vetoed), "per_contaminant": outs}
