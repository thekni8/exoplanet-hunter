"""Unit tests for the persistence stamp's chi2 floor (persistence.py).

No downloads. Guards the 2026-11-13 stamp fix: the chi2 consistency
test adds a 15% systematic floor in quadrature to each sector's sigma,
because without it the test vetoes REAL signals — and vetoes stronger
signals more (chi2 grows as depth^2). The injection-recovery control
run showed TOI-700's own real signal chi2-vetoed (p 1.4e-71) before
the fix; the floor must never silently regress to zero.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from persistence import CHI2_SYS_FRAC, _chi2_consistency  # noqa: E402


class TestChi2Floor(unittest.TestCase):
    def test_systematic_floor_constant(self):
        # The 15% floor is a calibrated, Dev-approved value — if it
        # changes, it changes deliberately, with the tests updated.
        self.assertEqual(CHI2_SYS_FRAC, 0.15)

    def test_real_signal_no_longer_vetoed(self):
        # Trial-12-like case: depths scatter ~20% around the mean with
        # small formal sigmas. Unfloored, the scatter is a hard veto
        # (p << 0.01); with the 15% floor the same depths are
        # consistent (p > 0.05). This is the bug the fix exists for.
        depths = [1.00, 1.20, 0.85, 1.10]
        sigmas = [0.02, 0.02, 0.02, 0.02]
        out = _chi2_consistency(depths, sigmas)
        self.assertLess(out["chi2_p_unfloored"], 0.01)
        self.assertGreater(out["chi2_p"], 0.05)

    def test_gross_inconsistency_still_vetoes(self):
        # The floor is not a rubber stamp: a 2x depth disagreement
        # must still fail the consistency test.
        out = _chi2_consistency([1.0, 2.0], [0.01, 0.01])
        self.assertLess(out["chi2_p"], 0.01)

    def test_consistent_depths_pass(self):
        out = _chi2_consistency([1.00, 1.02, 0.99], [0.05, 0.05, 0.05])
        self.assertGreater(out["chi2_p"], 0.05)
        self.assertGreater(out["chi2_p_unfloored"], 0.05)

    def test_single_sector_has_no_chi2(self):
        out = _chi2_consistency([1.0], [0.05])
        self.assertEqual(out["dof"], 0)
        self.assertIsNone(out["chi2_p"])


if __name__ == "__main__":
    unittest.main()
