"""Stage-runner tests (Phase 1.2, item A-5).

No downloads: the runner is about ORDER and GATING, so the
tests drive it with synthetic contexts and stub stages.

The rules under test:
a fold stage cannot consume a bulk ephemeris (only refine
produces a refined one); a stage cannot run on a missing or
unmeasured prerequisite; cheap stages ALWAYS run, and only
expensive stages short-circuit after a FAIL; a skipped
mandatory stage can never produce a candidate; a stage that
raises becomes unmeasured with an error execution status, never
a pass and never a run-killing crash; the context is frozen and
results are cached by input hash.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gauntlet.runner import (Ephemeris, StageSpec, TargetContext,  # noqa: E402
                             check_report_ready, get_stage,
                             register_stage, run_gauntlet,
                             validate_plan)
from gauntlet.stage_result import REQUIRED_STAGES, StageResult  # noqa: E402

PROV = {"calibration_version": "gauntlet_v2",
        "pipeline_git_sha": "test",
        "run_id": "test-run-1",
        "timestamp_utc": "2026-11-14T00:00:00+00:00"}

IMAGING_ON = {"on_target": True, "offset_px": 0.06,
              "offset_arcsec": 1.3}

# Native outputs that make every built-in adapter pass. The
# period is 12.5 d (above the pixel-check 8 d floor) so the
# pixel check runs and passes.
PASSING_NATIVES = {
    "catalogue.native": {"known": False},
    "clean_refold.native": (
        {"n_in": 42, "n_events": 13, "depth_percent": 0.9,
         "snr": 12.0}, "PASS"),
    "refine.native": {"period_d": 12.5, "t0": 1500.0,
                      "duration_d": 0.1, "converged": True,
                      "rms_resid_d": 0.001, "n_eras": 5},
    "raw_flux.native": {"depth_pct": 0.9, "signif_white": 12.0,
                        "n_in": 42, "n_events": 13},
    "shape.native": {"shape_verdict": "U-shaped",
                          "T23_T14": 0.62, "density_flag": False},
    "odd_even.native": (
        {"depth_pct": 2.0, "sig_white_pct": 0.14},
        {"depth_pct": 1.9, "sig_white_pct": 0.13}),
    "persistence.native": {"verdict": "CONSISTENT", "n_usable": 6},
    "holdout.native": "HOLDOUT-PASS",
    "diffimg.native": {"on_target": True, "offset_px": 0.06,
                       "offset_arcsec": 1.3, "n_sectors": 3},
    "pixel_check.native": {
        "verdict": "pass",
        "reason": "pixels darken at the claimed transit times"},
    "transit_fit.native": {"b": 0.4, "rp_re": 3.2, "t14_h": 2.1,
                           "density_flag": False,
                           "converged": True},
}


def _blend_native(target_depth=1.0, neighbour_depth=0.0, seed=7):
    """A blend native: a 10 d light curve with one transit at
    T0=1500.0, P=12.5 d, DUR=0.1 d. Default: a 1% target dip
    and a flat neighbour (on_target)."""
    rng = np.random.default_rng(seed)
    t = 1500.0 + np.arange(5000) * 0.002
    ph = (((t - 1500.0) / 12.5 + 0.5) % 1.0) - 0.5
    in_tr = np.abs(ph) < 0.5 * 0.1 / 12.5
    f_t = (np.ones_like(t) - target_depth / 100.0 * in_tr
           + rng.normal(0, 0.002, len(t)))
    f_n = (np.ones_like(t) - neighbour_depth / 100.0 * in_tr
           + rng.normal(0, 0.002, len(t)))
    return {"target_t": t, "target_f": f_t,
            "neighbour_t": t, "neighbour_f": f_n,
            "period_d": 12.5, "t0": 1500.0, "duration_d": 0.1,
            "neighbour_tic": "238620465",
            "separation_arcsec": 66.5}


PASSING_NATIVES["blend.native"] = _blend_native()


def _ctx(natives=None, kind="bulk", imaging=None, period=12.5,
         refine_period=None, bulk_survivor=True):
    natives = (dict(natives) if natives is not None
               else dict(PASSING_NATIVES))
    if refine_period is not None and "refine.native" in natives:
        natives["refine.native"] = dict(natives["refine.native"])
        natives["refine.native"]["period_d"] = refine_period
    eph = Ephemeris(kind, period, 1500.0, 0.1,
                    source="phase-scan refinement"
                    if kind == "refined" else "filed")
    return TargetContext(
        tic="238620464", ephemeris=eph, artifacts=natives,
        provenance=dict(PROV),
        imaging=dict(imaging) if imaging is not None else None,
        bulk_survivor=bulk_survivor)


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

    def test_fold_stages_refuse_bulk_ephemeris(self):
        # The core kind rule: a bulk period is not a fold
        # anchor. Without a refine native there is no refined
        # ephemeris, so refine and every fold stage are skipped
        # (never run); catalogue and clean_refold, which do not
        # fold, still run and pass. The verdict is INCONCLUSIVE
        # and the reasons name the refined ephemeris.
        natives = dict(PASSING_NATIVES)
        del natives["refine.native"]
        run = run_gauntlet(_ctx(natives=natives,
                                imaging=IMAGING_ON))
        self.assertEqual(run.final_verdict, "INCONCLUSIVE")
        by_stage = {r.stage: r for r in run.results}
        self.assertEqual(by_stage["catalogue"].status, "pass")
        self.assertEqual(by_stage["clean_refold"].status, "pass")
        for name in ("refine", "raw_flux", "persistence",
                     "shape", "odd_even", "holdout", "diffimg",
                     "blend", "pixel_check", "transit_fit"):
            self.assertEqual(by_stage[name].status, "unmeasured")
            self.assertEqual(by_stage[name].execution_status,
                             "skipped")
        self.assertIn("ephemeris.refined",
                      by_stage["raw_flux"].reason)

    def test_refined_entry_is_not_a_completed_refinement(self):
        # A caller holding only a refined ephemeris: the fold
        # stages run (the refined ephemeris IS available), but
        # refine and clean_refold are skipped — their input, the
        # bulk ephemeris, is absent — and the run cannot reach
        # CANDIDATE until refine actually runs.
        run = run_gauntlet(_ctx(kind="refined",
                                imaging=IMAGING_ON))
        self.assertEqual(run.final_verdict, "INCONCLUSIVE")
        by_stage = {r.stage: r for r in run.results}
        self.assertEqual(by_stage["refine"].status, "unmeasured")
        self.assertEqual(by_stage["refine"].execution_status,
                         "skipped")
        self.assertEqual(by_stage["clean_refold"].status,
                         "unmeasured")
        self.assertEqual(by_stage["raw_flux"].status, "pass")
        # The note names the first blocker (clean_refold); the
        # refine skip is asserted above.
        self.assertIn("clean_refold", run.verdict_note)

    def test_refine_upgrades_the_ephemeris(self):
        # The pixel check's P >= 8 d rule reads the REFINED
        # period: a 12.5 d bulk period refined to 2.17 d makes
        # the pixel check not_applicable.
        run = run_gauntlet(_ctx(imaging=IMAGING_ON,
                                refine_period=2.17))
        by_stage = {r.stage: r for r in run.results}
        self.assertEqual(by_stage["refine"].status, "pass")
        self.assertEqual(by_stage["pixel_check"].status,
                         "not_applicable")

    def test_missing_native_output_skips_only_that_stage(self):
        natives = dict(PASSING_NATIVES)
        del natives["shape.native"]
        run = run_gauntlet(_ctx(natives=natives, imaging=IMAGING_ON))
        self.assertEqual(run.final_verdict, "INCONCLUSIVE")
        by_stage = {r.stage: r for r in run.results}
        self.assertEqual(by_stage["shape"].status, "unmeasured")
        self.assertEqual(by_stage["shape"].execution_status,
                         "skipped")
        self.assertIn("shape.native",
                      by_stage["shape"].reason)
        # The other stages still ran and passed — except
        # transit_fit, whose prerequisite (shape) never ran.
        self.assertEqual(by_stage["raw_flux"].status, "pass")
        self.assertEqual(by_stage["odd_even"].status, "pass")
        self.assertEqual(by_stage["transit_fit"].status,
                         "unmeasured")
        self.assertIn("shape", by_stage["transit_fit"].reason)

    def test_fail_short_circuits_only_expensive_stages(self):
        # v2 semantics (A-5): cheap stages ALWAYS run after a
        # FAIL — their results are diagnostic. Only the
        # expensive stages (holdout, diffimg, transit_fit)
        # are not started.
        natives = dict(PASSING_NATIVES)
        natives["raw_flux.native"] = {
            "depth_pct": -0.02, "signif_white": -0.5,
            "n_in": 42, "n_events": 13}
        run = run_gauntlet(_ctx(natives=natives, imaging=IMAGING_ON))
        self.assertEqual(run.final_verdict, "REFUTED")
        by_stage = {r.stage: r for r in run.results}
        self.assertEqual(by_stage["raw_flux"].status, "fail")
        for name in ("shape", "odd_even", "persistence",
                     "blend", "pixel_check"):
            self.assertEqual(by_stage[name].status, "pass")
            self.assertEqual(by_stage[name].execution_status,
                             "completed")
        for name in ("holdout", "diffimg", "transit_fit"):
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
        self.assertEqual(by_stage["shape"].status, "pass")
        self.assertEqual(by_stage["shape"].execution_status,
                         "completed")
        self.assertEqual(by_stage["holdout"].status, "pass")
        self.assertEqual(by_stage["transit_fit"].status, "pass")

    def test_skipped_mandatory_stage_never_yields_candidate(self):
        # A plan that omits required stages cannot produce a
        # candidate — the aggregator sees never-run stages.
        run = run_gauntlet(_ctx(imaging=IMAGING_ON),
                           stages=["catalogue", "clean_refold",
                                   "refine", "raw_flux", "shape",
                                   "odd_even", "persistence",
                                   "pixel_check"])
        self.assertEqual(run.final_verdict, "INCONCLUSIVE")
        self.assertIn("holdout", run.verdict_note)

    def test_out_of_order_plan_cannot_produce_candidate(self):
        # A fold stage placed before refine is refused: its
        # prerequisite (the refined ephemeris) does not exist
        # yet. Order is enforced by the prerequisites, not by
        # trusting the caller's list.
        run = run_gauntlet(_ctx(imaging=IMAGING_ON),
                           stages=["raw_flux", "refine",
                                   "catalogue"])
        by_stage = {r.stage: r for r in run.results}
        self.assertEqual(by_stage["raw_flux"].status,
                         "unmeasured")
        self.assertEqual(by_stage["raw_flux"].execution_status,
                         "skipped")
        self.assertEqual(by_stage["refine"].status, "pass")
        self.assertEqual(run.final_verdict, "INCONCLUSIVE")

    def test_blend_fail_kills_the_candidate(self):
        # A deep neighbour dip at the target ephemeris is a
        # photocopy: the run ends BLEND.
        natives = dict(PASSING_NATIVES)
        natives["blend.native"] = _blend_native(
            target_depth=1.0, neighbour_depth=22.0)
        run = run_gauntlet(_ctx(natives=natives,
                                imaging=IMAGING_ON))
        self.assertEqual(run.final_verdict, "BLEND")
        by_stage = {r.stage: r for r in run.results}
        self.assertEqual(by_stage["blend"].status, "fail")

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
            "fit_stage", requires=("shape",),
            produces=("fit_stage",),
            func=lambda ctx: StageResult(
                "fit_stage", "pass", "fit ok", dict(PROV)),
            mandatory=False))
        try:
            # Producer passes -> dependent runs.
            run = run_gauntlet(_ctx(imaging=IMAGING_ON),
                               stages=["refine", "shape",
                                       "fit_stage"])
            by_stage = {r.stage: r for r in run.results}
            self.assertEqual(by_stage["fit_stage"].status, "pass")
            # Producer fails -> dependent is refused, never run
            # (prerequisite gating is not short-circuiting: it
            # applies in exhaustive mode too).
            natives = dict(PASSING_NATIVES)
            natives["shape.native"] = {
                "shape_verdict": "V-shaped", "T23_T14": 0.25,
                # P-8: a V-shaped FAIL needs the legs — frac_err
                # known with the upper bound under the 0.30 bar,
                # at depth0_signif >= 5.
                "frac_err": 0.02, "depth0_signif": 10.0,
                "density_flag": False}
            run = run_gauntlet(
                _ctx(natives=natives, imaging=IMAGING_ON),
                stages=["refine", "shape", "fit_stage"],
                mode="exhaustive")
            by_stage = {r.stage: r for r in run.results}
            self.assertEqual(by_stage["shape"].status, "fail")
            self.assertEqual(by_stage["fit_stage"].status,
                             "unmeasured")
            self.assertEqual(by_stage["fit_stage"].execution_status,
                             "skipped")
            self.assertIn("shape", by_stage["fit_stage"].reason)
        finally:
            from gauntlet.runner import STAGE_REGISTRY
            del STAGE_REGISTRY["fit_stage"]

    def test_waived_prerequisite_satisfies_dependent(self):
        # A producer that is inconclusive AND waived counts as
        # satisfied (the transit_fit rule); without the waiver
        # the dependent is refused. F-5: the producer carries a
        # waiver code, registered in WAIVER_CODES like the
        # stage itself (and removed afterwards).
        from gauntlet.stage_result import WAIVER_CODES
        WAIVER_CODES["prod_stage"] = {"test_code"}
        register_stage(StageSpec(
            "prod_stage", produces=("prod_stage",),
            func=lambda ctx: StageResult(
                "prod_stage", "inconclusive", "ambiguous",
                dict(PROV), waiver_code="test_code"),
            mandatory=False))
        register_stage(StageSpec(
            "dep_stage", requires=("prod_stage",),
            produces=("dep_stage",),
            func=lambda ctx: StageResult(
                "dep_stage", "pass", "ran", dict(PROV)),
            mandatory=False))
        policy = {"waivers": {"prod_stage": "test grounds"}}
        try:
            run = run_gauntlet(
                _ctx(imaging=IMAGING_ON),
                stages=["prod_stage", "dep_stage"],
                waivers={"prod_stage": "ambiguous by design"},
                policy=policy)
            by_stage = {r.stage: r for r in run.results}
            self.assertEqual(by_stage["dep_stage"].status, "pass")
            # F-5: the reason is stamped onto the waived result.
            self.assertEqual(by_stage["prod_stage"].waiver_reason,
                             "ambiguous by design")
            run = run_gauntlet(
                _ctx(imaging=IMAGING_ON),
                stages=["prod_stage", "dep_stage"])
            by_stage = {r.stage: r for r in run.results}
            self.assertEqual(by_stage["dep_stage"].status,
                             "unmeasured")
            self.assertEqual(by_stage["dep_stage"].execution_status,
                             "skipped")
        finally:
            from gauntlet.runner import STAGE_REGISTRY
            del STAGE_REGISTRY["prod_stage"]
            del STAGE_REGISTRY["dep_stage"]
            del WAIVER_CODES["prod_stage"]

    def test_validate_plan_finds_missing_prerequisites(self):
        ctx = _ctx(natives={})
        problems = validate_plan(ctx, list(REQUIRED_STAGES))
        # Every stage with a native input is a problem; the two
        # stages whose only requirement is an ephemeris
        # (clean_refold: bulk, present at entry; pixel_check:
        # refined, produced by refine in the plan) are not.
        self.assertEqual({s for s, _r in problems},
                         {"catalogue", "refine", "raw_flux",
                          "persistence", "shape", "odd_even",
                          "holdout", "diffimg", "blend",
                          "transit_fit"})
        self.assertTrue(all("native" in ";".join(reasons)
                            for _s, reasons in problems))
        # A full context validates clean.
        self.assertEqual(validate_plan(_ctx(),
                                      list(REQUIRED_STAGES)), [])
        with self.assertRaises(ValueError):
            validate_plan(_ctx(), ["nope"])


class TestConditionalStages(unittest.TestCase):
    def test_pixel_check_not_applicable_below_8d(self):
        # A short period makes the pixel check not_applicable,
        # which blocks CANDIDATE without a waiver and passes
        # with one (pixel_check is in the policy allowlist).
        run = run_gauntlet(_ctx(imaging=IMAGING_ON, period=2.17,
                                refine_period=2.17))
        self.assertEqual(run.final_verdict, "INCONCLUSIVE")
        by_stage = {r.stage: r for r in run.results}
        self.assertEqual(by_stage["pixel_check"].status,
                         "not_applicable")
        # F-5: the adapter attaches the structural code.
        self.assertEqual(by_stage["pixel_check"].waiver_code,
                         "period_lt_8d")
        run = run_gauntlet(
            _ctx(imaging=IMAGING_ON, period=2.17,
                 refine_period=2.17),
            waivers={"pixel_check": "period 2.17 d < 8 d"})
        self.assertEqual(run.final_verdict, "CANDIDATE")
        by_stage = {r.stage: r for r in run.results}
        self.assertEqual(by_stage["pixel_check"].waiver_reason,
                         "period 2.17 d < 8 d")

    def test_clean_refold_not_applicable_off_bulk(self):
        # A non-bulk target has no clean-data gate: the stage is
        # not_applicable, and the policy waives it.
        run = run_gauntlet(_ctx(imaging=IMAGING_ON,
                                bulk_survivor=False))
        by_stage = {r.stage: r for r in run.results}
        self.assertEqual(by_stage["clean_refold"].status,
                         "not_applicable")
        self.assertEqual(by_stage["clean_refold"].waiver_code,
                         "not_bulk_survivor")
        self.assertEqual(run.final_verdict, "INCONCLUSIVE")
        run = run_gauntlet(
            _ctx(imaging=IMAGING_ON, bulk_survivor=False),
            waivers={"clean_refold":
                     "deep-pipeline target, no bulk gate"})
        self.assertEqual(run.final_verdict, "CANDIDATE")


class TestFrozenContext(unittest.TestCase):
    def test_context_is_immutable(self):
        ctx = _ctx()
        with self.assertRaises(Exception):
            ctx.artifacts["new.native"] = {}
        with self.assertRaises(Exception):
            ctx.tic = "999"
        # with_artifact derives a NEW context; the original is
        # unchanged.
        ctx2 = ctx.with_artifact("extra.native", {"a": 1})
        self.assertNotIn("extra.native", ctx.artifacts)
        self.assertIn("extra.native", ctx2.artifacts)
        self.assertEqual(ctx2.tic, ctx.tic)

    def test_context_hash_ignores_provenance(self):
        # Two contexts differing only in run provenance (run_id,
        # timestamp) hash identically — otherwise the cache
        # could never hit.
        ctx1 = _ctx()
        prov2 = dict(PROV)
        prov2["run_id"] = "a-different-run"
        ctx2 = TargetContext(
            tic=ctx1.tic, ephemeris=ctx1.ephemeris,
            artifacts=dict(ctx1.artifacts), provenance=prov2,
            imaging=dict(IMAGING_ON) if ctx1.imaging else None,
            bulk_survivor=ctx1.bulk_survivor)
        self.assertEqual(ctx1.context_hash(), ctx2.context_hash())
        # A different native input hashes differently.
        natives = dict(PASSING_NATIVES)
        natives["shape.native"] = {
            "shape_verdict": "V-shaped", "T23_T14": 0.25,
            # P-8: a V-shaped FAIL needs the legs — frac_err
            # known with the upper bound under the 0.30 bar,
            # at depth0_signif >= 5.
            "frac_err": 0.02, "depth0_signif": 10.0,
            "density_flag": False}
        ctx3 = _ctx(natives=natives)
        self.assertNotEqual(ctx1.context_hash(),
                            ctx3.context_hash())


class TestResultCaching(unittest.TestCase):
    def test_second_run_is_cached(self):
        with tempfile.TemporaryDirectory() as td:
            run1 = run_gauntlet(_ctx(imaging=IMAGING_ON),
                                work_dir=td)
            self.assertFalse(run1.cached)
            self.assertEqual(run1.final_verdict, "CANDIDATE")
            cache = Path(td) / "gauntlet-cache"
            self.assertEqual(len(list(cache.glob("*.json"))), 1)
            run2 = run_gauntlet(_ctx(imaging=IMAGING_ON),
                                work_dir=td)
            self.assertTrue(run2.cached)
            self.assertEqual(run2.final_verdict, "CANDIDATE")
            self.assertEqual(
                [r.to_dict() for r in run2.results],
                [r.to_dict() for r in run1.results])

    def test_changed_input_misses_the_cache(self):
        with tempfile.TemporaryDirectory() as td:
            run_gauntlet(_ctx(imaging=IMAGING_ON), work_dir=td)
            natives = dict(PASSING_NATIVES)
            natives["shape.native"] = {
                "shape_verdict": "V-shaped", "T23_T14": 0.25,
                # P-8: a V-shaped FAIL needs the legs — frac_err
                # known with the upper bound under the 0.30 bar,
                # at depth0_signif >= 5.
                "frac_err": 0.02, "depth0_signif": 10.0,
                "density_flag": False}
            run2 = run_gauntlet(_ctx(natives=natives,
                                     imaging=IMAGING_ON),
                                work_dir=td)
            self.assertFalse(run2.cached)
            self.assertEqual(run2.final_verdict, "EB")

    def test_calibration_change_misses_the_cache(self):
        # F-16: the context hash ignores provenance (a different
        # run_id hashes identically), so a calibration change
        # must be caught by the cache verification, not the
        # hash. Same inputs, different calibration_version ->
        # the cache must NOT be reused.
        with tempfile.TemporaryDirectory() as td:
            ctx1 = _ctx(imaging=IMAGING_ON)
            run1 = run_gauntlet(ctx1, work_dir=td)
            self.assertFalse(run1.cached)
            # The cached record carries the verification fields.
            cache = Path(td) / "gauntlet-cache"
            record = json.loads(
                next(cache.glob("*.json")).read_text())
            self.assertEqual(record["calibration_version"],
                             "gauntlet_v2")
            self.assertTrue(record["code_fingerprint"])
            self.assertEqual(record["waivers"], {})
            prov2 = dict(PROV)
            prov2["calibration_version"] = "gauntlet_v1"
            ctx2 = TargetContext(
                tic=ctx1.tic, ephemeris=ctx1.ephemeris,
                artifacts=dict(ctx1.artifacts), provenance=prov2,
                imaging=dict(IMAGING_ON),
                bulk_survivor=ctx1.bulk_survivor)
            self.assertEqual(ctx1.context_hash(),
                             ctx2.context_hash())
            run2 = run_gauntlet(ctx2, work_dir=td)
            self.assertFalse(run2.cached)

    def test_waivers_change_misses_the_cache(self):
        # F-16: a run cached WITHOUT waivers must not be reused
        # for a run WITH waivers (and vice versa) — the verdict
        # differs (INCONCLUSIVE vs CANDIDATE) on identical
        # inputs.
        with tempfile.TemporaryDirectory() as td:
            run1 = run_gauntlet(
                _ctx(imaging=IMAGING_ON, bulk_survivor=False),
                work_dir=td)
            self.assertFalse(run1.cached)
            self.assertEqual(run1.final_verdict, "INCONCLUSIVE")
            waiver = {"clean_refold":
                      "deep-pipeline target, no bulk gate"}
            run2 = run_gauntlet(
                _ctx(imaging=IMAGING_ON, bulk_survivor=False),
                waivers=waiver, work_dir=td)
            self.assertFalse(run2.cached)
            self.assertEqual(run2.final_verdict, "CANDIDATE")
            # Same waivers again: the cache hits.
            run3 = run_gauntlet(
                _ctx(imaging=IMAGING_ON, bulk_survivor=False),
                waivers=waiver, work_dir=td)
            self.assertTrue(run3.cached)
            self.assertEqual(run3.final_verdict, "CANDIDATE")

    def test_code_change_misses_the_cache(self):
        # F-16: proven by mocking the fingerprint — a different
        # code fingerprint on the second run discards the cache.
        with tempfile.TemporaryDirectory() as td:
            run_gauntlet(_ctx(imaging=IMAGING_ON), work_dir=td)
            import gauntlet.runner as _runner_mod
            with mock.patch.object(
                    _runner_mod._provenance,
                    "fingerprint_result_affecting",
                    return_value="0" * 64):
                run2 = run_gauntlet(_ctx(imaging=IMAGING_ON),
                                    work_dir=td)
            self.assertFalse(run2.cached)

    def test_legacy_cache_record_is_discarded(self):
        # F-16: a pre-F-16 record (no verification fields) must
        # never be trusted — strip the fields and the run
        # re-executes.
        with tempfile.TemporaryDirectory() as td:
            run_gauntlet(_ctx(imaging=IMAGING_ON), work_dir=td)
            cache = Path(td) / "gauntlet-cache"
            path = next(cache.glob("*.json"))
            record = json.loads(path.read_text())
            for key in ("calibration_version",
                        "code_fingerprint", "waivers"):
                record.pop(key, None)
            path.write_text(json.dumps(record))
            run2 = run_gauntlet(_ctx(imaging=IMAGING_ON),
                                work_dir=td)
            self.assertFalse(run2.cached)


class TestReportGate(unittest.TestCase):
    def test_report_blocked_without_anything(self):
        ok, reason = check_report_ready([])
        self.assertFalse(ok)
        self.assertIn("persistence", reason)

    def test_report_blocked_on_unmeasured_blend(self):
        ok, reason = check_report_ready([
            StageResult("persistence", "pass", "ok", PROV),
            StageResult("diffimg", "pass", "ok", PROV),
            StageResult("blend", "unmeasured", "no data", PROV)])
        self.assertFalse(ok)
        self.assertIn("blend", reason)

    def test_report_blocked_on_failed_diffimg(self):
        ok, reason = check_report_ready([
            StageResult("persistence", "pass", "ok", PROV),
            StageResult("diffimg", "fail", "off-target", PROV),
            StageResult("blend", "pass", "ok", PROV)])
        self.assertFalse(ok)
        self.assertIn("diffimg", reason)

    def test_report_ready_on_all_pass(self):
        ok, _r = check_report_ready([
            StageResult("persistence", "pass", "ok", PROV),
            StageResult("diffimg", "pass", "ok", PROV),
            StageResult("blend", "pass", "on-target", PROV)])
        self.assertTrue(ok)

    def test_report_blocked_on_waiver_without_2e_review(self):
        # F-5: a waived candidate (waiver_reason on a result)
        # needs a second-eyes review marker before filing —
        # even when persistence/diffimg/blend all pass.
        results = [
            StageResult("persistence", "pass", "ok", PROV),
            StageResult("diffimg", "pass", "ok", PROV),
            StageResult("blend", "pass", "on-target", PROV),
            StageResult("holdout", "not_applicable",
                        "single-sector target", PROV,
                        waiver_code="single_sector",
                        waiver_reason="one sector only")]
        ok, reason = check_report_ready(results)
        self.assertFalse(ok)
        self.assertIn("second-eyes", reason)
        # An empty marker or a nameless reviewer does not count.
        ok, _r = check_report_ready(results, review_2e={})
        self.assertFalse(ok)
        ok, _r = check_report_ready(results,
                                    review_2e={"reviewer": "  "})
        self.assertFalse(ok)
        ok, _r = check_report_ready(
            results, review_2e={"reviewer": "second vetter"})
        self.assertTrue(ok)


if __name__ == "__main__":
    unittest.main()
