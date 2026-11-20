"""Stage 5 (a) frozen-set parity harness — Phase 4.1 completion vote.

Runs the unified K=3 driver (bulk/k3_driver.run_k3_star) UNFILTERED
on the frozen P4-1b campaign trials (451, oracle_trials.json) and
scores per-trial parity against the frozen P4-1b prototype results:
69/451 final rescues, the 52 K=2 rescues preserved with ZERO
regressions, pass-1 reproduction 451/451. EVERY discordance is
listed with a diagnosis — matching totals alone are not accepted
(PHASE41_PREREG section 2.1 (a)).

Design notes (read before changing the scoring):
- The harness reproduces the campaign's per-trial flow exactly
  (k3_run.run_host_campaign_k3): inject the planet, write the
  injected FITS, fresh pass 1 (VALIDATION ONLY — the ephemeris is
  estimated from the FROZEN recorded period, never the fresh
  pass 1), then hand the injected FITS + frozen recorded record to
  run_k3_star. The driver loads the FITS from the job path, so the
  injected FITS is what it screens — the same data the campaign's
  pass 2/3 saw.
- Scoring reuses the campaign's own rules on the driver's subsets:
  check_recovery (status survivor AND period within 1%) +
  alias veto + epoch_match. check_recovery reads only status +
  period_days, both carried by orc._subset — the subset is
  sufficient, and the harness asserts that on every trial.
- KNOWN DIVERGENCE (by design, DRIVER_411A section 1.1): the
  campaign short-circuits pass 3 when pass 2 rescues
  ("pass2-rescued"); the driver always calls _run_pass3 with
  p2_rescued=False (the null-leg rule — production has no
  injected planet), so on pass-2-rescued trials the driver RUNS
  pass 3 where the campaign did not. That changes the audit
  trail (eligibility reason, extra compute), never the verdict:
  final = k2 OR k3, and k2_recovered=True already settles it.
  The harness flags these trials (driver_pass3_extra=True) and
  the scorer treats the extra pass-3 run as EXPECTED, not a
  discordance. What IS a discordance: any difference in
  final_recovered / final_genuine / k2_recovered vs frozen.
- The P4-3b leg (272 trials, 25/272 stitched recoveries) is NOT
  run through run_k3_star: 4.1-1b (stacking in the driver) was
  never built, so no driver path exists for stitched trials.
  That leg is verified by running the campaign code
  (bulk/p43_run, P4-3b rule, flag-off) at the current tip and
  scoring it here (--mode p43-score). The scope limitation is
  recorded in STAGE5_ACCEPTANCE_RECORD.md, not hidden.
- A control run (k3_run.main, campaign, prototype arm, current
  tip) separates code drift from wiring: driver==control!=frozen
  is drift (explained via the control diff); driver!=control is
  a wiring issue. Run the control first; this module's scorer
  accepts an optional --control-dir and reports the three-way
  comparison.
"""

import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
import sys
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import bulk_screen as bs  # noqa: E402
from bulk import k2_prototype as k2  # noqa: E402
from bulk import k3_driver as k3d  # noqa: E402
from bulk import k3_run as k3run  # noqa: E402
from bulk import oracle_run as orc  # noqa: E402
from bulk.inject_campaign import check_recovery, inject_trial  # noqa: E402
from bulk.inject_real_s96 import (load_real_fits,  # noqa: E402
                                  write_injected_fits)
from provenance import SCHEMA_VERSION  # noqa: E402

HARNESS_VERSION = "stage5-a-1.0"
K3_FROZEN_FINAL = 69
K3_FROZEN_K2 = 52
K3_FROZEN_N = 451
P43_FROZEN_FINAL = 25
P43_FROZEN_N = 272


def _prov(git_sha):
    """Minimal valid provenance header for the driver's emitted
    rows (built literally: the Mac run dir is a git-archive
    extract, not a repo, so provenance.git_sha() cannot run)."""
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": "stage5-a-k3",
        "pipeline_git_sha": git_sha,
        "calibration_version": {"bulk": "v4"},
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
    }


def _trial_key(tic, sector, trial_id):
    return f"{tic}-s{int(sector):04d}-{trial_id}"


def _score_pass(screen_subset, veto, period_d, epoch_btjd,
                duration_d):
    """The campaign's recovery scoring on one pass subset.
    Returns (recovered, genuine, match, epoch_delta, epoch_match).
    """
    if screen_subset is None:
        return False, False, None, None, False
    # check_recovery reads status + period_days only — assert the
    # subset carries them (a subset without them is a bug, not a
    # miss).
    assert "status" in screen_subset and "period_days" in screen_subset
    m6 = bool(check_recovery(screen_subset, period_d))
    recovered = bool(m6 and not (veto or {}).get("vetoed"))
    delta = k2.epoch_delta(screen_subset.get("t0_btjd"), epoch_btjd,
                           period_d)
    ematch = bool(k2.epoch_match(delta, duration_d))
    genuine = bool(recovered and ematch)
    match = orc.period_match_class(screen_subset.get("period_days"),
                                   period_d)
    return recovered, genuine, match, delta, ematch


def run_host_driver_k3(job):
    """One host-sector: inject each frozen trial, fresh pass 1
    (validation), then the DRIVER (run_k3_star, unfiltered) on
    the injected FITS + frozen recorded record. Mirrors
    k3_run.run_host_campaign_k3's record shape."""
    tic = job["tic"]
    sector = job["sector"]
    out_dir = Path(job["out_dir"])
    workdir = Path(job["workdir"])
    manifest_sha = job["manifest_sha"]
    keep_fits = job.get("keep_fits", False)
    prov = job["prov"]
    out_path = out_dir / "hosts" / f"{tic}_s{sector:04d}.json"
    if out_path.exists():
        try:
            prev = json.loads(out_path.read_text())
        except ValueError:
            prev = {}
        if (prev.get("complete") is True
                and prev.get("manifest_sha") == manifest_sha
                and prev.get("arm") == "prototype"
                and prev.get("harness") == HARNESS_VERSION):
            return {"status": "skipped", "tic": tic, "sector": sector}
    t_start = time.time()
    try:
        t, f, q, fcol, _meta = load_real_fits(job["path"])
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
             "recorded": tr["recorded"], "arm": "prototype"}
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
            # --- fresh pass 1: VALIDATION ONLY (never an input
            # to the driver — the driver gets the FROZEN record,
            # exactly as the campaign estimates from it).
            t_p1 = time.time()
            p1 = k3run._screen(inj_path, tic, sector)
            r["seconds_pass1"] = round(time.time() - t_p1, 2)
            r["pass1"] = orc._subset(p1)
            rec = tr["recorded"]
            p_rec = rec.get("period_days")
            s_rec = rec.get("sde")
            p1_p = p1.get("period_days")
            p1_s = p1.get("sde")
            p_err = (abs(p1_p - p_rec) / p_rec
                     if p_rec and p1_p else None)
            s_err = (abs(p1_s - s_rec) / max(s_rec, 1.0)
                     if s_rec is not None and p1_s is not None
                     else None)
            r["pass1_repro"] = {
                "period_rel_err": p_err, "sde_rel_err": s_err,
                "ok": bool(p_err is not None and p_err < 0.01
                           and s_err is not None and s_err < 0.02)}
            if p_rec is None:
                r["error"] = "no-recorded-period"
                results.append(r)
                if not keep_fits:
                    os.remove(inj_path)
                continue
            # --- the DRIVER, unfiltered: injected FITS + frozen
            # recorded record (the campaign's estimation input).
            detail = k3d.run_k3_star({
                "tic": tic, "sector": sector, "path": inj_path,
                "pass1": rec, "meta": {},
                "workdir": str(workdir), "keep_fits": keep_fits,
                "prov": prov})
            if detail.get("error"):
                r["error"] = f"driver: {detail['error']}"
                r["driver_detail"] = {
                    k: v for k, v in detail.items()
                    if k not in ("rows",)}
                results.append(r)
                if not keep_fits:
                    os.remove(inj_path)
                continue
            r["ephemeris"] = detail.get("ephemeris")
            r["secondary_scan"] = detail.get("secondary_scan")
            r["k2_mask"] = detail.get("k2_mask")
            r["stopped_pass"] = detail.get("stopped_pass")
            r["pass3_eligibility"] = detail.get("pass3_eligibility")
            r["k3_ephemeris"] = detail.get("k3_ephemeris")
            r["k3_secondary_scan"] = detail.get("k3_secondary_scan")
            r["k3_mask"] = detail.get("k3_mask")
            r["alias_veto_pass3"] = detail.get("alias_veto_pass3")
            # --- score pass 2 with the campaign's rules.
            p2 = detail.get("pass2")
            r["pass2"] = p2
            r["alias_veto"] = detail.get("alias_veto")
            (r["k2_recovered"], r["k2_genuine"], r["pass2_match"],
             r["epoch_delta_d"], r["epoch_match"]) = _score_pass(
                p2, detail.get("alias_veto"), tr["period_d"],
                tr["epoch_btjd"], tr["duration_d"])
            r["m6_before_veto"] = bool(
                p2 is not None
                and check_recovery(p2, tr["period_d"]))
            r["epoch_delta_over_d"] = (
                abs(r["epoch_delta_d"]) / tr["duration_d"]
                if r["epoch_delta_d"] is not None else None)
            # --- score pass 3 with the campaign's rules. The
            # driver ran _run_pass3 with period_inj=None, so its
            # own k3_recovered is always False — the harness
            # scores from the subset + veto, identically to the
            # campaign's computation inside _run_pass3.
            p3 = detail.get("pass3")
            r["pass3"] = p3
            (r["k3_recovered"], r["k3_genuine"], r["pass3_match"],
             r["epoch_delta_d_pass3"],
             r["epoch_match_pass3"]) = _score_pass(
                p3, detail.get("alias_veto_pass3"), tr["period_d"],
                tr["epoch_btjd"], tr["duration_d"])
            r["m6_pass3_before_veto"] = bool(
                p3 is not None
                and check_recovery(p3, tr["period_d"]))
            r["epoch_delta_over_d_pass3"] = (
                abs(r["epoch_delta_d_pass3"]) / tr["duration_d"]
                if r["epoch_delta_d_pass3"] is not None else None)
            # Expected divergence (see module docstring): the
            # driver runs pass 3 on pass-2-rescued trials; the
            # campaign short-circuits. Flag it, never score it.
            r["driver_pass3_extra"] = bool(
                r["k2_recovered"] and p3 is not None)
            r["final_recovered"] = bool(
                r["k2_recovered"] or r["k3_recovered"])
            r["final_genuine"] = bool(
                r["k2_genuine"] or r["k3_genuine"])
            if not keep_fits:
                os.remove(inj_path)
        except Exception as exc:  # noqa: BLE001
            r["error"] = f"{type(exc).__name__}: {exc}"
        r["seconds"] = round(time.time() - t_tr, 2)
        results.append(r)
    rec = {"tic": tic, "sector": sector, "complete": True,
           "manifest_sha": manifest_sha, "calibration": "bulk_v4",
           "arm": "prototype", "harness": HARNESS_VERSION,
           "n_trials": len(results),
           "seconds": round(time.time() - t_start, 1),
           "trials": results}
    tmp = out_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(rec))
    tmp.replace(out_path)
    n_fin = sum(1 for r in results if r.get("final_recovered") is True)
    return {"status": "done", "tic": tic, "sector": sector,
            "n_trials": len(results), "n_final_recovered": n_fin}


def _load_trial_verdicts(hosts_dir, subdir="hosts"):
    """{trial_key: {final_recovered, final_genuine,
    k2_recovered, k2_genuine, pass1_repro_ok, trial}} from host
    files. `trial` is the full record (for discordance
    diagnosis)."""
    out = {}
    for path in sorted((Path(hosts_dir) / subdir).glob("*.json")):
        d = json.loads(path.read_text())
        for tr in d.get("trials", []):
            key = _trial_key(tr["tic"], tr["sector"],
                             tr["trial_id"])
            out[key] = {
                "final_recovered": tr.get("final_recovered"),
                "final_genuine": tr.get("final_genuine"),
                "k2_recovered": tr.get("k2_recovered"),
                "k2_genuine": tr.get("k2_genuine"),
                "pass1_repro_ok": (tr.get("pass1_repro") or {}).get(
                    "ok"),
                "trial": tr}
    return out


def _diagnose(key, mine, ref):
    """One-line diagnosis for a discordant trial: where do the
    driver and frozen runs first differ?"""
    mt, rt = mine["trial"], ref["trial"]
    bits = []
    if mine["pass1_repro_ok"] is not True:
        bits.append(
            f"pass1_repro FAIL (mine ok={mine['pass1_repro_ok']}, "
            f"frozen ok={ref['pass1_repro_ok']})")
    mp2, rp2 = mt.get("pass2"), rt.get("pass2")
    if (mp2 is None) != (rp2 is None):
        bits.append(f"pass2 presence mine={mp2 is not None} "
                    f"frozen={rp2 is not None} "
                    f"(stopped mine={mt.get('stopped_pass')} "
                    f"frozen={rt.get('stopped_pass')})")
    elif mp2 is not None:
        if mp2.get("period_days") != rp2.get("period_days"):
            bits.append(
                f"pass2 period mine={mp2.get('period_days')} "
                f"frozen={rp2.get('period_days')}")
        if mp2.get("status") != rp2.get("status"):
            bits.append(
                f"pass2 status mine={mp2.get('status')} "
                f"frozen={rp2.get('status')}")
        if mp2.get("sde") != rp2.get("sde"):
            bits.append(
                f"pass2 sde mine={mp2.get('sde')} "
                f"frozen={rp2.get('sde')}")
        mv = (mt.get("alias_veto") or {}).get("vetoed")
        rv = (rt.get("alias_veto") or {}).get("vetoed")
        if mv != rv:
            bits.append(f"pass2 veto mine={mv} frozen={rv}")
    mp3, rp3 = mt.get("pass3"), rt.get("pass3")
    if (mp3 is None) != (rp3 is None) and not mt.get(
            "driver_pass3_extra"):
        bits.append(
            f"pass3 presence mine={mp3 is not None} "
            f"frozen={rp3 is not None} "
            f"(elig mine={(mt.get('pass3_eligibility') or {}).get('reason')} "
            f"frozen={(rt.get('pass3_eligibility') or {}).get('reason')})")
    elif mp3 is not None and rp3 is not None:
        if mp3.get("period_days") != rp3.get("period_days"):
            bits.append(
                f"pass3 period mine={mp3.get('period_days')} "
                f"frozen={rp3.get('period_days')}")
        if mp3.get("status") != rp3.get("status"):
            bits.append(
                f"pass3 status mine={mp3.get('status')} "
                f"frozen={rp3.get('status')}")
    return "; ".join(bits) if bits else "no field-level difference found"


def score_k3(run_dir, frozen_dir, control_dir=None):
    """Compare the driver run against the frozen P4-1b reference
    (and, when given, the current-tip campaign control). Returns
    the summary dict; prints the verdict table."""
    mine = _load_trial_verdicts(run_dir)
    ref = _load_trial_verdicts(frozen_dir)
    ctrl = (_load_trial_verdicts(control_dir)
            if control_dir else None)
    assert len(ref) == K3_FROZEN_N, (
        f"frozen set has {len(ref)} trials, expected "
        f"{K3_FROZEN_N}")
    assert set(mine) == set(ref), (
        f"trial-key mismatch: mine-only "
        f"{sorted(set(mine) - set(ref))[:5]}, frozen-only "
        f"{sorted(set(ref) - set(mine))[:5]}")
    n_fin_mine = sum(1 for v in mine.values()
                     if v["final_recovered"] is True)
    n_fin_ref = sum(1 for v in ref.values()
                    if v["final_recovered"] is True)
    n_gen_mine = sum(1 for v in mine.values()
                     if v["final_genuine"] is True)
    n_k2_mine = sum(1 for v in mine.values()
                    if v["k2_recovered"] is True)
    n_k2_ref = sum(1 for v in ref.values()
                   if v["k2_recovered"] is True)
    fin_mine = {k for k, v in mine.items()
                if v["final_recovered"] is True}
    fin_ref = {k for k, v in ref.items()
               if v["final_recovered"] is True}
    k2_mine = {k for k, v in mine.items()
               if v["k2_recovered"] is True}
    k2_ref = {k for k, v in ref.items()
              if v["k2_recovered"] is True}
    repro_mine = sum(1 for v in mine.values()
                     if v["pass1_repro_ok"] is True)
    disc = []
    for key in sorted(ref):
        m, r = mine[key], ref[key]
        if (m["final_recovered"] != r["final_recovered"]
                or m["final_genuine"] != r["final_genuine"]
                or m["k2_recovered"] != r["k2_recovered"]):
            entry = {"trial": key,
                     "mine": {k: m[k] for k in (
                         "final_recovered", "final_genuine",
                         "k2_recovered")},
                     "frozen": {k: r[k] for k in (
                         "final_recovered", "final_genuine",
                         "k2_recovered")},
                     "diagnosis": _diagnose(key, m, r)}
            if ctrl is not None and key in ctrl:
                c = ctrl[key]
                entry["control"] = {k: c[k] for k in (
                    "final_recovered", "final_genuine",
                    "k2_recovered")}
                entry["control_agrees_with"] = (
                    "driver" if (c["final_recovered"]
                                 == m["final_recovered"]
                                 and c["k2_recovered"]
                                 == m["k2_recovered"])
                    else ("frozen" if (c["final_recovered"]
                                       == r["final_recovered"]
                                       and c["k2_recovered"]
                                       == r["k2_recovered"])
                          else "neither"))
            disc.append(entry)
    n_extra_p3 = sum(
        1 for v in mine.values()
        if v["trial"].get("driver_pass3_extra") is True)
    n_err = sum(1 for v in mine.values()
                if "error" in v["trial"])
    summary = {
        "harness": HARNESS_VERSION,
        "n_trials": len(mine),
        "final_recovered": {"driver": n_fin_mine,
                            "frozen": n_fin_ref,
                            "target": K3_FROZEN_FINAL},
        "final_genuine": {"driver": n_gen_mine,
                          "frozen": sum(
                              1 for v in ref.values()
                              if v["final_genuine"] is True)},
        "k2_recovered": {"driver": n_k2_mine,
                         "frozen": n_k2_ref,
                         "target": K3_FROZEN_K2},
        "final_set_identical": fin_mine == fin_ref,
        "final_gained": sorted(fin_mine - fin_ref),
        "final_lost": sorted(fin_ref - fin_mine),
        "k2_set_identical": k2_mine == k2_ref,
        "k2_gained": sorted(k2_mine - k2_ref),
        "k2_lost": sorted(k2_ref - k2_mine),
        "pass1_repro_ok": repro_mine,
        "pass1_repro_target": K3_FROZEN_N,
        "n_discordances": len(disc),
        "discordances": disc,
        "n_driver_pass3_extra_expected": n_extra_p3,
        "n_errors": n_err,
    }
    summary["verdict"] = (
        "PASS" if (fin_mine == fin_ref and k2_mine == k2_ref
                   and repro_mine == K3_FROZEN_N and n_err == 0)
        else "FAIL")
    return summary


def score_p43(run_dir, frozen_dir):
    """Compare a current-tip P4-3b campaign run against the frozen
    P4-3b reference (25/272 stitched recoveries, same trials)."""
    mine = _load_trial_verdicts(run_dir, subdir="hosts-p43")
    ref = _load_trial_verdicts(frozen_dir, subdir="hosts-p43")
    assert len(ref) == P43_FROZEN_N, (
        f"frozen P4-3b set has {len(ref)} trials, expected "
        f"{P43_FROZEN_N}")
    assert set(mine) == set(ref), (
        f"trial-key mismatch: mine-only "
        f"{sorted(set(mine) - set(ref))[:5]}, frozen-only "
        f"{sorted(set(ref) - set(mine))[:5]}")
    fin_mine = {k for k, v in mine.items()
                if v["final_recovered"] is True}
    fin_ref = {k for k, v in ref.items()
               if v["final_recovered"] is True}
    disc = []
    for key in sorted(fin_mine ^ fin_ref):
        m, r = mine[key], ref[key]
        mt, rt = m["trial"], r["trial"]
        mp2, rp2 = mt.get("pass2"), rt.get("pass2")
        diag = []
        if (mp2 is None) != (rp2 is None):
            diag.append(f"stitched pass2 presence mine={mp2 is not None} "
                        f"frozen={rp2 is not None}")
        elif mp2 is not None:
            if mp2.get("period_days") != rp2.get("period_days"):
                diag.append(
                    f"pass2 period mine={mp2.get('period_days')} "
                    f"frozen={rp2.get('period_days')}")
            if mp2.get("status") != rp2.get("status"):
                diag.append(
                    f"pass2 status mine={mp2.get('status')} "
                    f"frozen={rp2.get('status')}")
        disc.append({"trial": key,
                     "mine_final": m["final_recovered"],
                     "frozen_final": r["final_recovered"],
                     "diagnosis": "; ".join(diag) or
                     "no field-level difference found"})
    n_err = sum(1 for v in mine.values() if "error" in v["trial"])
    summary = {
        "harness": HARNESS_VERSION,
        "leg": "p43b-campaign-code",
        "n_trials": len(mine),
        "final_recovered": {"current_tip": len(fin_mine),
                            "frozen": len(fin_ref),
                            "target": P43_FROZEN_FINAL},
        "final_set_identical": fin_mine == fin_ref,
        "final_gained": sorted(fin_mine - fin_ref),
        "final_lost": sorted(fin_ref - fin_mine),
        "n_discordances": len(disc),
        "discordances": disc,
        "n_errors": n_err,
    }
    summary["verdict"] = (
        "PASS" if (fin_mine == fin_ref and n_err == 0) else "FAIL")
    return summary


def _build_k3_jobs(manifest, cache, out_dir, workdir, prov,
                   tics=None, limit_hosts=None):
    hosts = {}
    for tr in manifest["trials"]:
        if tr["group"] not in orc.ORACLE_GROUPS:
            continue
        key = (tr["tic"], tr["sector"])
        hosts.setdefault(key, []).append(tr)
    jobs, missing = [], []
    for (tic, sector), trs in sorted(hosts.items()):
        path = Path(cache) / f"s{int(sector):04d}" / f"{tic}.fits"
        if not path.exists():
            missing.append((tic, sector))
            continue
        jobs.append({"tic": tic, "sector": sector,
                     "path": str(path), "trials": trs,
                     "out_dir": str(out_dir),
                     "workdir": str(workdir),
                     "manifest_sha": manifest["_sha256"],
                     "prov": prov})
    if tics:
        keep = {str(t) for t in tics}
        jobs = [j for j in jobs if j["tic"] in keep]
    jobs.sort(key=lambda j: (j["sector"], int(j["tic"])))
    if limit_hosts is not None:
        jobs = jobs[:limit_hosts]
    return jobs, missing


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Stage 5 (a) frozen-set parity harness: the K=3 "
                    "driver (run_k3_star, unfiltered) on the frozen "
                    "451 P4-1b trials + scoring vs frozen (+control); "
                    "and P4-3b scoring (campaign code at current tip).")
    ap.add_argument("--mode", choices=("k3", "k3-score",
                                       "p43-score"),
                    default="k3")
    ap.add_argument("--manifest", default=None,
                    help="oracle_trials.json (k3 mode)")
    ap.add_argument("--cache", default=None,
                    help="cache root holding s<NNNN>/<tic>.fits")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--frozen-dir", default=None,
                    help="frozen reference run dir (scoring)")
    ap.add_argument("--control-dir", default=None,
                    help="current-tip campaign control dir (k3-score)")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--calibration", default="bulk_v4")
    ap.add_argument("--git-sha", default="worktree-tip",
                    help="pipeline sha stamped on emitted rows")
    ap.add_argument("--tics", nargs="*", default=None)
    ap.add_argument("--limit-hosts", type=int, default=None)
    ap.add_argument("--keep-fits", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.mode == "k3-score":
        if not args.frozen_dir:
            raise SystemExit("--frozen-dir is required for k3-score")
        s = score_k3(out_dir, args.frozen_dir, args.control_dir)
        (out_dir / "stage5_k3_summary.json").write_text(
            json.dumps(s, indent=1))
        print(f"[stage5] k3-score: final {s['final_recovered']} "
              f"k2 {s['k2_recovered']} repro "
              f"{s['pass1_repro_ok']}/{s['pass1_repro_target']} "
              f"discordances {s['n_discordances']} "
              f"verdict {s['verdict']}")
        return 0 if s["verdict"] == "PASS" else 1
    if args.mode == "p43-score":
        if not args.frozen_dir:
            raise SystemExit("--frozen-dir is required for p43-score")
        s = score_p43(out_dir, args.frozen_dir)
        (out_dir / "stage5_p43_summary.json").write_text(
            json.dumps(s, indent=1))
        print(f"[stage5] p43-score: final {s['final_recovered']} "
              f"discordances {s['n_discordances']} "
              f"verdict {s['verdict']}")
        return 0 if s["verdict"] == "PASS" else 1

    # --- k3 run mode ---
    if args.manifest is None or args.cache is None:
        raise SystemExit("--manifest and --cache are required for "
                         "k3 mode")
    manifest = orc._load_manifest(args.manifest)
    (out_dir / "hosts").mkdir(exist_ok=True)
    (out_dir / "injected").mkdir(exist_ok=True)
    prov = _prov(args.git_sha)
    jobs, missing = _build_k3_jobs(
        manifest, args.cache, out_dir, out_dir / "injected", prov,
        args.tics, args.limit_hosts)
    print(f"[stage5] k3 driver run: {len(jobs)} host-sectors, "
          f"{sum(len(j['trials']) for j in jobs)} trials, "
          f"{len(missing)} missing FITS, manifest "
          f"{manifest['_sha256'][:12]}…", flush=True)
    if missing:
        print(f"[stage5] MISSING FITS: {missing[:10]}", flush=True)
    if args.dry_run:
        return 0
    t0 = time.time()
    if args.workers <= 1:
        bs.set_calibration(args.calibration)
        results = [run_host_driver_k3(j) for j in jobs]
    else:
        from multiprocessing import Pool
        with Pool(args.workers, initializer=orc._init_worker,
                  initargs=(args.calibration,)) as pool:
            results = pool.map(run_host_driver_k3, jobs)
    done = sum(1 for r in results if r["status"] == "done")
    skipped = sum(1 for r in results if r["status"] == "skipped")
    failures = [r for r in results if r["status"] == "error"]
    for r in failures:
        print(f"[stage5] ERROR TIC {r['tic']} s{r['sector']:04d}: "
              f"{r.get('error')}", flush=True)
    n_fin = sum(r.get("n_final_recovered", 0) for r in results
                if r["status"] == "done")
    print(f"[stage5] done: {done} run, {skipped} skipped, "
          f"{len(failures)} failed, {n_fin} final recovered "
          f"(driver run only — score with --mode k3-score); "
          f"{time.time() - t0:.0f}s wall")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
