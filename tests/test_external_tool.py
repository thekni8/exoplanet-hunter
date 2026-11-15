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
  * sigkill: kills itself with SIGKILL (the kernel
    OOM-killer's signature, returncode -9);
  * noisy: prints garbage on stdout/stderr, writes a valid
    output (stdout is not the output channel);
  * noisy-badjson: garbage on stdout AND invalid output JSON;
  * list: writes a JSON list, not an object.

Plus unit tests for the C-10 input builder and the config
hash. Nothing here touches the network or the real tools.
"""
import hashlib
import json
import os
import sys
import tempfile
import textwrap
import time
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
    _memory_cap_preexec, build_tool_input,
    default_wrapper_path, run_external_tool, tool_config_hash,
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

# P-13: dies by signal, as the kernel OOM-killer would
# deliver it (returncode -9) — the runner must read FAILED,
# not crash and not mistake the signal for a pass.
FAKE_SIGKILL = textwrap.dedent("""\
    import os, signal
    os.kill(os.getpid(), signal.SIGKILL)
    """)

# P-13: garbage on both streams — stdout is not the output
# channel, so a valid output.json still completes.
FAKE_NOISY = textwrap.dedent("""\
    import argparse, json, sys
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()
    print("{not json, just noise")
    print("traceback-ish noise", file=sys.stderr)
    json.dump({"tool": "fake", "status": "completed",
               "seed": 0, "value": None, "metrics": {},
               "artifacts": [], "warnings": [],
               "wall_time_s": 0.1}, open(args.output, "w"))
    """)

# P-13: garbage on stdout AND invalid output JSON — the
# stdout noise must not mask the JSON failure.
FAKE_NOISY_BADJSON = textwrap.dedent("""\
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()
    print("{not json, just noise")
    open(args.output, "w").write("{not json")
    """)

# P-13: valid JSON, wrong shape — a list, not an object.
FAKE_LIST = textwrap.dedent("""\
    import argparse, json
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()
    json.dump(["not", "an", "object"], open(args.output, "w"))
    """)

# P-3: spawns a grandchild (a 30 s sleep) and records its PID
# in FAKE_GRANDCHILD_PID, then sleeps 30 s itself — the
# process-group-kill test proves the timeout takes the
# grandchild too, not just the wrapper.
FAKE_SPAWNER = textwrap.dedent("""\
    import os, subprocess, sys, time
    pid_file = os.environ["FAKE_GRANDCHILD_PID"]
    child = subprocess.Popen([sys.executable, "-c",
                              "import time; time.sleep(30)"])
    open(pid_file, "w").write(str(child.pid))
    time.sleep(30)
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


class TestFaultInjection(unittest.TestCase):
    """P-13: the fault matrix — every failure mode is a
    status, never a crash and never a silent PASS. The
    crash / timeout / memory-cap / missing-venv / missing-
    wrapper / malformed-output modes are covered in
    TestRunExternalTool; this class covers the remaining
    modes: signal kill, malformed stdout, spawn failure
    (the venv breaking mid-run), and non-object output."""

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

    def test_signal_kill_is_failed(self):
        # The kernel OOM-killer delivers SIGKILL: returncode
        # -9, no stderr, no output. The runner reads FAILED.
        with tempfile.TemporaryDirectory() as tmp:
            fake = self._write_fake(tmp, "fake_sigkill.py",
                                    FAKE_SIGKILL)
            res = run_external_tool(
                self._config(fake), self._input(), tmp)
            self.assertEqual(res.status, STATUS_FAILED)
            self.assertIsNone(res.output)
            self.assertEqual(res.returncode, -9)
            self.assertIn("exited -9", res.stderr_tail)

    def test_noisy_stdout_with_valid_output_completes(self):
        # Stdout is never parsed: garbage on stdout (and
        # stderr) with a valid output.json still completes.
        with tempfile.TemporaryDirectory() as tmp:
            fake = self._write_fake(tmp, "fake_noisy.py",
                                    FAKE_NOISY)
            res = run_external_tool(
                self._config(fake), self._input(), tmp)
            self.assertEqual(res.status, STATUS_COMPLETED)
            self.assertEqual(res.output["status"], "completed")
            self.assertEqual(res.returncode, 0)

    def test_noisy_stdout_with_bad_output_is_failed(self):
        # The stdout noise must not mask the JSON failure.
        with tempfile.TemporaryDirectory() as tmp:
            fake = self._write_fake(tmp, "fake_noisy_bad.py",
                                    FAKE_NOISY_BADJSON)
            res = run_external_tool(
                self._config(fake), self._input(), tmp)
            self.assertEqual(res.status, STATUS_FAILED)
            self.assertIsNone(res.output)
            self.assertIn("unreadable", res.stderr_tail)

    def test_non_object_output_is_failed(self):
        # Valid JSON, wrong shape — a list, not an object.
        with tempfile.TemporaryDirectory() as tmp:
            fake = self._write_fake(tmp, "fake_list.py",
                                    FAKE_LIST)
            res = run_external_tool(
                self._config(fake), self._input(), tmp)
            self.assertEqual(res.status, STATUS_FAILED)
            self.assertIsNone(res.output)
            self.assertIn("not an object", res.stderr_tail)

    def test_unexecutable_python_is_failed_not_a_raise(self):
        # The venv python exists (so the missing_venv check
        # passes) but cannot be spawned — the mid-run
        # breakage case: a status, not a raise.
        with tempfile.TemporaryDirectory() as tmp:
            fake = self._write_fake(tmp, "fake_ok.py", FAKE_OK)
            dead = Path(tmp) / "dead_python"
            dead.write_text("# not a python binary\n")
            dead.chmod(0o644)
            cfg = self._config(fake, python=str(dead))
            res = run_external_tool(cfg, self._input(), tmp)
            self.assertEqual(res.status, STATUS_FAILED)
            self.assertIsNone(res.output)
            self.assertIsNone(res.returncode)
            self.assertIn("could not spawn", res.stderr_tail)


class TestMemoryCapGuard(unittest.TestCase):
    """P-3 (Phase 2 vote follow-up): the RLIMIT_AS cap is
    Linux-only, the timeout kills the whole process group,
    and the run records whether the cap applied."""

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

    def test_cap_is_linux_only(self):
        # macOS/XNU counts the whole virtual address space
        # against RLIMIT_AS — the cap must not be installed
        # there. The platform seam makes this testable
        # without monkeypatching sys.platform.
        self.assertIsNone(_memory_cap_preexec(2048, "darwin"))
        self.assertIsNone(_memory_cap_preexec(2048, "win32"))

    @unittest.skipUnless(resource is not None,
                         "RLIMIT_AS needs Unix resource module")
    def test_cap_applies_on_linux(self):
        self.assertIsNotNone(_memory_cap_preexec(2048, "linux"))
        self.assertIsNone(_memory_cap_preexec(0, "linux"))

    def test_cap_applied_recorded(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake = self._write_fake(tmp, "fake_ok.py", FAKE_OK)
            res = run_external_tool(
                self._config(fake), self._input(), tmp)
            self.assertEqual(res.status, STATUS_COMPLETED)
            # On Linux the cap applies; on macOS it does not
            # (P-3 guard) — the record must say which.
            self.assertEqual(
                res.memory_cap_applied,
                sys.platform.startswith("linux"))

    def test_cap_not_applied_without_cap(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake = self._write_fake(tmp, "fake_ok.py", FAKE_OK)
            res = run_external_tool(
                self._config(fake, memory_mb=0),
                self._input(), tmp)
            self.assertEqual(res.status, STATUS_COMPLETED)
            self.assertFalse(res.memory_cap_applied)

    def test_timeout_kills_the_process_group(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake = self._write_fake(tmp, "fake_spawner.py",
                                    FAKE_SPAWNER)
            pid_file = str(Path(tmp) / "grandchild.pid")
            os.environ["FAKE_GRANDCHILD_PID"] = pid_file
            self.addCleanup(os.environ.pop,
                            "FAKE_GRANDCHILD_PID", None)
            res = run_external_tool(
                self._config(fake, timeout_s=2),
                self._input(), tmp)
            self.assertEqual(res.status, STATUS_TIMEOUT)
            self.assertIsNone(res.output)
            grandchild = int(Path(pid_file).read_text())
            # The grandchild must be dead, not orphaned: poll
            # briefly (a SIGKILLed child can sit as a zombie
            # until reaped). Clean up on failure so a
            # regression does not leave a 30 s sleeper behind.
            dead = False
            try:
                for _ in range(20):
                    try:
                        os.kill(grandchild, 0)
                    except ProcessLookupError:
                        dead = True
                        break
                    time.sleep(0.1)
            finally:
                if not dead:
                    try:
                        os.kill(grandchild, 9)
                    except ProcessLookupError:
                        pass
            self.assertTrue(
                dead,
                msg="grandchild survived the timeout — the "
                    "kill did not reach the process group")


if __name__ == "__main__":
    unittest.main()
