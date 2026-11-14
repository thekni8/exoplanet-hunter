"""External-tool plumbing tests (Phase 2, 2B-1).

The plumbing (gauntlet/external_tool.py) spawns LATTE and
TRICERATOPS out of process under a timeout and a memory cap.
These tests drive it with FAKE tool scripts — small Python
programs run by the current interpreter as the "venv python"
— so no real tool is ever imported or installed here:

  * ok: echoes a marker from the input into a canned output;
  * crash: exits 1 with stderr;
  * sleep: sleeps past the timeout;
  * hog: allocates far past the memory cap;
  * badjson: writes invalid JSON;
  * silent: exits 0 writing nothing.

Plus unit tests for the C-10 input builder and the config
hash. Nothing here touches the network or the real tools.
"""
import hashlib
import json
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

try:
    import resource
except ImportError:  # pragma: no cover - non-Unix hosts
    resource = None

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gauntlet.external_tool import (  # noqa: E402
    DEFAULT_SEED, STATUS_COMPLETED, STATUS_FAILED,
    STATUS_MISSING_VENV, STATUS_TIMEOUT, ToolConfig,
    build_tool_input, default_wrapper_path, run_external_tool,
    tool_config_hash,
)

FAKE_OK = textwrap.dedent("""\
    import argparse, json
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()
    inp = json.load(open(args.input))
    json.dump({"tool": inp["tool"], "status": "completed",
               "seed": inp["seed"],
               "marker": inp["signal"]["period_d"],
               "value": None, "metrics": {},
               "artifacts": [], "warnings": [],
               "wall_time_s": 0.1}, open(args.output, "w"))
    """)

FAKE_CRASH = textwrap.dedent("""\
    import sys
    print("boom: the tool exploded", file=sys.stderr)
    sys.exit(1)
    """)

FAKE_SLEEP = textwrap.dedent("""\
    import time
    time.sleep(30)
    """)

FAKE_HOG = textwrap.dedent("""\
    # Allocate 2 GB under a small RLIMIT_AS cap: the
    # allocation itself must fail (MemoryError) before any
    # real memory is touched.
    buf = bytearray(2 * 1024 * 1024 * 1024)
    buf[-1] = 1
    print(len(buf))
    """)

FAKE_BADJSON = textwrap.dedent("""\
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()
    open(args.output, "w").write("{not json")
    """)

FAKE_SILENT = textwrap.dedent("""\
    # Exits 0 and writes nothing — the LATTE failure mode
    # (it swallows per-target failures and exits 0).
    """)


def _target():
    return {"tic": "423498314", "ra_deg": 123.456,
            "dec_deg": -63.789, "tmag": 13.45,
            "star_radius_rsun": 0.673, "star_mass_msun": 0.61,
            "teff_k": 4400}


def _signal():
    return {"period_d": 0.8270470, "t0_bjd": 2459000.123,
            "duration_h": 1.41, "depth_frac": 0.01029,
            "n_transits": 42}


def _lightcurve():
    return {"path": "/tmp/lc.npz", "input_hash": "a" * 64,
            "sectors": [1, 2, 3], "cadence_s": 120.0}


def _neighbours():
    return {"path": "/tmp/census.json", "input_hash": "b" * 64,
            "radius_arcsec": 180.0}


class TestBuildToolInput(unittest.TestCase):

    def test_triceratops_contract(self):
        rec = build_tool_input(
            "triceratops", "1.1.0", DEFAULT_SEED, "c" * 64,
            _target(), _signal(), _lightcurve(), _neighbours())
        self.assertEqual(rec["tool"], "triceratops")
        self.assertEqual(rec["tool_version"], "1.1.0")
        self.assertEqual(rec["seed"], DEFAULT_SEED)
        self.assertEqual(rec["config_hash"], "c" * 64)
        # The ephemeris is always "refined" — the bulk period
        # is never a valid tool input.
        self.assertEqual(rec["signal"]["ephemeris"], "refined")
        self.assertEqual(rec["signal"]["period_d"], 0.8270470)
        self.assertEqual(rec["neighbours"]["radius_arcsec"], 180.0)
        # No contrast curve: nulls, not a missing key.
        self.assertEqual(rec["contrast_curve"],
                         {"path": None, "input_hash": None})
        self.assertEqual(rec["timeout_s"], 1800)

    def test_contrast_curve_carried(self):
        rec = build_tool_input(
            "triceratops", "1.1.0", DEFAULT_SEED, "c" * 64,
            _target(), _signal(), _lightcurve(), _neighbours(),
            contrast_curve={"path": "/tmp/cc.tbl",
                            "input_hash": "d" * 64})
        self.assertEqual(rec["contrast_curve"]["path"], "/tmp/cc.tbl")

    def test_latte_has_no_contrast_curve_key(self):
        # C-10: the LATTE input is the same shape with no
        # contrast_curve key at all (LATTE does not use one).
        rec = build_tool_input(
            "latte", "1.0.21", DEFAULT_SEED, "c" * 64,
            _target(), _signal(), _lightcurve(), _neighbours(),
            contrast_curve=False)
        self.assertNotIn("contrast_curve", rec)

    def test_missing_key_fails_loud(self):
        bad = _target()
        del bad["tmag"]
        with self.assertRaises(ValueError):
            build_tool_input("triceratops", "1.1.0", DEFAULT_SEED,
                             "c" * 64, bad, _signal(),
                             _lightcurve(), _neighbours())

    def test_config_hash(self):
        with tempfile.NamedTemporaryFile("w", suffix=".yaml",
                                         delete=False) as fh:
            fh.write("seed: 20261114\n")
            path = fh.name
        want = hashlib.sha256(b"seed: 20261114\n").hexdigest()
        self.assertEqual(tool_config_hash(path), want)

    def test_default_wrapper_path(self):
        self.assertTrue(default_wrapper_path("latte").endswith(
            "tools/run_latte.py"))
        self.assertTrue(default_wrapper_path("triceratops").endswith(
            "tools/run_triceratops.py"))


class TestRunExternalTool(unittest.TestCase):

    def _write_fake(self, tmp, name, source):
        path = Path(tmp) / name
        path.write_text(source)
        return str(path)

    def _config(self, wrapper, **kw):
        cfg = {"tool": "fake", "python": sys.executable,
               "wrapper": wrapper, "timeout_s": 30,
               "memory_mb": 2048, "seed": DEFAULT_SEED,
               "tool_version": "0", "config_hash": "x" * 64}
        cfg.update(kw)
        return ToolConfig(**cfg)

    def _input(self):
        return build_tool_input(
            "fake", "0", DEFAULT_SEED, "x" * 64, _target(),
            _signal(), _lightcurve(), _neighbours())

    def test_ok_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake = self._write_fake(tmp, "fake_ok.py", FAKE_OK)
            work = str(Path(tmp) / "work")
            res = run_external_tool(self._config(fake),
                                    self._input(), work)
            self.assertEqual(res.status, STATUS_COMPLETED)
            self.assertEqual(res.output["status"], "completed")
            self.assertEqual(res.output["seed"], DEFAULT_SEED)
            # The marker proves the wrapper received our input.
            self.assertEqual(res.output["marker"], 0.8270470)
            self.assertEqual(res.returncode, 0)
            self.assertGreaterEqual(res.wall_time_s, 0.0)
            # The input JSON is on disk for audit.
            self.assertTrue(
                (Path(work) / "input.json").exists())

    def test_crash_is_failed_not_a_raise(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake = self._write_fake(tmp, "fake_crash.py",
                                    FAKE_CRASH)
            res = run_external_tool(
                self._config(fake), self._input(), tmp)
            self.assertEqual(res.status, STATUS_FAILED)
            self.assertIsNone(res.output)
            self.assertEqual(res.returncode, 1)
            self.assertIn("boom", res.stderr_tail)

    def test_timeout_kills_the_child(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake = self._write_fake(tmp, "fake_sleep.py",
                                    FAKE_SLEEP)
            res = run_external_tool(
                self._config(fake, timeout_s=1),
                self._input(), tmp)
            self.assertEqual(res.status, STATUS_TIMEOUT)
            self.assertIsNone(res.output)
            self.assertIsNone(res.returncode)
            # Killed at ~1 s, not left running for 30 s.
            self.assertLess(res.wall_time_s, 5.0)
            self.assertGreaterEqual(res.wall_time_s, 0.9)

    @unittest.skipUnless(resource is not None,
                         "RLIMIT_AS needs Unix resource module")
    def test_memory_cap_kills_the_hog(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake = self._write_fake(tmp, "fake_hog.py", FAKE_HOG)
            res = run_external_tool(
                self._config(fake, memory_mb=256),
                self._input(), tmp)
            self.assertEqual(res.status, STATUS_FAILED)
            self.assertIsNone(res.output)
            self.assertIn("MemoryError", res.stderr_tail)

    def test_missing_venv_is_a_status_not_a_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake = self._write_fake(tmp, "fake_ok.py", FAKE_OK)
            cfg = self._config(fake,
                               python="/nonexistent/python3.12")
            res = run_external_tool(cfg, self._input(), tmp)
            self.assertEqual(res.status, STATUS_MISSING_VENV)
            self.assertIsNone(res.output)
            self.assertEqual(res.wall_time_s, 0.0)
            self.assertIn("Mac", res.stderr_tail)

    def test_missing_wrapper_is_failed(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = self._config("/nonexistent/run_fake.py")
            res = run_external_tool(cfg, self._input(), tmp)
            self.assertEqual(res.status, STATUS_FAILED)
            self.assertIn("wrapper not found", res.stderr_tail)

    def test_malformed_output_is_failed(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake = self._write_fake(tmp, "fake_badjson.py",
                                    FAKE_BADJSON)
            res = run_external_tool(
                self._config(fake), self._input(), tmp)
            self.assertEqual(res.status, STATUS_FAILED)
            self.assertIn("unreadable", res.stderr_tail)

    def test_exit_zero_without_output_is_failed(self):
        # LATTE swallows per-target failures and exits 0 —
        # exit code alone is not success.
        with tempfile.TemporaryDirectory() as tmp:
            fake = self._write_fake(tmp, "fake_silent.py",
                                    FAKE_SILENT)
            res = run_external_tool(
                self._config(fake), self._input(), tmp)
            self.assertEqual(res.status, STATUS_FAILED)
            self.assertIn("no output JSON", res.stderr_tail)


if __name__ == "__main__":
    unittest.main()
