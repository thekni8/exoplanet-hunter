"""Tests for runtime schema validation (validation.py).

No downloads. The key test runs a REAL screen record through the
validator: _screen_one on a synthetic FITS, emitted through the
production emit path, must validate — so the schema and the code
cannot drift silently (they already had: Phase 1 declared the
survivor `tic` an integer, but the code writes strings throughout
— the schema now says string, and test_wrong_type_fails pins it).
"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import provenance as prov  # noqa: E402
from bulk_screen import _screen_one, emit_survivor_record  # noqa: E402
from synth_fits import make_qlp_fits, screen_job  # noqa: E402
from validation import (RecordValidationError, validate_survivor,  # noqa: E402
                        validate_verdict)

FIXED_PROV = prov.provenance_header(
    "test-run-1", "bulk_v1", sha="abc1234",
    timestamp_utc="2026-11-14T06:00:00+00:00")


def _complete_survivor():
    rec = {"tic": "999999999", "sector": 96, "product": "QLP",
           "status": "survivor", "period_days": 2.5, "t0_btjd": 1502.0,
           "duration_hours": 2.4, "depth_percent": 1.0, "sde": 59.9,
           "ra": 100.0, "dec": -65.0, "tmag": 12.0, "radius_rsun": 0.7,
           "flags": [], "odd_even_ratio": 0.99,
           "secondary_depth_percent": 0.01, "near_systematic": False,
           "tier": "A", "mes_pink": 17.3, "cdpp_pct": 0.13,
           "n_events": 10, "n_strong_events": 10, "max_event_snr": 6.3,
           "v_ratio": 0.9, "control": False,
           "alt_peaks": [{"period_days": 5.0, "sde": 12.0,
                          "depth_percent": 0.5}],
           "clean_gate": "PASS",
           "clean_fold": {"n_clean": 1200, "n_in": 45, "n_events": 10,
                          "depth_percent": 0.95, "snr": 40.0}}
    rec.update(FIXED_PROV)
    return rec


def _complete_verdict():
    rec = {"tic": "423498314",
           "filed": {"period_days": 0.827047, "sde": 34.0,
                     "depth_pct": 1.029},
           "final_verdict": "CANDIDATE",
           "rawflux_verdict": "RAW-CONFIRMED",
           "shape_gate": {"shape_verdict": "V-shaped",
                          "T23_T14": 0.25, "T14_h": 1.41,
                          "depth_frac": 0.0103, "density_flag": True},
           "holdout_verdict": "HOLDOUT-PASS",
           "imaging": {"on_target": True, "offset_px": 0.06,
                       "offset_arcsec": 1.3, "blend_host_tic": None},
           "ephemeris_used": {"period_d": 0.827047, "t0": 1500.5,
                              "duration_d": 0.059,
                              "source": "phase-scan refinement"},
           "verdict_note": "Survived every gate; grazing shape keeps "
                           "the EB-on-companion alternative alive."}
    rec.update(FIXED_PROV)
    return rec


class TestSurvivorValidation(unittest.TestCase):
    def test_real_screen_output_validates(self):
        # The validator test against real output: a record produced
        # by the actual screen code, through the production emit
        # path, must validate. If the code adds a field the schema
        # does not declare, this goes red.
        with tempfile.TemporaryDirectory() as td:
            p = make_qlp_fits(Path(td) / "planet.fits", period_d=2.5,
                              depth_frac=0.01, duration_d=0.1,
                              noise_pct=0.003, seed=42)
            raw = _screen_one(screen_job(p))
            self.assertEqual(raw["status"], "survivor")
            rec = emit_survivor_record(raw, FIXED_PROV)
            validate_survivor(rec)  # must not raise

    def test_complete_survivor_validates(self):
        validate_survivor(_complete_survivor())

    def test_missing_required_field_fails(self):
        rec = _complete_survivor()
        del rec["run_id"]
        with self.assertRaises(RecordValidationError):
            validate_survivor(rec)

    def test_extra_field_fails(self):
        # additionalProperties: false — an agent's "helpful" extra
        # key must fail loudly, not silently break downstream parsers.
        rec = _complete_survivor()
        rec["notes_2"] = "a helpful extra key"
        with self.assertRaises(RecordValidationError):
            validate_survivor(rec)

    def test_wrong_type_fails(self):
        # tic is a STRING in the bulk screen (the TOI join compares
        # strings). An integer tic is a bug, not a synonym.
        rec = _complete_survivor()
        rec["tic"] = 999999999
        with self.assertRaises(RecordValidationError):
            validate_survivor(rec)

    def test_bad_timestamp_fails(self):
        rec = _complete_survivor()
        rec["timestamp_utc"] = "yesterday"
        with self.assertRaises(RecordValidationError):
            validate_survivor(rec)

    def test_bad_status_enum_fails(self):
        rec = _complete_survivor()
        rec["status"] = "maybe"
        with self.assertRaises(RecordValidationError):
            validate_survivor(rec)


class TestVerdictValidation(unittest.TestCase):
    def test_complete_verdict_validates(self):
        validate_verdict(_complete_verdict())

    def test_missing_required_field_fails(self):
        rec = _complete_verdict()
        del rec["final_verdict"]
        with self.assertRaises(RecordValidationError):
            validate_verdict(rec)

    def test_extra_field_fails(self):
        rec = _complete_verdict()
        rec["sde_raw"] = 34.0
        with self.assertRaises(RecordValidationError):
            validate_verdict(rec)


if __name__ == "__main__":
    unittest.main()
