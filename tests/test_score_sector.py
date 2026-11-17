"""Tests for scripts/score_sector.py (P3-21 frozen-ranker scoring).

Covers the S98 lock (TB-8), the one-sector rule, the permutation
property of score_records, and the TOI top-decile reporting — all
on synthetic records + a tiny synthetic model. The end-to-end
path (train_frozen_model on the committed dataset) is exercised
by the VM smoke run in the P3-21 commands doc, not here: it needs
the goal's data files, which are not repo fixtures.
"""
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bulk import ranker  # noqa: E402


def _load_score_sector():
    spec = importlib.util.spec_from_file_location(
        "score_sector", ROOT / "scripts" / "score_sector.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ss = _load_score_sector()


def _record(tic, sector=97, sde=10.0, mes=9.0, depth=0.5, n_ev=3):
    """A minimal survivor-shaped record the feature extractor
    accepts (all ten Stage 1 features computable)."""
    return {
        "tic": tic, "sector": sector, "sde": sde,
        "mes_pink": mes, "depth_percent": depth,
        "odd_even_ratio": 0.1, "n_events": n_ev,
        "n_strong_events": 2, "max_event_snr": 8.0,
    }


def _toy_model():
    """A tiny trained ranker (synthetic X/y — the model is only
    a scoring function here; the frozen model is exercised by
    the VM smoke run, not this test)."""
    rng = np.random.RandomState(0)
    X = rng.uniform(0, 2, size=(30, len(ranker.FEATURE_NAMES)))
    y = np.array([0] * 10 + [1] * 10 + [2] * 10)
    return ranker.train_ranker(X, y)


class TestS98Lock(unittest.TestCase):
    def test_filename_s0098_refused(self):
        with self.assertRaises(SystemExit):
            ss.guard_sector("rescore_v4_s0098.jsonl",
                            [_record(1, sector=98)])

    def test_record_sector_98_refused(self):
        with self.assertRaises(SystemExit):
            ss.guard_sector("survivors.jsonl",
                            [_record(1, sector=97),
                             _record(2, sector=98)])

    def test_mixed_sectors_refused(self):
        with self.assertRaises(SystemExit):
            ss.guard_sector("survivors.jsonl",
                            [_record(1, sector=97),
                             _record(2, sector=96)])

    def test_single_sector_ok(self):
        self.assertEqual(
            ss.guard_sector("rescore_v4_s0097.jsonl",
                            [_record(1), _record(2)]), 97)


class TestScoreRecords(unittest.TestCase):
    def test_is_permutation_with_ranks(self):
        model = _toy_model()
        rows = [_record(101, sde=20.0), _record(102, sde=8.0),
                _record(103, sde=15.0), _record(104, sde=12.0)]
        scored = ss.score_records(rows, model)
        self.assertEqual(len(scored), 4)
        self.assertEqual(sorted(r["tic"] for r in scored),
                         [101, 102, 103, 104])
        self.assertEqual(sorted(r["ranker_rank"] for r in scored),
                         [1, 2, 3, 4])
        self.assertEqual(sorted(r["sde_rank"] for r in scored),
                         [1, 2, 3, 4])
        for r in scored:
            self.assertTrue(0.0 <= r["planet_proba"] <= 1.0)

    def test_does_not_mutate_input(self):
        model = _toy_model()
        rows = [_record(101), _record(102)]
        before = [dict(r) for r in rows]
        ss.score_records(rows, model)
        self.assertEqual(rows, before)

    def test_empty_scores_empty(self):
        self.assertEqual(ss.score_records([], _toy_model()), [])


class TestBuildReport(unittest.TestCase):
    def _scored(self):
        model = _toy_model()
        rows = [_record(100 + i, sde=8.0 + i) for i in range(20)]
        return ss.score_records(rows, model), rows

    def _dataset(self):
        return {"rows": [{"split": "train"}] * 10
                + [{"split": "test"}] * 5,
                "class_weights": {"planet": 1.0, "astro_fp": 1.0,
                                  "instr_fp": 1.0}}

    def test_report_fields_and_permutation(self):
        scored, rows = self._scored()
        rep = ss.build_report(scored, rows, 97, 20261116,
                              "abc123", "deadbeef", self._dataset())
        self.assertEqual(rep["sector"], 97)
        self.assertEqual(rep["n_survivors"], 20)
        self.assertEqual(rep["top_decile_cutoff_rank"], 2)
        self.assertTrue(rep["permutation_check"])
        self.assertFalse(rep["limited"])
        self.assertEqual(len(rep["ranker_top10_tics"]), 10)

    def test_toi_ranks_and_top_decile(self):
        scored, rows = self._scored()
        top_tic = str(scored[0]["tic"])
        bottom_tic = str(scored[-1]["tic"])
        rep = ss.build_report(
            scored, rows, 97, 20261116, "abc123", "deadbeef",
            self._dataset(), toi_tics={top_tic, bottom_tic, "999"})
        toi = rep["toi"]
        self.assertEqual(toi["n_in_toi_list"], 3)
        self.assertEqual(toi["n_in_scored_set"], 2)
        self.assertEqual(toi["ranks"][top_tic], 1)
        self.assertEqual(toi["ranks"][bottom_tic], 20)
        self.assertEqual(toi["n_in_top_decile"], 1)

    def test_limited_flag_recorded(self):
        scored, rows = self._scored()
        rep = ss.build_report(scored, rows, 97, 20261116,
                              "abc123", "deadbeef", self._dataset(),
                              limited=True, limit=20)
        self.assertTrue(rep["limited"])
        self.assertEqual(rep["limit"], 20)


class TestToiCsvLoading(unittest.TestCase):
    def test_parses_header_and_dot_zero(self):
        with tempfile.NamedTemporaryFile(
                "w", suffix=".csv", delete=False) as fh:
            fh.write("tid\n123456789.0\n987654321\n")
            path = fh.name
        self.assertEqual(ss._load_toi_csv(path),
                         {"123456789", "987654321"})


if __name__ == "__main__":
    unittest.main()
