#!/usr/bin/env python
"""Standalone uncapped tiebreaker for ONE sweep-4 star, in a FRESH
process (the in-driver run for TIC 389564031 died with the chain when
a parallel render job exhausted the VM's RAM at 79 sectors).

Usage: sweep4_uncapped.py TIC RADIUS [--skip-analyze]

Reads the cap-20 ephemeris from vetting_results/{tic}.json, runs the
uncapped analyze (unless --skip-analyze or already present) and the
uncapped persistence at the FIXED cap-20 ephemeris, saves the full
table to vetting_results/{tic}_persistence_uncapped.json, and merges
the summary + era split into the JSON's uncapped_check block.
"""
import json
import sys
import time
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))

import hunter  # noqa: E402
import persistence  # noqa: E402
from sweep4_vet import persistence_summary, era_split  # noqa: E402


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def main():
    tic, radius = sys.argv[1], float(sys.argv[2])
    skip_analyze = "--skip-analyze" in sys.argv
    jp = BASE / "vetting_results" / f"{tic}.json"
    d = json.loads(jp.read_text())
    a = d["analyze"]
    p_rec, t0, dur = a["period_days"], a["t0_days"], a["duration_hours"]
    uc = d.get("uncapped_check") or {
        "note": "Uncapped tiebreaker (all sectors), ephemeris fixed at "
                "the cap-20 analyze solution for the persistence fold."}

    if not skip_analyze and "analyze_all_sectors" not in uc:
        log(f"TIC {tic}: uncapped analyze start")
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
        d["uncapped_check"] = uc
        jp.write_text(json.dumps(d, indent=2, default=str))
        log(f"TIC {tic}: uncapped analyze -> P={um['best_period_days']:.4f} "
            f"SDE={um['sde']:.1f} sectors={um['sectors_analyzed']}")
    else:
        log(f"TIC {tic}: uncapped analyze skipped (already recorded)")

    log(f"TIC {tic}: uncapped persistence start")
    uper = persistence.sector_persistence(
        tic, radius, p_rec, t0, dur, sector_cap=None,
        progress_callback=lambda m: log(f"  up: {m}"))
    (BASE / "vetting_results" / f"{tic}_persistence_uncapped.json").write_text(
        json.dumps(uper, indent=2, default=str))
    s = persistence_summary(uper)
    s["verdict_module"] = uper.get("verdict")
    uc["persistence_at_fixed_ephemeris"] = s
    uc["era_split"] = era_split(uper)
    d["uncapped_check"] = uc
    jp.write_text(json.dumps(d, indent=2, default=str))
    log(f"TIC {tic}: uncapped persistence -> {uper.get('verdict')} "
        f"(usable {uper.get('n_usable')}, pos {uper.get('n_pos_1p5sigma')}, "
        f"wmean {uper.get('weighted_mean_depth_pct')})")
    log(f"TIC {tic}: UNCAPPED DONE")


if __name__ == "__main__":
    main()
