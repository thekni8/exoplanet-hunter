"""Tests for the TRICERATOPS golden-test nightly driver (P3-8).

Offline: the driver runs a FAKE triceratops wrapper (via the
config_override test seam) that echoes the committed fixtures'
recorded tool outputs, so a green run proves the driver
plumbing + the receipt + the gate — never the real tool. The
real tool runs only on the Mac.

The gate tests (check_receipt) build receipts directly: a
gate-eligible receipt is a full, non-override, fresh, hashed
pass — every rejection reason is tested separately.
"""
import copy
import importlib.util
import json
import os
import sys
import tempfile
import textwrap
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from gauntlet.external_tool import DEFAULT_SEED, ToolConfig  # noqa: E402

_SPEC = importlib.util.spec_from_file_location(
    "triceratops_golden_nightly",
    REPO_ROOT / "scripts" / "triceratops_golden_nightly.py")
nightly = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(nightly)

FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures" / "triceratops"
TICS = ("183537452", "308851365")

# The fake wrapper echoes a pre-written tool output per TIC
# (from $NIGHTLY_TEST_OUTPUTS/<tic>.json) — the recorded
# C-10 outputs for a green run, a doctored one for a red run.
# It sleeps 0.5 s so the RSS watchdog (poll 0.2 s in tests)
# polls at least once — the receipt's peak-RSS recording is
# part of what these tests prove.
FAKE_TRICERATOPS = textwrap.dedent("""\
    import argparse, json, os, time
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()
    inp = json.load(open(args.input))
    tic = str(inp["target"]["tic"])
    out = json.load(open(os.path.join(
        os.environ["NIGHTLY_TEST_OUTPUTS"], tic + ".json")))
    time.sleep(0.5)
    json.dump(out, open(args.output, "w"))
    """)

FAKE_CRASH = textwrap.dedent("""\
    import sys
    print("the venv broke", file=sys.stderr)
    sys.exit(1)
    """)


def _load_fixture_output(tic):
    with open(FIXTURES_DIR / f"{tic}.json") as fh:
        return json.load(fh)["tool_output"]


def _synthetic_receipt(**overrides):
    """A gate-eligible receipt body, hashed (test helper for
    the gate tests — no run involved)."""
    body = {
        "receipt_version": 1,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "git_sha": "abc123",
        "working_tree_dirty": False,
        "policy": "external_tools_v2",
        "policy_sha256": "0" * 64,
        "fast": False,
        "ssl_cert_file": None,
        "config_override": False,
        "overall": "pass",
        "targets": {"183537452": {"status": "pass"},
                    "308851365": {"status": "pass"}},
        "issue": None,
    }
    body.update(overrides)
    return dict(body, receipt_hash=nightly._receipt_hash(body))


class NightlyTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.inputs_dir = self.tmp / "inputs"
        self.outputs_dir = self.tmp / "outputs"
        self.receipt = self.tmp / "receipt.json"
        self.workdir = self.tmp / "work"
        for tic in TICS:
            (self.inputs_dir / tic).mkdir(parents=True)
            (self.inputs_dir / tic / "input.json").write_text(
                json.dumps({
                    "target": {"tic": int(tic)},
                    "seed": 20261114,
                    "config_hash": "x" * 64,
                    "signal": {"period_d": 3.0, "depth": 0.01,
                               "duration_h": 2.0,
                               "t0_bjd": 2459000.0}}))
            self.outputs_dir.mkdir(exist_ok=True)
            (self.outputs_dir / f"{tic}.json").write_text(
                json.dumps(_load_fixture_output(tic)))
        # The fake wrapper finds its outputs via the env, and
        # a preset SSL_CERT_FILE keeps the driver from
        # invoking the venv python for certifi.
        self._env = mock.patch.dict(os.environ, {
            "NIGHTLY_TEST_OUTPUTS": str(self.outputs_dir),
            "SSL_CERT_FILE": "/nonexistent-test-bundle.pem",
        })
        self._env.start()
        self.addCleanup(self._env.stop)
        self.addCleanup(self._tmp.cleanup)

    def _write_fake(self, name, source):
        path = self.tmp / name
        path.write_text(source)
        return str(path)

    def _config(self, wrapper):
        return ToolConfig(
            tool="triceratops", python=sys.executable,
            wrapper=wrapper, timeout_s=60, memory_mb=2048,
            seed=DEFAULT_SEED, tool_version="0",
            config_hash="x" * 64)

    def _run(self, **kw):
        kw.setdefault("no_issue", True)
        return nightly.run_nightly(
            str(self.inputs_dir), str(FIXTURES_DIR),
            str(self.receipt), str(self.workdir),
            config_override=self._config(
                self._write_fake("fake_tri.py", FAKE_TRICERATOPS)),
            rss_poll_s=0.2,
            **kw)


class TestNightlyRun(NightlyTestCase):
    def test_green_run_writes_green_receipt(self):
        passed, receipt = self._run()
        self.assertTrue(passed)
        self.assertEqual(receipt["overall"], "pass")
        self.assertEqual(receipt["fast"], False)
        self.assertTrue(receipt["config_override"])
        for tic in TICS:
            entry = receipt["targets"][tic]
            self.assertEqual(entry["status"], "pass")
            self.assertEqual(entry["failures"], [])
            # The watchdog ran (P3-8): the receipt records a
            # peak RSS for every run.
            self.assertTrue(entry["rss_watchdog_applied"])
            self.assertIsNotNone(entry["peak_rss_mb"])
            self.assertGreater(entry["peak_rss_mb"], 5.0)
        # The receipt on disk verifies against its own hash.
        green, reason = nightly.check_receipt(str(self.receipt))
        # ...but a test-seam receipt is never gate-eligible.
        self.assertFalse(green)
        self.assertIn("config override", reason)

    def test_red_run_records_failures(self):
        # Doctor the EB output: FPP 0.001 reads INCONCLUSIVE,
        # not the expected FAIL/refute.
        eb = _load_fixture_output("308851365")
        eb["value"] = 0.001
        eb["metrics"]["fpp"] = 0.001
        (self.outputs_dir / "308851365.json").write_text(
            json.dumps(eb))
        passed, receipt = self._run()
        self.assertFalse(passed)
        self.assertEqual(receipt["overall"], "fail")
        entry = receipt["targets"]["308851365"]
        self.assertEqual(entry["status"], "fail")
        self.assertTrue(any("disposition" in f
                            for f in entry["failures"]))
        # The other target still passes — a red run is
        # per-target, not a blanket failure.
        self.assertEqual(receipt["targets"]["183537452"]["status"],
                         "pass")

    def test_crashed_tool_is_a_receipt_failure(self):
        passed, receipt = nightly.run_nightly(
            str(self.inputs_dir), str(FIXTURES_DIR),
            str(self.receipt), str(self.workdir),
            no_issue=True,
            config_override=self._config(
                self._write_fake("fake_crash.py", FAKE_CRASH)))
        self.assertFalse(passed)
        for tic in TICS:
            entry = receipt["targets"][tic]
            self.assertEqual(entry["status"], "run_failed")
            self.assertEqual(entry["run_status"], "failed")

    def test_missing_input_is_a_receipt_failure(self):
        os.remove(self.inputs_dir / "308851365" / "input.json")
        passed, receipt = self._run()
        self.assertFalse(passed)
        self.assertEqual(
            receipt["targets"]["308851365"]["status"],
            "missing_input")
        self.assertEqual(
            receipt["targets"]["183537452"]["status"], "pass")

    def test_fast_run_checks_plumbing_only(self):
        passed, receipt = self._run(fast=True)
        self.assertTrue(passed)
        self.assertTrue(receipt["fast"])
        for tic in TICS:
            self.assertEqual(receipt["targets"][tic]["status"],
                             "fast_ok")
        green, reason = nightly.check_receipt(str(self.receipt))
        self.assertFalse(green)
        self.assertIn("fast", reason)

    def test_failure_opens_an_issue(self):
        eb = _load_fixture_output("308851365")
        eb["value"] = 0.001
        eb["metrics"]["fpp"] = 0.001
        (self.outputs_dir / "308851365.json").write_text(
            json.dumps(eb))
        calls = []

        def fake_issue(summary, receipt_path, sha):
            calls.append((summary, receipt_path, sha))
            return True, "https://example.invalid/issues/1"

        with mock.patch.object(nightly, "_open_failure_issue",
                               side_effect=fake_issue):
            passed, receipt = self._run(no_issue=False)
        self.assertFalse(passed)
        self.assertEqual(len(calls), 1)
        self.assertIn("308851365", calls[0][0])
        self.assertTrue(receipt["issue"]["opened"])

    def test_failed_issue_attempt_leaves_a_marker(self):
        eb = _load_fixture_output("308851365")
        eb["value"] = 0.001
        eb["metrics"]["fpp"] = 0.001
        (self.outputs_dir / "308851365.json").write_text(
            json.dumps(eb))

        def failing_issue(summary, receipt_path, sha):
            return False, "gh unavailable (test)"

        with mock.patch.object(nightly, "_open_failure_issue",
                               side_effect=failing_issue):
            passed, receipt = self._run(no_issue=False)
        self.assertFalse(passed)
        self.assertFalse(receipt["issue"]["opened"])
        marker = self.tmp / "FAILURE"
        self.assertTrue(marker.exists())
        self.assertIn("gh unavailable", marker.read_text())


class TestReceiptGate(unittest.TestCase):
    def _write(self, receipt):
        path = Path(tempfile.mktemp(suffix=".json"))
        self.addCleanup(lambda: path.unlink(missing_ok=True))
        path.write_text(json.dumps(receipt))
        return str(path)

    def test_green_receipt_passes(self):
        green, reason = nightly.check_receipt(
            self._write(_synthetic_receipt()))
        self.assertTrue(green, reason)
        self.assertIn("green", reason)

    def test_missing_receipt_fails(self):
        green, _ = nightly.check_receipt("/nonexistent/r.json")
        self.assertFalse(green)

    def test_tampered_receipt_fails(self):
        receipt = _synthetic_receipt()
        receipt["targets"]["183537452"]["status"] = "fail"
        green, reason = nightly.check_receipt(
            self._write(receipt))
        self.assertFalse(green)
        self.assertIn("hash mismatch", reason)

    def test_red_receipt_fails(self):
        green, reason = nightly.check_receipt(
            self._write(_synthetic_receipt(overall="fail")))
        self.assertFalse(green)
        self.assertIn("not 'pass'", reason)

    def test_fast_receipt_fails(self):
        green, reason = nightly.check_receipt(
            self._write(_synthetic_receipt(fast=True)))
        self.assertFalse(green)
        self.assertIn("fast", reason)

    def test_override_receipt_fails(self):
        green, reason = nightly.check_receipt(
            self._write(_synthetic_receipt(config_override=True)))
        self.assertFalse(green)
        self.assertIn("override", reason)

    def test_stale_receipt_fails(self):
        stale = (datetime.now(timezone.utc)
                 - timedelta(days=10)).isoformat()
        green, reason = nightly.check_receipt(
            self._write(_synthetic_receipt(timestamp_utc=stale)))
        self.assertFalse(green)
        self.assertIn("10.0 days old", reason)

    def test_check_cli_exit_codes(self):
        self.assertEqual(
            nightly.main(["--check",
                          self._write(_synthetic_receipt())]), 0)
        self.assertEqual(
            nightly.main(["--check", "/nonexistent/r.json"]), 1)


if __name__ == "__main__":
    unittest.main()
