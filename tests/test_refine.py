"""Period-refinement tests (Phase 2, 2A).

refine_ephemeris is the narrow-grid BLS refit promoted verbatim
from holdout_test._refine_ephemeris. The vetting manual (§2)
requires refinement before any fixed-ephemeris fold: bulk-screen
periods carry +0.0004 to -0.0036 d errors, enough to smear a
fold over a multi-sector baseline. These tests prove the
promotion preserved the behaviour:

  * a filed period off by +0.001 d (the bulk error scale) is
    recovered to the true period on a synthetic transit;
  * the holdout_test alias still points at the same function
    (holdout_extended / holdout_supp call it through there);
  * degenerate inputs return None / an unconverged native that
    carries the filed ephemeris (never a silent substitution).
"""
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import holdout_test  # noqa: E402
from gauntlet.common import fold_depth  # noqa: E402
from gauntlet.refine import refine_ephemeris, refine_native  # noqa: E402


def _synthetic(P=3.9227, T0=1500.5, DUR=0.1, DEPTH=0.01, seed=11):
    """One 27 d sector, 2-min cadence, a box transit + white noise."""
    rng = np.random.default_rng(seed)
    t = 1500.0 + np.arange(0, 27.0, 2.0 / 1440.0)
    f = 1.0 + rng.normal(0, 0.001, len(t))
    ph = ((t - T0 + 0.5 * P) % P) - 0.5 * P
    f[np.abs(ph) <= DUR / 2] -= DEPTH
    return t, f


class TestRefine(unittest.TestCase):
    def test_recovers_bulk_error_scale(self):
        t, f = _synthetic()
        ref = refine_ephemeris(t, f, 3.9237, 0.1)  # +0.001 d off
        self.assertIsNotNone(ref, "refit failed on a clean synthetic")
        p_ref, t0_ref = ref
        self.assertAlmostEqual(p_ref, 3.9227, delta=5e-4)
        fold = fold_depth(t, f, p_ref, t0_ref, 0.1)
        self.assertIsNotNone(fold)
        self.assertGreater(fold["depth_pct"], 0.8)

    def test_alias_unchanged(self):
        self.assertIs(holdout_test._refine_ephemeris, refine_ephemeris)
        self.assertEqual(holdout_test.REFINE_PERIOD_TOL_FRAC, 0.01)
        self.assertEqual(holdout_test.REFINE_GRID_HALF_FRAC, 0.015)

    def test_degenerate_inputs(self):
        t, f = _synthetic()
        self.assertIsNone(refine_ephemeris(t[:100], f[:100], 3.9227, 0.1))
        self.assertIsNone(refine_ephemeris(t, f, 0.0, 0.1))
        self.assertIsNone(refine_ephemeris(t, f, 3.9227, 0.0))
        native = refine_native(t[:100], f[:100], 3.9227, 1500.5, 0.1)
        self.assertFalse(native["converged"])
        self.assertEqual(native["period_d"], 3.9227)
        self.assertEqual(native["t0"], 1500.5)

    def test_native_converged(self):
        t, f = _synthetic()
        native = refine_native(t, f, 3.9237, 1500.5, 0.1, n_eras=2)
        self.assertTrue(native["converged"])
        self.assertAlmostEqual(native["period_d"], 3.9227, delta=5e-4)
        self.assertEqual(native["n_eras"], 2)


if __name__ == "__main__":
    unittest.main()
