"""Blend pure-function tests (Phase 1.2, item A-6).

Offline only: the headline case is the synthetic TIC 139526205
fixture (tests/fixtures/blend/ — box transits at the real
ephemeris with the real depths; the curves are synthetic, the
verdict is the real case's). The other cases are built in
memory. No downloads anywhere.
"""
import json
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gauntlet.blend import check_blend  # noqa: E402
from gauntlet.stage_result import (  # noqa: E402
    REQUIRED_STAGES, aggregate_verdict, blend_result)

FIX = Path(__file__).resolve().parent / "fixtures" / "blend"
PROV = {"calibration_version": "gauntlet_v2",
        "pipeline_git_sha": "test",
        "run_id": "test-run-1",
        "timestamp_utc": "2026-11-14T00:00:00+00:00"}
IMAGING_ON = {"on_target": True, "offset_px": 0.06,
              "offset_arcsec": 1.3}

PERIOD = 2.9220404
T0 = 1500.5
DUR = 3.17 / 24.0


def _box_lc(depth_pct, sigma, n=21600, seed=1, period=PERIOD,
            t0=T0, dur=DUR):
    """A synthetic light curve: a box dip at the ephemeris +
    white noise. depth_pct 0.0 gives a flat curve."""
    rng = np.random.default_rng(seed)
    t = 1500.0 + np.arange(n) * (30.0 / n)
    ph = (((t - t0) / period + 0.5) % 1.0) - 0.5
    hw = 0.5 * dur / period
    f = np.where(np.abs(ph) < hw, 1.0 - depth_pct / 100.0, 1.0)
    return t, f + rng.normal(0, sigma, n)


def _native(target_depth, neighbour_depth, target_sigma=0.005,
            neighbour_sigma=0.01, seed=1):
    t_t, f_t = _box_lc(target_depth, target_sigma, seed=seed)
    t_n, f_n = _box_lc(neighbour_depth, neighbour_sigma,
                       seed=seed + 100)
    return {"target_t": t_t, "target_f": f_t,
            "neighbour_t": t_n, "neighbour_f": f_n,
            "period_d": PERIOD, "t0": T0, "duration_d": DUR,
            "neighbour_tic": "139524628",
            "separation_arcsec": 66.5}


def _all_pass_with_blend(blend_status_result):
    from gauntlet.stage_result import StageResult
    results = [StageResult(s, "pass", "ok", PROV)
               for s in REQUIRED_STAGES if s != "blend"]
    results.append(blend_status_result)
    return results


class TestSynthetic139526205(unittest.TestCase):
    def test_fixture_is_blend(self):
        # The headline case: the target's 0.505% dip is a
        # photocopy of the neighbour's ~22% EB (ratio ~44x).
        case = json.loads((FIX / "case.json").read_text())
        self.assertTrue(case["synthetic"])
        t = np.load(FIX / "tic139526205_target.npz")
        n = np.load(FIX / "tic139526205_neighbour.npz")
        r = check_blend(t["time"], t["flux"], n["time"],
                        n["flux"], case["period_d"], case["t0"],
                        case["duration_h"] / 24.0,
                        neighbour_tic=case["neighbour_tic"],
                        separation_arcsec=
                        case["separation_arcsec"])
        self.assertEqual(r["verdict"], "blend")
        self.assertGreater(r["target_signif"], 10.0)
        self.assertGreater(r["neighbour_signif"], 10.0)
        # Real ratio 22/0.505 = 43.6x; allow noise around it.
        self.assertGreater(r["depth_ratio"], 35.0)
        self.assertLess(r["depth_ratio"], 55.0)

    def test_fixture_kills_the_candidate(self):
        case = json.loads((FIX / "case.json").read_text())
        t = np.load(FIX / "tic139526205_target.npz")
        n = np.load(FIX / "tic139526205_neighbour.npz")
        native = {"target_t": t["time"], "target_f": t["flux"],
                  "neighbour_t": n["time"],
                  "neighbour_f": n["flux"],
                  "period_d": case["period_d"], "t0": case["t0"],
                  "duration_d": case["duration_h"] / 24.0,
                  "neighbour_tic": case["neighbour_tic"],
                  "separation_arcsec":
                  case["separation_arcsec"]}
        res = blend_result(native, PROV)
        self.assertEqual(res.status, "fail")
        self.assertEqual(res.stage, "blend")
        self.assertAlmostEqual(res.value, 45.5, delta=10.0)
        verdict, _note = aggregate_verdict(
            _all_pass_with_blend(res), IMAGING_ON)
        self.assertEqual(verdict, "BLEND")


class TestBlendVerdicts(unittest.TestCase):
    def test_flat_neighbour_is_on_target(self):
        native = _native(0.505, 0.0)
        r = check_blend(native["target_t"], native["target_f"],
                        native["neighbour_t"],
                        native["neighbour_f"], PERIOD, T0, DUR)
        self.assertEqual(r["verdict"], "on_target")
        self.assertEqual(blend_result(native, PROV).status,
                         "pass")

    def test_absent_target_signal_is_inconclusive(self):
        native = _native(0.0, 0.0)
        r = check_blend(native["target_t"], native["target_f"],
                        native["neighbour_t"],
                        native["neighbour_f"], PERIOD, T0, DUR)
        self.assertEqual(r["verdict"], "inconclusive")
        self.assertEqual(blend_result(native, PROV).status,
                         "inconclusive")

    def test_too_few_points_is_unmeasured(self):
        t = np.array([1500.0, 1500.1, 1500.2])
        f = np.array([1.0, 1.0, 1.0])
        r = check_blend(t, f, t, f, PERIOD, T0, DUR)
        self.assertEqual(r["verdict"], "unmeasured")
        native = {"target_t": t, "target_f": f,
                  "neighbour_t": t, "neighbour_f": f,
                  "period_d": PERIOD, "t0": T0,
                  "duration_d": DUR}
        self.assertEqual(blend_result(native, PROV).status,
                         "unmeasured")
        self.assertEqual(blend_result(None, PROV).status,
                         "unmeasured")

    def test_neighbour_below_ratio_bar_is_inconclusive(self):
        # A significant neighbour dip at 2x the target depth is
        # suspicious but below the 3x policy bar: inconclusive,
        # not a blend call and not a pass.
        native = _native(0.505, 1.01)
        r = check_blend(native["target_t"], native["target_f"],
                        native["neighbour_t"],
                        native["neighbour_f"], PERIOD, T0, DUR)
        self.assertEqual(r["verdict"], "inconclusive")
        self.assertGreater(r["neighbour_signif"], 3.0)

    def test_shallower_neighbour_signal_is_on_target(self):
        # The neighbour dips, but shallower than the target:
        # dilution only makes a photocopy shallower, so the
        # neighbour cannot be the source.
        native = _native(1.0, 0.5)
        r = check_blend(native["target_t"], native["target_f"],
                        native["neighbour_t"],
                        native["neighbour_f"], PERIOD, T0, DUR)
        self.assertEqual(r["verdict"], "on_target")

    def test_policy_override_moves_the_bar(self):
        # The fixture ratio (~44x) is a blend at the default
        # 3x bar; at a 50x bar it is inconclusive.
        case = json.loads((FIX / "case.json").read_text())
        t = np.load(FIX / "tic139526205_target.npz")
        n = np.load(FIX / "tic139526205_neighbour.npz")
        r = check_blend(t["time"], t["flux"], n["time"],
                        n["flux"], case["period_d"], case["t0"],
                        case["duration_h"] / 24.0,
                        policy={"blend_min_depth_ratio": 50.0})
        self.assertEqual(r["verdict"], "inconclusive")


if __name__ == "__main__":
    unittest.main()
