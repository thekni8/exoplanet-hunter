"""Tests for quality_flags.py (mask-fix follow-up M-1).

The integer pins are the point: the v3 mask must stay exactly
1610629823, built from the named constants, and the stray-light bits
11/12 must stay OUT of it (TOI-700 c lesson; 2026-11-15 vote 2/3).
"""

import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import quality_flags as qf


class TestNamedMasks(unittest.TestCase):
    def test_spoc_default_is_lightkurve_17087(self):
        # lightkurve TessQualityFlags.DEFAULT_BITMASK, verified
        # value-for-value against the installed lightkurve 2026-11-15.
        self.assertEqual(qf.SPOC_DEFAULT_MASK, 17087)
        self.assertEqual(
            qf.SPOC_DEFAULT_MASK,
            qf.SPOC_ATTITUDE_TWEAK
            | qf.SPOC_SAFE_MODE
            | qf.SPOC_COARSE_POINT
            | qf.SPOC_EARTH_POINT
            | qf.SPOC_ARGABRIGHTENING
            | qf.SPOC_DESAT
            | qf.SPOC_MANUAL_EXCLUDE
            | qf.SPOC_IMPULSIVE_OUTLIER
            | qf.SPOC_BAD_CALIBRATION_EXCLUDE,
        )

    def test_v3_mask_is_1610629823(self):
        # The pin: v3 = lightkurve default + QLP bits 29/30.
        self.assertEqual(qf.BULK_V3_MASK, 1610629823)
        self.assertEqual(
            qf.BULK_V3_MASK,
            qf.SPOC_DEFAULT_MASK
            | qf.QLP_UNDOCUMENTED_29
            | qf.QLP_LOW_PRECISION,
        )
        self.assertEqual(qf.QLP_UNDOCUMENTED_29, 1 << 29)
        self.assertEqual(qf.QLP_LOW_PRECISION, 1 << 30)

    def test_v1_v2_mask_is_17087(self):
        self.assertEqual(qf.BULK_V1_V2_MASK, 17087)

    def test_straylight_bits_stay_out_of_v3(self):
        # Bit 11 (Straylight, manual) and bit 12 (Straylight2,
        # automatic): a real transit can survive on these cadences
        # (TOI-700 c lesson). The 2026-11-15 vote went 2/3 against
        # masking bit 11; bit 12 was never proposed for masking.
        self.assertEqual(qf.BULK_V3_MASK & qf.SPOC_STRAYLIGHT, 0)
        self.assertEqual(qf.BULK_V3_MASK & qf.SPOC_STRAYLIGHT2, 0)
        self.assertEqual(qf.SPOC_STRAYLIGHT, 2048)
        self.assertEqual(qf.SPOC_STRAYLIGHT2, 4096)
        # The old QLP flag location is the same value as Straylight2.
        self.assertEqual(qf.QLP_LOW_PRECISION_OLD, qf.SPOC_STRAYLIGHT2)


class TestFlagNames(unittest.TestCase):
    def test_names_for_v3_mask(self):
        names = qf.flag_names(qf.BULK_V3_MASK)
        self.assertIn("qlp_low_precision", names)
        self.assertIn("qlp_undocumented_29", names)
        self.assertIn("attitude_tweak", names)
        self.assertIn("bad_calibration_exclude", names)
        self.assertNotIn("straylight", names)
        self.assertNotIn("straylight2", names)

    def test_unknown_bit_reported_not_dropped(self):
        self.assertEqual(qf.flag_names(1 << 20), ["bit_20"])

    def test_empty_mask(self):
        self.assertEqual(qf.flag_names(0), [])


class TestTallyUnmaskedBits(unittest.TestCase):
    def test_tally_counts_only_unmasked_bits(self):
        # 3 cadences: bit 11 alone, bit 30 alone, bits 11+30.
        q = np.array([2048, 1 << 30, 2048 | (1 << 30)], dtype=np.int64)
        tally = qf.tally_unmasked_bits(q, qf.BULK_V3_MASK)
        # Bit 30 is masked, so only bit 11 survives the tally.
        self.assertEqual(tally, {11: 2})

    def test_tally_empty_when_all_masked(self):
        q = np.array([1, 32, (1 << 29) | (1 << 30)], dtype=np.int64)
        self.assertEqual(qf.tally_unmasked_bits(q, qf.BULK_V3_MASK), {})

    def test_tally_empty_quality(self):
        q = np.zeros(10, dtype=np.int64)
        self.assertEqual(qf.tally_unmasked_bits(q, qf.BULK_V3_MASK), {})


if __name__ == "__main__":
    unittest.main()
