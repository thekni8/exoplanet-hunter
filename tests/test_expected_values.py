"""Tests for the expected-values file + checker (Phase 1.2, C-7).

The loader and the pure diff function. The CLI's git behaviour
is smoke-tested by hand (see the claims ledger): it depends on
the checkout's git state, which a unit test cannot pin.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.check_expected_values import (  # noqa: E402
    diff_expected_values)
from tests.expected_values import (  # noqa: E402
    load_expected_values, star_values)


class TestExpectedValuesFile(unittest.TestCase):
    def test_loader_returns_the_golden_numbers(self):
        # The numbers golden_checks.py has always asserted —
        # moved here verbatim, not re-derived.
        v = load_expected_values()
        self.assertEqual(v["schema_version"], "1.0")
        toi700 = star_values("150428135")
        self.assertEqual(toi700["headline_period_d"], 16.05094)
        self.assertEqual(toi700["headline_period_tol_d"], 0.05)
        self.assertEqual(toi700["headline_sde_min"], 8.5)
        self.assertEqual(toi700["second_period_d"], 9.97706)
        self.assertEqual(toi700["second_sde_min"], 6.5)
        wasp = star_values("25155310")
        self.assertEqual(wasp["period_d"], 3.286)
        self.assertEqual(wasp["period_tol_d"], 0.05)
        self.assertEqual(wasp["depth_frac"], 0.00631)
        self.assertEqual(wasp["depth_tol_frac"], 0.0015)
        eb = star_values("308851365")
        self.assertEqual(eb["period_d"], 0.75677)
        self.assertEqual(eb["period_tol_d"], 0.01)
        self.assertEqual(eb["t23_t14_max"], 0.5)
        self.assertTrue(eb["density_flag"])

    def test_unknown_star_raises(self):
        with self.assertRaises(KeyError):
            star_values("999999999")


class TestDiffExpectedValues(unittest.TestCase):
    def test_identical_is_quiet(self):
        old = {"stars": {"1": {"period_d": 1.0}}}
        self.assertEqual(diff_expected_values(old, old), [])

    def test_changed_leaf(self):
        old = {"stars": {"1": {"period_d": 1.0}}}
        new = {"stars": {"1": {"period_d": 1.5}}}
        lines = diff_expected_values(old, new)
        self.assertEqual(len(lines), 1)
        self.assertIn("stars.1.period_d", lines[0])
        self.assertIn("1.0 -> 1.5", lines[0])

    def test_added_and_removed(self):
        old = {"stars": {"1": {"period_d": 1.0, "sde_min": 8.5}}}
        new = {"stars": {"1": {"period_d": 1.0, "depth": 0.01},
                         "2": {"period_d": 2.0}}}
        lines = diff_expected_values(old, new)
        joined = "\n".join(lines)
        self.assertIn("stars.1.sde_min: REMOVED", joined)
        self.assertIn("stars.1.depth: ADDED", joined)
        self.assertIn("stars.2: ADDED", joined)

    def test_nested_paths(self):
        old = {"schema_version": "1.0"}
        new = {"schema_version": "2.0"}
        self.assertEqual(diff_expected_values(old, new),
                         ["schema_version: '1.0' -> '2.0'"])


if __name__ == "__main__":
    unittest.main()
