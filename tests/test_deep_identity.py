"""DF-4: bitwise identity test on real clean stars (deep_v2).

Where no cadence carries a newly masked bit (29/30), deep_v1
and deep_v2 must be BITWISE IDENTICAL — the only difference
between the profiles is the mask, and on these stars the masks
remove exactly the same rows. The test runs the REAL
hunter._run_pipeline through the fixture seam on two committed
real-data substrates:

  * QLP: TIC 149269965, Sector 1 (sap_flux, 1,281 points) —
    zero bit-29/30 cadences, 15 default-masked cadences, 288
    bit-12 cadences. Sector 1 predates the scattered-light
    flagging: 1,429 of the VM's cached S1 stars are clean.
  * SPOC: TIC 150428135 (TOI-700), Sector 1, 120 s
    (pdcsap_flux, 19,261 points) — zero bit-29/30 cadences
    (SPOC QUALITY is 16-bit, so bits 29/30 cannot occur), 982
    default-masked cadences.

The search outputs (Period, SDE, Depth, Duration, T0,
Total_Points, n_masked, flagged_fraction) must match EXACTLY.
The profile-identifying stamps (quality_mask_applied,
calibration_version) must DIFFER as expected — they are the
profiles, not the search. A widen-the-mask check (add bit 12
to the v2 mask temporarily) must fail this test on the QLP
star — verified by hand at build time, see PROGRESS.md.
"""

import json
import math
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402

import hunter  # noqa: E402
import quality_flags as qf  # noqa: E402
from bulk.inject_deep_real_s96 import write_fixture  # noqa: E402
from tests.calibration_guard import DeepCalibrationGuardCase  # noqa: E402

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "injection"

SUBSTRATES = (
    # (substrate file, tic, product)
    ("substrate_s01_149269965.npz", "149269965", "QLP"),
    ("substrate_s01_150428135_spoc.npz", "150428135", "SPOC"),
)

NEWLY_MASKED_BITS = (1 << 29) | (1 << 30)

# Search outputs that must match EXACTLY between v1 and v2.
IDENTITY_FIELDS = ("Period", "SDE", "Depth", "Duration_Days", "T0",
                   "Total_Points", "n_masked", "flagged_fraction")


def _exactly_equal(a, b):
    """Exact equality with correct NaN semantics (NaN == NaN for
    this comparison — a NaN SDE on both sides is identical, not
    a mismatch)."""
    if isinstance(a, float) and isinstance(b, float):
        if math.isnan(a) and math.isnan(b):
            return True
    return a == b


class TestDeepIdentity(DeepCalibrationGuardCase):
    def setUp(self):
        super().setUp()
        self._prev_env = os.environ.get("EXHUNT_FIXTURE_DIR")
        self._td = tempfile.TemporaryDirectory()
        os.environ["EXHUNT_FIXTURE_DIR"] = self._td.name

    def tearDown(self):
        # No manual calibration restore: the runs switch
        # through calibration_context, which restores in a
        # finally block; the guard base class asserts deep_v2
        # is back after every test.
        if self._prev_env is None:
            os.environ.pop("EXHUNT_FIXTURE_DIR", None)
        else:
            os.environ["EXHUNT_FIXTURE_DIR"] = self._prev_env
        self._td.cleanup()

    def _load_substrate(self, filename):
        d = np.load(FIXTURE_DIR / filename)
        return (np.asarray(d["t"], dtype=float),
                np.asarray(d["f"], dtype=float),
                np.asarray(d["q"], dtype=np.int64),
                json.loads(str(d["meta_json"])))

    def test_substrates_carry_no_newly_masked_bit(self):
        # The premise of the identity test, guarded against
        # substrate rot: zero cadences with bits 29/30, and a
        # NONZERO default-masked count — both profiles must
        # actually mask the same rows, not mask nothing.
        for filename, tic, product in SUBSTRATES:
            _t, _f, q, meta = self._load_substrate(filename)
            self.assertEqual(meta["tic"], tic)
            n_new = int(((q & NEWLY_MASKED_BITS) != 0).sum())
            self.assertEqual(n_new, 0, f"{product} {tic}: "
                             f"{n_new} cadences carry bits 29/30")
            n_default = int(((q & qf.SPOC_DEFAULT_MASK) != 0).sum())
            self.assertGreater(n_default, 0,
                               f"{product} {tic}: no cadence is "
                               f"masked by either profile — the "
                               f"identity test would be vacuous")

    def _assert_identity(self, tic, product):
        filename = next(f for f, t, _p in SUBSTRATES if t == tic)
        t, f, q, _meta = self._load_substrate(filename)
        write_fixture(self._td.name, tic, t, f, q)
        with hunter.calibration_context("deep_v1"):
            v1 = hunter._run_pipeline(tic, star_radius=1.0,
                                      max_sectors=None)
        with hunter.calibration_context("deep_v2"):
            v2 = hunter._run_pipeline(tic, star_radius=1.0,
                                      max_sectors=None)
        for field in IDENTITY_FIELDS:
            self.assertTrue(
                _exactly_equal(v1[field], v2[field]),
                f"{product} {tic}: {field} differs — "
                f"v1={v1[field]!r} v2={v2[field]!r}")
        # The stamps MUST differ — they identify the profile.
        self.assertEqual(v1["quality_mask_applied"], 17087)
        self.assertEqual(v2["quality_mask_applied"], 1610629823)
        self.assertEqual(v1["calibration_version"], "deep_v1")
        self.assertEqual(v2["calibration_version"], "deep_v2")

    def test_identity_qlp(self):
        self._assert_identity("149269965", "QLP")

    def test_identity_spoc(self):
        self._assert_identity("150428135", "SPOC")


if __name__ == "__main__":
    unittest.main()
