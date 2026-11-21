"""P4-3 driver: paired multi-sector campaign + null (Phase 4, item 4-3).

Build brief P4-3; PB-3 (3 sectors decided); PB-6 A9/A10/A2/A18.
Pre-registered in P43_PREREG.md (written BEFORE any P4-3
measurement) — the verdict rule in merge_campaign_p43 applies the
pre-registered acceptance as written.

Base pipeline (parent decision, from P4-1b evidence): K=3 (Arm A
prototype) ADOPTED, depth trigger DROPPED (co-mask on secondary
SNR >= 3 only), 25% cumulative duty-cycle cap (settled), NO
combined mask. Epoch rule frozen: |dT0| <= 0.5*D_inj.

Runtime-order law: pre-mask confirmed contaminants per sector ->
stitch (inverse-variance weighted, p43_stitch) -> K=3 on the
stitched curve. The stitch is REAL here (signal present across
sectors), not the identity.

Injection rule (pre-registered): the SAME planet is injected into
every stacked sector via the ABSOLUTE epoch_btjd
(injection_harness.inject_transit takes epoch_abs). NOT via
inject_trial's epoch_offset path (relative to the original sector's
t_min -- reusing it would shift the epoch by the t_min difference).
Each sector's injection is verified by folding the injection
multiplier at the intended ephemeris (inj_check).

Legs (paired, same manifest, same trials):
- single: the adopted pipeline (K=3 Arm A, depth-trigger dropped)
  on the trial's ORIGINAL sector only, via k3_run
  (run_host_campaign_k3 / run_host_null_k3). Must reproduce
  P4-1b Arm D's per-trial results EXACTLY -- validated in the
  merge against the P4-1b host files.
- stitched: this module (run_host_campaign_p43 /
  run_host_null_p43). Per sector: fresh pass 1 -> estimate ->
  pre-mask if a confirmed contaminant (depth > 1% OR survivor)
  -> stitch -> pass 2 -> pass 3 if eligible.

P4-3b frozen-seed fix (P43B_PREREG.md): P4-3 FAILED on
short-period regression because the per-sector pre-mask seeded
from each sector's FRESH pass-1 peak -- which, on an injected
curve, is the planet itself in 68% of trials. The fix seeds the
NON-ORIGINAL sectors' pre-masks from the FROZEN recorded period
(the contaminant), estimating the ephemeris per sector from that
seed, and masks only when the contaminant is confirmed present
in that sector (fold depth > 1% OR fold SNR >= 7.0). The original
sector keeps the fresh-peak seed (proven identical to the frozen
seed there); the null leg is unchanged. The seed choice lives in
_mask_seed_and_eligibility (pure, unit-tested); _process_sector
takes seed_mode="fresh"/"frozen" per sector.

P4-3c agreement-only rule (Phase 4.1, item 4.1-4;
PHASE41_PREREG.md section 2.4; behind the --agreement-only
flag): in NON-ORIGINAL sectors, mask ONLY when the fresh peak
agrees with the frozen record (the fresh rule: mask iff fresh
depth > 1% OR fresh status == survivor OR an EB flag -- the
ELIGFIX bypass, bulk_v6 only); mask NOTHING on disagreement.
This removes the frozen-seed mask path on disagreement -- the
P4-3b behavior that cost the 3 right165 trials (the frozen seed
was the planet there). Agreement is pre-registered: period
within 1% of the frozen record AND epoch within one transit
duration (section 0.4). The frozen record carries no epoch, so
the reference epoch is the original sector's fresh pass-1 t0
(fresh == frozen there -- P43B_RECORD section 7), threaded
through run_host_campaign_p43 (which processes the original
sector first when the flag is on). The original sector is
unchanged; the null leg is unchanged (the flag does not touch
run_host_null_p43 -- no trial record, no frozen seed there).
Host records written under the flag carry seed_fix "p43c"
(the resume discriminator), so P4-3b and P4-3c host files can
never resume each other.

P4-3 rule arm (--seed-mode fresh): the non-original sectors seed
from the FRESH pass-1 peak, as P4-3 did before the frozen-seed
fix -- no frozen seed anywhere. This arm exists to define the
P4-3c at-risk class on a fresh set (PHASE41_PREREG.md section
2.4: the class is the P4-3-rule recoveries with recorded period
= planet -- 5/272 on the frozen set, verified against the P4-3
and P4-3b host files). It is incompatible with --agreement-only
(the agreement test needs a frozen record to agree with). Host
records carry seed_fix "p43".

Null accounting is per ROW (PB-6 section 4): a host with both a
pass-2 and a pass-3 survivor contributes 2 rows. The stitched
null's pass-1 baseline is the stitched UNMASKED screen (the
pipeline's first search without the pre-mask); the A2-style bound
is final rows <= 1.25 x pass-1 rows.

Compute (A18, both readings, as P4-1b did): narrow = stitched
trial wall / single-sector trial wall (paired per trial);
production-fair = stitched per-star wall / bulk-screen per-star
wall (1.175 s/star, P4-1b section 6.3).

Offline on the Mac (cached FITS only). No S98 data is read at any
point. No new dependencies. No push / merge / PR -- the parent
does those.
"""

import argparse
import json
import math
import os
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import bulk_screen as bs  # noqa: E402
import injection_harness as ih  # noqa: E402
from bulk import k2_prototype as k2  # noqa: E402
from bulk import k3_prototype as k3  # noqa: E402
from bulk import k3_run  # noqa: E402
from bulk import oracle_run as orc  # noqa: E402
from bulk import p43_stitch as p43  # noqa: E402
from bulk.inject_campaign import check_recovery  # noqa: E402
from bulk.inject_real_s96 import load_real_fits  # noqa: E402
from bulk.inject_real_s96 import write_injected_fits  # noqa: E402

SECTORS = (95, 96, 97)
ARM = "no-depth-trigger"  # K=3 Arm A, depth trigger DROPPED (P4-1b)
DUTY_CAP = 0.25  # settled -- do not re-raise
# P4-3b frozen-seed fix (P43B_PREREG.md section 0.4): non-original
# sectors seed the pre-mask from the FROZEN recorded period, and
# the mask fires only when the contaminant is CONFIRMED present in
# that sector -- the frozen-seed fold depth > 1% (the frozen
# planet-like boundary, A23) OR the fold SNR >= 7.0 (adopting the
# frozen bulk SDE bar as the detection bar for the fixed-period
# fold; the fold tests ONE period, so its noise max over the
# phase x duration scan is ~4 sigma and SNR >= 7 is confident).
FROZEN_DEPTH_MIN_FRAC = 0.01
FROZEN_SNR_MIN = 7.0
# Resume discriminator (review 2026-11-18): the stitched host
# record carries this marker, and the resume check requires it --
# without it, running the fixed driver into the OLD P4-3 out-dir
# would silently skip all 34 hosts and re-report P4-3's result
# as P4-3b's. P4-3's host files lack the marker, so they are
# never resumed by the fixed driver.
SEED_FIX = "p43b"
# P4-3c (PHASE41_PREREG.md section 2.4): host records written
# under --agreement-only carry this marker instead, so P4-3b and
# P4-3c host files can never resume each other even if pointed
# at the same out-dir.
SEED_FIX_P43C = "p43c"
# P4-3 rule arm (--seed-mode fresh): host records carry this
# marker (the original P4-3 run predates the discriminator).
SEED_FIX_P43 = "p43"


def _seed_fix_for(seed_mode, agreement_only):
    """Resume-discriminator marker for a stitched run, from its
    rule: "p43" for the P4-3 rule arm (--seed-mode fresh), "p43c"
    for the P4-3c agreement-only rule, "p43b" for the P4-3b
    frozen-seed rule. Raises on an unknown seed mode and on the
    invalid combination (--agreement-only needs the frozen seed
    mode: the agreement test needs a frozen record to agree
    with)."""
    if seed_mode not in ("fresh", "frozen"):
        raise ValueError(
            f"unknown seed_mode {seed_mode!r} "
            "(expected 'fresh' or 'frozen')")
    if agreement_only and seed_mode != "frozen":
        raise ValueError(
            "--agreement-only requires the frozen seed mode "
            "(the agreement test needs a frozen record to agree "
            "with); got seed_mode 'fresh'")
    if seed_mode == "fresh":
        return SEED_FIX_P43
    return SEED_FIX_P43C if agreement_only else SEED_FIX
BOOTSTRAP_SEED = 20261117
BOOTSTRAP_REPS = 10000
BULK_PER_STAR_S = 1.175  # bulk-screen per-star wall (P4-1b section 6.3)
TRAPEZOID_MEAN = 0.85  # trapezoid (70% flat + 15% ramps) mean over D


def _sector_fits_path(cache_dir, tic, sector):
    return Path(cache_dir) / f"s{sector:04d}" / f"{tic}.fits"


def _inj_check(t, f, f_inj, period, epoch, duration, depth_frac):
    """Verify the injection landed at the intended absolute epoch.

    Fold the injection multiplier (f_inj / f) at the intended
    (period, epoch, duration): a correctly-placed trapezoid shows
    depth ~0.85*depth_frac (70% flat + 15% ramps). A wrong epoch
    (e.g. epoch_offset reused across sectors) shows ~0. Returns
    (depth_measured, ok): ok iff within max(30% of depth, 0.002).
    The multiplier is deterministic, so this check has no noise.
    """
    with np.errstate(divide="ignore", invalid="ignore"):
        mult = np.where(f != 0, f_inj / np.where(f != 0, f, 1.0),
                        1.0)
    # Fold only finite cadences: a NaN flux cadence (QLP can carry
    # them) must not fail the check via _fold_depth's mean.
    finite = np.isfinite(mult)
    if finite.sum() < 20:
        return None, False
    depth, _n_in, _noise = bs._fold_depth(
        t[finite], mult[finite], period, epoch, duration)
    if depth is None or not np.isfinite(depth):
        return None, False
    expected = TRAPEZOID_MEAN * depth_frac
    # No absolute floor: the fold is the deterministic multiplier,
    # so a purely relative tolerance is justified -- and the old
    # 0.002 floor made the check vacuous for the 0.2% trials
    # (expected 0.0017 < floor), the exact error it exists to catch.
    tol = 0.3 * depth_frac
    return float(depth), bool(abs(depth - expected) <= tol)


def _epoch_agrees(p1, frozen_epoch_ref, p_rec):
    """Epoch clause of the P4-3c agreement test (PHASE41_PREREG.md
    section 2.4): the fresh peak's epoch within ONE transit
    duration of the frozen record's epoch (tol_frac=1.0 -- the
    section 0.4 tolerance, NOT the frozen 0.5x epoch rule for
    recovery). p1 is the fresh pass-1 subset (t0_btjd /
    duration_hours); frozen_epoch_ref is the frozen record's epoch
    (BTJD), reconstructed as the original sector's fresh pass-1
    t0; p_rec is the frozen recorded period (the wrap period).

    Returns (agrees, reason, delta_d): agrees False with reason
    "unavailable" when any input is missing (fail closed -- an
    untestable epoch is not an agreement), "disagree" when the
    wrapped epoch difference exceeds one transit duration, None
    when they agree. delta_d is the wrapped epoch difference in
    days (None when unavailable).
    """
    t0_fresh = p1.get("t0_btjd")
    dur_h = p1.get("duration_hours")
    if frozen_epoch_ref is None or t0_fresh is None or dur_h is None:
        return False, "unavailable", None
    delta = k2.epoch_delta(t0_fresh, frozen_epoch_ref, p_rec)
    if delta is None:
        return False, "unavailable", None
    if k2.epoch_match(delta, dur_h / 24.0, tol_frac=1.0):
        return True, None, float(delta)
    return False, "disagree", float(delta)


def _mask_seed_and_eligibility(t_p, f_p, trial, p1, seed_mode,
                               agreement_only=False,
                               frozen_epoch_ref=None):
    """Choose the pre-mask seed + eligibility for one sector.

    Pure decision logic (no I/O), so it is unit-testable without a
    BLS screen. t_p, f_p are the PREPROCESSED arrays; trial is the
    manifest trial (carrying the frozen `recorded` period); p1 is
    the fresh pass-1 subset (period_days / depth_percent / status);
    seed_mode is "fresh" (original sector) or "frozen"
    (non-original sector, P4-3b fix).

    Returns a dict with seed_period, seed_source ("fresh" /
    "frozen" / "frozen-agree" / "fresh-fallback" /
    "agree-only-skip"), seed_agreement ("agree" / "disagree" /
    "disagree-epoch" / "no-fresh-peak" / "n/a"),
    seed_fallback_reason (or None), ephemeris (or None when no
    seed exists), secondary (or None), eligible (bool), reason
    (stable string), depth_for_mask (the recorded_depth_pct for
    build_k2_mask), and epoch_delta_d (the wrapped epoch
    difference, or None unless the P4-3c epoch test ran).

    Fresh path (P4-3 rule + ELIGFIX flag bypass, E1-E3): seed =
    the fresh pass-1 peak; eligible iff fresh depth > 1% OR
    fresh status == "survivor" OR the fresh record carries an
    EB-family flag (the bypass, active only when the mask gate
    is enabled). The shared predicate lives in k2_prototype
    (mask_eligibility); the null leg calls the same function.

    Frozen path (P43B_PREREG sections 0.4 + 0.4a): seed = the
    FROZEN recorded period; the ephemeris is estimated per sector
    from that seed; eligible iff the contaminant is confirmed
    present in THIS sector -- fold depth > 1% OR fold SNR >= 7.0.
    The depth passed to build_k2_mask is the frozen recorded depth
    (mirroring k2_run). The frozen seed is used ONLY where the
    fresh peak is misleading -- where it DISAGREES with the frozen
    record (> 1%, the match tolerance) or is absent (the
    agreement gate, section 0.4a: the recorded period is the
    PLANET, not a contaminant, for 163/272 trials, so masking it
    unconditionally would mask the planet). Where the fresh peak
    AGREES with the frozen record, the two seeds target the same
    signal and P4-3's fresh rule applies (seed_source
    "frozen-agree"). If no recorded period exists, fall back to
    the fresh peak (P4-3 behavior) and record it.

    Agreement-only path (P4-3c, PHASE41_PREREG section 2.4;
    agreement_only=True, non-original sectors only -- the
    original sector is unchanged): mask ONLY when the fresh peak
    agrees with the frozen record -- period within 1% AND epoch
    within one transit duration of the frozen record's epoch
    (frozen_epoch_ref, the original sector's fresh pass-1 t0);
    mask NOTHING on disagreement. The frozen-seed mask path is
    removed entirely: on disagreement (period, epoch, no fresh
    peak, or no recorded period) the sector is returned unmasked
    (seed_source "agree-only-skip", eligible False, ephemeris
    None) so the fresh peak -- the strongest signal, usually the
    planet -- stays in the stitched curve for pass 2 to find.
    Where period AND epoch agree, P4-3's fresh rule applies
    unchanged (seed_source "frozen-agree").
    """
    if seed_mode not in ("fresh", "frozen"):
        raise ValueError(
            f"unknown seed_mode {seed_mode!r} "
            "(expected 'fresh' or 'frozen')")
    p_rec = (trial.get("recorded") or {}).get("period_days")
    p1_p = p1.get("period_days")
    # Agreement gate (P43B_PREREG section 0.4a).
    agreement = "n/a"
    use_frozen = seed_mode == "frozen" and p_rec is not None
    if use_frozen and p1_p is not None:
        if abs(p1_p - float(p_rec)) / float(p_rec) < 0.01:
            use_frozen = False
            agreement = "agree"
        else:
            agreement = "disagree"
    elif use_frozen:
        agreement = "no-fresh-peak"
    # P4-3c agreement-only rule (PHASE41_PREREG section 2.4):
    # mask ONLY on agreement (period within 1% AND epoch within
    # one transit duration); mask NOTHING on disagreement. The
    # frozen-seed path is removed entirely -- on any disagreement
    # the sector is returned unmasked (no ephemeris estimated,
    # nothing to build a mask from). A period agreement that
    # fails the epoch clause is a disagreement (seed_agreement
    # "disagree-epoch"), as is an untestable epoch (fail closed).
    # With no recorded period there is nothing to agree with, so
    # nothing is masked either (the literal rule; unreachable in
    # both P4-3c manifests -- all trials carry a recorded period).
    epoch_delta_d = None
    if agreement_only and seed_mode == "frozen":
        skip_reason = None
        if p_rec is None:
            skip_reason = "agree-only-no-record"
        elif agreement == "agree":
            epoch_ok, epoch_why, epoch_delta_d = _epoch_agrees(
                p1, frozen_epoch_ref, float(p_rec))
            if not epoch_ok:
                agreement = "disagree-epoch"
                skip_reason = ("agree-only-epoch-unavailable"
                               if epoch_why == "unavailable"
                               else "agree-only-epoch-disagree")
        elif agreement == "disagree":
            skip_reason = "agree-only-disagree"
        else:  # no-fresh-peak
            skip_reason = "agree-only-no-fresh-peak"
        if skip_reason is not None:
            return {"seed_period": p1_p,
                    "seed_source": "agree-only-skip",
                    "seed_agreement": agreement,
                    "seed_fallback_reason": None,
                    "ephemeris": None, "secondary": None,
                    "eligible": False, "reason": skip_reason,
                    "depth_for_mask": p1.get("depth_percent"),
                    "epoch_delta_d": epoch_delta_d}
        # Period AND epoch agree: fall through to the frozen-agree
        # fresh rule below (use_frozen is already False).
    if use_frozen:
        seed_period = float(p_rec)
        seed_source = "frozen"
        fallback_reason = None
        depth_for_mask = (trial.get("recorded") or {}).get(
            "depth_percent")
    else:
        seed_period = p1_p
        if seed_mode == "frozen" and p_rec is None:
            seed_source = "fresh-fallback"
            fallback_reason = "no-recorded-period"
        elif seed_mode == "frozen" and agreement == "agree":
            seed_source = "frozen-agree"
            fallback_reason = None
        else:
            seed_source = "fresh"
            fallback_reason = None
        depth_for_mask = p1.get("depth_percent")
    out = {"seed_period": seed_period, "seed_source": seed_source,
           "seed_agreement": agreement,
           "seed_fallback_reason": fallback_reason,
           "ephemeris": None, "secondary": None,
           "eligible": False,
           "reason": ("no-pass1-period" if seed_source == "fresh"
                      else "no-seed-period"),
           "depth_for_mask": depth_for_mask,
           "epoch_delta_d": epoch_delta_d}
    if seed_period is None:
        return out
    ephemeris = k2.estimate_ephemeris(t_p, f_p, seed_period)
    secondary = k2.scan_secondary(
        t_p, f_p, ephemeris["period_ref_d"],
        ephemeris["t0_est_btjd"], ephemeris["duration_est_d"])
    out["ephemeris"] = ephemeris
    out["secondary"] = secondary
    if seed_source == "frozen":
        depth_est = ephemeris.get("depth_est_frac")
        snr_est = ephemeris.get("snr_est")
        eligible = bool(
            (depth_est is not None
             and depth_est > FROZEN_DEPTH_MIN_FRAC)
            or (snr_est is not None and snr_est >= FROZEN_SNR_MIN))
        out["eligible"] = eligible
        out["reason"] = ("frozen-contaminant" if eligible
                         else "frozen-not-confirmed")
    else:
        # ELIGFIX-20261121 (E1-E2): the fresh rule is the shared
        # predicate -- an EB flag bypasses the pre-filter so the
        # gate sees the record. eligible_via is written only
        # when the bypass fires (the auditable diff).
        eligible, eligible_via = k2.mask_eligibility(p1)
        out["eligible"] = eligible
        out["reason"] = ("confirmed-contaminant" if eligible
                         else "not-confirmed")
        if eligible_via == "eb-flag":
            out["eligible_via"] = eligible_via
    return out


def _process_sector(t, f, q, fcol, trial, base, tic, sector,
                    keep_fits, seed_mode="fresh",
                    agreement_only=False, frozen_epoch_ref=None):
    """One sector of one trial: inject, fresh pass 1, estimate,
    pre-mask if a confirmed contaminant.

    Returns a dict with the per-sector record + the arrays the
    stitch needs (t, f_inj, q, keep, sigma, ephemeris, mstats).
    The injection uses the ABSOLUTE epoch_btjd (pre-registered).

    seed_mode (P43B_PREREG sections 0.4 + 0.4a): "fresh" (the
    original sector -- the fresh pass-1 peak seeds the mask,
    unchanged from P4-3) or "frozen" (a non-original sector --
    the FROZEN recorded period seeds the mask, so the mask targets
    the contaminant instead of the planet, but ONLY where the
    fresh peak disagrees with the frozen record -- the agreement
    gate: where they agree, P4-3's fresh rule applies). The fresh
    pass 1 still runs in every sector (validation + diagnostics);
    it simply no longer seeds the mask in non-original sectors
    where it disagrees with the frozen record.

    agreement_only (P4-3c, PHASE41_PREREG section 2.4): in a
    non-original sector, mask ONLY when the fresh peak agrees
    with the frozen record (period within 1% AND epoch within
    one transit duration of frozen_epoch_ref -- the original
    sector's fresh pass-1 t0); mask NOTHING on disagreement. No
    effect on the original sector (seed_mode "fresh"); the null
    leg does not call this function.
    """
    period = trial["period_d"]
    epoch = trial["epoch_btjd"]
    duration = trial["duration_d"]
    depth = trial["depth_frac"]
    f_inj, _dur = ih.inject_transit(t, f, depth, period, epoch)
    inj_depth, inj_ok = _inj_check(t, f, f_inj, period, epoch,
                                   duration, depth)
    inj_path = str(base) + f"_s{sector:04d}.fits"
    write_injected_fits(inj_path, t, f_inj, q, fcol)
    t_p1 = time.time()
    p1 = k3_run._screen(inj_path, tic, sector)
    sec_p1 = round(time.time() - t_p1, 2)
    if not keep_fits:
        os.remove(inj_path)
    t_p, f_p, sigma = p43.preprocess_sector(t, f_inj, q)
    rec = {"sector": sector, "fcol": fcol,
           # The epoch actually passed to inject_transit, minus the
           # manifest epoch -- a measurement, not a hardcoded 0.0.
           "inject_epoch_delta_d": float(epoch - trial["epoch_btjd"]),
           "inj_check_depth": inj_depth, "inj_check_ok": inj_ok,
           "pass1": orc._subset(p1), "sigma": sigma,
           "seconds_pass1": sec_p1, "n_cadences": int(len(t))}
    t_e = time.time()
    seed = _mask_seed_and_eligibility(t_p, f_p, trial, p1,
                                      seed_mode,
                                      agreement_only=agreement_only,
                                      frozen_epoch_ref=(
                                          frozen_epoch_ref))
    sec_est = round(time.time() - t_e, 2)
    rec["seed_source"] = seed["seed_source"]
    rec["seed_period_d"] = seed["seed_period"]
    rec["seed_agreement"] = seed["seed_agreement"]
    if agreement_only:
        # P4-3c audit fields (flag-on runs only, so flag-off
        # records stay byte-identical to P4-3b's).
        rec["seed_epoch_delta_d"] = seed.get("epoch_delta_d")
        rec["frozen_epoch_ref_btjd"] = frozen_epoch_ref
    if seed.get("seed_fallback_reason"):
        rec["seed_fallback_reason"] = seed["seed_fallback_reason"]
    if seed["ephemeris"] is None:
        rec.update({"ephemeris": None, "secondary_scan": None,
                    "eligible": False, "reason": seed["reason"],
                    "k2_mask": None})
        return rec, (t, f_inj, q, np.ones(len(t), dtype=bool), sigma)
    ephemeris = seed["ephemeris"]
    secondary = seed["secondary"]
    rec["ephemeris"] = ephemeris
    rec["secondary_scan"] = {"phase": secondary[0],
                             "depth_frac": secondary[1],
                             "snr": secondary[2]}
    rec["seconds_est"] = sec_est
    rec["eligible"] = seed["eligible"]
    rec["reason"] = seed["reason"]
    if seed.get("eligible_via") is not None:
        rec["eligible_via"] = seed["eligible_via"]
    if not seed["eligible"]:
        rec["k2_mask"] = None
        return rec, (t, f_inj, q, np.ones(len(t), dtype=bool), sigma)
    # Mask gate (bulk_v6, design section 5.2): the mask applies
    # only when the signal being masked is contaminant-like.
    # The gate record is the FROZEN recorded row on the frozen
    # path (the mask targets the frozen contaminant) and the
    # fresh pass-1 record on the fresh path. Gated off: the
    # sector joins the stitch unmasked, like a not-eligible
    # sector (k2_mask None), with mask_gated_off recorded.
    gate_record = (trial.get("recorded")
                   if seed["seed_source"] == "frozen" else p1)
    if not k2.mask_gate_allows(gate_record):
        rec["k2_mask"] = None
        rec["mask_gated_off"] = True
        return rec, (t, f_inj, q, np.ones(len(t), dtype=bool), sigma)
    keep, mstats = k2.build_k2_mask(
        t, f_inj, q, ephemeris, seed["depth_for_mask"],
        secondary=secondary, duty_cap=DUTY_CAP, depth_trigger=False)
    rec["k2_mask"] = mstats
    return rec, (t, f_inj, q, keep, sigma)


def _mask_seed_diagnostic(t, f_inj, q, trial, fresh_rec, keep_fresh):
    """Mask-seed diagnostic (original sector only, pre-registered):
    build a second mask seeded from the FROZEN recorded period and
    compare it with the fresh-peak mask. The paired comparison
    rests on the seeds agreeing; if they diverge materially the
    comparison is flagged. Returns {period_diff_pct, duty_fresh,
    duty_recorded, jaccard_dropped} (jaccard None when either mask
    dropped nothing). keep_fresh is the fresh-peak mask (bool
    array over the sector's cadences, or None if unmasked).
    """
    p_rec = (trial.get("recorded") or {}).get("period_days")
    p_fresh = (fresh_rec.get("pass1") or {}).get("period_days")
    if p_rec is None or p_fresh is None:
        return {"period_diff_pct": None, "duty_fresh": None,
                "duty_recorded": None, "jaccard_dropped": None,
                "note": "missing-period"}
    if fresh_rec.get("k2_mask") is None:
        # No fresh mask was built (peak not a confirmed
        # contaminant) -- there is nothing to compare the
        # recorded-period mask against; building one would
        # manufacture a disagreement (jaccard 0.0) out of an
        # eligibility difference, not a seed difference.
        return {"period_diff_pct": float(
            100.0 * abs(p_fresh - p_rec) / p_rec),
            "duty_fresh": None, "duty_recorded": None,
            "jaccard_dropped": None, "note": "fresh-not-masked"}
    t_p, f_p = orc.preprocess_arrays(t, f_inj, q)
    eph_rec = k2.estimate_ephemeris(t_p, f_p, p_rec)
    sec_rec = k2.scan_secondary(
        t_p, f_p, eph_rec["period_ref_d"], eph_rec["t0_est_btjd"],
        eph_rec["duration_est_d"])
    depth_pct = (fresh_rec.get("pass1") or {}).get("depth_percent")
    keep_rec, mstats_rec = k2.build_k2_mask(
        t, f_inj, q, eph_rec, depth_pct, secondary=sec_rec,
        duty_cap=DUTY_CAP, depth_trigger=False)
    out = {"period_diff_pct": float(
        100.0 * abs(p_fresh - p_rec) / p_rec),
           "duty_fresh": (fresh_rec.get("k2_mask") or {}).get(
               "duty_cycle"),
           "duty_recorded": mstats_rec.get("duty_cycle"),
           "jaccard_dropped": None}
    if keep_fresh is not None:
        drop_f = ~keep_fresh
        drop_r = ~keep_rec
        union = int((drop_f | drop_r).sum())
        if union > 0:
            out["jaccard_dropped"] = float(
                int((drop_f & drop_r).sum()) / union)
    return out


def _contaminant_dict(ephemeris, mstats):
    """One masked contaminant, in k3.pass3_veto's dict shape."""
    return {"period_d": ephemeris["period_ref_d"],
            "t0_btjd": ephemeris["t0_est_btjd"],
            "mask_half_width_d": mstats["mask_half_width_d"],
            "comask_phase": mstats["secondary_phase"]}


def _stitched_pass2(t_s, f_s, q_s, fcol, base, tic, sector,
                    keep_fits):
    """Screen the stitched curve (pass 2). Returns the subset."""
    path = str(base) + "_stitched.fits"
    write_injected_fits(path, t_s, f_s, q_s, fcol)
    p2 = k3_run._screen(path, tic, sector)
    if not keep_fits:
        os.remove(path)
    return orc._subset(p2), p2


def _stitched_pass3(t_s, f_s, q_s, fcol, base, tic, sector, keep,
                    p2, contaminants, trial, keep_fits,
                    flagged=None):
    """Pass 3 on the stitched curve: estimate the pass-2 peak's
    ephemeris from the stitched masked curve, build the mask,
    union with the stitched keep mask, cap at 25%, screen.

    contaminants is the list of per-sector masked-contaminant
    dicts (k3.pass3_veto shape); the pass-3 verdict vetoes against
    them PLUS the pass-2 peak. period/epoch/duration_inj are the
    injected planet (ground truth for the verdict only -- never an
    input to the mask). `flagged` is orc.flagged_periods' output
    for the per-sector pass-1 records (F-2, bulk_v6): when given,
    a pass-3 row matching a flagged pass-1 signal re-raises the
    EB flags (and the demotion). Returns (eligibility, record).
    """
    veto2 = k3.pass3_veto(p2.get("period_days"), p2.get("t0_btjd"),
                          contaminants)
    elig, reason = k3.pass3_eligible(p2, veto2, False)
    out = {"eligible": bool(elig), "reason": reason,
           "veto_pass2": veto2}
    if not elig:
        return out, {"pass3": None, "p3_recovered": False,
                     "p3_genuine": False}
    t_p2, f_p2 = orc.preprocess_arrays(t_s[keep], f_s[keep],
                                       q_s[keep])
    eph2 = k2.estimate_ephemeris(t_p2, f_p2, p2.get("period_days"))
    sec2 = k2.scan_secondary(t_p2, f_p2, eph2["period_ref_d"],
                             eph2["t0_est_btjd"],
                             eph2["duration_est_d"])
    # k3_run seeds the cap from the mask-seed period (ephemeris1,
    # the pass-1 contaminant); the stitched analog is the pass-2
    # peak, which seeds the pass-3 mask. Numerically 0.25 for this
    # arm either way.
    cap = k3.trial_cap(ARM, p2.get("period_days"))
    keep3_raw, mstats3 = k2.build_k2_mask(
        t_s, f_s, q_s, eph2, p2.get("depth_percent"), secondary=sec2,
        duty_cap=1.0, depth_trigger=False)
    keep_union, duty_u, stopped_u = k3.apply_union_cap(
        t_s, f_s, q_s, keep, keep3_raw, cap)
    mstats3["union_duty_cycle"] = float(duty_u)
    mstats3["duty_cap"] = float(cap)
    mstats3["stopped"] = bool(stopped_u)
    mstats3["stop_reason"] = ("STOPPED_MASK_DUTY_CYCLE"
                              if stopped_u else None)
    mstats3["stopped_pass"] = 3 if stopped_u else None
    rec = {"k3_ephemeris": eph2,
           "k3_secondary_scan": {"phase": sec2[0],
                                 "depth_frac": sec2[1],
                                 "snr": sec2[2]},
           "k3_mask": mstats3}
    if stopped_u:
        rec.update({"pass3": None, "p3_recovered": False,
                    "p3_genuine": False})
        return out, rec
    path = str(base) + "_stitched_k3.fits"
    write_injected_fits(path, t_s[keep_union], f_s[keep_union],
                        q_s[keep_union], fcol)
    p3 = k3_run._screen(path, tic, sector)
    if not keep_fits:
        os.remove(path)
    # F-2 (bulk_v6): as in k3_run._run_pass3 — re-raise a
    # flagged pass-1 signal's EB flags on the pass-3 row
    # before the subset and the recovery verdict.
    carried3 = (orc.carried_eb_flags(p3.get("period_days"),
                                     flagged)
                if flagged else [])
    if carried3:
        orc.apply_eb_carry(p3, carried3)
    rec["pass3"] = orc._subset(p3)
    if carried3:
        rec["pass3"]["flags_carried_from"] = (
            orc.FLAGS_CARRIED_FROM_PASS1)
    veto3 = k3.pass3_veto(
        p3.get("period_days"), p3.get("t0_btjd"),
        contaminants + [_contaminant_dict(eph2, mstats3)])
    rec["alias_veto_pass3"] = veto3
    if trial.get("period_d") is None:
        # Null leg: no injected planet, so no recovery/epoch
        # verdict -- the caller uses the pass-3 screen record only
        # (same guard as k3_run._run_pass3).
        rec["pass3_match"] = None
        rec["m6_pass3_before_veto"] = None
        rec["p3_recovered"] = False
        rec["epoch_delta_d_pass3"] = None
        rec["epoch_delta_over_d_pass3"] = None
        rec["epoch_match_pass3"] = False
        rec["p3_genuine"] = False
        return out, rec
    rec["pass3_match"] = orc.period_match_class(
        p3.get("period_days"), trial["period_d"])
    m6_3 = bool(check_recovery(p3, trial["period_d"]))
    rec["m6_pass3_before_veto"] = m6_3
    rec["p3_recovered"] = bool(m6_3 and not veto3["vetoed"])
    delta3 = k2.epoch_delta(p3.get("t0_btjd"), trial["epoch_btjd"],
                            trial["period_d"])
    rec["epoch_delta_d_pass3"] = delta3
    rec["epoch_delta_over_d_pass3"] = (
        abs(delta3) / trial["duration_d"]
        if delta3 is not None else None)
    rec["epoch_match_pass3"] = bool(k2.epoch_match(
        delta3, trial["duration_d"]))
    rec["p3_genuine"] = bool(rec["p3_recovered"]
                             and rec["epoch_match_pass3"])
    return out, rec


def run_host_campaign_p43(job):
    """One TIC: inject each trial into all of the host's sectors
    (absolute epoch), per-sector fresh pass 1 + pre-mask, stitch,
    pass 2, pass 3 where eligible, verdicts. Mirrors
    k3_run.run_host_campaign_k3's record shape where the legs
    share a field (final_recovered / final_genuine / pass2_match /
    epoch_delta_d), so the merge can join the legs per trial.
    """
    tic = job["tic"]
    sectors = job["sectors"]
    paths = job["paths"]
    out_dir = Path(job["out_dir"])
    workdir = Path(job["workdir"])
    manifest_sha = job["manifest_sha"]
    calibration = job["calibration"]
    keep_fits = job.get("keep_fits", False)
    # P4-3c (PHASE41_PREREG section 2.4): the agreement-only rule
    # behind the --agreement-only flag. Host records written under
    # the flag carry seed_fix "p43c", so P4-3b and P4-3c host
    # files can never resume each other. seed_mode selects the
    # non-original sector seed: "frozen" (P4-3b, default) or
    # "fresh" (the P4-3 rule arm -- no frozen seed anywhere).
    agreement_only = bool(job.get("agreement_only", False))
    seed_mode = job.get("seed_mode", "frozen")
    seed_fix = _seed_fix_for(seed_mode, agreement_only)
    # PIPE50-9c (4.1-3): record the stitched pass-1 screen per
    # trial (the unmasked stitch screen). Flag-gated (the
    # P4-3c precedent): flag-off records stay byte-identical to
    # P4-3b's. The flag is part of the resume check below, so a
    # host file written without pass-1 is never resumed by a
    # run that needs it (and vice versa). bulk_v6 default
    # (PIPE50-9c adoption, design section 5.4): when the job
    # does not set the key, the PROFILE decides
    # (record_pass1_stitched: true under bulk_v6, absent/False
    # under frozen profiles) — the driver flag overrides by
    # setting the job key.
    record_pass1 = bool(job.get(
        "record_pass1_stitched",
        getattr(bs, "RECORD_PASS1_STITCHED", False)))
    out_path = out_dir / "hosts-p43" / f"{tic}_p43.json"
    if out_path.exists():
        try:
            prev = json.loads(out_path.read_text())
        except ValueError:
            prev = {}
        if (prev.get("complete") is True
                and prev.get("manifest_sha") == manifest_sha
                and prev.get("arm") == ARM
                and prev.get("calibration") == calibration
                and prev.get("seed_fix") == seed_fix
                and prev.get("mes_gate") == job.get("mes_gate")
                and prev.get("pass1_stitched", False)
                == record_pass1
                and not any("error" in tr
                            for tr in prev.get("trials", []))):
            return {"status": "skipped", "tic": tic}
    t_start = time.time()
    sector_data = {}
    for sec in sectors:
        try:
            t, f, q, fcol, _meta = load_real_fits(paths[str(sec)])
        except Exception as exc:  # noqa: BLE001
            return {"status": "error", "tic": tic,
                    "error": f"load_real_fits s{sec}: {exc}"}
        sector_data[sec] = {"t": t, "f": f, "q": q, "fcol": fcol,
                            "crowdsap": p43.read_crowdsap(
                                paths[str(sec)])}
    results = []
    for tr in job["trials"]:
        t_tr = time.time()
        r = {"tic": tic, "sector": tr["sector"],
             "trial_id": tr["trial_id"], "group": tr["group"],
             "period_d": tr["period_d"],
             "epoch_btjd": tr["epoch_btjd"],
             "duration_d": tr["duration_d"],
             "depth_frac": tr["depth_frac"],
             "n_events_expected": tr.get("n_events_expected")}
        try:
            base = workdir / f"{tic}_{tr['trial_id']}"
            per_sector = {}
            sector_inj = {}  # sec -> (t, f_inj, q, keep)
            masked = []  # (sector, t, f_inj, q, keep) for the stitch
            sigmas = {}
            contaminants = []
            any_masked = False  # D-MASK-STITCHED (bulk_v6)
            sec_p1 = sec_est = 0.0
            # P4-3c: the agreement test's epoch clause needs the
            # frozen record's epoch, reconstructed as the
            # ORIGINAL sector's fresh pass-1 t0 (fresh == frozen
            # there -- P43B_RECORD section 7). Process the
            # original sector first when the flag is on, so its
            # epoch is available when the non-original sectors
            # decide. (The stitch time-sorts -- p43_stitch
            # stitch_weighted -- so processing order does not
            # affect the stitched curve; the per-sector record is
            # keyed by sector; the flag-off path keeps the
            # original order, unchanged.) The original sector is
            # 95 or 96 by manifest construction, never 97.
            orig_sec = tr["sector"]
            ordered = ([orig_sec] + [s for s in sectors
                                     if s != orig_sec]
                       if agreement_only else list(sectors))
            frozen_epoch_ref = None
            for sec in ordered:
                sd = sector_data[sec]
                # P4-3b fix (P43B_PREREG section 0.4): the original
                # sector keeps the fresh-peak seed (proven identical
                # to the frozen seed there); non-original sectors
                # seed from the FROZEN recorded period, so the
                # pre-mask targets the contaminant, not the planet.
                rec, (t_s_, f_i, q_s_, keep, sig) = _process_sector(
                    sd["t"], sd["f"], sd["q"], sd["fcol"], tr, base,
                    tic, sec, keep_fits,
                    seed_mode=("fresh" if sec == tr["sector"]
                               else seed_mode),
                    agreement_only=agreement_only,
                    frozen_epoch_ref=frozen_epoch_ref)
                if sec == orig_sec:
                    frozen_epoch_ref = (rec.get("pass1") or {}).get(
                        "t0_btjd")
                rec["crowdsap"] = sd["crowdsap"]
                per_sector[sec] = rec
                sector_inj[sec] = (t_s_, f_i, q_s_, keep)
                sigmas[sec] = sig
                sec_p1 += rec.get("seconds_pass1", 0.0)
                sec_est += rec.get("seconds_est", 0.0)
                mstats = rec.get("k2_mask") or {}
                if mstats.get("stopped"):
                    # Sector excluded from the stitch (pre-registered).
                    continue
                if rec.get("k2_mask") is not None:
                    # A mask was built for this sector (not
                    # gated off, not ineligible).
                    any_masked = True
                masked.append({"sector": sec, "t": t_s_[keep],
                               "f": f_i[keep], "q": q_s_[keep],
                               "fcol": sd["fcol"],
                               "crowdsap": sd["crowdsap"]})
                if rec.get("eligible") and rec.get("ephemeris") \
                        and rec.get("k2_mask") is not None:
                    # A gated-off sector (k2_mask None) has no
                    # mask, hence no masked contaminant to veto
                    # against -- it must not contribute a
                    # contaminant entry. (M4-p43, 2026-11-20:
                    # the unguarded append crashed with KeyError
                    # 'mask_half_width_d' on gated-off sectors
                    # -- 187/272 stitched trials in the M4 run.)
                    contaminants.append(_contaminant_dict(
                        rec["ephemeris"], mstats))
            r["sectors"] = {str(k): _sector_record(v)
                            for k, v in per_sector.items()}
            r["inj_check_ok"] = all(
                v.get("inj_check_ok") is True
                for v in per_sector.values())
            # Stitched pass-1 screen (PIPE50-9c, flag-gated):
            # screen the UNMASKED stitch -- all sectors, full
            # arrays, no keep mask applied -- and record it per
            # trial. Mirrors the null leg's A2-style pass-1
            # baseline (run_host_null_p43 builds `unmasked`
            # the same way). A DIAGNOSTIC: it does not feed
            # pass 2/3 (which use the masked stitch) and does
            # not change any pipeline decision. It runs BEFORE
            # the all-sectors-stopped early-continue, so even
            # stopped trials get a pass-1 screen (the unmasked
            # data exists regardless of the masking). A distinct
            # base so the FITS does not collide with the masked
            # pass-2 file (_stitched.fits) when keep_fits is on.
            if record_pass1:
                t_p1s = time.time()
                unmasked = []
                for sec in sectors:
                    t_u, f_u, q_u, _k = sector_inj[sec]
                    unmasked.append(
                        {"sector": sec, "t": t_u, "f": f_u,
                         "q": q_u,
                         "fcol": sector_data[sec]["fcol"],
                         "crowdsap": sector_data[sec][
                             "crowdsap"]})
                t_u, f_u, q_u, _tr_u = p43.stitch_weighted(
                    unmasked, sigmas)
                base_u = (workdir
                          / f"{tic}_{tr['trial_id']}_unmasked")
                p1s, _p1s_raw = _stitched_pass2(
                    t_u, f_u, q_u, unmasked[0]["fcol"], base_u,
                    tic, tr["sector"], keep_fits)
                r["pass1"] = p1s
                delta1 = k2.epoch_delta(
                    p1s.get("t0_btjd"), tr["epoch_btjd"],
                    tr["period_d"])
                r["epoch_delta_over_d_pass1"] = (
                    abs(delta1) / tr["duration_d"]
                    if delta1 is not None else None)
                r["pass1_sectors"] = list(sectors)
                r["seconds_pass1_stitched"] = round(
                    time.time() - t_p1s, 2)
            # Mask-seed diagnostic (original sector only):
            # reuses the already-injected arrays + fresh keep mask
            # (no recomputation -- the mask is deterministic).
            orig = tr["sector"]
            if orig in per_sector and per_sector[orig].get(
                    "ephemeris") is not None:
                t_o, f_o, q_o, keep_o = sector_inj[orig]
                r["mask_seed_diagnostic"] = _mask_seed_diagnostic(
                    t_o, f_o, q_o, tr, per_sector[orig], keep_o)
            else:
                r["mask_seed_diagnostic"] = None
            if not masked:
                r.update({"stopped_pass": 2, "stitch": None,
                          "pass2": None, "pass2_match": None,
                          "alias_veto": None, "epoch_delta_d": None,
                          "epoch_match": False, "p2_recovered": False,
                          "p2_genuine": False,
                          "pass3_eligibility": {
                              "eligible": False,
                              "reason": "all-sectors-stopped"},
                          "pass3": None, "p3_recovered": False,
                          "p3_genuine": False,
                          "final_recovered": False,
                          "final_genuine": False,
                          "total_dropped_frac": None,
                          "sector_consistency": None})
                r["seconds"] = round(time.time() - t_tr, 2)
                results.append(r)
                continue
            t_s, f_s, q_s, tracking = p43.stitch_weighted(
                masked, sigmas)
            r["stitch"] = tracking
            r["excluded_sectors"] = sorted(
                set(sectors) - {m["sector"] for m in masked})
            bounds = [(m["sector"], float(np.min(m["t"])),
                       float(np.max(m["t"]))) for m in masked]
            t_p2s = time.time()
            # F-2 (bulk_v6): the flagged source for the
            # stitched leg is the PER-SECTOR pass-1 records
            # (always in scope; the stitched pass-1 exists
            # only when record_pass1 is on, so it is not a
            # source — per-sector only, same in both legs).
            flagged = orc.flagged_periods(
                [v.get("pass1") for v in per_sector.values()])
            # D-MASK-STITCHED (bulk_v6, design section 5.2): when
            # NO sector masked, the masked stitch IS the
            # unmasked stitch, so the stitched pass-2 screen
            # would return exactly the recorded stitched
            # pass-1 screen (same input, deterministic screen).
            # Carry it forward instead of re-screening; pass 3
            # does not run (nothing was masked). When the
            # stitched pass-1 was not recorded (record_pass1
            # off — frozen profiles), screen the unmasked
            # stitch as before (the same result, one extra
            # screen). The copy is shallow + a fresh flags
            # list, so the F-2 carry below cannot mutate the
            # stored pass-1 record.
            if (not any_masked and record_pass1
                    and r.get("pass1") is not None):
                p2 = dict(r["pass1"])
                p2["flags"] = list(p2.get("flags") or [])
                p2["carried_from"] = "pass1"
                carried_from_pass1 = True
            else:
                p2, _p2_raw = _stitched_pass2(
                    t_s, f_s, q_s, masked[0]["fcol"], base, tic,
                    orig, keep_fits)
                carried_from_pass1 = False
            # The stitched pass-2 record IS the subset
            # (_stitched_pass2 returns it), so the carry
            # lands on it directly — before the recovery
            # verdict and pass-3 eligibility, exactly as a
            # measured flag would.
            carried = orc.carried_eb_flags(
                p2.get("period_days"), flagged)
            if carried:
                orc.apply_eb_carry(p2, carried)
            sec_p2 = round(time.time() - t_p2s, 2)
            r["pass2"] = p2
            r["pass2_match"] = orc.period_match_class(
                p2.get("period_days"), tr["period_d"])
            veto2 = k3.pass3_veto(p2.get("period_days"),
                                  p2.get("t0_btjd"), contaminants)
            r["alias_veto"] = veto2
            m6 = bool(check_recovery(p2, tr["period_d"]))
            r["m6_before_veto"] = m6
            r["p2_recovered"] = bool(m6 and not veto2["vetoed"])
            delta = k2.epoch_delta(p2.get("t0_btjd"),
                                   tr["epoch_btjd"], tr["period_d"])
            r["epoch_delta_d"] = delta
            r["epoch_delta_over_d"] = (
                abs(delta) / tr["duration_d"]
                if delta is not None else None)
            r["epoch_match"] = bool(k2.epoch_match(
                delta, tr["duration_d"]))
            r["p2_genuine"] = bool(r["p2_recovered"]
                                   and r["epoch_match"])
            # Stitched keep mask (for the pass-3 union + diagnostics).
            keep_stitched = np.ones(len(t_s), dtype=bool)
            # (t_s is the stitched curve; the per-sector keeps are
            # already applied. The union mask is built on it below.)
            if carried_from_pass1:
                # No mask (D-MASK-STITCHED): pass 3 does not
                # run — nothing was masked, so there is
                # nothing to look behind.
                r["pass3_eligibility"] = {
                    "eligible": False,
                    "reason": "no-mask-carry-forward"}
                r["pass3"] = None
                r["p3_recovered"] = False
                r["p3_genuine"] = False
                r["sector_consistency"] = _consistency_at(
                    t_s, f_s, q_s, bounds, p2)
            elif r["p2_recovered"]:
                r["pass3_eligibility"] = {
                    "eligible": False, "reason": "pass2-rescued"}
                r["pass3"] = None
                r["p3_recovered"] = False
                r["p3_genuine"] = False
                r["sector_consistency"] = _consistency_at(
                    t_s, f_s, q_s, bounds, p2)
            else:
                t_p3s = time.time()
                elig, rec3 = _stitched_pass3(
                    t_s, f_s, q_s, masked[0]["fcol"], base, tic,
                    orig, keep_stitched, p2, contaminants, tr,
                    keep_fits, flagged=flagged)
                sec_p3 = round(time.time() - t_p3s, 2)
                r["pass3_eligibility"] = elig
                r.update(rec3)
                r["seconds_pass3"] = sec_p3
                if rec3.get("pass3") is not None:
                    r["sector_consistency"] = _consistency_at(
                        t_s, f_s, q_s, bounds, rec3["pass3"])
                else:
                    r["sector_consistency"] = _consistency_at(
                        t_s, f_s, q_s, bounds, p2)
            r["final_recovered"] = bool(
                r["p2_recovered"] or r["p3_recovered"])
            r["final_genuine"] = bool(
                r["p2_genuine"] or r["p3_genuine"])
            # Total dropped fraction (review 2026-11-18): the
            # pass-3 union cap binds 25% of the STITCHED curve's
            # valid cadences (pre-registration section 0.4 as
            # written); the per-sector pre-mask drops are already
            # deleted before stitching, so the total dropped
            # fraction of the original 3-sector data can exceed
            # 25%. Recorded per trial (relative to raw cadences);
            # the ruling and the distribution go in the record.
            n_orig = sum(v.get("n_cadences", 0)
                         for v in per_sector.values())
            n_stitched = (r.get("stitch") or {}).get(
                "n_cadences_total")
            union_duty = 0.0
            if r.get("pass3") is not None:
                union_duty = ((r.get("k3_mask") or {}).get(
                    "union_duty_cycle") or 0.0)
            r["total_dropped_frac"] = (
                float(1.0 - (n_stitched * (1.0 - union_duty))
                      / n_orig)
                if n_orig and n_stitched else None)
            r["seconds_pass1"] = round(sec_p1, 2)
            r["seconds_est"] = round(sec_est, 2)
            r["seconds_pass2"] = sec_p2
        except Exception as exc:  # noqa: BLE001
            r["error"] = f"{type(exc).__name__}: {exc}"
        r["seconds"] = round(time.time() - t_tr, 2)
        results.append(r)
    rec = {"tic": tic, "sectors": list(sectors), "complete": True,
           "manifest_sha": manifest_sha, "calibration": calibration,
           "arm": ARM, "seed_fix": seed_fix,
           "mes_gate": job.get("mes_gate"),
           "agreement_only": agreement_only,
           "seed_mode": seed_mode,
           "n_trials": len(results),
           "seconds": round(time.time() - t_start, 1),
           "trials": results}
    if record_pass1:
        # Flag-on runs only, so flag-off records stay
        # byte-identical to P4-3b's (the P4-3c precedent).
        rec["pass1_stitched"] = True
    tmp = out_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(_json_safe(rec)))
    tmp.replace(out_path)
    n_fin = sum(1 for r in results
                if r.get("final_recovered") is True)
    return {"status": "done", "tic": tic, "n_trials": len(results),
            "n_final_recovered": n_fin}


def _json_safe(obj):
    """Recursively replace non-finite floats (inf/nan) with None so
    host files are strict JSON. k2.estimate_ephemeris can return
    float("inf") for refine_snr_gain; the ephemeris dict is stored
    verbatim in host records, so without this json.dumps emits
    non-strict Infinity (pre-existing in k2/k3_run; none seen in
    the smoke files, but fail closed)."""
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    return obj


def _sector_record(rec):
    """Per-sector record without the arrays (JSON-safe)."""
    return {k: v for k, v in rec.items()}


def _consistency_at(t_s, f_s, q_s, bounds, found):
    """Per-sector transit-consistency record at a found ephemeris
    (pre-registered diagnostic). Runs on the preprocessed stitched
    curve."""
    period = found.get("period_days")
    t0 = found.get("t0_btjd")
    duration_h = found.get("duration_hours")
    if period is None or t0 is None or duration_h is None:
        return None
    duration = duration_h / 24.0
    t_p, f_p = orc.preprocess_arrays(t_s, f_s, q_s)
    return p43.sector_consistency(t_p, f_p, q_s, bounds, period,
                                  t0, duration)


def run_host_null_p43(job):
    """One TIC, UNINJECTED, stitched pipeline: per-sector fresh
    pass 1 -> pre-mask -> stitch (masked) -> pass 2 -> pass 3
    where eligible. The A2-style pass-1 baseline is the stitched
    UNMASKED screen (the pipeline's first search without the
    pre-mask). Per-pass null accounting, per ROW.
    """
    tic = job["tic"]
    sectors = job["sectors"]
    paths = job["paths"]
    out_dir = Path(job["out_dir"])
    workdir = Path(job["workdir"])
    manifest_sha = job["manifest_sha"]
    calibration = job["calibration"]
    keep_fits = job.get("keep_fits", False)
    out_path = out_dir / "null-p43" / f"{tic}_p43.json"
    if out_path.exists():
        try:
            prev = json.loads(out_path.read_text())
        except ValueError:
            prev = {}
        if (prev.get("complete") is True
                and prev.get("manifest_sha") == manifest_sha
                and prev.get("arm") == ARM
                and prev.get("calibration") == calibration
                and prev.get("mes_gate") == job.get("mes_gate")
                and "error" not in prev):
            return {"status": "skipped", "tic": tic}
    t_start = time.time()
    r = {"tic": tic, "sectors": list(sectors), "arm": ARM,
         "mes_gate": job.get("mes_gate")}
    try:
        base = workdir / f"{tic}_null"
        per_sector = {}
        masked = []
        unmasked = []
        sigmas = {}
        contaminants = []
        any_masked = False  # D-MASK-STITCHED (bulk_v6)
        for sec in sectors:
            t, f, q, fcol, _meta = load_real_fits(paths[str(sec)])
            raw_path = str(base) + f"_s{sec:04d}.fits"
            write_injected_fits(raw_path, t, f, q, fcol)
            p1 = k3_run._screen(raw_path, tic, sec)
            if not keep_fits:
                os.remove(raw_path)
            t_p, f_p = orc.preprocess_arrays(t, f, q)
            sigma = p43.sector_sigma(t_p, f_p)
            sigmas[sec] = sigma
            rec = {"sector": sec, "fcol": fcol, "sigma": sigma,
                   "pass1": orc._subset(p1),
                   "crowdsap": p43.read_crowdsap(paths[str(sec)]),
                   "n_cadences": int(len(t))}
            p1_p = p1.get("period_days")
            if p1_p is None:
                rec.update({"ephemeris": None,
                            "secondary_scan": None,
                            "eligible": False,
                            "reason": "no-pass1-period",
                            "k2_mask": None})
                per_sector[sec] = rec
                masked.append({"sector": sec, "t": t, "f": f, "q": q,
                               "fcol": fcol,
                               "crowdsap": rec["crowdsap"]})
                unmasked.append({"sector": sec, "t": t, "f": f,
                                 "q": q, "fcol": fcol,
                                 "crowdsap": rec["crowdsap"]})
                continue
            ephemeris = k2.estimate_ephemeris(t_p, f_p, p1_p)
            secondary = k2.scan_secondary(
                t_p, f_p, ephemeris["period_ref_d"],
                ephemeris["t0_est_btjd"],
                ephemeris["duration_est_d"])
            rec["ephemeris"] = ephemeris
            rec["secondary_scan"] = {"phase": secondary[0],
                                     "depth_frac": secondary[1],
                                     "snr": secondary[2]}
            depth_pct = p1.get("depth_percent")
            # ELIGFIX-20261121 (E1-E2): the shared predicate --
            # an EB flag bypasses the pre-filter so the gate
            # sees the record. eligible_via is written only
            # when the bypass fires (the auditable diff).
            eligible, eligible_via = k2.mask_eligibility(p1)
            rec["eligible"] = eligible
            rec["reason"] = ("confirmed-contaminant" if eligible
                             else "not-confirmed")
            if eligible_via == "eb-flag":
                rec["eligible_via"] = eligible_via
            if not eligible:
                rec["k2_mask"] = None
                keep = np.ones(len(t), dtype=bool)
            elif not k2.mask_gate_allows(p1):
                # Mask gate (bulk_v6, design section 5.2): the
                # fresh pass-1 signal is planet-like (shallow,
                # unflagged) — no mask. The sector joins the
                # stitch unmasked, like a not-eligible sector.
                rec["k2_mask"] = None
                rec["mask_gated_off"] = True
                keep = np.ones(len(t), dtype=bool)
            else:
                keep, mstats = k2.build_k2_mask(
                    t, f, q, ephemeris, depth_pct, secondary=secondary,
                    duty_cap=DUTY_CAP, depth_trigger=False)
                rec["k2_mask"] = mstats
                if not mstats.get("stopped"):
                    contaminants.append(_contaminant_dict(
                        ephemeris, mstats))
            per_sector[sec] = rec
            unmasked.append({"sector": sec, "t": t, "f": f, "q": q,
                             "fcol": fcol,
                             "crowdsap": rec["crowdsap"]})
            if (rec.get("k2_mask") or {}).get("stopped"):
                continue  # sector excluded from the stitch
            if rec.get("k2_mask") is not None:
                any_masked = True
            masked.append({"sector": sec, "t": t[keep], "f": f[keep],
                           "q": q[keep], "fcol": fcol,
                           "crowdsap": rec["crowdsap"]})
        r["sectors"] = {str(k): v for k, v in per_sector.items()}
        # Pass-1 baseline: the stitched UNMASKED screen. A
        # distinct base so the FITS does not collide with the
        # masked pass-2 file (_stitched.fits) when keep_fits is on.
        t_u, f_u, q_u, tr_u = p43.stitch_weighted(unmasked, sigmas)
        base_u = workdir / f"{tic}_null_unmasked"
        p1s, _ = _stitched_pass2(t_u, f_u, q_u, unmasked[0]["fcol"],
                                 base_u, tic, sectors[0], keep_fits)
        r["pass1"] = p1s
        r["pass1_survivor"] = bool(p1s.get("status") == "survivor")
        r["stitch_unmasked"] = tr_u
        # Full pipeline: the stitched MASKED curve.
        r["pass2_survivor"] = False
        r["pass3_survivor"] = False
        # N6 (M2NULL-20261121, RATIFIED): the stitched null leg
        # never wrote final_survivor (k3_run's null leg does) —
        # the M2 scorer's flag-based D2st host count read 0.00.
        # Same semantics as k3_run: pass-2 OR pass-3 survivor.
        r["final_survivor"] = False
        if not masked:
            r.update({"pass2": None, "pass3": None,
                      "note": "all-sectors-stopped",
                      "final_rows": 0})
        else:
            t_s, f_s, q_s, tracking = p43.stitch_weighted(
                masked, sigmas)
            r["stitch"] = tracking
            r["excluded_sectors"] = sorted(
                set(sectors) - {m["sector"] for m in masked})
            # F-2 (bulk_v6): as in the campaign leg — the
            # flagged source is the per-sector pass-1
            # records. (The stitched pass-1 baseline above
            # is always recorded in this leg, but it is not
            # a source — per-sector only, same in both legs.)
            flagged = orc.flagged_periods(
                [v.get("pass1") for v in per_sector.values()])
            # D-MASK-STITCHED (bulk_v6, design section 5.2): as
            # in the campaign leg — when no sector masked, the
            # masked stitch IS the unmasked stitch, so carry
            # the pass-1 baseline forward instead of
            # re-screening; pass 3 does not run. The baseline
            # is always recorded in this leg, so no
            # record_pass1 guard is needed.
            if not any_masked:
                p2 = dict(r["pass1"])
                p2["flags"] = list(p2.get("flags") or [])
                p2["carried_from"] = "pass1"
                carried_from_pass1 = True
            else:
                p2, _ = _stitched_pass2(t_s, f_s, q_s,
                                        masked[0]["fcol"], base, tic,
                                        sectors[0], keep_fits)
                carried_from_pass1 = False
            carried = orc.carried_eb_flags(
                p2.get("period_days"), flagged)
            if carried:
                orc.apply_eb_carry(p2, carried)
            r["pass2"] = p2
            r["pass2_survivor"] = bool(
                p2.get("status") == "survivor")
            veto2 = k3.pass3_veto(p2.get("period_days"),
                                  p2.get("t0_btjd"), contaminants)
            trial_none = {"period_d": None, "epoch_btjd": None,
                          "duration_d": None}
            if carried_from_pass1:
                # No mask: pass 3 does not run (nothing was
                # masked, so there is nothing to look behind).
                # The no-short-circuit rule below does not
                # apply — this is a design-mandated skip, not
                # a survivor short-circuit.
                r["pass3_eligibility"] = {
                    "eligible": False,
                    "reason": "no-mask-carry-forward"}
                r["pass3"] = None
                r["pass3_survivor"] = False
            else:
                # No survivor short-circuit here (unlike the campaign
                # leg): k3_run's null leg runs pass 3 whenever eligible,
                # because a pass-2 survivor is a candidate the K=3
                # search looks behind. Skipping it would undercount
                # null rows and bias the A2 bound toward PASS.
                elig, rec3 = _stitched_pass3(
                    t_s, f_s, q_s, masked[0]["fcol"], base, tic,
                    sectors[0], np.ones(len(t_s), dtype=bool), p2,
                    contaminants, trial_none, keep_fits,
                    flagged=flagged)
                r["pass3_eligibility"] = elig
                r["k3_mask"] = rec3.get("k3_mask")
                r["k3_ephemeris"] = rec3.get("k3_ephemeris")
                r["pass3"] = rec3.get("pass3")
                r["pass3_survivor"] = bool(
                    (rec3.get("pass3") or {}).get("status")
                    == "survivor")
            r["final_rows"] = (int(r["pass2_survivor"])
                               + int(r["pass3_survivor"]))
            # N6: same OR as k3_run's null leg — and identical
            # to bool(final_rows), the rule the BP-1 extract
            # builder (nulldiag_extract.py) used to synthesise
            # this key for stitched records.
            r["final_survivor"] = bool(
                r["pass2_survivor"] or r["pass3_survivor"])
    except Exception as exc:  # noqa: BLE001
        r["error"] = f"{type(exc).__name__}: {exc}"
    r["complete"] = True
    r["manifest_sha"] = manifest_sha
    r["calibration"] = calibration
    r["seconds"] = round(time.time() - t_start, 1)
    tmp = out_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(_json_safe(r)))
    tmp.replace(out_path)
    return {"status": "done", "tic": tic,
            "pass1_survivor": r.get("pass1_survivor"),
            "final_rows": r.get("final_rows")}


def _bootstrap_paired_gain(host_gains, n_rep=BOOTSTRAP_REPS,
                           seed=BOOTSTRAP_SEED):
    """Host-level bootstrap 95% CI on a PAIRED gain (stitched -
    single per host). host_gains is a list of per-host gains
    (ints). Same method as oracle_run._bootstrap_host_ci (10,000
    reps, seed 20261117), applied to the gain instead of a count.
    """
    rng = np.random.default_rng(seed)
    n_hosts = len(host_gains)
    if n_hosts == 0:
        return None
    g = np.array(host_gains, dtype=float)
    vals = np.empty(n_rep)
    for i in range(n_rep):
        idx = rng.integers(0, n_hosts, n_hosts)
        vals[i] = g[idx].sum()
    return {"lo": float(np.percentile(vals, 2.5)),
            "hi": float(np.percentile(vals, 97.5)),
            "n_rep": n_rep, "seed": seed, "n_hosts": n_hosts}


def _cell_stats(paired, cell_fn, all_hosts):
    """Per-cell paired gain stats. paired is a list of per-trial
    dicts with keys tic, single (bool), stitched (bool).
    all_hosts is the FULL host list (the 34 TICs): the bootstrap
    resamples all of them (pre-registration section 0.7), and a
    host with no trials in the cell contributes gain 0. Resampling
    only the cell's hosts would overstate the uncertainty.
    Returns {n_trials, single, stitched, gain, ci, loho_min,
    loho_all_positive, top_host_gain, top_host_share, n_hosts}.
    cell_fn(trial) -> bool.
    """
    cell = [t for t in paired if cell_fn(t)]
    hosts = {h: {"n": 0, "single": 0, "stitched": 0}
             for h in all_hosts}
    for t in cell:
        h = hosts.setdefault(t["tic"], {"n": 0, "single": 0,
                                        "stitched": 0})
        h["n"] += 1
        h["single"] += int(t["single"] is True)
        h["stitched"] += int(t["stitched"] is True)
    gains = [h["stitched"] - h["single"] for h in hosts.values()]
    total = int(sum(gains))
    ci = _bootstrap_paired_gain(gains)
    loho = {}
    for tic, h in hosts.items():
        loho[tic] = total - (h["stitched"] - h["single"])
    top = max(gains) if gains else 0
    return {"n_trials": len(cell),
            "single": int(sum(h["single"] for h in hosts.values())),
            "stitched": int(sum(h["stitched"]
                                for h in hosts.values())),
            "gain": total, "ci": ci,
            "loho_min": min(loho.values()) if loho else None,
            "loho_all_positive": bool(
                all(v > 0 for v in loho.values())) if loho else False,
            "top_host_gain": int(top),
            "top_host_share": (float(top) / total
                               if total > 0 else None),
            "n_hosts": len(hosts)}


def _dropped_frac_stats(stitched):
    """Distribution of total_dropped_frac over stitched trials
    (finding 6 diagnostic): the fraction of the original 3-sector
    data dropped by the pre-mask + pass-3 mask combined. The cap
    binds 25% of the STITCHED curve (pre-registration section 0.4
    as written), so the total can exceed 25% -- reported here."""
    vals = sorted(tr["total_dropped_frac"]
                  for tr in stitched.values()
                  if tr.get("total_dropped_frac") is not None)
    if not vals:
        return {"n": 0, "median": None, "p90": None, "max": None}
    return {"n": len(vals),
            "median": float(np.median(vals)),
            "p90": float(np.percentile(vals, 90)),
            "max": float(np.max(vals))}


def merge_campaign_p43(out_dir, manifest, p41b_dir=None,
                       prereg="P43_PREREG.md section 0.7"):
    """Aggregate the paired legs into p43_summary.json and apply
    the PRE-REGISTERED verdict rule (P43_PREREG.md section 0.7, or
    the prereg named by `prereg` -- the P4-3b fix applies the
    identical rule from P43B_PREREG.md section 0.7).

    Reads the single leg (k3_run host files, out_dir/hosts/) and
    the stitched leg (out_dir/hosts-p43/), joins per trial on
    (tic, sector, trial_id), and computes per-cell gains, the
    69-count, regression checks, host-concentration, A18 (both
    readings), and the PASS/FAIL verdict. If p41b_dir is given,
    validates the single leg against P4-1b Arm D's host files
    (per-trial exact reproduction); a mismatch is recorded and
    blocks the verdict (the paired baseline is invalid).
    """
    out_dir = Path(out_dir)
    # Cell definitions come from the FROZEN MANIFEST (pre-registered
    # section 0.2) -- the single-leg records do not carry
    # n_events_expected (k3_run never stored it), so reading it
    # from the leg would silently empty the low-event cell.
    man_trials = {(tr["tic"], tr["sector"], tr["trial_id"]): tr
                  for tr in manifest.get("trials", [])}
    single = {}
    for p in sorted((out_dir / "hosts").glob("*.json")):
        try:
            rec = json.loads(p.read_text())
        except ValueError:
            continue
        if rec.get("complete") is True and rec.get("arm") == ARM:
            for tr in rec.get("trials", []):
                single[(tr["tic"], tr["sector"],
                        tr["trial_id"])] = tr
    stitched = {}
    for p in sorted((out_dir / "hosts-p43").glob("*.json")):
        try:
            rec = json.loads(p.read_text())
        except ValueError:
            continue
        if rec.get("complete") is True and rec.get("arm") == ARM:
            for tr in rec.get("trials", []):
                stitched[(tr["tic"], tr["sector"],
                          tr["trial_id"])] = tr
    keys = sorted(set(single) & set(stitched))
    not_in_manifest = [k for k in keys if k not in man_trials]
    all_hosts = sorted({tr["tic"] for tr in manifest["trials"]})
    n_error_trials = (
        sum(1 for tr in single.values() if "error" in tr)
        + sum(1 for tr in stitched.values() if "error" in tr))
    paired = []
    for k in keys:
        s_tr = single[k]
        t_tr = stitched[k]
        m_tr = man_trials.get(k) or {}
        paired.append({
            "tic": k[0], "sector": k[1], "trial_id": k[2],
            "group": m_tr.get("group", s_tr.get("group")),
            "period_d": m_tr.get("period_d", s_tr.get("period_d")),
            "n_events_expected": m_tr.get("n_events_expected"),
            "single": bool(s_tr.get("final_recovered") is True),
            "stitched": bool(t_tr.get("final_recovered") is True),
            "single_genuine": bool(
                s_tr.get("final_genuine") is True),
            "stitched_genuine": bool(
                t_tr.get("final_genuine") is True),
            "single_seconds": s_tr.get("seconds"),
            "stitched_seconds": t_tr.get("seconds"),
            "single_pass1_period": (s_tr.get("pass1") or {}).get(
                "period_days"),
            "stitched_orig_pass1_period": (
                (t_tr.get("sectors") or {}).get(
                    str(k[1]), {}).get("pass1") or {}).get(
                        "period_days"),
            "inj_check_ok": t_tr.get("inj_check_ok"),
        })
    # --- validation: single leg vs P4-1b Arm D (if given) ---
    repro = {"checked": False, "n_compared": 0, "n_match": 0,
             "mismatches": []}
    if p41b_dir is not None:
        p41b = {}
        for p in sorted(Path(p41b_dir).glob("*.json")):
            try:
                rec = json.loads(p.read_text())
            except ValueError:
                continue
            if rec.get("complete") is True:
                for tr in rec.get("trials", []):
                    p41b[(tr["tic"], tr["sector"],
                          tr["trial_id"])] = tr
        repro["checked"] = True
        for k in keys:
            ref = p41b.get(k)
            if ref is None:
                continue
            repro["n_compared"] += 1
            s_tr = single[k]
            p1_s = (s_tr.get("pass1") or {}).get("period_days")
            p1_r = (ref.get("pass1") or {}).get("period_days")
            p1_ok = (p1_s is not None and p1_r is not None
                     and abs(p1_s - p1_r) <= 0.01 * p1_r)
            ok = (bool(s_tr.get("final_recovered") is True)
                  == bool(ref.get("final_recovered") is True)
                  and bool(s_tr.get("final_genuine") is True)
                  == bool(ref.get("final_genuine") is True)
                  and bool(s_tr.get("k2_recovered") is True)
                  == bool(ref.get("k2_recovered") is True)
                  and p1_ok)
            if ok:
                repro["n_match"] += 1
            else:
                repro["mismatches"].append(
                    {"tic": k[0], "sector": k[1],
                     "trial_id": k[2],
                     "single_final": s_tr.get("final_recovered"),
                     "p41b_final": ref.get("final_recovered"),
                     "single_genuine": s_tr.get("final_genuine"),
                     "p41b_genuine": ref.get("final_genuine"),
                     "single_k2": s_tr.get("k2_recovered"),
                     "p41b_k2": ref.get("k2_recovered"),
                     "single_pass1_period": p1_s,
                     "p41b_pass1_period": p1_r})
        repro["all_match"] = (repro["n_compared"] > 0
                              and repro["n_match"]
                              == repro["n_compared"])
    # --- validation: fresh pass 1 vs the FROZEN P3-10 record
    # (section 0.8: 1% period / 2% SDE). k3_run records it per
    # trial as pass1_repro.ok on the single leg; aggregate it.
    p1_frozen_ok = sum(
        1 for tr in single.values()
        if (tr.get("pass1_repro") or {}).get("ok") is True)
    p1_frozen_compared = sum(
        1 for tr in single.values() if tr.get("pass1_repro"))
    # --- diagnostic: fresh-vs-fresh seed agreement (section 0.6 --
    # the stitched leg's ORIGINAL sector seeds from its fresh
    # pass-1 peak (P4-3b: non-original sectors seed from the
    # frozen recorded period), the single leg from the frozen
    # record). NOT the section 0.8 validation; named as such.
    seed_matches = 0
    seed_compared = 0
    for t in paired:
        a = t["single_pass1_period"]
        b = t["stitched_orig_pass1_period"]
        if a is not None and b is not None:
            seed_compared += 1
            if abs(a - b) <= 0.01 * a:
                seed_matches += 1
    # --- cells (pre-registered definitions) ---
    cells = {
        "long_period": _cell_stats(
            paired, lambda t: 10.0 <= (t["period_d"] or 0) <= 15.0,
            all_hosts),
        "low_event": _cell_stats(
            paired, lambda t: t["n_events_expected"] in (2, 3),
            all_hosts),
        "short_period": _cell_stats(
            paired, lambda t: (t["period_d"] or 99) < 5.0,
            all_hosts),
        "recovered_412": _cell_stats(
            paired, lambda t: t["group"] == "recovered_412",
            all_hosts),
        "right165_69": _cell_stats(
            paired, lambda t: t["group"] == "right165_69",
            all_hosts),
    }
    # --- A18 compute (both readings) ---
    ratios = [t["stitched_seconds"] / t["single_seconds"]
              for t in paired
              if t["single_seconds"] and t["stitched_seconds"]
              and t["single_seconds"] > 0]
    stitched_secs = [t["stitched_seconds"] for t in paired
                     if t["stitched_seconds"] is not None]
    a18 = {"narrow": {
        "median": float(np.median(ratios)) if ratios else None,
        "p10": float(np.percentile(ratios, 10)) if ratios else None,
        "p90": float(np.percentile(ratios, 90)) if ratios else None,
        "max": float(np.max(ratios)) if ratios else None,
        "n": len(ratios)},
           "production_fair": {
        "median_stitched_trial_s": (
            float(np.median(stitched_secs))
            if stitched_secs else None),
        "bulk_per_star_s": BULK_PER_STAR_S,
        "ratio": (float(np.median(stitched_secs))
                  / BULK_PER_STAR_S if stitched_secs else None)},
           "note": ("Narrow: stitched trial wall / single-sector "
                    "trial wall (paired per trial). Production-fair: "
                    "median stitched trial wall / bulk-screen "
                    "per-star wall (1.175 s/star, P4-1b section "
                    "6.3). A18's baseline is undefined (P4-1b "
                    "finding) -- both readings reported, flagged, "
                    "not part of the verdict.")}
    # --- verdict (pre-registered section 0.7) ---
    lp = cells["long_period"]
    le = cells["low_event"]
    sp = cells["short_period"]
    r412 = cells["recovered_412"]
    # --- null element (section 0.7 #5): the stitched null bound
    # lives in p43_null_summary.json (same out_dir). The verdict is
    # PASS iff ALL hold, so a missing null summary blocks it.
    null_summary = None
    null_path = out_dir / "p43_null_summary.json"
    if null_path.exists():
        try:
            null_summary = json.loads(null_path.read_text())
        except ValueError:
            null_summary = None
    null_bound_ok = bool(
        null_summary is not None
        and (null_summary.get("stitched") or {}).get(
            "bound_verdict") == "PASS")
    checks = {}
    checks["long_period_gain_positive"] = lp["gain"] > 0
    checks["long_period_ci_excludes_zero"] = bool(
        lp["ci"] is not None and lp["ci"]["lo"] > 0)
    checks["low_event_gain_positive"] = le["gain"] > 0
    checks["low_event_ci_excludes_zero"] = bool(
        le["ci"] is not None and le["ci"]["lo"] > 0)
    checks["short_period_no_regression"] = (
        sp["stitched"] >= sp["single"])
    checks["recovered_412_no_regression"] = (
        r412["stitched"] >= r412["single"])
    checks["host_concentration_loho"] = bool(
        lp["loho_all_positive"] and le["loho_all_positive"])
    checks["host_concentration_top_share"] = bool(
        (lp["top_host_share"] is None or lp["top_host_share"] < 0.5)
        and (le["top_host_share"] is None
             or le["top_host_share"] < 0.5))
    # Fail-closed: an unchecked reproduction is not a passed one.
    checks["single_leg_repro"] = bool(
        repro["checked"] and repro.get("all_match") is True)
    checks["inj_checks_ok"] = all(
        t["inj_check_ok"] is True for t in paired)
    # Section 0.8: all 272 trials run, 0 errors, nothing missing.
    checks["completeness"] = bool(
        len(paired) == len(manifest.get("trials", []))
        and len(set(single) - set(stitched)) == 0
        and len(set(stitched) - set(single)) == 0
        and len(not_in_manifest) == 0)
    checks["no_errors"] = (n_error_trials == 0)
    checks["null_bound"] = null_bound_ok
    verdict = "PASS" if all(checks.values()) else "FAIL"
    failing = [k for k, v in checks.items() if not v]
    summary = {
        "tool": "p43_run", "mode": "campaign", "arm": ARM,
        "manifest_sha": manifest.get("_sha256"),
        "n_trials_paired": len(paired),
        "n_not_in_manifest": len(not_in_manifest),
        "n_single_only": len(set(single) - set(stitched)),
        "n_stitched_only": len(set(stitched) - set(single)),
        "cells": cells,
        "right165_testable": cells["right165_69"]["n_trials"],
        "right165_stitched_rescued": cells["right165_69"]["stitched"],
        "right165_single_rescued": cells["right165_69"]["single"],
        "single_leg_repro_vs_p41b": repro,
        "pass1_repro_vs_frozen": {
            "n_compared": p1_frozen_compared,
            "n_ok": p1_frozen_ok,
            "note": ("Single leg's pass1_repro.ok vs the frozen "
                     "P3-10 record (1% period / 2% SDE, section "
                     "0.8).")},
        "seed_agreement": {"n_compared": seed_compared,
                           "n_match": seed_matches,
                           "note": ("Fresh-vs-fresh pass-1 period "
                                    "agreement (section 0.6 "
                                    "diagnostic, not the section "
                                    "0.8 validation).")},
        "total_dropped_frac": _dropped_frac_stats(stitched),
        "null": ({"present": True,
                  "stitched_bound_verdict":
                      (null_summary.get("stitched") or {}).get(
                          "bound_verdict"),
                  "stitched_final_rows":
                      (null_summary.get("stitched") or {}).get(
                          "final_rows"),
                  "stitched_bound_rows":
                      (null_summary.get("stitched") or {}).get(
                          "bound_rows")}
                 if null_summary is not None
                 else {"present": False,
                       "note": ("Null leg not run yet -- the "
                                "verdict cannot PASS until it is.")}),
        "a18": a18,
        "checks": checks,
        "failing_checks": failing,
        "verdict": verdict,
        "note": ("Verdict rule pre-registered in " + prereg
                 + "; A18 is reported, not part of the "
                 "verdict."),
    }
    (out_dir / "p43_summary.json").write_text(
        json.dumps(_json_safe(summary), indent=2))
    return summary


def merge_null_p43(out_dir):
    """Aggregate the paired null legs into p43_null_summary.json.
    Stitched pass-1 baseline = the stitched UNMASKED screen;
    bound = ceil(1.25 x pass-1 rows) (A2-style, per ROW)."""
    out_dir = Path(out_dir)
    stitched = []
    for p in sorted((out_dir / "null-p43").glob("*.json")):
        try:
            rec = json.loads(p.read_text())
        except ValueError:
            continue
        if rec.get("complete") is True and rec.get("arm") == ARM:
            stitched.append(rec)
    single = []
    for p in sorted((out_dir / "null_hosts").glob("*.json")):
        try:
            rec = json.loads(p.read_text())
        except ValueError:
            continue
        if rec.get("complete") is True and rec.get("arm") == ARM:
            single.append(rec)

    def _agg(recs):
        n = len(recs)
        p1 = sum(1 for r in recs if r.get("pass1_survivor") is True)
        p2 = sum(1 for r in recs if r.get("pass2_survivor") is True)
        p3 = sum(1 for r in recs if r.get("pass3_survivor") is True)
        final = p2 + p3
        bound = math.ceil(1.25 * p1) if p1 else 0
        return {"n_hosts": n, "pass1_survivors": p1,
                "pass2_survivors": p2, "pass3_survivors": p3,
                "final_rows": final, "bound_rows": bound,
                "bound_verdict": ("PASS" if final <= bound
                                  else "FAIL"),
                "pass1_per_1000": (1000.0 * p1 / n if n else None),
                "final_per_1000": (1000.0 * final / n
                                   if n else None),
                "delta_per_1000": (1000.0 * (final - p1) / n
                                   if n else None)}

    s = _agg(stitched)
    s1 = _agg(single)
    summary = {"tool": "p43_run", "mode": "null", "arm": ARM,
               "stitched": s, "single": s1,
               "note": ("Stitched pass-1 baseline = the stitched "
                        "UNMASKED screen (pre-registered). Small-n "
                        "caveat: 34 hosts. Bound = ceil(1.25 x "
                        "pass-1 rows), per ROW (PB-6 section 4).")}
    (out_dir / "p43_null_summary.json").write_text(
        json.dumps(_json_safe(summary), indent=2))
    return summary


def _build_jobs(manifest, cache_dir, out_dir, workdir_p43,
                workdir_single, keep_fits, calibration, tics=None,
                limit_hosts=None, agreement_only=False,
                seed_mode="frozen", mes_gate=None):
    """Build the paired job lists (single + stitched) for the
    manifest's TICs. Returns (single_jobs, stitched_jobs,
    missing). A missing sector FITS skips the TIC ENTIRELY (no
    single job either): a single-only host would silently
    shrink the paired set, and the completeness check would
    then block the verdict. calibration is the CLI value
    (args.calibration), not the manifest's -- the workers are
    initialized with it, so the records must agree.
    agreement_only (P4-3c) and seed_mode (P4-3 rule arm) are
    carried on the stitched jobs only -- the single leg and the
    null leg never read them (the null leg is unchanged by the
    flag: no trial record, no frozen seed).
    Per-host sectors (4.1-10 / 4.1-3): when the manifest
    carries sectors_by_host {tic: [sectors]}, each host's
    stitched stack uses ITS list (the 4.1-10 hosts have 2/3/4
    sectors in nine combos; the P4-3 default SECTORS would skip
    every non-3-sector host). Otherwise SECTORS (95/96/97) is
    used, exactly as before -- P4-3/BP-1 manifests are
    unaffected. The trial's original sector must be in the
    host's list. mes_gate (None = profile bar) is carried on
    every job: the leg functions record it and refuse to resume
    a host file written at a different gate (tiers differ)."""
    hosts = {}
    for tr in manifest["trials"]:
        hosts.setdefault(tr["tic"], {"sector": tr["sector"],
                                     "trials": []})
        hosts[tr["tic"]]["trials"].append(tr)
    sectors_by_host = manifest.get("sectors_by_host") or {}
    single_jobs, stitched_jobs, missing = [], [], []
    for tic in sorted(hosts, key=int):
        if tics and tic not in tics:
            continue
        sector = hosts[tic]["sector"]
        if tic in sectors_by_host:
            host_sectors = sorted(int(s)
                                  for s in sectors_by_host[tic])
            assert sector in host_sectors, (
                f"TIC {tic}: original sector {sector} not in "
                f"sectors_by_host {host_sectors}")
        else:
            host_sectors = list(SECTORS)
        paths = {}
        ok = True
        for sec in host_sectors:
            p = _sector_fits_path(cache_dir, tic, sec)
            if not p.exists():
                missing.append((tic, sec))
                ok = False
            paths[str(sec)] = str(p)
        if not ok:
            continue
        path = _sector_fits_path(cache_dir, tic, sector)
        single_jobs.append(
            {"tic": tic, "sector": sector, "path": str(path),
             "trials": hosts[tic]["trials"],
             "out_dir": str(out_dir),
             "workdir": str(workdir_single),
             "calibration": calibration,
             "keep_fits": keep_fits, "arm": ARM, "spans": None,
             "manifest_sha": manifest["_sha256"],
             "mes_gate": mes_gate})
        stitched_jobs.append(
            {"tic": tic, "sectors": list(host_sectors), "paths": paths,
             "trials": hosts[tic]["trials"],
             "out_dir": str(out_dir),
             "workdir": str(workdir_p43),
             "calibration": calibration,
             "keep_fits": keep_fits,
             "agreement_only": agreement_only,
             "seed_mode": seed_mode,
             "manifest_sha": manifest["_sha256"],
             "mes_gate": mes_gate})
    if limit_hosts is not None:
        single_jobs = single_jobs[:limit_hosts]
        stitched_jobs = stitched_jobs[:limit_hosts]
    return single_jobs, stitched_jobs, missing


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="P4-3: paired multi-sector campaign + null "
                    "(3-sector stack, K=3, depth trigger dropped).")
    ap.add_argument("--mode", choices=("campaign", "null"),
                    default="campaign")
    ap.add_argument("--leg", choices=("single", "stitched", "both"),
                    default="both")
    ap.add_argument("--manifest", required=True,
                    help="p43_manifest.json (272 trials, 34 TICs)")
    ap.add_argument("--cache", required=True,
                    help="bulk/cache dir with s0095/s0096/s0097")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--calibration", default="bulk_v4")
    ap.add_argument("--tics", nargs="*", default=None)
    ap.add_argument("--limit-hosts", type=int, default=None)
    ap.add_argument("--keep-fits", action="store_true")
    ap.add_argument("--merge-only", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--p41b-dir", default=None,
                    help="P4-1b Arm D host files (single-leg "
                         "reproduction check in the merge)")
    ap.add_argument("--prereg-ref",
                    default="P43_PREREG.md section 0.7",
                    help="Pre-registration reference cited in the "
                         "summary (P4-3b: 'P43B_PREREG.md section "
                         "0.7'; P4-3c: 'PHASE41_PREREG.md section "
                         "2.4')")
    ap.add_argument("--agreement-only", action="store_true",
                    help="P4-3c agreement-only rule (Phase 4.1, "
                         "item 4.1-4): in non-original sectors, "
                         "mask ONLY when the fresh peak agrees "
                         "with the frozen record (period within "
                         "1%% AND epoch within one transit "
                         "duration); mask NOTHING on disagreement. "
                         "The original sector and the null leg "
                         "are unchanged.")
    ap.add_argument("--seed-mode", choices=("frozen", "fresh"),
                    default="frozen",
                    help="Non-original sector pre-mask seed: "
                         "'frozen' (P4-3b, default) or 'fresh' "
                         "(the P4-3 rule -- the fresh pass-1 peak "
                         "seeds the mask, no frozen seed "
                         "anywhere; defines the P4-3c at-risk "
                         "class on a fresh set). Incompatible "
                         "with --agreement-only.")
    args = ap.parse_args(argv)
    if args.agreement_only and args.seed_mode != "frozen":
        ap.error("--agreement-only requires --seed-mode frozen")
    out_dir = Path(args.out_dir)
    cache = Path(args.cache)
    manifest = orc._load_manifest(args.manifest)
    if args.mode == "campaign":
        if args.merge_only:
            summary = merge_campaign_p43(out_dir, manifest,
                                         args.p41b_dir,
                                         args.prereg_ref)
            print(f"[p43] merged {summary['n_trials_paired']} "
                  f"paired trials; verdict "
                  f"{summary['verdict']} "
                  f"(failing: {summary['failing_checks']})")
            return 0
        single_jobs, stitched_jobs, missing = _build_jobs(
            manifest, cache, out_dir, out_dir / "injected-p43",
            out_dir / "injected", args.keep_fits,
            args.calibration, args.tics, args.limit_hosts,
            agreement_only=args.agreement_only,
            seed_mode=args.seed_mode)
        print(f"[p43] campaign: {len(single_jobs)} single jobs, "
              f"{len(stitched_jobs)} stitched jobs, "
              f"{len(missing)} missing FITS; "
              f"agreement_only={args.agreement_only} "
              f"seed_mode={args.seed_mode}", flush=True)
        if args.dry_run:
            return 0
        (out_dir / "hosts").mkdir(parents=True, exist_ok=True)
        (out_dir / "hosts-p43").mkdir(parents=True, exist_ok=True)
        (out_dir / "injected").mkdir(parents=True, exist_ok=True)
        (out_dir / "injected-p43").mkdir(parents=True, exist_ok=True)
        t0 = time.time()
        if args.workers <= 1:
            bs.set_calibration(args.calibration)
            results = []
            if args.leg in ("single", "both"):
                results += [k3_run.run_host_campaign_k3(j)
                            for j in single_jobs]
            if args.leg in ("stitched", "both"):
                results += [run_host_campaign_p43(j)
                            for j in stitched_jobs]
        else:
            from multiprocessing import Pool
            # Pool.map needs a single function; run each leg's jobs
            # in its own pool pass (same initializer as k3_run).
            results = []
            for fn, leg_jobs in (
                    (k3_run.run_host_campaign_k3, single_jobs)
                    if args.leg in ("single", "both") else (None, []),
                    (run_host_campaign_p43, stitched_jobs)
                    if args.leg in ("stitched", "both") else (None, [])):
                if fn is None:
                    continue
                with Pool(args.workers,
                          initializer=orc._init_worker,
                          initargs=(args.calibration,)) as pool:
                    results += pool.map(fn, leg_jobs)
        done = sum(1 for r in results if r["status"] == "done")
        skipped = sum(1 for r in results
                      if r["status"] == "skipped")
        failures = [r for r in results if r["status"] == "error"]
        for r in failures:
            print(f"[p43] ERROR TIC {r['tic']}: "
                  f"{r.get('error')}", flush=True)
        summary = merge_campaign_p43(out_dir, manifest,
                                     args.p41b_dir,
                                     args.prereg_ref)
        if not summary["null"]["present"]:
            print("[p43] NOTE: null leg not run yet -- the verdict "
                  "above is PENDING the null element (section 0.7 "
                  "#5); re-merge after the null run.", flush=True)
        print(f"[p43] done: {done} run, {skipped} skipped, "
              f"{len(failures)} failed; "
              f"{summary['n_trials_paired']} paired trials; "
              f"long-period gain "
              f"{summary['cells']['long_period']['gain']} "
              f"(CI {summary['cells']['long_period']['ci']}), "
              f"low-event gain "
              f"{summary['cells']['low_event']['gain']} "
              f"(CI {summary['cells']['low_event']['ci']}), "
              f"right165 stitched "
              f"{summary['right165_stitched_rescued']}/"
              f"{summary['right165_testable']}; verdict "
              f"{summary['verdict']} "
              f"(failing: {summary['failing_checks']}); "
              f"{time.time() - t0:.0f}s wall")
        return 0 if not failures else 1
    # --- null mode ---
    if args.merge_only:
        summary = merge_null_p43(out_dir)
        print(f"[p43] null merged: stitched "
              f"{summary['stitched']['pass1_survivors']} -> "
              f"{summary['stitched']['final_rows']} rows "
              f"(bound {summary['stitched']['bound_rows']}, "
              f"{summary['stitched']['bound_verdict']}); single "
              f"{summary['single']['pass1_survivors']} -> "
              f"{summary['single']['final_rows']} rows "
              f"(bound {summary['single']['bound_rows']}, "
              f"{summary['single']['bound_verdict']})")
        return 0
    single_jobs, stitched_jobs, missing = _build_jobs(
        manifest, cache, out_dir, out_dir / "null_injected-p43",
        out_dir / "null_injected", args.keep_fits,
        args.calibration, args.tics, args.limit_hosts)
    # Null jobs carry no trials -- strip them (same job shape minus
    # the trial list).
    for j in single_jobs:
        j.pop("trials", None)
    for j in stitched_jobs:
        j.pop("trials", None)
    print(f"[p43] null: {len(single_jobs)} single jobs, "
          f"{len(stitched_jobs)} stitched jobs, "
          f"{len(missing)} missing FITS", flush=True)
    if args.dry_run:
        return 0
    (out_dir / "null_hosts").mkdir(parents=True, exist_ok=True)
    (out_dir / "null-p43").mkdir(parents=True, exist_ok=True)
    (out_dir / "null_injected").mkdir(parents=True, exist_ok=True)
    (out_dir / "null_injected-p43").mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    results = []
    for fn, leg_jobs in (
            (k3_run.run_host_null_k3, single_jobs)
            if args.leg in ("single", "both") else (None, []),
            (run_host_null_p43, stitched_jobs)
            if args.leg in ("stitched", "both") else (None, [])):
        if fn is None:
            continue
        if args.workers <= 1:
            bs.set_calibration(args.calibration)
            results += [fn(j) for j in leg_jobs]
        else:
            from multiprocessing import Pool
            with Pool(args.workers,
                      initializer=orc._init_worker,
                      initargs=(args.calibration,)) as pool:
                results += pool.map(fn, leg_jobs)
    done = sum(1 for r in results if r["status"] == "done")
    skipped = sum(1 for r in results if r["status"] == "skipped")
    failures = [r for r in results if r["status"] == "error"]
    for r in failures:
        print(f"[p43] ERROR TIC {r['tic']}: {r.get('error')}",
              flush=True)
    summary = merge_null_p43(out_dir)
    print(f"[p43] null done: {done} run, {skipped} skipped, "
          f"{len(failures)} failed; stitched "
          f"{summary['stitched']['pass1_survivors']} -> "
          f"{summary['stitched']['final_rows']} rows "
          f"(bound {summary['stitched']['bound_rows']}, "
          f"{summary['stitched']['bound_verdict']}); "
          f"{time.time() - t0:.0f}s wall")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
