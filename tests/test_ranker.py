"""3A experimental ranker tests (Phase 3, P3-16–P3-19).

Offline, synthetic screen records only — no data files, no
network, no Mac. The ranker is an offline experiment: these
tests pin the feature contract (P3-16), the model + baselines +
metrics (P3-18), and the rank-only enforcement (P3-19).
"""
import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402

from bulk import ranker  # noqa: E402


def _record(**over):
    """A synthetic full screen record; overrides set the field."""
    row = {
        "tic": "1",
        "sde": 20.0,
        "mes_pink": 15.0,
        "depth_percent": 0.5,
        "odd_even_ratio": 0.9,
        "n_events": 4,
        "n_strong_events": 3,
        "max_event_snr": 9.0,
        "period_days": 3.5,
        "t0_btjd": 3910.0,
        "tier": "A",
    }
    row.update(over)
    return row


def _campaign_screen(**over):
    """A synthetic campaign screen dict (reduced copy, P3-10)."""
    row = {
        "sde": 20.0,
        "mes_pink": 15.0,
        "status": "survivor",
        "tier": "A",
        "period_days": 3.5,
        "depth_percent": 0.5,
        "flags": [],
        "odd_even_ratio": 0.9,
        "search_health": "VALID_DETECTION",
        "n_events_found": 4,
        "n_strong_events": 3,
        "max_event_snr": 9.0,
        "alts": [],
    }
    row.update(over)
    return row


class TestFeatureContract(unittest.TestCase):
    """P3-16: the ten Stage 1 features + symmetry by construction."""

    def test_feature_names_fixed(self):
        self.assertEqual(
            ranker.FEATURE_NAMES,
            (
                "log_sde",
                "log_mes",
                "log_depth",
                "odd_even_ratio",
                "n_events",
                "n_strong_events",
                "log_max_event_snr",
                "mes_sde_ratio",
                "strong_fraction",
                "single_vs_combined",
            ),
        )

    def test_extract_features_values(self):
        feats = ranker.extract_features(_record())
        self.assertAlmostEqual(feats["log_sde"], math.log10(20.0))
        self.assertAlmostEqual(feats["log_mes"], math.log10(15.0))
        self.assertAlmostEqual(feats["log_depth"], math.log10(0.5))
        self.assertEqual(feats["odd_even_ratio"], 0.9)
        self.assertEqual(feats["n_events"], 4.0)
        self.assertEqual(feats["n_strong_events"], 3.0)
        self.assertAlmostEqual(
            feats["log_max_event_snr"], math.log10(9.0))
        self.assertAlmostEqual(feats["mes_sde_ratio"], 15.0 / 20.0)
        self.assertAlmostEqual(feats["strong_fraction"], 3.0 / 4.0)
        self.assertAlmostEqual(feats["single_vs_combined"], 9.0 / 15.0)

    def test_campaign_and_full_record_agree(self):
        """Same signal, two record shapes, identical features.

        The campaign persists n_events_found where the screen
        emits n_events — the one normalisation. Everything else
        is the same code path (P3-16 symmetry).
        """
        full = ranker.extract_features(_record())
        camp = ranker.extract_features(_campaign_screen())
        self.assertEqual(full, camp)

    def test_prohibited_fields_ignored(self):
        """Period, T0 and tier never reach the features (P3-16)."""
        base = ranker.extract_features(_record())
        wild = ranker.extract_features(_record(
            period_days=13.2, t0_btjd=9999.0, tier="B"))
        self.assertEqual(base, wild)
        for field in ranker.PROHIBITED_FIELDS:
            self.assertNotIn(field, ranker.FEATURE_NAMES)

    def test_no_nans_on_missing_fields(self):
        """Every field missing -> finite sentinels, never NaN."""
        empty = {k: None for k in _record()}
        feats = ranker.extract_features(empty)
        self.assertEqual(set(feats), set(ranker.FEATURE_NAMES))
        for value in feats.values():
            self.assertTrue(math.isfinite(value), value)
        self.assertEqual(feats["log_sde"], 0.0)
        self.assertEqual(feats["log_depth"], -2.0)
        self.assertEqual(feats["odd_even_ratio"], -1.0)
        self.assertEqual(feats["n_events"], 0.0)

    def test_imputation_reporting(self):
        partial = _record(odd_even_ratio=None, max_event_snr=None)
        imputed = ranker.feature_imputation(partial)
        self.assertIn("odd_even_ratio", imputed)
        self.assertIn("log_max_event_snr", imputed)
        self.assertIn("single_vs_combined", imputed)
        self.assertNotIn("log_sde", imputed)
        self.assertEqual(
            ranker.feature_imputation(_record()), set())

    def test_symmetry_check_reports_gap(self):
        """The check sees a class-correlated imputation gap."""
        good = [_record() for _ in range(10)]
        bad = [_record(odd_even_ratio=None) for _ in range(10)]
        rates = ranker.check_feature_symmetry(
            {"planet": good, "fp": bad})
        self.assertEqual(rates["odd_even_ratio"]["planet"], 0.0)
        self.assertEqual(rates["odd_even_ratio"]["fp"], 1.0)
        self.assertEqual(rates["_max_gap"]["odd_even_ratio"], 1.0)
        self.assertEqual(rates["_max_gap"]["log_sde"], 0.0)

    def test_features_to_array(self):
        arr = ranker.features_to_array(
            [_record(), _record(sde=10.0)])
        self.assertEqual(arr.shape, (2, 10))
        self.assertTrue(np.all(np.isfinite(arr)))
        self.assertAlmostEqual(arr[0, 0], math.log10(20.0))
        self.assertAlmostEqual(arr[1, 0], math.log10(10.0))


class TestModelAndBaselines(unittest.TestCase):
    """P3-18: the 3-class model + the three baselines."""

    def _toy_data(self, n=60, seed=1):
        """Separable toy data: planets high-SDE + high-MES."""
        rng = np.random.RandomState(seed)
        rows, y = [], []
        for i in range(n):
            planet = i % 3 == 0
            rows.append(_record(
                sde=30.0 if planet else 10.0,
                mes_pink=25.0 if planet else 8.0,
                depth_percent=0.5 if planet else 2.0,
                n_events=4 if planet else 2))
            y.append(0 if planet else (1 if i % 3 == 1 else 2))
        return rows, np.array(y)

    def test_train_ranker_and_proba(self):
        rows, y = self._toy_data()
        X = ranker.features_to_array(rows)
        model = ranker.train_ranker(X, y)
        proba = ranker.planet_proba(model, X)
        self.assertEqual(proba.shape, (len(rows),))
        self.assertTrue(np.all((proba >= 0) & (proba <= 1)))
        # Planets score above non-planets on separable toy data.
        self.assertGreater(proba[y == 0].mean(),
                           proba[y != 0].mean())

    def test_logistic_baseline(self):
        rows, y = self._toy_data()
        X = ranker.features_to_array(rows)
        model = ranker.train_logistic(X, y)
        proba = ranker.logistic_planet_proba(model, X)
        self.assertEqual(proba.shape, (len(rows),))
        self.assertTrue(np.all((proba >= 0) & (proba <= 1)))

    def test_sde_scores(self):
        scores = ranker.sde_scores(
            [_record(sde=10.0), _record(sde=30.0)])
        self.assertEqual(list(scores), [10.0, 30.0])

    def test_gate_scores_tier_then_sde(self):
        """Tier A outranks tier B at any SDE; SDE within tier."""
        rows = [
            _record(sde=50.0, tier="B"),
            _record(sde=8.0, tier="A"),
            _record(sde=20.0, tier="B"),
            _record(sde=9.0, tier=None),
        ]
        scores = ranker.gate_scores(rows)
        self.assertGreater(scores[1], scores[0])  # A/8 > B/50
        self.assertGreater(scores[0], scores[2])  # B/50 > B/20
        self.assertGreater(scores[2], scores[3])  # B/20 > no-tier


class TestMetrics(unittest.TestCase):
    """P3-18: ranking metrics on hand-computed cases."""

    def test_recall_at_k(self):
        y = [1, 0, 1, 0, 0]
        scores = [0.9, 0.8, 0.7, 0.6, 0.5]
        self.assertEqual(ranker.recall_at_k(y, scores, 2), 0.5)
        self.assertEqual(ranker.recall_at_k(y, scores, 3), 1.0)
        self.assertEqual(ranker.recall_at_k(y, scores, 0), 0.0)
        self.assertEqual(ranker.recall_at_k([0, 0], scores[:2], 2), 0.0)

    def test_recall_at_fraction(self):
        y = [1, 0, 1, 0, 0, 0, 0, 0, 0, 0]
        scores = [0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2, 0.1, 0.0]
        # Top 20% = top 2 rows -> 1 of 2 positives.
        self.assertEqual(ranker.recall_at_fraction(y, scores, 0.2), 0.5)

    def test_ndcg(self):
        y = [1, 1, 0, 0]
        self.assertEqual(
            ranker.ndcg(y, [0.9, 0.8, 0.7, 0.6]), 1.0)
        self.assertLess(
            ranker.ndcg(y, [0.6, 0.7, 0.8, 0.9]), 1.0)
        self.assertEqual(ranker.ndcg([0, 0], [0.9, 0.8]), 0.0)

    def test_average_precision(self):
        y = [1, 1, 0, 0]
        self.assertEqual(
            ranker.average_precision(y, [0.9, 0.8, 0.7, 0.6]), 1.0)
        ap = ranker.average_precision(y, [0.6, 0.9, 0.8, 0.7])
        # Ranked y = [1, 0, 0, 1]: hits at positions 1 and 4.
        self.assertAlmostEqual(ap, (1.0 + 0.5) / 2.0)

    def test_confusion_and_per_class_recall(self):
        y_true = [0, 0, 1, 1, 2, 2]
        y_pred = [0, 1, 1, 2, 2, 0]
        mat = ranker.confusion_3class(y_true, y_pred)
        self.assertEqual(mat[0, 0], 1)
        self.assertEqual(mat[0, 1], 1)
        self.assertEqual(mat[1, 1], 1)
        self.assertEqual(mat[1, 2], 1)
        self.assertEqual(mat[2, 2], 1)
        self.assertEqual(mat[2, 0], 1)
        recall = ranker.per_class_recall(y_true, y_pred)
        self.assertEqual(recall["planet"], 0.5)
        self.assertEqual(recall["astro_fp"], 0.5)
        self.assertEqual(recall["instr_fp"], 0.5)

    def test_ranks_of(self):
        scores = [0.5, 0.9, 0.7]
        ranks = ranker.ranks_of(scores, [True, False, True])
        self.assertEqual(list(ranks), [3, 2])


class TestRankOnlyEnforcement(unittest.TestCase):
    """P3-19: permutation, SDE fallback, advisory-only boundary."""

    def _toy_model(self):
        rows, y = [], []
        for i in range(30):
            planet = i % 2 == 0
            rows.append(_record(
                tic=str(i),
                sde=30.0 if planet else 10.0,
                mes_pink=25.0 if planet else 8.0))
            y.append(0 if planet else 1)
        X = ranker.features_to_array(rows)
        return rows, ranker.train_ranker(X, np.array(y))

    def test_rank_queue_is_permutation(self):
        """Output = input reordered: same rows, same count."""
        rows, model = self._toy_model()
        ranked = ranker.rank_queue(rows, model)
        self.assertEqual(len(ranked), len(rows))
        self.assertEqual({r["tic"] for r in ranked},
                         {r["tic"] for r in rows})
        # Planets (even TICs) rank above non-planets on toy data.
        top_half = {r["tic"] for r in ranked[:15]}
        self.assertTrue(all(int(t) % 2 == 0 for t in top_half))

    def test_rank_queue_does_not_mutate_input(self):
        """Ranking changes no row and no verdict (advisory only)."""
        import copy
        rows, model = self._toy_model()
        before = copy.deepcopy(rows)
        ranker.rank_queue(rows, model)
        self.assertEqual(rows, before)

    def test_rank_queue_empty(self):
        rows, model = self._toy_model()
        self.assertEqual(ranker.rank_queue([], model), [])
        self.assertEqual(ranker.rank_queue_with_fallback([], model), [])

    def test_sde_fallback_no_model(self):
        rows, _ = self._toy_model()
        ranked = ranker.rank_queue_with_fallback(rows, model=None)
        sdes = [r["sde"] for r in ranked]
        self.assertEqual(sdes, sorted(sdes, reverse=True))
        self.assertEqual({r["tic"] for r in ranked},
                         {r["tic"] for r in rows})

    def test_sde_fallback_on_broken_model(self):
        """A model that throws still yields an SDE-ordered queue."""

        class Broken:
            def predict_proba(self, X):
                raise RuntimeError("boom")

        rows, _ = self._toy_model()
        ranked = ranker.rank_queue_with_fallback(rows, model=Broken())
        sdes = [r["sde"] for r in ranked]
        self.assertEqual(sdes, sorted(sdes, reverse=True))

    def test_no_production_code_consumes_ranker(self):
        """Grep-verified: no production module imports the ranker.

        The ranker is an offline experiment. Only the experiment
        scripts (rank_experiment.py and the P3-21 validation
        scorer score_sector.py), the dataset builder, and the
        tests may touch it.
        """
        root = Path(__file__).resolve().parent.parent
        allowed = {
            root / "bulk" / "ranker.py",
            root / "bulk" / "ranker_dataset.py",
            root / "scripts" / "rank_experiment.py",
            # P3-21: the frozen-ranker sector scorer is the
            # validation pass of the same offline experiment —
            # it reproduces the frozen model and writes an
            # advisory ranking only. It is not a production
            # module and no production code imports it.
            root / "scripts" / "score_sector.py",
        }
        offenders = []
        for path in root.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            if path.parent.name == "tests":
                continue
            if path in allowed:
                continue
            text = path.read_text(errors="ignore")
            for needle in ("bulk.ranker", "bulk import ranker",
                           "ranker_dataset", "rank_experiment"):
                if needle in text:
                    offenders.append(f"{path.relative_to(root)}: "
                                     f"{needle!r}")
        self.assertEqual(offenders, [])

    def test_desk_driver_takes_no_rank_input(self):
        """The desk driver cannot be steered by rank output.

        Parsed from source (ast) rather than imported — importing
        gauntlet.desk pulls in the heavy MAST/astro stack, which
        has no place in a fast offline test.
        """
        import ast

        root = Path(__file__).resolve().parent.parent
        tree = ast.parse((root / "gauntlet" / "desk.py").read_text())
        funcs = {node.name: node for node in ast.walk(tree)
                 if isinstance(node, ast.FunctionDef)}
        classes = {node.name: node for node in ast.walk(tree)
                   if isinstance(node, ast.ClassDef)}
        self.assertIn("run_desk_gauntlet", funcs)
        params = {a.arg for a in
                  funcs["run_desk_gauntlet"].args.args}
        self.assertNotIn("rank", params)
        self.assertNotIn("score", params)
        self.assertNotIn("ranker", params)
        self.assertIn("Survivor", classes)
        fields = {node.target.id for node in
                  classes["Survivor"].body
                  if isinstance(node, ast.AnnAssign)}
        self.assertNotIn("rank", fields)
        self.assertNotIn("score", fields)


if __name__ == "__main__":
    unittest.main()
