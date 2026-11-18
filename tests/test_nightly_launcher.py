"""Tests for the TRICERATOPS nightly launchd launcher + plist (fixes
round 1). The 03:00 run on 2026-11-18 failed with exit 78 because
launchd could not open its stdout path on /Volumes/NVME while the
Mac was in clamshell sleep and the volume was inaccessible. These
tests lock in the fix: nothing launchd touches at spawn time may
live on the external volume, and the launcher must wait for the
volume (then run the nightly) or time out loudly.

Offline, seconds: the launcher's test seams (NIGHTLY_READY_FILE,
NIGHTLY_EXEC_CMD, NIGHTLY_WAIT_SECONDS, NIGHTLY_POLL_S) fake the
volume and the nightly; no real waiting, no Mac needed.
"""
import os
import plistlib
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LAUNCHD_DIR = ROOT / "scripts" / "launchd"
LAUNCHER = LAUNCHD_DIR / "triceratops-nightly-launcher.sh"
PLIST = LAUNCHD_DIR / "com.takeshi.exoplanet.triceratops-nightly.plist"


def _run_launcher(env_extra, timeout_s=60):
    """Run the launcher with the given env overrides; return
    (returncode, combined output)."""
    env = dict(os.environ)
    env.update(env_extra)
    proc = subprocess.run(
        ["/bin/bash", str(LAUNCHER)], capture_output=True, text=True,
        env=env, timeout=timeout_s)
    return proc.returncode, proc.stdout + proc.stderr


class TestPlistTemplate(unittest.TestCase):
    def setUp(self):
        with open(PLIST, "rb") as fh:
            self.plist = plistlib.load(fh)

    def test_label_and_schedule(self):
        self.assertEqual(
            self.plist["Label"],
            "com.takeshi.exoplanet.triceratops-nightly")
        interval = self.plist["StartCalendarInterval"]
        self.assertEqual(interval["Hour"], 3)
        self.assertEqual(interval["Minute"], 0)
        self.assertIs(self.plist["RunAtLoad"], False)

    def test_nothing_spawn_time_lives_on_nvme(self):
        """Every path launchd touches at spawn (program, stdout,
        stderr, working directory) must be on the internal disk.
        A path on /Volumes/NVME is exactly what failed the 03:00
        run (exit 78: launchd could not open the stdout path
        while the volume was inaccessible in clamshell sleep)."""
        for arg in self.plist["ProgramArguments"]:
            if arg.startswith("/"):
                self.assertFalse(
                    arg.startswith("/Volumes/"),
                    f"spawn-time program path on NVMe: {arg}")
        for key in ("StandardOutPath", "StandardErrorPath"):
            path = self.plist[key]
            self.assertTrue(os.path.isabs(path), key)
            self.assertFalse(
                path.startswith("/Volumes/"),
                f"{key} on NVMe: {path}")
        self.assertEqual(
            self.plist["StandardOutPath"],
            self.plist["StandardErrorPath"])
        wd = self.plist.get("WorkingDirectory")
        self.assertTrue(
            wd is None or not wd.startswith("/Volumes/"),
            f"WorkingDirectory on NVMe: {wd}")

    def test_program_is_the_launcher(self):
        args = self.plist["ProgramArguments"]
        self.assertEqual(args[0], "/bin/bash")
        self.assertEqual(
            args[1],
            "/Users/dk/Library/LaunchAgents/"
            "triceratops-nightly-launcher.sh")


class TestLauncher(unittest.TestCase):
    def test_volume_present_runs_nightly_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            ready = Path(tmp) / "ready"
            ready.touch()
            code, out = _run_launcher({
                "NIGHTLY_READY_FILE": str(ready),
                "NIGHTLY_EXEC_CMD": "echo NIGHTLY_EXECUTED",
                "NIGHTLY_POLL_S": "1",
            })
        self.assertEqual(code, 0, out)
        self.assertIn("NIGHTLY_EXECUTED", out)
        self.assertIn("volume ready", out)

    def test_volume_absent_times_out_loudly(self):
        # No ready file; a 3-second wait must exit 1 with the
        # timeout line (fast: the seam overrides the 9 h default).
        code, out = _run_launcher({
            "NIGHTLY_READY_FILE": "/nonexistent/ready-file",
            "NIGHTLY_WAIT_SECONDS": "3",  # 3 s
            "NIGHTLY_POLL_S": "1",
        })
        self.assertEqual(code, 1, out)
        self.assertIn("VOLUME_WAIT_TIMEOUT", out)

    def test_volume_appearing_mid_wait_proceeds(self):
        with tempfile.TemporaryDirectory() as tmp:
            ready = Path(tmp) / "ready"

            def _appear():
                time.sleep(2)
                ready.touch()

            threading.Thread(target=_appear, daemon=True).start()
            code, out = _run_launcher({
                "NIGHTLY_READY_FILE": str(ready),
                "NIGHTLY_EXEC_CMD": "echo NIGHTLY_EXECUTED",
                "NIGHTLY_WAIT_SECONDS": "30",
                "NIGHTLY_POLL_S": "1",
            })
        self.assertEqual(code, 0, out)
        self.assertIn("NIGHTLY_EXECUTED", out)
        self.assertIn("waiting for", out)

    def test_launcher_is_executable_and_bash_clean(self):
        self.assertTrue(os.access(LAUNCHER, os.X_OK))
        proc = subprocess.run(
            ["/bin/bash", "-n", str(LAUNCHER)],
            capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)


if __name__ == "__main__":
    unittest.main()
