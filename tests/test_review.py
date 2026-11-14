"""Filing review gate tests (Phase 2, 2E).

The gate prepares a review record from a 2D evidence
package and lets a human approve/reject it. The gate is
enforced at DECISION time: an ineligible record can be
prepared (its blockers are visible) and rejected, but never
approved. An approved review IS the F-5 second-eyes marker
— its reviewer satisfies check_report_ready's review_2e
requirement for a waived candidate.

Packages here are built with the real build_verdict +
build_evidence_package (the same helpers as
test_evidence.py, replicated — test files stand alone).
"""
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import provenance as _prov  # noqa: E402
from gauntlet.evidence import build_evidence_package  # noqa: E402
from gauntlet.review import (  # noqa: E402
    prepare_filing_review, record_review_decision,
    review_2e_marker)
from gauntlet.runner import check_report_ready  # noqa: E402
from gauntlet.stage_result import (  # noqa: E402
    REQUIRED_STAGES, StageResult, latte_result,
    triceratops_result)
from gauntlet.verdict import build_verdict  # noqa: E402
from validation import (  # noqa: E402
    RecordValidationError, validate_filing_review,
)

PROV = {"calibration_version": "gauntlet_v2",
        "tool": "test", "tool_version": "0"}
IMAGING_ON = {"on_target": True, "offset_px": 0.3,
              "offset_arcsec": 6.0, "blend_host_tic": None}
FILED = {"period_days": 3.9227, "depth_pct": 1.0, "sde": 29.2}


def _pass_results(exclude=(), overrides=None):
    results = []
    for stage in REQUIRED_STAGES:
        if stage in exclude:
            continue
        over = (overrides or {}).get(stage)
        if over is not None:
            results.append(over)
        else:
            results.append(StageResult(stage, "pass", "ok", PROV))
    return results


def _package(results, waivers=None, extra=None):
    verdict = build_verdict(
        "999999999", FILED, results, imaging=IMAGING_ON,
        ephemeris_used={"period_d": 3.9227, "t0": 1500.5,
                        "duration_d": 0.105, "source": "refined"},
        run_id="test-run-1", waivers=waivers)
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "verdict_record.json").write_text(
            json.dumps(verdict))
        (Path(tmp) / "desk_natives.json").write_text(
            json.dumps({"natives": {}, "extra_evidence": {}}))
        return build_evidence_package(
            "999999999", verdict, extra or {}, tmp)


def _tool_extra():
    latte = latte_result({
        "tool": "latte", "tool_version": "1.0.21",
        "seed": 20261114, "config_hash": "c" * 64,
        "status": "completed", "value": None,
        "metrics": {"report_pdf": "/tmp/work/DV_report.pdf",
                    "output_dir": "/tmp/work",
                    "latte_indir": "/tmp/latte-out",
                    "n_artifacts": 3},
        "input_hashes": {"lightcurve": "a" * 64,
                         "neighbours": "b" * 64},
        "artifacts": ["/tmp/work/DV_report.pdf"],
        "warnings": [], "wall_time_s": 123.0,
        "n_transits": 7}).to_dict()
    tri = triceratops_result({
        "tool": "triceratops", "tool_version": "1.1.0",
        "seed": 20261114, "config_hash": "c" * 64,
        "status": "completed", "value": 0.0032,
        "metrics": {"fpp": 0.0032, "nfpp": 0.0008,
                    "prob_planet": 0.9968,
                    "prob_eb_target": 0.0021,
                    "prob_eb_neighbour": 0.0009,
                    "prob_hierarchical_eb": 0.0002,
                    "n_samples": 1000000,
                    "most_likely_false_positive":
                        "EB on TIC 999999999",
                    "fpp_degenerate": False,
                    "dilution_corrected": False,
                    "contrast_curve_used": False},
        "input_hashes": {"lightcurve": "a" * 64,
                         "neighbours": "b" * 64},
        "artifacts": ["/tmp/work/triceratops_probs.csv"],
        "warnings": [], "wall_time_s": 412.5,
        "n_transits": 7}).to_dict()
    return {"external_tools": {"latte": latte,
                               "triceratops": tri}}


class TestPrepareFilingReview(unittest.TestCase):

    def test_prepare_eligible_candidate(self):
        pkg = _package(_pass_results())
        review = prepare_filing_review(
            pkg, timestamp_utc="2026-11-15T00:00:00Z")
        self.assertEqual(review["record_type"], "filing_review")
        self.assertEqual(review["schema_version"], "1.0")
        self.assertEqual(review["tic"], "999999999")
        self.assertEqual(review["run_id"], "test-run-1")
        self.assertEqual(review["status"], "awaiting_review")
        self.assertTrue(review["eligible"])
        self.assertEqual(review["eligibility"]["blockers"], [])
        self.assertTrue(
            review["eligibility"]["verdict_is_candidate"])
        self.assertTrue(
            review["eligibility"]
            ["all_stages_pass_or_waived"])
        self.assertTrue(
            review["eligibility"]
            ["persistence_diffimg_blend_pass"])
        self.assertIsNone(review["decision"])
        # The review binds to the exact package bytes.
        expected = hashlib.sha256(
            _prov.canonical_json(pkg).encode("utf-8")
        ).hexdigest()
        self.assertEqual(review["evidence_package_hash"],
                         expected)
        by_item = {i["item"]: i
                   for i in review["checklist"]}
        self.assertEqual(
            by_item["read_latte_report"]["status"],
            "not_applicable")
        self.assertEqual(
            by_item["confirm_triceratops"]["status"],
            "not_applicable")
        self.assertEqual(by_item["review_waivers"]["status"],
                         "not_applicable")
        self.assertEqual(
            by_item["confirm_catalogue_current"]["status"],
            "pending")

    def test_prepare_with_tools_checklist(self):
        pkg = _package(_pass_results(), extra=_tool_extra())
        review = prepare_filing_review(pkg)
        by_item = {i["item"]: i
                   for i in review["checklist"]}
        latte = by_item["read_latte_report"]
        self.assertEqual(latte["status"], "pending")
        self.assertIn("DV_report.pdf", latte["detail"])
        tri = by_item["confirm_triceratops"]
        self.assertEqual(tri["status"], "pending")
        self.assertIn("0.0032", tri["detail"])
        self.assertIn("EB on TIC 999999999", tri["detail"])

    def test_prepare_ineligible_eb(self):
        shape = StageResult(
            "shape", "fail", "V-shaped: T23/T14 0.08", PROV)
        pkg = _package(
            _pass_results(overrides={"shape": shape}))
        review = prepare_filing_review(pkg)
        # The record exists (its blockers are visible); the
        # gate is enforced at decision time.
        self.assertEqual(review["status"], "awaiting_review")
        self.assertFalse(review["eligible"])
        blockers = review["eligibility"]["blockers"]
        self.assertTrue(any("not CANDIDATE" in b
                            for b in blockers))
        self.assertTrue(any("shape is fail" in b
                            for b in blockers))

    def test_prepare_missing_stage(self):
        pkg = _package(_pass_results(exclude=("diffimg",)))
        review = prepare_filing_review(pkg)
        self.assertFalse(review["eligible"])
        self.assertIn("diffimg never ran",
                      review["eligibility"]["blockers"])
        self.assertFalse(
            review["eligibility"]
            ["persistence_diffimg_blend_pass"])

    def test_prepare_unwaived_inconclusive(self):
        holdout = StageResult(
            "holdout", "inconclusive", "one sector only", PROV)
        pkg = _package(
            _pass_results(overrides={"holdout": holdout}))
        review = prepare_filing_review(pkg)
        self.assertFalse(review["eligible"])
        blockers = review["eligibility"]["blockers"]
        self.assertTrue(any(
            "holdout is inconclusive without a waiver" in b
            for b in blockers))

    def test_prepare_waived_candidate_eligible(self):
        # A waived CANDIDATE IS eligible: this review is the
        # second-eyes marker the F-5 rule requires, so the
        # gate checks the data part (persistence/diffimg/
        # blend) and lets the review itself supply the
        # marker.
        holdout = StageResult(
            "holdout", "inconclusive",
            "one sector only", PROV,
            waiver_code="single_sector")
        pkg = _package(
            _pass_results(overrides={"holdout": holdout}),
            waivers={"holdout": "single sector"})
        review = prepare_filing_review(pkg)
        self.assertTrue(review["eligible"])
        self.assertEqual(review["eligibility"]["blockers"], [])
        by_item = {i["item"]: i
                   for i in review["checklist"]}
        waivers = by_item["review_waivers"]
        self.assertEqual(waivers["status"], "pending")
        self.assertIn("holdout", waivers["detail"])

    def test_prepare_rejects_malformed_package(self):
        with self.assertRaises(RecordValidationError):
            prepare_filing_review({"tic": "999999999"})


class TestRecordReviewDecision(unittest.TestCase):

    def test_approve_eligible(self):
        pkg = _package(_pass_results())
        review = prepare_filing_review(pkg)
        decided = record_review_decision(
            review, "Dev", "approved",
            "All gates pass; LATTE read; FPP 0.0032.",
            timestamp_utc="2026-11-15T01:00:00Z")
        self.assertEqual(decided["status"], "approved")
        self.assertEqual(decided["decision"]["reviewer"], "Dev")
        self.assertEqual(decided["decision"]["decision"],
                         "approved")
        self.assertEqual(decided["decision"]["timestamp_utc"],
                         "2026-11-15T01:00:00Z")
        # The input record is not mutated.
        self.assertEqual(review["status"], "awaiting_review")
        self.assertIsNone(review["decision"])
        validate_filing_review(decided)

    def test_approve_ineligible_raises(self):
        shape = StageResult(
            "shape", "fail", "V-shaped: T23/T14 0.08", PROV)
        pkg = _package(
            _pass_results(overrides={"shape": shape}))
        review = prepare_filing_review(pkg)
        with self.assertRaises(ValueError) as ctx:
            record_review_decision(
                review, "Dev", "approved", "looks fine")
        self.assertIn("shape is fail", str(ctx.exception))

    def test_reject_ineligible_allowed(self):
        shape = StageResult(
            "shape", "fail", "V-shaped: T23/T14 0.08", PROV)
        pkg = _package(
            _pass_results(overrides={"shape": shape}))
        review = prepare_filing_review(pkg)
        decided = record_review_decision(
            review, "Dev", "rejected",
            "EB — not worth pursuing.")
        self.assertEqual(decided["status"], "rejected")

    def test_decision_validation(self):
        pkg = _package(_pass_results())
        review = prepare_filing_review(pkg)
        with self.assertRaises(ValueError):
            record_review_decision(
                review, "  ", "approved", "ok")
        with self.assertRaises(ValueError):
            record_review_decision(
                review, "Dev", "approved", "  ")
        with self.assertRaises(ValueError):
            record_review_decision(
                review, "Dev", "maybe", "unsure")

    def test_double_decision_raises(self):
        pkg = _package(_pass_results())
        review = prepare_filing_review(pkg)
        decided = record_review_decision(
            review, "Dev", "approved", "all gates pass")
        with self.assertRaises(ValueError):
            record_review_decision(
                decided, "Dev", "rejected", "changed my mind")

    def test_approved_review_is_2e_marker(self):
        # The integration proof: a waived CANDIDATE reads
        # report_ready False without a review marker, and
        # True with the approved review's reviewer.
        holdout = StageResult(
            "holdout", "inconclusive",
            "one sector only", PROV,
            waiver_code="single_sector")
        pkg = _package(
            _pass_results(overrides={"holdout": holdout}),
            waivers={"holdout": "single sector"})
        results = [StageResult.from_dict(d)
                   for d in pkg["stages"].values()]
        ready, _reason = check_report_ready(results)
        self.assertFalse(ready)
        review = prepare_filing_review(pkg)
        self.assertIsNone(review_2e_marker(review))
        decided = record_review_decision(
            review, "Dev", "approved",
            "Single sector is all that exists; holdout "
            "waiver accepted.")
        marker = review_2e_marker(decided)
        self.assertEqual(marker, {"reviewer": "Dev"})
        ready, _reason = check_report_ready(
            results, review_2e=marker)
        self.assertTrue(ready)

    def test_schema_validation_direct(self):
        pkg = _package(_pass_results())
        review = prepare_filing_review(pkg)
        validate_filing_review(review)
        bad = dict(review)
        del bad["eligibility"]
        with self.assertRaises(RecordValidationError):
            validate_filing_review(bad)


if __name__ == "__main__":
    unittest.main()
