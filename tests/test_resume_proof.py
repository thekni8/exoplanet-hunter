"""Driver-level resume-fingerprint proof (Phase 1.2 follow-up F-6).

test_provenance2 proves the fingerprint MOVES when
result-affecting files change; test_run_fingerprint proves a
TAMPERED checkpoint refuses. What neither proves is the driver's
own accept/refuse decisions on a LIVE checkpoint: a docs edit
must ACCEPT (resume completes, slices not re-screened), a
code/calibration/schema edit must REFUSE with the fingerprint
message. These tests run the driver twice from a throwaway repo
copy (the canary's _copy_tree pattern — mutations never touch
the real tree), with the stub screen behind EXHUNT_SCREEN_CMD:
no downloads, no network.

Every driver run passes --allow-v1 (sector 999 under bulk_v1;
valid today, required after F-15 gates run_chunked).
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent
                       / "scripts"))

from mutation_canaries import _copy_tree, _rehash_registry  # noqa: E402
from tests.test_resume import (  # noqa: E402
    EXPECTED_SURVIVORS, _build_workdir, _invocations,
    _merged_survivors, _run_driver)


def _run_copy_driver(copy_root, work, recipe, stub_log,
                     timeout=180):
    """Run the throwaway copy's driver to completion. Returns
    (returncode, stdout+stderr)."""
    env = dict(os.environ)
    env["EXHUNT_SCREEN_CMD"] = (
        f"{sys.executable} {copy_root / 'tests' / 'stub_screen.py'}"
        f" --sleep 0")
    env["EXHUNT_STUB_LOG"] = str(stub_log)
    cmd = [sys.executable,
           str(copy_root / "bulk" / "run_chunked.py"),
           "--recipe", str(recipe), "--work-dir", str(work),
           "--skip-known-filter", "--allow-v1"]
    r = subprocess.run(cmd, capture_output=True, text=True,
                       env=env, timeout=timeout)
    return r.returncode, r.stdout + r.stderr


class TestResumeProof(unittest.TestCase):
    def _first_run(self, td):
        """Copy the repo, run the driver to completion in the
        copy. Returns (copy_root, work, recipe, stub_log)."""
        copy_root = _copy_tree()
        self.addCleanup(shutil.rmtree, copy_root.parent,
                        True)
        work, recipe = _build_workdir(td)
        stub_log = Path(td) / "invocations.log"
        rc, out = _run_copy_driver(copy_root, work, recipe,
                                   stub_log)
        self.assertEqual(rc, 0, msg=out[-2000:])
        self.assertEqual(len(_invocations(stub_log)), 3)
        return copy_root, work, recipe, stub_log

    def test_docs_edit_accepts_resume(self):
        # A .md edit moves neither fingerprint: the second run
        # resumes from the live checkpoint, completes, and
        # re-screens NOTHING.
        with tempfile.TemporaryDirectory() as td:
            copy_root, work, recipe, stub_log = self._first_run(td)
            readme = copy_root / "README.md"
            readme.write_text(readme.read_text()
                              + "\n<!-- docs-only change -->\n")
            rc, out = _run_copy_driver(copy_root, work, recipe,
                                       stub_log)
            self.assertEqual(rc, 0, msg=out[-2000:])
            self.assertEqual(len(_invocations(stub_log)), 3,
                             "a docs edit must not re-screen")
            got = [r["tic"]
                   for r in _merged_survivors(work / "run_s0999")]
            self.assertEqual(got, EXPECTED_SURVIVORS)

    def test_hunter_edit_refuses_resume(self):
        # A code edit (hunter.py: BLS/detrend) moves the resume
        # fingerprint: the driver refuses with the fingerprint
        # message, exit 1.
        with tempfile.TemporaryDirectory() as td:
            copy_root, work, recipe, stub_log = self._first_run(td)
            hunter = copy_root / "hunter.py"
            hunter.write_text(hunter.read_text()
                              + "\n# comment-only code edit\n")
            rc, out = _run_copy_driver(copy_root, work, recipe,
                                       stub_log)
            self.assertEqual(rc, 1, msg=out[-2000:])
            self.assertIn("REFUSING TO RESUME", out)
            self.assertIn("resume fingerprint mismatch", out)
            self.assertEqual(len(_invocations(stub_log)), 3,
                             "a refused resume screens nothing")

    def test_calibration_edit_refuses_resume(self):
        # A calibration edit moves the resume fingerprint too.
        # The registry is re-hashed after the edit (the canary's
        # post step) so the refusal is the RESUME fingerprint,
        # not the registry hash check.
        with tempfile.TemporaryDirectory() as td:
            copy_root, work, recipe, stub_log = self._first_run(td)
            prof = copy_root / "calibration" / "bulk_v1.yaml"
            text = prof.read_text()
            self.assertIn("survivor_sde: 7.0", text)
            prof.write_text(text.replace("survivor_sde: 7.0",
                                         "survivor_sde: 7.1"))
            err = _rehash_registry(copy_root)
            self.assertIsNone(err, msg=err)
            rc, out = _run_copy_driver(copy_root, work, recipe,
                                       stub_log)
            self.assertEqual(rc, 1, msg=out[-2000:])
            self.assertIn("REFUSING TO RESUME", out)
            self.assertIn("resume fingerprint mismatch", out)

    def test_schema_edit_refuses_resume(self):
        # A schema edit moves the resume fingerprint. The edit
        # is description text only — it cannot change validation
        # behaviour, so the refusal is the fingerprint.
        with tempfile.TemporaryDirectory() as td:
            copy_root, work, recipe, stub_log = self._first_run(td)
            schema = copy_root / "schema" / "survivor-schema.json"
            text = schema.read_text()
            old = "One line of survivors.jsonl as written by bulk_screen.py."
            self.assertIn(old, text)
            schema.write_text(text.replace(
                old, old + " (description edit)"))
            rc, out = _run_copy_driver(copy_root, work, recipe,
                                       stub_log)
            self.assertEqual(rc, 1, msg=out[-2000:])
            self.assertIn("REFUSING TO RESUME", out)
            self.assertIn("resume fingerprint mismatch", out)

    def test_second_run_resumes_own_checkpoint(self):
        # The cheap control on the real repo: run the driver
        # twice on the same work dir — the second run resumes
        # from its own checkpoint with the live resume
        # fingerprint, completes, and re-screens nothing.
        with tempfile.TemporaryDirectory() as td:
            work, recipe = _build_workdir(td)
            stub_log = Path(td) / "invocations.log"
            rc, out = _run_driver(work, recipe, stub_log,
                                  extra_args=("--allow-v1",))
            self.assertEqual(rc, 0, msg=out[-2000:])
            self.assertEqual(len(_invocations(stub_log)), 3)
            rc, out = _run_driver(work, recipe, stub_log,
                                  extra_args=("--allow-v1",))
            self.assertEqual(rc, 0, msg=out[-2000:])
            self.assertEqual(len(_invocations(stub_log)), 3,
                             "the second run must not re-screen")
            got = [r["tic"]
                   for r in _merged_survivors(work / "run_s0999")]
            self.assertEqual(got, EXPECTED_SURVIVORS)


if __name__ == "__main__":
    unittest.main()
