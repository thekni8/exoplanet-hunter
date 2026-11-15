"""LATTE adapter + wrapper tests (Phase 2, 2B-2).

Two layers, both driven without the real tool:

* The ADAPTER (gauntlet/stage_result.py:latte_result) maps
  canned LATTE output JSONs onto StageResults. LATTE emits
  plots + a PDF, no machine-readable dispositions — so a
  completed run is INCONCLUSIVE, never PASS/FAIL.
* The WRAPPER (gauntlet/tools/run_latte.py) is run for real
  against a FAKE LATTE package: a minimal `LATTE` package on
  PYTHONPATH whose __main__ mimics the real one's contract
  (reads _config.txt from its own package dir, reads the
  --targetlist CSV, writes {indir}/{tic}/DV_report_{tic}.pdf).
  Variants cover success, exit-0-with-no-report (the real
  LATTE's failure mode), a crash, a missing _config.txt, and
  an unimportable LATTE.

The wrapper's nested-timeout branch is tested in-process
(importing run_latte and monkeypatching its subprocess call):
a subprocess-level test would need to wait out the 60 s
nested-timeout floor.
"""
import ast
import csv
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gauntlet.external_tool import build_tool_input  # noqa: E402
from gauntlet.stage_result import latte_result  # noqa: E402
from validation import (  # noqa: E402
    RecordValidationError, validate_latte_output,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
WRAPPER = str(REPO_ROOT / "gauntlet" / "tools" / "run_latte.py")


def _output(**overrides):
    out = {
        "tool": "latte",
        "tool_version": "1.0.21",
        "seed": 20261114,
        "config_hash": "c" * 64,
        "status": "completed",
        "value": None,
        "metrics": {"report_pdf": "/tmp/work/DV_report_1.pdf",
                    "output_dir": "/tmp/latte-out/1",
                    "n_artifacts": 12,
                    "latte_indir": "/tmp/latte-out"},
        "input_hashes": {"lightcurve": "a" * 64,
                         "neighbours": "b" * 64},
        "artifacts": ["/tmp/work/DV_report_1.pdf"],
        "warnings": [],
        "wall_time_s": 187.0,
        "n_transits": 42,
    }
    out.update(overrides)
    return out


class TestLatteResult(unittest.TestCase):

    def test_completed_is_report_only_never_pass(self):
        res = latte_result(_output())
        self.assertEqual(res.stage, "latte")
        # LATTE has no machine-readable dispositions: a
        # completed run is report_only (P-5), never a pass —
        # and never inconclusive either: inconclusive means
        # the stage measured and could not decide, and here
        # there was nothing to decide.
        self.assertEqual(res.status, "report_only")
        self.assertEqual(res.execution_status, "completed")
        self.assertIn("human must read it", res.reason)
        self.assertEqual(res.value, None)
        self.assertEqual(res.artifacts,
                         ["/tmp/work/DV_report_1.pdf"])
        self.assertEqual(res.tool_version, "1.0.21")
        self.assertEqual(res.config_hash, "c" * 64)
        self.assertEqual(res.input_hashes["lightcurve"],
                         "a" * 64)
        self.assertEqual(res.n_transits, 42)
        self.assertEqual(res.details["report_pdf"],
                         "/tmp/work/DV_report_1.pdf")
        self.assertEqual(res.metrics["n_artifacts"], 12)

    def test_failed_is_unmeasured_error(self):
        res = latte_result(_output(
            status="failed",
            metrics={"report_pdf": None, "output_dir": None,
                     "n_artifacts": 0, "latte_indir": None},
            artifacts=[]))
        self.assertEqual(res.status, "unmeasured")
        self.assertEqual(res.execution_status, "error")
        self.assertIn("failed", res.reason)

    def test_timeout_is_unmeasured_error(self):
        res = latte_result(_output(
            status="timeout",
            metrics={"report_pdf": None, "output_dir": None,
                     "n_artifacts": 0, "latte_indir": None},
            artifacts=[]))
        self.assertEqual(res.status, "unmeasured")
        self.assertEqual(res.execution_status, "error")

    def test_completed_without_report_is_unmeasured(self):
        # The schema's if/then rule: a completed run MUST
        # carry a report PDF. A completion claim without one
        # is a schema failure -> unmeasured + error.
        res = latte_result(_output(metrics={
            "report_pdf": None, "output_dir": "/tmp/x",
            "n_artifacts": 0, "latte_indir": "/tmp"}))
        self.assertEqual(res.status, "unmeasured")
        self.assertEqual(res.execution_status, "error")
        self.assertIn("schema validation", res.reason)

    def test_malformed_output_is_unmeasured(self):
        bad = _output()
        del bad["seed"]
        res = latte_result(bad)
        self.assertEqual(res.status, "unmeasured")
        self.assertEqual(res.execution_status, "error")

    def test_no_native_is_unmeasured(self):
        res = latte_result(None)
        self.assertEqual(res.status, "unmeasured")

    def test_schema_validation_direct(self):
        validate_latte_output(_output())
        bad = _output(status="exploded")
        with self.assertRaises(RecordValidationError):
            validate_latte_output(bad)


FAKE_LATTE_OK = textwrap.dedent("""\
    import argparse, csv, os
    ap = argparse.ArgumentParser()
    ap.add_argument("--targetlist", required=True)
    ap.add_argument("--o", action="store_true")
    ap.add_argument("--noshow", action="store_true")
    args = ap.parse_args()
    pkg_dir = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(pkg_dir, "_config.txt")) as fh:
        indir = fh.read().strip()
    with open(args.targetlist, newline="") as fh:
        row = next(csv.DictReader(fh))
    tic = row["TICID"]
    target_dir = os.path.join(indir, tic)
    os.makedirs(target_dir, exist_ok=True)
    with open(os.path.join(target_dir,
                           "DV_report_{}.pdf".format(tic)),
              "wb") as fh:
        fh.write(b"%PDF-fake-latte-report")
    with open(os.path.join(target_dir,
                           "full_lightcurve.png"), "wb") as fh:
        fh.write(b"\\x89PNG-fake")
    """)

FAKE_LATTE_NO_REPORT = textwrap.dedent("""\
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--targetlist", required=True)
    ap.add_argument("--o", action="store_true")
    ap.add_argument("--noshow", action="store_true")
    ap.parse_args()
    # Exit 0 and write nothing — the real LATTE's
    # per-target failure mode.
    """)

FAKE_LATTE_CRASH = textwrap.dedent("""\
    import sys
    print("latte exploded", file=sys.stderr)
    sys.exit(1)
    """)


def _input_dict(ffi_mode=False):
    inp = build_tool_input(
        "latte", "1.0.21", 20261114, "c" * 64,
        {"tic": "423498314", "ra_deg": 123.456,
         "dec_deg": -63.789, "tmag": 13.45,
         "star_radius_rsun": 0.673, "star_mass_msun": 0.61,
         "teff_k": 4400},
        {"period_d": 0.8270470, "t0_bjd": 2459000.123,
         "duration_h": 1.41, "depth_frac": 0.01029,
         "n_transits": 42},
        {"path": "/tmp/lc.npz", "input_hash": "a" * 64,
         "sectors": [1, 2, 3], "cadence_s": 120.0},
        {"path": "/tmp/census.json", "input_hash": "b" * 64,
         "radius_arcsec": 180.0},
        contrast_curve=False)
    inp["ffi_mode"] = ffi_mode
    return inp


class TestRunLatteWrapper(unittest.TestCase):

    def _fake_latte(self, tmp, main_source, with_config=True):
        """A fake LATTE package on PYTHONPATH. Returns
        (fakevenv_dir, indir)."""
        fakevenv = Path(tmp) / "fakevenv"
        pkg = fakevenv / "LATTE"
        pkg.mkdir(parents=True)
        (pkg / "__init__.py").write_text("")
        (pkg / "__main__.py").write_text(main_source)
        indir = Path(tmp) / "latte-out"
        indir.mkdir()
        if with_config:
            (pkg / "_config.txt").write_text(str(indir))
        return str(fakevenv), str(indir)

    def _run_wrapper(self, tmp, fakevenv, inp):
        work = Path(tmp) / "work"
        work.mkdir(exist_ok=True)
        input_path = work / "input.json"
        output_path = work / "output.json"
        input_path.write_text(json.dumps(inp))
        env = dict(os.environ)
        env["PYTHONPATH"] = fakevenv + os.pathsep + env.get(
            "PYTHONPATH", "")
        proc = subprocess.run(
            [sys.executable, WRAPPER, "--input", str(input_path),
             "--output", str(output_path)],
            capture_output=True, text=True, env=env, timeout=120)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return work, json.loads(output_path.read_text())

    def _read_targetlist(self, work):
        with open(work / "targetlist.csv", newline="") as fh:
            return next(csv.DictReader(fh))

    def test_success_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            fakevenv, indir = self._fake_latte(
                tmp, FAKE_LATTE_OK)
            work, out = self._run_wrapper(
                tmp, fakevenv, _input_dict())
            self.assertEqual(out["status"], "completed")
            self.assertEqual(out["tool"], "latte")
            self.assertEqual(out["seed"], 20261114)
            # tessLATTE is not installed here: the wrapper
            # falls back to the input's version + a warning.
            self.assertEqual(out["tool_version"], "1.0.21")
            self.assertTrue(any("could not read" in w
                                for w in out["warnings"]))
            # The report PDF was copied into the workdir.
            pdf = Path(out["metrics"]["report_pdf"])
            self.assertTrue(pdf.exists())
            self.assertEqual(pdf.parent, work)
            self.assertEqual(out["artifacts"], [str(pdf)])
            self.assertEqual(out["metrics"]["n_artifacts"], 2)
            self.assertEqual(out["input_hashes"]["lightcurve"],
                             "a" * 64)
            self.assertEqual(out["n_transits"], 42)
            validate_latte_output(out)
            # The targetlist CSV the wrapper wrote.
            row = self._read_targetlist(work)
            self.assertEqual(row["TICID"], "423498314")
            self.assertEqual(float(row["period"]), 0.8270470)
            self.assertEqual(float(row["t0"]), 2459000.123)
            self.assertEqual(ast.literal_eval(row["sectors"]),
                             [1, 2, 3])
            self.assertEqual(row["BLS"], "no")
            self.assertEqual(row["model"], "no")
            self.assertEqual(row["FFI"], "no")

    def test_ffi_mode_passes_through(self):
        with tempfile.TemporaryDirectory() as tmp:
            fakevenv, _ = self._fake_latte(tmp, FAKE_LATTE_OK)
            work, out = self._run_wrapper(
                tmp, fakevenv, _input_dict(ffi_mode=True))
            self.assertEqual(out["status"], "completed")
            self.assertEqual(
                self._read_targetlist(work)["FFI"], "yes")

    def test_exit_zero_without_report_is_failed(self):
        with tempfile.TemporaryDirectory() as tmp:
            fakevenv, _ = self._fake_latte(
                tmp, FAKE_LATTE_NO_REPORT)
            _work, out = self._run_wrapper(
                tmp, fakevenv, _input_dict())
            self.assertEqual(out["status"], "failed")
            self.assertIsNone(out["metrics"]["report_pdf"])
            self.assertTrue(any("no DV report" in w
                                for w in out["warnings"]))
            validate_latte_output(out)

    def test_crash_is_failed(self):
        with tempfile.TemporaryDirectory() as tmp:
            fakevenv, _ = self._fake_latte(tmp, FAKE_LATTE_CRASH)
            _work, out = self._run_wrapper(
                tmp, fakevenv, _input_dict())
            self.assertEqual(out["status"], "failed")
            self.assertTrue(any("exited 1" in w
                                for w in out["warnings"]))

    def test_missing_config_is_failed(self):
        with tempfile.TemporaryDirectory() as tmp:
            fakevenv, _ = self._fake_latte(
                tmp, FAKE_LATTE_OK, with_config=False)
            _work, out = self._run_wrapper(
                tmp, fakevenv, _input_dict())
            self.assertEqual(out["status"], "failed")
            self.assertTrue(any("not configured" in w
                                for w in out["warnings"]))

    def test_latte_not_importable_is_failed(self):
        with tempfile.TemporaryDirectory() as tmp:
            empty = Path(tmp) / "empty"
            empty.mkdir()
            _work, out = self._run_wrapper(
                tmp, str(empty), _input_dict())
            self.assertEqual(out["status"], "failed")
            self.assertTrue(any("not importable" in w
                                for w in out["warnings"]))

    def test_nested_timeout_is_timeout(self):
        # In-process: monkeypatch the wrapper's subprocess
        # call to raise TimeoutExpired (a subprocess-level
        # test would wait out the 60 s nested-timeout floor).
        spec = importlib.util.spec_from_file_location(
            "run_latte", WRAPPER)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp) / "work"
            work.mkdir()
            input_path = work / "input.json"
            output_path = work / "output.json"
            input_path.write_text(json.dumps(_input_dict()))
            indir = str(Path(tmp) / "latte-out")
            os.makedirs(indir)
            orig_indir = mod._latte_indir
            orig_run = mod.subprocess.run
            mod._latte_indir = lambda: (indir, None)

            def _raise(*args, **kwargs):
                raise subprocess.TimeoutExpired(
                    cmd=args[0], timeout=kwargs.get("timeout"))
            mod.subprocess.run = _raise
            try:
                out = mod.run(str(input_path), str(output_path))
            finally:
                mod._latte_indir = orig_indir
                mod.subprocess.run = orig_run
            self.assertEqual(out["status"], "timeout")
            self.assertIsNone(out["metrics"]["report_pdf"])
            validate_latte_output(out)


if __name__ == "__main__":
    unittest.main()
