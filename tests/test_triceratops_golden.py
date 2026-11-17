"""TRICERATOPS golden-fixture assertions (Phase 3, P3-7 / TB-12).

The C-10 runs, committed as fixtures
(tests/fixtures/triceratops/), asserted OFFLINE in normal CI —
the assertions, not the nightly, are the merge gate (TB-3 /
TB-12). This module is in the golden shard (the required check).

What is asserted (TB-4):
  * EB TIC 308851365 reads FAIL / refute (FPP >= 0.5).
  * WASP-29b TIC 183537452 reads INCONCLUSIVE; FPP < 0.5 (not
    a FAIL); NFPP < 0.01; the STP split dominates the FPP
    (STP > 50% of FPP). NO hard-coded FPP > 0.015 assertion,
    NO FPP-STP <= 0.015 assertion (tied to the deferred
    disposition, TB-2).
  * TOI-700 c TIC 150428135 reads INCONCLUSIVE on the same
    terms (panel row 27, retry5 — the first
    non-reconstructed fixture, measured from the panel
    workdir).
  * The disposition re-derives identically under v1 and v2
    (P-4) — v2 is a recording act, not a behaviour change.
  * Seed stability (when >= 5 seeds are committed): same
    disposition across seeds AND the FPP band clear of the
    decision boundaries (0.015 / 0.5) — "same disposition"
    alone is too simplistic for a Monte Carlo tool.

What is NOT asserted yet (visible skips, Mac work pending):
  * The >= 5-seed FPP / STP-split bands (fixtures carry one
    seed each; band width comes from the seed spread, never
    invented).

All bands are TOLERANCE BANDS, never exact floats:
TRICERATOPS fetches neighbours and TRILEGAL remotely, so
identical inputs do not guarantee bitwise-identical output.
"""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from calibration import load_profile  # noqa: E402
from gauntlet.stage_result import triceratops_result  # noqa: E402
from gauntlet.triceratops_golden import (  # noqa: E402
    MIN_SEEDS_FOR_BAND, check_fixture_output,
    check_seed_stability, load_fixture)
from validation import validate_triceratops_output  # noqa: E402


class TestGoldenFixtures(unittest.TestCase):
    def _assert_fixture(self, tic):
        fx = load_fixture(tic)
        # The fixture's tool output validates against the
        # output schema (a reconstructed fixture must still
        # be a well-formed tool output).
        validate_triceratops_output(fx["tool_output"])
        # The shared check (gauntlet/triceratops_golden.py) —
        # the same definition of "passes" the nightly uses.
        policy = load_profile("external_tools_v2")
        failures = check_fixture_output(
            fx, fx["tool_output"], policy)
        self.assertEqual(failures, [], f"TIC {tic}")
        res = triceratops_result(fx["tool_output"], policy=policy)
        return fx, res

    def test_eb_refutes(self):
        # TB-4: the EB must read FAIL/refute (FPP >= 0.5).
        fx, res = self._assert_fixture("308851365")
        self.assertEqual(res.policy_version, "external_tools_v2")
        self.assertGreaterEqual(
            fx["tool_output"]["metrics"]["fpp"], 0.5)

    def test_wasp29b_inconclusive(self):
        # TB-4: INCONCLUSIVE; FPP < 0.5 (not a FAIL);
        # NFPP < 0.01. No FPP > 0.015 assertion, no
        # FPP-STP assertion.
        fx, res = self._assert_fixture("183537452")
        self.assertEqual(res.policy_version, "external_tools_v2")
        metrics = fx["tool_output"]["metrics"]
        self.assertLess(metrics["fpp"], 0.5)
        self.assertLess(metrics["nfpp"], 0.01)

    def test_wasp29b_stp_dominates(self):
        # The STP split dominates the FPP (0.160 of 0.169 =
        # 95%) — the structural check that runs now; the
        # STP-split BAND waits for >= 5 seeds.
        fx = load_fixture("183537452")
        scenario = fx["scenario"]
        fpp = fx["tool_output"]["metrics"]["fpp"]
        share = scenario["stp"] / fpp
        self.assertGreater(
            share, fx["expected"]["stp_share_min"],
            f"STP share of FPP {share:.2f} below the "
            f"dominance bar")
        # The scenario probabilities sum to 1 (a fixture
        # integrity check, not a science assertion).
        total = (scenario["tp"] + scenario["ptp"]
                 + scenario["stp"] + scenario["seb"])
        self.assertAlmostEqual(total, 1.0, places=3)

    def test_disposition_rederives_under_v1_and_v2(self):
        # P-4: the same raw numbers read the same under v1
        # and v2 — v2 is a recording act, not a behaviour
        # change (the bars are identical).
        v1 = load_profile("external_tools_v1")
        v2 = load_profile("external_tools_v2")
        for tic in ("308851365", "183537452", "150428135"):
            fx = load_fixture(tic)
            s1 = triceratops_result(
                fx["tool_output"], policy=v1).status
            s2 = triceratops_result(
                fx["tool_output"], policy=v2).status
            self.assertEqual(
                s1, s2, f"TIC {tic}: v1 reads {s1}, v2 {s2}")

    def test_seed_band_pending(self):
        # The >= 5-seed bands are unmeasured until the Mac
        # runs them. This test skips visibly (not silently)
        # while any fixture has < 5 seeds, and asserts the
        # stability check once the seeds land.
        policy = load_profile("external_tools_v2")
        pending = []
        for tic in ("308851365", "183537452", "150428135"):
            fx = load_fixture(tic)
            if len(fx["seeds"]) < MIN_SEEDS_FOR_BAND:
                pending.append(tic)
                continue
            ok, reason = check_seed_stability(fx["seeds"], policy)
            self.assertTrue(ok, f"TIC {tic}: {reason}")
        if pending:
            self.skipTest(
                "seed band pending >= 5-seed Mac runs (P3-7) "
                f"for TIC {', '.join(pending)}")

    def test_toi700c_inconclusive(self):
        # TB-4: INCONCLUSIVE; FPP < 0.5 (not a FAIL);
        # NFPP < 0.01. No FPP > 0.015 assertion, no
        # FPP-STP assertion. (PM-3: the pending test
        # converted into a real assertion test on the
        # measured panel run, row 27 retry5.)
        fx, res = self._assert_fixture("150428135")
        self.assertEqual(res.policy_version, "external_tools_v2")
        metrics = fx["tool_output"]["metrics"]
        self.assertLess(metrics["fpp"], 0.5)
        self.assertLess(metrics["nfpp"], 0.01)

    def test_toi700c_stp_dominates(self):
        # The STP split dominates the FPP (0.1826 of
        # 0.1910 = 96%) — the structural check that runs
        # now; the STP-split BAND waits for >= 5 seeds.
        fx = load_fixture("150428135")
        scenario = fx["scenario"]
        fpp = fx["tool_output"]["metrics"]["fpp"]
        share = scenario["stp"] / fpp
        self.assertGreater(
            share, fx["expected"]["stp_share_min"],
            f"STP share of FPP {share:.2f} below the "
            f"dominance bar")
        # The scenario probabilities sum to 1 (a fixture
        # integrity check, not a science assertion) — the
        # full split, all 18 scenarios (unlike WASP-29b,
        # whose four named scenarios already sum to 1).
        total = sum(v for v in scenario.values()
                    if isinstance(v, (int, float)))
        self.assertAlmostEqual(total, 1.0, places=3)


class TestSeedStabilityCheck(unittest.TestCase):
    """The stability check itself, on synthetic seed sets."""

    def _policy(self):
        return {"triceratops": {"fpp_validate_max": 0.015,
                                "nfpp_validate_max": 0.001,
                                "fpp_refute_min": 0.5}}

    def _seeds(self, fpps):
        return [{"seed": 1000 + i, "fpp": f, "nfpp": 0.0}
                for i, f in enumerate(fpps)]

    def test_stable_inconclusive_passes(self):
        ok, _ = check_seed_stability(
            self._seeds([0.16, 0.17, 0.169, 0.171, 0.168]),
            self._policy())
        self.assertTrue(ok)

    def test_boundary_crossing_fails(self):
        # The band [0.012, 0.020] straddles the 0.015
        # validate bar: the disposition flips across seeds
        # (pass vs inconclusive) — not stable.
        ok, reason = check_seed_stability(
            self._seeds([0.012, 0.014, 0.016, 0.018, 0.020]),
            self._policy())
        self.assertFalse(ok)
        self.assertIn("varies", reason)

    def test_band_touching_boundary_fails(self):
        # The subtle case: every seed reads inconclusive
        # (NFPP 0.005 blocks the pass), but the FPP band
        # [0.012, 0.020] straddles the 0.015 validate bar —
        # the disposition agrees only because NFPP blocks it,
        # so the separation is inadequate.
        seeds = [{"seed": 1000 + i, "fpp": f, "nfpp": 0.005}
                 for i, f in enumerate(
                     [0.012, 0.014, 0.016, 0.018, 0.020])]
        ok, reason = check_seed_stability(seeds, self._policy())
        self.assertFalse(ok)
        self.assertIn("touches", reason)
        # The same NFPP with a clear band passes.
        seeds = [{"seed": 1000 + i, "fpp": f, "nfpp": 0.005}
                 for i, f in enumerate(
                     [0.02, 0.021, 0.022, 0.023, 0.024])]
        ok, _ = check_seed_stability(seeds, self._policy())
        self.assertTrue(ok)

    def test_too_few_seeds_raises(self):
        with self.assertRaises(ValueError):
            check_seed_stability(self._seeds([0.16, 0.17]),
                                 self._policy())


if __name__ == "__main__":
    unittest.main()
