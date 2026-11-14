#!/usr/bin/env python
"""Depth x noise clip grid (Phase 1.2, B-2).

Measures the bulk screen's MAD-clip options on synthetic
one-sector stars through the REAL screen (bulk_screen._screen_one
on synthetic QLP FITS) — no mirrors, no re-implemented BLS.
The option is chosen by the PRE-REGISTERED criteria in
bulk/CLIP_GRID_CRITERIA.md; this script only produces the
numbers.

Cells (fixed by the pre-registration): depths 0.5/1.0/1.5/3.0%,
noise 0.1/0.3/1.0%, periods 2.17/7.31 d, seeds 42/43, plus
noise-only nulls (seeds 42-45 per noise level). Each cell runs
under all five clip settings (four options + `none`, the
unclipped reference): 300 screen runs, a few minutes.

Checkpointing: one JSON line per (cell, option) run, appended
to <out-dir>/cells.jsonl as it completes. --resume skips runs
already in the file, so an interrupted grid resumes instead of
restarting. --max-cells caps the run (cells are taken in plan
order; the cap is a bound on runtime, not a selection).

Outputs (in --out-dir, default /tmp/clip_grid):
  cells.jsonl    one record per run (the checkpoint)
  summary.json   per-option aggregates + the decision inputs

Usage:
  python bulk/clip_grid.py [--out-dir DIR] [--resume] [--max-cells N]
"""
import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import bulk_screen as bs  # noqa: E402
from mad_clip import mad_clip_mask  # noqa: E402
from synth_fits import make_qlp_fits, screen_job  # noqa: E402

DEPTHS_PCT = [0.5, 1.0, 1.5, 3.0]
NOISE_PCT = [0.001, 0.003, 0.01]
PERIODS_D = [2.17, 7.31]
SEEDS = [42, 43]
NULL_SEEDS = [42, 43, 44, 45]
DURATION_D = 0.1
N_POINTS = 1296
CADENCE_MIN = 30.0
T_START = 1500.0
OPTIONS = ["symmetric", "upward_only", "isolated_low_only",
           "floor_10pct", "none"]
SURVIVOR_SDE = 7.0  # the screen bar (bulk_v1 survivor_sde)


def build_plan():
    """The fixed cell list, in plan order."""
    cells = []
    for depth in DEPTHS_PCT:
        for noise in NOISE_PCT:
            for period in PERIODS_D:
                for seed in SEEDS:
                    cells.append({"kind": "inject",
                                  "depth_pct": depth,
                                  "noise_pct": noise,
                                  "period_d": period,
                                  "seed": seed})
    for noise in NOISE_PCT:
        for seed in NULL_SEEDS:
            cells.append({"kind": "null",
                          "depth_pct": 0.0,
                          "noise_pct": noise,
                          "period_d": None,
                          "seed": seed})
    return cells


def _transit_mask(t, period_d):
    """In-transit mask for a synth_fits star (t0 = T_START + 2.0,
    transits centred at t0 + k*P)."""
    t0 = T_START + 2.0
    phase = ((t - t0 + 0.5 * period_d) % period_d) - 0.5 * period_d
    return np.abs(phase) < DURATION_D / 2.0


def _load_arrays(path):
    from astropy.io import fits
    with fits.open(path) as hdul:
        d = hdul[1].data
        return (np.asarray(d["TIME"], dtype=float),
                np.asarray(d["KSPSAP_FLUX"], dtype=float))


def run_cell(cell, options, fits_dir):
    """Build one synthetic star, screen it under each option.
    Returns one record per option."""
    tag = (f"{cell['kind']}_d{cell['depth_pct']}_n"
           f"{cell['noise_pct']}_p{cell['period_d']}_s{cell['seed']}")
    path = Path(fits_dir) / f"{tag}.fits"
    make_qlp_fits(
        path, n_points=N_POINTS, cadence_min=CADENCE_MIN,
        t_start=T_START,
        period_d=cell["period_d"] if cell["kind"] == "inject" else None,
        depth_frac=cell["depth_pct"] / 100.0,
        duration_d=DURATION_D, noise_pct=cell["noise_pct"],
        seed=cell["seed"])
    t, f = _load_arrays(path)
    f_norm = f / np.median(f)
    in_transit = (_transit_mask(t, cell["period_d"])
                  if cell["kind"] == "inject" else None)
    records = []
    for option in options:
        keep = mad_clip_mask(f_norm, option)
        bs.set_clip_option(option)
        rec = bs._screen_one(screen_job(path))
        out = {
            "cell": cell, "option": option,
            "status": rec.get("status"),
            "tier": rec.get("tier"),
            "sde": rec.get("sde"),
            "period_days": rec.get("period_days"),
            "depth_percent": rec.get("depth_percent"),
            "n_points_kept": int(keep.sum()),
            "n_points_total": int(len(f)),
        }
        if in_transit is not None and in_transit.sum() > 0:
            out["transit_kept_frac"] = float(
                keep[in_transit].mean())
            out["n_transit_points"] = int(in_transit.sum())
            p_inj = cell["period_d"]
            p_rec = rec.get("period_days")
            out["recovered"] = bool(
                rec.get("status") == "survivor"
                and rec.get("sde") is not None
                and rec["sde"] >= SURVIVOR_SDE
                and p_rec is not None
                and abs(p_rec - p_inj) / p_inj <= 0.01)
        else:
            out["false_alarm"] = bool(
                rec.get("status") == "survivor")
        records.append(out)
    return records


def summarize(records):
    """Per-option aggregates (the decision inputs)."""
    by_option = {}
    for option in OPTIONS:
        rows = [r for r in records if r["option"] == option]
        inj = [r for r in rows if r["cell"]["kind"] == "inject"]
        nulls = [r for r in rows if r["cell"]["kind"] == "null"]
        deep = [r for r in inj
                if r["cell"]["depth_pct"] >= 1.5
                and r["cell"]["noise_pct"] <= 0.003]
        by_option[option] = {
            "n_inject": len(inj),
            "n_null": len(nulls),
            "recovery_all": (
                sum(r["recovered"] for r in inj) / len(inj)
                if inj else None),
            "recovery_deep_quiet": (
                sum(r["recovered"] for r in deep) / len(deep)
                if deep else None),
            "null_false_alarm_rate": (
                sum(r["false_alarm"] for r in nulls) / len(nulls)
                if nulls else None),
            "mean_transit_kept_frac": (
                float(np.mean([r["transit_kept_frac"] for r in inj
                               if "transit_kept_frac" in r]))
                if inj else None),
        }
    # Monotonicity: on every (noise, period, seed) slice, the
    # deeper transit must not score below the shallower one.
    mono = {}
    for option in OPTIONS:
        rows = [r for r in records if r["option"] == option
                and r["cell"]["kind"] == "inject"]
        violations = []
        for noise in NOISE_PCT:
            for period in PERIODS_D:
                for seed in SEEDS:
                    sde = {}
                    for r in rows:
                        c = r["cell"]
                        if (c["noise_pct"] == noise
                                and c["period_d"] == period
                                and c["seed"] == seed
                                and r["sde"] is not None):
                            sde[c["depth_pct"]] = r["sde"]
                    for lo, hi in ((1.0, 1.5), (1.5, 3.0)):
                        if lo in sde and hi in sde \
                                and sde[hi] < sde[lo]:
                            violations.append(
                                {"noise_pct": noise,
                                 "period_d": period, "seed": seed,
                                 "sde_lo": sde[lo],
                                 "sde_hi": sde[hi],
                                 "depths": [lo, hi]})
        mono[option] = {"n_violations": len(violations),
                        "violations": violations}
    return {"by_option": by_option, "monotonicity": mono}


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Depth x noise clip grid (B-2).")
    ap.add_argument("--out-dir", default="/tmp/clip_grid")
    ap.add_argument("--resume", action="store_true",
                    help="skip (cell, option) runs already in "
                         "cells.jsonl")
    ap.add_argument("--max-cells", type=int, default=None,
                    help="cap the number of cells (plan order)")
    ap.add_argument("--options", default=",".join(OPTIONS),
                    help="comma-separated clip options to run "
                         "(default: all five)")
    args = ap.parse_args(argv)
    options = [o.strip() for o in args.options.split(",") if o.strip()]
    for o in options:
        if o not in OPTIONS:
            ap.error(f"unknown clip option {o!r}")

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    cells_path = out_dir / "cells.jsonl"
    fits_dir = out_dir / "fits"
    fits_dir.mkdir(parents=True, exist_ok=True)

    done = set()
    records = []
    if args.resume and cells_path.exists():
        for line in cells_path.read_text().splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            c = r["cell"]
            done.add((c["kind"], c["depth_pct"], c["noise_pct"],
                      c["period_d"], c["seed"], r["option"]))
            records.append(r)
        print(f"[grid] resumed: {len(records)} runs already done",
              flush=True)

    plan = build_plan()
    if args.max_cells is not None:
        plan = plan[:args.max_cells]
    t0 = time.time()
    n_new = 0
    with open(cells_path, "a") as fh:
        for i, cell in enumerate(plan):
            todo = [o for o in options
                    if (cell["kind"], cell["depth_pct"],
                        cell["noise_pct"], cell["period_d"],
                        cell["seed"], o) not in done]
            if not todo:
                continue
            for rec in run_cell(cell, todo, fits_dir):
                fh.write(json.dumps(rec) + "\n")
                fh.flush()
                records.append(rec)
                n_new += 1
            if (i + 1) % 10 == 0 or i == len(plan) - 1:
                print(f"[grid] {i + 1}/{len(plan)} cells, "
                      f"{n_new} new runs, {time.time() - t0:.0f}s",
                      flush=True)
    bs.set_clip_option("symmetric")  # leave the module as found
    summary = summarize(records)
    summary["n_cells"] = len(plan)
    summary["n_runs"] = len(records)
    summary["wall_s"] = time.time() - t0
    (out_dir / "summary.json").write_text(
        json.dumps(summary, indent=2))
    print(f"[grid] done: {len(records)} runs in "
          f"{summary['wall_s']:.0f}s", flush=True)
    for option, agg in summary["by_option"].items():
        print(f"  {option:18s} deep-quiet recovery "
              f"{agg['recovery_deep_quiet']}, null FA "
              f"{agg['null_false_alarm_rate']}, monotonicity "
              f"violations "
              f"{summary['monotonicity'][option]['n_violations']}",
              flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
