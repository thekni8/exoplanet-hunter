"""Frozen v1 records + 1.2-format validation (Phase 1.2, item A-2).

The 1.2 schemas must accept BOTH shapes: frozen 1.1 records (scalar
calibration_version, schema_version "1.1", no new fields) and new
1.2 records (per-subsystem calibration map, working_tree_clean,
calibration_sha256, input_identity). The fixtures in
tests/fixtures/v1_records/ are byte-frozen 1.1 records — they must
never be edited to make the suite green; if they stop validating,
the schema broke backward compatibility.
"""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from validation import validate_survivor, validate_verdict  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "v1_records"


class TestFrozenV1Records(unittest.TestCase):
    def test_v1_survivor_still_validates(self):
        rec = json.loads((FIXTURES / "survivor_v1.json").read_text())
        self.assertEqual(rec["schema_version"], "1.1")
        self.assertEqual(rec["calibration_version"], "bulk_v1")
        validate_survivor(rec)

    def test_v1_verdict_still_validates(self):
        rec = json.loads((FIXTURES / "verdict_v1.json").read_text())
        self.assertEqual(rec["schema_version"], "1.1")
        self.assertEqual(rec["calibration_version"], "gauntlet_v1")
        validate_verdict(rec)


class TestV12Records(unittest.TestCase):
    def test_v12_survivor_validates(self):
        rec = json.loads((FIXTURES / "survivor_v1.json").read_text())
        rec["schema_version"] = "1.2"
        rec["calibration_version"] = {"bulk": "v1"}
        rec["working_tree_clean"] = True
        rec["calibration_sha256"] = "a" * 64
        rec["input_identity"] = {
            "product_ids": ["tess2020000000000-s0096-0000000382069441"
                            "-0016-s_lc.fits"],
            "sectors": [96], "author": "QLP", "cadence_s": 120.0,
            "input_file_sha256": "b" * 64,
            "bls_input_hash": "c" * 64}
        validate_survivor(rec)

    def test_v12_verdict_validates(self):
        rec = json.loads((FIXTURES / "verdict_v1.json").read_text())
        rec["schema_version"] = "1.2"
        rec["calibration_version"] = {"gauntlet": "v1"}
        rec["working_tree_clean"] = False
        rec["calibration_sha256"] = "a" * 64
        validate_verdict(rec)

    def test_null_working_tree_clean_validates(self):
        # git unavailable (source export) — the field is null,
        # never a silent lie about the tree state.
        rec = json.loads((FIXTURES / "survivor_v1.json").read_text())
        rec["working_tree_clean"] = None
        validate_survivor(rec)


if __name__ == "__main__":
    unittest.main()
