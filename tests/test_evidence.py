"""Evidence package tests (Phase 2, 2D).

The builder takes a real build_verdict record + the desk
extra dict + a workdir, and returns the single reviewable
record: verdict, waiver-stamped stages, external-tool
evidence, scores, provenance, input hashes, completeness.

Verdict records here are built with the real build_verdict
(never hand-assembled), so the package is tested against
the records the driver actually produces.
"""
import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gauntlet.evidence import build_evidence_package  # noqa: E402
from gauntlet.stage_result import (  # noqa: E402
    REQUIRED_STAGES, StageResult, latte_result,
    triceratops_result)
from gauntlet.verdict import build_verdict  # noqa: E402
from validation import (  # noqa: E402
    RecordValidationError, validate_evidence_package,
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


def _verdict(results, waivers=None):
    return build_verdict(
        "999999999", FILED, results, imaging=IMAGING_ON,
        ephemeris_used={"period_d": 3.9227, "t0": 1500.5,
                        "duration_d": 0.105, "source": "refined"},
        run_id="test-run-1", waivers=waivers)


def _write_sources(workdir, verdict):
    (Path(workdir) / "verdict_record.json").write_text(
        json.dumps(verdict))
    (Path(workdir) / "desk_natives.json").write_text(
        json.dumps({"natives": {}, "extra_evidence": {}}))


class TestEvidencePackage(unittest.TestCase):

    def test_candidate_package_complete(self):
        with tempfile.TemporaryDirectory() as tmp:
            verdict = _verdict(_pass_results())
            _write_sources(tmp, verdict)
            pkg = build_evidence_package(
                "999999999", verdict, {}, tmp)
            self.assertEqual(pkg["record_type"],
                             "evidence_package")
            self.assertEqual(pkg["schema_version"], "1.0")
            self.assertEqual(pkg["tic"], "999999999")
            self.assertEqual(pkg["run_id"], "test-run-1")
            self.assertEqual(pkg["verdict"]["final_verdict"],
                             "CANDIDATE")
            self.assertEqual(pkg["verdict"]["filed"], FILED)
            self.assertEqual(pkg["verdict"]["imaging"],
                             IMAGING_ON)
            self.assertEqual(pkg["verdict"]["waivers"], [])
            self.assertIsNone(pkg["verdict"]["waivers_hash"])
            self.assertEqual(set(pkg["stages"]),
                             set(REQUIRED_STAGES))
            self.assertEqual(pkg["external_tools"], {})
            self.assertEqual(pkg["scores"],
                             {"triceratops": None, "latte": None})
            # Provenance is copied from the verdict record.
            self.assertEqual(pkg["provenance"]["schema_version"],
                             "1.2")
            self.assertEqual(
                pkg["provenance"]["calibration_version"],
                {"gauntlet": "v2"})
            self.assertIsInstance(
                pkg["provenance"]["calibration_sha256"], str)
            self.assertIsInstance(
                pkg["provenance"]["pipeline_git_sha"], str)
            self.assertIsInstance(
                pkg["provenance"]["working_tree_clean"], bool)
            self.assertIsInstance(
                pkg["provenance"]["code_fingerprint"], str)
            self.assertTrue(
                pkg["provenance"]["code_fingerprint"])
            # The input hashes match the files on disk.
            vr = hashlib.sha256(
                open(os.path.join(tmp, "verdict_record.json"),
                     "rb").read()).hexdigest()
            dn = hashlib.sha256(
                open(os.path.join(tmp, "desk_natives.json"),
                     "rb").read()).hexdigest()
            self.assertEqual(
                pkg["inputs"]["verdict_record"]["sha256"], vr)
            self.assertEqual(
                pkg["inputs"]["desk_natives"]["sha256"], dn)
            comp = pkg["completeness"]
            self.assertEqual(comp["n_stages"], 12)
            self.assertEqual(comp["n_pass"], 12)
            self.assertEqual(comp["n_fail"], 0)
            self.assertEqual(comp["missing_required"], [])
            self.assertTrue(comp["report_ready"])

    def test_package_with_tools(self):
        with tempfile.TemporaryDirectory() as tmp:
            verdict = _verdict(_pass_results())
            _write_sources(tmp, verdict)
            latte = latte_result({
                "tool": "latte", "tool_version": "1.0.21",
                "seed": 20261114, "config_hash": "c" * 64,
                "status": "completed", "value": None,
                "metrics": {
                    "report_pdf": "/tmp/work/DV_report.pdf",
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
                "metrics": {
                    "fpp": 0.0032, "nfpp": 0.0008,
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
            extra = {"external_tools": {"latte": latte,
                                        "triceratops": tri}}
            pkg = build_evidence_package(
                "999999999", verdict, extra, tmp)
            self.assertEqual(set(pkg["external_tools"]),
                             {"latte", "triceratops"})
            tri_score = pkg["scores"]["triceratops"]
            self.assertEqual(tri_score["fpp"], 0.0032)
            self.assertEqual(tri_score["nfpp"], 0.0008)
            self.assertEqual(tri_score["prob_planet"], 0.9968)
            self.assertEqual(
                tri_score["most_likely_false_positive"],
                "EB on TIC 999999999")
            self.assertEqual(tri_score["status"], "pass")
            lat_score = pkg["scores"]["latte"]
            self.assertEqual(lat_score["report_pdf"],
                             "/tmp/work/DV_report.pdf")
            self.assertEqual(lat_score["status"], "inconclusive")

    def test_missing_source_files_hash_null(self):
        with tempfile.TemporaryDirectory() as tmp:
            verdict = _verdict(_pass_results())
            # Neither source file is written.
            pkg = build_evidence_package(
                "999999999", verdict, {}, tmp)
            self.assertIsNone(
                pkg["inputs"]["verdict_record"]["sha256"])
            self.assertIsNone(
                pkg["inputs"]["desk_natives"]["sha256"])

    def test_missing_required_stage(self):
        with tempfile.TemporaryDirectory() as tmp:
            verdict = _verdict(
                _pass_results(exclude=("diffimg",)))
            _write_sources(tmp, verdict)
            pkg = build_evidence_package(
                "999999999", verdict, {}, tmp)
            comp = pkg["completeness"]
            self.assertEqual(comp["missing_required"],
                             ["diffimg"])
            self.assertFalse(comp["report_ready"])
            self.assertIn("diffimg",
                          comp["report_ready_reason"])
            self.assertEqual(pkg["verdict"]["final_verdict"],
                             "INCONCLUSIVE")

    def test_waived_candidate_not_report_ready(self):
        # A waived CANDIDATE still needs a second-eyes review
        # before filing (F-5) — the package says so.
        with tempfile.TemporaryDirectory() as tmp:
            holdout = StageResult(
                "holdout", "inconclusive",
                "one sector only", PROV,
                waiver_code="single_sector")
            verdict = _verdict(
                _pass_results(
                    overrides={"holdout": holdout}),
                waivers={"holdout": "single sector"})
            _write_sources(tmp, verdict)
            pkg = build_evidence_package(
                "999999999", verdict, {}, tmp)
            self.assertEqual(pkg["verdict"]["final_verdict"],
                             "CANDIDATE")
            self.assertEqual(len(pkg["verdict"]["waivers"]), 1)
            self.assertEqual(
                pkg["verdict"]["waivers"][0]["code"],
                "single_sector")
            comp = pkg["completeness"]
            self.assertFalse(comp["report_ready"])
            self.assertIn("second-eyes",
                          comp["report_ready_reason"])

    def test_failed_stage_counted(self):
        with tempfile.TemporaryDirectory() as tmp:
            shape = StageResult(
                "shape", "fail", "V-shaped: T23/T14 0.08", PROV)
            verdict = _verdict(
                _pass_results(overrides={"shape": shape}))
            _write_sources(tmp, verdict)
            pkg = build_evidence_package(
                "999999999", verdict, {}, tmp)
            self.assertEqual(pkg["verdict"]["final_verdict"],
                             "EB")
            comp = pkg["completeness"]
            self.assertEqual(comp["n_fail"], 1)
            self.assertEqual(comp["n_pass"], 11)
            # report_ready is the NARROW filing-gate data
            # precondition (persistence + diffimg + blend
            # pass) — it holds here even though the verdict is
            # EB. The 2E review gate refuses non-CANDIDATE
            # verdicts on its own check; report_ready alone
            # never files anything.
            self.assertTrue(comp["report_ready"])

    def test_schema_validation_direct(self):
        with tempfile.TemporaryDirectory() as tmp:
            verdict = _verdict(_pass_results())
            _write_sources(tmp, verdict)
            pkg = build_evidence_package(
                "999999999", verdict, {}, tmp)
            validate_evidence_package(pkg)
            bad = dict(pkg)
            del bad["scores"]
            with self.assertRaises(RecordValidationError):
                validate_evidence_package(bad)


if __name__ == "__main__":
    unittest.main()
