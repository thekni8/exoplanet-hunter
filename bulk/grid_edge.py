"""Grid-edge disposition for bulk-screen survivors (Phase 3, P3-14).

The S96 bulk_v3 rescore left 1,630 survivors at P = 20.0 exactly —
the search grid's upper edge, 35% of all survivors. P = 20.0 is a
search-boundary observation, not proof of a single transit: BLS
pins a lone dip to the longest period it can. These records need a
distinct disposition, not silent inclusion in tier B and not silent
deletion (3/3 of the vote: never delete grid-edge singles).

Vocabulary (defined once in search_health.py, P3-1 — imported
here, never redefined):
  SINGLE_TRANSIT_POOL — passes the quality floor; Phase 4's
    single-transit input, ledgered as deferred, not refuted.
  GRID_EDGE_REJECT — fails the floor; not pool material.
  PERIODIC_CANDIDATE — a boundary-limited record with >1 event;
    periodic candidacy stands (the boundary flag is informational).

The quality floor (Gemini, adopted by the vote): a single-event
grid-edge record enters the pool only when its in-transit cadences
carry NO unmasked quality flags AND it has >= 4 in-transit
cadences (filters single-cadence cosmic rays / dropouts).

Leg evaluation order (maximally informative without fabrication):
the unmasked-flag leg is evaluated first because it can fail on
evidence alone (any unmasked flag in transit fails it, whatever
the cadence count); the cadence leg needs n_in_transit. A record
whose unmasked-flag state is unknown, or whose cadence count is
unknown after the flag leg passes, is left UNDISPOSITIONED
(disposition None + a reason) — never pooled or rejected on
missing data. That is the honest outcome for legacy rescore rows,
which carry no n_in_transit: they are not re-dispositioned by
fiat. They get dispositioned when re-screened under bulk_v4+
(which records n_in_transit), or by a dedicated FITS re-read
pass (recorded as follow-up in wave2-progress.md).
"""

import search_health as _health

# The vote's floor values (P3-14). The calibration profile is the
# single source of truth at screen time — bulk_screen passes its
# profile-derived values in; these are the defaults for callers
# without a profile (and the values the profile must match).
GRID_EDGE_MIN_IN_TRANSIT_CADENCES = 4
GRID_EDGE_MAX_UNMASKED_FLAG_FRACTION = 0.0

# Ledger status for pooled singles: deferred, not refuted.
LEDGER_DEFERRED = "deferred"

# Tolerance for "period is the grid edge": the BLS grid's upper
# endpoint is exactly max_period_d as built, but a record that
# passed through JSON keeps full float precision — 1e-9 relative
# catches float noise without catching 19.99.
_EDGE_RTOL = 1e-9


def is_grid_edge_record(rec, max_period_d=20.0):
    """True when the record sits at the period grid's UPPER edge.
    The low edge (0.5 d) is out of scope: no pile-up was observed
    there, and P3-14 is the P = 20.0 singles."""
    period = rec.get("period_days")
    if period is None:
        return False
    try:
        period = float(period)
    except (TypeError, ValueError):
        return False
    return abs(period - float(max_period_d)) <= _EDGE_RTOL * float(
        max_period_d)


def _unmasked_flags_present(rec):
    """Tri-state: True when in-transit cadences provably carry an
    unmasked quality flag, False when they provably carry none,
    None when the record cannot say.

    Evidence, in order: the explicit fraction field
    (in_transit_unmasked_flag_fraction, the DF-13 deep-pipeline
    field — 0.0 means none, > 0 means some); else the M-4
    unmasked-bit tally (empty tally means none; non-empty means
    some — the tally counts cadences per bit, so only the
    zero/non-zero distinction is used, never a fraction derived
    from it)."""
    frac = rec.get("in_transit_unmasked_flag_fraction")
    if frac is not None:
        try:
            return float(frac) > 0.0
        except (TypeError, ValueError):
            pass
    tally = rec.get("unmasked_bits_in_transit")
    if tally is None:
        return None
    if not isinstance(tally, dict):
        return None
    try:
        return sum(int(v) for v in tally.values()) > 0
    except (TypeError, ValueError):
        return None


def disposition_grid_edge(rec, max_period_d=20.0,
                          min_in_transit=GRID_EDGE_MIN_IN_TRANSIT_CADENCES,
                          max_unmasked_fraction=GRID_EDGE_MAX_UNMASKED_FLAG_FRACTION):
    """Disposition for one survivor record. Returns
    (disposition, reason); disposition is None when the record
    is not grid-edge or the floor cannot be evaluated on the
    available evidence — the caller leaves such records
    undispositioned.

    max_unmasked_fraction is the floor's flag leg (the vote's
    value is 0.0: no unmasked flags in transit). It is a
    parameter, not a constant, so the profile stays the single
    source of truth; only 0.0 is meaningful today (any positive
    value would need its own vote — the leg is a zero test, and
    the evidence functions only distinguish zero from non-zero).
    """
    if not is_grid_edge_record(rec, max_period_d=max_period_d):
        return None, "not a grid-edge record"
    n_events = rec.get("n_events")
    if n_events is None:
        return None, ("grid-edge record with unknown event count "
                      "— floor unevaluable")
    try:
        n_events = int(n_events)
    except (TypeError, ValueError):
        return None, ("grid-edge record with non-numeric event "
                      "count — floor unevaluable")
    if n_events > 1:
        return (_health.PERIODIC_CANDIDATE,
                "boundary-limited but multi-event; periodic "
                "candidacy stands")
    # Single-event grid-edge record: apply the floor, flag leg
    # first (it can fail on evidence alone).
    if float(max_unmasked_fraction) != 0.0:
        return None, ("unsupported max_unmasked_fraction "
                      f"{max_unmasked_fraction!r} — the floor is "
                      "a zero test (P3-14); any positive value "
                      "needs its own vote")
    unmasked = _unmasked_flags_present(rec)
    if unmasked is True:
        return (_health.GRID_EDGE_REJECT,
                "in-transit cadences carry unmasked quality flags")
    n_in = rec.get("n_in_transit")
    if n_in is None:
        if unmasked is None:
            return None, ("floor unevaluable — in-transit flag "
                          "state and cadence count both missing")
        return None, ("floor unevaluable — n_in_transit missing "
                      "(legacy record; re-screen under bulk_v4+)")
    try:
        n_in = int(n_in)
    except (TypeError, ValueError):
        return None, ("floor unevaluable — non-numeric "
                      "n_in_transit")
    if unmasked is None:
        return None, ("floor unevaluable — in-transit flag state "
                      "unknown")
    if n_in < int(min_in_transit):
        return (_health.GRID_EDGE_REJECT,
                f"fewer than {int(min_in_transit)} in-transit "
                f"cadences ({n_in}) — single-cadence "
                "dropout/cosmic-ray country")
    return (_health.SINGLE_TRANSIT_POOL,
            "passes the quality floor (no unmasked in-transit "
            f"flags, {n_in} in-transit cadences)")


def build_handoff_record(rec, camera=None, ccd=None,
                         max_period_d=20.0,
                         min_in_transit=GRID_EDGE_MIN_IN_TRANSIT_CADENCES,
                         max_unmasked_fraction=GRID_EDGE_MAX_UNMASKED_FLAG_FRACTION):
    """The full hand-off record for one grid-edge single (Claude):
    epoch, depth, duration, SNR, camera/CCD, flagged fraction —
    plus the disposition and the ledger status (deferred, not
    refuted). Values absent from the record read None; the
    hand-off is a snapshot, not a validation gate. camera/ccd
    come from the FITS header at screen time (None when the
    header lacks them). The floor parameters pass through to
    disposition_grid_edge so the nested disposition agrees with
    the top-level one under any profile."""
    disposition, _reason = disposition_grid_edge(
        rec, max_period_d=max_period_d,
        min_in_transit=min_in_transit,
        max_unmasked_fraction=max_unmasked_fraction)
    return {
        "tic": rec.get("tic"),
        "sector": rec.get("sector"),
        "period_days": rec.get("period_days"),
        "epoch_btjd": rec.get("t0_btjd"),
        "depth_percent": rec.get("depth_percent"),
        "duration_hours": rec.get("duration_hours"),
        "max_event_snr": rec.get("max_event_snr"),
        "camera_ccd": {"camera": camera, "ccd": ccd},
        "flagged_in_transit_frac":
            rec.get("flagged_in_transit_frac"),
        "n_in_transit": rec.get("n_in_transit"),
        "n_events": rec.get("n_events"),
        "disposition": disposition,
        "ledger_status": LEDGER_DEFERRED,
    }
