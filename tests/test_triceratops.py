"""TRICERATOPS adapter + wrapper tests (Phase 2, 2C-1).

Two layers, both driven without the real tool:

* The ADAPTER (gauntlet/stage_result.py:triceratops_result)
  maps canned TRICERATOPS output JSONs onto StageResults
  using the POLICY bars (a small test policy here; one test
  proves the default policy loads from external_tools_v2).
  PASS needs FPP and NFPP both under the validation bars;
  FAIL needs FPP over the refute bar; the grey zone (and a
  low FPP blocked by a high NFPP) is INCONCLUSIVE. A
  DEGENERATE computation (FPP=1.0 from a failed MC) is
  UNMEASURED, never a fail.
* The WRAPPER (gauntlet/tools/run_triceratops.py) is run
  for real against a FAKE triceratops package: a minimal
  `triceratops` package on PYTHONPATH whose `target` class
  mimics the real API (target/calc_depths/calc_probs) and
  records its arguments + one random draw, so the tests can
  prove the phase fold, the seeding (same seed -> same
  draw), the dilution flag, and the failure modes.

The real tool is never imported or installed here.
"""
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gauntlet.external_tool import (  # noqa: E402
    ToolConfig, build_tool_input, run_external_tool)
from gauntlet.stage_result import (  # noqa: E402
    triceratops_disposition, triceratops_result)
from validation import (  # noqa: E402
    RecordValidationError, validate_stage_result,
    validate_triceratops_output,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
WRAPPER = str(REPO_ROOT / "gauntlet" / "tools"
              / "run_triceratops.py")

_POLICY = {"triceratops": {"fpp_validate_max": 0.015,
                           "nfpp_validate_max": 0.001,
                           "fpp_refute_min": 0.5}}


def _metrics(**over):
    m = {"fpp": 0.0032, "nfpp": 0.0008, "prob_planet": 0.9968,
         "prob_eb_target": 0.0021, "prob_eb_neighbour": 0.0009,
         "prob_hierarchical_eb": 0.0002, "n_samples": 1000000,
         "most_likely_false_positive": "EB on TIC 423498314",
         "fpp_degenerate": False, "dilution_corrected": False,
         "contrast_curve_used": False,
         "n_fold_points": 1234}
    m.update(over)
    return m


def _output(**overrides):
    out = {
        "tool": "triceratops",
        "tool_version": "1.1.0",
        "seed": 20261114,
        "config_hash": "c" * 64,
        "status": "completed",
        "value": 0.0032,
        "metrics": _metrics(),
        "input_hashes": {"lightcurve": "a" * 64,
                         "neighbours": "b" * 64},
        "artifacts": ["/tmp/work/triceratops_probs.csv"],
        "warnings": ["no contrast curve: NFPP is an upper "
                     "bound"],
        "wall_time_s": 412.5,
        "n_transits": 42,
    }
    out.update(overrides)
    return out


def _failed_metrics():
    return {"fpp": None, "nfpp": None, "prob_planet": None,
            "prob_eb_target": None, "prob_eb_neighbour": None,
            "prob_hierarchical_eb": None, "n_samples": 0,
            "most_likely_false_positive": None,
            "fpp_degenerate": False,
            "dilution_corrected": False,
            "contrast_curve_used": False,
            "n_fold_points": None}


class TestTriceratopsResult(unittest.TestCase):

    def test_planet_passes(self):
        res = triceratops_result(_output(), policy=_POLICY)
        self.assertEqual(res.stage, "triceratops")
        self.assertEqual(res.status, "pass")
        self.assertEqual(res.value, 0.0032)
        self.assertEqual(res.threshold, 0.015)
        self.assertIsNone(res.uncertainty)
        self.assertEqual(res.metrics["nfpp"], 0.0008)
        self.assertEqual(res.metrics["prob_eb_target"], 0.0021)
        self.assertEqual(res.metrics["n_samples"], 1000000)
        self.assertEqual(res.metrics["n_fold_points"], 1234)
        self.assertEqual(res.metrics["seed"], 20261114)
        self.assertEqual(res.metrics["most_likely_false_positive"],
                         "EB on TIC 423498314")
        self.assertEqual(res.tool_version, "1.1.0")
        self.assertEqual(res.n_transits, 42)
        self.assertIn("upper bound", res.reason)

    def test_eb_fails(self):
        res = triceratops_result(
            _output(value=0.87,
                    metrics=_metrics(
                        fpp=0.87, nfpp=0.001,
                        prob_planet=0.13,
                        prob_eb_target=0.80,
                        most_likely_false_positive=(
                            "EB on TIC 308851365"))),
            policy=_POLICY)
        self.assertEqual(res.status, "fail")
        self.assertIn("refute bar", res.reason)

    def test_grey_zone_is_inconclusive(self):
        res = triceratops_result(
            _output(value=0.05,
                    metrics=_metrics(
                        fpp=0.05, nfpp=0.0005,
                        prob_planet=0.95)),
            policy=_POLICY)
        self.assertEqual(res.status, "inconclusive")
        self.assertIn("grey zone", res.reason)

    def test_low_fpp_high_nfpp_is_inconclusive(self):
        # NFPP alone never refutes in v1 (without a contrast
        # curve it is an upper bound) — but it blocks
        # validation.
        res = triceratops_result(
            _output(value=0.004,
                    metrics=_metrics(
                        fpp=0.004, nfpp=0.02,
                        prob_planet=0.996)),
            policy=_POLICY)
        self.assertEqual(res.status, "inconclusive")

    def test_degenerate_is_unmeasured_not_fail(self):
        # The critical case: a degenerate computation reports
        # FPP=1.0 for a FAILED computation, not a confident
        # false positive. It must never read FAIL.
        res = triceratops_result(
            _output(value=1.0,
                    metrics=_metrics(
                        fpp=1.0, nfpp=0.0, prob_planet=0.0,
                        fpp_degenerate=True)),
            policy=_POLICY)
        self.assertEqual(res.status, "unmeasured")
        self.assertEqual(res.execution_status, "error")
        self.assertIn("degenerate", res.reason)

    def test_failed_is_unmeasured_error(self):
        res = triceratops_result(
            _output(status="failed", value=None,
                    metrics=_failed_metrics(), artifacts=[]),
            policy=_POLICY)
        self.assertEqual(res.status, "unmeasured")
        self.assertEqual(res.execution_status, "error")

    def test_timeout_is_unmeasured_error(self):
        res = triceratops_result(
            _output(status="timeout", value=None,
                    metrics=_failed_metrics(), artifacts=[]),
            policy=_POLICY)
        self.assertEqual(res.status, "unmeasured")
        self.assertEqual(res.execution_status, "error")

    def test_malformed_output_is_unmeasured(self):
        bad = _output()
        del bad["seed"]
        res = triceratops_result(bad, policy=_POLICY)
        self.assertEqual(res.status, "unmeasured")
        self.assertEqual(res.execution_status, "error")

    def test_no_native_is_unmeasured(self):
        res = triceratops_result(None, policy=_POLICY)
        self.assertEqual(res.status, "unmeasured")

    def test_schema_validation_direct(self):
        validate_triceratops_output(_output())
        bad = _output(status="exploded")
        with self.assertRaises(RecordValidationError):
            validate_triceratops_output(bad)

    def test_default_policy_loads(self):
        # policy=None loads the real external_tools_v2
        # profile (registry-verified): the planet output
        # passes under the ratified bars (P3-9: the default
        # policy moved v1 -> v2; the bars are unchanged).
        res = triceratops_result(_output())
        self.assertEqual(res.status, "pass")
        self.assertEqual(res.threshold, 0.015)

    def test_policy_version_recorded(self):
        # P-4: the result names the policy that produced its
        # disposition — the raw numbers are policy-free, so a
        # policy-only edit re-derives the disposition without
        # re-running the tool.
        res = triceratops_result(_output())
        self.assertEqual(res.policy_version, "external_tools_v2")
        self.assertEqual(res.to_dict()["policy_version"],
                         "external_tools_v2")
        # The new field passes the stage-result schema
        # (additionalProperties: false would reject an
        # undeclared field).
        validate_stage_result(res.to_dict())
        # An explicit policy's version is recorded verbatim.
        pol = dict(_POLICY, version="external_tools_v9")
        res = triceratops_result(_output(), policy=pol)
        self.assertEqual(res.policy_version, "external_tools_v9")

    def test_disposition_is_pure_policy_mapping(self):
        # P-4: the same raw numbers read differently under a
        # different policy — the disposition is a reading of
        # the evidence, not the evidence itself. FPP 0.01
        # passes under the default bars (0.015) but is
        # inconclusive under a stricter policy (0.005).
        status, _reason = triceratops_disposition(
            0.01, 0.0008, False, {"version": "external_tools_v2",
                                  "triceratops": {
                                      "fpp_validate_max": 0.015,
                                      "nfpp_validate_max": 0.001,
                                      "fpp_refute_min": 0.5}})
        self.assertEqual(status, "pass")
        status, _reason = triceratops_disposition(
            0.01, 0.0008, False, {"version": "external_tools_v9",
                                  "triceratops": {
                                      "fpp_validate_max": 0.005,
                                      "nfpp_validate_max": 0.001,
                                      "fpp_refute_min": 0.5}})
        self.assertEqual(status, "inconclusive")

    def test_disposition_nan_is_inconclusive(self):
        # P-4: a NaN FPP fails both policy comparisons — it
        # is not a pass and not a refutation.
        status, reason = triceratops_disposition(
            float("nan"), 0.0008, False,
            {"version": "external_tools_v1",
             "triceratops": _POLICY["triceratops"]})
        self.assertEqual(status, "inconclusive")
        self.assertIn("grey zone", reason)

    def test_disposition_degenerate_is_unmeasured(self):
        status, reason = triceratops_disposition(
            1.0, 0.5, True,
            {"version": "external_tools_v1",
             "triceratops": _POLICY["triceratops"]})
        self.assertEqual(status, "unmeasured")
        self.assertIn("degenerate", reason)


FAKE_TRI = textwrap.dedent("""\
    import json, os, socket, time
    import numpy as np
    import pandas as pd

    def _obs(**kw):
        path = os.environ.get("FAKE_TRI_OBS")
        if not path:
            return
        data = {}
        if os.path.exists(path):
            data = json.load(open(path))
        data.update(kw)
        json.dump(data, open(path, "w"))

    class target:
        def __init__(self, ID, sectors, search_radius=10,
                     **kw):
            _obs(ID=int(ID), sectors=[int(s) for s in sectors],
                 search_radius=int(search_radius),
                 trilegal_fname=kw.get("trilegal_fname"),
                 socket_timeout=socket.getdefaulttimeout())
            behaviour = os.environ.get(
                "FAKE_TRI_BEHAVIOUR", "planet")
            if behaviour == "hang_init":
                time.sleep(5)
            if behaviour == "flaky_init":
                state_path = os.path.join(
                    os.path.dirname(
                        os.environ.get("FAKE_TRI_OBS", "")),
                    "init_attempts.txt")
                count = 0
                if os.path.exists(state_path):
                    count = int(open(state_path).read())
                count += 1
                open(state_path, "w").write(str(count))
                failures = int(os.environ.get(
                    "FAKE_TRI_INIT_FAILURES", "0"))
                if count <= failures:
                    raise ConnectionError(
                        "simulated MAST stall")
            # P4-8: the fake "builds" one image per requested
            # sector by default; the drop behaviours model
            # the real tool silently dropping sectors
            # (triceratops.py ~242: per-sector try/except
            # prints and continues, so a stalled fetch
            # returns fewer images than requested sectors).
            self.TESS_images = [None] * len(sectors)
            if behaviour == "drop_one":
                # A silent sector drop with no hang and no
                # timeout: the completeness check alone must
                # catch it.
                self.TESS_images = self.TESS_images[:-1]
            if behaviour == "swallow_drop":
                # The P4-8 swallowing fake: a slow fetch
                # inside the tool's per-sector try/except —
                # the phase alarm (or any exception) is
                # swallowed, the sector is dropped, and the
                # tool returns with fewer images than
                # requested sectors.
                try:
                    time.sleep(float(os.environ.get(
                        "FAKE_TRI_SLOW_FETCH_S", "120")))
                except Exception:
                    pass
                self.TESS_images = self.TESS_images[:-1]
            if behaviour == "write_gaia_csv":
                # The tool writes <tic>_gaia_background.csv
                # to its cwd on a live Gaia query
                # (funcs.py:840) — P4-8 expects it in the
                # run workdir, never the repo root.
                with open(f"{ID}_gaia_background.csv",
                          "w") as fh:
                    fh.write("ID,Tmag\\n%d,13.45\\n" % ID)
            self.ID = ID
            self.sectors = sectors
            self.FPP_degenerate = False
            # PM-1: the real tool sets trilegal_missing when
            # the background query fails; the fake models it
            # via behaviour so the wrapper's fail-closed
            # check can be tested without the real tool.
            self.trilegal_missing = (
                behaviour == "trilegal_missing")

        def calc_depths(self, tdepth, all_ap_pixels=None,
                        dilution_corrected=True):
            _obs(tdepth=float(tdepth),
                 dilution_corrected=bool(dilution_corrected))

        def calc_probs(self, time, flux_0, flux_err_0, P_orb,
                       contrast_curve_file=None, filt="TESS",
                       N=1000000, parallel=False,
                       drop_scenario=[], verbose=1,
                       flatpriors=False, exptime=0.00139,
                       nsamples=20, molusc_file=None,
                       dilution_corrected=True):
            _obs(P_orb=float(P_orb), N=int(N),
                 exptime=float(exptime), nsamples=int(nsamples),
                 verbose=int(verbose),
                 contrast_curve_file=contrast_curve_file,
                 dilution_corrected_calc=bool(dilution_corrected),
                 flux_err=float(flux_err_0),
                 time_min=float(np.min(time)),
                 time_max=float(np.max(time)),
                 n_points=int(len(time)),
                 random_draw=float(np.random.rand()))
            behaviour = os.environ.get(
                "FAKE_TRI_BEHAVIOUR", "planet")
            if behaviour == "crash":
                raise RuntimeError("boom: the MC exploded")
            if behaviour == "degenerate":
                self.FPP = 1.0
                self.NFPP = 0.0
                self.FPP_degenerate = True
                self.probs = pd.DataFrame({
                    "ID": [423498314, 423498314],
                    "scenario": ["TP", "EB"],
                    "prob": [0.0, 0.0]})
                return
            if behaviour == "eb":
                self.FPP = 0.87
                self.NFPP = 0.001
                self.probs = pd.DataFrame({
                    "ID": [423498314, 423498314, 423498315,
                           423498314, 423498315, 423498315,
                           423498315, 423498315, 423498315],
                    "scenario": ["TP", "EB", "BEB", "SEB",
                                 "DTP", "DEB", "DEBx2P", "BTP",
                                 "BEBx2P"],
                    "prob": [0.13, 0.80, 0.05, 0.02, 0.0, 0.0,
                             0.0, 0.0, 0.0]})
                return
            if behaviour == "skipped_background":
                # PM-1: the table the tool produces when the
                # background population was silently skipped
                # — 5 of the 6 background scenarios are
                # absent (BEB is present, to prove the check
                # is per-scenario, not all-or-nothing).
                self.FPP = 0.0032
                self.NFPP = 0.0009
                self.probs = pd.DataFrame({
                    "ID": [423498314, 423498314, 423498315,
                           423498314],
                    "scenario": ["TP", "EB", "BEB", "PEB"],
                    "prob": [0.9968, 0.0021, 0.0009, 0.0002]})
                return
            self.FPP = 0.0032
            self.NFPP = 0.0009
            # PM-1: the table carries all 6 background
            # scenarios (DTP, DEB, DEBx2P, BTP, BEB,
            # BEBx2P) — the real tool's table does when the
            # background population is present. The new rows
            # carry prob 0.0 so the existing metric
            # assertions (prob_eb_neighbour 0.0009 etc.) are
            # unchanged.
            self.probs = pd.DataFrame({
                "ID": [423498314, 423498314, 423498315,
                       423498314, 423498315, 423498315,
                       423498315, 423498315, 423498315],
                "scenario": ["TP", "EB", "BEB", "PEB", "DTP",
                             "DEB", "DEBx2P", "BTP", "BEBx2P"],
                "prob": [0.9968, 0.0021, 0.0009, 0.0002, 0.0,
                         0.0, 0.0, 0.0, 0.0]})
    """)


def _input_dict(tmp, dilution_corrected=False, sectors=None):
    rng = np.random.default_rng(7)
    t = 1500.0 + np.arange(0, 27.0, 10.0 / 1440.0)
    ph = ((t - 1500.5 + 0.5 * 3.9227) % 3.9227) - 0.5 * 3.9227
    f = np.ones_like(t)
    f[np.abs(ph) <= 0.105 / 2] -= 0.01
    f = f * (1.0 + rng.normal(0, 0.0005, len(t)))
    lc_path = str(Path(tmp) / "lc.npz")
    np.savez(lc_path, time=t, flux=f)
    import hashlib
    lc_hash = hashlib.sha256(
        open(lc_path, "rb").read()).hexdigest()
    inp = build_tool_input(
        "triceratops", "1.1.0", 20261114, "c" * 64,
        {"tic": "423498314", "ra_deg": 123.456,
         "dec_deg": -63.789, "tmag": 13.45,
         "star_radius_rsun": 0.673, "star_mass_msun": 0.61,
         "teff_k": 4400},
        {"period_d": 3.9227, "t0_bjd": 1500.5,
         "duration_h": 2.52, "depth_frac": 0.01,
         "n_transits": 7},
        {"path": lc_path, "input_hash": lc_hash,
         "sectors": sectors if sectors is not None else [96],
         "cadence_s": 600.0},
        {"path": "/tmp/census.json", "input_hash": "b" * 64,
         "radius_arcsec": 180.0})
    inp["dilution_corrected"] = dilution_corrected
    return inp


class TestRunTriceratopsWrapper(unittest.TestCase):

    def _fake_tri(self, tmp):
        fakevenv = Path(tmp) / "fakevenv"
        pkg = fakevenv / "triceratops"
        pkg.mkdir(parents=True)
        (pkg / "__init__.py").write_text("")
        (pkg / "triceratops.py").write_text(FAKE_TRI)
        return str(fakevenv)

    def _run_wrapper(self, tmp, fakevenv, inp,
                     behaviour="planet", cwd=None,
                     extra_env=None):
        work = Path(tmp) / "work"
        work.mkdir(exist_ok=True)
        input_path = work / "input.json"
        output_path = work / "output.json"
        input_path.write_text(json.dumps(inp))
        obs_path = str(Path(tmp) / "obs.json")
        env = dict(os.environ)
        env["PYTHONPATH"] = fakevenv + os.pathsep + env.get(
            "PYTHONPATH", "")
        env["FAKE_TRI_OBS"] = obs_path
        env["FAKE_TRI_BEHAVIOUR"] = behaviour
        if extra_env:
            env.update(extra_env)
        proc = subprocess.run(
            [sys.executable, WRAPPER, "--input", str(input_path),
             "--output", str(output_path)],
            capture_output=True, text=True, env=env, timeout=120,
            cwd=cwd)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = json.loads(output_path.read_text())
        obs = (json.loads(Path(obs_path).read_text())
               if os.path.exists(obs_path) else {})
        return work, out, obs

    def test_success_planet(self):
        with tempfile.TemporaryDirectory() as tmp:
            fakevenv = self._fake_tri(tmp)
            inp = _input_dict(tmp)
            work, out, obs = self._run_wrapper(
                tmp, fakevenv, inp)
            self.assertEqual(out["status"], "completed")
            self.assertEqual(out["value"], 0.0032)
            self.assertEqual(out["seed"], 20261114)
            # triceratops is not installed here: the wrapper
            # falls back to the input's version + a warning.
            self.assertEqual(out["tool_version"], "1.1.0")
            self.assertTrue(any("could not read" in w
                                for w in out["warnings"]))
            self.assertTrue(any("upper bound" in w
                                for w in out["warnings"]))
            m = out["metrics"]
            self.assertEqual(m["fpp"], 0.0032)
            self.assertEqual(m["nfpp"], 0.0009)
            self.assertAlmostEqual(m["prob_planet"], 0.9968)
            self.assertEqual(m["prob_eb_target"], 0.0021)
            self.assertEqual(m["prob_eb_neighbour"], 0.0009)
            self.assertEqual(m["prob_hierarchical_eb"], 0.0002)
            self.assertEqual(m["n_samples"], 1000000)
            self.assertEqual(m["most_likely_false_positive"],
                             "EB on TIC 423498314")
            self.assertFalse(m["fpp_degenerate"])
            # PM-1: the background-scenario check ran and
            # passed (all 6 background scenarios present).
            self.assertTrue(m["background_scenarios_checked"])
            self.assertFalse(m["dilution_corrected"])
            self.assertFalse(m["contrast_curve_used"])
            self.assertEqual(out["n_transits"], 7)
            # The scenario table was saved as an artifact.
            csv_path = Path(out["artifacts"][0])
            self.assertTrue(csv_path.exists())
            self.assertEqual(csv_path.parent, work)
            validate_triceratops_output(out)
            # The tool was called with the right arguments.
            self.assertEqual(obs["ID"], 423498314)
            self.assertEqual(obs["sectors"], [96])
            self.assertEqual(obs["search_radius"], 10)
            self.assertEqual(obs["tdepth"], 0.01)
            self.assertEqual(obs["P_orb"], 3.9227)
            self.assertEqual(obs["N"], 1000000)
            self.assertAlmostEqual(obs["exptime"],
                                   600.0 / 86400.0)
            self.assertIsNone(obs["contrast_curve_file"])
            self.assertFalse(obs["dilution_corrected"])
            self.assertFalse(obs["dilution_corrected_calc"])
            self.assertGreater(obs["flux_err"], 0.0)
            # P-15 (TEST CHANGE, stated): the fold is BINNED
            # before calc_probs — ~200 bins in a ±3-duration
            # window, not the full 3888-cadence curve. The
            # old assertions (span [-P/2, P/2], >1000 points)
            # described the unbinned behaviour and are
            # replaced by the binned ones below.
            z = np.load(inp["lightcurve"]["path"])
            ph_in = ((z["time"] - 1500.5 + 0.5 * 3.9227)
                     % 3.9227) - 0.5 * 3.9227
            expected_n = int(
                (np.abs(ph_in) <= 3 * 0.105).sum())
            self.assertEqual(m["n_fold_points"], expected_n)
            self.assertGreater(m["n_fold_points"], 100)
            self.assertLessEqual(obs["n_points"], 200)
            self.assertGreaterEqual(obs["n_points"], 100)
            self.assertGreaterEqual(obs["time_min"], -3 * 0.105)
            self.assertLessEqual(obs["time_max"], 3 * 0.105)

    def test_same_seed_reproduces(self):
        # Seeded determinism: the same input + seed gives the
        # same MC draw (and the same FPP) twice.
        with tempfile.TemporaryDirectory() as tmp:
            fakevenv = self._fake_tri(tmp)
            _w1, out1, obs1 = self._run_wrapper(
                tmp, fakevenv, _input_dict(tmp))
            tmp2 = Path(tmp) / "run2"
            tmp2.mkdir()
            _w2, out2, obs2 = self._run_wrapper(
                str(tmp2), fakevenv, _input_dict(str(tmp2)))
            self.assertEqual(obs1["random_draw"],
                             obs2["random_draw"])
            self.assertEqual(out1["value"], out2["value"])

    def test_degenerate_flag_carried(self):
        with tempfile.TemporaryDirectory() as tmp:
            fakevenv = self._fake_tri(tmp)
            _w, out, _obs = self._run_wrapper(
                tmp, fakevenv, _input_dict(tmp),
                behaviour="degenerate")
            self.assertEqual(out["status"], "completed")
            self.assertTrue(out["metrics"]["fpp_degenerate"])
            self.assertTrue(any("degenerate" in w
                                for w in out["warnings"]))
            # PM-1: the background check is skipped for a
            # degenerate computation (its table is
            # meaningless) — the flag stays False.
            self.assertFalse(
                out["metrics"]["background_scenarios_checked"])
            # And the adapter maps it to unmeasured, not fail.
            res = triceratops_result(out, policy=_POLICY)
            self.assertEqual(res.status, "unmeasured")

    def test_crash_is_failed(self):
        with tempfile.TemporaryDirectory() as tmp:
            fakevenv = self._fake_tri(tmp)
            _w, out, _obs = self._run_wrapper(
                tmp, fakevenv, _input_dict(tmp),
                behaviour="crash")
            self.assertEqual(out["status"], "failed")
            self.assertIsNone(out["value"])
            self.assertIsNone(out["metrics"]["fpp"])
            self.assertEqual(out["metrics"]["n_samples"], 0)
            self.assertTrue(any("boom" in w
                                for w in out["warnings"]))
            validate_triceratops_output(out)

    def test_dilution_flag_passes_through(self):
        with tempfile.TemporaryDirectory() as tmp:
            fakevenv = self._fake_tri(tmp)
            _w, out, obs = self._run_wrapper(
                tmp, fakevenv,
                _input_dict(tmp, dilution_corrected=True))
            self.assertEqual(out["status"], "completed")
            self.assertTrue(out["metrics"]["dilution_corrected"])
            self.assertTrue(obs["dilution_corrected"])
            self.assertTrue(obs["dilution_corrected_calc"])

    def test_triceratops_not_importable_is_failed(self):
        with tempfile.TemporaryDirectory() as tmp:
            empty = Path(tmp) / "empty"
            empty.mkdir()
            _w, out, _obs = self._run_wrapper(
                tmp, str(empty), _input_dict(tmp))
            self.assertEqual(out["status"], "failed")
            self.assertTrue(any("not importable" in w
                                for w in out["warnings"]))

    def test_hang_init_fails_fast_with_phase_named(self):
        # 2026-11-16: a stalled target build must fail fast
        # and name its phase — not burn the runner's cap in
        # silence. The fake hangs 5 s per attempt; the 1 s
        # phase budget fires twice and the wrapper gives up.
        with tempfile.TemporaryDirectory() as tmp:
            fakevenv = self._fake_tri(tmp)
            _w, out, _obs = self._run_wrapper(
                tmp, fakevenv, _input_dict(tmp),
                behaviour="hang_init",
                extra_env={"TRICERATOPS_INIT_TIMEOUT_S": "1",
                           "TRICERATOPS_INIT_ATTEMPTS": "2"})
            self.assertEqual(out["status"], "failed")
            self.assertTrue(any("target_init" in w
                                for w in out["warnings"]))
            self.assertTrue(any("2 attempt" in w
                                for w in out["warnings"]))
            self.assertLess(out["wall_time_s"], 20)
            validate_triceratops_output(out)
            log = Path(tmp) / "work" / "phase_log.txt"
            self.assertTrue(log.exists())
            self.assertIn("TIMED OUT", log.read_text())

    def test_flaky_init_retries_and_completes(self):
        # One stalled attempt, then success: the retry
        # recovers the target instead of failing the run.
        with tempfile.TemporaryDirectory() as tmp:
            fakevenv = self._fake_tri(tmp)
            _w, out, _obs = self._run_wrapper(
                tmp, fakevenv, _input_dict(tmp),
                behaviour="flaky_init",
                extra_env={"FAKE_TRI_INIT_FAILURES": "1"})
            self.assertEqual(out["status"], "completed")
            self.assertEqual(out["value"], 0.0032)
            log = Path(tmp) / "work" / "phase_log.txt"
            text = log.read_text()
            self.assertIn("attempt 1 network error", text)
            self.assertIn("attempt 2 done", text)

    def test_cached_gaia_population_passed(self):
        # A Gaia CSV the tool itself wrote for this target
        # is passed as trilegal_fname, so a retry skips the
        # live Gaia query with identical data. P4-8 (TEST
        # CHANGE, stated): the cache lives in the run
        # workdir — the wrapper runs the tool phases there,
        # so a CSV in the workdir is found. The old
        # placement (a CSV in the caller's cwd) no longer
        # models anything the wrapper does.
        with tempfile.TemporaryDirectory() as tmp:
            fakevenv = self._fake_tri(tmp)
            work = Path(tmp) / "work"
            work.mkdir(exist_ok=True)
            csv_path = (work
                        / "423498314_gaia_background.csv")
            csv_path.write_text("ID,Tmag\n423498314,13.45\n")
            _w, out, obs = self._run_wrapper(
                tmp, fakevenv, _input_dict(tmp), cwd=tmp)
            self.assertEqual(out["status"], "completed")
            self.assertEqual(obs["trilegal_fname"],
                             str(csv_path))

    def test_phase_seconds_and_socket_timeout_recorded(self):
        with tempfile.TemporaryDirectory() as tmp:
            fakevenv = self._fake_tri(tmp)
            _w, out, obs = self._run_wrapper(
                tmp, fakevenv, _input_dict(tmp),
                extra_env={"TRICERATOPS_SOCKET_TIMEOUT_S": "42"})
            self.assertEqual(out["status"], "completed")
            self.assertEqual(obs["socket_timeout"], 42)
            phases = out["metrics"]["phase_seconds"]
            self.assertEqual(set(phases),
                             {"target_init", "calc_depths",
                              "calc_probs"})
            self.assertTrue(all(v >= 0 for v in phases.values()))
            validate_triceratops_output(out)
            log = Path(tmp) / "work" / "phase_log.txt"
            self.assertIn("target_init attempt 1 done",
                          log.read_text())
            self.assertIn(str(log), out["artifacts"])

    def test_trilegal_missing_fails_fast(self):
        # PM-1: a silently skipped background population
        # fails the run before calc_probs — never an FPP
        # computed without the background scenarios.
        with tempfile.TemporaryDirectory() as tmp:
            fakevenv = self._fake_tri(tmp)
            _w, out, obs = self._run_wrapper(
                tmp, fakevenv, _input_dict(tmp),
                behaviour="trilegal_missing")
            self.assertEqual(out["status"], "failed")
            self.assertIsNone(out["value"])
            self.assertTrue(any("trilegal_missing" in w
                                for w in out["warnings"]))
            self.assertFalse(
                out["metrics"]["background_scenarios_checked"])
            # calc_probs never ran: no random draw recorded.
            self.assertNotIn("random_draw", obs)
            validate_triceratops_output(out)

    def test_missing_background_scenarios_fail_closed(self):
        # PM-1: a probability table missing background
        # scenarios fails the run and names the missing
        # ones (here 5 of 6 are absent; BEB is present).
        with tempfile.TemporaryDirectory() as tmp:
            fakevenv = self._fake_tri(tmp)
            _w, out, _obs = self._run_wrapper(
                tmp, fakevenv, _input_dict(tmp),
                behaviour="skipped_background")
            self.assertEqual(out["status"], "failed")
            self.assertIsNone(out["value"])
            self.assertTrue(any("DTP" in w and "DEB" in w
                                for w in out["warnings"]))
            self.assertFalse(
                out["metrics"]["background_scenarios_checked"])
            validate_triceratops_output(out)

    def test_drop_one_fails_loud_without_timeout(self):
        # P4-8: a silent sector drop with no hang and no
        # timeout — the completeness check alone must catch
        # it. The run fails and names the shortfall; no FPP
        # is reported on the partial sector set.
        with tempfile.TemporaryDirectory() as tmp:
            fakevenv = self._fake_tri(tmp)
            _w, out, _obs = self._run_wrapper(
                tmp, fakevenv, _input_dict(tmp, sectors=[96, 97]),
                behaviour="drop_one")
            self.assertEqual(out["status"], "failed")
            self.assertIsNone(out["value"])
            self.assertTrue(any("dropped sectors" in w
                                for w in out["warnings"]))
            self.assertEqual(
                out["metrics"]["sectors_requested"], 2)
            self.assertEqual(
                out["metrics"]["sectors_built"], 1)
            self.assertFalse(
                out["metrics"]["background_scenarios_checked"])
            validate_triceratops_output(out)
            log = Path(tmp) / "work" / "phase_log.txt"
            self.assertIn("SECTOR DROP", log.read_text())

    def test_swallow_drop_fails_loud_at_init_budget(self):
        # P4-8: the swallowing fake — a 120 s fetch inside
        # the tool's per-sector try/except, with the init
        # budget at 30 s. The alarm fires at 30 s, the fake
        # swallows it and drops the sector, and the wrapper
        # fails loudly on the shortfall — at ~30 s, not at
        # the runner cap and never as a silent completion.
        with tempfile.TemporaryDirectory() as tmp:
            fakevenv = self._fake_tri(tmp)
            _w, out, _obs = self._run_wrapper(
                tmp, fakevenv, _input_dict(tmp, sectors=[96, 97]),
                behaviour="swallow_drop",
                extra_env={"TRICERATOPS_INIT_TIMEOUT_S": "30",
                           "FAKE_TRI_SLOW_FETCH_S": "120"})
            self.assertEqual(out["status"], "failed")
            self.assertIsNone(out["value"])
            self.assertTrue(any("dropped sectors" in w
                                for w in out["warnings"]))
            self.assertEqual(
                out["metrics"]["sectors_requested"], 2)
            self.assertEqual(
                out["metrics"]["sectors_built"], 1)
            self.assertLess(out["wall_time_s"], 90)
            self.assertGreaterEqual(out["wall_time_s"], 25)
            validate_triceratops_output(out)

    def test_gaia_csv_lands_in_workdir(self):
        # P4-8: the Gaia CSV the tool writes on a live query
        # lands in the run workdir, never the caller's cwd
        # (clean worktree — no new files at the repo root).
        with tempfile.TemporaryDirectory() as tmp:
            fakevenv = self._fake_tri(tmp)
            work, out, _obs = self._run_wrapper(
                tmp, fakevenv, _input_dict(tmp),
                behaviour="write_gaia_csv", cwd=tmp)
            self.assertEqual(out["status"], "completed")
            csv_name = "423498314_gaia_background.csv"
            self.assertTrue((work / csv_name).exists())
            self.assertFalse((Path(tmp) / csv_name).exists())

    def test_spawn_context_propagates_config(self):
        # P4-8 (PB-2 acceptance input): the out-of-process
        # runner must propagate the requested config to the
        # worker — a worker silently running under defaults
        # while the record claims the requested config is
        # the PB-2 calibration-drop bug in another form. A
        # non-default seed + config_hash must be echoed
        # verbatim in the output.
        with tempfile.TemporaryDirectory() as tmp:
            fakevenv = self._fake_tri(tmp)
            inp = _input_dict(tmp)
            inp["seed"] = 777
            inp["config_hash"] = "d" * 64
            env = dict(os.environ)
            env["PYTHONPATH"] = (fakevenv + os.pathsep
                                 + env.get("PYTHONPATH", ""))
            env["FAKE_TRI_OBS"] = str(Path(tmp) / "obs.json")
            env["FAKE_TRI_BEHAVIOUR"] = "planet"
            with mock.patch.dict(os.environ, env):
                res = run_external_tool(
                    ToolConfig(tool="triceratops",
                               python=sys.executable,
                               wrapper=WRAPPER, timeout_s=120,
                               memory_mb=0, seed=777,
                               tool_version="1.1.0",
                               config_hash="d" * 64),
                    inp, str(Path(tmp) / "work"))
            self.assertEqual(res.status, "completed")
            self.assertEqual(res.output["seed"], 777)
            self.assertEqual(res.output["config_hash"],
                             "d" * 64)
            self.assertEqual(
                res.output["metrics"]["sectors_requested"], 1)
            self.assertEqual(
                res.output["metrics"]["sectors_built"], 1)

    def test_init_timeout_30_aborts_swallowing_fake(self):
        # P4-8 acceptance (brief): TRICERATOPS_INIT_TIMEOUT_S
        # =30 aborts at 30 s against a swallowing fake. The
        # abort is the wrapper's, not the runner's kill: the
        # runner timeout is a generous 300 s, and the output
        # is a failed run (written by the wrapper at ~30 s),
        # not a runner timeout.
        with tempfile.TemporaryDirectory() as tmp:
            fakevenv = self._fake_tri(tmp)
            inp = _input_dict(tmp, sectors=[96, 97])
            env = dict(os.environ)
            env["PYTHONPATH"] = (fakevenv + os.pathsep
                                 + env.get("PYTHONPATH", ""))
            env["FAKE_TRI_OBS"] = str(Path(tmp) / "obs.json")
            env["FAKE_TRI_BEHAVIOUR"] = "swallow_drop"
            env["FAKE_TRI_SLOW_FETCH_S"] = "120"
            env["TRICERATOPS_INIT_TIMEOUT_S"] = "30"
            with mock.patch.dict(os.environ, env):
                res = run_external_tool(
                    ToolConfig(tool="triceratops",
                               python=sys.executable,
                               wrapper=WRAPPER, timeout_s=300,
                               memory_mb=0, seed=20261114,
                               tool_version="1.1.0",
                               config_hash="c" * 64),
                    inp, str(Path(tmp) / "work"))
            self.assertEqual(res.status, "completed")
            self.assertEqual(res.output["status"], "failed")
            self.assertTrue(any("dropped sectors" in w
                                for w in res.output["warnings"]))
            self.assertEqual(
                res.output["metrics"]["sectors_requested"], 2)
            self.assertEqual(
                res.output["metrics"]["sectors_built"], 1)
            self.assertLess(res.wall_time_s, 90)
            self.assertGreaterEqual(res.wall_time_s, 25)


class TestBinFold(unittest.TestCase):
    """P-15: the phase-fold binning, unit-tested."""

    @classmethod
    def setUpClass(cls):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "run_triceratops", str(WRAPPER))
        cls.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.mod)

    def test_bins_to_about_200_in_window(self):
        rng = np.random.default_rng(3)
        ph = rng.uniform(-1.96, 1.96, 4000)
        f = 1.0 + rng.normal(0, 0.001, 4000)
        centres, fluxes, n = self.mod._bin_fold(
            ph, f, duration_d=0.105)
        # ~16% of the phase range is inside ±3 durations.
        self.assertGreater(n, 400)
        self.assertLess(n, 900)
        self.assertLessEqual(len(centres), 200)
        self.assertGreaterEqual(len(centres), 150)
        self.assertTrue(np.all(np.abs(centres) <= 3 * 0.105))
        # Bins are ordered by phase and the fluxes are
        # medians (finite, near unity).
        self.assertTrue(np.all(np.diff(centres) > 0))
        self.assertTrue(np.all(np.isfinite(fluxes)))
        self.assertTrue(np.all(np.abs(fluxes - 1.0) < 0.01))

    def test_median_flux_resists_outliers(self):
        ph = np.linspace(-0.3, 0.3, 2000)
        f = np.ones_like(ph)
        f[1000] = 100.0  # one wild outlier
        _c, fluxes, _n = self.mod._bin_fold(
            ph, f, duration_d=0.105, n_bins=10)
        self.assertTrue(np.all(np.abs(fluxes - 1.0) < 1e-9))

    def test_empty_window_returns_empty(self):
        ph = np.array([1.0, 1.5, -1.2])
        f = np.ones_like(ph)
        centres, fluxes, n = self.mod._bin_fold(
            ph, f, duration_d=0.105)
        self.assertEqual(n, 0)
        self.assertEqual(len(centres), 0)
        self.assertEqual(len(fluxes), 0)


class TestExternalToolsV2Policy(unittest.TestCase):
    """P3-9: v2 records disposition (A) with the v1 bars
    unchanged — a recording act, not a behaviour change."""

    def test_v2_bars_unchanged_from_v1(self):
        from calibration import load_profile
        v1 = load_profile("external_tools_v1")["triceratops"]
        v2 = load_profile("external_tools_v2")["triceratops"]
        for key in ("fpp_validate_max", "nfpp_validate_max",
                    "fpp_refute_min"):
            self.assertEqual(v2[key], v1[key], key)
        for key in ("tool_version", "venv_python", "wrapper"):
            self.assertEqual(v2[key], v1[key], key)

    def test_v2_records_disposition_a(self):
        from calibration import load_profile
        disp = load_profile(
            "external_tools_v2")["triceratops"]["disposition"]
        self.assertEqual(disp["policy"], "A")
        self.assertEqual(disp["grey_zone"], "inconclusive")
        self.assertIn("validated", disp["grey_zone_never"])
        self.assertIn("likely planet", disp["grey_zone_never"])
        # TB-2: the STP-excluded disposition is NOT adopted
        # in Phase 3.
        self.assertIn("not adopted",
                      disp["stp_excluded_disposition"])

    def test_v2_is_the_default_policy(self):
        from gauntlet.stage_result import (
            EXTERNAL_TOOLS_POLICY_VERSION)
        self.assertEqual(EXTERNAL_TOOLS_POLICY_VERSION,
                         "external_tools_v2")


if __name__ == "__main__":
    unittest.main()
