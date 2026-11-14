"""TRICERATOPS adapter + wrapper tests (Phase 2, 2C-1).

Two layers, both driven without the real tool:

* The ADAPTER (gauntlet/stage_result.py:triceratops_result)
  maps canned TRICERATOPS output JSONs onto StageResults
  using the POLICY bars (a small test policy here; one test
  proves the default policy loads from external_tools_v1).
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

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gauntlet.external_tool import build_tool_input  # noqa: E402
from gauntlet.stage_result import triceratops_result  # noqa: E402
from validation import (  # noqa: E402
    RecordValidationError, validate_triceratops_output,
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
         "contrast_curve_used": False}
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
            "contrast_curve_used": False}


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
        # policy=None loads the real external_tools_v1
        # profile (registry-verified): the planet output
        # passes under the provisional bars.
        res = triceratops_result(_output())
        self.assertEqual(res.status, "pass")
        self.assertEqual(res.threshold, 0.015)


FAKE_TRI = textwrap.dedent("""\
    import json, os
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
                 search_radius=int(search_radius))
            self.ID = ID
            self.sectors = sectors
            self.FPP_degenerate = False

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
                           423498314],
                    "scenario": ["TP", "EB", "BEB", "SEB"],
                    "prob": [0.13, 0.80, 0.05, 0.02]})
                return
            self.FPP = 0.0032
            self.NFPP = 0.0009
            self.probs = pd.DataFrame({
                "ID": [423498314, 423498314, 423498315,
                       423498314],
                "scenario": ["TP", "EB", "BEB", "PEB"],
                "prob": [0.9968, 0.0021, 0.0009, 0.0002]})
    """)


def _input_dict(tmp, dilution_corrected=False):
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
         "sectors": [96], "cadence_s": 600.0},
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
                     behaviour="planet"):
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
        proc = subprocess.run(
            [sys.executable, WRAPPER, "--input", str(input_path),
             "--output", str(output_path)],
            capture_output=True, text=True, env=env, timeout=120)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = json.loads(output_path.read_text())
        obs = (json.loads(Path(obs_path).read_text())
               if os.path.exists(obs_path) else {})
        return work, out, obs

    def test_success_planet(self):
        with tempfile.TemporaryDirectory() as tmp:
            fakevenv = self._fake_tri(tmp)
            work, out, obs = self._run_wrapper(
                tmp, fakevenv, _input_dict(tmp))
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
            # Phase-folded time spans [-P/2, P/2].
            self.assertGreaterEqual(obs["time_min"], -3.9227 / 2)
            self.assertLessEqual(obs["time_max"], 3.9227 / 2)
            self.assertGreater(obs["n_points"], 1000)

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


if __name__ == "__main__":
    unittest.main()
