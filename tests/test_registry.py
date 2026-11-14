"""Calibration-registry tests (Phase 1.2, item A-1).

The registry (calibration/registry.json) is what makes profile
immutability ENFORCED instead of documented: the loader recomputes
each profile's sha256 and rejects a mismatch, and CI diffs the
registry against the base branch so existing entries cannot be
rewritten. These tests prove both guards, using temp copies of
the calibration dir (the real profiles are never touched).
"""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent
                       / "scripts"))

import calibration  # noqa: E402
from calibration import CalibrationError, load_profile  # noqa: E402
from check_registry import registry_diff, verify_hashes  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
REAL_CAL = ROOT / "calibration"


def _copy_cal_dir(td):
    """A temp copy of the real calibration dir (profiles +
    registry), with CALIBRATION_DIR pointed at it. Returns the
    temp dir path; caller restores calibration.CALIBRATION_DIR."""
    dest = Path(td) / "calibration"
    shutil.copytree(REAL_CAL, dest)
    old = calibration.CALIBRATION_DIR
    calibration.CALIBRATION_DIR = dest
    return dest, old


class TestRegistryLoad(unittest.TestCase):
    def test_v1_profiles_load_against_registry(self):
        # The grandfathered v1 entries match the frozen files.
        for name in ("bulk_v1", "deep_v1", "gauntlet_v1"):
            prof = load_profile(name)
            self.assertEqual(prof["version"], name)

    def test_tampered_profile_fails_load(self):
        # A silent edit to a frozen profile — even a comment —
        # changes the hash and the load refuses it.
        with tempfile.TemporaryDirectory() as td:
            dest, old = _copy_cal_dir(td)
            try:
                p = dest / "bulk_v1.yaml"
                p.write_text(p.read_text() + "\n# innocent comment\n")
                with self.assertRaises(CalibrationError):
                    load_profile("bulk_v1")
            finally:
                calibration.CALIBRATION_DIR = old

    def test_unregistered_profile_fails_load(self):
        # A profile file with no registry entry is not loadable —
        # register first, then use.
        with tempfile.TemporaryDirectory() as td:
            dest, old = _copy_cal_dir(td)
            try:
                (dest / "bulk_v9.yaml").write_text(
                    "version: bulk_v9\nstatus: experimental\n"
                    "rationale: test profile\nsurvivor_sde: 7.0\n")
                with self.assertRaises(CalibrationError):
                    load_profile("bulk_v9")
            finally:
                calibration.CALIBRATION_DIR = old

    def test_missing_registry_fails_load(self):
        with tempfile.TemporaryDirectory() as td:
            dest, old = _copy_cal_dir(td)
            try:
                (dest / "registry.json").unlink()
                with self.assertRaises(CalibrationError):
                    load_profile("bulk_v1")
            finally:
                calibration.CALIBRATION_DIR = old

    def test_v2_without_status_or_rationale_fails(self):
        # v2+ profiles must declare status + rationale IN THE
        # FILE (v1 is grandfathered through the registry instead
        # — the v1 files stay byte-identical).
        with tempfile.TemporaryDirectory() as td:
            dest, old = _copy_cal_dir(td)
            try:
                (dest / "bulk_v9.yaml").write_text(
                    "version: bulk_v9\nsurvivor_sde: 7.0\n")
                with self.assertRaises(CalibrationError):
                    load_profile("bulk_v9")
            finally:
                calibration.CALIBRATION_DIR = old

    def test_v2_with_fields_and_registry_entry_loads(self):
        with tempfile.TemporaryDirectory() as td:
            dest, old = _copy_cal_dir(td)
            try:
                (dest / "bulk_v9.yaml").write_text(
                    "version: bulk_v9\nstatus: experimental\n"
                    "rationale: test profile\nsurvivor_sde: 7.0\n")
                reg = json.loads(
                    (dest / "registry.json").read_text())
                reg["entries"].append(
                    calibration.registry_entry_for(
                        "bulk_v9", "experimental", "test profile",
                        supersedes="bulk_v1"))
                (dest / "registry.json").write_text(
                    json.dumps(reg, indent=2))
                prof = load_profile("bulk_v9")
                self.assertEqual(prof["version"], "bulk_v9")
                self.assertEqual(prof["status"], "experimental")
            finally:
                calibration.CALIBRATION_DIR = old


class TestRegistryDiff(unittest.TestCase):
    def _entry(self, sha="aaa", status="active",
               rationale="r", supersedes=None):
        return {"calibration_id": "bulk_v1", "sha256": sha,
                "status": status, "rationale": rationale,
                "supersedes": supersedes}

    def test_identical_registries_pass(self):
        old = {"bulk_v1": self._entry()}
        self.assertEqual(registry_diff(old, dict(old)), [])

    def test_appended_entry_passes(self):
        old = {"bulk_v1": self._entry()}
        new = dict(old)
        new["bulk_v2"] = self._entry(sha="bbb")
        self.assertEqual(registry_diff(old, new), [])

    def test_edited_hash_fails(self):
        old = {"bulk_v1": self._entry()}
        new = {"bulk_v1": self._entry(sha="bbb")}
        v = registry_diff(old, new)
        self.assertEqual(len(v), 1)
        self.assertIn("sha256", v[0])

    def test_edited_rationale_fails(self):
        old = {"bulk_v1": self._entry()}
        new = {"bulk_v1": self._entry(rationale="rewritten")}
        v = registry_diff(old, new)
        self.assertEqual(len(v), 1)
        self.assertIn("rationale", v[0])

    def test_removed_entry_fails(self):
        old = {"bulk_v1": self._entry()}
        v = registry_diff(old, {})
        self.assertEqual(len(v), 1)
        self.assertIn("REMOVED", v[0])


class TestCheckScript(unittest.TestCase):
    def test_verify_hashes_passes_on_real_repo(self):
        self.assertEqual(verify_hashes(ROOT), [])

    def test_end_to_end_in_temp_git_repo(self):
        # The full CI path in miniature: a temp repo with the
        # registry committed, then a tampered profile (hash guard)
        # and a rewritten registry entry (diff guard).
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "repo"
            (repo / "calibration").mkdir(parents=True)
            (repo / "scripts").mkdir()
            shutil.copytree(REAL_CAL, repo / "calibration",
                            dirs_exist_ok=True)
            shutil.copy(ROOT / "scripts" / "check_registry.py",
                        repo / "scripts" / "check_registry.py")
            env = {"PATH": "/usr/bin:/bin", "HOME": td,
                   "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                   "GIT_COMMITTER_NAME": "t",
                   "GIT_COMMITTER_EMAIL": "t@t"}
            def git(*a):
                return subprocess.run(["git", *a], cwd=repo,
                                      capture_output=True, text=True,
                                      env=env, timeout=30)
            git("init", "-b", "main")
            git("add", "-A")
            git("commit", "-qm", "base")
            script = repo / "scripts" / "check_registry.py"
            run = lambda *a: subprocess.run(
                [sys.executable, str(script), "--repo-root",
                 str(repo), *a], capture_output=True, text=True,
                timeout=60)
            # Clean tree: both guards pass.
            r = run("--base", "HEAD")
            self.assertEqual(r.returncode, 0, msg=r.stdout + r.stderr)
            # Tamper a profile: the hash guard fails.
            p = repo / "calibration" / "bulk_v1.yaml"
            p.write_text(p.read_text() + "\n# tamper\n")
            r = run("--base", "HEAD")
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("hash mismatch", r.stdout)
            # Restore the file, rewrite the registry entry instead:
            # the hash guard passes (entry matches the file) but
            # the diff guard catches the rewrite.
            git("checkout", "--", "calibration/bulk_v1.yaml")
            reg = json.loads(
                (repo / "calibration" / "registry.json").read_text())
            reg["entries"][0]["rationale"] = "rewritten history"
            (repo / "calibration" / "registry.json").write_text(
                json.dumps(reg, indent=2))
            r = run("--base", "HEAD")
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("rationale", r.stdout)


if __name__ == "__main__":
    unittest.main()
