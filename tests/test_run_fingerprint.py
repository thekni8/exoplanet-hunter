"""Tests for the run fingerprint (Phase 1.2, C-8).

One hash identifying a run's full computation — code SHA +
dirty flag + calibration hash + resolved recipe + window-file
hash + env hash + input IDs — plus the resume subset that
excludes the git SHA and the dirty flag (a docs-only commit or
a stray untracked file must not refuse a legitimate resume).
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import provenance as prov  # noqa: E402
from tests.test_resume import (  # noqa: E402
    _build_workdir, _run_driver)

ROOT = Path(__file__).resolve().parent.parent


def _components(**overrides):
    base = {
        "code_fingerprint": "a" * 64,
        "calibration_hash": "b" * 64,
        "recipe_hash": "c" * 64,
        "window_sha256": "d" * 64,
        "env_hash": "e" * 64,
        "input_ids": ["100000002", "100000005"],
        "git_sha": "abc1234",
        "working_tree_clean": True,
    }
    base.update(overrides)
    return base


class TestRunFingerprint(unittest.TestCase):
    def test_deterministic(self):
        c = _components()
        self.assertEqual(prov.run_fingerprint(c),
                         prov.run_fingerprint(_components()))
        self.assertEqual(prov.resume_fingerprint(c),
                         prov.resume_fingerprint(_components()))
        self.assertEqual(len(prov.run_fingerprint(c)), 64)
        self.assertEqual(len(prov.resume_fingerprint(c)), 64)

    def test_each_result_component_moves_both_hashes(self):
        base = _components()
        full0 = prov.run_fingerprint(base)
        resume0 = prov.resume_fingerprint(base)
        for key in prov.RESUME_FINGERPRINT_KEYS:
            with self.subTest(component=key):
                changed = _components(**{key: "f" * 64
                                         if key != "input_ids"
                                         else ["999999999"]})
                self.assertNotEqual(prov.run_fingerprint(changed),
                                    full0)
                self.assertNotEqual(
                    prov.resume_fingerprint(changed), resume0)

    def test_git_sha_moves_full_not_resume(self):
        # The A-3 problem, restated for the fingerprint: a
        # docs-only commit changes the SHA but not results.
        base = _components()
        changed = _components(git_sha="def5678")
        self.assertNotEqual(prov.run_fingerprint(changed),
                            prov.run_fingerprint(base))
        self.assertEqual(prov.resume_fingerprint(changed),
                         prov.resume_fingerprint(base))

    def test_dirty_flag_moves_full_not_resume(self):
        base = _components()
        changed = _components(working_tree_clean=False)
        self.assertNotEqual(prov.run_fingerprint(changed),
                            prov.run_fingerprint(base))
        self.assertEqual(prov.resume_fingerprint(changed),
                         prov.resume_fingerprint(base))

    def test_fingerprint_block_round_trips(self):
        block = prov.fingerprint_block(
            calibration_versions={"bulk": "v1"})
        self.assertEqual(block["full"],
                         prov.run_fingerprint(block["components"]))
        self.assertEqual(block["resume"],
                         prov.resume_fingerprint(
                             block["components"]))
        self.assertEqual(
            block["components"]["calibration_hash"],
            prov.calibration_content_hash({"bulk": "v1"}))
        self.assertEqual(
            block["components"]["code_fingerprint"],
            prov.fingerprint_result_affecting())

    def test_build_manifest_carries_fingerprint(self):
        m = prov.build_manifest(
            "test-run-1", {"bulk": "v1"}, sector=999,
            recipe={"sector": 999, "tag": "t"},
            code_fingerprint="a" * 64)
        block = m["fingerprint"]
        self.assertEqual(block["full"],
                         prov.run_fingerprint(block["components"]))
        self.assertEqual(block["components"]["code_fingerprint"],
                         "a" * 64)
        self.assertEqual(block["components"]["git_sha"],
                         m["pipeline"]["git_sha"])

    def test_env_hash_deterministic(self):
        self.assertEqual(prov.env_hash(), prov.env_hash())
        self.assertEqual(len(prov.env_hash()), 64)


class TestResumeFingerprintCheck(unittest.TestCase):
    def test_resume_refuses_tampered_resume_fingerprint(self):
        # A checkpoint whose resume fingerprint was altered
        # refuses — even though its code fingerprint is still
        # valid, the resume fingerprint takes precedence.
        with tempfile.TemporaryDirectory() as td:
            work, recipe = _build_workdir(td)
            stub_log = Path(td) / "stub.log"
            rc, _out = _run_driver(work, recipe, stub_log)
            self.assertEqual(rc, 0)
            run = work / "run_s0999"
            cp_path = run / "checkpoint.json"
            cp = json.loads(cp_path.read_text())
            self.assertIn("resume_fingerprint", cp)
            self.assertIn("run_fingerprint", cp)
            tampered = cp["resume_fingerprint"]
            tampered = ("0" if tampered[0] != "0" else "1") \
                + tampered[1:]
            cp["resume_fingerprint"] = tampered
            cp_path.write_text(json.dumps(cp))
            rc, out = _run_driver(work, recipe, stub_log)
            self.assertEqual(rc, 1)
            self.assertIn("REFUSING TO RESUME", out)
            self.assertIn("resume fingerprint mismatch", out)

    def test_accept_flag_resumes_across_fingerprint_change(self):
        with tempfile.TemporaryDirectory() as td:
            work, recipe = _build_workdir(td)
            stub_log = Path(td) / "stub.log"
            rc, _out = _run_driver(work, recipe, stub_log)
            self.assertEqual(rc, 0)
            run = work / "run_s0999"
            cp_path = run / "checkpoint.json"
            cp = json.loads(cp_path.read_text())
            tampered = cp["resume_fingerprint"]
            cp["resume_fingerprint"] = (
                ("0" if tampered[0] != "0" else "1")
                + tampered[1:])
            cp_path.write_text(json.dumps(cp))
            rc, out = _run_driver(
                work, recipe, stub_log,
                extra_args=["--accept-code-change"])
            self.assertEqual(rc, 0)
            self.assertIn("WARNING: resuming across", out)
            summary = json.loads(
                (run / "summary.json").read_text())
            self.assertTrue(summary["mixed_pipeline"])


if __name__ == "__main__":
    unittest.main()
