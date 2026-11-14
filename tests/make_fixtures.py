#!/usr/bin/env python3
"""Regenerate the offline golden-star fixtures (tests/fixtures/golden/).

Each fixture is the stitched, cleaned light curve (raw_time /
raw_flux) exactly as hunter._run_pipeline's live path produces it
for one golden star, plus the metadata the offline tests need
(sector cap, TIC density for the EB shape gate). The offline tests
(test_golden_fixtures.py) run the pipeline against these fixtures
with no network — the PR gate stays green through a MAST outage.

Run this when the fixtures go stale: after a pipeline change that
alters the fetch/clean path, or when the live and offline suites
disagree. It downloads the same data the live golden tests use
(tens of MB, cached by lightkurve), so run it with the venv
python from the repo root:

    .venv/bin/python tests/make_fixtures.py

The fixtures are committed to git (small npz files, < 1 MB total).
Regenerating them is a deliberate, reviewable change — a fixture
diff means the pipeline's view of a known star changed.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

import hunter  # noqa: E402
import provenance as prov  # noqa: E402
from gauntlet.rawflux_check import tic_density  # noqa: E402

FIXTURE_DIR = ROOT / "tests" / "fixtures" / "golden"

# Same arguments as the golden tests (test_golden_stars.py).
STARS = [
    {"tic": "150428135", "radius": 0.42, "max_sectors": 2},
    {"tic": "25155310", "radius": 1.30, "max_sectors": 1},
    {"tic": "308851365", "radius": 1.0, "max_sectors": 1},
]


def main():
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    sha = prov.git_sha()
    for star in STARS:
        tic = star["tic"]
        print(f"[{tic}] running live pipeline "
              f"(radius {star['radius']}, "
              f"max_sectors {star['max_sectors']})...", flush=True)
        full = hunter._run_pipeline(
            tic, star_radius=star["radius"],
            max_sectors=star["max_sectors"])
        meta = {
            "tic": tic,
            "max_sectors": star["max_sectors"],
            "star_radius": star["radius"],
            "n_sectors": int(full["Sectors_Analyzed"]),
            "n_points": int(len(full["raw_time"])),
            "live_period_d": float(full["Period"]),
            "live_sde": float(full["SDE"]),
            "generated_at": prov.utc_now_iso(),
            "pipeline_git_sha": sha,
        }
        if tic == "308851365":
            rho_star, _src = tic_density(tic)
            meta["rho_star_solar"] = rho_star
            print(f"[{tic}] rho_star = {rho_star}", flush=True)
        path = FIXTURE_DIR / f"TIC_{tic}.npz"
        np.savez_compressed(
            path, t=np.asarray(full["raw_time"], dtype=float),
            f=np.asarray(full["raw_flux"], dtype=float),
            meta_json=json.dumps(meta))
        print(f"[{tic}] wrote {path} "
              f"({meta['n_points']} pts, P={meta['live_period_d']:.5f} d, "
              f"SDE={meta['live_sde']:.1f}, "
              f"{path.stat().st_size / 1024:.0f} KB)", flush=True)
    print("fixtures done — run the offline suite to verify:")
    print("  .venv/bin/python -m unittest tests.test_golden_fixtures -v")


if __name__ == "__main__":
    main()
