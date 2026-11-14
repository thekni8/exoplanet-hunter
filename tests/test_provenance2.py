"""Provenance layer 2 tests (Phase 1.2, item A-2).

Layer 1 (1.1) stamped the code and the calibration labels. Layer 2
stamps the INPUTS and the CONTENT: the working-tree dirty flag, the
calibration content hash, the input identity (MAST products,
sectors, author, cadence, file and manifest hashes, BLS input
hash), and a fingerprint over the result-affecting files that the
resume check (A-3) depends on.
"""
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import calibration as cal  # noqa: E402
import provenance as prov  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
GIT_ENV = {"PATH": "/usr/bin:/bin", "HOME": "/tmp",
           "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


def _git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo,
                          capture_output=True, text=True,
                          env=GIT_ENV, timeout=30)


class TestFingerprint(unittest.TestCase):
    def _tree(self, td):
        root = Path(td)
        (root / "gauntlet").mkdir()
        (root / "bulk").mkdir()
        (root / "calibration").mkdir()
        (root / "schema").mkdir()
        (root / "tests").mkdir()
        (root / "bulk_screen.py").write_text("SCREEN = 1\n")
        (root / "gauntlet" / "verdict.py").write_text("V = 1\n")
        (root / "bulk" / "run_chunked.py").write_text("C = 1\n")
        # F-6: the named result-affecting file classes — the
        # deep pipeline, the clip, and the stage logic.
        (root / "hunter.py").write_text("HUNTER = 1\n")
        (root / "mad_clip.py").write_text("CLIP = 1\n")
        (root / "gauntlet" / "stage_result.py").write_text(
            "STAGE = 1\n")
        (root / "gauntlet" / "runner.py").write_text("RUN = 1\n")
        (root / "calibration" / "bulk_v1.yaml").write_text(
            "version: bulk_v1\n")
        (root / "schema" / "survivor-schema.json").write_text("{}\n")
        (root / "tests" / "test_x.py").write_text("pass\n")
        (root / "README.md").write_text("docs\n")
        return root

    def test_deterministic(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._tree(td)
            self.assertEqual(prov.fingerprint_result_affecting(root),
                             prov.fingerprint_result_affecting(root))

    def test_code_change_changes_fingerprint(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._tree(td)
            before = prov.fingerprint_result_affecting(root)
            (root / "bulk_screen.py").write_text("SCREEN = 2\n")
            self.assertNotEqual(
                before, prov.fingerprint_result_affecting(root))

    def test_calibration_change_changes_fingerprint(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._tree(td)
            before = prov.fingerprint_result_affecting(root)
            (root / "calibration" / "bulk_v1.yaml").write_text(
                "version: bulk_v1\nsurvivor_sde: 9.0\n")
            self.assertNotEqual(
                before, prov.fingerprint_result_affecting(root))

    def test_schema_change_changes_fingerprint(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._tree(td)
            before = prov.fingerprint_result_affecting(root)
            (root / "schema" / "survivor-schema.json").write_text(
                '{"x": 1}\n')
            self.assertNotEqual(
                before, prov.fingerprint_result_affecting(root))

    def test_docs_and_tests_do_not_change_fingerprint(self):
        # The property A-3 depends on: a docs-only or test-only
        # commit must not force a resume refusal.
        with tempfile.TemporaryDirectory() as td:
            root = self._tree(td)
            before = prov.fingerprint_result_affecting(root)
            (root / "README.md").write_text("rewritten docs\n")
            (root / "tests" / "test_x.py").write_text("pass\npass\n")
            self.assertEqual(
                before, prov.fingerprint_result_affecting(root))

    def test_real_repo_fingerprint_is_stable(self):
        self.assertEqual(prov.fingerprint_result_affecting(),
                         prov.fingerprint_result_affecting())

    def test_named_file_classes_move_fingerprint(self):
        # F-6: the fingerprint is not just "some file changed" —
        # each NAMED result-affecting class moves it: the deep
        # pipeline (hunter.py: BLS/detrend), the clip
        # (mad_clip.py), and the stage logic
        # (gauntlet/stage_result.py + gauntlet/runner.py). A
        # future refactor that moved one of these files out of
        # the hashed globs would fail here, not silently.
        named = {"hunter.py": "HUNTER = 2\n",
                 "mad_clip.py": "CLIP = 2\n",
                 "gauntlet/stage_result.py": "STAGE = 2\n",
                 "gauntlet/runner.py": "RUN = 2\n"}
        for rel, new_text in named.items():
            with self.subTest(file=rel):
                with tempfile.TemporaryDirectory() as td:
                    root = self._tree(td)
                    before = prov.fingerprint_result_affecting(
                        root)
                    (root / rel).write_text(new_text)
                    self.assertNotEqual(
                        before,
                        prov.fingerprint_result_affecting(root))


class TestWorkingTreeClean(unittest.TestCase):
    def test_clean_dirty_and_non_git(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "repo"
            repo.mkdir()
            _git(repo, "init", "-b", "main")
            (repo / "a.py").write_text("x = 1\n")
            _git(repo, "add", "-A")
            _git(repo, "commit", "-qm", "base")
            self.assertTrue(prov.working_tree_clean(repo))
            (repo / "a.py").write_text("x = 2\n")
            # The cache assumes the tree does not change mid-run;
            # a new run re-reads it.
            prov.working_tree_clean.cache_clear()
            self.assertFalse(prov.working_tree_clean(repo))
            plain = Path(td) / "plain"
            plain.mkdir()
            self.assertIsNone(prov.working_tree_clean(plain))

    def test_git_dirty_is_the_complement(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "repo"
            repo.mkdir()
            _git(repo, "init", "-b", "main")
            (repo / "a.py").write_text("x = 1\n")
            _git(repo, "add", "-A")
            _git(repo, "commit", "-qm", "base")
            self.assertFalse(prov.git_dirty(repo))
            (repo / "a.py").write_text("x = 2\n")
            prov.working_tree_clean.cache_clear()
            self.assertTrue(prov.git_dirty(repo))
            plain = Path(td) / "plain"
            plain.mkdir()
            self.assertIsNone(prov.git_dirty(plain))


class TestBlsInputHash(unittest.TestCase):
    def test_deterministic_and_sensitive(self):
        import numpy as np
        t = np.arange(1000, dtype=np.float64)
        f = np.ones(1000) - 0.01 * np.exp(-((t - 500) ** 2) / 10)
        h1 = prov.bls_input_hash(t, f)
        h2 = prov.bls_input_hash(t.copy(), f.copy())
        self.assertEqual(h1, h2)
        f2 = f.copy()
        f2[500] += 1e-9
        self.assertNotEqual(h1, prov.bls_input_hash(t, f2))
        self.assertNotEqual(h1, prov.bls_input_hash(t[:999], f[:999]))


class TestInputIdentity(unittest.TestCase):
    def test_omits_nones_and_flags_fixtures(self):
        ident = prov.input_identity(product_ids=["a", "b"],
                                    sectors=[96, 97],
                                    author="SPOC", cadence_s=120.0,
                                    bls_input_hash="deadbeef")
        self.assertEqual(ident["product_ids"], ["a", "b"])
        self.assertEqual(ident["sectors"], [96, 97])
        self.assertEqual(ident["author"], "SPOC")
        self.assertEqual(ident["cadence_s"], 120.0)
        self.assertNotIn("input_file_sha256", ident)
        self.assertNotIn("fixture", ident)
        fx = prov.input_identity(fixture=True,
                                 product_ids=["fixture:TIC_1"])
        self.assertTrue(fx["fixture"])


class TestCalibrationContentHash(unittest.TestCase):
    def test_matches_registry_hash(self):
        # The content hash is built from the same file hashes the
        # registry pins — the two systems agree by construction.
        expected = hashlib.sha256(
            prov.canonical_json(
                {"bulk": cal.profile_sha256("bulk_v1")}).encode(
                    "utf-8")).hexdigest()
        self.assertEqual(
            prov.calibration_content_hash({"bulk": "v1"}),
            expected)

    def test_changes_when_profile_bytes_change(self):
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "calibration"
            dest.mkdir()
            src = ROOT / "calibration" / "bulk_v1.yaml"
            (dest / "bulk_v1.yaml").write_text(src.read_text())
            old = cal.CALIBRATION_DIR
            cal.CALIBRATION_DIR = dest
            try:
                before = prov.calibration_content_hash(
                    {"bulk": "v1"})
                (dest / "bulk_v1.yaml").write_text(
                    src.read_text() + "\n# comment\n")
                after = prov.calibration_content_hash(
                    {"bulk": "v1"})
                self.assertNotEqual(before, after)
            finally:
                cal.CALIBRATION_DIR = old

    def test_header_and_manifest_carry_it(self):
        h = prov.provenance_header("r1", {"bulk": "v1"})
        self.assertEqual(
            h["calibration_sha256"],
            prov.calibration_content_hash({"bulk": "v1"}))
        m = prov.build_manifest(
            "r1", {"bulk": "v1"}, sector=96, product="QLP",
            input_identity=prov.input_identity(
                product_ids=["p1"], sectors=[96]))
        self.assertEqual(m["calibration"]["versions"],
                         {"bulk": "v1"})
        self.assertEqual(
            m["calibration"]["sha256"],
            prov.calibration_content_hash({"bulk": "v1"}))
        self.assertEqual(
            m["calibration"]["hashes"]["bulk"],
            cal.profile_sha256("bulk_v1"))
        self.assertIn("working_tree_clean", m["execution"])
        self.assertEqual(m["data"]["input_identity"]["sectors"],
                         [96])


class TestBulkScreenIdentity(unittest.TestCase):
    def test_screened_survivor_carries_input_identity(self):
        # A real screen record, through the production emit path,
        # carries the input identity — and still validates.
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from bulk_screen import _screen_one, emit_survivor_record
        from synth_fits import make_qlp_fits, screen_job
        from validation import validate_survivor
        with tempfile.TemporaryDirectory() as td:
            p = make_qlp_fits(Path(td) / "planet.fits", period_d=2.5,
                              depth_frac=0.01, duration_d=0.1,
                              noise_pct=0.003, seed=42)
            raw = _screen_one(screen_job(p))
            self.assertEqual(raw["status"], "survivor")
            ident = raw["input_identity"]
            self.assertEqual(ident["product_ids"], ["planet.fits"])
            self.assertEqual(ident["sectors"], [1])
            self.assertEqual(ident["author"], "QLP")
            self.assertEqual(len(ident["bls_input_hash"]), 64)
            # Survivors only: the input file hash.
            self.assertEqual(ident["input_file_sha256"],
                             prov.file_sha256(p))
            h = prov.provenance_header(
                "test-run-1", {"bulk": "v1"}, sha="abc1234",
                timestamp_utc="2026-11-14T06:00:00+00:00")
            validate_survivor(emit_survivor_record(raw, h))


class TestHunterIdentity(unittest.TestCase):
    def test_fixture_run_carries_input_identity(self):
        # The deep pipeline on the TOI-700 fixture: marked as a
        # fixture, with the BLS input hash of the arrays that
        # actually entered BLS (recomputed from the flat arrays
        # the pipeline returned).
        import os
        import hunter
        fx_dir = (Path(__file__).resolve().parent / "fixtures"
                  / "golden")
        prev = os.environ.get("EXHUNT_FIXTURE_DIR")
        os.environ["EXHUNT_FIXTURE_DIR"] = str(fx_dir)
        try:
            full = hunter._run_pipeline("150428135",
                                        star_radius=0.42,
                                        max_sectors=2)
        finally:
            if prev is None:
                os.environ.pop("EXHUNT_FIXTURE_DIR", None)
            else:
                os.environ["EXHUNT_FIXTURE_DIR"] = prev
        ident = full["input_identity"]
        self.assertTrue(ident["fixture"])
        self.assertEqual(ident["product_ids"],
                         ["fixture:TIC_150428135"])
        self.assertEqual(
            ident["bls_input_hash"],
            prov.bls_input_hash(full["flat_time"],
                                full["flat_flux"]))
        out = hunter.full_result_to_json_dict(full)
        self.assertEqual(out["metrics"]["input_identity"], ident)


if __name__ == "__main__":
    unittest.main()
