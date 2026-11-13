#!/usr/bin/env python
"""Sweep-5 gauntlet for ONE hit (RA 110.0, Dec -63.0 patch).

Usage: sweep5_vet.py TIC RADIUS SWEEP_P SWEEP_SDE STAMP [--folds-only] [--uncapped]

Same stage order and pre-set decision rules as vet_star2.py / sweep4_vet.py:
  (known) is_already_known_online
  (a) analyze reproduce (cap 20, bls 10000)   fail -> PIPELINE PHANTOM
  (b) odd/even   likely-EB -> LIKELY BINARY;
                 inconclusive + folds evaporated (<25% of BLS depth)
                   -> PIPELINE PHANTOM; inconclusive otherwise -> INCONCLUSIVE
  (c) double-period  likely-binary -> LIKELY BINARY;
                      inconclusive -> INCONCLUSIVE
  (d) orbit-phase boundary fraction (diagnostic; pile-up flagged)
  (e) sector persistence -> SURVIVES / BLEND-SUSPECT / INCONCLUSIVE

Default mode runs (c), (d) and (e) as POST-GATE diagnostics even after a
(b)/(c) kill (the sweep-3/4 precedent for patchy stamps), so the record
always carries the full stage set. The mechanical verdict is preserved
verbatim in driver_verdict_raw; "verdict" starts as the same class and
may be reconciled afterwards (documented via reclassification_note).

--folds-only stops after (c) (fold completion for self-convicted hits).
--uncapped adds the standing tiebreaker for shallow patchy hits: an
all-sector analyze plus persistence at the FIXED cap-20 ephemeris,
with an era split of the uncapped per-sector table (sweep-3 format).
Full persistence tables are saved as vetting_results/{tic}_persistence_cap20.json
and {tic}_persistence_uncapped.json sidecars.

History discipline (sweep-5 brief): hunter.log_candidate is replaced by
a no-op in THIS driver process, so no reproduction appends to
discoveries.csv; data/hunter.db is never touched (no API server runs).
Both files' md5s are verified byte-identical at close by the parent.
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

# --- history guard: suppress discoveries.csv appends in this process ---
_ORIG_LOG_CANDIDATE = hunter.log_candidate
hunter.log_candidate = lambda *a, **k: None

FIELD = "RA 110.0, Dec -63.0, cone 1.0"


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def persistence_summary(per):
    """Compact summary of a persistence.sector_persistence() result
    (everything except the per-sector / per-event tables)."""
    if not isinstance(per, dict):
        return per
    return {k: v for k, v in per.items() if k not in ("sectors", "events")}


def era_split(per):
    """Era split of an uncapped persistence result (sweep-3 format).
    Groups are computed over usable sector entries only."""
    secs = [s for s in per.get("sectors", [])
            if s.get("usable") and s.get("sigma_pct") and s.get("depth_pct") is not None]

    def agg(entries):
        if not entries:
            return {"n_ranges": 0, "n_pos_1p5sigma": 0,
                    "weighted_mean_depth_pct": None,
                    "weighted_mean_sigma_pct": None,
                    "significance_sigma": None}
        d = np.array([s["depth_pct"] for s in entries])
        sg = np.array([s["sigma_pct"] for s in entries])
        w = 1.0 / sg ** 2
        wm = float(np.sum(w * d) / np.sum(w))
        ws = float(1.0 / np.sqrt(np.sum(w)))
        return {"n_ranges": len(entries),
                "n_pos_1p5sigma": int(np.sum([s["signif"] >= 1.5 for s in entries])),
                "weighted_mean_depth_pct": wm,
                "weighted_mean_sigma_pct": ws,
                "significance_sigma": wm / ws if ws else None}

    all_secs = per.get("sectors", [])
    first20 = [s for s in all_secs[:20]
               if s.get("usable") and s.get("sigma_pct") and s.get("depth_pct") is not None]
    return {
        "first20_ranges_swept_subset": agg(first20),
        "sectors_le_13": agg([s for s in secs if s["sector"] is not None and s["sector"] <= 13]),
        "sectors_27_39": agg([s for s in secs if s["sector"] is not None and 27 <= s["sector"] <= 39]),
        "sectors_40_59": agg([s for s in secs if s["sector"] is not None and 40 <= s["sector"] <= 59]),
        "sectors_ge_60": agg([s for s in secs if s["sector"] is not None and s["sector"] >= 60]),
    }


def main():
    tic, radius = sys.argv[1], float(sys.argv[2])
    sweep_p, sweep_sde = float(sys.argv[3]), float(sys.argv[4])
    stamp = sys.argv[5]
    folds_only = "--folds-only" in sys.argv
    do_uncapped = "--uncapped" in sys.argv
    out_path = OUTDIR / f"{tic}.json"
    res = {"tic": tic, "star_radius_rsun": radius, "gauntlet": "sweep5",
           "sweep": {"period_days": sweep_p, "sde": sweep_sde,
                     "field": FIELD, "in_sweep_persistence_stamp": stamp},
           "history_logging": "suppressed in driver (hunter.log_candidate "
                              "no-op); data/hunter.db untouched"}

    def save():
        out_path.write_text(json.dumps(res, indent=2, default=str))

    t_start = time.time()
    gate = {"verdict": None, "stage": None, "reason": None}  # mechanical stage-gate kill

    def set_gate(verdict, stage, why):
        if gate["verdict"] is None:
            gate.update(verdict=verdict, stage=stage, reason=why)

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
        res["verdict"] = "PIPELINE PHANTOM"
        res["driver_verdict_raw"] = "PIPELINE PHANTOM (stage-gate kill at a)"
        res["killed_at_stage"] = "a"
        res["kill_reason"] = f"analyze raised: {exc}"
        res["elapsed_s"] = round(time.time() - t_start, 1)
        save()
        log(f"TIC {tic}: PIPELINE PHANTOM (analyze raised)")
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
        res["verdict"] = "PIPELINE PHANTOM"
        res["driver_verdict_raw"] = "PIPELINE PHANTOM (stage-gate kill at a)"
        res["killed_at_stage"] = "a"
        res["kill_reason"] = (f"not reproduced (SDE={a['sde']:.1f}, "
                              f"period match={match:.3f})")
        res["elapsed_s"] = round(time.time() - t_start, 1)
        save()
        log(f"TIC {tic}: PIPELINE PHANTOM (not reproduced)")
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
        set_gate("INCONCLUSIVE", "b", f"odd/even raised: {exc}")
        res["verdict"] = gate["verdict"]
        res["driver_verdict_raw"] = "INCONCLUSIVE (stage-gate kill at b)"
        res["killed_at_stage"] = "b"
        res["kill_reason"] = gate["reason"]
        res["elapsed_s"] = round(time.time() - t_start, 1)
        save()
        return
    save()
    oe_v = res["odd_even"]["verdict"]
    log(f"TIC {tic}: (b) odd/even -> {oe_v}")
    if oe_v == "likely-eclipsing-binary":
        set_gate("LIKELY BINARY", "b",
                 "odd/even depths differ (alternating eclipse depths)")
    elif oe_v == "inconclusive":
        deepest = max(abs(res["odd_even"]["depth_odd_percent"] or 0.0),
                      abs(res["odd_even"]["depth_even_percent"] or 0.0))
        frac = deepest / a["depth_percent"] if a["depth_percent"] else 0.0
        res["odd_even"]["fold_depth_fraction_of_bls"] = frac
        save()
        if frac < 0.25:
            set_gate("PIPELINE PHANTOM", "b",
                     f"odd/even inconclusive and folds evaporated "
                     f"(deepest fold dip {deepest:.3f}% = {frac:.0%} of BLS depth)")
        else:
            set_gate("INCONCLUSIVE", "b",
                     "odd/even inconclusive (dip present but unmeasurable split)")

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
        set_gate("INCONCLUSIVE", "c", f"double-period raised: {exc}")
    save()
    if "double_period" in res and "verdict" in res["double_period"]:
        dp_v = res["double_period"]["verdict"]
        log(f"TIC {tic}: (c) double-period -> {dp_v}")
        if dp_v == "likely-binary":
            set_gate("LIKELY BINARY", "c",
                     f"ellipsoidal wave {res['double_period']['delta_percent']:+.2f}% "
                     f"@ {res['double_period']['delta_sigma']:.0f} sigma")
        elif dp_v == "inconclusive":
            set_gate("INCONCLUSIVE", "c",
                     "quadrature dip at 2P (unexplained out-of-eclipse structure)")

    if folds_only:
        if gate["verdict"] is None:
            # planet-consistent through (c): fold completion has no kill;
            # provisional class, persistence is the sweep's own stamp.
            res["verdict"] = "SURVIVES FOLDS (provisional)"
            res["driver_verdict_raw"] = "no fold kill at (b)/(c)"
            res["killed_at_stage"] = None
            res["kill_reason"] = None
        else:
            res["verdict"] = gate["verdict"]
            res["driver_verdict_raw"] = f"{gate['verdict']} (stage-gate kill at {gate['stage']})"
            res["killed_at_stage"] = gate["stage"]
            res["kill_reason"] = gate["reason"]
        res["elapsed_s"] = round(time.time() - t_start, 1)
        save()
        log(f"TIC {tic}: FOLDS DONE -> {res['verdict']} in {res['elapsed_s']}s")
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
        (OUTDIR / f"{tic}_persistence_cap20.json").write_text(
            json.dumps(per, indent=2, default=str))
        key = "persistence" if gate["verdict"] is None else "persistence_postgate_diagnostic"
        res[key] = persistence_summary(per)
        res["_persistence_key"] = key
    except Exception as exc:
        res["persistence_error"] = f"{type(exc).__name__}: {exc}"
        set_gate("INCONCLUSIVE", "e", f"persistence raised: {exc}")
        per = None
    save()
    if per is not None:
        log(f"TIC {tic}: (e) persistence -> {per.get('verdict')} "
            f"(usable {per.get('n_usable')}, pos {per.get('n_pos_1p5sigma')}, "
            f"wmean {per.get('weighted_mean_depth_pct')})")

    # mechanical verdict
    if gate["verdict"] is not None:
        res["verdict"] = gate["verdict"]
        res["driver_verdict_raw"] = f"{gate['verdict']} (stage-gate kill at {gate['stage']})"
        res["killed_at_stage"] = gate["stage"]
        res["kill_reason"] = gate["reason"]
    elif per is not None:
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
        res["driver_verdict_raw"] = verdict
        res["killed_at_stage"] = None if verdict.startswith("SURVIVES") else "e"
        res["kill_reason"] = (f"persistence {pv}"
                              + (f"; raw monster sectors "
                                 f"{[mm2['sector'] for mm2 in monsters]}" if monsters else "")
                              + ("; orbit-phase pile-up" if pileup else ""))
    res.pop("_persistence_key", None)
    save()

    # uncapped tiebreaker
    if do_uncapped:
        log(f"TIC {tic}: uncapped analyze start")
        uc = {"note": "Uncapped tiebreaker (all sectors), ephemeris fixed at "
                      "the cap-20 analyze solution for the persistence fold."}
        try:
            uj = hunter.analyze_target_json(
                tic, star_radius=radius, bls_points=10000, max_sectors=None,
                progress_callback=lambda m: log(f"  u: {m}"))
            um = uj["metrics"]
            uc["analyze_all_sectors"] = {
                "period_days": um["best_period_days"], "sde": um["sde"],
                "depth_percent": um["depth_percent"],
                "planet_radius_re": um["planet_radius_earth"],
                "duration_hours": um["duration_hours"], "t0_days": um["t0_days"],
                "sectors_analyzed": um["sectors_analyzed"],
                "total_points": um["total_points"],
            }
            log(f"TIC {tic}: uncapped analyze -> P={um['best_period_days']:.4f} "
                f"SDE={um['sde']:.1f} sectors={um['sectors_analyzed']}")
        except Exception as exc:
            uc["analyze_all_sectors"] = {"error": f"{type(exc).__name__}: {exc}"}
        save()
        log(f"TIC {tic}: uncapped persistence start")
        try:
            uper = persistence.sector_persistence(
                tic, radius, p_rec, a["t0_days"], a["duration_hours"],
                sector_cap=None, progress_callback=lambda m: log(f"  up: {m}"))
            (OUTDIR / f"{tic}_persistence_uncapped.json").write_text(
                json.dumps(uper, indent=2, default=str))
            s = persistence_summary(uper)
            s["verdict_module"] = uper.get("verdict")
            uc["persistence_at_fixed_ephemeris"] = s
            uc["era_split"] = era_split(uper)
            log(f"TIC {tic}: uncapped persistence -> {uper.get('verdict')} "
                f"(usable {uper.get('n_usable')}, pos {uper.get('n_pos_1p5sigma')}, "
                f"wmean {uper.get('weighted_mean_depth_pct')})")
        except Exception as exc:
            uc["persistence_at_fixed_ephemeris"] = {"error": f"{type(exc).__name__}: {exc}"}
        res["uncapped_check"] = uc
        save()

    res["elapsed_s"] = round(time.time() - t_start, 1)
    save()
    log(f"TIC {tic}: FINAL {res['verdict']} in {res['elapsed_s']}s")


if __name__ == "__main__":
    main()
