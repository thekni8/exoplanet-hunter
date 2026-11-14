"""CI clip-grid test (Phase 1.2, B-2): the headline pair.

The full grid (bulk/clip_grid.py, 300 runs) is a report, not a
CI test — this module pins its headline result in the golden
suite: on 0.3% noise at P 2.17 d (seed 42), a 1.5% transit must
score at least as high as a 1.0% one. Under v1's symmetric clip
the deeper transit scores LOWER (SDE 62.6 vs 69.8 — the clip
eats the transit); under v2's floored clip it scores higher
(101.7 vs 72.6). The v1 case is a STRICT expected failure:
if it ever passes, the suite goes red, which is the point —
v1's defect must stay visible until v1 is retired.
"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import bulk_screen as bs  # noqa: E402
from synth_fits import make_qlp_fits, screen_job  # noqa: E402

NOISE_PCT = 0.003
PERIOD_D = 2.17
SEED = 42


def _screen(depth_pct):
    """Screen one synthetic star; return the _screen_one record."""
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / f"d{depth_pct}.fits"
        make_qlp_fits(path, period_d=PERIOD_D,
                      depth_frac=depth_pct / 100.0,
                      noise_pct=NOISE_PCT, seed=SEED)
        return bs._screen_one(screen_job(path))


class TestClipGrid(unittest.TestCase):
    def setUp(self):
        self._previous = bs.CALIBRATION_VERSION

    def tearDown(self):
        bs.set_calibration(self._previous)

    def test_monotonicity_under_v2(self):
        bs.set_calibration("bulk_v2")
        sde_10 = _screen(1.0)["sde"]
        sde_15 = _screen(1.5)["sde"]
        self.assertIsNotNone(sde_10)
        self.assertIsNotNone(sde_15)
        self.assertGreaterEqual(
            sde_15, sde_10,
            "deeper transit must not score below the shallower one")

    def test_monotonicity_under_v3(self):
        # v3 adds only the quality mask; these fixtures have
        # quality==0 everywhere, so the mask is a no-op and v3
        # must reproduce v2's SDEs EXACTLY — the mask changes
        # nothing on clean data. Monotonicity pins the pair too.
        bs.set_calibration("bulk_v2")
        v2_10 = _screen(1.0)["sde"]
        v2_15 = _screen(1.5)["sde"]
        bs.set_calibration("bulk_v3")
        v3_10 = _screen(1.0)["sde"]
        v3_15 = _screen(1.5)["sde"]
        self.assertEqual(v3_10, v2_10)
        self.assertEqual(v3_15, v2_15)
        self.assertGreaterEqual(
            v3_15, v3_10,
            "deeper transit must not score below the shallower one")

    @unittest.expectedFailure
    def test_monotonicity_under_v1(self):
        # STRICT xfail: v1's symmetric clip inverts this pair
        # (62.6 vs 69.8). If it ever passes, the suite goes red.
        bs.set_calibration("bulk_v1")
        sde_10 = _screen(1.0)["sde"]
        sde_15 = _screen(1.5)["sde"]
        self.assertIsNotNone(sde_10)
        self.assertIsNotNone(sde_15)
        self.assertGreaterEqual(sde_15, sde_10)

    def test_null_under_v2_is_not_a_survivor(self):
        bs.set_calibration("bulk_v2")
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "null.fits"
            make_qlp_fits(path, period_d=None,
                          noise_pct=NOISE_PCT, seed=SEED)
            rec = bs._screen_one(screen_job(path))
        self.assertNotEqual(rec["status"], "survivor")
