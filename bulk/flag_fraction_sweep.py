#!/usr/bin/env python
"""Flag-fraction sweep: the sensitivity cost of the v3 quality mask.

Measures how much a real transit loses when scattered-light flags
(bits 29/30) cover 5/10/20% of cadences, mask on (bulk_v3) vs off
(bulk_v2) — through the REAL screen (bulk_screen._screen_one on
synthetic QLP FITS), no mirrors, no re-implemented BLS.

Fixture: a WASP-29b-equivalent transit (P 3.9227 d, 1.14% depth,
0.3% noise) — the known planet v2 recovered and v1 missed — plus
a marginal shallow cell (0.5% depth, MES 8.5 under v2, just below
the tier-A bar of 9.0). Every cell shares flux seed 42, so the
underlying light curve is identical across cells and only the
QUALITY flags differ; flag placements are seeded per cell.

Topology (Gemini's critique, 2026-11-15 vote): real bits 29/30
come in contiguous 0.5-2.5-day blocks, not random sprinkles, so
the sweep runs BOTH topologies:
  random  flags placed uniformly at random (the original sweep);
  blocks  contiguous blocks of uniform(0.5, 2.5) d, placed at
          random starts until the target fraction is reached.
Placement: `all` (any cadence may be flagged) or `off_transit`
(only out-of-transit cadences — the control where flags never
touch the transit). Flag bit is 29 throughout (the original
sweep's choice); the topology is the variable, not the bit.

History: the first version of this sweep lived at
/tmp/flag_fraction_sweep.py and was LOST when the VM was replaced
(/tmp is wiped). This committed version (M-5, 2026-11-15) was
rewritten from the table in bulk/SENSITIVITY_MAP.md section v3
plus the PROGRESS.md C-6 description. Its numbers are close to
the original's but not bit-identical (the original flag seeds
are unrecoverable); the conclusions are the same -- see the
table it prints and SENSITIVITY_MAP.md.

Outputs (in --out-dir, default /tmp/flag_fraction_sweep):
  cells.jsonl    one record per (cell, calibration) run
  summary.json   the plan + per-cell v2/v3 SDE/MES/status
  (stdout)       the markdown table for SENSITIVITY_MAP.md

Usage:
  python bulk/flag_fraction_sweep.py [--out-dir DIR] [--quick]
  --quick runs 3 cells (clean, random 20% all, blocks 20% all)
  instead of the full 13 -- the CI smoke subset.
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
from synth_fits import make_qlp_fits, screen_job  # noqa: E402

PERIOD_D = 3.9227
DEPTH_FRAC = 0.0114
MARGINAL_DEPTH_FRAC = 0.005
DURATION_D = 0.1
NOISE_PCT = 0.003
FLUX_SEED = 42
FLAG_BIT = 29
FLAG_SEED_BASE = 1000
BLOCK_MIN_D = 0.5
BLOCK_MAX_D = 2.5
CADENCE_MIN = 30.0
N_POINTS = 1296
CALIBRATIONS = ("bulk_v2", "bulk_v3")

# (label, depth_frac, topology, placement, frac)
# topology None = clean (no flags).
PLAN = [
    ("clean", DEPTH_FRAC, None, "all", 0.0),
    ("random 5% all", DEPTH_FRAC, "random", "all", 0.05),
    ("random 10% all", DEPTH_FRAC, "random", "all", 0.10),
    ("random 20% all", DEPTH_FRAC, "random", "all", 0.20),
    ("random 10% off-transit", DEPTH_FRAC, "random", "off_transit", 0.10),
    ("random 20% off-transit", DEPTH_FRAC, "random", "off_transit", 0.20),
    ("blocks 10% all", DEPTH_FRAC, "blocks", "all", 0.10),
    ("blocks 20% all", DEPTH_FRAC, "blocks", "all", 0.20),
    ("blocks 10% off-transit", DEPTH_FRAC, "blocks", "off_transit", 0.10),
    ("blocks 20% off-transit", DEPTH_FRAC, "blocks", "off_transit", 0.20),
    ("marginal 0.5% clean", MARGINAL_DEPTH_FRAC, None, "all", 0.0),
    ("marginal 0.5% random 10% all", MARGINAL_DEPTH_FRAC,
     "random", "all", 0.10),
    ("marginal 0.5% random 20% all", MARGINAL_DEPTH_FRAC,
     "random", "all", 0.20),
]

QUICK_LABELS = {"clean", "random 20% all", "blocks 20% all"}


def _flag_callable(frac, topology, placement, seed):
    """quality callable for make_qlp_fits: flag `frac` of ALL
    cadences with bit 29, in the given topology/placement."""
    def _q(t, in_transit):
        rng = np.random.default_rng(seed)
        q = np.zeros(len(t), dtype=np.int32)
        target = int(round(frac * len(t)))
        if topology == "random":
            pool = (np.where(~in_transit)[0]
                    if placement == "off_transit"
                    else np.arange(len(t)))
            chosen = rng.choice(
                pool, size=min(target, len(pool)), replace=False)
            q[chosen] = np.int32(1 << FLAG_BIT)
        else:  # blocks: contiguous 0.5-2.5 d stretches
            flagged = np.zeros(len(t), dtype=bool)
            lo = int(BLOCK_MIN_D * 24 * 60 / CADENCE_MIN)
            hi = int(BLOCK_MAX_D * 24 * 60 / CADENCE_MIN)
            tries = 0
            while int(flagged.sum()) < target and tries < 10000:
                tries += 1
                start = int(rng.integers(0, len(t)))
                blen = int(rng.integers(lo, hi + 1))
                span = np.arange(start, min(start + blen, len(t)))
                if placement == "off_transit":
                    span = span[~in_transit[span]]
                flagged[span] = True
            q[flagged] = np.int32(1 << FLAG_BIT)
        return q
    return _q


def build_plan(quick=False):
    """The fixed cell list, in plan order."""
    cells = []
    for i, (label, depth, topology, placement, frac) in enumerate(PLAN):
        if quick and label not in QUICK_LABELS:
            continue
        cells.append({"label": label, "depth_frac": depth,
                      "topology": topology, "placement": placement,
                      "flag_frac": frac,
                      "flag_seed": FLAG_SEED_BASE + i})
    return cells


def run_cell(cell, workdir):
    """Screen one cell under v2 and v3. Returns a record with
    both calibrations' SDE/MES/status (+ the actual flagged
    fraction measured from the written FITS)."""
    path = Path(workdir) / f"{cell['label'].replace(' ', '_')}.fits"
    kw = dict(period_d=PERIOD_D, depth_frac=cell["depth_frac"],
              duration_d=DURATION_D, noise_pct=NOISE_PCT,
              seed=FLUX_SEED)
    if cell["topology"] is not None:
        kw["quality"] = _flag_callable(
            cell["flag_frac"], cell["topology"], cell["placement"],
            cell["flag_seed"])
    make_qlp_fits(path, **kw)
    from astropy.io import fits
    with fits.open(path) as hdul:
        q = np.asarray(hdul[1].data["QUALITY"])
    actual_frac = float((q != 0).mean())
    out = {"cell": cell["label"], "depth_frac": cell["depth_frac"],
           "topology": cell["topology"],
           "placement": cell["placement"],
           "flag_frac_target": cell["flag_frac"],
           "flag_frac_actual": actual_frac,
           "flag_seed": cell["flag_seed"]}
    for cal in CALIBRATIONS:
        bs.set_calibration(cal)
        r = bs._screen_one(screen_job(path))
        out[cal] = {"sde": r.get("sde"),
                    "mes_pink": r.get("mes_pink"),
                    "status": r.get("status"),
                    "tier": r.get("tier"),
                    "period_days": r.get("period_days")}
    return out


def _fmt(x, nd=1):
    return f"{x:.{nd}f}" if x is not None else "—"


def print_table(records):
    print()
    print("| Cell | v2 SDE / MES | v3 SDE / MES | v3 status |")
    print("|---|---|---|---|")
    for rec in records:
        v2, v3 = rec["bulk_v2"], rec["bulk_v3"]
        print(f"| {rec['cell']} | {_fmt(v2['sde'])} / "
              f"{_fmt(v2['mes_pink'])} | {_fmt(v3['sde'])} / "
              f"{_fmt(v3['mes_pink'])} | {v3['status']}"
              f"{' ' + v3['tier'] if v3.get('tier') else ''} |")
    print()


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Flag-fraction sweep: v3 mask cost (see module "
                    "docstring).")
    ap.add_argument("--out-dir", default="/tmp/flag_fraction_sweep",
                    help="output directory (cells.jsonl + summary.json)")
    ap.add_argument("--quick", action="store_true",
                    help="3 cells only (clean, random 20%% all, "
                         "blocks 20%% all)")
    args = ap.parse_args(argv)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    workdir = out_dir / "fits"
    workdir.mkdir(exist_ok=True)
    plan = build_plan(quick=args.quick)
    t0 = time.time()
    records = []
    previous = bs.CALIBRATION_VERSION
    try:
        with open(out_dir / "cells.jsonl", "w") as fh:
            for i, cell in enumerate(plan):
                rec = run_cell(cell, workdir)
                records.append(rec)
                fh.write(json.dumps(rec) + "\n")
                fh.flush()
                print(f"[sweep] {i + 1}/{len(plan)} {cell['label']}: "
                      f"v2 SDE {_fmt(rec['bulk_v2']['sde'])} / MES "
                      f"{_fmt(rec['bulk_v2']['mes_pink'])} | v3 SDE "
                      f"{_fmt(rec['bulk_v3']['sde'])} / MES "
                      f"{_fmt(rec['bulk_v3']['mes_pink'])} "
                      f"({rec['bulk_v3']['status']})", flush=True)
    finally:
        bs.set_calibration(previous)
    summary = {"tool": "flag_fraction_sweep",
               "period_d": PERIOD_D, "depth_frac": DEPTH_FRAC,
               "marginal_depth_frac": MARGINAL_DEPTH_FRAC,
               "noise_pct": NOISE_PCT, "flux_seed": FLUX_SEED,
               "flag_bit": FLAG_BIT, "quick": bool(args.quick),
               "cells": records,
               "wall_seconds": time.time() - t0}
    (out_dir / "summary.json").write_text(
        json.dumps(summary, indent=2))
    print_table(records)
    # "Lost" means v2 found it and v3 did not -- a cell that was
    # never a survivor under v2 (e.g. the marginal clean cell,
    # recorded under both) is not a loss.
    lost = [r["cell"] for r in records
            if r["bulk_v2"]["status"] == "survivor"
            and r["bulk_v3"]["status"] != "survivor"]
    print(f"[sweep] done: {len(records)} cells in "
          f"{summary['wall_seconds']:.0f}s; v3 lost: "
          f"{lost if lost else 'none'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
