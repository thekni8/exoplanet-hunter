"""DF-3: the neighbour fold masks QLP bits 29/30 (offline).

fetch_neighbour downloads live, so the unit under test is the
_masked_keep helper it applies post-download, driven by a fake
light curve. The blend comparison must be mask-consistent: the
target's fold is masked, so the neighbour's must be too.
"""

import unittest

import numpy as np

from gauntlet.neighbour_fold import _masked_keep  # noqa: E402
from quality_flags import DEEP_V2_MASK  # noqa: E402


class _FakeCol:
    def __init__(self, values):
        self.value = np.asarray(values)


class _FakeLC:
    def __init__(self, cols):
        self._cols = cols

    @property
    def colnames(self):
        return list(self._cols)

    def __getitem__(self, key):
        return _FakeCol(self._cols[key])


class TestNeighbourMask(unittest.TestCase):
    def test_bits_29_30_dropped_bit12_kept(self):
        # q: clean, bit 29, bit 30, bit 12 (TOI-700 c), bit 0
        # (in the SPOC default mask). Bit 12 is NOT masked.
        q = [0, 1 << 29, 1 << 30, 4096, 1]
        lc = _FakeLC({"quality": q})
        keep = _masked_keep(lc, DEEP_V2_MASK)
        np.testing.assert_array_equal(
            keep, [True, False, False, True, False])

    def test_no_quality_column_returns_none(self):
        lc = _FakeLC({"sap_flux": [1.0, 1.0]})
        self.assertIsNone(_masked_keep(lc, DEEP_V2_MASK))

    def test_uint16_quality_does_not_overflow(self):
        # SPOC 16-bit QUALITY: a bare uint16 & mask raises
        # OverflowError under numpy 2.x — the int64 cast is the
        # defence (DF-5), pinned here for this site too.
        q = np.array([0, 1, 4096], dtype=np.uint16)
        lc = _FakeLC({"quality": q})
        keep = _masked_keep(lc, DEEP_V2_MASK)
        np.testing.assert_array_equal(keep, [True, False, True])

    def test_explicit_mask_respected(self):
        q = [0, 1 << 29, 1 << 30]
        lc = _FakeLC({"quality": q})
        keep = _masked_keep(lc, 0)
        np.testing.assert_array_equal(keep, [True, True, True])


if __name__ == "__main__":
    unittest.main()
