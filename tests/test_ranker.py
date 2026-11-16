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


if __name__ == "__main__":
    unittest.main()
