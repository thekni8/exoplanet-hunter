"""Tests for the array-based holdout (Phase 2 vote follow-up
P-19). No downloads.

The agreement test monkeypatches hunter._run_pipeline +
persistence._sector_ranges so holdout_test() (the pipeline
path) and holdout_from_arrays() (the array path) run on
identical inputs — their result dicts must be identical, so
the factorisation changed no fold logic. The synthetic tests
run the array path end-to-end on 4-sector light curves: a
signal in all 4 sectors PASSES; a signal in 2 of 4 FAILS
(the held-out no-signal folds read ~0 while the signal
folds predict).
"""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402

import holdout_test  # noqa: E402
from gauntlet.desk import LiveDataSource  # noqa: E402

P = 3.9227
T0 = 1500.5
DUR_D = 0.105
DUR_H = DUR_D * 24.0
DEPTH = 0.01


def _sector_times(start, ndays=27.0, cadence_min=10.0):
    return start + np.arange(0, ndays, cadence_min / 1440.0)


def _inject(t, depth):
    f = np.ones_like(t)
    ph = ((t - T0 + 0.5 * P) % P) - 0.5 * P
    f[np.abs(ph) <= DUR_D / 2] -= depth
    return f


def _fixture(per_sector_depth, seed=11):
    """(t, f, ranges): 27 d sectors, 3 d gaps, 10-min cadence."""
    rng = np.random.default_rng(seed)
    ts, fs, ranges = [], [], []
    for i, d in enumerate(per_sector_depth):
        t = _sector_times(1500.0 + 30.0 * i)
        f = _inject(t, d) * (1.0 + rng.normal(0, 0.0005, len(t)))
        ts.append(t)
        fs.append(f)
        ranges.append({"sector": 96 + i, "tmin": float(t.min()),
                       "tmax": float(t.max())})
    return np.concatenate(ts), np.concatenate(fs), ranges


class TestHoldoutFromArrays(unittest.TestCase):
    def test_pipeline_path_agrees_with_array_path(self):
        t, f, ranges = _fixture([DEPTH] * 4)
        pipeline = {"flat_time": t, "flat_flux": f,
                    "raw_time": t, "raw_flux": f}
        with mock.patch("hunter._run_pipeline",
                        return_value=pipeline), mock.patch(
                            "persistence._sector_ranges",
                            return_value=ranges):
            via_pipeline = holdout_test.holdout_test(
                "999999999", P, T0, DUR_H)
        via_arrays = holdout_test.holdout_from_arrays(
            t, f, t, f, ranges, "999999999", P, T0, DUR_H)
        self.assertEqual(via_pipeline, via_arrays)

    def test_signal_in_all_sectors_passes(self):
        t, f, ranges = _fixture([DEPTH] * 4)
        res = holdout_test.holdout_from_arrays(
            t, f, t, f, ranges, "999999999", P, T0, DUR_H)
        self.assertEqual(res["verdict"], "HOLDOUT-PASS")
        self.assertEqual(res["n_usable_folds"], 4)
        self.assertTrue(all(fold["signif"] >= 3.0
                            for fold in res["folds"]
                            if fold["usable"]))

    def test_signal_in_two_of_four_fails(self):
        # Era-confined signal: the two signal folds predict,
        # the two held-out no-signal folds read ~0 — a strict
        # majority above the bar is impossible.
        t, f, ranges = _fixture([DEPTH, DEPTH, 0.0, 0.0])
        res = holdout_test.holdout_from_arrays(
            t, f, t, f, ranges, "999999999", P, T0, DUR_H)
        self.assertEqual(res["verdict"], "HOLDOUT-FAIL")
        self.assertEqual(res["n_usable_folds"], 4)
        self.assertEqual(res["folds_at_or_above_bar"], 2)

    def test_two_sectors_is_insufficient(self):
        t, f, ranges = _fixture([DEPTH] * 2)
        res = holdout_test.holdout_from_arrays(
            t, f, t, f, ranges, "999999999", P, T0, DUR_H)
        self.assertEqual(res["verdict"],
                         "HOLDOUT-INSUFFICIENT-DATA")

    def test_duplicate_product_ranges_merge(self):
        # One range per product: the same sector twice must
        # still fold as one sector, or the same photons sit
        # on both sides of a fold boundary.
        t, f, ranges = _fixture([DEPTH] * 4)
        doubled = ranges + [dict(r) for r in ranges]
        res = holdout_test.holdout_from_arrays(
            t, f, t, f, doubled, "999999999", P, T0, DUR_H)
        self.assertEqual(res["n_sectors_total"], 4)
        self.assertEqual(res["n_folds"], 4)
        self.assertEqual(res["verdict"], "HOLDOUT-PASS")


class TestLiveSourceHoldout(unittest.TestCase):
    def test_arrays_path_skips_the_pipeline(self):
        src = LiveDataSource()
        arrays = {"flat_t": np.array([1.0]), "flat_f": np.array([1.0]),
                  "raw_t": np.array([1.0]), "raw_f": np.array([1.0]),
                  "ranges": []}
        with mock.patch(
                "holdout_test.holdout_from_arrays",
                return_value={"verdict": "HOLDOUT-PASS"}) as arr, \
                mock.patch(
                    "holdout_test.holdout_test") as pipe:
            verdict = src.holdout("999999999", P, T0, DUR_H,
                                  arrays=arrays)
        self.assertEqual(verdict, "HOLDOUT-PASS")
        arr.assert_called_once()
        pipe.assert_not_called()

    def test_no_arrays_falls_back_to_the_pipeline(self):
        src = LiveDataSource()
        with mock.patch(
                "holdout_test.holdout_from_arrays") as arr, \
                mock.patch(
                    "holdout_test.holdout_test",
                    return_value={"verdict": "HOLDOUT-FAIL"}) as pipe:
            verdict = src.holdout("999999999", P, T0, DUR_H)
        self.assertEqual(verdict, "HOLDOUT-FAIL")
        pipe.assert_called_once()
        arr.assert_not_called()


if __name__ == "__main__":
    unittest.main()
