"""Quality-mask tests (bulk_v3): flagged-cadence artifacts must die.

The bulk_v2 rescore gauntlet (S96, 2026-11-14) found 18/25 NEW
tier-A leads were dips living ONLY on quality bit-29/30 cadences
(TESS scattered light), with zero clean cadences in transit. v2's
10% MAD-clip floor preserves those deep flagged dropouts (4-9%),
so the screen promoted them. v3 masks bits 29/30 at screen input
(quality_mask 1610629823 = lightkurve default 17087 + bits 29/30).

Each artifact cell below is a synthetic fixture at a REAL
artifact's screen period/depth (from the gauntlet ledger) and
asserts BOTH halves: under bulk_v2 the screen PROMOTES it (this
is the failure reproduction — if the fixture ever stops promoting
under v2, the test fails on the v2 half, not vacuously on v3)
and under bulk_v3 it does NOT (below the record floor: the dip
never reaches BLS).

The guards prove the mask does not eat real signals: a clean
WASP-29b-equivalent transit (P 3.9227 d, 1.14% — the known planet
v2 recovered and v1 missed), the same transit with scattered-light
flags on non-transit cadences, and a transit sitting on bit-12
(4096) cadences (the TOI-700 c lesson: bit 12 must stay unmasked).

Note on depths: the fixture depths are the SCREEN-measured depths
from the ledger (0.5-2.9%), not the raw unmasked fold depths
(1.5-9.3%) — real scattered-light ramps are not box-shaped, so
BLS measures a shallower effective depth than the raw fold. The
fixture reproduces the failure mode (a flagged-only signal the
screen promotes), not the ramp shape.
"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np  # noqa: E402

import bulk_screen as bs  # noqa: E402
from synth_fits import make_qlp_fits, screen_job  # noqa: E402

# (label, period_d, depth_frac, flag_bit, flagged_frac, t0, noise)
# Screen depths/periods from the gauntlet ledger; t0=1501.0 on the
# 12.6 d cells so all three events fall inside the 27 d span (Tier A
# needs >= 3 events).
ARTIFACT_CELLS = [
    ("382256433-like", 12.6438, 0.029, 30, 1.0, 1501.0, 0.003),
    ("382571558-like", 12.2903, 0.0204, 29, 1.0, 1501.0, 0.003),
    ("355401152-like", 6.5138, 0.0291, 30, 1.0, None, 0.003),
    ("12.64d-partial-flag", 12.6438, 0.02, 30, 0.7, 1501.0, 0.003),
    ("141865558-like", 6.2810, 0.0049, 29, 1.0, None, 0.001),
]

WASP29B_PERIOD = 3.9227
WASP29B_DEPTH = 0.0114


def _flag_out_of_transit(frac, bit, seed=7):
    """quality callable: flag `frac` of OUT-of-transit cadences
    with `bit` (scattered-light stretches that do not overlap
    the transit)."""
    def _q(t, in_transit):
        rng = np.random.default_rng(seed)
        q = np.zeros(len(t), dtype=np.int32)
        out = np.where(~in_transit)[0]
        n = int(round(frac * len(out)))
        q[rng.choice(out, size=n, replace=False)] = np.int32(1 << bit)
        return q
    return _q


def _flag_in_transit(bit):
    """quality callable: flag every in-transit cadence with `bit`."""
    def _q(t, in_transit):
        return np.where(in_transit, np.int32(1 << bit),
                        np.int32(0)).astype(np.int32)
    return _q


class TestQualityMask(unittest.TestCase):
    def setUp(self):
        self._previous = bs.CALIBRATION_VERSION

    def tearDown(self):
        bs.set_calibration(self._previous)

    def _screen(self, path, calibration):
        bs.set_calibration(calibration)
        return bs._screen_one(screen_job(path))

    def test_mask_values_by_calibration(self):
        # v1/v2 predate the field and mean the lightkurve default;
        # v3 adds bits 29/30 (TESS scattered light).
        for name, expected in (("bulk_v1", 17087),
                               ("bulk_v2", 17087),
                               ("bulk_v3", 1610629823)):
            bs.set_calibration(name)
            self.assertEqual(bs.QUALITY_MASK, expected, name)
        # The v3 value is exactly default + bits 29/30, nothing else.
        bs.set_calibration("bulk_v3")
        self.assertEqual(bs.QUALITY_MASK, 17087 | (1 << 29) | (1 << 30))

    def test_flagged_artifacts_promoted_under_v2_rejected_under_v3(self):
        # The core regression (claims C-1): every artifact cell
        # promotes under v2 and falls below the record floor
        # under v3 — the dip never reaches BLS.
        with tempfile.TemporaryDirectory() as td:
            for label, period, depth, bit, frac, t0, noise in \
                    ARTIFACT_CELLS:
                path = Path(td) / f"{label}.fits"
                kw = dict(period_d=period, depth_frac=depth,
                          duration_d=0.1, noise_pct=noise, seed=42,
                          flagged_only_frac=frac, flag_bit=bit)
                if t0 is not None:
                    kw["t0"] = t0
                make_qlp_fits(path, **kw)
                v2 = self._screen(path, "bulk_v2")
                self.assertEqual(v2["status"], "survivor", label)
                self.assertEqual(v2["tier"], "A", label)
                self.assertAlmostEqual(v2["period_days"], period,
                                       delta=0.05, msg=label)
                v3 = self._screen(path, "bulk_v3")
                self.assertEqual(v3["status"], "below_floor", label)
                self.assertLess(v3["sde"], 6.0, label)

    def test_wasp29b_clean_transit_survives_under_v3(self):
        # Sensitivity guard (C-2): the known planet v2 recovered
        # and v1 missed must still be found under v3.
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "w29b.fits"
            make_qlp_fits(path, period_d=WASP29B_PERIOD,
                          depth_frac=WASP29B_DEPTH, duration_d=0.1,
                          noise_pct=0.003, seed=42)
            for cal in ("bulk_v2", "bulk_v3"):
                r = self._screen(path, cal)
                self.assertEqual(r["status"], "survivor", cal)
                self.assertEqual(r["tier"], "A", cal)
                self.assertAlmostEqual(r["period_days"],
                                       WASP29B_PERIOD, delta=0.05,
                                       msg=cal)

    def test_transit_with_flags_elsewhere_survives_under_v3(self):
        # Sensitivity guard (C-3): scattered-light flags on
        # non-transit cadences must not kill a real transit —
        # the mask removes the flagged cadences, not the signal.
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "w29b-flagged.fits"
            make_qlp_fits(path, period_d=WASP29B_PERIOD,
                          depth_frac=WASP29B_DEPTH, duration_d=0.1,
                          noise_pct=0.003, seed=42,
                          quality=_flag_out_of_transit(0.10, 29))
            for cal in ("bulk_v2", "bulk_v3"):
                r = self._screen(path, cal)
                self.assertEqual(r["status"], "survivor", cal)
                self.assertAlmostEqual(r["period_days"],
                                       WASP29B_PERIOD, delta=0.05,
                                       msg=cal)

    def test_bit12_transit_still_survives_under_v3(self):
        # Selectivity guard (C-4): bit 12 (4096) is NOT in the
        # mask — TOI-700 c's only sector-1 transit sits on bit-12
        # cadences, and masking them would delete real planets.
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "w29b-bit12.fits"
            make_qlp_fits(path, period_d=WASP29B_PERIOD,
                          depth_frac=WASP29B_DEPTH, duration_d=0.1,
                          noise_pct=0.003, seed=42,
                          quality=_flag_in_transit(12))
            for cal in ("bulk_v2", "bulk_v3"):
                r = self._screen(path, cal)
                self.assertEqual(r["status"], "survivor", cal)
                self.assertAlmostEqual(r["period_days"],
                                       WASP29B_PERIOD, delta=0.05,
                                       msg=cal)

    def test_flagged_fraction_and_tally_on_artifact(self):
        # M-4: the 70%-flagged artifact cell, measured on the RAW
        # arrays. Under v2 it promotes -- and the record says so:
        # ~70% of its in-transit cadences are flagged, and the
        # tally names bit 30 as the unmasked bit carrying them.
        # Under v3 the same fixture falls below the floor, and
        # below-floor records carry NO M-4 fields: there is no
        # detection to diagnose (the BLS argmax there is a noise
        # peak, so a fraction at that ephemeris would measure
        # noise, not the signal).
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "partial.fits"
            make_qlp_fits(path, period_d=12.6438, depth_frac=0.02,
                          duration_d=0.1, noise_pct=0.003, seed=42,
                          flagged_only_frac=0.7, flag_bit=30,
                          t0=1501.0)
            v2 = self._screen(path, "bulk_v2")
            self.assertEqual(v2["status"], "survivor")
            self.assertAlmostEqual(v2["flagged_in_transit_frac"],
                                   0.7, delta=0.15)
            self.assertIn(30, v2["unmasked_bits_in_transit"])
            self.assertGreater(
                v2["unmasked_bits_in_transit"][30], 5)
            v3 = self._screen(path, "bulk_v3")
            self.assertEqual(v3["status"], "below_floor")
            self.assertNotIn("flagged_in_transit_frac", v3)
            self.assertNotIn("unmasked_bits_in_transit", v3)

    def test_flagged_fraction_and_tally_on_bit12_transit(self):
        # M-4: the TOI-700 c class -- a REAL transit with a
        # flagged fraction of ~1.0. The fraction is a diagnostic,
        # not a veto: it must be recorded, not acted on. The
        # tally names bit 12 (unmasked under every calibration).
        # The emitted record (JSON round-trip: int tally keys
        # become strings) still validates against the schema.
        import json

        import provenance as prov
        from bulk_screen import emit_survivor_record
        from validation import validate_survivor
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "w29b-bit12.fits"
            make_qlp_fits(path, period_d=WASP29B_PERIOD,
                          depth_frac=WASP29B_DEPTH, duration_d=0.1,
                          noise_pct=0.003, seed=42,
                          quality=_flag_in_transit(12))
            r = self._screen(path, "bulk_v3")
            self.assertEqual(r["status"], "survivor")
            self.assertGreater(r["flagged_in_transit_frac"], 0.9)
            self.assertIn(12, r["unmasked_bits_in_transit"])
            self.assertGreater(r["unmasked_bits_in_transit"][12],
                               20)
            h = prov.provenance_header(
                "test-run-m4", {"bulk": "v3"}, sha="abc1234",
                timestamp_utc="2026-11-15T06:00:00+00:00")
            emitted = emit_survivor_record(r, h)
            self.assertIn("flagged_in_transit_frac", emitted)
            self.assertIn("unmasked_bits_in_transit", emitted)
            round_tripped = json.loads(json.dumps(emitted))
            self.assertEqual(
                round_tripped["unmasked_bits_in_transit"],
                {str(k): v for k, v in
                 r["unmasked_bits_in_transit"].items()})
            validate_survivor(round_tripped)  # must not raise

    def test_clean_transit_has_zero_flagged_fraction(self):
        # M-4 control: a clean transit carries fraction 0.0 and
        # an empty tally under v3.
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "w29b.fits"
            make_qlp_fits(path, period_d=WASP29B_PERIOD,
                          depth_frac=WASP29B_DEPTH, duration_d=0.1,
                          noise_pct=0.003, seed=42)
            r = self._screen(path, "bulk_v3")
            self.assertEqual(r["status"], "survivor")
            self.assertEqual(r["flagged_in_transit_frac"], 0.0)
            self.assertEqual(r["unmasked_bits_in_transit"], {})


if __name__ == "__main__":
    unittest.main()
