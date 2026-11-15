"""Live download-to-stitch-to-mask test (DF-21).

The fixture seam (tests/test_deep_quality_mask.py) proves the mask
LOGIC; this proves the LIVE product path preserves QUALITY the way
the deep_v2 bundle assumes: a real MAST download, through the
pipeline's own ``hunter._download_products`` (which passes the
active profile's mask as an explicit ``quality_bitmask``, DF-11),
stitched, then masked.

Star: TIC 31852076, QLP sector 96 — the sensitivity substrate
star. Its S96 file is known to carry bit-29/30 cadences (3,028
bit-29 + 1,074 bit-30 in the cached FITS, 3,212 masked rows under
the v2 mask), so the premise is verifiable, not assumed: the test
fails loudly if the live file ever stops carrying those bits.

LIVE TIER ONLY: this module is in DOWNLOAD_TESTS
(tests/run_golden.py) — excluded from --fast and the PR gate, run
by .github/workflows/live.yml (weekly + on merge to main). The
offline suite gains no network dependency.

Multi-sector stitching itself is covered by the live golden
stars (TOI-700, test_golden_stars.py); this test pins one product
so the masked-row counts are exact.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import lightkurve as lk  # noqa: E402
import numpy as np  # noqa: E402

import hunter  # noqa: E402
import quality_flags as qf  # noqa: E402
from tests.calibration_guard import DeepCalibrationGuardCase  # noqa: E402

TIC = "31852076"
SECTOR = 96
AUTHOR = "QLP"


class TestDeepMaskLive(DeepCalibrationGuardCase):
    def test_live_download_stitch_mask(self):
        # 1. Pin the product: QLP sector 96 for the substrate star.
        search = lk.search_lightcurve(f"TIC {TIC}", author=AUTHOR)
        self.assertGreater(len(search), 0,
                           f"no {AUTHOR} products for TIC {TIC} on MAST")
        table = search.table
        rows96 = [i for i in range(len(table))
                  if int(table["sequence_number"][i]) == SECTOR]
        self.assertGreater(len(rows96), 0,
                           f"no {AUTHOR} sector-{SECTOR} product for "
                           f"TIC {TIC} on MAST")
        pinned = search[rows96[:1]]

        # 2. The raw curve, no reader mask: the ground truth for
        #    the hand count.
        raw = pinned[0].download(quality_bitmask="none")
        self.assertIn("quality", raw.columns,
                      "live QLP download carries no QUALITY column")
        q = np.asarray(raw.quality, dtype=np.int64)
        keep = (q & qf.DEEP_V2_MASK) == 0
        n_expected = int((~keep).sum())
        n_new_bits = int(((q & ((1 << 29) | (1 << 30))) != 0).sum())
        self.assertGreater(
            n_new_bits, 0,
            "premise failed: the live S96 file carries no bit-29/30 "
            "cadences — the test would prove nothing")
        self.assertGreater(n_expected, 0)

        # 3. The pipeline's own download under deep_v2: the reader
        #    applies the v2 mask at read time (DF-11).
        with hunter.calibration_context("deep_v2"):
            coll = hunter._download_products(pinned, TIC)
        self.assertEqual(len(coll), 1)
        lc = coll[0]

        # 4. Reader drop == hand count; surviving times identical;
        #    no surviving row carries a masked bit; the DF-9
        #    counting input (meta QUALITY_MASK) is present.
        self.assertIn("QUALITY_MASK", lc.meta)
        self.assertEqual(len(raw) - len(lc), n_expected,
                         "reader dropped a different row count than "
                         "the hand-masked count")
        np.testing.assert_array_equal(
            np.asarray(lc.time.value),
            np.asarray(raw.time.value)[keep])
        q_surv = np.asarray(lc.quality, dtype=np.int64)
        self.assertEqual(int(((q_surv & qf.DEEP_V2_MASK) != 0).sum()), 0)

        # 5. Stitch + post-download mask: the reader already did
        #    the work, so the defence-in-depth layer drops nothing
        #    further — and the post-download mask on the raw curve
        #    agrees with the reader exactly.
        stitched = coll.stitch()
        masked = hunter._apply_quality_mask(stitched, qf.DEEP_V2_MASK)
        self.assertEqual(len(masked), len(lc),
                         "post-download mask dropped rows the reader "
                         "kept (reader and mask disagree)")
        masked_raw = hunter._apply_quality_mask(raw, qf.DEEP_V2_MASK)
        self.assertEqual(len(raw) - len(masked_raw), n_expected)
        np.testing.assert_array_equal(
            np.asarray(masked_raw.time.value),
            np.asarray(lc.time.value))


if __name__ == "__main__":
    unittest.main()
