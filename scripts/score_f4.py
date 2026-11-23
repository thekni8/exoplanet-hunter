#!/usr/bin/env python3
"""F4 (S12FIX) scoring: stitched-0.75 fresh validation verdict.

Runs ON THE MAC (needs the FITS cache + the F4 run outputs).
Read-only on the run dirs: folds only; the only write is the
verdict JSON (--out).

Fold code: build_unmasked_stitch / fold_gate / validate_against
are copied from probe4_rescreen_gate.py (eligfix-vote) — the same
fold code the protocol freezes in §1 (load_real_fits ->
preprocess -> stitch_weighted -> _rescore/_fold_depth, bulk_v6
calibration). The one addition: fold_gate also returns the fold
depth's noise sigma (protocol §7 logging). The F4 modes,
criteria (a)-(d) and verdict are new.

Pass criteria (F4_PROTOCOL.md §1, stitched leg only):
  (a) every fresh NULL re-screen fold has ratio < 0.75
  (b) every fresh mask-rescue planet has ratio >= 0.75
  (c) planet cost is 0/N
  (d) report min rescue ratio, max null ratio, null re-screen
      count (report the count; do not pad it)

Definitions (following the 5.2/validation precedent):
- mask-rescue planet: a recovered Arm-P trial whose final row is
  a RE-SCREEN (not a pass-2 copy, not a pass-1 carry) AND whose
  unmasked fold FAILS the gate (the reprieve is what saves it).
  The 7 E6 mask rescues were exactly this population.
- null re-screen fold: a re-screen row among the Arm-N post-veto
  finals (the merge's stitched T0 veto + VSX filter, if wired,
  are already applied in the host files — demoted rows are no
  longer survivors, so reading the merged records gives the
  post-veto set directly, as in the 5.2 measurement).
- ratio: unmasked fold depth / masked row depth at the re-screen
  ephemeris (raw fold-depth ratio, no robust estimator).

Verdict: PASS iff (a)+(b)+(c) hold AND every chain validation
passes. Any chain-validation failure or fold error -> SCORING
FAILURE (fail loud; the measurement is untrusted, no verdict).
One-shot (protocol §8): a FAIL ends the 0.75 candidate until a
new vote. No re-tuning after unblinding.

Usage (on the Mac):
  python bulk/.venv-mac/bin/python score_f4.py --repo <worktree> \
    --run-p /Volumes/NVME/pingu-jobs/bulkv6-f4/run_p_20261123 \
    --run-n /Volumes/NVME/pingu-jobs/bulkv6-f4/run_n_20261123 \
    --cache /Volumes/NVME/pingu-jobs/exoplanet-hunter/bulk/cache \
    --out /Volumes/NVME/pingu-jobs/bulkv6-f4/f4_verdict.json
"""
import argparse
import glob
import json
import os
import sys
import time

REPRIEVE_RATIO = 0.75
PROTOCOL_SHA256 = (
    "3ae4bbd38924373bc53c496de64adc18199723f353b6cd5b53bdd471fad87c18")


def build_unmasked_stitch(cache_dir, tic, sectors, inject=None):
    """Rebuild the unmasked stitched curve exactly as pass 1 sees it.

    Per sector: load_real_fits -> (inject) -> preprocess_arrays ->
    sigma; stitch_weighted on the raw (injected) arrays; then the
    screen front end (preprocess_arrays) on the stitched curve.
    (Verbatim from probe4_rescreen_gate.py.)
    """
    from bulk import oracle_run as orc
    from bulk import p43_stitch as p43
    from bulk.inject_real_s96 import load_real_fits
    import injection_harness as ih

    secs = []
    sigmas = {}
    for sec in sectors:
        path = os.path.join(cache_dir, f"s{int(sec):04d}", f"{tic}.fits")
        t, f, q, fcol, _meta = load_real_fits(path)
        if inject is not None:
            period_d, epoch_btjd, depth_frac = inject
            f, _dur = ih.inject_transit(t, f, depth_frac, period_d,
                                        epoch_btjd)
        t_p, f_p, sigma = p43.preprocess_sector(t, f, q)
        sigmas[sec] = sigma
        secs.append({"sector": sec, "t": t, "f": f, "q": q,
                     "fcol": fcol, "crowdsap": None})
    t_u, f_u, q_u, _tr = p43.stitch_weighted(secs, sigmas)
    t_flat, f_flat = orc.preprocess_arrays(t_u, f_u, q_u)
    return t_flat, f_flat, int(len(t_flat))


def fold_gate(t_flat, f_flat, row):
    """The confirmation gate at one row's ephemeris on the unmasked
    stitch. Returns the rescore metrics, the folded depth + its
    noise sigma, the unmasked tier/status and the verdict.
    (probe4's fold_gate + the noise capture for protocol §7.)"""
    import bulk_screen as bs
    from bulk import oracle_run as orc

    p = row.get("period_days")
    t0 = row.get("t0_btjd")
    dur_h = row.get("duration_hours")
    if p is None or t0 is None or dur_h is None:
        return {"error": "missing ephemeris", "confirmed": False}
    dur = float(dur_h) / 24.0
    rs = bs._rescore(t_flat, f_flat, float(p), float(t0), dur)
    depth, n_in, noise = bs._fold_depth(t_flat, f_flat, float(p),
                                        float(t0), dur)
    depth_pct = float(depth) * 100.0
    noise_pct = (float(noise) * 100.0 if noise != float("inf")
                 else None)
    out = {"period_days": float(p), "t0_btjd": float(t0),
           "duration_d": dur, "fold_depth_pct": depth_pct,
           "fold_depth_noise_pct": noise_pct,
           "fold_n_in_transit": int(n_in),
           "row_sde": row.get("sde"),
           "row_depth_pct": row.get("depth_percent")}
    if rs is None:
        out.update({"rescore": None, "unmasked_tier": None,
                    "unmasked_status": "recorded",
                    "gate_reason": "rescore-none",
                    "confirmed": False})
        return out
    tier, status, reason = orc.derive_tier(rs, row.get("sde"),
                                           depth_pct)
    out.update({
        "rescore": {
            "mes_pink": rs["mes_pink"],
            "max_event_snr": rs["max_event_snr"],
            "n_events": rs["n_events"],
            "n_strong_events": rs["n_strong_events"],
            "n_events_dropped": rs["n_events_dropped"],
            "cdpp_pct": rs["cdpp_pct"],
            "v_ratio": rs["v_ratio"],
        },
        "unmasked_tier": tier, "unmasked_status": status,
        "gate_reason": reason, "confirmed": status == "survivor"})
    return out


def validate_against(t_flat, f_flat, ref_row):
    """Fold at ref_row's ephemeris and compare with its recorded
    metrics. (Verbatim from probe4_rescreen_gate.py.)"""
    import bulk_screen as bs

    p = ref_row.get("period_days")
    t0 = ref_row.get("t0_btjd")
    dur_h = ref_row.get("duration_hours")
    if p is None or t0 is None or dur_h is None:
        return {"ok": False, "reason": "missing ephemeris"}
    rs = bs._rescore(t_flat, f_flat, float(p), float(t0),
                     float(dur_h) / 24.0)
    if rs is None:
        return {"ok": False, "reason": "rescore-none"}
    mes_r = ref_row.get("mes_pink")
    max_r = ref_row.get("max_event_snr")
    nev_r = ref_row.get("n_events")

    def close(a, b):
        if a is None or b is None:
            return None
        return abs(a - b) <= max(0.01 * abs(a), 0.05)

    ok = (rs["n_events"] == nev_r and close(rs["mes_pink"], mes_r)
          and close(rs["max_event_snr"], max_r))
    return {"ok": bool(ok),
            "mes_recorded": mes_r, "mes_fold": rs["mes_pink"],
            "maxev_recorded": max_r,
            "maxev_fold": rs["max_event_snr"],
            "nev_recorded": nev_r, "nev_fold": rs["n_events"]}


def _ratio(fold):
    """Reprieve ratio: unmasked fold depth / masked row depth."""
    masked = fold.get("row_depth_pct")
    unmasked = fold.get("fold_depth_pct")
    if masked is None or unmasked is None or masked <= 0:
        return None
    return unmasked / masked


def mode_planet(args, out):
    """Arm P: recovered trials -> mask-rescue planets -> ratios."""
    recs = []
    for f in sorted(glob.glob(os.path.join(
            args.run_p, "hosts-p43", "*.json"))):
        r = json.load(open(f))
        for t in r["trials"]:
            t["_sectors"] = list(r["sectors"])
            recs.append(t)

    def final_row(t):
        if t.get("p3_recovered") and t.get("pass3"):
            return "pass3", t["pass3"]
        if t.get("p2_recovered") and t.get("pass2"):
            return "pass2", t["pass2"]
        return None, None

    recovered = [t for t in recs if t.get("final_recovered")]
    at_risk, copies, anomalies = [], [], []
    for t in recovered:
        pk, row = final_row(t)
        if pk is None:
            # Recovered only via the 5.1 carried row: a pass-1
            # recovery preserved, not a re-screen.
            if t.get("p1_carried_recovered"):
                copies.append(t)
            else:
                anomalies.append(t)
            continue
        if pk == "pass2" and row.get("carried_from") == "pass1":
            copies.append(t)
        else:
            at_risk.append(t)
    # 10 validation copies spread across the list (probe4's rule).
    step = max(1, len(copies) // 10) if copies else 1
    val_copies = copies[::step][:10]
    folds, validations, errors = [], [], []
    skipped = []
    for t in at_risk + val_copies:
        pk, row = final_row(t)
        if pk is None:
            # No pass-2/pass-3 final row: recovered only via the
            # 5.1 carried row (p1_carried_recovered). Not a
            # re-screen, so not a mask-rescue candidate and no
            # fold ephemeris applies. Skip from the measured set
            # — but log it, never silently (F4 scorer fix:
            # validation copies sampled from `copies` can be
            # p1-carried trials; the fold loop used to pass
            # their None row to fold_gate and crash).
            skipped.append({
                "tic": str(t["tic"]),
                "trial_id": t["trial_id"],
                "group": ("at_risk" if t in at_risk
                          else "validation_copy"),
            })
            continue
        tic = str(t["tic"])
        inject = (t["period_d"], t["epoch_btjd"], t["depth_frac"])
        t_flat, f_flat, n_cad = build_unmasked_stitch(
            args.cache, tic, t["_sectors"], inject=inject)
        val = validate_against(t_flat, f_flat, t.get("pass1") or {})
        val.update({"tic": tic, "trial_id": t["trial_id"],
                    "n_cadences": n_cad})
        validations.append(val)
        g = fold_gate(t_flat, f_flat, row)
        ratio = _ratio(g)
        g.update({"leg": "stitched", "tic": tic,
                  "trial_id": t["trial_id"], "pass": pk,
                  "group": ("at_risk" if t in at_risk
                            else "validation_copy"),
                  "reprieve_ratio": ratio,
                  "reprieved": (ratio is not None
                                and ratio >= REPRIEVE_RATIO),
                  "inj_period_d": t["period_d"],
                  "inj_depth_pct": t["depth_frac"] * 100.0,
                  "row_tier": row.get("tier"),
                  "row_status": row.get("status"),
                  "row_n_events": row.get("n_events"),
                  "row_mes": row.get("mes_pink"),
                  "row_maxev": row.get("max_event_snr")})
        if ratio is None:
            errors.append(f"{tic}:{t['trial_id']}:{pk} "
                          f"(no ratio: masked depth "
                          f"{g.get('row_depth_pct')})")
        folds.append(g)
    ar = [g for g in folds if g["group"] == "at_risk"]
    # Mask-rescue planets: at-risk trials the gate would remove
    # (unmasked fold does not confirm) — the reprieve is what
    # saves them. This is the E6 7/170 population.
    rescues = [g for g in ar if not g["confirmed"]]
    rescue_ratios = [g["reprieve_ratio"] for g in rescues
                     if g["reprieve_ratio"] is not None]
    at_risk_ratios = [g["reprieve_ratio"] for g in ar
                      if g["reprieve_ratio"] is not None]
    lost = [g for g in rescues
            if g["reprieve_ratio"] is None
            or g["reprieve_ratio"] < REPRIEVE_RATIO]
    out["planet"] = {
        "recovered_n": len(recovered),
        "at_risk_n": len(at_risk),
        "copy_n": len(copies),
        "validation_copy_n": len(val_copies),
        "anomaly_n": len(anomalies),
        "anomalies": [f"{t['tic']}:{t['trial_id']}"
                      for t in anomalies],
        "skipped_no_final_row_n": len(skipped),
        "skipped_no_final_row": [
            f"{s['tic']}:{s['trial_id']}:{s['group']}"
            for s in skipped],
        "mask_rescue_n": len(rescues),
        "mask_rescue_lost_n": len(lost),
        "mask_rescue_lost": [f"{g['tic']}:{g['trial_id']}"
                             f":{g['pass']}" for g in lost],
        "min_rescue_ratio": (min(rescue_ratios)
                             if rescue_ratios else None),
        "min_at_risk_ratio": (min(at_risk_ratios)
                              if at_risk_ratios else None),
        "folds": folds,
        "errors": errors,
    }
    out["validations"].extend(validations)
    return out


def mode_null(args, out):
    """Arm N: post-veto final re-screen rows -> ratios."""
    recs = {}
    for f in sorted(glob.glob(os.path.join(
            args.run_n, "null-p43", "*.json"))):
        r = json.load(open(f))
        recs[str(r["tic"])] = r
    finals = []
    for tic, r in sorted(recs.items()):
        for pk in ("pass2", "pass3"):
            if r.get(f"{pk}_survivor") is True:
                row = dict(r.get(pk) or {})
                row["tic"] = tic
                row["pass"] = pk
                row["kind"] = ("copy"
                               if (pk == "pass2"
                                   and row.get("carried_from")
                                   == "pass1")
                               else "rescreen")
                finals.append(row)
    rescreens = [r for r in finals if r["kind"] == "rescreen"]
    by_host = {}
    for r in rescreens:
        by_host.setdefault(r["tic"], []).append(r)
    folds, validations, errors = [], [], []
    for tic in sorted(by_host):
        r = recs[tic]
        t_flat, f_flat, n_cad = build_unmasked_stitch(
            args.cache, tic, r["sectors"])
        val = validate_against(t_flat, f_flat, r.get("pass1") or {})
        val.update({"tic": tic, "n_cadences": n_cad})
        validations.append(val)
        for row in by_host[tic]:
            g = fold_gate(t_flat, f_flat, row)
            ratio = _ratio(g)
            g.update({"leg": "stitched", "tic": tic,
                      "pass": row["pass"], "kind": row["kind"],
                      "reprieve_ratio": ratio,
                      "reprieved": (ratio is not None
                                    and ratio >= REPRIEVE_RATIO),
                      "row_tier": row.get("tier"),
                      "row_status": row.get("status"),
                      "row_n_events": row.get("n_events"),
                      "row_mes": row.get("mes_pink"),
                      "row_maxev": row.get("max_event_snr")})
            if ratio is None:
                errors.append(f"{tic}:{row['pass']} (no ratio: "
                              f"masked depth "
                              f"{g.get('row_depth_pct')})")
            folds.append(g)
    ratios = [g["reprieve_ratio"] for g in folds
              if g["reprieve_ratio"] is not None]
    out["null"] = {
        "final_rows_n": len(finals),
        "rescreen_n": len(rescreens),
        "copy_n": len(finals) - len(rescreens),
        "max_ratio": max(ratios) if ratios else None,
        "folds": folds,
        "errors": errors,
    }
    out["validations"].extend(validations)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True,
                    help="exoplanet-hunter-bulkv6 worktree")
    ap.add_argument("--run-p", required=True,
                    help="F4 Arm P out-dir (campaign)")
    ap.add_argument("--run-n", required=True,
                    help="F4 Arm N out-dir (null)")
    ap.add_argument("--cache", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--scorer-commit", default=None)
    args = ap.parse_args()
    sys.path.insert(0, args.repo)
    import bulk_screen as bs
    bs.set_calibration("bulk_v6")
    t0 = time.time()
    out = {"tool": "score_f4.py",
           "item": "F4 stitched-0.75 fresh validation",
           "protocol_sha256": PROTOCOL_SHA256,
           "seed_block": [42000000, 42001999],
           "scorer_commit": args.scorer_commit,
           "calibration": "bulk_v6",
           "run_p": args.run_p, "run_n": args.run_n,
           "cache_dir": args.cache,
           "reprieve_threshold": REPRIEVE_RATIO,
           "validations": []}
    out = mode_planet(args, out)
    out = mode_null(args, out)
    out["seconds"] = round(time.time() - t0, 1)
    vals = out["validations"]
    out["validation_ok"] = sum(1 for v in vals if v["ok"])
    out["validation_n"] = len(vals)
    out["validation_failures"] = [
        {k: v[k] for k in ("tic", "trial_id", "reason")
         if k in v} for v in vals if not v["ok"]]
    # Criteria (a)-(d).
    p, n = out["planet"], out["null"]
    fold_errors = p["errors"] + n["errors"]
    a_ratios = [g["reprieve_ratio"] for g in n["folds"]
                if g["reprieve_ratio"] is not None]
    crit_a = all(r < REPRIEVE_RATIO for r in a_ratios)
    crit_b = (p["min_rescue_ratio"] is not None
              and p["min_rescue_ratio"] >= REPRIEVE_RATIO)
    crit_c = p["mask_rescue_lost_n"] == 0
    out["criteria"] = {
        "a_null_rescreens_below_threshold": crit_a,
        "b_rescues_above_threshold": crit_b,
        "c_planet_cost_zero": crit_c,
        "d_min_rescue_ratio": p["min_rescue_ratio"],
        "d_max_null_ratio": n["max_ratio"],
        "d_null_rescreen_count": n["rescreen_n"],
        "d_mask_rescue_count": p["mask_rescue_n"],
    }
    # Size check (protocol §3: designed for >= 30 rescues).
    out["size_flag"] = (
        None if p["mask_rescue_n"] >= 30
        else (f"mask-rescue count {p['mask_rescue_n']} < 30 "
              f"designed — validation weaker than designed"))
    if out["validation_ok"] != out["validation_n"]:
        out["verdict"] = "SCORING FAILURE"
        out["verdict_reason"] = (
            f"chain validation {out['validation_ok']}/"
            f"{out['validation_n']} — the fold chain is "
            f"untrusted; no verdict")
    elif fold_errors:
        out["verdict"] = "SCORING FAILURE"
        out["verdict_reason"] = (
            f"{len(fold_errors)} fold(s) without a ratio: "
            f"{fold_errors[:5]}")
    elif p["anomaly_n"]:
        out["verdict"] = "SCORING FAILURE"
        out["verdict_reason"] = (
            f"{p['anomaly_n']} recovered trial(s) with no "
            f"recovery flag: {p['anomalies'][:5]}")
    elif crit_a and crit_b and crit_c:
        out["verdict"] = "PASS"
        out["verdict_reason"] = (
            "(a) all null re-screen ratios < 0.75; (b) all "
            "mask-rescue ratios >= 0.75; (c) planet cost 0")
    else:
        failed = [k for k, v in
                  (("a", crit_a), ("b", crit_b), ("c", crit_c))
                  if not v]
        out["verdict"] = "FAIL"
        out["verdict_reason"] = (
            f"criteria failed: {', '.join(failed)}. One-shot "
            f"rule: the 0.75 candidate ENDS until a new vote.")
    with open(args.out, "w") as fh:
        json.dump(out, fh, indent=1)
    print(json.dumps({"verdict": out["verdict"],
                      "criteria": out["criteria"],
                      "validation": (f"{out['validation_ok']}/"
                                     f"{out['validation_n']}"),
                      "size_flag": out["size_flag"]}, indent=1))
    print(f"wrote {args.out} in {out['seconds']}s")


if __name__ == "__main__":
    main()
