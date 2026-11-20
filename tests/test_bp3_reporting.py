"""BP-3 template + 5-seed reporting tests (PIPE50-2, bulk_v6
step 6).

The FPP template gains fpp_median, fpp_band, per_seed,
n_seeds; the headline is the MAX seed; single-seed runs are
tagged n_seeds 1 (PROVISIONAL_TRIAGE); the PASS rule is
unchanged (every seed <= 0.015). Covered here:

  * summarize_seed_band on the measured Zorro 5-seed record
    (fixture 183537452's `zorro` block): median 0.003446,
    band [0.000115, 0.016801], headline = max 0.016801 —
    does NOT validate (4/5 pass), matching the 4.1-6 FAIL
    verdict. The median reads PASS; the max is the honest
    headline.
  * aggregate_triceratops_results: value = max FPP, status
    from the existing disposition on (max FPP, max NFPP),
    the headline seed's per-scenario breakdown, and
    UNMEASURED when any seed is unmeasured.
  * The Zorro record re-rendered through the new template
    (scores + filing-review checklist, the real
    build_evidence_package + prepare_filing_review path):
    the confirm_triceratops item carries headline =
    0.016801, median, band, per_seed, n_seeds 5.
  * A single-seed run through the same path: n_seeds 1 +
    PROVISIONAL_TRIAGE in the scores and the review detail.

The desk caller's 5-seed default is tested in
test_desk_external_tools.py (it owns the fake wrappers);
the nightly receipt tag in test_triceratops_nightly.py.
test_seed_band_pending is NOT touched — its failure is the
TB-4 finding, not a regression.
"""
import copy
import json
import math
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from calibration import load_profile  # noqa: E402
from gauntlet.evidence import build_evidence_package  # noqa: E402
from gauntlet.review import prepare_filing_review  # noqa: E402
from gauntlet.stage_result import (  # noqa: E402
    REQUIRED_STAGES, StageResult, aggregate_triceratops_results,
    triceratops_result)
from gauntlet.triceratops_golden import (  # noqa: E402
    BP3_SEEDS, load_fixture, summarize_seed_band)
from gauntlet.verdict import build_verdict  # noqa: E402

PROV = {"calibration_version": "gauntlet_v2",
        "tool": "test", "tool_version": "0"}
IMAGING_ON = {"on_target": True, "offset_px": 0.3,
              "offset_arcsec": 6.0, "blend_host_tic": None}
FILED = {"period_days": 3.9227, "depth_pct": 1.0, "sde": 29.2}

# The measured Zorro 5-seed record (4.1-6, fixture
# 183537452's `zorro` block): median 0.003446, band
# [0.000115, 0.016801], FAIL under the strict CC-4 bar
# (seed 20261115 FPP 0.0168 > 0.015; 4/5 pass).
ZORRO_MEDIAN = 0.003446366334737605
ZORRO_BAND = [0.0001151992967932669, 0.016800747229404722]

# P-7: the tool-artifact files the fixtures cite must really
# exist — the evidence package hashes them, and the review
# gate blocks on a null hash. One module-lived temp dir
# holds one probs CSV per BP-3 seed.
_ARTIFACT_DIR = None


def setUpModule():
    global _ARTIFACT_DIR
    _ARTIFACT_DIR = tempfile.mkdtemp(prefix="bp3-artifacts-")
    for seed in BP3_SEEDS:
        Path(_ARTIFACT_DIR,
             f"triceratops_probs_{seed}.csv").write_text(
                 "scenario,prob\nplanet,0.9968\n")


def tearDownModule():
    import shutil
    shutil.rmtree(_ARTIFACT_DIR, ignore_errors=True)


def _zorro_seeds():
    return load_fixture("183537452")["zorro"]["seeds"]


def _policy():
    return load_profile("external_tools_v3")


def _output(seed, fpp, nfpp, degenerate=False):
    """A schema-valid tool output for one seed, from the
    WASP-29b fixture's tool output with the seed numbers
    overridden."""
    out = copy.deepcopy(load_fixture("183537452")["tool_output"])
    out["seed"] = seed
    out["value"] = fpp
    out["metrics"]["fpp"] = fpp
    out["metrics"]["nfpp"] = nfpp
    out["metrics"]["fpp_degenerate"] = degenerate
    out["artifacts"] = [os.path.join(
        _ARTIFACT_DIR, f"triceratops_probs_{seed}.csv")]
    return out


def _results(entries, policy=None):
    """Single-seed StageResults for [(seed, fpp, nfpp)]."""
    policy = policy if policy is not None else _policy()
    return [triceratops_result(_output(seed, fpp, nfpp),
                               policy=policy)
            for seed, fpp, nfpp in entries]


def _package(tri_result):
    """A full evidence package carrying one triceratops
    StageResult (the test_review scaffolding, replicated —
    test files stand alone)."""
    verdict = build_verdict(
        "999999999", FILED,
        [StageResult(stage, "pass", "ok", PROV)
         for stage in REQUIRED_STAGES],
        imaging=IMAGING_ON,
        ephemeris_used={"period_d": 3.9227, "t0": 1500.5,
                        "duration_d": 0.105, "source": "refined"},
        run_id="test-run-bp3")
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "verdict_record.json").write_text(
            json.dumps(verdict))
        (Path(tmp) / "desk_natives.json").write_text(
            json.dumps({"natives": {}, "extra_evidence": {}}))
        return build_evidence_package(
            "999999999", verdict,
            {"external_tools": {"triceratops":
                                tri_result.to_dict()}},
            tmp)


class TestSummarizeSeedBand(unittest.TestCase):

    def test_zorro_summary(self):
        summary = summarize_seed_band(_zorro_seeds(), _policy())
        self.assertEqual(summary["n_seeds"], 5)
        self.assertEqual(summary["fpp_median"], ZORRO_MEDIAN)
        self.assertEqual(summary["fpp_band"], ZORRO_BAND)
        self.assertEqual(summary["headline_fpp"], ZORRO_BAND[1])
        self.assertEqual(summary["headline_nfpp"], 0.0)
        # The median reads PASS; the max is the honest
        # headline — and it does NOT validate (4.1-6 FAIL).
        self.assertLessEqual(summary["fpp_median"], 0.015)
        self.assertGreater(summary["headline_fpp"], 0.015)
        self.assertFalse(summary["validates"])
        self.assertIsNone(summary["seed_status"])
        self.assertEqual(
            [e["seed"] for e in summary["per_seed"]],
            list(BP3_SEEDS))
        self.assertEqual(summary["per_seed"][1]["fpp"],
                         ZORRO_BAND[1])

    def test_all_pass_validates(self):
        seeds = [{"seed": 20261114 + i, "fpp": 0.001 * (i + 1),
                  "nfpp": 0.0005}
                 for i in range(5)]
        summary = summarize_seed_band(seeds, _policy())
        self.assertTrue(summary["validates"])
        self.assertEqual(summary["headline_fpp"], 0.005)
        self.assertIsNone(summary["seed_status"])

    def test_single_seed_provisional(self):
        summary = summarize_seed_band(
            [{"seed": 20261114, "fpp": 0.0032, "nfpp": 0.0008}],
            _policy())
        self.assertEqual(summary["n_seeds"], 1)
        self.assertEqual(summary["seed_status"],
                         "PROVISIONAL_TRIAGE")
        self.assertEqual(summary["fpp_median"], 0.0032)
        self.assertEqual(summary["fpp_band"], [0.0032, 0.0032])
        self.assertEqual(summary["headline_fpp"], 0.0032)
        self.assertTrue(summary["validates"])

    def test_empty_raises(self):
        with self.assertRaises(ValueError):
            summarize_seed_band([], _policy())

    def test_nan_seed_does_not_validate(self):
        seeds = [{"seed": 20261114 + i, "fpp": 0.0032,
                  "nfpp": 0.0008} for i in range(4)]
        seeds.append({"seed": 20261118, "fpp": float("nan"),
                      "nfpp": 0.0008})
        summary = summarize_seed_band(seeds, _policy())
        self.assertFalse(summary["validates"])
        # The band is computed over the measured seeds; the
        # NaN seed is still visible in per_seed.
        self.assertEqual(summary["headline_fpp"], 0.0032)
        self.assertEqual(len(summary["per_seed"]), 5)
        self.assertTrue(math.isnan(summary["per_seed"][4]["fpp"]))

    def test_null_fpp_does_not_validate(self):
        seeds = [{"seed": 20261114 + i, "fpp": 0.0032,
                  "nfpp": 0.0008} for i in range(4)]
        seeds.append({"seed": 20261118, "fpp": None,
                      "nfpp": None})
        summary = summarize_seed_band(seeds, _policy())
        self.assertFalse(summary["validates"])
        self.assertEqual(summary["headline_fpp"], 0.0032)


class TestAggregateTriceratops(unittest.TestCase):

    def test_zorro_aggregate(self):
        entries = [(s["seed"], s["fpp"], s["nfpp"])
                   for s in _zorro_seeds()]
        agg = aggregate_triceratops_results(
            _results(entries), policy=_policy())
        self.assertEqual(agg.value, ZORRO_BAND[1])
        # Max 0.0168 sits in the grey zone under
        # disposition (A) — inconclusive, not a pass.
        self.assertEqual(agg.status, "inconclusive")
        self.assertEqual(agg.threshold, 0.015)
        metrics = agg.metrics
        self.assertEqual(metrics["n_seeds"], 5)
        self.assertEqual(metrics["fpp_median"], ZORRO_MEDIAN)
        self.assertEqual(metrics["fpp_band"], ZORRO_BAND)
        self.assertEqual(len(metrics["per_seed"]), 5)
        self.assertIsNone(metrics["seed_status"])
        # The headline seed (max FPP) supplies the
        # per-scenario breakdown.
        self.assertEqual(metrics["seed"], 20261115)
        self.assertEqual(metrics["fpp"], ZORRO_BAND[1])
        self.assertEqual(metrics["nfpp"], 0.0)
        self.assertEqual(len(agg.artifacts), 5)
        self.assertIn("headline FPP", agg.reason)
        self.assertIn("20261115", agg.reason)

    def test_all_pass_aggregate(self):
        entries = [(20261114 + i, 0.001 * (i + 1), 0.0005)
                   for i in range(5)]
        agg = aggregate_triceratops_results(
            _results(entries), policy=_policy())
        self.assertEqual(agg.status, "pass")
        self.assertEqual(agg.value, 0.005)

    def test_one_seed_refutes(self):
        # FAIL-on-max: the aggregate disposition runs the
        # existing function on the headline, so one seed
        # >= 0.5 reads FAIL. A direct consequence of
        # headline = MAX (flagged in the build record —
        # the vote did not discuss it).
        entries = [(20261114 + i, 0.001, 0.0005)
                   for i in range(4)]
        entries.append((20261118, 0.6, 0.0005))
        agg = aggregate_triceratops_results(
            _results(entries), policy=_policy())
        self.assertEqual(agg.status, "fail")
        self.assertEqual(agg.value, 0.6)

    def test_degenerate_seed_unmeasured(self):
        results = _results([(20261114 + i, 0.0032, 0.0008)
                            for i in range(4)])
        deg = triceratops_result(
            _output(20261118, 1.0, 0.999, degenerate=True),
            policy=_policy())
        self.assertEqual(deg.status, "unmeasured")
        agg = aggregate_triceratops_results(
            results + [deg], policy=_policy())
        self.assertEqual(agg.status, "unmeasured")
        self.assertEqual(agg.execution_status, "error")
        self.assertIn("unmeasured", agg.reason)

    def test_empty_raises(self):
        with self.assertRaises(ValueError):
            aggregate_triceratops_results([], policy=_policy())


class TestZorroTemplateRerender(unittest.TestCase):
    """The design §7 validation: the Zorro 5-seed record
    re-rendered through the new template (headline = max
    0.016801 → does not validate, matching the 4.1-6 FAIL)."""

    def test_zorro_rerendered_through_template(self):
        entries = [(s["seed"], s["fpp"], s["nfpp"])
                   for s in _zorro_seeds()]
        agg = aggregate_triceratops_results(
            _results(entries), policy=_policy())
        pkg = _package(agg)
        score = pkg["scores"]["triceratops"]
        self.assertEqual(score["fpp"], ZORRO_BAND[1])
        self.assertEqual(score["fpp_median"], ZORRO_MEDIAN)
        self.assertEqual(score["fpp_band"], ZORRO_BAND)
        self.assertEqual(score["n_seeds"], 5)
        self.assertEqual(len(score["per_seed"]), 5)
        self.assertIsNone(score["seed_status"])
        review = prepare_filing_review(pkg, "pingu")
        self.assertTrue(review["eligible"])
        by_item = {i["item"]: i for i in review["checklist"]}
        tri = by_item["confirm_triceratops"]
        self.assertEqual(tri["status"], "pending")
        self.assertEqual(tri["headline"], ZORRO_BAND[1])
        self.assertEqual(tri["fpp_median"], ZORRO_MEDIAN)
        self.assertEqual(tri["fpp_band"], ZORRO_BAND)
        self.assertEqual(tri["n_seeds"], 5)
        self.assertEqual(len(tri["per_seed"]), 5)
        # The headline exceeds the 0.015 validation bar —
        # does not validate (the 4.1-6 FAIL); the median
        # alone would have read PASS.
        self.assertGreater(tri["headline"], 0.015)
        self.assertLessEqual(tri["fpp_median"], 0.015)
        self.assertIn("0.0168", tri["detail"])
        self.assertNotIn("PROVISIONAL_TRIAGE", tri["detail"])

    def test_single_seed_tagged_provisional(self):
        single = triceratops_result(
            _output(20261114, 0.0032, 0.0008), policy=_policy())
        pkg = _package(single)
        score = pkg["scores"]["triceratops"]
        self.assertEqual(score["fpp"], 0.0032)
        self.assertEqual(score["n_seeds"], 1)
        self.assertEqual(score["seed_status"],
                         "PROVISIONAL_TRIAGE")
        self.assertEqual(score["fpp_band"], [0.0032, 0.0032])
        review = prepare_filing_review(pkg, "pingu")
        by_item = {i["item"]: i for i in review["checklist"]}
        tri = by_item["confirm_triceratops"]
        self.assertEqual(tri["n_seeds"], 1)
        self.assertEqual(tri["headline"], 0.0032)
        self.assertIn("PROVISIONAL_TRIAGE", tri["detail"])


if __name__ == "__main__":
    unittest.main()
