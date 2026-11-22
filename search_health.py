"""Search-health vocabulary + periodogram health check (Phase 3, P3-1 / DF-20).

One definition site for the outcome vocabulary the vote settled (TB-10):
a periodogram search is either numerically invalid, boundary-limited,
or valid — and a valid search either detects something or it doesn't.
The survivor dispositions live here too so the bulk screen (P3-14)
and the health check (P3-1) can never fork the vocabulary.

Why this exists: deep_v1's unmasked BLS periodograms went degenerate
on heavily-flagged QLP hosts (SDE NaN, period pinned at the 25 d
ceiling) and the pipeline reported them as ordinary non-detections —
a blind search passing as "no hit". The DF-17 census found 0 NaN-SDE
rows in the stored ledger, so the degenerate cases were invisible in
the records, not absent from the searches. A degenerate search must
record SEARCH_INVALID, never pass as a valid search.

Claude's _robust_sde catch (Phase 3 vote): the robust-SDE scale
falls back to 1e-12 when the noise floor has zero variance (MAD == 0
and std == 0). A peak that sits OUTSIDE the noise-floor sample — e.g.
a strong systematic-family peak, which the scale computation
excludes — then reads as a huge finite SDE instead of NaN. Worse,
BLS on constant flux does not even produce exactly-zero powers:
the detrend leaves ~1e-13 floating-point residue, BLS turns it
into ~1e-27 powers, and the scale-invariant SDE amplifies that
residue to a max SDE of 44.4 (measured 2026-11-15) — above the
deep HIT_SDE. The health check therefore tests the noise-floor
SCALE against an absolute threshold (DEGENERATE_SCALE_MAX),
not exact zero variance, so a degenerate search can never
masquerade as a high-SDE detection.
"""

import math

# --- Search-health outcomes (TB-10 four-way vocabulary) ------------------
SEARCH_INVALID = "SEARCH_INVALID"
BOUNDARY_LIMITED = "BOUNDARY_LIMITED"
VALID_NO_DETECTION = "VALID_NO_DETECTION"
VALID_DETECTION = "VALID_DETECTION"

SEARCH_HEALTH_VALUES = frozenset({
    SEARCH_INVALID, BOUNDARY_LIMITED, VALID_NO_DETECTION, VALID_DETECTION,
})

# The robust-SDE scale below which a periodogram's noise floor is
# floating-point noise, not data. MUST match the 1e-12 fallback
# scale in hunter._sde_scale and bulk_screen._robust_sde (both
# return 1e-12 when the noise floor has exactly zero variance).
# Measured separation (2026-11-15, bulk BLS grid): pure noise at
# 0.3% -> scale 1.6e-05; pure noise at 0.01% (quieter than any
# real TESS star) -> 1.7e-08; WASP-29b-like signal -> 3.1e-05;
# constant flux (floating-point noise only) -> 2.1e-27, with a
# max SDE of 44.4 — above the deep HIT_SDE. 1e-12 sits 4+ orders
# below the quietest plausible real floor and 15 orders above
# the floating-point case.
DEGENERATE_SCALE_MAX = 1e-12

# --- Survivor dispositions (shared with P3-14 grid-edge work) ------------
# PERIODIC_CANDIDATE / SINGLE_EVENT / BELOW_THRESHOLD are ChatGPT's
# four-way data model (the fourth term, SEARCH_INVALID, is above).
# SINGLE_TRANSIT_POOL / GRID_EDGE_REJECT are the grid-edge split
# (P3-14): the pool is Phase 4's single-transit input, ledgered as
# deferred, not refuted.
PERIODIC_CANDIDATE = "PERIODIC_CANDIDATE"
SINGLE_EVENT = "SINGLE_EVENT"
BELOW_THRESHOLD = "BELOW_THRESHOLD"
SINGLE_TRANSIT_POOL = "SINGLE_TRANSIT_POOL"
GRID_EDGE_REJECT = "GRID_EDGE_REJECT"
# Demoted by the SECTOR_EPOCH_CLUSTER veto (P3-15, bulk_v4):
# the row is a member of a >20-star (P, T0) cluster — a shared
# glitch epoch, not a planet. A demotion, never a deletion:
# the row keeps this disposition and stays queryable in
# screen_hits.jsonl; a member repeating in another sector can
# be revived (P3-13 §7). The veto overwrites a P3-14
# disposition on the same row (the veto is the later, stronger
# verdict); the P3-14 finding survives in the row's grid_edge
# hand-off record.
DEMOTED_SECTOR_EPOCH_CLUSTER = "DEMOTED_SECTOR_EPOCH_CLUSTER"
# Demoted by the T0-cluster veto (F-1, bulk_v6 / PIPE50-1):
# the row is a few-event (n_events <= 2) member of a >20-star
# T0-only cluster — a sector-wide common-mode artifact epoch,
# not a planet. Same demote-not-delete reversibility as the
# (P, T0) veto: the row keeps this disposition and stays
# queryable in screen_hits.jsonl (the manual-review queue
# covers both veto dispositions). A row is demoted by at most
# one veto in the §6 merge order (the (P, T0) veto runs first
# on the pass-1 set; F-1 runs on the post-veto kept set plus
# the K=3 join), so no precedence rule is needed between them.
DEMOTED_T0_CLUSTER = "DEMOTED_T0_CLUSTER"
# Demoted by the nearby-eclipsing VSX filter (5.2 null
# diagnosis fix #2): the host has a VSX variable of type E
# (eclipsing binary) at separation 2-30 arcsec — a nearby
# blend, not the target itself. Same demote-not-delete
# reversibility as the T0 veto: the row keeps this
# disposition and stays queryable; the triggering VSX entry
# (name, vartype, period, separation) is recorded in the
# host record's `vsx_filter` audit key. Measured trade-off:
# 5 + 5 rows at 0/170 + 0/144 planet cost (the blend link is
# solid for only 1 of the 3 triggering hosts — see
# DIAGNOSIS_5_2_NULL.md section 5).
DEMOTED_VSX_NEARBY_E = "DEMOTED_VSX_NEARBY_E"

DISPOSITION_VALUES = frozenset({
    PERIODIC_CANDIDATE, SINGLE_EVENT, BELOW_THRESHOLD,
    SINGLE_TRANSIT_POOL, GRID_EDGE_REJECT,
    DEMOTED_SECTOR_EPOCH_CLUSTER, DEMOTED_T0_CLUSTER,
    DEMOTED_VSX_NEARBY_E,
})


def _noise_floor_degenerate(powers, period_vals, systematic_periods):
    """True when the robust-SDE noise floor is degenerate — i.e.
    its scale is at floating-point-noise level, so the SDE
    divides by a meaningless number. Mirrors the scale
    computation exactly: the base is the powers OUTSIDE the
    systematic family (+-3%); the scale is MAD*1.4826 when the
    MAD is positive, else the std when positive, else the
    1e-12 fallback. Degenerate means scale <= DEGENERATE_SCALE_MAX.

    Why absolute, not exact-zero: BLS on constant flux does NOT
    produce exactly-zero powers — the detrend leaves ~1e-13
    floating-point residue, BLS turns it into ~1e-27 powers, and
    the scale-invariant SDE amplifies that residue to a max SDE
    of 44.4 (measured 2026-11-15). An exact-zero check would
    miss it; the scale check catches both the exact-zero case
    (fallback scale 1e-12) and the floating-point-noise case."""
    import numpy as np
    keep = np.ones(len(powers), dtype=bool)
    for s in systematic_periods:
        keep &= np.abs(period_vals - s) > 0.03 * s
    base = np.asarray(powers, dtype=float)[keep]
    if base.size == 0:
        return True, "no periodogram points outside the systematic family"
    med = float(np.median(base))
    mad = float(np.median(np.abs(base - med))) * 1.4826
    scale = mad if mad > 0 else float(np.std(base))
    if scale <= 0:
        scale = DEGENERATE_SCALE_MAX
    if scale <= DEGENERATE_SCALE_MAX:
        return True, ("degenerate periodogram: noise-floor scale "
                      f"{scale:.3g} at floating-point level "
                      "(robust SDE is meaningless)")
    return False, ""


def assess_periodogram(powers, period_vals, peak_index, sde_at_peak,
                       systematic_periods, hit_sde):
    """Health of one BLS search. Returns (status, reason).

    powers / period_vals: the periodogram arrays (same length).
    peak_index: index of the headline peak in those arrays.
    sde_at_peak: the robust SDE at the headline peak.
    systematic_periods: the systematic family excluded from the
        noise floor (hunter._SYSTEMATIC_PERIODS /
        bulk_screen.SYSTEMATIC_PERIODS — same values, passed in
        because the bulk screen's come from its profile).
    hit_sde: the caller's detection bar — a VALID search splits
        into VALID_DETECTION (sde >= hit_sde) vs
        VALID_NO_DETECTION. Deep passes HIT_SDE (8.5); bulk
        passes RECORD_FLOOR_SDE (6.0, the record floor — the
        tier logic decides survivorship separately).

    Checks, in order: empty periodogram; non-finite powers;
    non-finite SDE at the peak; degenerate (floating-point-level
    scale) noise floor; peak at the grid edge. A boundary peak
    is NOT invalid
    — a real signal can lie near a search boundary, and bulk's
    20 d edge holds legitimate single dips (TB-10).
    """
    import numpy as np
    pw = np.asarray(powers, dtype=float)
    pv = np.asarray(period_vals, dtype=float)
    if pw.size == 0 or pv.size == 0 or pw.size != pv.size:
        return SEARCH_INVALID, "empty or mismatched periodogram arrays"
    if not np.all(np.isfinite(pw)):
        return SEARCH_INVALID, "non-finite periodogram powers"
    if not math.isfinite(float(sde_at_peak)):
        return SEARCH_INVALID, "non-finite SDE at peak"
    degenerate, deg_reason = _noise_floor_degenerate(
        pw, pv, systematic_periods)
    if degenerate:
        return SEARCH_INVALID, deg_reason
    if peak_index <= 0 or peak_index >= pw.size - 1:
        return BOUNDARY_LIMITED, "headline peak at search grid edge"
    if float(sde_at_peak) >= hit_sde:
        return VALID_DETECTION, "valid search with a detection"
    return VALID_NO_DETECTION, "valid search with no qualifying detection"
