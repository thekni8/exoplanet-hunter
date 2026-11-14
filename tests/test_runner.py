"""Stage-runner tests (Phase 1.2, item P0-1).

No downloads: the runner is about ORDER and GATING, so the
tests drive it with synthetic contexts and stub stages.

The rules under test (the Phase 1.1 vote's weakest closure):
a fold stage cannot consume a bulk ephemeris; a stage cannot
run on a missing or unmeasured prerequisite; a FAIL
short-circuits the run; a skipped mandatory stage can never
produce a candidate; a stage that raises becomes unmeasured
with an error execution status, never a pass and never a
run-killing crash.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gauntlet.runner import (Ephemeris, StageSpec, TargetContext,  # noqa: E402
                             check_report_ready, get_stage,
                             register_stage, run_gauntlet,
                             validate_plan)
from gauntlet.stage_result import REQUIRED_STAGES, StageResult  # noqa: E402

PROV = {"calibration_version": "gauntlet_v1",
        "pipeline_git_sha": "test",
        "run_id": "test-run-1",
        "timestamp_utc": "2026-11-14T00:00:00+00:00"}

IMAGING_ON = {"on_target": True, "offset_px": 0.06,
              "offset_arcsec": 1.3}

# Native outputs that make every built-in adapter pass.
PASSING_NATIVES = {
    "clean_gate.native": (
        {"n_in": 42, "n_events": 13, "depth_percent": 0.9,
         "snr": 12.0}, "PASS"),
    "raw_flux.native": {"depth_pct": 0.9, "signif_white": 12.0,
                        "n_in": 42, "n_events": 13},
    "shape_gate.native": {"shape_verdict": "U-shaped",
                          "T23_T14": 0.62, "density_flag": False},
    "parity.native": (
        {"depth_pct": 2.0, "sig_white_pct": 0.14},
        {"depth_pct": 1.9, "sig_white_pct": 0.13}),
    "persistence.native": {"verdict": "CONSISTENT", "n_usable": 6},
    "holdout.native": "HOLDOUT-PASS",
}


def _ctx(natives=None, kind="refined", imaging=None):
    eph = Ephemeris(kind, 2.17, 1500.0, 0.1,
                    source="phase-scan refinement"
                    if kind == "refined" else "filed")
    return TargetContext(
        tic="238620464", ephemeris=eph,
        artifacts=dict(natives if natives is not None
                       else PASSING_NATIVES),
        provenance=dict(PROV),
        imaging=dict(imaging) if imaging is not None else None)


class TestEphemerisKind(unittest.TestCase):
    def test_bulk_and_refined_are_distinct_artifacts(self):
        b = Ephemeris("bulk", 2.17, 1500.0, 0.1)
        r = Ephemeris("refined", 2.17, 1500.0, 0.1)
        self.assertNotEqual(b.artifact_key, r.artifact_key)
        self.assertEqual(b.artifact_key, "ephemeris.bulk")
        self.assertEqual(r.artifact_key, "ephemeris.refined")

    def test_bad_kind_rejected(self):
        with self.assertRaises(ValueError):
            Ephemeris("maybe", 2.17, 1500.0, 0.1)


class TestRunnerGating(unittest.TestCase):
    def test_all_pass_plus_imaging_is_candidate(self):
        run = run_gauntlet(_ctx(imaging=IMAGING_ON))
        self.assertEqual(run.final_verdict, "CANDIDATE")
        self.assertEqual(run.skipped, [])
        self.assertEqual([r.stage for r in run.results],
                         list(REQUIRED_STAGES))

    def test_bulk_ephemeris_refuses_every_fold_stage(self):
        # The core kind rule: a bulk period is not a fold anchor.
        # Every fold stage is skipped (never run), the verdict is
        # INCONCLUSIVE, and the reasons name the kind mismatch.
        run = run_gauntlet(_ctx(kind="bulk", imaging=IMAGING_ON))
        self.assertEqual(run.final_verdict, "INCONCLUSIVE")
        self.assertEqual(len(run.skipped), len(REQUIRED_STAGES))
        for r in run.results:
            self.assertEqual(r.status, "unmeasured")
            self.assertEqual(r.execution_status, "skipped")
            self.assertIn("refined ephemeris", r.reason)

    def test_missing_native_output_skips_only_that_stage(self):
        natives = dict(PASSING_NATIVES)
        del natives["shape_gate.native"]
        run = run_gauntlet(_ctx(natives=natives, imaging=IMAGING_ON))
        self.assertEqual(run.final_verdict, "INCONCLUSIVE")
        by_stage = {r.stage: r for r in run.results}
        self.assertEqual(by_stage["shape_gate"].status, "unmeasured")
        self.assertEqual(by_stage["shape_gate"].execution_status,
                         "skipped")
        self.assertIn("shape_gate.native",
                      by_stage["shape_gate"].reason)
        # The other stages still ran and passed.
        self.assertEqual(by_stage["raw_flux"].status, "pass")
        self.assertEqual(by_stage["parity"].status, "pass")

    def test_fail_short_circuits(self):
        natives = dict(PASSING_NATIVES)
        natives["raw_flux.native"] = {
            "depth_pct": -0.02, "signif_white": -0.5,
            "n_in": 42, "n_events": 13}
        run = run_gauntlet(_ctx(natives=natives, imaging=IMAGING_ON))
        self.assertEqual(run.final_verdict, "REFUTED")
        by_stage = {r.stage: r for r in run.results}
        self.assertEqual(by_stage["raw_flux"].status, "fail")
        # Everything after the fail never started.
        for name in ("shape_gate", "parity", "persistence",
                     "holdout"):
            self.assertEqual(by_stage[name].status, "unmeasured")
            self.assertEqual(by_stage[name].execution_status,
                             "not_started")

    def test_exhaustive_runs_past_fail(self):
        natives = dict(PASSING_NATIVES)
        natives["raw_flux.native"] = {
            "depth_pct": -0.02, "signif_white": -0.5,
            "n_in": 42, "n_events": 13}
        run = run_gauntlet(_ctx(natives=natives, imaging=IMAGING_ON),
                           mode="exhaustive")
        self.assertEqual(run.final_verdict, "REFUTED")
        by_stage = {r.stage: r for r in run.results}
        self.assertEqual(by_stage["shape_gate"].status, "pass")
        self.assertEqual(by_stage["shape_gate"].execution_status,
                         "completed")

    def test_skipped_mandatory_stage_never_yields_candidate(self):
        # A plan that omits a required stage cannot produce a
        # candidate — the aggregator sees a never-run stage.
        run = run_gauntlet(_ctx(imaging=IMAGING_ON),
                           stages=["clean_gate", "raw_flux",
                                   "shape_gate", "parity",
                                   "persistence"])
        self.assertEqual(run.final_verdict, "INCONCLUSIVE")
        self.assertIn("holdout", run.verdict_note)

    def test_unknown_stage_raises(self):
        with self.assertRaises(ValueError):
            run_gauntlet(_ctx(), stages=["nope"])

    def test_bad_mode_raises(self):
        with self.assertRaises(ValueError):
            run_gauntlet(_ctx(), mode="sideways")

    def test_stage_exception_becomes_unmeasured_error(self):
        def _boom(_ctx):
            raise RuntimeError("synthetic tool crash")
        register_stage(StageSpec("boom_stage", func=_boom,
                                 mandatory=False))
        try:
            run = run_gauntlet(_ctx(imaging=IMAGING_ON),
                               stages=list(REQUIRED_STAGES)
                               + ["boom_stage"])
        finally:
            # The registry is global: leave it as found.
            from gauntlet.runner import STAGE_REGISTRY
            del STAGE_REGISTRY["boom_stage"]
        by_stage = {r.stage: r for r in run.results}
        boom = by_stage["boom_stage"]
        self.assertEqual(boom.status, "unmeasured")
        self.assertEqual(boom.execution_status, "error")
        self.assertIn("RuntimeError", boom.reason)
        # The crash did not kill the run — but the candidate is
        # blocked, because an unmeasured stage is a gap.
        self.assertEqual(run.final_verdict, "INCONCLUSIVE")


class TestDependencyGating(unittest.TestCase):
    def test_dependent_stage_blocked_by_failed_prerequisite(self):
        # A stage requiring another stage's product runs only
        # when the producer PASSED.
        register_stage(StageSpec(
            "fit_stage", requires=("shape_gate",),
            produces=("fit_stage",),
            func=lambda ctx: StageResult(
                "fit_stage", "pass", "fit ok", dict(PROV)),
            mandatory=False))
        try:
            # Producer passes -> dependent runs.
            run = run_gauntlet(_ctx(imaging=IMAGING_ON),
                               stages=["shape_gate", "fit_stage"])
            by_stage = {r.stage: r for r in run.results}
            self.assertEqual(by_stage["fit_stage"].status, "pass")
            # Producer fails -> dependent is refused, never run.
            natives = dict(PASSING_NATIVES)
            natives["shape_gate.native"] = {
                "shape_verdict": "V-shaped", "T23_T14": 0.25,
                "density_flag": False}
            run = run_gauntlet(
                _ctx(natives=natives, imaging=IMAGING_ON),
                stages=["shape_gate", "fit_stage"],
                mode="exhaustive")
            by_stage = {r.stage: r for r in run.results}
            self.assertEqual(by_stage["shape_gate"].status, "fail")
            self.assertEqual(by_stage["fit_stage"].status,
                             "unmeasured")
            self.assertEqual(by_stage["fit_stage"].execution_status,
                             "skipped")
            self.assertIn("shape_gate", by_stage["fit_stage"].reason)
        finally:
            from gauntlet.runner import STAGE_REGISTRY
            del STAGE_REGISTRY["fit_stage"]

    def test_validate_plan_finds_missing_prerequisites(self):
        ctx = _ctx(natives={})
        problems = validate_plan(ctx, list(REQUIRED_STAGES))
        self.assertEqual(len(problems), len(REQUIRED_STAGES))
        self.assertTrue(all("native" in ";".join(reasons)
                            for _s, reasons in problems))
        # A full context validates clean.
        self.assertEqual(validate_plan(_ctx(),
                                      list(REQUIRED_STAGES)), [])
        with self.assertRaises(ValueError):
            validate_plan(_ctx(), ["nope"])


class TestReportGate(unittest.TestCase):
    def test_report_blocked_without_blend(self):
        ok, reason = check_report_ready([])
        self.assertFalse(ok)
        self.assertIn("blend", reason)

    def test_report_blocked_on_unmeasured_blend(self):
        ok, _r = check_report_ready([
            StageResult("blend", "unmeasured", "no data", PROV)])
        self.assertFalse(ok)

    def test_report_blocked_on_failed_blend(self):
        ok, _r = check_report_ready([
            StageResult("blend", "fail", "photocopy", PROV)])
        self.assertFalse(ok)

    def test_report_ready_on_passed_blend(self):
        ok, _r = check_report_ready([
            StageResult("blend", "pass", "on-target", PROV)])
        self.assertTrue(ok)


if __name__ == "__main__":
    unittest.main()
