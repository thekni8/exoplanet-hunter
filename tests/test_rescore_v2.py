"""Tests for bulk/rescore_v2.py (Phase 1.2, B-2).

Synthetic cache only — the real rescore runs on the Mac, where
the sector caches live (Dev-only step). The fixture cache holds
three stars:
  * a QUIET star with a DEEP transit (3.0% on 0.3% noise) that
    v1 missed entirely (SDE 5.4, below the floor) and v2
    recovers — the rescore's whole purpose;
  * a QUIET null (0.3% noise, no transit) — a candidate by clip
    level, but no survivor;
  * a NOISY null (1.0% noise) — not a candidate at all, because
    its 5-sigma clip level sits above 3%.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import bulk_screen as bs  # noqa: E402
from bulk import rescore_v2  # noqa: E402
from synth_fits import make_qlp_fits, screen_job  # noqa: E402

DEEP_TIC = "111111111"   # quiet + deep transit
QUIET_NULL_TIC = "222222222"
NOISY_NULL_TIC = "333333333"


def _make_cache(root):
    cache = Path(root) / "cache" / "s0096"
    cache.mkdir(parents=True)
    make_qlp_fits(cache / f"{DEEP_TIC}.fits", period_d=2.17,
                  depth_frac=0.03, noise_pct=0.003, seed=42)
    make_qlp_fits(cache / f"{QUIET_NULL_TIC}.fits", period_d=None,
                  noise_pct=0.003, seed=42)
    make_qlp_fits(cache / f"{NOISY_NULL_TIC}.fits", period_d=None,
                  noise_pct=0.01, seed=42)
    return str(Path(root) / "cache")


class TestRescoreV2(unittest.TestCase):
    def setUp(self):
        self._previous = bs.CALIBRATION_VERSION

    def tearDown(self):
        bs.set_calibration(self._previous)

    def test_clip_level_separates_quiet_from_noisy(self):
        with tempfile.TemporaryDirectory() as td:
            cache = _make_cache(td)
            deep = rescore_v2.clip_level(
                f"{cache}/s0096/{DEEP_TIC}.fits")
            noisy = rescore_v2.clip_level(
                f"{cache}/s0096/{NOISY_NULL_TIC}.fits")
        self.assertLess(deep, 0.03)
        self.assertGreater(noisy, 0.03)

    def test_dry_run_lists_candidates_without_bls(self):
        with tempfile.TemporaryDirectory() as td:
            cache = _make_cache(td)
            out = Path(td) / "out"
            rc = rescore_v2.main(["--sector", "96",
                                  "--cache", cache,
                                  "--out", str(out),
                                  "--dry-run"])
            self.assertEqual(rc, 0)
            cands = json.loads(
                (out / "candidates.json").read_text())
            self.assertEqual(
                sorted(c["tic"] for c in cands),
                sorted([DEEP_TIC, QUIET_NULL_TIC]))
            for c in cands:
                self.assertLess(c["clip_level_frac"], 0.03)
            self.assertFalse(
                (out / "rescore_v2_s0096.jsonl").exists())
            summary = json.loads((out / "summary.json").read_text())
            self.assertEqual(summary["n_cached"], 3)
            self.assertEqual(summary["n_candidates"], 2)
            self.assertTrue(summary["dry_run"])

    def test_full_run_recovers_what_v1_missed(self):
        with tempfile.TemporaryDirectory() as td:
            cache = _make_cache(td)
            # v1 misses the deep transit on the quiet star.
            bs.set_calibration("bulk_v1")
            v1 = bs._screen_one(screen_job(
                f"{cache}/s0096/{DEEP_TIC}.fits", tic=DEEP_TIC,
                sector=96))
            self.assertNotEqual(v1["status"], "survivor")
            # The rescore under v2 recovers it.
            out = Path(td) / "out"
            rc = rescore_v2.main(["--sector", "96",
                                  "--cache", cache,
                                  "--out", str(out)])
            self.assertEqual(rc, 0)
            rows = [json.loads(line) for line in
                    (out / "rescore_v2_s0096.jsonl")
                    .read_text().splitlines() if line.strip()]
            self.assertEqual(len(rows), 1)
            rec = rows[0]
            self.assertEqual(rec["tic"], DEEP_TIC)
            self.assertEqual(rec["status"], "survivor")
            self.assertEqual(rec["calibration_version"],
                             {"bulk": "v2"})
            self.assertEqual(rec["superseded_by"], "bulk_v2")
            summary = json.loads((out / "summary.json").read_text())
            self.assertEqual(summary["n_rescreened"], 2)
            self.assertEqual(summary["n_survivors"], 1)
            self.assertEqual(summary["n_errors"], 0)
