"""Unit tests for provenance headers + run manifests (provenance.py).

No downloads. Guards the Phase 1.1 item-1 contract: every output
record carries schema_version, run_id, pipeline_git_sha,
calibration_version, timestamp_utc, and (for recipe-driven runs)
the hash of the RESOLVED recipe — stamped at write time, never
reconstructed afterwards.
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import provenance as prov  # noqa: E402
from bulk_screen import emit_survivor_record  # noqa: E402


class TestProvenanceHeader(unittest.TestCase):
    def test_header_has_all_required_keys(self):
        h = prov.provenance_header("bulk-test-1", "bulk_v1")
        for key in ("schema_version", "run_id", "pipeline_git_sha",
                    "calibration_version", "timestamp_utc"):
            self.assertIn(key, h)
        self.assertEqual(h["schema_version"], prov.SCHEMA_VERSION)
        self.assertEqual(h["run_id"], "bulk-test-1")
        self.assertEqual(h["calibration_version"], "bulk_v1")

    def test_header_is_deterministic_with_explicit_inputs(self):
        # Same inputs -> same header. The determinism test (item 9)
        # depends on this: provenance is injected, never read from
        # the clock inside the writer.
        kw = {"run_id": "r1", "calibration_version": "bulk_v1",
              "sha": "abc1234", "timestamp_utc": "2026-11-14T06:00:00+00:00"}
        self.assertEqual(prov.provenance_header(**kw),
                         prov.provenance_header(**kw))

    def test_recipe_hash_omitted_when_no_recipe(self):
        h = prov.provenance_header("r1", "bulk_v1")
        self.assertNotIn("recipe_hash", h)
        h2 = prov.provenance_header("r1", "bulk_v1",
                                    recipe_hash="deadbeef")
        self.assertEqual(h2["recipe_hash"], "deadbeef")

    def test_git_sha_matches_repo(self):
        # In this repo git is available: the stamped SHA must be the
        # real HEAD, not a placeholder.
        expected = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=prov.repo_root(), capture_output=True, text=True,
            timeout=10).stdout.strip()
        self.assertEqual(prov.git_sha(), expected)
        self.assertNotEqual(prov.git_sha(), "unknown")

    def test_run_id_format_and_uniqueness(self):
        a = prov.new_run_id("bulk")
        b = prov.new_run_id("bulk")
        self.assertTrue(a.startswith("bulk-"), a)
        self.assertNotEqual(a, b)


class TestRecipeHash(unittest.TestCase):
    def test_stable_and_order_insensitive(self):
        r1 = {"sector": 96, "window": {"min_mag": 10.0, "max_mag": 13.5},
              "tag": "t", "slice_size": 1250, "dl_workers": 8,
              "workers": None}
        r2 = {"workers": None, "dl_workers": 8, "slice_size": 1250,
              "tag": "t", "window": {"max_mag": 13.5, "min_mag": 10.0},
              "sector": 96}
        self.assertEqual(prov.recipe_hash(r1), prov.recipe_hash(r2))

    def test_changes_when_a_value_changes(self):
        base = {"sector": 96, "window": {"min_mag": 10.0}}
        changed = {"sector": 96, "window": {"min_mag": 9.0}}
        self.assertNotEqual(prov.recipe_hash(base),
                            prov.recipe_hash(changed))

    def test_ignores_internal_keys(self):
        # "_file" is where the recipe lived on this machine — it must
        # not change the hash of what ran.
        base = {"sector": 96}
        with_file = {"sector": 96,
                     "_file": "/somewhere/bulk/recipes/sector-96.yaml"}
        self.assertEqual(prov.recipe_hash(base),
                         prov.recipe_hash(with_file))


class TestEmitAndManifest(unittest.TestCase):
    def test_emit_merges_provenance_and_drops_nones(self):
        rec = {"tic": 123, "sector": 96, "product": "QLP",
               "status": "survivor", "sde": 9.5, "period_days": 2.5,
               "ra": None, "flags": []}
        h = prov.provenance_header(
            "r1", "bulk_v1", sha="abc1234",
            timestamp_utc="2026-11-14T06:00:00+00:00")
        out = emit_survivor_record(rec, h)
        self.assertEqual(out["tic"], 123)
        self.assertEqual(out["run_id"], "r1")
        self.assertEqual(out["pipeline_git_sha"], "abc1234")
        self.assertEqual(out["calibration_version"], "bulk_v1")
        self.assertNotIn("ra", out)  # None-valued fields are dropped
        self.assertIn("flags", out)  # ...but empty lists are kept

    def test_manifest_round_trip(self):
        with tempfile.TemporaryDirectory() as td:
            m = prov.build_manifest(
                "bulk-test-1", "bulk_v1", sector=96, product="QLP",
                sha="abc1234",
                timestamp_utc="2026-11-14T06:00:00+00:00")
            p = prov.write_manifest(td, m)
            back = json.loads(Path(p).read_text())
            self.assertEqual(back["run_id"], "bulk-test-1")
            self.assertEqual(back["pipeline"]["git_sha"], "abc1234")
            self.assertEqual(back["calibration"]["version"], "bulk_v1")
            self.assertEqual(back["data"]["sector"], 96)
            self.assertEqual(back["execution"]["status"], "started")


if __name__ == "__main__":
    unittest.main()
