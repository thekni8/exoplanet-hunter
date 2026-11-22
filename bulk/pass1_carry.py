"""5.1 pass-1 carry-forward (Phase 5, S4 design note §4.4).

Pure functions shared by the campaign drivers (k2_run, k3_run,
p43_run) and the frozen-replay validation — one implementation,
so the replay measures exactly what the drivers do.

The K=2 mask deletes the signal pass 1 found: pass 1 runs on
raw flux, the mask is built from pass-1's own ephemeris, and
the final record is pass2 OR pass3 — pass 1 is not in the OR
(0/800 disjoint on the bright-star single leg). Design (A)
retains pass-1 survivors as carried final rows: the mask still
applies for the pass-2/3 searches, but the pass-1 result is
preserved, subject to the same downstream gates as any final
row (F-1 at merge time, F-2, alias veto, tier/MES gates).

A carried row is built from the pass-1 SUBSET (the stored
record shape), never the full screen record — so the replay
can build it from frozen host files exactly as the driver
builds it live. F-1 (merge-time T0 veto) is NOT applied here:
it needs cross-host clustering and runs at merge time, exactly
as for pass-2/3 rows.
"""

from bulk import k2_prototype as k2
from bulk import k3_prototype as k3
from bulk import oracle_run as orc
from bulk.inject_campaign import check_recovery

# Period-match tolerance for the same-signal test (the
# RECOVERY_TOL precedent: 1%).
SAME_SIGNAL_PERIOD_TOL = 0.01


def same_signal(period_a, t0_a, period_b, t0_b, duration_d):
    """True iff two screen rows are the SAME signal (§4.4.4):
    periods within 1% AND wrapped epoch difference within one
    transit duration. False when any input is missing (epoch
    coincidence cannot be established) or the duration is
    missing/zero."""
    if (period_a is None or t0_a is None or period_b is None
            or t0_b is None or duration_d is None
            or not duration_d):
        return False
    if (abs(float(period_a) - float(period_b)) / float(period_b)
            > SAME_SIGNAL_PERIOD_TOL):
        return False
    delta = k2.epoch_delta(t0_a, t0_b, period_b)
    if delta is None:
        return False
    return abs(delta) <= float(duration_d)


def _period_matches(period_a, period_b,
                    tol=SAME_SIGNAL_PERIOD_TOL):
    """Period-only match (for veto-reference exclusion)."""
    if period_a is None or period_b is None:
        return False
    return (abs(float(period_a) - float(period_b))
            / float(period_b) <= tol)


def build_carried_row(pass1_subset, *, flagged=(), veto_ref=None,
                      contaminants=None, veto_skipped_reason=None):
    """Build the carried final row for a pass-1 survivor (§4.4).

    pass1_subset: the stored pass-1 screen subset (orc._subset
    shape). flagged: orc.flagged_periods output for the leg's
    flagged source (per-sector pass-1s on the stitched leg;
    the fresh pass-1 itself on the single leg). veto_ref: the
    single-leg alias-veto reference — {"period_ref_d",
    "t0_est_btjd", "mask_half_width_d", "comask_phase"} (the
    ephemeris + mask stats, same reference as pass-2's veto).
    contaminants: the stitched-leg veto references (the
    k3.pass3_veto list). veto_skipped_reason: recorded when
    neither reference is given (the null legs: the ephemeris
    is seeded from pass-1 itself, so a veto against it would
    be a signal vetoed by itself — degenerate, skipped).

    Returns (row_or_None, audit). row is None when pass-1 is
    not a survivor (no carry). The audit carries the F-2
    outcome, the alias-veto dict (stored by the driver as
    alias_veto_carried), and the veto-reference exclusion
    count. The veto never changes the row's status (the
    pass-2 pattern: the veto is a separate key the scorer
    reads); F-2 demotes the row exactly as it demotes a
    pass-2/3 row (status "demoted" + flags + provenance).

    Veto-reference exclusion (documented design decision):
    a veto reference must be a DIFFERENT signal from the
    candidate. A reference whose period matches the carried
    row's period within 1% IS the same signal measured again
    (the stitched leg's original-sector entry is seeded from
    the fresh pass-1 itself; the single leg's ephemeris can
    coincide with the fresh peak) — vetoing against it would
    veto every carried row by construction. Such references
    are excluded and counted; harmonic aliases (ratio != 1)
    are still vetoed.
    """
    audit = {"f2_demoted": False, "f2_flags": [],
             "alias_veto": None, "n_veto_refs_excluded": 0}
    if pass1_subset is None:
        audit["reason"] = "no-pass1-record"
        return None, audit
    if pass1_subset.get("status") != "survivor":
        audit["reason"] = "pass1-not-survivor"
        return None, audit
    row = dict(pass1_subset)
    row["flags"] = list(pass1_subset.get("flags") or [])
    row["carried_from"] = "pass1"
    # F-2 (§4.5.3): exactly as a pass-2/3 row. On the single
    # leg the flagged source is pass-1 itself, so this fires
    # only if a survivor carries an EB flag (the screen
    # demotes EB-flagged rows, so it should not happen — the
    # check documents the routing and fails closed if it ever
    # does). On the stitched leg the source is the per-sector
    # pass-1s, and a stitched signal matching a per-sector EB
    # is a real F-2 case.
    carried = orc.carried_eb_flags(row.get("period_days"),
                                   flagged)
    if carried:
        orc.apply_eb_carry(row, carried)
        audit["f2_demoted"] = True
        audit["f2_flags"] = list(carried)
    # Alias veto (§4.5.4): the same veto function as pass-2/3,
    # with same-signal references excluded (see above).
    if veto_ref is not None:
        ref_period = veto_ref.get("period_ref_d")
        if _period_matches(ref_period, row.get("period_days")):
            audit["alias_veto"] = {
                "vetoed": False,
                "skipped_reason": "same-signal-as-reference"}
            audit["n_veto_refs_excluded"] = 1
        else:
            audit["alias_veto"] = k2.alias_veto(
                row.get("period_days"), row.get("t0_btjd"),
                ref_period, veto_ref.get("t0_est_btjd"),
                veto_ref.get("mask_half_width_d"),
                comask_phase=veto_ref.get("comask_phase"))
    elif contaminants is not None:
        refs = [c for c in contaminants
                if not _period_matches(c.get("period_d"),
                                       row.get("period_days"))]
        audit["n_veto_refs_excluded"] = (
            len(contaminants) - len(refs))
        audit["alias_veto"] = k3.pass3_veto(
            row.get("period_days"), row.get("t0_btjd"), refs)
    else:
        audit["alias_veto"] = {
            "vetoed": False,
            "skipped_reason": (veto_skipped_reason
                               or "no-veto-reference")}
    return row, audit


def dedupe_carried(carried_row, pass2_subset, pass3_subset,
                   duration_d):
    """Which later pass independently recovered the SAME signal
    as the carried row (§4.4.4) — "pass2", "pass3", or None.
    Only surviving later rows count (a non-survivor is not a
    final row, so there is nothing to merge with). A deduped
    carry is NOT a loss: the signal is in the final record
    once, with pass-1 provenance."""
    if carried_row is None:
        return None
    for name, sub in (("pass2", pass2_subset),
                      ("pass3", pass3_subset)):
        if sub is None or sub.get("status") != "survivor":
            continue
        if same_signal(carried_row.get("period_days"),
                       carried_row.get("t0_btjd"),
                       sub.get("period_days"),
                       sub.get("t0_btjd"), duration_d):
            return name
    return None


def veto_ref_from(ephemeris, mstats):
    """Single-leg alias-veto reference from the estimated
    ephemeris + mask stats (the same reference as pass-2's
    veto), or None when no mask was built (gated-off stats
    carry no half-width — no mask, no veto) or the ephemeris
    is missing."""
    if ephemeris is None or mstats is None:
        return None
    if mstats.get("mask_half_width_d") is None:
        return None
    if ephemeris.get("period_ref_d") is None:
        return None
    return {"period_ref_d": ephemeris["period_ref_d"],
            "t0_est_btjd": ephemeris.get("t0_est_btjd"),
            "mask_half_width_d": mstats["mask_half_width_d"],
            "comask_phase": mstats.get("secondary_phase")}


def carried_survivor(carried_row):
    """True iff the carried row is a final survivor (built from
    a pass-1 survivor and not F-2-demoted)."""
    return bool(carried_row is not None
                and carried_row.get("status") == "survivor")


def carried_recovery_verdict(carried_row, alias_veto, trial):
    """(recovered, genuine) for a carried row against the
    injected trial — the campaign's own rule, parallel to the
    pass-2 verdict: M-6 (status survivor + period within 1%)
    AND not alias-vetoed; genuine adds the half-duration epoch
    match (k2.epoch_match's default, as for k2_genuine). The
    scorer re-derives recovery with the one-duration rule
    independently; this is the runner's accounting."""
    if carried_row is None:
        return False, False
    m6 = bool(check_recovery(carried_row, trial["period_d"]))
    recovered = bool(
        m6 and not (alias_veto or {}).get("vetoed"))
    delta = k2.epoch_delta(carried_row.get("t0_btjd"),
                           trial["epoch_btjd"],
                           trial["period_d"])
    genuine = bool(recovered and k2.epoch_match(
        delta, trial["duration_d"]))
    return recovered, genuine


def count_final_rows(carried_row, pass2_subset, pass3_subset,
                     duration_d):
    """Distinct final rows (§4.4.2 + §4.4.4): carried + pass-2
    + pass-3 survivors, minus one when the carried row
    dedupes with a surviving later pass. Pass-2 vs pass-3
    dedup is NOT applied (the pre-5.1 counting rule counts
    them separately; this fix changes only the carried row's
    contribution)."""
    n = int(carried_survivor(carried_row))
    n += int(pass2_subset is not None
             and pass2_subset.get("status") == "survivor")
    n += int(pass3_subset is not None
             and pass3_subset.get("status") == "survivor")
    if (carried_survivor(carried_row)
            and dedupe_carried(carried_row, pass2_subset,
                               pass3_subset, duration_d)
            is not None):
        n -= 1
    return n
