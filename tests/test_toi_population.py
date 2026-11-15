"""Labelled-population TOI run test (Phase 1.2 follow-up F-8).

Runs the offline population (the three golden fixtures) through
scripts/toi_population.py and diffs the confusion counts + the
per-star stage statuses against the committed baseline
(tests/fixtures/toi_population/baseline.json). A change fails
the test and forces a deliberate baseline update — the counts
are the gauntlet's measured discrimination on known planets vs
a known EB, so a silent change is a regression until proven
otherwise.

Slow (~2.5 min: three pipeline runs). Excluded from the smoke
tier (F-10); runs in the full suite.
"""
import json
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.toi_population import run_population  # noqa: E402

BASELINE = (Path(__file__).resolve().parent / "fixtures"
            / "toi_population" / "baseline.json")

_ARTIFACT = None


def setUpModule():
    # One population run (~2.5 min) shared by both tests.
    global _ARTIFACT
    _ARTIFACT = run_population(live=False)


class TestToiPopulation(unittest.TestCase):
    def test_confusion_counts_match_baseline(self):
        if not BASELINE.exists():
            raise RuntimeError(
                "TOI population baseline missing: "
                f"{BASELINE} — regenerate with: "
                ".venv/bin/python scripts/toi_population.py "
                "--out /tmp/toi_population_artifact.json, inspect "
                "it, then copy its counts + per-star stages into "
                "the baseline")
        baseline = json.loads(BASELINE.read_text())
        self.assertEqual(_ARTIFACT["counts"], baseline["counts"],
                         msg="confusion counts changed — if the "
                             "change is deliberate, update the "
                             "baseline and say why in the commit")
        got_stages = {s["tic"]: s["stages"]
                      for s in _ARTIFACT["stars"]}
        self.assertEqual(got_stages, baseline["stages"],
                         msg="per-star stage statuses changed — "
                             "if deliberate, update the baseline "
                             "and say why in the commit")

    def test_planets_pass_measured_stages(self):
        # The baseline diff above pins the exact counts; this
        # test pins the MEANING: WASP-126 b passes every
        # measured stage; TOI-700 c fails NO stage — its
        # shape reads INCONCLUSIVE under the P-8
        # uncertainty-aware gate (a V-shaped point estimate,
        # T23/T14 0.2925, whose 1-sigma upper bound is above
        # the 0.30 bar on a shallow 0.32% transit — the
        # marginal false-kill the vote fixed, with the bar
        # itself unchanged at 0.30); the EB is killed by
        # catalogue + shape.
        counts = _ARTIFACT["counts"]
        self.assertEqual(counts["planets"]["all_measured_pass"], 1)
        self.assertEqual(counts["planets"]["any_fail"], 0)
        self.assertEqual(counts["fps"]["killed"],
                         counts["fps"]["n"])
        self.assertEqual(counts["fps"]["kill_stages"],
                         {"catalogue": 1, "shape": 1})
        by_tic = {s["tic"]: s for s in _ARTIFACT["stars"]}
        self.assertEqual(by_tic["150428135"]["kill_stages"], [])
        self.assertEqual(by_tic["25155310"]["kill_stages"], [])


if __name__ == "__main__":
    unittest.main()
