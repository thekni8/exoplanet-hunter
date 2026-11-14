"""Offline golden tests: the pipeline end to end on the same three
known objects as the live tests, against COMMITTED fixtures
(tests/fixtures/golden/) instead of live MAST downloads.

The fixture seam (hunter._fixture_lightcurve, enabled by the
EXHUNT_FIXTURE_DIR env var) loads the stitched, cleaned light
curve from the npz; everything downstream — detrend window,
flatten, BLS, shape gate — is the production code path, and the
assertions are the SAME ones the live tests use
(tests/golden_checks.py). If the live and offline suites ever
disagree, the fixture is stale: regenerate it with
tests/make_fixtures.py.

Each test also proves the fixture was actually used (the
pipeline's raw_time matches the fixture bytes exactly). A missing
fixture must fail loudly here, never silently fall back to a live
download — the whole point of this module is that the PR gate
runs with no network.
"""
import json
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402

import hunter  # noqa: E402
from tests.golden_checks import check_eb, check_toi700, check_wasp126  # noqa: E402

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "golden"
TICS = ("150428135", "25155310", "308851365")

_PREV = None


def setUpModule():
    global _PREV
    missing = [f"TIC_{t}.npz" for t in TICS
               if not (FIXTURE_DIR / f"TIC_{t}.npz").exists()]
    if missing:
        # A missing fixture is a FAIL, not a skip: the PR gate
        # must never go green with the offline tests silently
        # absent. Regenerate with tests/make_fixtures.py.
        raise RuntimeError(
            "golden fixtures missing: " + ", ".join(missing) +
            " — regenerate with: "
            ".venv/bin/python tests/make_fixtures.py")
    _PREV = os.environ.get("EXHUNT_FIXTURE_DIR")
    os.environ["EXHUNT_FIXTURE_DIR"] = str(FIXTURE_DIR)


def tearDownModule():
    if _PREV is None:
        os.environ.pop("EXHUNT_FIXTURE_DIR", None)
    else:
        os.environ["EXHUNT_FIXTURE_DIR"] = _PREV


def _fixture_meta(tic):
    z = np.load(FIXTURE_DIR / f"TIC_{tic}.npz")
    return z, json.loads(str(z["meta_json"]))


def _assert_fixture_used(tc, full, tic):
    """The pipeline's raw arrays must be the fixture's bytes —
    proof the seam fired and no download happened."""
    z, _meta = _fixture_meta(tic)
    tc.assertTrue(
        np.array_equal(np.asarray(full["raw_time"], dtype=float),
                       np.asarray(z["t"], dtype=float)),
        msg=f"TIC {tic}: raw_time does not match the fixture — "
            f"the live path ran instead of the offline seam")


class TestGoldenFixtures(unittest.TestCase):
    def test_toi700_offline(self):
        full = hunter._run_pipeline("150428135", star_radius=0.42,
                                    max_sectors=2)
        _assert_fixture_used(self, full, "150428135")
        check_toi700(self, full)

    def test_wasp126_offline(self):
        full = hunter._run_pipeline("25155310", star_radius=1.30,
                                    max_sectors=1)
        _assert_fixture_used(self, full, "25155310")
        check_wasp126(self, full)

    def test_eb_offline(self):
        _z, meta = _fixture_meta("308851365")
        full = hunter._run_pipeline("308851365", star_radius=1.0,
                                    max_sectors=1)
        _assert_fixture_used(self, full, "308851365")
        check_eb(self, full, meta["rho_star_solar"])


if __name__ == "__main__":
    unittest.main()
