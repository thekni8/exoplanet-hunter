"""P4-1b driver: run K=3 (pass 1 -> K=2 mask -> pass 2 -> pass-3 mask
-> pass 3) over the 451 wrong-period trials (campaign mode) and the
120 uninjected hosts (null mode), per arm.

Arms (P41B_RECORD.md §0.8, pre-registered):
  prototype       — K=2 mask, 25% cap (PRIMARY, gate arm)
  combined        — K=2 mask + T0-derived artifact spans, 25% cap
  cap-aware       — K=2 mask, period-aware cap (25% / 75% for P<5d)
  no-depth-trigger — K=2 mask, co-mask SNR-only, 25% cap

The measurement setup REPRODUCES the P4-1a run (bulk/k2_run.py):
same manifest, same injection, same fresh pass 1 (validation only),
same fold-based estimation, same K=2 mask code — so the pass-2
rescue count MUST reproduce P4-1a's 52 exactly (the merge flags any
difference as a bug, not a result). The only new step is pass 3,
gated on the pre-registered eligibility rule (bulk/k3_prototype).

Runtime-order law: pre-mask confirmed contaminants per sector ->
stitch (bulk/k3_prototype.stitch_sectors; single-sector identity in
this measurement — see P41B_RECORD.md §0.6) -> K=3 on the stitched
curve.

Gate (pre-registered, PB-6): P4-1b PASSES iff the PRIMARY arm
rescues >= 23 (oracle-derived bar), with zero regressions on the
412 (all 52 K=2 rescues preserved + pass-1 reproduction 451/451)
and null survivors <= +25% on total candidate ROWS (PB-6 A2).
The 52 K=2 baseline is the value comparison, not the gate.
"""

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
elif os.environ.get("K3_REPO"):
    REPO = Path(os.environ["K3_REPO"]).resolve()
elif _here.parent.name == "bulk" and (
        _here.parent.parent / "bulk_screen.py").exists():
    REPO = _here.parent.parent
else:
    raise SystemExit("k3_run: need --repo (script is outside a "
                     "repo checkout and K3_REPO is unset)")
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))

import numpy as np  # noqa: E402

import bulk_screen as bs  # noqa: E402
from bulk import k2_prototype as k2  # noqa: E402
from bulk import k3_prototype as k3  # noqa: E402
from bulk import oracle_run as orc  # noqa: E402
from bulk import pass1_carry as p1c  # noqa: E402
from bulk.inject_campaign import check_recovery, inject_trial  # noqa: E402
from bulk.inject_real_s96 import (load_real_fits,  # noqa: E402
                                  write_injected_fits)
from synth_fits import screen_job  # noqa: E402

# Frozen comparison numbers (PB-1 / PB-2 / P4-1a — cited, not re-derived).
ORACLE_RECOVERED = 45
ORACLE_GENUINE = 44
ORACLE_BY_GROUP = {"lockon_207": 17, "depth_148": 27, "wrong165_96": 1}
ARTIFACT_DEPTH_RECOVERED = 29
ARTIFACT_DEPTH_N = 148
K2_RECOVERED = 52  # P4-1a pass-2 count — the K=3 driver must reproduce it
K2_GENUINE = 52
K2_BAR = 23  # pre-registered in PB-6: 50% of the oracle bound
NULL_P1_SURVIVORS = 4  # P4-1a null leg — must reproduce


def _screen(path, tic, sector, return_periodogram=False,
            detrend="v6"):
    # Calibration is global (set by _init_worker / the serial
    # path via bs.set_calibration); screen_job takes no
    # calibration argument. return_periodogram threads the 5.6
    # periodogram exposure through (default off); detrend threads
    # the 5.7 detrend selection through (default "v6").
    return bs._screen_one(screen_job(
        path, tic, sector, return_periodogram=return_periodogram,
        detrend=detrend))


def _load_spans(path):
    """Load the PB-2 T0-derived artifact spans (phase2_validation.json).

    Returns (spans_by_sector, sha256): spans_by_sector maps sector
    (95/96) to a list of [lo, hi] BTJD pairs.
    """
    raw = Path(path).read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    d = json.loads(raw)
    return {96: d["s96_derived_spans"], 95: d["s95_derived_spans"]}, sha


def _est_error(ephemeris, p1):
    """Estimation error vs the fresh pass-1 ephemeris (DIAGNOSTIC ONLY).

    Measures how far the fold-based estimate sits from the fresh BLS
    measurement the oracle used. Never feeds the mask.
    """
    p1_p = p1.get("period_days")
    p1_t0 = p1.get("t0_btjd")
    dur_h = p1.get("duration_hours")
    out = {"period_frac": None, "t0_d": None, "duration_d": None}
    if p1_p is None:
        return out
    out["period_frac"] = float(
        (ephemeris["period_ref_d"] - p1_p) / p1_p)
    if p1_t0 is not None:
        d = (ephemeris["t0_est_btjd"] - p1_t0) % p1_p
        if d > p1_p / 2.0:
            d -= p1_p
        out["t0_d"] = float(d)
    if dur_h is not None:
        out["duration_d"] = float(
            ephemeris["duration_est_d"] - dur_h / 24.0)
    return out


def _run_pass2(t, f_inj, q, fcol, base, tic, sector, ephemeris,
               secondary, recorded_depth_pct, arm, spans, keep_fits,
               detrend="v6"):
    """Build the K=2 (+ artifact, combined arm) mask and run pass 2.

    Returns (keep2, mstats, p2_or_None, mask_path_or_None). The mask
    is built from the estimated ephemeris (never the fresh pass 1).
    """
    cap = k3.trial_cap(arm, ephemeris["period_ref_d"])
    depth_trigger = arm != "no-depth-trigger"
    if arm == "combined":
        # Bypass the internal cap (duty_cap=1.0); the cap applies to
        # the COMBINED (K=2 + artifact) duty cycle, checked below.
        keep_raw, mstats = k2.build_k2_mask(
            t, f_inj, q, ephemeris, recorded_depth_pct,
            secondary=secondary, duty_cap=1.0,
            depth_trigger=depth_trigger)
        keep_art = k3.artifact_keep_mask(t, spans)
        keep2 = keep_raw & keep_art
        duty = k3.combined_duty_cycle(t, f_inj, q, keep2)
        mstats["artifact_spans_applied"] = True
        mstats["artifact_spans_n"] = len(spans)
        mstats["combined_duty_cycle"] = float(duty)
        mstats["duty_cap"] = 0.25
        mstats["depth_trigger"] = bool(depth_trigger)
        if duty > 0.25:
            mstats["stopped"] = True
            mstats["stop_reason"] = "STOPPED_MASK_DUTY_CYCLE"
            keep2 = np.ones(len(t), dtype=bool)
        else:
            mstats["stopped"] = False
            mstats["stop_reason"] = None
    else:
        keep2, mstats = k2.build_k2_mask(
            t, f_inj, q, ephemeris, recorded_depth_pct,
            secondary=secondary, duty_cap=cap,
            depth_trigger=depth_trigger)
    if mstats["stopped"]:
        return keep2, mstats, None, None
    t_s, f_s, q_s = k3.stitch_sectors(
        [(t[keep2], f_inj[keep2], q[keep2])])
    mask_path = str(base) + "_k2masked.fits"
    write_injected_fits(mask_path, t_s, f_s, q_s, fcol)
    p2 = _screen(mask_path, tic, sector, detrend=detrend)
    if not keep_fits:
        os.remove(mask_path)
    return keep2, mstats, p2, mask_path


def _run_pass3(t, f_inj, q, fcol, base, tic, sector, keep2, p2,
               ephemeris1, mstats1, arm, period_inj, epoch_inj,
               duration_inj, keep_fits, flagged=None, detrend="v6"):
    """Build the pass-3 mask from the pass-2 peak and run pass 3.

    Assumes pass 2 did not rescue and the peak is eligible
    (checked by the caller via k3.pass3_eligible). The pass-3 mask
    is unioned with the K=2 mask; the ARM cap applies to the union.
    period_inj / epoch_inj / duration_inj are the injected planet
    (ground truth for the recovery verdict only — never an input to
    the mask). `flagged` is orc.flagged_periods' output for the
    pass-1 record(s) (F-2, bulk_v6): when given, a pass-3 row
    matching a flagged pass-1 signal re-raises the EB flags (and
    the demotion). Returns (eligibility_dict, k3_record_dict).
    """
    veto2 = k2.alias_veto(
        p2.get("period_days"), p2.get("t0_btjd"),
        ephemeris1["period_ref_d"], ephemeris1["t0_est_btjd"],
        mstats1["mask_half_width_d"],
        comask_phase=mstats1["secondary_phase"])
    elig, reason = k3.pass3_eligible(p2, veto2, False)
    out = {"eligible": bool(elig), "reason": reason, "veto_pass2": veto2}
    if not elig:
        return out, {"pass3": None, "k3_recovered": False,
                     "k3_genuine": False}
    # Estimate the pass-2 peak's ephemeris from the stitched
    # (K=2-masked) curve — the curve pass 2 saw.
    t_s, f_s, q_s = k3.stitch_sectors(
        [(t[keep2], f_inj[keep2], q[keep2])])
    t_p2, f_p2 = orc.preprocess_arrays(t_s, f_s, q_s,
                                       detrend=detrend)
    eph2 = k2.estimate_ephemeris(t_p2, f_p2, p2.get("period_days"))
    sec2 = k2.scan_secondary(t_p2, f_p2, eph2["period_ref_d"],
                             eph2["t0_est_btjd"],
                             eph2["duration_est_d"])
    cap = k3.trial_cap(arm, ephemeris1["period_ref_d"])
    depth_trigger = arm != "no-depth-trigger"
    # Bypass the internal cap; the cap applies to the UNION mask.
    keep3_raw, mstats3 = k2.build_k2_mask(
        t, f_inj, q, eph2, p2.get("depth_percent"), secondary=sec2,
        duty_cap=1.0, depth_trigger=depth_trigger)
    keep_union, duty_u, stopped_u = k3.apply_union_cap(
        t, f_inj, q, keep2, keep3_raw, cap)
    mstats3["union_duty_cycle"] = float(duty_u)
    mstats3["duty_cap"] = float(cap)
    mstats3["stopped"] = bool(stopped_u)
    mstats3["stop_reason"] = ("STOPPED_MASK_DUTY_CYCLE"
                              if stopped_u else None)
    mstats3["stopped_pass"] = 3 if stopped_u else None
    rec = {"k3_ephemeris": eph2,
           "k3_secondary_scan": {"phase": sec2[0],
                                 "depth_frac": sec2[1], "snr": sec2[2]},
           "k3_mask": mstats3}
    if stopped_u:
        rec.update({"pass3": None, "k3_recovered": False,
                    "k3_genuine": False})
        return out, rec
    t_s3, f_s3, q_s3 = k3.stitch_sectors(
        [(t[keep_union], f_inj[keep_union], q[keep_union])])
    mask3_path = str(base) + "_k3masked.fits"
    write_injected_fits(mask3_path, t_s3, f_s3, q_s3, fcol)
    p3 = _screen(mask3_path, tic, sector, detrend=detrend)
    if not keep_fits:
        os.remove(mask3_path)
    # F-2 (bulk_v6): re-raise a flagged pass-1 signal's EB
    # flags on the pass-3 row — before the subset (so the
    # stored record carries them) and before the recovery
    # verdict (check_recovery requires status "survivor",
    # so a carried demotion fails recovery exactly as a
    # measured flag would).
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
        [{"period_d": ephemeris1["period_ref_d"],
          "t0_btjd": ephemeris1["t0_est_btjd"],
          "mask_half_width_d": mstats1["mask_half_width_d"],
          "comask_phase": mstats1["secondary_phase"]},
         {"period_d": eph2["period_ref_d"],
          "t0_btjd": eph2["t0_est_btjd"],
          "mask_half_width_d": mstats3["mask_half_width_d"],
          "comask_phase": mstats3["secondary_phase"]}])
    rec["alias_veto_pass3"] = veto3
    if period_inj is None:
        # Null leg: no injected planet, so no recovery/epoch
        # verdict — the caller uses the pass-3 screen record only.
        rec["pass3_match"] = None
        rec["m6_pass3_before_veto"] = None
        rec["k3_recovered"] = False
        rec["epoch_delta_d_pass3"] = None
        rec["epoch_delta_over_d_pass3"] = None
        rec["epoch_match_pass3"] = False
        rec["k3_genuine"] = False
        return out, rec
    rec["pass3_match"] = orc.period_match_class(
        p3.get("period_days"), period_inj)
    m6_3 = bool(check_recovery(p3, period_inj))
    rec["m6_pass3_before_veto"] = m6_3
    rec["k3_recovered"] = bool(m6_3 and not veto3["vetoed"])
    delta3 = k2.epoch_delta(p3.get("t0_btjd"), epoch_inj, period_inj)
    rec["epoch_delta_d_pass3"] = delta3
    rec["epoch_delta_over_d_pass3"] = (
        abs(delta3) / duration_inj if delta3 is not None else None)
    rec["epoch_match_pass3"] = bool(k2.epoch_match(delta3,
                                                   duration_inj))
    rec["k3_genuine"] = bool(rec["k3_recovered"]
                             and rec["epoch_match_pass3"])
    return out, rec

def run_host_campaign_k3(job):
    """One host-sector: inject each of the 451 trials, fresh pass 1
    (validation only), K=2 estimation + mask, pass 2, pass 3 where
    eligible, verdicts."""
    tic = job["tic"]
    sector = job["sector"]
    arm = job["arm"]
    spans = (job.get("spans") or {}).get(sector) if job.get("spans") \
        else None
    out_dir = Path(job["out_dir"])
    workdir = Path(job["workdir"])
    manifest_sha = job["manifest_sha"]
    calibration = job["calibration"]
    keep_fits = job.get("keep_fits", False)
    # 5.7 detrend (D9): the single leg's screens change too, so the
    # flag is part of the resume check (a v6 host file is never
    # resumed by a v7 run, and vice versa).
    detrend = job.get("detrend", "v6")
    out_path = out_dir / "hosts" / f"{tic}_s{sector:04d}.json"
    if out_path.exists():
        try:
            prev = json.loads(out_path.read_text())
        except ValueError:
            prev = {}
        if (prev.get("complete") is True
                and prev.get("manifest_sha") == manifest_sha
                and prev.get("arm") == arm
                and prev.get("mes_gate") == job.get("mes_gate")
                and prev.get("detrend", "v6") == detrend):
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
             "epoch_btjd": tr["epoch_btjd"],
             "duration_d": tr["duration_d"],
             "epoch_offset_d": tr["epoch_offset_d"],
             "depth_frac": tr["depth_frac"],
             "recorded": tr["recorded"], "arm": arm}
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
            # --- fresh pass 1: VALIDATION ONLY (never an input to
            # the estimation). Same reproduction check as the oracle.
            t_p1 = time.time()
            p1 = _screen(inj_path, tic, sector, detrend=detrend)
            r["seconds_pass1"] = round(time.time() - t_p1, 2)
            r["pass1"] = orc._subset(p1)
            # PIPE50-9b (bulk_v6): the pass-1 epoch delta the
            # any-stage scorer reads (pass1_recovers) — the
            # single-leg analog of the stitched leg's
            # epoch_delta_over_d_pass1 (p43_run). Without it,
            # any-stage scoring on the single leg is vacuous
            # (pass 1 can never recover: leg_recovers needs
            # the recorded epoch delta).
            delta1 = k2.epoch_delta(p1.get("t0_btjd"),
                                    tr["epoch_btjd"],
                                    tr["period_d"])
            r["epoch_delta_over_d_pass1"] = (
                abs(delta1) / tr["duration_d"]
                if delta1 is not None else None)
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
            # --- prototype estimation (recorded period + fold only)
            if p_rec is None:
                r["error"] = "no-recorded-period"
                results.append(r)
                if not keep_fits:
                    os.remove(inj_path)
                continue
            t_p, f_p = orc.preprocess_arrays(t, f_inj, q,
                                            detrend=detrend)
            ephemeris = k2.estimate_ephemeris(t_p, f_p, p_rec)
            r["ephemeris"] = ephemeris
            r["est_error_vs_fresh_p1"] = _est_error(ephemeris, p1)
            secondary = k2.scan_secondary(
                t_p, f_p, ephemeris["period_ref_d"],
                ephemeris["t0_est_btjd"],
                ephemeris["duration_est_d"])
            r["secondary_scan"] = {
                "phase": secondary[0], "depth_frac": secondary[1],
                "snr": secondary[2]}
            # --- pass 2 (K=2 mask + artifact spans, combined arm)
            # Mask gate (bulk_v6, design section 5.2): the mask
            # applies only when the signal being masked is
            # contaminant-like. The gate record is the RECORDED
            # row (the mask seed; the fresh p1 is validation
            # only). Gate OFF (frozen profiles) = mask
            # unconditional. Gated off: no mask — pass 2
            # carries the fresh pass-1 record forward as the
            # leg result (no re-search; the record stands) and
            # pass 3 does not run.
            gate_allows = k2.mask_gate_allows(rec)
            if gate_allows:
                keep2, mstats, p2, _ = _run_pass2(
                    t, f_inj, q, fcol, base, tic, sector, ephemeris,
                    secondary, rec.get("depth_percent"), arm, spans,
                    keep_fits, detrend=detrend)
                carried_from_pass1 = False
            else:
                keep2 = np.ones(len(t), dtype=bool)
                mstats = k2.gated_off_mask_stats()
                p2 = p1
                carried_from_pass1 = True
            r["k2_mask"] = mstats
            if p2 is None:
                r["pass2"] = None
                r["pass2_match"] = None
                r["alias_veto"] = None
                r["epoch_delta_d"] = None
                r["epoch_match"] = False
                r["k2_recovered"] = False
                r["k2_genuine"] = False
                r["m6_before_veto"] = False
                r["stopped_pass"] = 2
                r["pass3_eligibility"] = {
                    "eligible": False,
                    "reason": "stopped-duty-cycle"}
                r["pass3"] = None
                r["k3_recovered"] = False
                r["k3_genuine"] = False
                # 5.1 design (A) §4.4.5: the duty-cycle cap
                # stops the MASKED re-search, not the
                # preservation — a pass-1 survivor is still
                # carried (the mask stats carry the half-width
                # even when stopped, so the alias veto still
                # applies).
                _carry, _audit = p1c.build_carried_row(
                    r["pass1"],
                    flagged=orc.flagged_periods(p1),
                    veto_ref=p1c.veto_ref_from(ephemeris, mstats))
                r["pass1_carried"] = _carry
                r["alias_veto_carried"] = _audit["alias_veto"]
                if _carry is not None:
                    _carry["deduped_with"] = None
                (r["p1_carried_recovered"],
                 r["p1_carried_genuine"]) = (
                    p1c.carried_recovery_verdict(
                        _carry, _audit["alias_veto"], tr))
                r["final_recovered"] = bool(
                    r["p1_carried_recovered"])
                r["final_genuine"] = bool(
                    r["p1_carried_genuine"])
            else:
                r["stopped_pass"] = None
                # F-2 (bulk_v6): re-raise the fresh pass-1
                # screen's EB flags on the pass-2 row when its
                # period matches a flagged pass-1 signal — on
                # the FULL record, before the subset (so the
                # stored record carries the flags + demotion)
                # and before the recovery verdict and pass-3
                # eligibility (a carried demotion behaves
                # exactly as a measured flag would). Skipped
                # in the no-mask branch: there p2 IS p1, so
                # its flags are measured, not carried (applying
                # F-2 would mislabel them as carried).
                flagged = orc.flagged_periods(p1)
                carried = (orc.carried_eb_flags(
                    p2.get("period_days"), flagged)
                    if not carried_from_pass1 else [])
                if carried:
                    orc.apply_eb_carry(p2, carried)
                r["pass2"] = orc._subset(p2)
                if carried:
                    r["pass2"]["flags_carried_from"] = (
                        orc.FLAGS_CARRIED_FROM_PASS1)
                if carried_from_pass1:
                    r["pass2"]["carried_from"] = "pass1"
                r["pass2_match"] = orc.period_match_class(
                    p2.get("period_days"), tr["period_d"])
                # No mask in the carry branch, so no mask to
                # veto against (None, like the stopped branch).
                veto = None if carried_from_pass1 else k2.alias_veto(
                    p2.get("period_days"), p2.get("t0_btjd"),
                    ephemeris["period_ref_d"],
                    ephemeris["t0_est_btjd"],
                    mstats["mask_half_width_d"],
                    comask_phase=mstats["secondary_phase"])
                r["alias_veto"] = veto
                m6 = bool(check_recovery(p2, spec["period_d"]))
                r["m6_before_veto"] = m6
                # No mask in the carry branch (veto is None), so
                # there is no veto to fail -- the carried
                # recovery stands. (M4-p43, 2026-11-20: the
                # bare veto["vetoed"] subscript crashed with
                # TypeError on gated-off recovering trials --
                # 138/272 single-leg trials in the M4 run.)
                r["k2_recovered"] = bool(
                    m6 and (veto is None or not veto["vetoed"]))
                delta = k2.epoch_delta(p2.get("t0_btjd"),
                                       tr["epoch_btjd"],
                                       tr["period_d"])
                r["epoch_delta_d"] = delta
                r["epoch_delta_over_d"] = (
                    abs(delta) / tr["duration_d"]
                    if delta is not None else None)
                r["epoch_match"] = bool(k2.epoch_match(
                    delta, tr["duration_d"]))
                r["k2_genuine"] = bool(
                    r["k2_recovered"] and r["epoch_match"])
                if r["k2_recovered"]:
                    r["pass3_eligibility"] = {
                        "eligible": False,
                        "reason": "pass2-rescued"}
                    r["pass3"] = None
                    r["k3_recovered"] = False
                    r["k3_genuine"] = False
                elif carried_from_pass1:
                    # No mask (design section 5.2): pass 3
                    # does not run — nothing was masked, so
                    # there is nothing to look behind.
                    r["pass3_eligibility"] = {
                        "eligible": False,
                        "reason": "no-mask-carry-forward"}
                    r["pass3"] = None
                    r["k3_recovered"] = False
                    r["k3_genuine"] = False
                else:
                    elig, rec3 = _run_pass3(
                        t, f_inj, q, fcol, base, tic, sector, keep2,
                        p2, ephemeris, mstats, arm, tr["period_d"],
                        tr["epoch_btjd"], tr["duration_d"],
                        keep_fits, flagged=flagged,
                        detrend=detrend)
                    r["pass3_eligibility"] = elig
                    r.update(rec3)
                # 5.1 design (A) §4.4: preserve the pass-1
                # survivor as a carried final row. The veto
                # reference is the ephemeris + mask stats (same
                # as pass-2's veto); in the gated-off branch
                # there is no mask, so the veto is skipped
                # (veto_ref_from returns None). Dedupe against
                # pass-2/3 (a deduped carry is not a loss).
                _carry, _audit = p1c.build_carried_row(
                    r["pass1"], flagged=flagged,
                    veto_ref=p1c.veto_ref_from(ephemeris, mstats),
                    veto_skipped_reason=(
                        "no-mask-carry-forward"
                        if carried_from_pass1 else None))
                r["pass1_carried"] = _carry
                r["alias_veto_carried"] = _audit["alias_veto"]
                if _carry is not None:
                    _carry["deduped_with"] = p1c.dedupe_carried(
                        _carry, r.get("pass2"), r.get("pass3"),
                        tr["duration_d"])
                (r["p1_carried_recovered"],
                 r["p1_carried_genuine"]) = (
                    p1c.carried_recovery_verdict(
                        _carry, _audit["alias_veto"], tr))
                r["final_recovered"] = bool(
                    r["k2_recovered"] or r["k3_recovered"]
                    or r["p1_carried_recovered"])
                r["final_genuine"] = bool(
                    r["k2_genuine"] or r["k3_genuine"]
                    or r["p1_carried_genuine"])
            if not keep_fits:
                os.remove(inj_path)
        except Exception as exc:  # noqa: BLE001
            r["error"] = f"{type(exc).__name__}: {exc}"
        r["seconds"] = round(time.time() - t_tr, 2)
        results.append(r)
    rec = {"tic": tic, "sector": sector, "complete": True,
           "manifest_sha": manifest_sha, "calibration": calibration,
           "arm": arm, "mes_gate": job.get("mes_gate"),
           "n_trials": len(results),
           "seconds": round(time.time() - t_start, 1),
           "trials": results}
    if detrend != "v6":
        # Flag-on runs only, so flag-off records stay byte-identical.
        rec["detrend"] = detrend
    tmp = out_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(rec))
    tmp.replace(out_path)
    n_fin = sum(1 for r in results if r.get("final_recovered") is True)
    return {"status": "done", "tic": tic, "sector": sector,
            "n_trials": len(results), "n_final_recovered": n_fin}


def run_host_null_k3(job):
    """One host-sector, UNINJECTED: fresh pass 1 -> K=2 mask -> pass 2
    -> pass 3 where eligible. Per-pass null accounting."""
    tic = job["tic"]
    sector = job["sector"]
    arm = job["arm"]
    spans = (job.get("spans") or {}).get(sector) if job.get("spans") \
        else None
    out_dir = Path(job["out_dir"])
    workdir = Path(job["workdir"])
    calibration = job["calibration"]
    keep_fits = job.get("keep_fits", False)
    # 5.7 detrend (D9): as in the campaign leg.
    detrend = job.get("detrend", "v6")
    out_path = out_dir / "null_hosts" / f"{tic}_s{sector:04d}.json"
    if out_path.exists():
        try:
            prev = json.loads(out_path.read_text())
        except ValueError:
            prev = {}
        if (prev.get("complete") is True
                and prev.get("arm") == arm
                and prev.get("mes_gate") == job.get("mes_gate")
                and prev.get("detrend", "v6") == detrend):
            return {"status": "skipped", "tic": tic, "sector": sector}
    t_start = time.time()
    r = {"tic": tic, "sector": sector, "arm": arm,
         "mes_gate": job.get("mes_gate")}
    try:
        t, f, q, fcol, meta = load_real_fits(job["path"])
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "tic": tic, "sector": sector,
                "error": f"load_real_fits: {exc}"}
    try:
        base = workdir / f"{tic}_s{sector:04d}_null"
        raw_path = str(base) + ".fits"
        write_injected_fits(raw_path, t, f, q, fcol)
        p1 = _screen(raw_path, tic, sector, detrend=detrend)
        r["pass1"] = orc._subset(p1)
        r["pass1_survivor"] = bool(p1.get("status") == "survivor")
        # F-2 source for the leg (pass-2 and the 5.1 carried row
        # share it — computed once, before the period check, so
        # the stopped / no-period branches see it too).
        flagged = orc.flagged_periods(p1)
        p1_p = p1.get("period_days")
        r["pass2_survivor"] = False
        r["pass3_survivor"] = False
        r["final_survivor"] = False
        if p1_p is None:
            r["pass2"] = None
            r["pass3"] = None
            r["note"] = "no-pass1-period"
        else:
            t_p, f_p = orc.preprocess_arrays(t, f, q,
                                            detrend=detrend)
            ephemeris = k2.estimate_ephemeris(t_p, f_p, p1_p)
            r["ephemeris"] = ephemeris
            secondary = k2.scan_secondary(
                t_p, f_p, ephemeris["period_ref_d"],
                ephemeris["t0_est_btjd"],
                ephemeris["duration_est_d"])
            r["secondary_scan"] = {
                "phase": secondary[0], "depth_frac": secondary[1],
                "snr": secondary[2]}
            # Mask gate (bulk_v6, design section 5.2): as in
            # the campaign leg — the gate record here is the
            # FRESH pass-1 screen (no recorded row exists in
            # the null leg). Gated off: pass 2 carries the
            # fresh pass-1 record forward; pass 3 does not run.
            gate_allows = k2.mask_gate_allows(p1)
            if gate_allows:
                keep2, mstats, p2, _ = _run_pass2(
                    t, f, q, fcol, base, tic, sector, ephemeris,
                    secondary, p1.get("depth_percent"), arm, spans,
                    keep_fits, detrend=detrend)
                carried_from_pass1 = False
            else:
                keep2 = np.ones(len(t), dtype=bool)
                mstats = k2.gated_off_mask_stats()
                p2 = p1
                carried_from_pass1 = True
            r["k2_mask"] = mstats
            if p2 is None:
                r["pass2"] = None
                r["pass3"] = None
                r["note"] = "stopped-duty-cycle"
                r["stopped_pass"] = 2
            else:
                # F-2 (bulk_v6): as in the campaign leg — the
                # fresh pass-1 screen's EB flags travel to the
                # pass-2 row on a harmonic period match, before
                # the subset, the survivor flag, and pass-3
                # eligibility. Skipped in the no-mask branch
                # (p2 IS p1 there — its flags are measured,
                # not carried). `flagged` was computed above
                # (shared with the 5.1 carried row).
                carried = (orc.carried_eb_flags(
                    p2.get("period_days"), flagged)
                    if not carried_from_pass1 else [])
                if carried:
                    orc.apply_eb_carry(p2, carried)
                r["pass2"] = orc._subset(p2)
                if carried:
                    r["pass2"]["flags_carried_from"] = (
                        orc.FLAGS_CARRIED_FROM_PASS1)
                if carried_from_pass1:
                    r["pass2"]["carried_from"] = "pass1"
                r["pass2_survivor"] = bool(
                    p2.get("status") == "survivor")
                # No mask in the carry branch, so no mask to
                # veto against — and pass 3 does not run.
                if carried_from_pass1:
                    r["pass3_eligibility"] = {
                        "eligible": False,
                        "reason": "no-mask-carry-forward"}
                    r["pass3"] = None
                else:
                    veto2 = k2.alias_veto(
                        p2.get("period_days"), p2.get("t0_btjd"),
                        ephemeris["period_ref_d"],
                        ephemeris["t0_est_btjd"],
                        mstats["mask_half_width_d"],
                        comask_phase=mstats["secondary_phase"])
                    # Null leg: there is no injected planet, so the
                    # "pass 2 rescued" short-circuit does not apply — a
                    # pass-2 survivor is a candidate the K=3 search
                    # looks behind (the eligibility rule's survivor
                    # branch covers it). p2_rescued is always False here.
                    elig, reason = k3.pass3_eligible(
                        orc._subset(p2), veto2, False)
                    r["pass3_eligibility"] = {"eligible": bool(elig),
                                              "reason": reason}
                    if not elig:
                        r["pass3"] = None
                    else:
                        _e, rec3 = _run_pass3(
                            t, f, q, fcol, base, tic, sector, keep2,
                            p2, ephemeris, mstats, arm,
                            period_inj=None, epoch_inj=None,
                            duration_inj=None, keep_fits=keep_fits,
                            flagged=flagged, detrend=detrend)
                        # _run_pass3 needs an injected period for the
                        # recovery verdict — the null leg has none, so
                        # use the pass-3 record's screen fields only.
                        r["k3_mask"] = rec3.get("k3_mask")
                        r["k3_ephemeris"] = rec3.get("k3_ephemeris")
                        r["pass3"] = rec3.get("pass3")
                        r["pass3_survivor"] = bool(
                            (rec3.get("pass3") or {}).get("status")
                            == "survivor")
        # 5.1 design (A) §4.4: preserve the pass-1 survivor as
        # a carried final row — in every branch, including
        # stopped (§4.4.5: the cap stops the masked re-search,
        # not the preservation) and no-pass1-period (no carry
        # is possible there; the build returns None). No alias
        # veto reference exists in the null leg: the ephemeris
        # is seeded from pass-1 itself, so a veto against it
        # would be a signal vetoed by itself (degenerate —
        # skipped with the reason recorded). final_survivor is
        # the carried OR pass-2 OR pass-3 survivor; final_rows
        # counts distinct final rows (dedupe applied).
        _carry, _audit = p1c.build_carried_row(
            r["pass1"], flagged=flagged,
            veto_skipped_reason="null-leg-no-independent-reference")
        r["pass1_carried"] = _carry
        r["alias_veto_carried"] = _audit["alias_veto"]
        _dur = ((_carry or {}).get("duration_hours") or 0) / 24.0
        if _carry is not None:
            _carry["deduped_with"] = p1c.dedupe_carried(
                _carry, r.get("pass2"), r.get("pass3"), _dur)
        r["pass1_carried_survivor"] = p1c.carried_survivor(_carry)
        r["final_rows"] = p1c.count_final_rows(
            _carry, r.get("pass2"), r.get("pass3"), _dur)
        r["final_survivor"] = bool(
            r["pass1_carried_survivor"] or r["pass2_survivor"]
            or r["pass3_survivor"])
        if not keep_fits:
            os.remove(raw_path)
    except Exception as exc:  # noqa: BLE001
        r["error"] = f"{type(exc).__name__}: {exc}"
    r["complete"] = True
    r["calibration"] = calibration
    if detrend != "v6":
        # Flag-on runs only, so flag-off records stay byte-identical.
        r["detrend"] = detrend
    r["seconds"] = round(time.time() - t_start, 1)
    tmp = out_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(r))
    tmp.replace(out_path)
    return {"status": "done", "tic": tic, "sector": sector,
            "pass1_survivor": r.get("pass1_survivor"),
            "pass2_survivor": r.get("pass2_survivor"),
            "pass3_survivor": r.get("pass3_survivor")}

def _stats(vals):
    """Median / p90 / max of a list of floats (None-safe)."""
    v = sorted(x for x in vals if x is not None)
    if not v:
        return {"n": 0, "median": None, "p90": None, "max": None}
    return {"n": len(v),
            "median": float(np.median(v)),
            "p90": float(np.percentile(v, 90)),
            "max": float(max(v))}


def merge_campaign_k3(out_dir, manifest, arm):
    """Aggregate per-host campaign files into k3_summary_<arm>.json."""
    out_dir = Path(out_dir)
    host_files = sorted((out_dir / "hosts").glob("*.json"))
    records = []
    for p in host_files:
        try:
            rec = json.loads(p.read_text())
        except ValueError:
            continue
        if rec.get("complete") is True and rec.get("arm") == arm:
            records.append(rec)
    trials = [tr for rec in records for tr in rec["trials"]]
    by_group = {}
    for tr in trials:
        by_group.setdefault(tr["group"], []).append(tr)
    k3_trials = [tr for g in orc.ORACLE_GROUPS
                 for tr in by_group.get(g, [])]
    repro = [tr for tr in trials if tr.get("pass1_repro")]
    n_repro_ok = sum(1 for tr in repro
                     if tr["pass1_repro"].get("ok"))
    # Pass-2 validation: must reproduce P4-1a exactly — but ONLY on
    # the full 451-trial run; a smoke subset cannot match 52.
    full_run = len(k3_trials) == 451
    p2_rec = sum(1 for tr in k3_trials
                 if tr.get("k2_recovered") is True)
    p2_gen = sum(1 for tr in k3_trials
                 if tr.get("k2_genuine") is True)
    p2_match = (bool(p2_rec == K2_RECOVERED and p2_gen == K2_GENUINE)
                if full_run else None)
    # Pass-3 gains: rescued at pass 3 having not been rescued at pass 2.
    p3_rec = sum(1 for tr in k3_trials
                 if tr.get("k3_recovered") is True)
    p3_gen = sum(1 for tr in k3_trials
                 if tr.get("k3_genuine") is True)
    fin_rec = sum(1 for tr in k3_trials
                  if tr.get("final_recovered") is True)
    fin_gen = sum(1 for tr in k3_trials
                  if tr.get("final_genuine") is True)
    by_g = {g: {"n": len(by_group.get(g, [])),
                "pass2_recovered": sum(
                    1 for tr in by_group.get(g, [])
                    if tr.get("k2_recovered") is True),
                "pass3_recovered": sum(
                    1 for tr in by_group.get(g, [])
                    if tr.get("k3_recovered") is True),
                "final_recovered": sum(
                    1 for tr in by_group.get(g, [])
                    if tr.get("final_recovered") is True),
                "final_genuine": sum(
                    1 for tr in by_group.get(g, [])
                    if tr.get("final_genuine") is True),
                "oracle_recovered": ORACLE_BY_GROUP.get(g),
                "stopped_pass2": sum(
                    1 for tr in by_group.get(g, [])
                    if tr.get("stopped_pass") == 2),
                "stopped_pass3": sum(
                    1 for tr in by_group.get(g, [])
                    if (tr.get("k3_mask") or {}).get("stopped") is True)}
            for g in orc.ORACLE_GROUPS}
    by_sector = {}
    for tr in k3_trials:
        s = tr["sector"]
        d = by_sector.setdefault(s, {"n": 0, "pass2_recovered": 0,
                                     "pass3_recovered": 0,
                                     "final_recovered": 0,
                                     "final_genuine": 0})
        d["n"] += 1
        d["pass2_recovered"] += int(tr.get("k2_recovered") is True)
        d["pass3_recovered"] += int(tr.get("k3_recovered") is True)
        d["final_recovered"] += int(tr.get("final_recovered") is True)
        d["final_genuine"] += int(tr.get("final_genuine") is True)
    eb_hosts = set(manifest.get("eb_hosts", []))
    host_rec = {}
    for rec in records:
        for tr in rec["trials"]:
            if tr["group"] in orc.ORACLE_GROUPS:
                h = host_rec.setdefault(rec["tic"], [0, 0])
                h[0] += 1
                h[1] += int(tr.get("final_recovered") is True)
    eb = {"n": 0, "recovered": 0}
    non_eb = {"n": 0, "recovered": 0}
    for tic, (n, r) in host_rec.items():
        d = eb if tic in eb_hosts else non_eb
        d["n"] += n
        d["recovered"] += r
    match3 = {}
    for tr in k3_trials:
        m = tr.get("pass3_match")
        if m is not None:
            match3[m] = match3.get(m, 0) + 1
    ci = orc._bootstrap_host_ci(list(host_rec.values()))
    rescued = [tr for tr in k3_trials
               if tr.get("final_recovered") is True]
    epoch_pass = sum(1 for tr in rescued
                     if tr.get("final_genuine") is True)
    epoch_stats = _stats([tr.get("epoch_delta_over_d_pass3")
                          for tr in rescued
                          if tr.get("k3_recovered") is True])
    stopped2 = [tr for tr in k3_trials
                if tr.get("stopped_pass") == 2]
    stopped3 = [tr for tr in k3_trials
                if (tr.get("k3_mask") or {}).get("stopped") is True]
    elig_reasons = {}
    for tr in k3_trials:
        e = tr.get("pass3_eligibility") or {}
        rs = e.get("reason")
        if rs is not None:
            elig_reasons[rs] = elig_reasons.get(rs, 0) + 1
    comask = {}
    for tr in k3_trials:
        m = tr.get("k2_mask", {})
        if m.get("secondary_comasked"):
            t = m.get("comask_trigger")
            comask[t] = comask.get(t, 0) + 1
    vetoed3 = [tr for tr in k3_trials
               if (tr.get("alias_veto_pass3") or {}).get("vetoed")
               is True]
    vetoed3_would = [tr for tr in vetoed3
                     if tr.get("m6_pass3_before_veto") is True]
    p3_survivors = [tr for tr in k3_trials
                    if (tr.get("pass3") or {}).get("status")
                    == "survivor"]
    p3_fp = [tr for tr in p3_survivors
             if tr.get("k3_recovered") is not True]
    depth = by_group.get("depth_148", [])
    depth_fin = sum(1 for tr in depth
                    if tr.get("final_recovered") is True)
    # A18 compute: total trial wall vs pass-1-only wall.
    tot_s = sum(tr.get("seconds") or 0 for tr in k3_trials)
    p1_s = sum(tr.get("seconds_pass1") or 0 for tr in k3_trials)
    ratio = (tot_s / p1_s) if p1_s else None
    summary = {
        "tool": "k3_run", "mode": "campaign", "arm": arm,
        "n_hosts_completed": len(records),
        "n_trials": len(k3_trials),
        "pass1_reproduction": {
            "n_checked": len(repro), "n_ok": n_repro_ok,
            "mismatches": [f"{tr['tic']}_s{tr['sector']:04d}_"
                           f"{tr['trial_id']}" for tr in repro
                           if not tr["pass1_repro"].get("ok")]},
        "pass2_validation": {
            "recovered": p2_rec, "genuine": p2_gen,
            "expected_recovered": K2_RECOVERED,
            "expected_genuine": K2_GENUINE,
            "matches_p41a": p2_match},
        "k3": {
            "pass2_recovered": p2_rec, "pass2_genuine": p2_gen,
            "pass3_recovered": p3_rec, "pass3_genuine": p3_gen,
            "final_recovered": fin_rec, "final_genuine": fin_gen,
            "n": len(k3_trials),
            "rate": (fin_rec / len(k3_trials) if k3_trials else None),
            "by_group": by_g, "by_sector": by_sector,
            "eb_hosts_15": eb, "non_eb_hosts": non_eb,
            "pass3_match": match3,
            "host_level_ci_95": ci},
        "gate": {
            "bar_rescues": K2_BAR,
            "recovered": fin_rec,
            "verdict": (("PASS" if fin_rec >= K2_BAR else "FAIL")
                        if full_run else "N/A (subset)"),
            "rule": ("P4-1b passes iff the PRIMARY arm rescues >= 23 "
                     "(oracle-derived bar, PB-6 A1/A4), with zero "
                     "regressions (A3) and null <= +25% rows (A2). "
                     "This merge's verdict is computed for its own "
                     "arm; the P4-1b gate verdict is Arm A's.")},
        "vs_oracle": {
            "oracle_recovered": ORACLE_RECOVERED,
            "oracle_genuine": ORACLE_GENUINE,
            "k3_recovered": fin_rec,
            "k3_genuine": fin_gen,
            "fraction_of_oracle_bound": (
                fin_rec / ORACLE_RECOVERED if ORACLE_RECOVERED
                else None)},
        "vs_k2": {
            "k2_recovered": K2_RECOVERED,
            "k2_genuine": K2_GENUINE,
            "k3_recovered": fin_rec,
            "k3_genuine": fin_gen,
            "delta_recovered": fin_rec - K2_RECOVERED,
            "pass3_gained": p3_rec},
        "vs_artifact_depth": {
            "n": len(depth),
            "k3_recovered": depth_fin,
            "artifact_recovered": ARTIFACT_DEPTH_RECOVERED,
            "oracle_recovered": ORACLE_BY_GROUP["depth_148"],
            "k2_recovered": sum(
                1 for tr in depth if tr.get("k2_recovered") is True)},
        "epoch_rule": {
            "tol_frac_of_duration": k2.EPOCH_TOL_DUR_FRAC,
            "rescued_n": len(rescued),
            "genuine_n": fin_gen,
            "abs_delta_over_d_pass3": epoch_stats},
        "mask": {
            "n_stopped_pass2": len(stopped2),
            "n_stopped_pass3": len(stopped3),
            "stopped_pass2_trials": [
                f"{tr['tic']}_s{tr['sector']:04d}_{tr['trial_id']}"
                for tr in stopped2],
            "stopped_pass3_trials": [
                f"{tr['tic']}_s{tr['sector']:04d}_{tr['trial_id']}"
                for tr in stopped3],
            "comask_triggers": comask,
            "n_comasked": sum(comask.values()),
            "pass3_eligibility_reasons": elig_reasons},
        "alias_veto_pass3": {
            "n_vetoed": len(vetoed3),
            "n_would_be_recovered_but_vetoed": len(vetoed3_would),
            "vetoed_trials": [f"{tr['tic']}_s{tr['sector']:04d}_"
                              f"{tr['trial_id']}" for tr in vetoed3]},
        "pass3_null": {
            "n_pass3_survivors": len(p3_survivors),
            "n_wrong_period_survivors": len(p3_fp)},
        "compute_a18": {
            "total_trial_seconds": round(tot_s, 1),
            "pass1_only_seconds": round(p1_s, 1),
            "ratio_vs_single_pass": (round(ratio, 2)
                                    if ratio is not None else None),
            "bound": 2.5,
            "note": ("Ratio includes estimation + mask time in the "
                     "numerator (conservative); the denominator is "
                     "the pass-1 screen wall on the same trials.")},
        "constants": {
            "epoch_tol_dur_frac": k2.EPOCH_TOL_DUR_FRAC,
            "alias_eps": k2.ALIAS_EPS,
            "alias_mn": list(k2.ALIAS_MN),
            "duty_cycle_cap_primary": k3.CAP_PRIMARY,
            "cap_short_p_d": k3.CAP_SHORT_P_D,
            "cap_short": k3.CAP_SHORT,
            "secondary_queue_cap": k3.SECONDARY_QUEUE_CAP,
            "buffer_depth_pct": k2.BUFFER_DEPTH_PCT,
            "buffer_factor": k2.BUFFER_FACTOR,
            "comask_depth_pct": k2.COMASK_DEPTH_PCT,
            "comask_snr": k2.COMASK_SNR,
            "comask_phase_lo": k2.COMASK_PHASE_LO,
            "comask_phase_hi": k2.COMASK_PHASE_HI,
            "refine_min_gain": k2.REFINE_MIN_GAIN},
    }
    (out_dir / f"k3_summary_{arm}.json").write_text(
        json.dumps(summary, indent=2))
    return summary


def merge_null_k3(out_dir, arm):
    """Aggregate per-host null files into k3_null_summary_<arm>.json.

    Null survivors are counted per ROW (PB-6 §4): a host with both a
    pass-2 and a pass-3 survivor contributes 2 rows. The pipeline's
    output rows are the pass>=2 survivors; the bound (A2) is final
    rows <= 1.25 x pass-1 rows.
    """
    out_dir = Path(out_dir)
    host_files = sorted((out_dir / "null_hosts").glob("*.json"))
    records = []
    for p in host_files:
        try:
            rec = json.loads(p.read_text())
        except ValueError:
            continue
        if rec.get("complete") is True and rec.get("arm") == arm:
            records.append(rec)
    n = len(records)
    p1_s = sum(1 for r in records if r.get("pass1_survivor") is True)
    p2_s = sum(1 for r in records if r.get("pass2_survivor") is True)
    p3_s = sum(1 for r in records if r.get("pass3_survivor") is True)
    final_rows = p2_s + p3_s
    bound_rows = math.ceil(1.25 * p1_s) if p1_s else 0
    stopped2 = sum(1 for r in records
                   if r.get("stopped_pass") == 2)
    stopped3 = sum(1 for r in records
                   if (r.get("k3_mask") or {}).get("stopped") is True)
    no_p1 = sum(1 for r in records
                if r.get("note") == "no-pass1-period")
    summary = {
        "tool": "k3_run", "mode": "null", "arm": arm,
        "n_hosts": n,
        "pass1_survivors": p1_s,
        "pass2_survivors": p2_s,
        "pass3_survivors": p3_s,
        "final_rows": final_rows,
        "bound_rows": bound_rows,
        "bound_verdict": ("PASS" if final_rows <= bound_rows
                          else "FAIL"),
        "pass1_per_1000": (1000.0 * p1_s / n if n else None),
        "pass2_per_1000": (1000.0 * p2_s / n if n else None),
        "final_per_1000": (1000.0 * final_rows / n if n else None),
        "delta_per_1000": (1000.0 * (final_rows - p1_s) / n
                           if n else None),
        "n_stopped_pass2": stopped2,
        "n_stopped_pass3": stopped3,
        "n_no_pass1_period": no_p1,
        "note": ("Final rows = pass-2 + pass-3 survivor rows (per "
                 "ROW, PB-6 section 4); the A2 bound is final rows "
                 "<= 1.25 x pass-1 rows."),
    }
    (out_dir / f"k3_null_summary_{arm}.json").write_text(
        json.dumps(summary, indent=2))
    return summary


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="P4-1b K=3 run: campaign (451 wrong-period "
                    "trials) + null (120 uninjected hosts), per arm.")
    ap.add_argument("--mode", choices=("campaign", "null"),
                    default="campaign")
    ap.add_argument("--arm", choices=k3.ARMS, default="prototype")
    ap.add_argument("--repo", default=str(REPO))
    ap.add_argument("--manifest", default=None,
                    help="oracle_trials.json (campaign mode)")
    ap.add_argument("--artifact-spans", default=None,
                    help="phase2_validation.json (combined arm)")
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
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    cache = Path(args.cache)
    spans = None
    spans_sha = None
    if args.arm == "combined":
        if args.artifact_spans is None:
            raise SystemExit("--artifact-spans is required for "
                             "the combined arm")
        spans, spans_sha = _load_spans(args.artifact_spans)
        print(f"[k3] combined arm: spans sha {spans_sha[:12]}…, "
              f"S96 {len(spans[96])} spans, S95 {len(spans[95])} "
              f"spans", flush=True)

    if args.mode == "campaign":
        if args.manifest is None:
            raise SystemExit("--manifest is required for "
                             "campaign mode")
        manifest = orc._load_manifest(args.manifest)
        (out_dir / "hosts").mkdir(exist_ok=True)
        if args.merge_only:
            summary = merge_campaign_k3(out_dir, manifest, args.arm)
            print(f"[k3] merged {summary['n_hosts_completed']} "
                  f"hosts, {summary['n_trials']} trials, "
                  f"pass2 {summary['k3']['pass2_recovered']} "
                  f"(P4-1a {K2_RECOVERED}), pass3 "
                  f"{summary['k3']['pass3_recovered']}, final "
                  f"{summary['k3']['final_recovered']}, gate "
                  f"{summary['gate']['verdict']}")
            return 0
        hosts = {}
        for tr in manifest["trials"]:
            if tr["group"] not in orc.ORACLE_GROUPS:
                continue
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
                         "keep_fits": args.keep_fits,
                         "arm": args.arm, "spans": spans})
        if args.tics:
            keep = {str(t) for t in args.tics}
            jobs = [j for j in jobs if j["tic"] in keep]
        jobs.sort(key=lambda j: (j["sector"], int(j["tic"])))
        if args.limit_hosts is not None:
            jobs = jobs[:args.limit_hosts]
        print(f"[k3] campaign arm={args.arm}: {len(jobs)} "
              f"host-sectors, "
              f"{sum(len(j['trials']) for j in jobs)} trials, "
              f"{len(missing)} missing FITS", flush=True)
        if args.dry_run:
            return 0
        (out_dir / "injected").mkdir(exist_ok=True)
        t0 = time.time()
        if args.workers <= 1:
            bs.set_calibration(args.calibration)
            results = [run_host_campaign_k3(j) for j in jobs]
        else:
            from multiprocessing import Pool
            with Pool(args.workers, initializer=orc._init_worker,
                      initargs=(args.calibration,)) as pool:
                results = pool.map(run_host_campaign_k3, jobs)
        done = sum(1 for r in results if r["status"] == "done")
        skipped = sum(1 for r in results
                      if r["status"] == "skipped")
        failures = [r for r in results if r["status"] == "error"]
        for r in failures:
            print(f"[k3] ERROR TIC {r['tic']} s{r['sector']:04d}: "
                  f"{r.get('error')}", flush=True)
        summary = merge_campaign_k3(out_dir, manifest, args.arm)
        print(f"[k3] done: {done} run, {skipped} skipped, "
              f"{len(failures)} failed, "
              f"{summary['n_hosts_completed']} hosts merged; "
              f"pass2 {summary['k3']['pass2_recovered']}/"
              f"{summary['n_trials']} (P4-1a {K2_RECOVERED}, "
              f"match={summary['pass2_validation']['matches_p41a']}), "
              f"pass3 {summary['k3']['pass3_recovered']}, final "
              f"{summary['k3']['final_recovered']} "
              f"({summary['k3']['final_genuine']} genuine), "
              f"gate {summary['gate']['verdict']} "
              f"(bar {summary['gate']['bar_rescues']}); "
              f"{time.time() - t0:.0f}s wall")
        return 0 if not failures else 1

    # --- null mode ---
    if args.manifest is None:
        raise SystemExit("--manifest is required for null mode "
                         "(host list)")
    manifest = orc._load_manifest(args.manifest)
    (out_dir / "null_hosts").mkdir(exist_ok=True)
    if args.merge_only:
        summary = merge_null_k3(out_dir, args.arm)
        print(f"[k3] null merged {summary['n_hosts']} hosts, "
              f"pass1 {summary['pass1_survivors']} -> pass2 "
              f"{summary['pass2_survivors']} -> pass3 "
              f"{summary['pass3_survivors']} (final rows "
              f"{summary['final_rows']}, bound "
              f"{summary['bound_rows']}, "
              f"{summary['bound_verdict']})")
        return 0
    hosts = {}
    for tr in manifest["trials"]:
        key = (tr["tic"], tr["sector"])
        hosts.setdefault(key, True)
    jobs = []
    missing = []
    for (tic, sector) in sorted(hosts):
        path = cache / f"s{sector:04d}" / f"{tic}.fits"
        if not path.exists():
            missing.append((tic, sector))
            continue
        jobs.append({"tic": tic, "sector": sector,
                     "path": str(path),
                     "out_dir": str(out_dir),
                     "workdir": str(out_dir / "null_injected"),
                     "calibration": args.calibration,
                     "keep_fits": args.keep_fits,
                     "arm": args.arm, "spans": spans})
    if args.tics:
        keep = {str(t) for t in args.tics}
        jobs = [j for j in jobs if j["tic"] in keep]
    jobs.sort(key=lambda j: (j["sector"], int(j["tic"])))
    if args.limit_hosts is not None:
        jobs = jobs[:args.limit_hosts]
    print(f"[k3] null arm={args.arm}: {len(jobs)} host-sectors, "
          f"{len(missing)} missing FITS", flush=True)
    if args.dry_run:
        return 0
    (out_dir / "null_injected").mkdir(exist_ok=True)
    t0 = time.time()
    if args.workers <= 1:
        bs.set_calibration(args.calibration)
        results = [run_host_null_k3(j) for j in jobs]
    else:
        from multiprocessing import Pool
        with Pool(args.workers, initializer=orc._init_worker,
                  initargs=(args.calibration,)) as pool:
            results = pool.map(run_host_null_k3, jobs)
    done = sum(1 for r in results if r["status"] == "done")
    skipped = sum(1 for r in results
                  if r["status"] == "skipped")
    failures = [r for r in results if r["status"] == "error"]
    for r in failures:
        print(f"[k3] ERROR TIC {r['tic']} s{r['sector']:04d}: "
              f"{r.get('error')}", flush=True)
    summary = merge_null_k3(out_dir, args.arm)
    print(f"[k3] null done: {done} run, {skipped} skipped, "
          f"{len(failures)} failed; pass1 "
          f"{summary['pass1_survivors']} -> pass2 "
          f"{summary['pass2_survivors']} -> pass3 "
          f"{summary['pass3_survivors']} (final rows "
          f"{summary['final_rows']}, bound "
          f"{summary['bound_rows']}, "
          f"{summary['bound_verdict']}); "
          f"{time.time() - t0:.0f}s wall")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
