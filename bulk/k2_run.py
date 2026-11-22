"""P4-1a driver: run the K=2 prototype over the 451 wrong-period trials
(campaign mode) and the 120 uninjected hosts (null mode).

The measurement setup REPRODUCES the PB-1 oracle run (bulk/oracle_run.py)
and reuses its helpers (preprocess_arrays, period_match_class, _subset,
_bootstrap_host_ci, _init_worker, ORACLE_GROUPS) so the only difference
between the oracle bound and the prototype measurement is the ephemeris
source: the oracle masked from a FRESH pass-1 BLS measurement; the
prototype masks from an ephemeris ESTIMATED from the data
(bulk/k2_prototype.estimate_ephemeris), starting only from the RECORDED
pass-1 period. A fresh pass 1 IS still run per trial, but ONLY as a
validation (pass-1 reproduction vs the recorded campaign, exactly as the
oracle did) and as the reference for the estimation-error diagnostic — its
ephemeris is never fed into the mask. The code enforces this: the
estimation call takes (preprocessed arrays, recorded period) and nothing
else.

Campaign mode (the 451 = lockon_207 + depth_148 + wrong165_96):
  inject -> fresh pass 1 (validation only) -> estimate ephemeris from the
  recorded period -> phase-scan the secondary -> build the K=2 mask
  (duty-cycle cap) -> pass 2 on the masked curve -> M-6 recovery, alias
  veto, epoch rule.

Null mode (the 120 uninjected hosts): fresh pass 1 -> estimate from the
fresh period (no recorded uninjected pass 1 exists; the estimation
machinery is identical) -> mask -> pass 2. Reports pass-1 vs pass-2
survivors as a rate per 1,000 stars.

Gate (pre-registered, PB-6): P4-1a PASSES iff k2_recovered >= 23 (50% of
the oracle bound 45). Recovery is M-6 (survivor AND found period within
strict 1% of injected), with alias-vetoed trials excluded. The epoch rule
(period + epoch match) is measured alongside and does not change the gate.

Frozen comparison numbers (PB-1 / PB-2, cited — not re-derived here):
  oracle: 45/451 recovered (lockon 17/207, depth 27/148, wrong165 1/96),
  44/451 genuine under the P4-1a epoch rule (TIC 308208247 s96 planet04
  is a false rescue the epoch rule removes);
  artifact mask: 29/148 depth trials (vs the oracle's 27/148).
"""

import argparse
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
elif os.environ.get("K2_REPO"):
    REPO = Path(os.environ["K2_REPO"]).resolve()
elif _here.parent.name == "bulk" and (
        _here.parent.parent / "bulk_screen.py").exists():
    REPO = _here.parent.parent
else:
    raise SystemExit("k2_run: need --repo (script is outside a "
                     "repo checkout and K2_REPO is unset)")
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))

import numpy as np  # noqa: E402

import bulk_screen as bs  # noqa: E402
from bulk import k2_prototype as k2  # noqa: E402
from bulk import oracle_run as orc  # noqa: E402
from bulk import pass1_carry as p1c  # noqa: E402
from bulk.inject_campaign import check_recovery, inject_trial  # noqa: E402
from bulk.inject_real_s96 import (load_real_fits,  # noqa: E402
                                  write_injected_fits)
from synth_fits import screen_job  # noqa: E402

# Frozen comparison numbers (PB-1 / PB-2 — see module docstring).
ORACLE_RECOVERED = 45
ORACLE_GENUINE = 44
ORACLE_BY_GROUP = {"lockon_207": 17, "depth_148": 27, "wrong165_96": 1}
ARTIFACT_DEPTH_RECOVERED = 29
ARTIFACT_DEPTH_N = 148
K2_BAR = 23  # pre-registered in PB-6: 50% of the oracle bound


def _screen(path, tic, sector):
    # Calibration is global (set by _init_worker / the serial
    # path via bs.set_calibration); screen_job takes no
    # calibration argument.
    return bs._screen_one(screen_job(path, tic, sector))


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


def run_host_campaign(job):
    """One host-sector: inject each of the 451 trials, fresh pass 1
    (validation only), prototype estimation + mask, pass 2, verdicts."""
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
             "epoch_btjd": tr["epoch_btjd"],
             "duration_d": tr["duration_d"],
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
            # --- fresh pass 1: VALIDATION ONLY (never an input to
            # the estimation). Same reproduction check as the oracle.
            p1 = _screen(inj_path, tic, sector)
            r["pass1"] = orc._subset(p1)
            # 5.1 scorer half (S3): the pass-1 epoch delta the
            # any-stage scorer reads (pass1_recovers) — the K=2
            # analog of k3_run's PIPE50-9b recording. Without
            # it, any-stage scoring on K=2 records is vacuous
            # (the scorer derives it from the stored t0 on old
            # records, but new runs record it directly).
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
                # 5.1 design (A) §4.4: no recorded period, no
                # mask, no veto reference — the pass-1 survivor
                # is still carried (the veto is skipped, reason
                # recorded); dropping it would be a silent
                # deletion of exactly the kind §4.7 forbids.
                _carry, _audit = p1c.build_carried_row(
                    r["pass1"],
                    veto_skipped_reason="no-recorded-period")
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
                results.append(r)
                if not keep_fits:
                    os.remove(inj_path)
                continue
            t_p, f_p = orc.preprocess_arrays(t, f_inj, q)
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
            keep, mstats = k2.build_k2_mask(
                t, f_inj, q, ephemeris, rec.get("depth_percent"),
                secondary=secondary)
            r["k2_mask"] = mstats
            if mstats["stopped"]:
                r["pass2"] = None
                r["pass2_match"] = None
                r["alias_veto"] = None
                r["epoch_delta_d"] = None
                r["epoch_match"] = False
                r["k2_recovered"] = False
                r["k2_genuine"] = False
                r["m6_before_veto"] = False
            else:
                mask_path = str(base) + "_k2masked.fits"
                write_injected_fits(mask_path, t[keep], f_inj[keep],
                                    q[keep], fcol)
                p2 = _screen(mask_path, tic, sector)
                r["pass2"] = orc._subset(p2)
                r["pass2_match"] = orc.period_match_class(
                    p2.get("period_days"), tr["period_d"])
                veto = k2.alias_veto(
                    p2.get("period_days"), p2.get("t0_btjd"),
                    ephemeris["period_ref_d"],
                    ephemeris["t0_est_btjd"],
                    mstats["mask_half_width_d"],
                    comask_phase=mstats["secondary_phase"])
                r["alias_veto"] = veto
                m6 = bool(check_recovery(p2, spec["period_d"]))
                r["m6_before_veto"] = m6
                r["k2_recovered"] = bool(m6 and not veto["vetoed"])
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
                if not keep_fits:
                    os.remove(mask_path)
            # 5.1 design (A) §4.4: preserve the pass-1 survivor
            # as a carried final row — in the stopped branch
            # too (§4.4.5: the cap stops the masked re-search,
            # not the preservation; the stopped mask stats
            # carry the half-width, so the alias veto still
            # applies). The veto reference is the ephemeris +
            # mask stats (same as pass-2's veto). No F-2 in
            # this legacy driver — it implements none anywhere
            # (adding it only to carried rows would be
            # inconsistent; adding it to pass-2 would change
            # the closed P4-1a campaign).
            _carry, _audit = p1c.build_carried_row(
                r["pass1"],
                veto_ref=p1c.veto_ref_from(ephemeris, mstats))
            r["pass1_carried"] = _carry
            r["alias_veto_carried"] = _audit["alias_veto"]
            if _carry is not None:
                _carry["deduped_with"] = p1c.dedupe_carried(
                    _carry, r.get("pass2"), None,
                    tr["duration_d"])
            (r["p1_carried_recovered"],
             r["p1_carried_genuine"]) = (
                p1c.carried_recovery_verdict(
                    _carry, _audit["alias_veto"], tr))
            r["final_recovered"] = bool(
                r["k2_recovered"] or r["p1_carried_recovered"])
            r["final_genuine"] = bool(
                r["k2_genuine"] or r["p1_carried_genuine"])
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
    n_k2 = sum(1 for r in results if r.get("k2_recovered") is True)
    return {"status": "done", "tic": tic, "sector": sector,
            "n_trials": len(results), "n_k2_recovered": n_k2}


def run_host_null(job):
    """One host-sector, UNINJECTED: fresh pass 1 -> prototype mask
    (estimated from the fresh period — no recorded uninjected pass 1
    exists) -> pass 2. Per-pass null accounting."""
    tic = job["tic"]
    sector = job["sector"]
    out_dir = Path(job["out_dir"])
    workdir = Path(job["workdir"])
    calibration = job["calibration"]
    keep_fits = job.get("keep_fits", False)
    out_path = out_dir / "null_hosts" / f"{tic}_s{sector:04d}.json"
    if out_path.exists():
        try:
            prev = json.loads(out_path.read_text())
        except ValueError:
            prev = {}
        if prev.get("complete") is True:
            return {"status": "skipped", "tic": tic, "sector": sector}
    t_start = time.time()
    r = {"tic": tic, "sector": sector}
    try:
        t, f, q, fcol, meta = load_real_fits(job["path"])
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "tic": tic, "sector": sector,
                "error": f"load_real_fits: {exc}"}
    try:
        base = workdir / f"{tic}_s{sector:04d}_null"
        raw_path = str(base) + ".fits"
        write_injected_fits(raw_path, t, f, q, fcol)
        p1 = _screen(raw_path, tic, sector)
        r["pass1"] = orc._subset(p1)
        r["pass1_survivor"] = bool(p1.get("status") == "survivor")
        p1_p = p1.get("period_days")
        if p1_p is None:
            r["pass2"] = None
            r["pass2_survivor"] = False
            r["note"] = "no-pass1-period"
        else:
            t_p, f_p = orc.preprocess_arrays(t, f, q)
            ephemeris = k2.estimate_ephemeris(t_p, f_p, p1_p)
            r["ephemeris"] = ephemeris
            secondary = k2.scan_secondary(
                t_p, f_p, ephemeris["period_ref_d"],
                ephemeris["t0_est_btjd"],
                ephemeris["duration_est_d"])
            r["secondary_scan"] = {
                "phase": secondary[0], "depth_frac": secondary[1],
                "snr": secondary[2]}
            keep, mstats = k2.build_k2_mask(
                t, f, q, ephemeris, p1.get("depth_percent"),
                secondary=secondary)
            r["k2_mask"] = mstats
            if mstats["stopped"]:
                r["pass2"] = None
                r["pass2_survivor"] = False
                r["note"] = "stopped-duty-cycle"
            else:
                mask_path = str(base) + "_k2masked.fits"
                write_injected_fits(mask_path, t[keep], f[keep],
                                    q[keep], fcol)
                p2 = _screen(mask_path, tic, sector)
                r["pass2"] = orc._subset(p2)
                r["pass2_survivor"] = bool(
                    p2.get("status") == "survivor")
                if not keep_fits:
                    os.remove(mask_path)
        # 5.1 design (A) §4.4: preserve the pass-1 survivor as
        # a carried final row — in every branch, including
        # stopped (§4.4.5) and no-pass1-period (no carry is
        # possible there; the build returns None). The null
        # leg skips the alias veto (the ephemeris is seeded
        # from pass-1 itself — degenerate, reason recorded).
        # No F-2 in this legacy driver. final_survivor is the
        # carried OR pass-2 survivor; final_rows counts
        # distinct final rows (dedupe applied).
        _carry, _audit = p1c.build_carried_row(
            r["pass1"],
            veto_skipped_reason="null-leg-no-independent-reference")
        r["pass1_carried"] = _carry
        r["alias_veto_carried"] = _audit["alias_veto"]
        _dur = ((_carry or {}).get("duration_hours") or 0) / 24.0
        if _carry is not None:
            _carry["deduped_with"] = p1c.dedupe_carried(
                _carry, r.get("pass2"), None, _dur)
        r["pass1_carried_survivor"] = p1c.carried_survivor(_carry)
        r["final_rows"] = p1c.count_final_rows(
            _carry, r.get("pass2"), None, _dur)
        r["final_survivor"] = bool(
            r["pass1_carried_survivor"] or r["pass2_survivor"])
        if not keep_fits:
            os.remove(raw_path)
    except Exception as exc:  # noqa: BLE001
        r["error"] = f"{type(exc).__name__}: {exc}"
    r["complete"] = True
    r["calibration"] = calibration
    r["seconds"] = round(time.time() - t_start, 1)
    tmp = out_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(r))
    tmp.replace(out_path)
    return {"status": "done", "tic": tic, "sector": sector,
            "pass1_survivor": r.get("pass1_survivor"),
            "pass2_survivor": r.get("pass2_survivor")}


def _stats(vals):
    """Median / p90 / max of a list of floats (None-safe)."""
    v = sorted(x for x in vals if x is not None)
    if not v:
        return {"n": 0, "median": None, "p90": None, "max": None}
    return {"n": len(v),
            "median": float(np.median(v)),
            "p90": float(np.percentile(v, 90)),
            "max": float(max(v))}


def merge_campaign(out_dir, manifest):
    """Aggregate per-host campaign files into k2_summary.json."""
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
    k2_trials = [tr for g in orc.ORACLE_GROUPS
                 for tr in by_group.get(g, [])]
    repro = [tr for tr in trials if tr.get("pass1_repro")]
    n_repro_ok = sum(1 for tr in repro
                     if tr["pass1_repro"].get("ok"))
    recov = sum(1 for tr in k2_trials
                if tr.get("k2_recovered") is True)
    genuine = sum(1 for tr in k2_trials
                  if tr.get("k2_genuine") is True)
    # 5.1: the carried pass-1 row joins the final list, so the
    # final counts (carried OR pass-2) are reported alongside
    # the pre-registered k2 counts — the P4-1a gate still uses
    # k2_recovered only.
    final_recov = sum(1 for tr in k2_trials
                      if tr.get("final_recovered") is True)
    final_genuine = sum(1 for tr in k2_trials
                        if tr.get("final_genuine") is True)
    by_g = {g: {"n": len(by_group.get(g, [])),
                "recovered": sum(
                    1 for tr in by_group.get(g, [])
                    if tr.get("k2_recovered") is True),
                "genuine": sum(
                    1 for tr in by_group.get(g, [])
                    if tr.get("k2_genuine") is True),
                "oracle_recovered": ORACLE_BY_GROUP.get(g),
                "stopped": sum(
                    1 for tr in by_group.get(g, [])
                    if tr.get("k2_mask", {}).get("stopped") is True)}
            for g in orc.ORACLE_GROUPS}
    by_sector = {}
    for tr in k2_trials:
        s = tr["sector"]
        d = by_sector.setdefault(s, {"n": 0, "recovered": 0,
                                     "genuine": 0})
        d["n"] += 1
        d["recovered"] += int(tr.get("k2_recovered") is True)
        d["genuine"] += int(tr.get("k2_genuine") is True)
    eb_hosts = set(manifest.get("eb_hosts", []))
    host_rec = {}
    for rec in records:
        for tr in rec["trials"]:
            if tr["group"] in orc.ORACLE_GROUPS:
                h = host_rec.setdefault(rec["tic"], [0, 0])
                h[0] += 1
                h[1] += int(tr.get("k2_recovered") is True)
    eb = {"n": 0, "recovered": 0}
    non_eb = {"n": 0, "recovered": 0}
    for tic, (n, r) in host_rec.items():
        d = eb if tic in eb_hosts else non_eb
        d["n"] += n
        d["recovered"] += r
    match_counts = {}
    for tr in k2_trials:
        m = tr.get("pass2_match")
        match_counts[m] = match_counts.get(m, 0) + 1
    ci = orc._bootstrap_host_ci(list(host_rec.values()))
    # Epoch rule: how many M-6 rescues also pass it.
    rescued = [tr for tr in k2_trials
               if tr.get("k2_recovered") is True]
    epoch_pass = sum(1 for tr in rescued
                     if tr.get("epoch_match") is True)
    epoch_stats = _stats([tr.get("epoch_delta_over_d")
                          for tr in rescued])
    # Duty-cycle stops, co-mask triggers, alias vetoes.
    stopped = [tr for tr in k2_trials
               if tr.get("k2_mask", {}).get("stopped") is True]
    comask = {}
    for tr in k2_trials:
        m = tr.get("k2_mask", {})
        if m.get("secondary_comasked"):
            t = m.get("comask_trigger")
            comask[t] = comask.get(t, 0) + 1
    vetoed = [tr for tr in k2_trials
              if (tr.get("alias_veto") or {}).get("vetoed") is True]
    vetoed_would_be = [tr for tr in vetoed
                       if tr.get("m6_before_veto") is True]
    # Estimation error (vs the fresh pass 1): rescued vs not.
    not_rescued = [tr for tr in k2_trials
                   if tr.get("k2_recovered") is not True]
    est = {
        "rescued": {
            "abs_t0_d": _stats([abs(tr["est_error_vs_fresh_p1"]["t0_d"])
                                for tr in rescued
                                if tr.get("est_error_vs_fresh_p1")
                                and tr["est_error_vs_fresh_p1"]["t0_d"]
                                is not None]),
            "abs_duration_d": _stats(
                [abs(tr["est_error_vs_fresh_p1"]["duration_d"])
                 for tr in rescued
                 if tr.get("est_error_vs_fresh_p1")
                 and tr["est_error_vs_fresh_p1"]["duration_d"]
                 is not None]),
            "abs_period_frac": _stats(
                [abs(tr["est_error_vs_fresh_p1"]["period_frac"])
                 for tr in rescued
                 if tr.get("est_error_vs_fresh_p1")
                 and tr["est_error_vs_fresh_p1"]["period_frac"]
                 is not None])},
        "not_rescued": {
            "abs_t0_d": _stats([abs(tr["est_error_vs_fresh_p1"]["t0_d"])
                                for tr in not_rescued
                                if tr.get("est_error_vs_fresh_p1")
                                and tr["est_error_vs_fresh_p1"]["t0_d"]
                                is not None]),
            "abs_duration_d": _stats(
                [abs(tr["est_error_vs_fresh_p1"]["duration_d"])
                 for tr in not_rescued
                 if tr.get("est_error_vs_fresh_p1")
                 and tr["est_error_vs_fresh_p1"]["duration_d"]
                 is not None]),
            "abs_period_frac": _stats(
                [abs(tr["est_error_vs_fresh_p1"]["period_frac"])
                 for tr in not_rescued
                 if tr.get("est_error_vs_fresh_p1")
                 and tr["est_error_vs_fresh_p1"]["period_frac"]
                 is not None])},
    }
    n_refined = sum(1 for tr in k2_trials
                    if (tr.get("ephemeris") or {}).get(
                        "period_refined") is True)
    n_low_snr = sum(1 for tr in k2_trials
                    if (tr.get("ephemeris") or {}).get(
                        "low_snr") is True)
    # Pass-2 false positives among the 451 (wrong-period survivors).
    p2_survivors = [tr for tr in k2_trials
                    if (tr.get("pass2") or {}).get("status")
                    == "survivor"]
    p2_fp = [tr for tr in p2_survivors
             if tr.get("k2_recovered") is not True]
    depth = by_group.get("depth_148", [])
    depth_rec = sum(1 for tr in depth
                    if tr.get("k2_recovered") is True)
    summary = {
        "tool": "k2_run", "mode": "campaign",
        "n_hosts_completed": len(records),
        "n_trials": len(k2_trials),
        "pass1_reproduction": {
            "n_checked": len(repro), "n_ok": n_repro_ok,
            "mismatches": [f"{tr['tic']}_s{tr['sector']:04d}_"
                           f"{tr['trial_id']}" for tr in repro
                           if not tr["pass1_repro"].get("ok")]},
        "k2": {
            "recovered": recov, "n": len(k2_trials),
            "rate": (recov / len(k2_trials) if k2_trials else None),
            "genuine": genuine,
            "by_group": by_g, "by_sector": by_sector,
            "eb_hosts_15": eb, "non_eb_hosts": non_eb,
            "pass2_match": match_counts,
            "host_level_ci_95": ci},
        "gate": {
            "bar_rescues": K2_BAR,
            "recovered": recov,
            "verdict": "PASS" if recov >= K2_BAR else "FAIL",
            "rule": ("P4-1a passes iff k2_recovered >= 23 (50% of "
                     "the oracle bound 45, pre-registered in PB-6); "
                     "recovery is M-6 with alias-vetoed trials "
                     "excluded")},
        "vs_oracle": {
            "oracle_recovered": ORACLE_RECOVERED,
            "oracle_genuine": ORACLE_GENUINE,
            "k2_recovered": recov,
            "k2_genuine": genuine,
            "final_recovered": final_recov,
            "final_genuine": final_genuine,
            "fraction_of_oracle_bound": (
                recov / ORACLE_RECOVERED if ORACLE_RECOVERED
                else None)},
        "vs_artifact_depth": {
            "n": len(depth),
            "k2_recovered": depth_rec,
            "artifact_recovered": ARTIFACT_DEPTH_RECOVERED,
            "oracle_recovered": ORACLE_BY_GROUP["depth_148"]},
        "epoch_rule": {
            "tol_frac_of_duration": k2.EPOCH_TOL_DUR_FRAC,
            "rescued_n": len(rescued),
            "epoch_pass_among_rescued": epoch_pass,
            "abs_delta_over_d": epoch_stats,
            "genuine_n": genuine},
        "estimation": {
            "n_period_refined": n_refined,
            "n_low_snr": n_low_snr,
            "error_vs_fresh_p1": est},
        "mask": {
            "n_stopped_duty_cycle": len(stopped),
            "stopped_trials": [f"{tr['tic']}_s{tr['sector']:04d}_"
                               f"{tr['trial_id']}" for tr in stopped],
            "comask_triggers": comask,
            "n_comasked": sum(comask.values())},
        "alias_veto": {
            "n_vetoed": len(vetoed),
            "n_would_be_recovered_but_vetoed": len(vetoed_would_be),
            "vetoed_trials": [f"{tr['tic']}_s{tr['sector']:04d}_"
                              f"{tr['trial_id']}" for tr in vetoed]},
        "pass2_null": {
            "n_pass2_survivors": len(p2_survivors),
            "n_wrong_period_survivors": len(p2_fp)},
        "constants": {
            "epoch_tol_dur_frac": k2.EPOCH_TOL_DUR_FRAC,
            "alias_eps": k2.ALIAS_EPS,
            "alias_mn": list(k2.ALIAS_MN),
            "duty_cycle_cap": k2.DUTY_CYCLE_CAP,
            "buffer_depth_pct": k2.BUFFER_DEPTH_PCT,
            "buffer_factor": k2.BUFFER_FACTOR,
            "comask_depth_pct": k2.COMASK_DEPTH_PCT,
            "comask_snr": k2.COMASK_SNR,
            "comask_phase_lo": k2.COMASK_PHASE_LO,
            "comask_phase_hi": k2.COMASK_PHASE_HI,
            "refine_min_gain": k2.REFINE_MIN_GAIN},
    }
    (out_dir / "k2_summary.json").write_text(
        json.dumps(summary, indent=2))
    return summary


def merge_null(out_dir):
    """Aggregate per-host null files into k2_null_summary.json."""
    out_dir = Path(out_dir)
    host_files = sorted((out_dir / "null_hosts").glob("*.json"))
    records = []
    for p in host_files:
        try:
            rec = json.loads(p.read_text())
        except ValueError:
            continue
        if rec.get("complete") is True:
            records.append(rec)
    n = len(records)
    p1_s = sum(1 for r in records if r.get("pass1_survivor") is True)
    p2_s = sum(1 for r in records if r.get("pass2_survivor") is True)
    # 5.1: the carried pass-1 row joins the final list.
    p1c_s = sum(1 for r in records
                if r.get("pass1_carried_survivor") is True)
    fin_s = sum(1 for r in records
                if r.get("final_survivor") is True)
    fin_rows = sum(int(r.get("final_rows") or 0) for r in records)
    stopped = sum(1 for r in records
                  if (r.get("k2_mask") or {}).get("stopped") is True)
    no_p1 = sum(1 for r in records
                if r.get("note") == "no-pass1-period")
    summary = {
        "tool": "k2_run", "mode": "null",
        "n_hosts": n,
        "pass1_survivors": p1_s,
        "pass2_survivors": p2_s,
        "pass1_carried_survivors": p1c_s,
        "final_survivors": fin_s,
        "final_rows": fin_rows,
        "pass1_per_1000": (1000.0 * p1_s / n if n else None),
        "pass2_per_1000": (1000.0 * p2_s / n if n else None),
        "final_per_1000": (1000.0 * fin_rows / n if n else None),
        "delta_per_1000": (1000.0 * (p2_s - p1_s) / n if n else None),
        "n_stopped_duty_cycle": stopped,
        "n_no_pass1_period": no_p1,
        "note": ("Pass 2 is the prototype mask-and-re-search on the "
                 "uninjected curve; the null bound (<= +25% vs "
                 "pass 1) is 4-1b's (PB-6 A2), reported here as "
                 "context only."),
    }
    (out_dir / "k2_null_summary.json").write_text(
        json.dumps(summary, indent=2))
    return summary


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="P4-1a K=2 prototype run: campaign (451 "
                    "wrong-period trials) + null (120 uninjected "
                    "hosts).")
    ap.add_argument("--mode", choices=("campaign", "null"),
                    default="campaign")
    ap.add_argument("--repo", default=str(REPO))
    ap.add_argument("--manifest", default=None,
                    help="oracle_trials.json (campaign mode)")
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

    if args.mode == "campaign":
        if args.manifest is None:
            raise SystemExit("--manifest is required for "
                             "campaign mode")
        manifest = orc._load_manifest(args.manifest)
        (out_dir / "hosts").mkdir(exist_ok=True)
        if args.merge_only:
            summary = merge_campaign(out_dir, manifest)
            print(f"[k2] merged {summary['n_hosts_completed']} "
                  f"hosts, {summary['n_trials']} trials, "
                  f"{summary['k2']['recovered']} recovered, "
                  f"gate {summary['gate']['verdict']}")
            return 0
        # resolve host-sectors from the manifest (451 trials only)
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
                         "keep_fits": args.keep_fits})
        if args.tics:
            keep = {str(t) for t in args.tics}
            jobs = [j for j in jobs if j["tic"] in keep]
        jobs.sort(key=lambda j: (j["sector"], int(j["tic"])))
        if args.limit_hosts is not None:
            jobs = jobs[:args.limit_hosts]
        print(f"[k2] campaign: {len(jobs)} host-sectors, "
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
            with Pool(args.workers, initializer=orc._init_worker,
                      initargs=(args.calibration,)) as pool:
                results = pool.map(run_host_campaign, jobs)
        done = sum(1 for r in results if r["status"] == "done")
        skipped = sum(1 for r in results
                      if r["status"] == "skipped")
        failures = [r for r in results if r["status"] == "error"]
        for r in failures:
            print(f"[k2] ERROR TIC {r['tic']} s{r['sector']:04d}: "
                  f"{r.get('error')}", flush=True)
        summary = merge_campaign(out_dir, manifest)
        print(f"[k2] done: {done} run, {skipped} skipped, "
              f"{len(failures)} failed, "
              f"{summary['n_hosts_completed']} hosts merged; "
              f"K2 {summary['k2']['recovered']}/"
              f"{summary['n_trials']} recovered "
              f"({summary['k2']['genuine']} genuine), "
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
        summary = merge_null(out_dir)
        print(f"[k2] null merged {summary['n_hosts']} hosts, "
              f"pass1 {summary['pass1_survivors']} -> pass2 "
              f"{summary['pass2_survivors']} survivors "
              f"({summary['delta_per_1000']}/1000)")
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
                     "keep_fits": args.keep_fits})
    if args.tics:
        keep = {str(t) for t in args.tics}
        jobs = [j for j in jobs if j["tic"] in keep]
    jobs.sort(key=lambda j: (j["sector"], int(j["tic"])))
    if args.limit_hosts is not None:
        jobs = jobs[:args.limit_hosts]
    print(f"[k2] null: {len(jobs)} host-sectors, "
          f"{len(missing)} missing FITS", flush=True)
    if args.dry_run:
        return 0
    (out_dir / "null_injected").mkdir(exist_ok=True)
    t0 = time.time()
    if args.workers <= 1:
        bs.set_calibration(args.calibration)
        results = [run_host_null(j) for j in jobs]
    else:
        from multiprocessing import Pool
        with Pool(args.workers, initializer=orc._init_worker,
                  initargs=(args.calibration,)) as pool:
            results = pool.map(run_host_null, jobs)
    done = sum(1 for r in results if r["status"] == "done")
    skipped = sum(1 for r in results if r["status"] == "skipped")
    failures = [r for r in results if r["status"] == "error"]
    for r in failures:
        print(f"[k2] ERROR TIC {r['tic']} s{r['sector']:04d}: "
              f"{r.get('error')}", flush=True)
    summary = merge_null(out_dir)
    print(f"[k2] null done: {done} run, {skipped} skipped, "
          f"{len(failures)} failed; pass1 "
          f"{summary['pass1_survivors']} -> pass2 "
          f"{summary['pass2_survivors']} survivors "
          f"(delta {summary['delta_per_1000']}/1000); "
          f"{time.time() - t0:.0f}s wall")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
