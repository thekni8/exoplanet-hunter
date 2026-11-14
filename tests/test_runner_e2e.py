"""End-to-end runner integration test (Phase 1.2 follow-up F-7).

test_runner.py proves the runner's ORDER and GATING rules with
stub stages; this file proves the whole gauntlet over one
synthetic target, end to end, through the real adapters and the
real DAG — ChatGPT's 7-scenario table from the Phase 1.2 vote:

  1. all-pass -> CANDIDATE
  2. missing prerequisite -> skipped + INCONCLUSIVE
  3. UNMEASURED (a stage that ran but could not measure) blocks
     promotion -> INCONCLUSIVE
  4. FAIL in an expensive-stage prerequisite short-circuits the
     expensive stages (raw_flux FAIL -> holdout/diffimg/
     transit_fit not_started; shape FAIL -> transit_fit
     not_started) while cheap stages still run
  5. INCONCLUSIVE/NOT_APPLICABLE blocks unless waived
     (clean_refold not_applicable via bulk_survivor=False +
     waiver -> CANDIDATE)
  6. a stage that raises -> unmeasured + error (not a
     scientific FAIL, not a run kill)
  7. repeated execution -> identical (verdict + per-stage
     status/execution_status)

The target is self-contained (its own builder — this file does
not import test_runner): P 12.5 d, 1.0% injected depth, a
neighbouring contaminant for the BLEND scenario (22% neighbour
dip). No downloads, no network.
"""
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gauntlet.runner import (Ephemeris, StageSpec, TargetContext,  # noqa: E402
                             STAGE_REGISTRY, register_stage,
                             run_gauntlet)
from gauntlet.stage_result import REQUIRED_STAGES  # noqa: E402

PROV = {"calibration_version": "gauntlet_v2",
        "pipeline_git_sha": "test",
        "run_id": "test-run-e2e",
        "timestamp_utc": "2026-11-14T00:00:00+00:00"}

IMAGING_ON = {"on_target": True, "offset_px": 0.06,
              "offset_arcsec": 1.3}

PERIOD_D = 12.5  # above the pixel-check 8 d floor
T0 = 1500.0
DURATION_D = 0.1
DEPTH_PCT = 1.0


def _blend_native(neighbour_depth=0.0, seed=7):
    """A blend native: a 10 d light curve with transits at
    P=12.5 d, T0=1500.0, DUR=0.1 d. Default: a 1% target dip
    and a flat neighbour (on_target). neighbour_depth=22.0
    makes the neighbour the source (BLEND)."""
    rng = np.random.default_rng(seed)
    t = 1500.0 + np.arange(5000) * 0.002
    ph = (((t - T0) / PERIOD_D + 0.5) % 1.0) - 0.5
    in_tr = np.abs(ph) < 0.5 * DURATION_D / PERIOD_D
    f_t = (np.ones_like(t) - DEPTH_PCT / 100.0 * in_tr
           + rng.normal(0, 0.002, len(t)))
    f_n = (np.ones_like(t) - neighbour_depth / 100.0 * in_tr
           + rng.normal(0, 0.002, len(t)))
    return {"target_t": t, "target_f": f_t,
            "neighbour_t": t, "neighbour_f": f_n,
            "period_d": PERIOD_D, "t0": T0,
            "duration_d": DURATION_D,
            "neighbour_tic": "238620465",
            "separation_arcsec": 66.5}


def _passing_natives():
    """Native outputs that make every built-in adapter pass."""
    return {
        "catalogue.native": {"known": False},
        "clean_refold.native": (
            {"n_in": 42, "n_events": 13, "depth_percent": 0.9,
             "snr": 12.0}, "PASS"),
        "refine.native": {"period_d": PERIOD_D, "t0": T0,
                          "duration_d": DURATION_D,
                          "converged": True,
                          "rms_resid_d": 0.001, "n_eras": 5},
        "raw_flux.native": {"depth_pct": 0.9, "signif_white": 12.0,
                            "n_in": 42, "n_events": 13},
        "shape.native": {"shape_verdict": "U-shaped",
                         "T23_T14": 0.62, "density_flag": False},
        "odd_even.native": (
            {"depth_pct": 2.0, "sig_white_pct": 0.14},
            {"depth_pct": 1.9, "sig_white_pct": 0.13}),
        "persistence.native": {"verdict": "CONSISTENT",
                               "n_usable": 6},
        "holdout.native": "HOLDOUT-PASS",
        "diffimg.native": {"on_target": True, "offset_px": 0.06,
                           "offset_arcsec": 1.3, "n_sectors": 3},
        "blend.native": _blend_native(),
        "pixel_check.native": {
            "verdict": "pass",
            "reason": "pixels darken at the claimed transit times"},
        "transit_fit.native": {"b": 0.4, "rp_re": 3.2,
                               "t14_h": 2.1, "density_flag": False,
                               "converged": True},
    }


def _target(natives=None, imaging=IMAGING_ON, bulk_survivor=True):
    """One synthetic target context: P 12.5 d, 1.0% depth,
    on-target imaging. `natives` overrides individual native
    outputs (pass None as a value to DROP that native)."""
    arts = _passing_natives()
    for key, value in (natives or {}).items():
        if value is None:
            arts.pop(key, None)
        else:
            arts[key] = value
    eph = Ephemeris("bulk", PERIOD_D, T0, DURATION_D,
                    source="filed")
    return TargetContext(
        tic="238620464", ephemeris=eph, artifacts=arts,
        provenance=dict(PROV),
        imaging=dict(imaging) if imaging is not None else None,
        bulk_survivor=bulk_survivor)


def _by_stage(run):
    return {r.stage: r for r in run.results}


class TestRunnerEndToEnd(unittest.TestCase):
    def test_1_all_pass_is_candidate(self):
        run = run_gauntlet(_target())
        self.assertEqual(run.final_verdict, "CANDIDATE")
        self.assertEqual(run.skipped, [])
        self.assertEqual([r.stage for r in run.results],
                         list(REQUIRED_STAGES))
        self.assertTrue(all(r.status == "pass"
                            for r in run.results))
        self.assertTrue(all(r.execution_status == "completed"
                            for r in run.results))

    def test_2_missing_prerequisite_skips_and_blocks(self):
        # persistence.native dropped: persistence is skipped
        # (unmeasured, execution skipped) and the verdict is
        # INCONCLUSIVE — every other stage still ran.
        run = run_gauntlet(
            _target(natives={"persistence.native": None}))
        self.assertEqual(run.final_verdict, "INCONCLUSIVE")
        by_stage = _by_stage(run)
        self.assertEqual(by_stage["persistence"].status,
                         "unmeasured")
        self.assertEqual(by_stage["persistence"].execution_status,
                         "skipped")
        self.assertIn("persistence",
                      [s for s, _r in run.skipped])
        self.assertEqual(by_stage["shape"].status, "pass")
        self.assertEqual(by_stage["transit_fit"].status, "pass")

    def test_3_unmeasured_blocks_promotion(self):
        # holdout RAN but could not measure (too few folds):
        # unmeasured with execution completed — still blocks.
        run = run_gauntlet(_target(
            natives={"holdout.native": "HOLDOUT-INSUFFICIENT-DATA"}))
        self.assertEqual(run.final_verdict, "INCONCLUSIVE")
        by_stage = _by_stage(run)
        self.assertEqual(by_stage["holdout"].status, "unmeasured")
        self.assertEqual(by_stage["holdout"].execution_status,
                         "completed")
        self.assertIn("holdout", run.verdict_note)

    def test_4a_raw_flux_fail_short_circuits_expensive(self):
        # raw_flux FAIL (no dip in the raw flux): the expensive
        # stages never start, the cheap stages still run, the
        # verdict is REFUTED.
        run = run_gauntlet(_target(natives={
            "raw_flux.native": {"depth_pct": 0.05,
                                "signif_white": 0.4,
                                "n_in": 42, "n_events": 13}}))
        self.assertEqual(run.final_verdict, "REFUTED")
        by_stage = _by_stage(run)
        self.assertEqual(by_stage["raw_flux"].status, "fail")
        for stage in ("holdout", "diffimg", "transit_fit"):
            self.assertEqual(by_stage[stage].status, "unmeasured")
            self.assertEqual(by_stage[stage].execution_status,
                             "not_started")
        for stage in ("persistence", "shape", "odd_even",
                      "blend", "pixel_check"):
            self.assertEqual(by_stage[stage].execution_status,
                             "completed")

    def test_4b_shape_fail_short_circuits_transit_fit(self):
        # shape FAIL (V-shaped): transit_fit — expensive, and
        # requiring shape — never starts; the verdict is EB.
        run = run_gauntlet(_target(natives={
            "shape.native": {"shape_verdict": "V-shaped",
                             "T23_T14": 0.15,
                             "density_flag": False}}))
        self.assertEqual(run.final_verdict, "EB")
        by_stage = _by_stage(run)
        self.assertEqual(by_stage["shape"].status, "fail")
        self.assertEqual(by_stage["transit_fit"].status,
                         "unmeasured")
        self.assertEqual(by_stage["transit_fit"].execution_status,
                         "not_started")

    def test_4c_blend_fail_is_blend(self):
        # The neighbouring contaminant carries the signal (22%
        # neighbour dip at the same ephemeris): BLEND.
        run = run_gauntlet(_target(natives={
            "blend.native": _blend_native(neighbour_depth=22.0)}))
        self.assertEqual(run.final_verdict, "BLEND")
        by_stage = _by_stage(run)
        self.assertEqual(by_stage["blend"].status, "fail")
        self.assertIn("photocopy", by_stage["blend"].reason)
        self.assertEqual(by_stage["blend"].details["neighbour_tic"],
                         "238620465")

    def test_5_not_applicable_blocks_unless_waived(self):
        # A deep-pipeline target (not a bulk survivor) has no
        # clean-data gate: clean_refold is not_applicable and
        # blocks — until the policy waives it with a reason.
        run = run_gauntlet(_target(bulk_survivor=False))
        self.assertEqual(run.final_verdict, "INCONCLUSIVE")
        self.assertEqual(_by_stage(run)["clean_refold"].status,
                         "not_applicable")
        run = run_gauntlet(
            _target(bulk_survivor=False),
            waivers={"clean_refold":
                     "deep-pipeline target, no bulk gate"})
        self.assertEqual(run.final_verdict, "CANDIDATE")
        self.assertEqual(
            _by_stage(run)["clean_refold"].waiver_reason,
            "deep-pipeline target, no bulk gate")

    def test_6_exception_is_unmeasured_error(self):
        # A stage that raises is unmeasured with an error
        # execution status — never a scientific FAIL, never a
        # run kill: the other stages still run and the verdict
        # is INCONCLUSIVE (unmeasured blocks).
        def _boom(_ctx):
            raise RuntimeError("tool crashed: OOM")
        register_stage(StageSpec(
            "boom_stage", produces=("boom_stage",), func=_boom,
            mandatory=False))
        self.addCleanup(STAGE_REGISTRY.pop, "boom_stage", None)
        stages = list(REQUIRED_STAGES) + ["boom_stage"]
        run = run_gauntlet(_target(), stages=stages)
        by_stage = _by_stage(run)
        self.assertEqual(by_stage["boom_stage"].status,
                         "unmeasured")
        self.assertEqual(by_stage["boom_stage"].execution_status,
                         "error")
        self.assertIn("OOM", by_stage["boom_stage"].reason)
        self.assertEqual(run.final_verdict, "INCONCLUSIVE")
        self.assertEqual(by_stage["shape"].status, "pass")

    def test_7_repeated_execution_is_identical(self):
        run1 = run_gauntlet(_target())
        run2 = run_gauntlet(_target())
        self.assertEqual(run1.final_verdict, run2.final_verdict)
        sig = lambda run: [(r.stage, r.status,
                            r.execution_status, r.reason)
                           for r in run.results]
        self.assertEqual(sig(run1), sig(run2))
        # The waived path is deterministic too.
        run3 = run_gauntlet(
            _target(bulk_survivor=False),
            waivers={"clean_refold":
                     "deep-pipeline target, no bulk gate"})
        run4 = run_gauntlet(
            _target(bulk_survivor=False),
            waivers={"clean_refold":
                     "deep-pipeline target, no bulk gate"})
        self.assertEqual(sig(run3), sig(run4))
        self.assertEqual(run3.final_verdict, "CANDIDATE")


if __name__ == "__main__":
    unittest.main()
