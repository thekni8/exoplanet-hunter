"""Ledger tests (Phase 1.2, item C-3).

The ledger is the durable per-sector record (counts + survivor
TICs + calibration + fingerprint) that makes "0 in ~111,000"
auditable without the Mac's raw run data. These tests build
ledgers from synthetic run dirs — the stub driver's outputs
(the real summary / manifest / checkpoint shapes) and
hand-built minimal run dirs — never from real run data.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import provenance as prov  # noqa: E402
from bulk import build_ledger  # noqa: E402
from tests.test_resume import (  # noqa: E402
    EXPECTED_SURVIVORS, _build_workdir, _run_driver)


def _stub_run(td):
    """A completed stub-driver run. Returns the run dir."""
    work, recipe = _build_workdir(td)
    rc, out = _run_driver(work, recipe, Path(td) / "inv.log")
    assert rc == 0, out[-2000:]
    return work / "run_s0999"


class TestBuildLedger(unittest.TestCase):
    def test_ledger_from_stub_run(self):
        with tempfile.TemporaryDirectory() as td:
            run = _stub_run(td)
            ledger = build_ledger.build_ledger(999, run)
            self.assertEqual(ledger["sector"], 999)
            self.assertEqual(ledger["schema_version"], "1.0")
            counts = ledger["counts"]
            self.assertEqual(counts["window"], 10)
            self.assertEqual(counts["searched"], 10)
            self.assertEqual(counts["survivors"], 3)
            self.assertEqual(counts["survivor_tiers"],
                             {"A": 2, "B": 1})
            self.assertEqual(counts["download"]["cached"], 10)
            self.assertEqual(
                [e["tic"] for e in ledger["survivors"]],
                EXPECTED_SURVIVORS)
            tiers = {e["tic"]: e["tier"]
                     for e in ledger["survivors"]}
            self.assertEqual(tiers, {"100000002": "A",
                                     "100000005": "B",
                                     "100000008": "A"})
            self.assertEqual(ledger["calibration"]["versions"],
                             {"bulk": "v1"})
            # A v1 run carries its known defect on its face.
            self.assertEqual(ledger["known_defects"],
                             ["mad_clip_no_floor"])
            # C-8: the stub run's manifest carries the full run
            # fingerprint block — full + resume hashes + the
            # components, which name the live code fingerprint.
            fp = ledger["fingerprint"]
            self.assertEqual(len(fp["full"]), 64)
            self.assertEqual(len(fp["resume"]), 64)
            self.assertEqual(
                fp["components"]["code_fingerprint"],
                prov.fingerprint_result_affecting())
            self.assertIsNotNone(
                fp["components"]["recipe_hash"])
            self.assertFalse(fp["mixed_pipeline"])
            self.assertTrue(ledger["conservation"]["ok"])
            self.assertEqual(ledger["run_status"], "completed")
            self.assertIsNone(ledger["rescore"])

    def test_sector_mismatch_refused(self):
        with tempfile.TemporaryDirectory() as td:
            run = _stub_run(td)
            with self.assertRaises(SystemExit):
                build_ledger.build_ledger(98, run)

    def test_missing_summary_refused(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(SystemExit):
                build_ledger.build_ledger(96, Path(td))

    def test_deterministic_except_generated_at(self):
        with tempfile.TemporaryDirectory() as td:
            run = _stub_run(td)
            a = build_ledger.build_ledger(999, run)
            b = build_ledger.build_ledger(999, run)
            a.pop("generated_at")
            b.pop("generated_at")
            self.assertEqual(a, b)

    def test_cli_writes_the_file(self):
        with tempfile.TemporaryDirectory() as td:
            run = _stub_run(td)
            out = Path(td) / "ledger.json"
            rc = build_ledger.main(["--sector", "999",
                                    "--run-dir", str(run),
                                    "--out", str(out)])
            self.assertEqual(rc, 0)
            ledger = json.loads(out.read_text())
            self.assertEqual(ledger["sector"], 999)
            self.assertEqual(len(ledger["survivors"]), 3)

    def test_legacy_string_calibration_normalised(self):
        with tempfile.TemporaryDirectory() as td:
            run = Path(td) / "run"
            run.mkdir()
            (run / "summary.json").write_text(json.dumps({
                "sector": 96, "stars_in": 5, "stars_searched": 5,
                "hits_recorded": 1, "survivors": 1,
                "survivor_tiers": {"A": 1, "B": 0},
                "screen_counts": {"survivor": 1, "recorded": 4},
                "survivor_tics": ["111"],
                "provenance": {
                    "run_id": "legacy", "calibration_version":
                    "bulk_v1", "pipeline_git_sha": "abc",
                    "recipe_hash": "d" * 64}}))
            (run / "survivors.jsonl").write_text(
                '{"tic": "111", "tier": "A"}\n')
            ledger = build_ledger.build_ledger(96, run)
            self.assertEqual(ledger["calibration"]["versions"],
                             {"bulk": "v1"})
            self.assertEqual(ledger["known_defects"],
                             ["mad_clip_no_floor"])
            self.assertEqual(ledger["survivors"],
                             [{"tic": "111", "tier": "A"}])
            # No manifest / checkpoint: those fields are None,
            # not a crash.
            self.assertIsNone(
                ledger["fingerprint"]["code_fingerprint"])
            self.assertIsNone(ledger["run_status"])


def _rescore_dir(td, sector=999, dry_run=False, survivors=()):
    """A synthetic rescore_v2 output dir."""
    d = Path(td) / "rescore"
    d.mkdir(parents=True, exist_ok=True)
    (d / "summary.json").write_text(json.dumps({
        "tool": "rescore_v2", "sector": sector,
        "calibration_version": "bulk_v2",
        "n_candidates": len(survivors), "n_rescreened": 2,
        "n_survivors": len(survivors), "n_errors": 0,
        "dry_run": dry_run, "run_id": "rescore-test"}))
    with open(d / f"rescore_v2_s{sector:04d}.jsonl", "w") as fh:
        for tic, tier in survivors:
            fh.write(json.dumps({"tic": tic, "tier": tier,
                                 "superseded_by": "bulk_v2"})
                     + "\n")
    return d


class TestRescoreMerge(unittest.TestCase):
    def test_merge_marks_superseded_and_adds_new(self):
        with tempfile.TemporaryDirectory() as td:
            run = _stub_run(td)
            # 100000002 is a v1 survivor (re-scored); 100000011
            # is a star v1 missed entirely (new v2 survivor).
            rd = _rescore_dir(
                td, survivors=[("100000002", "A"),
                               ("100000011", "B")])
            ledger = build_ledger.build_ledger(999, run,
                                               rescore_dir=rd)
            by_tic = {e["tic"]: e
                      for e in ledger["survivors"]}
            self.assertEqual(by_tic["100000002"]["superseded_by"],
                             "bulk_v2")
            self.assertEqual(by_tic["100000011"],
                             {"tic": "100000011", "tier": "B",
                              "calibration": "bulk_v2",
                              "found_by": "rescore_v2"})
            # Untouched entries carry no superseded flag.
            self.assertNotIn("superseded_by",
                             by_tic["100000005"])
            self.assertEqual(
                ledger["rescore"]["n_superseded"], 1)
            self.assertEqual(
                ledger["rescore"]["n_new_survivors"], 1)
            self.assertEqual(ledger["rescore"]["calibration"],
                             "bulk_v2")

    def test_dry_run_rescore_refused(self):
        with tempfile.TemporaryDirectory() as td:
            run = _stub_run(td)
            rd = _rescore_dir(td, dry_run=True)
            with self.assertRaises(SystemExit):
                build_ledger.build_ledger(999, run,
                                          rescore_dir=rd)


if __name__ == "__main__":
    unittest.main()
