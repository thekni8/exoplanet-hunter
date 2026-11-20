# Oracle-mask run + event-count rescore (Phase 4 pre-build, PB-1 + PB-2).
#
# PB-1 (oracle): for each of the 451 wrong-period planet trials in the
# frozen P3-10 v2 campaign record, mask the recorded contaminant
# ephemeris with the planned mask rules and re-run UNCHANGED bulk_v4
# pass 1 (_screen_one). The oracle recovery count upper-bounds what
# P4-1a (mask-and-re-search) can achieve; the P4-1a bar is a
# pre-registered fraction (ORACLE_FRACTION = 0.5) of that bound.
# Also produces the P_found/P_inj table and the EB-hosts-vs-rest split.
#
# PB-2 (event-count rescore): for every planet trial (and, in --mode
# s97, for the 13,983 Tier-A mega-cluster members of the S97 v4
# rescore), recompute the tier-relevant counts under the P4-2 rule —
# fully in-span events only, minimum in-window coverage, guard bands
# at segment edges — and re-derive the tier. Reports the regression
# cost on the 412 recovered planets and the S97 queue-size effect.
# Also tests the cheaper baseline: an event-level artifact mask for
# the 148 depth trials (mask the sector's known glitch epochs,
# re-run pass 1) — mask-and-re-search must beat it.
#
# Design notes (read before modifying):
# - The pipeline is NEVER modified: this driver only CALLS
#   bulk_screen._screen_one (pass 1 / pass 2) and replicates its
#   preprocessing + _rescore arithmetic in-process for the PB-2
#   measurement. The replication is VALIDATED on every trial: the
#   unfiltered rescore must match _screen_one's recorded rs fields.
# - Pass 1 must REPRODUCE the recorded campaign screen (period
#   within 1%, SDE within 2%). The campaign ran under bulk_v3; this
#   driver runs under bulk_v4 — the BLS-relevant constants are
#   identical between v3 and v4 (verified by diff), so P/SDE/depth
#   reproduce; only status/tier may differ for 2-event tier-B rows
#   (TWO_COMBINED, v4-only), which does not change the 451
#   population. A reproduction failure is recorded, not fatal —
#   but a low reproduction rate invalidates the run.
# - Mask rule (Claude, comparison DB-6): mask width =
#   max(1.25*D, D + 2*drift), drift = P * df * T_span, df from the
#   live BLS grid. Secondary co-mask (bundle rule): if the pass-1
#   secondary depth is >= 1.0%, also mask the phi=0.5 windows.
# - P4-2 operational rule (PB-2 measurement definition; pre-
#   registered in PB-6 as P4-2's rule): an event counts only if its
#   full [centre-D/2, centre+D/2] window lies within one
#   contiguous valid segment with `guard_d` clearance from the
#   segment edges, with in-window coverage >= MIN_COV_FRAC of the
#   expected cadences and >= MIN_COV_N cadences. A gap is a jump
#   > GAP_D between consecutive valid cadences. Guard widths
#   0 / 0.1 / 0.25 d are all measured (trade-off curve, not a
#   single point); 0.25 d matches P4-3's edge trim.
# - The oracle bar fraction (0.5) is a judgment call, recorded
#   here and pre-registered in PB-6: the oracle masks with
#   KNOWN-TRUTH ephemerides from a fresh pass-1 measurement, while
#   the prototype must estimate them from data — capturing half
#   the oracle bound is the pass bar for 4-1a.
#
# Usage (Mac):
#   ORACLE_REPO=/Volumes/NVME/pingu-jobs/exoplanet-hunter \
#   .venv/bin/python bulk/oracle_run.py --mode campaign \
#     --manifest oracle_trials.json --cache bulk/cache \
#     --out-dir /Volumes/NVME/pingu-jobs/phase4-prebuild/oracle \
#     --workers 6
#   .venv/bin/python bulk/oracle_run.py --mode s97 \
#     --screen-hits bulk/run_s0097/screen_hits.jsonl ... (same flags)
#   .venv/bin/python bulk/oracle_run.py --mode phase2 ... (S95
#     artifact mask, after phase 1: derives S95 glitch epochs from
#     the phase-1 pass-1 T0s, validated against P3-13 on S96)
#   .venv/bin/python bulk/oracle_run.py --merge-only --mode campaign
#     --out-dir ...  (aggregate existing host files, no re-run)

import argparse
import hashlib
import json
import math
import os
import sys
import time
from pathlib import Path

# --- repo resolution (before any repo import; must work in spawn
# workers, which re-import this module with the parent's argv) ------
_ap = argparse.ArgumentParser(add_help=False)
_ap.add_argument("--repo", default=None)
_ns, _ = _ap.parse_known_args()
_repo_arg = _ns.repo
_here = Path(__file__).resolve()
if _repo_arg:
    REPO = Path(_repo_arg).resolve()
elif os.environ.get("ORACLE_REPO"):
    REPO = Path(os.environ["ORACLE_REPO"]).resolve()
elif _here.parent.name == "bulk" and (
        _here.parent.parent / "bulk_screen.py").exists():
    REPO = _here.parent.parent
else:
    raise SystemExit("oracle_run: need --repo (script is outside a "
                     "repo checkout and ORACLE_REPO is unset)")
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))

import numpy as np  # noqa: E402

import bulk_screen as bs  # noqa: E402
import injection_harness as ih  # noqa: E402
from bulk.inject_campaign import (ALT_HARMONIC_RATIOS,  # noqa: E402
                                check_recovery, inject_trial)
from bulk.inject_real_s96 import (load_real_fits,  # noqa: E402
                                  write_injected_fits)
from synth_fits import screen_job  # noqa: E402

ORACLE_FRACTION = 0.5       # P4-1a must clear this fraction of the bound
GUARD_VARIANTS_D = (0.0, 0.1, 0.25)
MIN_COV_FRAC = 0.5          # min in-window coverage (fraction of expected)
MIN_COV_N = 3               # min in-window cadences
GAP_D = 0.05                # jump between valid cadences that breaks a segment
SECONDARY_COMASK_MIN_PCT = 1.0  # co-mask phi=0.5 iff secondary depth >= this
HARMONIC_RATIOS = (1.0 / 3.0, 0.5, 2.0 / 3.0, 1.5, 2.0, 3.0)

# P3-13 S96 glitch-epoch spans (BTJD), p3-13-spike.md section 3.
# G0 sector start, G2/G3 orbit 199/200 boundary, G8 sector end.
# (G1/G4/G5/G6/G7 are the smaller intermediate epochs; the four
# listed spans carry the F13/F9/F6 families. The artifact mask
# uses these four spans.)
S96_GLITCH_SPANS = [
    (3908.45, 3908.75),   # G0
    (3919.85, 3920.05),   # G2
    (3920.25, 3920.45),   # G3
    (3932.95, 3933.45),   # G8
]

ORACLE_GROUPS = ("lockon_207", "depth_148", "wrong165_96")


# ---------------------------------------------------------------------------
# Preprocessing replication (must match _screen_one's front end exactly)
# ---------------------------------------------------------------------------

def preprocess_arrays(t, f, q):
    """Replicate _screen_one's preprocessing: quality mask ->
    normalise -> MAD clip -> savgol flatten. Returns (t, f) as
    they enter BLS. Uses the live calibration constants."""
    from scipy.signal import savgol_filter
    t = np.asarray(t, dtype=float)
    f = np.asarray(f, dtype=float)
    q = np.asarray(q, dtype=int)
    ok = np.isfinite(t) & np.isfinite(f) & ((q & bs.QUALITY_MASK) == 0)
    t, f = t[ok], f[ok]
    if len(t) < 200:
        return t, f
    med = np.median(f)
    f = f / med
    keep = bs._mad_clip_mask(f, bs.CLIP_OPTION)
    t, f = t[keep], f[keep]
    dt = float(np.median(np.diff(t))) if len(t) > 1 else 0.0
    win = int(round(2.0 / dt)) if dt > 0 else 97
    win += (win % 2 == 0)
    win = int(min(max(win, 31), len(t) // 2 * 2 - 1))
    if win >= 31:
        trend = savgol_filter(f, win, 2)
        trend[trend == 0] = 1.0
        f = f / trend
    f = f - np.median(f) + 1.0
    return t, f


def segments_from_times(t, gap_d=GAP_D):
    """Contiguous valid segments — the production implementation
    (bulk_screen.segments_from_times); kept as a local alias so
    this driver's call sites are unchanged."""
    return bs.segments_from_times(t, gap_d=gap_d)


def rescore_filtered(t, f, period, t0, duration,
                     guard_d=0.0, min_cov_frac=MIN_COV_FRAC,
                     filter_events=True):
    """_rescore with the P4-2 event filter.

    P4-2: this is now a thin delegation to the production
    bulk_screen._rescore — one implementation of the rule, so
    the guard curve this driver measures IS the production
    rule's curve. (PB-2's driver carried its own copy; the
    P4-2 build ported the rule into _rescore and this function
    delegates to it. The driver's constants GAP_D /
    MIN_COV_FRAC / MIN_COV_N equal the profile defaults, so
    the delegation is exact.)"""
    return bs._rescore(t, f, period, t0, duration, guard_d=guard_d,
                       min_cov_frac=min_cov_frac,
                       filter_events=filter_events)


def derive_tier(rs, sde, depth_pct):
    """Tier logic (bulk_screen._screen_one lines 1224-1244) +
    TWO_COMBINED, from a rescore dict. Returns (tier, status,
    gate_reason). `depth_pct` and `sde` are the pass-1 values
    (unchanged by the rescore). EB-flag demotion is applied by
    the caller (flags don't change under the rescore).
    Below-floor rows (sde < RECORD_FLOOR_SDE) keep their
    below_floor status: _screen_one returns early for them."""
    if rs is None:
        return None, "recorded", None
    if sde is not None and sde < bs.RECORD_FLOOR_SDE:
        return None, "below_floor", None
    if sde is None or sde < bs.SURVIVOR_SDE:
        return None, "recorded", None
    tier = None
    if (rs["n_events"] >= bs.TIER_A_MIN_EVENTS
            and rs["mes_pink"] >= bs.TIER_A_MES
            and rs["n_strong_events"] >= bs.TIER_A_MIN_STRONG):
        tier = "A"
    elif (rs["n_events"] < bs.TIER_A_MIN_EVENTS
            and rs["max_event_snr"] >= bs.TIER_B_EVENT_SNR
            and depth_pct is not None
            and depth_pct <= bs.TIER_B_MAX_DEPTH_PCT):
        tier = "B"
    gate_reason = None
    if tier == "B" and bs.TWO_COMBINED_ENABLED and rs["n_events"] == 2:
        if not (rs["n_strong_events"] >= 2
                and rs["mes_pink"] >= bs.TIER_A_MES):
            gate_reason = "FAILED_TWO_COMBINED"
            return tier, "demoted", gate_reason
    if tier is not None:
        return tier, "survivor", None
    return None, "recorded", None


# ---------------------------------------------------------------------------
# Masks
# ---------------------------------------------------------------------------

def mask_half_width(period, duration, t_span):
    """Half of mask = max(1.25*D, D + 2*drift); drift = P*df*T."""
    df = ((1.0 / bs.MIN_PERIOD_D) - (1.0 / bs.MAX_PERIOD_D)) / (
        bs.BLS_GRID_POINTS - 1)
    drift = period * df * t_span
    width = max(1.25 * duration, duration + 2.0 * drift)
    return 0.5 * width, drift


def _drop_windows(t, f, q, centres, half_width):
    """Drop cadences within +-half_width of any centre."""
    keep = np.ones(len(t), dtype=bool)
    for c in centres:
        keep &= ~((t >= c - half_width) & (t <= c + half_width))
    return t[keep], f[keep], q[keep], int((~keep).sum())


def apply_oracle_mask(t, f, q, period, t0, duration,
                      secondary_depth_pct=None):
    """Mask the contaminant ephemeris (+ the phi=0.5 secondary
    when deep). Returns (t, f, q, stats)."""
    t = np.asarray(t, dtype=float)
    t_span = float(np.nanmax(t) - np.nanmin(t))
    half, drift = mask_half_width(period, duration, t_span)
    t_min, t_max = float(np.nanmin(t)), float(np.nanmax(t))
    k0 = math.floor((t_min - t0) / period)
    k1 = math.ceil((t_max - t0) / period)
    centres = [t0 + k * period for k in range(k0, k1 + 1)]
    t2, f2, q2, n_drop = _drop_windows(t, f, q, centres, half)
    co_mask = False
    n_drop2 = 0
    if (secondary_depth_pct is not None
            and secondary_depth_pct >= SECONDARY_COMASK_MIN_PCT):
        centres2 = [c + 0.5 * period for c in centres]
        t2, f2, q2, n_drop2 = _drop_windows(t2, f2, q2, centres2, half)
        co_mask = True
    n_tot = len(t)
    stats = {"mask_half_width_d": half, "grid_drift_d": drift,
             "n_events_masked": len(centres),
             "n_cadences_dropped": n_drop + n_drop2,
             "duty_cycle_dropped": ((n_drop + n_drop2) / n_tot
                                     if n_tot else 0.0),
             "secondary_comasked": co_mask}
    return t2, f2, q2, stats


def apply_artifact_mask(t, f, q, spans):
    """Mask the sector's known glitch-epoch spans. Returns
    (t, f, q, stats)."""
    t = np.asarray(t, dtype=float)
    keep = np.ones(len(t), dtype=bool)
    for (lo, hi) in spans:
        keep &= ~((t >= lo) & (t <= hi))
    n_drop = int((~keep).sum())
    return (t[keep], f[keep], q[keep],
            {"n_cadences_dropped": n_drop,
             "duty_cycle_dropped": (n_drop / len(t) if len(t) else 0.0),
             "n_spans": len(spans)})


def period_match_class(pfound, pinj, tol=0.02):
    """'exact' | 'harmonic' | 'wrong' | 'no-period' (2% def)."""
    if pfound is None or pinj is None or pinj <= 0:
        return "no-period"
    r = pfound / pinj
    if abs(r - 1) <= tol:
        return "exact"
    for h in HARMONIC_RATIOS:
        if abs(r - h) / h <= tol:
            return "harmonic"
    return "wrong"


# ---------------------------------------------------------------------------
# Screen-record subset (what we keep per pass)
# ---------------------------------------------------------------------------

_KEEP_KEYS = ("status", "tier", "period_days", "t0_btjd",
              "duration_hours", "depth_percent", "sde", "mes_pink",
              "n_events", "n_strong_events", "max_event_snr",
              "cdpp_pct", "v_ratio", "flags", "gate_reason",
              "secondary_depth_percent", "search_health")


def _subset(rec):
    return {k: rec.get(k) for k in _KEEP_KEYS}


def _init_worker(calibration):
    bs.set_calibration(calibration)


# ---------------------------------------------------------------------------
# Campaign mode (PB-1 + PB-2 on the 960 planet trials)
# ---------------------------------------------------------------------------

def _screen(path, tic, sector):
    # Calibration is global (set by _init_worker / the serial
    # path via bs.set_calibration); screen_job takes no
    # calibration argument.
    return bs._screen_one(screen_job(path, tic, sector))


def _eb_demoted(pass1):
    """Pass-1 demotion by an EB flag (not TWO_COMBINED, which is
    event-count-dependent and re-evaluated by derive_tier)."""
    return (pass1.get("status") == "demoted"
            and pass1.get("gate_reason") != "FAILED_TWO_COMBINED")


# ---------------------------------------------------------------------------
# F-2: EB-flag carry-forward (bulk_v6 / PIPE50-1)
# ---------------------------------------------------------------------------
# When a screen demotes a signal with EB flags, the flag travels
# with the signal identity to later passes on the same host: a
# later-pass row matching a flagged signal re-raises the flag
# (and the demotion). Evidence: TIC 38516539 — per-sector
# pass-1 screens demoted it with DURATION_EB (S95, S97) and
# SECONDARY_EB + HARMONIC_P2_SUSPECT (S96); the masked stitched
# pass-2 row carried NO flags and survived as tier A (the mask
# removed the secondary evidence). The carried set is the EB
# family only (design D-F2): flags endswith "_EB" or containing
# "HARMONIC". DEPTH_TOO_SHALLOW is demoting but NOT carried (a
# property of the new measurement, not an identity to attach
# to a later signal); TWO_EVENT_WEAK is not carried either
# (event-count-dependent, re-evaluated per pass — the same
# reasoning as _eb_demoted above).
#
# Harmonic matching uses the code's existing ratio set
# (inject_campaign.ALT_HARMONIC_RATIOS, already used for
# alt-peak filtering) at 1% tolerance (the RECOVERY_TOL
# precedent). A carried flag re-raises the demotion exactly as
# a measured flag would (status "demoted" + the flag in the
# record), and carries a provenance marker (flags_carried_from:
# "pass1") so a carried flag is never mistaken for a measured
# one. The marker is NOT in _KEEP_KEYS: call sites set it on
# the stored subset after _subset (a marker on the full record
# would not survive the subset).

# The provenance marker value for a carried flag.
FLAGS_CARRIED_FROM_PASS1 = "pass1"


def is_eb_flag(flag):
    """True iff the flag is in the carried EB family (D-F2):
    endswith "_EB" or containing "HARMONIC"."""
    return flag.endswith("_EB") or "HARMONIC" in flag


def flagged_periods(records):
    """[(period, [flags])] for EB-flagged pass-1 signals.

    `records` is one pass-1 record or an iterable of them
    (the p43 stitched leg passes the per-sector pass-1
    records). A record contributes iff it carries a found
    period AND at least one EB-family flag. Only the EB
    family is returned (D-F2)."""
    if isinstance(records, dict):
        records = [records]
    out = []
    for rec in records:
        period = rec.get("period_days") if rec else None
        if period is None:
            continue
        flags = [f for f in (rec.get("flags") or [])
                 if is_eb_flag(f)]
        if flags:
            out.append((period, flags))
    return out


def carried_eb_flags(period, flagged,
                     ratios=ALT_HARMONIC_RATIOS, tol=0.01):
    """EB flags carried to a later-pass row at `period`.

    `flagged` is flagged_periods' output. A flagged signal
    matches iff period / flagged_period is within `tol`
    (relative) of one of `ratios`. Returns the sorted unique
    matched flags, or [] (no match, or no period)."""
    if period is None:
        return []
    matched = set()
    for fperiod, flags in flagged:
        if not fperiod:
            continue
        ratio = period / fperiod
        for h in ratios:
            if abs(ratio - h) / h <= tol:
                matched.update(flags)
                break
    return sorted(matched)


def apply_eb_carry(record, flags):
    """Apply a carried flag set to a pass record, in place:
    the flags join the record's flags list (no duplicates),
    the status becomes "demoted", and the provenance marker
    records the carry. Returns True (the caller still sets
    the marker on the stored subset after _subset — see the
    module note above)."""
    existing = record.get("flags") or []
    record["flags"] = existing + [f for f in flags
                                  if f not in existing]
    record["status"] = "demoted"
    record["flags_carried_from"] = FLAGS_CARRIED_FROM_PASS1
    return True


def run_host_campaign(job):
    """One host-sector: inject each manifest trial, pass 1, PB-2
    rescore, oracle pass 2 (451), artifact pass 2b (S96 depth)."""
    tic = job["tic"]
    sector = job["sector"]
    out_dir = Path(job["out_dir"])
    workdir = Path(job["workdir"])
    manifest_sha = job["manifest_sha"]
    calibration = job["calibration"]
    keep_fits = job.get("keep_fits", False)
    out_path = out_dir / "hosts" / f"{tic}_s{sector:04d}.json"
    if out_path.exists():
        try:
            prev = json.loads(out_path.read_text())
        except ValueError:
            prev = {}
        if (prev.get("complete") is True
                and prev.get("manifest_sha") == manifest_sha):
            return {"status": "skipped", "tic": tic, "sector": sector}
    t_start = time.time()
    try:
        t, f, q, fcol, meta = load_real_fits(job["path"])
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "tic": tic, "sector": sector,
                "error": f"load_real_fits: {exc}"}
    t_min = float(np.nanmin(t))
    results = []
    for tr in job["trials"]:
        r = {"trial_id": tr["trial_id"], "tic": tic, "sector": sector,
             "group": tr["group"], "period_d": tr["period_d"],
             "epoch_offset_d": tr["epoch_offset_d"],
             "depth_frac": tr["depth_frac"],
             "recorded": tr["recorded"]}
        t_tr = time.time()
        try:
            spec = {"kind": "planet", "period_d": tr["period_d"],
                    "epoch_offset_d": tr["epoch_offset_d"],
                    "depth_frac": tr["depth_frac"]}
            f_inj, dur_d, epoch = inject_trial(t, f, q, spec, t_min)
            r["inject_epoch_delta_d"] = float(epoch - tr["epoch_btjd"])
            r["inject_dur_delta_d"] = float(dur_d - tr["duration_d"])
            base = workdir / f"{tic}_s{sector:04d}_{tr['trial_id']}"
            inj_path = str(base) + ".fits"
            write_injected_fits(inj_path, t, f_inj, q, fcol)
            p1 = _screen(inj_path, tic, sector)
            r["pass1"] = _subset(p1)
            # --- pass-1 reproduction vs the recorded campaign ---
            rec = tr["recorded"]
            p_rec = rec.get("period_days")
            s_rec = rec.get("sde")
            p1_p = p1.get("period_days")
            p1_s = p1.get("sde")
            p_err = (abs(p1_p - p_rec) / p_rec
                     if p_rec and p1_p else None)
            s_err = (abs(p1_s - s_rec) / max(s_rec, 1.0)
                     if s_rec is not None and p1_s is not None else None)
            r["pass1_repro"] = {
                "period_rel_err": p_err, "sde_rel_err": s_err,
                "ok": bool(p_err is not None and p_err < 0.01
                           and s_err is not None and s_err < 0.02)}
            # --- PB-2 rescore (from the injected arrays) --------
            t_p, f_p = preprocess_arrays(t, f_inj, q)
            dur_h = p1.get("duration_hours")
            rs = None
            if (p1_p and p1.get("t0_btjd") is not None
                    and dur_h is not None):
                rs = rescore_filtered(
                    t_p, f_p, p1_p, p1["t0_btjd"], dur_h / 24.0,
                    filter_events=False)
            if rs is not None:
                p1_rs = {k: p1.get(k) for k in
                         ("mes_pink", "n_events", "n_strong_events",
                          "max_event_snr")}
                if p1_rs["mes_pink"] is None:
                    # Below-floor pass 1: _screen_one returns
                    # early with no rs fields, so there is
                    # nothing to compare against (not a
                    # mismatch — the rescore is unvalidated
                    # for these trials, and they cannot be
                    # survivors under any guard).
                    r["preproc_validation"] = {
                        "matched": None, "reason": "pass1-no-rs"}
                else:
                    match = (
                        rs["n_events"] == p1_rs["n_events"]
                        and rs["n_strong_events"]
                        == p1_rs["n_strong_events"]
                        and abs(rs["mes_pink"] - p1_rs["mes_pink"])
                        <= 1e-6 * max(1.0, abs(p1_rs["mes_pink"]))
                        and abs(rs["max_event_snr"]
                                - p1_rs["max_event_snr"])
                        <= 1e-6 * max(1.0,
                                      abs(p1_rs["max_event_snr"])))
                    r["preproc_validation"] = {
                        "matched": bool(match),
                        "unfiltered": {k: rs[k] for k in
                                       ("mes_pink", "n_events",
                                        "n_strong_events",
                                        "max_event_snr")},
                        "pass1": p1_rs}
            else:
                r["preproc_validation"] = {"matched": None,
                                           "reason": "no-rescore"}
            variants = {}
            if (p1_p and p1.get("t0_btjd") is not None
                    and dur_h is not None):
                eb = _eb_demoted(p1)
                for guard in GUARD_VARIANTS_D:
                    rv = rescore_filtered(
                        t_p, f_p, p1_p, p1["t0_btjd"], dur_h / 24.0,
                        guard_d=guard, filter_events=True)
                    if rv is None:
                        variants[str(guard)] = {"rescore": None}
                        continue
                    tier, status, gate = derive_tier(
                        rv, p1_s, p1.get("depth_percent"))
                    if eb:
                        # EB-flag demotion persists regardless
                        # of tier (as in _screen_one: demote
                        # flags set status demoted even with
                        # tier None).
                        status = "demoted"
                    variants[str(guard)] = {
                        "n_events": rv["n_events"],
                        "n_strong_events": rv["n_strong_events"],
                        "max_event_snr": rv["max_event_snr"],
                        "mes_pink": rv["mes_pink"],
                        "n_events_dropped": rv["n_events_dropped"],
                        "tier": tier, "status": status,
                        "gate_reason": gate}
            r["pb2_rescore"] = variants
            # --- oracle pass 2 (the 451) ------------------------
            if (tr["group"] in ORACLE_GROUPS and p1_p is not None
                    and dur_h is not None
                    and p1.get("t0_btjd") is not None):
                t_m, f_m, q_m, mstats = apply_oracle_mask(
                    t, f_inj, q, p1_p, p1["t0_btjd"], dur_h / 24.0,
                    p1.get("secondary_depth_percent"))
                r["oracle_mask"] = mstats
                mask_path = str(base) + "_masked.fits"
                write_injected_fits(mask_path, t_m, f_m, q_m, fcol)
                p2 = _screen(mask_path, tic, sector)
                r["pass2"] = _subset(p2)
                r["oracle_recovered"] = bool(
                    check_recovery(p2, spec["period_d"]))
                r["pass2_match"] = period_match_class(
                    p2.get("period_days"), tr["period_d"])
                if not keep_fits:
                    os.remove(mask_path)
            # --- artifact pass 2b (S96 depth trials) ------------
            if tr["group"] == "depth_148" and sector == 96:
                t_a, f_a, q_a, astats = apply_artifact_mask(
                    t, f_inj, q, S96_GLITCH_SPANS)
                r["artifact_mask"] = astats
                art_path = str(base) + "_artifact.fits"
                write_injected_fits(art_path, t_a, f_a, q_a, fcol)
                p2b = _screen(art_path, tic, sector)
                r["pass2b"] = _subset(p2b)
                r["artifact_recovered"] = bool(
                    check_recovery(p2b, spec["period_d"]))
                r["pass2b_match"] = period_match_class(
                    p2b.get("period_days"), tr["period_d"])
                if not keep_fits:
                    os.remove(art_path)
            if not keep_fits:
                os.remove(inj_path)
        except Exception as exc:  # noqa: BLE001
            r["error"] = f"{type(exc).__name__}: {exc}"
        r["seconds"] = round(time.time() - t_tr, 2)
        results.append(r)
    rec = {"tic": tic, "sector": sector, "complete": True,
           "manifest_sha": manifest_sha, "calibration": calibration,
           "n_trials": len(results),
           "seconds": round(time.time() - t_start, 1),
           "trials": results}
    tmp = out_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(rec))
    tmp.replace(out_path)
    n_oracle = sum(1 for r in results
                   if r.get("oracle_recovered") is True)
    return {"status": "done", "tic": tic, "sector": sector,
            "n_trials": len(results), "n_oracle_recovered": n_oracle}


def _bootstrap_host_ci(host_counts, n_rep=10000, seed=20261117):
    """Host-level bootstrap 95% CI on the oracle recovery count.
    host_counts: list of (n_oracle_trials, n_recovered) per host."""
    rng = np.random.default_rng(seed)
    n_hosts = len(host_counts)
    if n_hosts == 0:
        return None
    tot = np.array([h[0] for h in host_counts], dtype=float)
    rec = np.array([h[1] for h in host_counts], dtype=float)
    counts = np.empty(n_rep)
    for i in range(n_rep):
        idx = rng.integers(0, n_hosts, n_hosts)
        counts[i] = rec[idx].sum()
    return {"lo": float(np.percentile(counts, 2.5)),
            "hi": float(np.percentile(counts, 97.5)),
            "n_rep": n_rep, "seed": seed,
            "n_hosts": n_hosts}


def merge_campaign(out_dir, manifest):
    """Aggregate per-host campaign files into oracle_summary.json."""
    out_dir = Path(out_dir)
    host_files = sorted((out_dir / "hosts").glob("*.json"))
    records = []
    for p in host_files:
        try:
            rec = json.loads(p.read_text())
        except ValueError:
            continue
        if rec.get("complete") is True:
            records.append(rec)
    trials = [tr for rec in records for tr in rec["trials"]]
    by_group = {}
    for tr in trials:
        by_group.setdefault(tr["group"], []).append(tr)
    oracle = [tr for g in ORACLE_GROUPS for tr in by_group.get(g, [])]
    repro = [tr for tr in trials if tr.get("pass1_repro")]
    n_repro_ok = sum(1 for tr in repro
                     if tr["pass1_repro"].get("ok"))
    val = [tr for tr in trials
           if tr.get("preproc_validation", {}).get("matched") is not None]
    n_val_ok = sum(1 for tr in val
                   if tr["preproc_validation"]["matched"])
    recov = sum(1 for tr in oracle
                if tr.get("oracle_recovered") is True)
    by_g = {g: {"n": len(by_group.get(g, [])),
                "recovered": sum(1 for tr in by_group.get(g, [])
                                 if tr.get("oracle_recovered") is True)}
            for g in ORACLE_GROUPS}
    by_sector = {}
    for tr in oracle:
        s = tr["sector"]
        d = by_sector.setdefault(s, {"n": 0, "recovered": 0})
        d["n"] += 1
        d["recovered"] += int(tr.get("oracle_recovered") is True)
    eb_hosts = set(manifest.get("eb_hosts", []))
    eb_deep = set(manifest.get("eb_hosts_deep", []))
    host_rec = {}
    for rec in records:
        for tr in rec["trials"]:
            if tr["group"] in ORACLE_GROUPS:
                h = host_rec.setdefault(rec["tic"], [0, 0])
                h[0] += 1
                h[1] += int(tr.get("oracle_recovered") is True)
    eb = {"n": 0, "recovered": 0}
    non_eb = {"n": 0, "recovered": 0}
    for tic, (n, r) in host_rec.items():
        d = eb if tic in eb_hosts else non_eb
        d["n"] += n
        d["recovered"] += r
    match_counts = {}
    for tr in oracle:
        m = tr.get("pass2_match")
        match_counts[m] = match_counts.get(m, 0) + 1
    ci = _bootstrap_host_ci(list(host_rec.values()))
    bar = math.ceil(ORACLE_FRACTION * recov) if recov else 0
    # PB-2: per-guard tier transitions + regression on the 412
    pb2 = {}
    for guard in GUARD_VARIANTS_D:
        g = str(guard)
        trans = {}
        reg = {"n_recovered_412": 0, "still_survivor": 0,
               "dropped": 0}
        for tr in trials:
            v = tr.get("pb2_rescore", {}).get(g)
            if not v or "tier" not in v:
                continue
            key = (tr["recorded"].get("status"), v["status"])
            trans[f"{key[0]}->{key[1]}"] = \
                trans.get(f"{key[0]}->{key[1]}", 0) + 1
            if tr["group"] == "recovered_412":
                reg["n_recovered_412"] += 1
                if v["status"] == "survivor":
                    reg["still_survivor"] += 1
                else:
                    reg["dropped"] += 1
        pb2[g] = {"transitions": trans, "regression_412": reg}
    # artifact baseline (S96 depth subset) vs oracle on the same 82
    art = [tr for tr in trials
           if tr["group"] == "depth_148"
           and tr["sector"] == 96]
    art_rec = sum(1 for tr in art
                  if tr.get("artifact_recovered") is True)
    art_oracle = sum(1 for tr in art
                     if tr.get("oracle_recovered") is True)
    summary = {
        "tool": "oracle_run", "mode": "campaign",
        "n_hosts_completed": len(records),
        "n_trials": len(trials),
        "n_oracle_trials": len(oracle),
        "pass1_reproduction": {
            "n_checked": len(repro), "n_ok": n_repro_ok,
            "mismatches": [f"{tr['tic']}_s{tr['sector']:04d}_"
                           f"{tr['trial_id']}" for tr in repro
                           if not tr["pass1_repro"].get("ok")]},
        "preproc_validation": {
            "n_checked": len(val), "n_matched": n_val_ok,
            "mismatches": [f"{tr['tic']}_s{tr['sector']:04d}_"
                           f"{tr['trial_id']}" for tr in val
                           if not tr["preproc_validation"]["matched"]][:50]},
        "oracle": {
            "recovered": recov, "n": len(oracle),
            "rate": (recov / len(oracle) if oracle else None),
            "by_group": by_g, "by_sector": by_sector,
            "eb_hosts_15": eb, "non_eb_hosts": non_eb,
            "pass2_match": match_counts,
            "host_level_ci_95": ci},
        "p4_1a_bar": {
            "oracle_bound": recov,
            "fraction": ORACLE_FRACTION,
            "bar_rescues": bar,
            "rule": ("P4-1a passes iff it rescues >= bar_rescues of "
                     "the 451 (50% of the oracle bound); the bar is "
                     "pre-registered in PB-6")},
        "pb2": pb2,
        "artifact_baseline_s96": {
            "n": len(art), "artifact_recovered": art_rec,
            "oracle_recovered_same_subset": art_oracle},
    }
    (out_dir / "oracle_summary.json").write_text(
        json.dumps(summary, indent=2))
    return summary


# ---------------------------------------------------------------------------
# S97 mode (PB-2 on the Tier-A mega-cluster members; P4-2 re-measures
# the guard curve on the FIXED screen's Tier-A members)
# ---------------------------------------------------------------------------

def run_s97_chunk(job):
    """One chunk of S97 stars: load FITS, preprocess, rescore
    under the P4-2 rule variants, re-derive tiers."""
    out_path = Path(job["out_path"])
    if out_path.exists():
        try:
            prev = json.loads(out_path.read_text())
        except ValueError:
            prev = {}
        if prev.get("complete") is True:
            return {"status": "skipped",
                    "chunk": job["chunk_id"],
                    "n": len(job["rows"])}
    cache = Path(job["cache"])
    results = []
    for row in job["rows"]:
        tic = row["tic"]
        r = {"tic": tic, "period_days": row["period_days"],
             "t0_btjd": row["t0_btjd"],
             "duration_hours": row["duration_hours"],
             "depth_percent": row["depth_percent"],
             "sde": row["sde"], "tier": row["tier"],
             "status": row["status"],
             "flags": row.get("flags"),
             "gate_reason": row.get("gate_reason")}
        try:
            path = cache / "s0097" / f"{tic}.fits"
            t, f, q, fcol, meta = load_real_fits(str(path))
            t_p, f_p = preprocess_arrays(t, f, q)
            dur_d = row["duration_hours"] / 24.0
            # P4-2: the recorded row comes from a screen that
            # applies the event-count filter at guard 0 (the
            # screen default), so the validation reproduces it
            # with the SAME filter — an unfiltered rescore would
            # mismatch on every row the filter touched. A match
            # proves driver preprocessing + rule reproduce the
            # screen's recorded numbers exactly.
            rs = rescore_filtered(t_p, f_p, row["period_days"],
                                  row["t0_btjd"], dur_d,
                                  guard_d=0.0, filter_events=True)
            if rs is not None:
                match = (
                    rs["n_events"] == row.get("n_events")
                    and rs["n_strong_events"]
                    == row.get("n_strong_events")
                    and abs(rs["mes_pink"] - row["mes_pink"])
                    <= 1e-6 * max(1.0, abs(row["mes_pink"]))
                    and abs(rs["max_event_snr"]
                            - row["max_event_snr"])
                    <= 1e-6 * max(1.0, abs(row["max_event_snr"])))
                r["preproc_validation"] = {"matched": bool(match)}
            else:
                r["preproc_validation"] = {"matched": None,
                                           "reason": "no-rescore"}
            variants = {}
            eb = _eb_demoted(row)
            for guard in GUARD_VARIANTS_D:
                rv = rescore_filtered(t_p, f_p, row["period_days"],
                                      row["t0_btjd"], dur_d,
                                      guard_d=guard,
                                      filter_events=True)
                if rv is None:
                    variants[str(guard)] = {"rescore": None}
                    continue
                tier, status, gate = derive_tier(
                    rv, row["sde"], row["depth_percent"])
                if eb:
                    status = "demoted"
                variants[str(guard)] = {
                    "n_events": rv["n_events"],
                    "n_strong_events": rv["n_strong_events"],
                    "max_event_snr": rv["max_event_snr"],
                    "mes_pink": rv["mes_pink"],
                    "n_events_dropped": rv["n_events_dropped"],
                    "tier": tier, "status": status,
                    "gate_reason": gate}
            r["pb2_rescore"] = variants
        except Exception as exc:  # noqa: BLE001
            r["error"] = f"{type(exc).__name__}: {exc}"
        results.append(r)
    rec = {"chunk_id": job["chunk_id"], "complete": True,
           "n": len(results), "results": results}
    tmp = out_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(rec))
    tmp.replace(out_path)
    return {"status": "done", "chunk": job["chunk_id"],
            "n": len(results)}


def merge_s97(out_dir):
    """Aggregate S97 chunk files into s97_summary.json."""
    out_dir = Path(out_dir)
    chunk_files = sorted((out_dir / "chunks").glob("chunk_*.json"))
    results = []
    for p in chunk_files:
        try:
            rec = json.loads(p.read_text())
        except ValueError:
            continue
        if rec.get("complete") is True:
            results.extend(rec["results"])
    val = [r for r in results
           if r.get("preproc_validation", {}).get("matched") is not None]
    n_val_ok = sum(1 for r in val
                   if r["preproc_validation"]["matched"])
    pb2 = {}
    for guard in GUARD_VARIANTS_D:
        g = str(guard)
        trans = {}
        survivors = 0
        tier_a = 0
        for r in results:
            v = r.get("pb2_rescore", {}).get(g)
            if not v or "tier" not in v:
                continue
            key = f"{r['tier']}->{v['tier']}"
            trans[key] = trans.get(key, 0) + 1
            if v["status"] == "survivor":
                survivors += 1
                if v["tier"] == "A":
                    tier_a += 1
        pb2[g] = {"transitions": trans,
                  "survivors_remaining": survivors,
                  "tier_a_remaining": tier_a,
                  "queue_reduction": len(results) - survivors}
    summary = {"tool": "oracle_run", "mode": "s97",
               "n_stars": len(results),
               "preproc_validation": {
                   "n_checked": len(val), "n_matched": n_val_ok,
                   "mismatches": [r["tic"] for r in val
                                  if not r["preproc_validation"]
                                  ["matched"]][:50]},
               "pb2": pb2}
    (out_dir / "s97_summary.json").write_text(
        json.dumps(summary, indent=2))
    return summary


# ---------------------------------------------------------------------------
# Phase 2 (PB-2 artifact baseline, S95): derive S95 glitch epochs from
# the phase-1 pass-1 T0s of wrong-period trials, validate the method
# on S96 against the P3-13 spans, then mask + re-screen the 66 S95
# depth trials. If the S96 validation fails, the S95 step is skipped
# and the baseline is S96-only (reported, not fudged).
# ---------------------------------------------------------------------------

def cluster_t0s(t0s, tol_d=0.125, min_members=4, buffer_d=0.1):
    """Group sorted T0s into clusters (consecutive within tol_d);
    keep groups with >= min_members. Returns spans
    [(lo, hi), ...] expanded by buffer_d."""
    t0s = sorted(t0s)
    spans = []
    if not t0s:
        return spans
    start = t0s[0]
    prev = t0s[0]
    count = 1
    for t0 in t0s[1:]:
        if t0 - prev <= tol_d:
            count += 1
        else:
            if count >= min_members:
                spans.append((start - buffer_d, prev + buffer_d))
            start, count = t0, 1
        prev = t0
    if count >= min_members:
        spans.append((start - buffer_d, prev + buffer_d))
    return spans


def _spans_overlap(a, b):
    return a[0] <= b[1] and b[0] <= a[1]


def run_artifact_host(job):
    """Re-inject the given depth trials, apply the artifact mask,
    screen. (Phase 2: S95 depth trials under the derived spans.)"""
    tic = job["tic"]
    sector = job["sector"]
    out_dir = Path(job["out_dir"])
    workdir = Path(job["workdir"])
    calibration = job["calibration"]
    spans = job["spans"]
    keep_fits = job.get("keep_fits", False)
    out_path = out_dir / "hosts" / f"{tic}_s{sector:04d}.json"
    if out_path.exists():
        try:
            prev = json.loads(out_path.read_text())
        except ValueError:
            prev = {}
        if prev.get("complete") is True:
            return {"status": "skipped", "tic": tic, "sector": sector}
    try:
        t, f, q, fcol, meta = load_real_fits(job["path"])
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "tic": tic, "sector": sector,
                "error": f"load_real_fits: {exc}"}
    t_min = float(np.nanmin(t))
    results = []
    for tr in job["trials"]:
        r = {"trial_id": tr["trial_id"], "tic": tic, "sector": sector,
             "group": tr["group"], "period_d": tr["period_d"]}
        try:
            spec = {"kind": "planet", "period_d": tr["period_d"],
                    "epoch_offset_d": tr["epoch_offset_d"],
                    "depth_frac": tr["depth_frac"]}
            f_inj, dur_d, epoch = inject_trial(t, f, q, spec, t_min)
            t_a, f_a, q_a, astats = apply_artifact_mask(
                t, f_inj, q, spans)
            r["artifact_mask"] = astats
            art_path = (workdir
                        / f"{tic}_s{sector:04d}_{tr['trial_id']}"
                        "_artifact.fits")
            write_injected_fits(str(art_path), t_a, f_a, q_a, fcol)
            p2b = _screen(str(art_path), tic, sector)
            r["pass2b"] = _subset(p2b)
            r["artifact_recovered"] = bool(
                check_recovery(p2b, spec["period_d"]))
            r["pass2b_match"] = period_match_class(
                p2b.get("period_days"), tr["period_d"])
            if not keep_fits:
                os.remove(art_path)
        except Exception as exc:  # noqa: BLE001
            r["error"] = f"{type(exc).__name__}: {exc}"
        results.append(r)
    rec = {"tic": tic, "sector": sector, "complete": True,
           "spans": spans, "n_trials": len(results),
           "trials": results}
    tmp = out_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(rec))
    tmp.replace(out_path)
    n_rec = sum(1 for r in results
                if r.get("artifact_recovered") is True)
    return {"status": "done", "tic": tic, "sector": sector,
            "n_trials": len(results), "n_recovered": n_rec}


def _derive_phase2_spans(p1_dir, out_dir):
    """Derive S95 glitch epochs from the phase-1 pass-1 T0s of
    wrong-period trials, after validating the T0-clustering
    method on S96 against the P3-13 spans. Returns the S95
    spans, or None if the S96 validation fails (<2/4 spans)."""
    p1_dir = Path(p1_dir)
    host_files = sorted((p1_dir / "hosts").glob("*.json"))
    t0s_by_sector = {95: [], 96: []}
    for p in host_files:
        try:
            rec = json.loads(p.read_text())
        except ValueError:
            continue
        if rec.get("complete") is not True:
            continue
        for tr in rec["trials"]:
            if tr["group"] not in ORACLE_GROUPS:
                continue
            p1 = tr.get("pass1") or {}
            if (p1.get("t0_btjd") is not None
                    and period_match_class(
                        p1.get("period_days"),
                        tr["period_d"]) == "wrong"):
                t0s_by_sector[rec["sector"]].append(p1["t0_btjd"])
    spans96 = cluster_t0s(t0s_by_sector[96])
    n_hit = sum(1 for s in S96_GLITCH_SPANS
                if any(_spans_overlap(s, d) for d in spans96))
    print(f"[oracle] phase2: S96 derived spans {spans96}; "
          f"P3-13 spans recovered {n_hit}/4 "
          f"({len(t0s_by_sector[96])} wrong-period T0s)",
          flush=True)
    validation = {"s96_derived_spans": spans96,
                  "p3_13_spans_recovered": n_hit,
                  "n_s96_t0s": len(t0s_by_sector[96]),
                  "n_s95_t0s": len(t0s_by_sector[95])}
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    (Path(out_dir) / "phase2_validation.json").write_text(
        json.dumps(validation, indent=2))
    if n_hit < 2:
        print("[oracle] phase2: S96 validation FAILED "
              "(<2/4 P3-13 spans) — S95 step skipped, "
              "artifact baseline is S96-only", flush=True)
        return None
    spans95 = cluster_t0s(t0s_by_sector[95])
    print(f"[oracle] phase2: S95 derived spans {spans95} "
          f"({len(t0s_by_sector[95])} T0s)", flush=True)
    validation["s95_derived_spans"] = spans95
    (Path(out_dir) / "phase2_validation.json").write_text(
        json.dumps(validation, indent=2))
    return spans95


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _manifest_sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _load_manifest(path):
    man = json.loads(Path(path).read_text())
    man["_sha256"] = _manifest_sha(path)
    return man


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Oracle-mask run + event-count rescore "
                    "(Phase 4 pre-build PB-1/PB-2).")
    ap.add_argument("--mode", choices=("campaign", "s97", "phase2"),
                    default="campaign")
    ap.add_argument("--repo", default=str(REPO))
    ap.add_argument("--manifest", default=None,
                    help="oracle_trials.json (campaign/phase2)")
    ap.add_argument("--cache", required=True,
                    help="cache root holding s<NNNN>/<tic>.fits")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--calibration", default="bulk_v4")
    ap.add_argument("--tics", nargs="*", default=None,
                    help="restrict to these TICs (smoke runs)")
    ap.add_argument("--limit-hosts", type=int, default=None)
    ap.add_argument("--keep-fits", action="store_true")
    ap.add_argument("--merge-only", action="store_true",
                    help="aggregate existing outputs, no re-run")
    ap.add_argument("--screen-hits", default=None,
                    help="S97 screen_hits.jsonl (s97 mode)")
    ap.add_argument("--phase1-dir", default=None,
                    help="phase-1 campaign out-dir (phase2 mode)")
    ap.add_argument("--phase2-sector", type=int, default=95,
                    help="sector for the phase2 artifact run")
    ap.add_argument("--spans-file", default=None,
                    help="JSON list of [lo, hi] spans for the "
                         "phase2 artifact run; skips the T0 "
                         "derivation/validation when given")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    cache = Path(args.cache)

    if args.mode == "campaign":
        if args.manifest is None:
            raise SystemExit("--manifest is required for "
                             "campaign mode")
        manifest = _load_manifest(args.manifest)
        (out_dir / "hosts").mkdir(exist_ok=True)
        if args.merge_only:
            summary = merge_campaign(out_dir, manifest)
            print(f"[oracle] merged {summary['n_hosts_completed']} "
                  f"hosts, {summary['n_oracle_trials']} oracle "
                  f"trials, {summary['oracle']['recovered']} "
                  f"recovered")
            return 0
        # resolve host-sectors from the manifest
        hosts = {}
        for tr in manifest["trials"]:
            key = (tr["tic"], tr["sector"])
            hosts.setdefault(key, []).append(tr)
        jobs = []
        missing = []
        for (tic, sector), trs in sorted(hosts.items()):
            path = cache / f"s{sector:04d}" / f"{tic}.fits"
            if not path.exists():
                missing.append((tic, sector))
                continue
            jobs.append({"tic": tic, "sector": sector,
                         "path": str(path), "trials": trs,
                         "out_dir": str(out_dir),
                         "workdir": str(out_dir / "injected"),
                         "manifest_sha": manifest["_sha256"],
                         "calibration": args.calibration,
                         "keep_fits": args.keep_fits})
        if args.tics:
            keep = {str(t) for t in args.tics}
            jobs = [j for j in jobs if j["tic"] in keep]
        jobs.sort(key=lambda j: (j["sector"], int(j["tic"])))
        if args.limit_hosts is not None:
            jobs = jobs[:args.limit_hosts]
        print(f"[oracle] campaign: {len(jobs)} host-sectors, "
              f"{sum(len(j['trials']) for j in jobs)} trials, "
              f"{len(missing)} missing FITS", flush=True)
        if args.dry_run:
            return 0
        (out_dir / "injected").mkdir(exist_ok=True)
        t0 = time.time()
        if args.workers <= 1:
            bs.set_calibration(args.calibration)
            results = [run_host_campaign(j) for j in jobs]
        else:
            from multiprocessing import Pool
            with Pool(args.workers, initializer=_init_worker,
                      initargs=(args.calibration,)) as pool:
                results = pool.map(run_host_campaign, jobs)
        done = sum(1 for r in results if r["status"] == "done")
        skipped = sum(1 for r in results
                      if r["status"] == "skipped")
        failures = [r for r in results if r["status"] == "error"]
        for r in failures:
            print(f"[oracle] ERROR TIC {r['tic']} s{r['sector']:04d}: "
                  f"{r.get('error')}", flush=True)
        summary = merge_campaign(out_dir, manifest)
        print(f"[oracle] done: {done} run, {skipped} skipped, "
              f"{len(failures)} failed, "
              f"{summary['n_hosts_completed']} hosts merged; "
              f"oracle {summary['oracle']['recovered']}/"
              f"{summary['n_oracle_trials']} recovered; "
              f"P4-1a bar {summary['p4_1a_bar']['bar_rescues']} "
              f"rescues; {time.time() - t0:.0f}s wall")
        return 0 if not failures else 1

    if args.mode == "s97":
        if args.screen_hits is None:
            raise SystemExit("--screen-hits is required for s97 mode")
        (out_dir / "chunks").mkdir(exist_ok=True)
        if args.merge_only:
            summary = merge_s97(out_dir)
            print(f"[oracle] s97 merged {summary['n_stars']} stars")
            return 0
        rows = [json.loads(line) for line in
                Path(args.screen_hits).read_text().splitlines()
                if line.strip()]
        # pre-veto survivor set = survivors + the 500 cluster-demoted
        pre = [r for r in rows
               if r["status"] == "survivor"
               or r.get("disposition")
               == "DEMOTED_SECTOR_EPOCH_CLUSTER"]
        # P4-2: the veto's clustering input is the v3-tier
        # survivor set — survivors PLUS the TWO-COMBINED-demoted
        # rows (gate_reason FAILED_TWO_COMBINED, still in hits).
        # Without them, borderline clusters shrink below the >20
        # bar and their tier-A members escape the target set
        # (the fixed S97 run: 8 clusters / 34 tier-A without
        # them, 10 / 48 with them — the veto's own numbers).
        # TWO-COMBINED rows are clustering input only, never
        # targets (they are already demoted).
        cluster_input = pre + [r for r in rows
                               if r.get("gate_reason")
                               == bs.GATE_REASON_TWO_COMBINED]
        from bulk.replay_matrix import sector_epoch_cluster_tics
        clustered, clusters = sector_epoch_cluster_tics(cluster_input)
        sizes = sorted((len(c) for c in clusters), reverse=True)
        print(f"[oracle] s97 clusters: {len(clusters)} clusters "
              f">= 21, sizes {sizes[:8]}, total clustered "
              f"{len(clustered)}", flush=True)
        by_tic = {r["tic"]: r for r in pre}
        targets = [by_tic[t] for c in clusters for t in c
                   if t in by_tic and by_tic[t]["tier"] == "A"]
        print(f"[oracle] s97 Tier-A mega-cluster members: "
              f"{len(targets)}", flush=True)
        if args.dry_run:
            return 0
        chunk_size = 250
        chunks = [targets[i:i + chunk_size]
                  for i in range(0, len(targets), chunk_size)]
        jobs = [{"chunk_id": i,
                 "rows": ch,
                 "cache": str(cache),
                 "out_path": str(out_dir / "chunks"
                                 / f"chunk_{i:03d}.json")}
                for i, ch in enumerate(chunks)]
        t0 = time.time()
        if args.workers <= 1:
            bs.set_calibration(args.calibration)
            results = [run_s97_chunk(j) for j in jobs]
        else:
            from multiprocessing import Pool
            with Pool(args.workers, initializer=_init_worker,
                      initargs=(args.calibration,)) as pool:
                results = pool.map(run_s97_chunk, jobs)
        done = sum(1 for r in results if r["status"] == "done")
        skipped = sum(1 for r in results
                      if r["status"] == "skipped")
        summary = merge_s97(out_dir)
        print(f"[oracle] s97 done: {done} chunks run, {skipped} "
              f"skipped, {summary['n_stars']} stars merged; "
              f"{time.time() - t0:.0f}s wall")
        return 0

    if args.mode == "phase2":
        if args.manifest is None:
            raise SystemExit("--manifest is required for phase2 mode")
        manifest = _load_manifest(args.manifest)
        sector = args.phase2_sector
        if args.spans_file is not None:
            spans = [tuple(s) for s in
                     json.loads(Path(args.spans_file).read_text())]
            print(f"[oracle] phase2: spans from "
                  f"{args.spans_file}: {len(spans)} spans, "
                  f"sector {sector}", flush=True)
        else:
            if args.phase1_dir is None:
                raise SystemExit("--phase1-dir is required for "
                                 "phase2 mode without --spans-file")
            p1_dir = Path(args.phase1_dir)
            spans = _derive_phase2_spans(p1_dir, out_dir)
            if spans is None:
                return 0
        if args.dry_run:
            return 0
        (out_dir / "hosts").mkdir(exist_ok=True)
        (out_dir / "injected").mkdir(exist_ok=True)
        hosts = {}
        for tr in manifest["trials"]:
            if (tr["group"] == "depth_148"
                    and tr["sector"] == sector):
                hosts.setdefault((tr["tic"], sector), []).append(tr)
        jobs = []
        for (tic, sec), trs in sorted(hosts.items()):
            path = cache / f"s{sec:04d}" / f"{tic}.fits"
            if not path.exists():
                continue
            jobs.append({"tic": tic, "sector": sec,
                         "path": str(path), "trials": trs,
                         "out_dir": str(out_dir),
                         "workdir": str(out_dir / "injected"),
                         "calibration": args.calibration,
                         "spans": spans,
                         "keep_fits": args.keep_fits})
        print(f"[oracle] phase2: {len(jobs)} s{sector} depth hosts, "
              f"{sum(len(j['trials']) for j in jobs)} trials",
              flush=True)
        t0 = time.time()
        if args.workers <= 1:
            bs.set_calibration(args.calibration)
            results = [run_artifact_host(j) for j in jobs]
        else:
            from multiprocessing import Pool
            with Pool(args.workers, initializer=_init_worker,
                      initargs=(args.calibration,)) as pool:
                results = pool.map(run_artifact_host, jobs)
        done = sum(1 for r in results if r["status"] == "done")
        n_rec = sum(r.get("n_recovered", 0) for r in results
                    if r["status"] == "done")
        print(f"[oracle] phase2 done: {done} hosts, "
              f"{n_rec} artifact-recovered; "
              f"{time.time() - t0:.0f}s wall")
        return 0

    raise SystemExit(f"unknown mode {args.mode}")


if __name__ == "__main__":
    raise SystemExit(main())
