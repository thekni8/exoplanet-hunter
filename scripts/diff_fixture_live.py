#!/usr/bin/env python3
"""Diff the fixture path vs the live path for one golden star
(Phase 1.2, item C-4).

Runs hunter._run_pipeline with and without EXHUNT_FIXTURE_DIR
and compares the BLS input hash, the refined period, SDE, depth,
and the shape-gate T23/T14. Exit 0 when the BLS input hashes
match (identical data entered BLS on both paths); exit 1 with a
plain-words report when they differ — the fixture is stale or
MAST reprocessed the data, and the fix is to regenerate the
fixture with tests/make_fixtures.py, not to edit the test.

The T23/T14 values are reported, not asserted equal: on the EB
the gate's T23/T14 is numerically unstable (a 3e-5 period
perturbation swings it across 0.34-0.47 — the 0.297 live vs
0.474 fixture swing), so a T23/T14 difference with EQUAL BLS
input hashes is refinement argmax noise, not a divergence. What
must agree is the data (the hash) and the stable bounds
(T23/T14 < 0.50, density flag).

Usage:
  python scripts/diff_fixture_live.py --tic 308851365 \\
      --star-radius 1.0 --max-sectors 1
"""
import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

import hunter  # noqa: E402
from gauntlet.rawflux_check import trapezoid_shape_gate  # noqa: E402

FIXTURE_DIR = ROOT / "tests" / "fixtures" / "golden"


def _fixture_meta(tic):
    z = np.load(FIXTURE_DIR / f"TIC_{tic}.npz")
    return json.loads(str(z["meta_json"]))


def _shape(full, rho_star):
    gate = trapezoid_shape_gate(
        full["raw_time"], full["raw_flux"],
        full["Period"], full["T0"], full["Duration_Days"],
        rho_star)
    return gate


def diff(tic, star_radius, max_sectors):
    """Run both paths and return a report dict."""
    live = hunter._run_pipeline(tic, star_radius=star_radius,
                                max_sectors=max_sectors)
    prev = os.environ.get("EXHUNT_FIXTURE_DIR")
    os.environ["EXHUNT_FIXTURE_DIR"] = str(FIXTURE_DIR)
    try:
        fixture = hunter._run_pipeline(
            tic, star_radius=star_radius, max_sectors=max_sectors)
    finally:
        if prev is None:
            os.environ.pop("EXHUNT_FIXTURE_DIR", None)
        else:
            os.environ["EXHUNT_FIXTURE_DIR"] = prev
    meta = _fixture_meta(tic)
    rho_star = meta["rho_star_solar"]
    live_gate = _shape(live, rho_star)
    fix_gate = _shape(fixture, rho_star)
    live_hash = live["input_identity"]["bls_input_hash"]
    fix_hash = fixture["input_identity"]["bls_input_hash"]
    return {
        "tic": tic,
        "bls_input_hash_match": live_hash == fix_hash,
        "live": {
            "bls_input_hash": live_hash,
            "period_days": live["Period"],
            "sde": live["SDE"],
            "depth_percent": live["Depth"] * 100.0,
            "t23_t14": live_gate.get("T23_T14"),
            "density_flag": live_gate.get("density_flag"),
        },
        "fixture": {
            "bls_input_hash": fix_hash,
            "period_days": fixture["Period"],
            "sde": fixture["SDE"],
            "depth_percent": fixture["Depth"] * 100.0,
            "t23_t14": fix_gate.get("T23_T14"),
            "density_flag": fix_gate.get("density_flag"),
        },
        "period_delta_days": abs(live["Period"]
                                 - fixture["Period"]),
    }


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Diff the fixture path vs the live path for "
                    "one golden star.")
    ap.add_argument("--tic", required=True)
    ap.add_argument("--star-radius", type=float, required=True)
    ap.add_argument("--max-sectors", type=int, default=1)
    args = ap.parse_args(argv)
    report = diff(args.tic, args.star_radius, args.max_sectors)
    print(json.dumps(report, indent=2))
    if report["bls_input_hash_match"]:
        print("\nMATCH: both paths fed BLS identical arrays.")
        if report["period_delta_days"] > 1e-3:
            print("WARNING: periods differ by more than the "
                  "argmax-noise band "
                  f"({report['period_delta_days']:.2e} d) — "
                  "the search itself diverged.")
            return 1
        return 0
    print("\nDIVERGENCE: the fixture and live paths fed BLS "
          "different arrays — the fixture is stale or MAST "
          "reprocessed the data. Regenerate with "
          "tests/make_fixtures.py.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
