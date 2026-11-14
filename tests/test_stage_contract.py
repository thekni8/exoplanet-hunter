"""Unmeasured-status contract tests (Phase 1.1, item 7).

No downloads, no pipeline runs: the contract is about TYPES and
RULES, so the tests drive the adapters and the aggregator with
synthetic stage outputs and check the verdicts + schema
enforcement directly.

The rule under test: "unmeasured" means NOT YET VETTED and is
never a pass. No CANDIDATE verdict may stand on an unmeasured
stage, a missing stage, or missing imaging — enforced twice:
in code (aggregate_verdict) and in the schema (the CANDIDATE
if/then rule in schema/verdict-schema.json).
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gauntlet.stage_result import (REQUIRED_STAGES, StageResult,  # noqa: E402
                                   aggregate_verdict,
                                   clean_gate_result,
                                   holdout_result, parity_result,
                                   persistence_result,
                                   raw_flux_result, shape_gate_result)
from gauntlet.verdict import build_verdict  # noqa: E402
from validation import RecordValidationError, validate_verdict  # noqa: E402

PROV = {"calibration_version": "gauntlet_v1",
        "pipeline_git_sha": "test",
        "run_id": "test-run-1",
        "timestamp_utc": "2026-11-14T00:00:00+00:00"}

FILED = {"period_days": 2.17, "depth_pct": 0.40, "sde": 31.0}
IMAGING_ON = {"on_target": True, "offset_px": 0.06,
              "offset_arcsec": 1.3}


def _pass(stage):
    return StageResult(stage, "pass", f"{stage} passed", PROV)


def _all_pass():
    return [_pass(s) for s in REQUIRED_STAGES]


def _base_verdict(final_verdict, **overrides):
    rec = {"calibration_version": "gauntlet_v1",
           "filed": dict(FILED),
           "final_verdict": final_verdict,
           "pipeline_git_sha": "test",
           "run_id": "test-run-1",
           "schema_version": "1.1",
           "tic": "238620464",
           "timestamp_utc": "2026-11-14T00:00:00+00:00"}
    rec.update(overrides)
    return rec


class TestStageResult(unittest.TestCase):
    def test_invalid_status_rejected(self):
        with self.assertRaises(ValueError):
            StageResult("shape_gate", "maybe", "nope", PROV)

    def test_only_pass_is_pass(self):
        for status, expected in (("pass", True), ("fail", False),
                                 ("unmeasured", False),
                                 ("inconclusive", False)):
            r = StageResult("shape_gate", status, "x", PROV)
            self.assertEqual(r.is_pass, expected, msg=status)

    def test_unmeasured_is_not_measured(self):
        r = StageResult("holdout", "unmeasured", "no data", PROV)
        self.assertFalse(r.is_measured)
        self.assertTrue(_pass("holdout").is_measured)

    def test_round_trip(self):
        r = StageResult("parity", "pass", "agree", PROV,
                        {"odd_depth_pct": 1.0})
        self.assertEqual(StageResult.from_dict(r.to_dict()), r)


class TestAdapters(unittest.TestCase):
    def test_shape_gate(self):
        v = shape_gate_result(
            {"shape_verdict": "V-shaped", "T23_T14": 0.25}, PROV)
        self.assertEqual(v.status, "fail")
        d = shape_gate_result(
            {"shape_verdict": "U-shaped", "T23_T14": 0.62,
             "density_flag": True,
             "density_reason": "rho_circ/rho_star < 0.80"}, PROV)
        self.assertEqual(d.status, "fail")  # density kills a U
        u = shape_gate_result(
            {"shape_verdict": "U-shaped", "T23_T14": 0.62,
             "density_flag": False}, PROV)
        self.assertEqual(u.status, "pass")
        a = shape_gate_result(
            {"shape_verdict": "ambiguous", "T23_T14": 0.47,
             "density_flag": False}, PROV)
        self.assertEqual(a.status, "inconclusive")
        self.assertFalse(a.is_pass)
        m = shape_gate_result(
            {"verdict": "unmeasured", "reason": "no core bins"},
            PROV)
        self.assertEqual(m.status, "unmeasured")
        self.assertFalse(m.is_pass)

    def test_clean_gate(self):
        fold = {"n_in": 42, "n_events": 13, "depth_percent": -0.03,
                "snr": -0.5}
        self.assertEqual(
            clean_gate_result(fold, "FAIL", PROV).status, "fail")
        self.assertEqual(
            clean_gate_result(
                {"n_in": 42, "n_events": 13, "depth_percent": 0.9,
                 "snr": 12.0}, "PASS", PROV).status, "pass")
        self.assertEqual(
            clean_gate_result(
                {"n_in": 3, "n_events": 1}, "INSUFFICIENT",
                PROV).status, "unmeasured")

    def test_raw_flux(self):
        strong = {"depth_pct": 0.9, "signif_white": 12.0,
                  "n_in": 42, "n_events": 13}
        self.assertEqual(
            raw_flux_result(strong, PROV).status, "pass")
        none = {"depth_pct": -0.02, "signif_white": -0.5,
                "n_in": 42, "n_events": 13}
        self.assertEqual(raw_flux_result(none, PROV).status, "fail")
        thin = {"depth_pct": 0.9, "signif_white": 12.0,
                "n_in": 3, "n_events": 1}
        self.assertEqual(
            raw_flux_result(thin, PROV).status, "unmeasured")

    def test_parity(self):
        odd = {"depth_pct": 2.0, "sig_white_pct": 0.14}
        even = {"depth_pct": 0.8, "sig_white_pct": 0.13}
        self.assertEqual(
            parity_result(odd, even, PROV).status, "fail")
        even2 = {"depth_pct": 1.9, "sig_white_pct": 0.13}
        self.assertEqual(
            parity_result(odd, even2, PROV).status, "pass")
        self.assertEqual(
            parity_result(None, even, PROV).status, "unmeasured")

    def test_persistence(self):
        self.assertEqual(
            persistence_result({"verdict": "CONSISTENT",
                                "n_usable": 6}, PROV).status,
            "pass")
        for bad in ("MIXED", "CONCENTRATED", "RAW-REFUTED"):
            self.assertEqual(
                persistence_result({"verdict": bad}, PROV).status,
                "fail", msg=bad)
        self.assertEqual(
            persistence_result({"n_usable": 0}, PROV).status,
            "unmeasured")

    def test_holdout(self):
        self.assertEqual(
            holdout_result("HOLDOUT-PASS", PROV).status, "pass")
        self.assertEqual(
            holdout_result("HOLDOUT-FAIL", PROV).status, "fail")
        self.assertEqual(
            holdout_result("HOLDOUT-INSUFFICIENT-DATA",
                           PROV).status, "unmeasured")
        self.assertEqual(
            holdout_result(None, PROV).status, "unmeasured")


class TestAggregate(unittest.TestCase):
    def test_all_pass_plus_imaging_is_candidate(self):
        verdict, _note = aggregate_verdict(_all_pass(), IMAGING_ON)
        self.assertEqual(verdict, "CANDIDATE")

    def test_fail_kills(self):
        results = _all_pass()
        results[2] = StageResult("shape_gate", "fail", "V-shaped",
                                 PROV)
        verdict, _note = aggregate_verdict(results, IMAGING_ON)
        self.assertEqual(verdict, "EB")
        results = _all_pass()
        results[0] = StageResult("clean_gate", "fail",
                                 "flagged only", PROV)
        verdict, _note = aggregate_verdict(results, IMAGING_ON)
        self.assertEqual(verdict, "REFUTED")

    def test_unmeasured_is_never_candidate(self):
        results = _all_pass()
        results[5] = StageResult("holdout", "unmeasured",
                                 "no data", PROV)
        verdict, _note = aggregate_verdict(results, IMAGING_ON)
        self.assertEqual(verdict, "INCONCLUSIVE")

    def test_missing_stage_is_never_candidate(self):
        results = _all_pass()[:-1]  # holdout never ran
        verdict, _note = aggregate_verdict(results, IMAGING_ON)
        self.assertEqual(verdict, "INCONCLUSIVE")

    def test_inconclusive_is_never_candidate(self):
        results = _all_pass()
        results[2] = StageResult("shape_gate", "inconclusive",
                                 "ambiguous", PROV)
        verdict, _note = aggregate_verdict(results, IMAGING_ON)
        self.assertEqual(verdict, "INCONCLUSIVE")

    def test_off_target_imaging_is_blend(self):
        verdict, _note = aggregate_verdict(
            _all_pass(),
            {"on_target": False, "blend_host_tic": 123})
        self.assertEqual(verdict, "BLEND")

    def test_all_pass_without_imaging_is_inconclusive(self):
        verdict, _note = aggregate_verdict(_all_pass(), None)
        self.assertEqual(verdict, "INCONCLUSIVE")
        verdict, _note = aggregate_verdict(
            _all_pass(), {"on_target": None})
        self.assertEqual(verdict, "INCONCLUSIVE")


class TestCandidateSchemaRule(unittest.TestCase):
    def test_candidate_without_imaging_rejected(self):
        with self.assertRaises(RecordValidationError):
            validate_verdict(_base_verdict("CANDIDATE"))

    def test_candidate_with_off_target_imaging_rejected(self):
        with self.assertRaises(RecordValidationError):
            validate_verdict(_base_verdict(
                "CANDIDATE",
                imaging={"on_target": False}))

    def test_candidate_with_unmeasured_stage_rejected(self):
        stages = {s: _pass(s).to_dict() for s in REQUIRED_STAGES}
        stages["holdout"] = StageResult(
            "holdout", "unmeasured", "no data", PROV).to_dict()
        with self.assertRaises(RecordValidationError):
            validate_verdict(_base_verdict(
                "CANDIDATE", imaging=dict(IMAGING_ON),
                stages=stages))

    def test_candidate_with_imaging_and_all_pass_accepted(self):
        stages = {s: _pass(s).to_dict() for s in REQUIRED_STAGES}
        rec = validate_verdict(_base_verdict(
            "CANDIDATE", imaging=dict(IMAGING_ON), stages=stages))
        self.assertEqual(rec["final_verdict"], "CANDIDATE")

    def test_kill_verdict_needs_no_imaging(self):
        rec = validate_verdict(_base_verdict("EB"))
        self.assertEqual(rec["final_verdict"], "EB")


class TestBuildVerdict(unittest.TestCase):
    def test_candidate_end_to_end(self):
        rec = build_verdict("238620464", FILED, _all_pass(),
                            imaging=dict(IMAGING_ON),
                            run_id="test-run-1")
        self.assertEqual(rec["final_verdict"], "CANDIDATE")
        self.assertEqual(rec["calibration_version"], "gauntlet_v1")
        self.assertEqual(rec["run_id"], "test-run-1")
        self.assertEqual(set(rec["stages"]), set(REQUIRED_STAGES))

    def test_build_verdict_derives_kill(self):
        results = _all_pass()
        results[2] = StageResult("shape_gate", "fail", "V-shaped",
                                 PROV)
        rec = build_verdict("238620464", FILED, results,
                            imaging=dict(IMAGING_ON),
                            run_id="test-run-1")
        self.assertEqual(rec["final_verdict"], "EB")

    def test_build_verdict_never_forges_candidate(self):
        # Even with imaging on-target, an unmeasured stage means
        # INCONCLUSIVE — build_verdict cannot be talked into a
        # CANDIDATE by its caller.
        results = _all_pass()
        results[5] = StageResult("holdout", "unmeasured",
                                 "no data", PROV)
        rec = build_verdict("238620464", FILED, results,
                            imaging=dict(IMAGING_ON),
                            run_id="test-run-1")
        self.assertEqual(rec["final_verdict"], "INCONCLUSIVE")


if __name__ == "__main__":
    unittest.main()
