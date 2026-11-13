#!/usr/bin/env python
"""Sweep-2 gauntlet for ONE hit. Usage: vet_star2.py TIC RADIUS SWEEP_P SWEEP_SDE

Stage order (JSON rewritten after each stage; a kill stops the gauntlet):
  (known) is_already_known_online
  (a) analyze reproduce (cap 20, bls 10000)   fail -> PIPELINE PHANTOM
  (b) odd/even   likely-EB -> LIKELY BINARY;
                 inconclusive + folds evaporated (<25% of BLS depth)
                   -> PIPELINE PHANTOM; inconclusive otherwise -> INCONCLUSIVE
  (c) double-period  likely-binary -> LIKELY BINARY;
                      inconclusive -> INCONCLUSIVE
  (d) orbit-phase boundary fraction (diagnostic; pile-up flagged)
  (e) ONLY if planet-consistent through (c): sector persistence
      (persistence.py) -> SURVIVES / BLEND-SUSPECT / INCONCLUSIVE.
      ExoFOP contamination is fetched separately by the parent and
      patched into the JSON afterwards.
  (f) holdout prediction (holdout_test.py, 2026-11-11): leave-one-
      sector-out — the ephemeris is refit without each fold of
      sectors and must predict that fold's dips in RAW flux. Recorded
      whenever (e) is reached. HOLDOUT-FAIL demotes a provisional
      SURVIVES to INCONCLUSIVE; PASS / INSUFFICIENT-DATA never change
      the verdict. A pass proves predictive periodicity ONLY — a
      clean eclipsing binary passes this stage — so it complements
      the raw-flux, shape and imaging gates, never replaces them.
"""
import json
import sys
import time
import warnings
from pathlib import Path

import numpy as np

warnings.filterwarnings("ignore")

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
OUTDIR = BASE / "vetting_results"
OUTDIR.mkdir(exist_ok=True)

import hunter  # noqa: E402
from vet_star import orbit_phase_test  # noqa: E402
import persistence  # noqa: E402
import holdout_test  # noqa: E402


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def main():
    tic, radius = sys.argv[1], float(sys.argv[2])
    sweep_p, sweep_sde = float(sys.argv[3]), float(sys.argv[4])
    out_path = OUTDIR / f"{tic}.json"
    res = {"tic": tic, "star_radius_rsun": radius, "gauntlet": "sweep2",
           "sweep": {"period_days": sweep_p, "sde": sweep_sde,
                     "field": "RA 70.0, Dec -70.0, cone 1.0"}}

    def save():
        out_path.write_text(json.dumps(res, indent=2, default=str))

    def kill(verdict, stage, why):
        res["verdict"] = verdict
        res["killed_at_stage"] = stage
        res["kill_reason"] = why
        res["elapsed_s"] = round(time.time() - t_start, 1)
        save()
        log(f"TIC {tic}: {verdict} (killed at {stage}: {why})")

    t_start = time.time()

    # (known)
    try:
        res["known_zooniverse_talk"] = bool(hunter.is_already_known_online(tic))
    except Exception as exc:
        res["known_zooniverse_talk"] = f"error: {exc}"
    save()
    log(f"TIC {tic}: known={res['known_zooniverse_talk']}")

    # (a) analyze
    log(f"TIC {tic}: (a) analyze start")
    try:
        aj = hunter.analyze_target_json(
            tic, star_radius=radius, bls_points=10000, max_sectors=20,
            progress_callback=lambda m: log(f"  a: {m}"))
        m = aj["metrics"]
        res["analyze"] = {
            "period_days": m["best_period_days"], "sde": m["sde"],
            "depth_percent": m["depth_percent"],
            "planet_radius_re": m["planet_radius_earth"],
            "duration_hours": m["duration_hours"], "t0_days": m["t0_days"],
            "sectors_analyzed": m["sectors_analyzed"],
            "total_points": m["total_points"],
        }
    except Exception as exc:
        res["analyze"] = {"error": f"{type(exc).__name__}: {exc}"}
        kill("PIPELINE PHANTOM", "a", f"analyze raised: {exc}")
        return
    save()
    a = res["analyze"]
    log(f"TIC {tic}: (a) P={a['period_days']:.4f} SDE={a['sde']:.1f} "
        f"depth={a['depth_percent']:.3f}% Rp={a['planet_radius_re']:.2f}")

    p_rec = a["period_days"]
    rel = abs(p_rec - sweep_p) / sweep_p
    rel_half = abs(p_rec - sweep_p / 2) / sweep_p
    rel_dbl = abs(p_rec - 2 * sweep_p) / sweep_p
    match = min(rel, rel_half, rel_dbl)
    res["period_match"] = {"rel_diff": rel, "rel_diff_half": rel_half,
                           "rel_diff_double": rel_dbl}
    res["reproduced"] = bool(a["sde"] >= 8.5 and match < 0.02)
    save()
    if not res["reproduced"]:
        kill("PIPELINE PHANTOM", "a",
             f"not reproduced (SDE={a['sde']:.1f}, period match={match:.3f})")
        return

    # (b) odd/even
    log(f"TIC {tic}: (b) odd/even start")
    try:
        oe = hunter.odd_even_test_json(tic, p_rec, sector_cap=20,
                                       progress_callback=lambda m: log(f"  b: {m}"))
        mm = oe["metrics"]
        res["odd_even"] = {
            "verdict": mm["verdict"], "verdict_text": mm["verdict_text"],
            "depth_odd_percent": mm["depth_odd_percent"],
            "depth_even_percent": mm["depth_even_percent"],
            "depth_ratio": mm["depth_ratio"],
            "period_fit_days": mm["period_fit_days"],
        }
    except Exception as exc:
        res["odd_even"] = {"error": f"{type(exc).__name__}: {exc}"}
        kill("INCONCLUSIVE", "b", f"odd/even raised: {exc}")
        return
    save()
    oe_v = res["odd_even"]["verdict"]
    log(f"TIC {tic}: (b) odd/even -> {oe_v}")
    if oe_v == "likely-eclipsing-binary":
        kill("LIKELY BINARY", "b",
             "odd/even depths differ (alternating eclipse depths)")
        return
    if oe_v == "inconclusive":
        deepest = max(abs(res["odd_even"]["depth_odd_percent"] or 0.0),
                      abs(res["odd_even"]["depth_even_percent"] or 0.0))
        frac = deepest / a["depth_percent"] if a["depth_percent"] else 0.0
        res["odd_even"]["fold_depth_fraction_of_bls"] = frac
        save()
        if frac < 0.25:
            kill("PIPELINE PHANTOM", "b",
                 f"odd/even inconclusive and folds evaporated "
                 f"(deepest fold dip {deepest:.3f}% = {frac:.0%} of BLS depth)")
        else:
            kill("INCONCLUSIVE", "b",
                 "odd/even inconclusive (dip present but unmeasurable split)")
        return

    # (c) double-period
    log(f"TIC {tic}: (c) double-period start")
    try:
        dp = hunter.double_period_test_json(tic, p_rec, sector_cap=20,
                                            progress_callback=lambda m: log(f"  c: {m}"))
        mm = dp["metrics"]
        res["double_period"] = {
            "verdict": mm["verdict"], "verdict_text": mm["verdict_text"],
            "delta_percent": mm["delta_percent"],
            "delta_sigma": mm["delta_sigma"],
            "period_2p_refined_days": mm["period_2p_refined_days"],
            "eclipse1_depth_percent": mm["eclipse1_depth_percent"],
            "eclipse2_depth_percent": mm["eclipse2_depth_percent"],
        }
    except Exception as exc:
        res["double_period"] = {"error": f"{type(exc).__name__}: {exc}"}
        kill("INCONCLUSIVE", "c", f"double-period raised: {exc}")
        return
    save()
    dp_v = res["double_period"]["verdict"]
    log(f"TIC {tic}: (c) double-period -> {dp_v}")
    if dp_v == "likely-binary":
        kill("LIKELY BINARY", "c",
             f"ellipsoidal wave {res['double_period']['delta_percent']:+.2f}% "
             f"@ {res['double_period']['delta_sigma']:.0f} sigma")
        return
    if dp_v == "inconclusive":
        kill("INCONCLUSIVE", "c",
             "quadrature dip at 2P (unexplained out-of-eclipse structure)")
        return

    # (d) orbit-phase (diagnostic)
    log(f"TIC {tic}: (d) orbit-phase start")
    try:
        res["orbit_phase"] = orbit_phase_test(
            tic, p_rec, a["t0_days"], a["duration_hours"] / 24.0, sector_cap=20)
    except Exception as exc:
        res["orbit_phase"] = {"error": f"{type(exc).__name__}: {exc}"}
    save()
    op = res["orbit_phase"]
    pileup = False
    if isinstance(op, dict) and op.get("on_data_centers"):
        od = op["on_data_centers"]
        pileup = bool(od["frac_within_1p5d_of_orbit_boundary"] >= 0.5
                      and od["circular_mean_resultant_R"] >= 0.4)
        log(f"TIC {tic}: (d) on-data n={od['n']} "
            f"frac@boundary={od['frac_within_1p5d_of_orbit_boundary']:.2f} "
            f"R={od['circular_mean_resultant_R']} pileup={pileup}")
    res["orbit_phase_pileup_flag"] = pileup
    save()

    # (e) sector persistence
    log(f"TIC {tic}: (e) persistence start")
    try:
        per = persistence.sector_persistence(
            tic, radius, p_rec, a["t0_days"], a["duration_hours"],
            sector_cap=20, progress_callback=lambda m: log(f"  e: {m}"))
        res["persistence"] = per
    except Exception as exc:
        res["persistence"] = {"error": f"{type(exc).__name__}: {exc}"}
        kill("INCONCLUSIVE", "e", f"persistence raised: {exc}")
        return
    save()
    log(f"TIC {tic}: (e) persistence -> {per.get('verdict')} "
        f"(usable {per.get('n_usable')}, pos {per.get('n_pos_1p5sigma')}, "
        f"wmean {per.get('weighted_mean_depth_pct')})")

    pv = per.get("verdict")
    monsters = per.get("raw_monster_sectors") or []
    if pv == "CONSISTENT" and not pileup:
        verdict = "SURVIVES (provisional - pending ExoFOP contamination)"
    elif pv == "CONSISTENT" and pileup:
        verdict = "INCONCLUSIVE"
    elif monsters:
        verdict = "BLEND-SUSPECT"
    else:
        verdict = "INCONCLUSIVE"
    res["verdict"] = verdict
    res["killed_at_stage"] = None if verdict.startswith("SURVIVES") else "e"
    res["kill_reason"] = (f"persistence {pv}"
                          + (f"; raw monster sectors "
                             f"{[mm['sector'] for mm in monsters]}" if monsters else "")
                          + ("; orbit-phase pile-up" if pileup else ""))

    # (f) holdout prediction (2026-11-11) — see module docstring.
    log(f"TIC {tic}: (f) holdout start")
    try:
        ho = holdout_test.holdout_test(
            tic, p_rec, a["t0_days"], a["duration_hours"],
            sector_cap=20, star_radius=radius,
            progress_callback=lambda m: log(f"  f: {m}"))
        res["holdout"] = ho
        log(f"TIC {tic}: (f) holdout -> {ho.get('verdict')} "
            f"(usable folds {ho.get('n_usable_folds')}, "
            f"combined signif {ho.get('combined_signif')})")
        if (ho.get("verdict") == "HOLDOUT-FAIL"
                and verdict.startswith("SURVIVES")):
            verdict = "INCONCLUSIVE"
            res["verdict"] = verdict
            res["killed_at_stage"] = "f"
            res["kill_reason"] += ("; holdout HOLDOUT-FAIL (refit "
                                    "ephemeris does not predict held-out "
                                    "raw flux)")
    except Exception as exc:
        res["holdout"] = {"error": f"{type(exc).__name__}: {exc}"}
        log(f"TIC {tic}: (f) holdout error (non-killing): {exc}")
    save()

    res["elapsed_s"] = round(time.time() - t_start, 1)
    save()
    log(f"TIC {tic}: FINAL {verdict} in {res['elapsed_s']}s")


if __name__ == "__main__":
    main()
