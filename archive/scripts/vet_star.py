#!/usr/bin/env python
"""Vet ONE sweep hit end-to-end and write vetting_results/<tic>.json.

Usage: vet_star.py TIC STAR_RADIUS SWEEP_PERIOD SWEEP_SDE

Stages (JSON rewritten after each stage so partial progress survives):
  (e) is_already_known_online
  (a) analyze_target_json at sweep settings (bls 10000, cap 20)
  (b) odd_even_test_json at recovered period, cap 20      [if reproduced]
  (c) double_period_test_json at recovered period, cap 20 [if reproduced]
  (d) orbit-phase test on the raw stitched curve          [if reproduced]
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

ORBIT = 13.7  # TESS orbital period, days


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def orbit_phase_test(tic, period, t0, duration_days, sector_cap=20):
    """Custom systematic test: do the transit centers pile up at a fixed
    phase of the 13.7-d TESS orbit cycle (anchored at each data segment's
    start, segments split at gaps > 0.5 d)? Instrumental scattered-light
    dips recur right after downlink/data-resume, i.e. at the same orbit
    phase every orbit; a real planet's centers drift through all phases
    unless P is commensurate with 13.7 d."""
    lc, n_sectors = hunter._fetch_stitched(tic, max_sectors=sector_cap)
    t = np.asarray(lc.time.value, dtype=float)
    f = np.asarray(lc.flux.value, dtype=float)
    ok = np.isfinite(t) & np.isfinite(f)
    t = np.sort(t[ok])
    if len(t) < 100:
        return {"error": f"only {len(t)} usable points"}

    dt = np.diff(t)
    brk = np.where(dt > 0.5)[0]
    starts = [0] + (brk + 1).tolist()
    ends = brk.tolist() + [len(t) - 1]
    segments = [(float(t[s]), float(t[e])) for s, e in zip(starts, ends)
                if t[e] - t[s] > 0.5]
    anchors = np.array([s for s, _ in segments])

    k0 = int(np.ceil((t[0] - t0) / period))
    k1 = int(np.floor((t[-1] - t0) / period))
    centers = t0 + period * np.arange(k0, k1 + 1)
    half_dur = 0.5 * (duration_days or 0.2)

    phases, on_data = [], []
    for c in centers:
        idx = np.searchsorted(anchors, c + 1e-9) - 1
        if idx < 0:
            continue
        phases.append(float((c - anchors[idx]) % ORBIT))
        s, e = segments[idx]
        on_data.append(bool(s - half_dur <= c <= e + half_dur))
    phases = np.array(phases)
    on_data = np.array(on_data, dtype=bool)
    if len(phases) == 0:
        return {"error": "no transit centers in span", "n_sectors": int(n_sectors)}

    def summarize(ph):
        if len(ph) == 0:
            return None
        dist_b = np.minimum(ph, ORBIT - ph)
        bins = np.histogram(ph, bins=np.linspace(0, ORBIT, 11))[0].tolist()
        theta = 2 * np.pi * ph / ORBIT
        r_bar = float(np.abs(np.mean(np.exp(1j * theta))))
        return {
            "n": int(len(ph)),
            "phases_days": [round(float(x), 2) for x in sorted(ph.tolist())],
            "frac_within_1p5d_after_segment_start": float(np.mean(ph < 1.5)),
            "frac_within_1p5d_of_orbit_boundary": float(np.mean(dist_b < 1.5)),
            "expected_boundary_frac_by_chance": round(3.0 / ORBIT, 3),
            "phase_bins_1p37d": bins,
            "circular_mean_resultant_R": round(r_bar, 3),
        }

    return {
        "n_sectors_fetched": int(n_sectors),
        "n_points": int(len(t)),
        "n_segments": len(segments),
        "segment_lengths_days": [round(e - s, 1) for s, e in segments],
        "period_over_orbit_ratio": round(period / ORBIT, 4),
        "all_centers": summarize(phases),
        "on_data_centers": summarize(phases[on_data]),
        "n_centers_in_gaps": int((~on_data).sum()),
    }


def main():
    tic, radius = sys.argv[1], float(sys.argv[2])
    sweep_p, sweep_sde = float(sys.argv[3]), float(sys.argv[4])
    out_path = OUTDIR / f"{tic}.json"
    res = {"tic": tic, "star_radius_rsun": radius,
           "sweep": {"period_days": sweep_p, "sde": sweep_sde}}

    def save():
        out_path.write_text(json.dumps(res, indent=2, default=str))

    # (e) known check — cheap, always run
    t_start = time.time()
    try:
        res["known_zooniverse_talk"] = bool(hunter.is_already_known_online(tic))
    except Exception as exc:  # fail-open helper, but record surprises
        res["known_zooniverse_talk"] = f"error: {exc}"
    res["vsx"] = "not-run (no VSX helper in codebase; needs browser)"
    save()
    log(f"TIC {tic}: known={res['known_zooniverse_talk']}")

    # (a) analyze at sweep settings
    log(f"TIC {tic}: analyze start (cap 20, bls 10000)")
    try:
        aj = hunter.analyze_target_json(
            tic, star_radius=radius, bls_points=10000, max_sectors=20,
            progress_callback=lambda m: log(f"  analyze: {m}"))
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
        res["reproduced"] = False
        res["verdict"] = "NOT REPRODUCED (analyze raised)"
        save()
        log(f"TIC {tic}: analyze FAILED {exc}")
        return
    save()
    a = res["analyze"]
    log(f"TIC {tic}: analyze -> P={a['period_days']:.4f} SDE={a['sde']:.1f} "
        f"depth={a['depth_percent']:.3f}% Rp={a['planet_radius_re']:.2f}")

    # reproduction test: SDE >= 8.5 and period matches sweep (or harmonic)
    p_rec = a["period_days"]
    rel = abs(p_rec - sweep_p) / sweep_p
    rel_half = abs(p_rec - sweep_p / 2) / sweep_p
    rel_dbl = abs(p_rec - 2 * sweep_p) / sweep_p
    match = min(rel, rel_half, rel_dbl)
    res["period_match"] = {"rel_diff": rel, "rel_diff_half": rel_half,
                           "rel_diff_double": rel_dbl}
    res["reproduced"] = bool(a["sde"] >= 8.5 and match < 0.02)
    if not res["reproduced"]:
        res["verdict"] = "NOT REPRODUCED"
        save()
        log(f"TIC {tic}: NOT REPRODUCED (SDE={a['sde']:.1f}, match={match:.3f})")
        return

    # (b) odd/even
    log(f"TIC {tic}: odd/even start")
    try:
        oe = hunter.odd_even_test_json(tic, p_rec, sector_cap=20,
                                       progress_callback=lambda m: log(f"  oe: {m}"))
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
    save()
    log(f"TIC {tic}: odd/even -> {res['odd_even'].get('verdict')}")

    # (c) double-period
    log(f"TIC {tic}: double-period start")
    try:
        dp = hunter.double_period_test_json(tic, p_rec, sector_cap=20,
                                            progress_callback=lambda m: log(f"  dp: {m}"))
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
    save()
    log(f"TIC {tic}: double-period -> {res['double_period'].get('verdict')}")

    # (d) orbit-phase test
    log(f"TIC {tic}: orbit-phase test start")
    try:
        res["orbit_phase"] = orbit_phase_test(
            tic, p_rec, a["t0_days"], a["duration_hours"] / 24.0, sector_cap=20)
    except Exception as exc:
        res["orbit_phase"] = {"error": f"{type(exc).__name__}: {exc}"}
    save()
    op = res["orbit_phase"]
    if "on_data_centers" in op and op["on_data_centers"]:
        od = op["on_data_centers"]
        log(f"TIC {tic}: orbit-phase on-data n={od['n']} "
            f"frac@boundary={od['frac_within_1p5d_of_orbit_boundary']:.2f} "
            f"R={od['circular_mean_resultant_R']}")
    else:
        log(f"TIC {tic}: orbit-phase -> {op.get('error', 'no on-data summary')}")

    res["elapsed_s"] = round(time.time() - t_start, 1)
    save()
    log(f"TIC {tic}: DONE in {res['elapsed_s']}s")


if __name__ == "__main__":
    main()
