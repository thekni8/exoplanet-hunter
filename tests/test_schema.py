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
from validation import (RecordValidationError, validate_desk_natives,  # noqa: E402
                        validate_survivor, validate_verdict)

FIXED_PROV = prov.provenance_header(
    "test-run-1", {"bulk": "v1"}, sha="abc1234",
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


def _complete_desk_natives():
    return {
        "natives": {
            "catalogue.native": {"known": False, "source": None,
                                 "var_type": None,
                                 "period_match": False},
            "clean_refold.native": [
                {"n_clean": 1200, "n_in": 45, "n_events": 10,
                 "depth_percent": 0.95, "snr": 40.0,
                 "quality_mask": 1610629823,
                 "flagged_fold": {"n_clean": 1200, "n_in": 0,
                                  "n_events": 0,
                                  "depth_percent": None,
                                  "snr": None}},
                "PASS"],
            "refine.native": {"period_d": 2.5, "t0": 1502.0,
                              "duration_d": 0.1, "converged": True,
                              "rms_resid_d": 0.0001, "n_eras": 3},
            "raw_flux.native": {"depth_pct": 0.95,
                                "signif_white": 40.0,
                                "signif_red": 20.0, "n_in": 45,
                                "n_events": 10,
                                "sig_white_pct": 0.02,
                                "sig_red_pct": 0.05},
            "shape.native": {"method": "trapezoid_fit",
                             "T14_h": 2.4, "T23_T14": 0.5,
                             "frac_err": 0.1, "depth0_signif": 40.0,
                             "shape_verdict": "U-shaped",
                             "density_flag": False},
            "odd_even.native": [
                {"depth_pct": 0.95, "sig_white_pct": 0.02,
                 "signif_white": 40.0, "n_in": 22, "n_events": 5},
                None],
            "persistence.native": {"n_usable": 3,
                                   "verdict": "CONSISTENT"},
            "pixel_check.native": {
                "verdict": "pass",
                "reason": "all pixels consistent",
                "details": {"n_in": 45, "n_pixels_tested": 9,
                            "target_pixel": {"y": 1, "x": 1,
                                             "depth_pct": 0.95,
                                             "signif": 40.0}}},
            "holdout.native": "HOLDOUT-PASS",
            "diffimg.native": {"on_target": True, "offset_px": 0.06,
                               "offset_arcsec": 1.3,
                               "blend_host_tic": None, "n_sectors": 3,
                               "offset_sigma_px": 0.1,
                               "offset_over_sigma": 0.6,
                               "sigma_source": "split_half_scatter"},
            "transit_fit.native": {"b": 0.2, "rp_re": 2.5,
                                   "t14_h": 2.4,
                                   "density_flag": False,
                                   "converged": True, "chi2": 120.0,
                                   "npts": 3000},
        },
        "extra_evidence": {
            "survivor": {"tic": "999999999", "period_d": 2.5,
                         "t0_btjd": 1502.0, "duration_h": 2.4,
                         "depth_pct": 0.95, "sde": 59.9,
                         "sector": 96, "bulk_survivor": True},
            "pipeline_set": {"pfx": "SPOC", "sectors": [96]},
            "refined_ephemeris": {"period_d": 2.5,
                                  "t0_btjd": 1502.0,
                                  "converged": True},
            "external_tools": {
                "latte": {"stage": "latte", "status": "report_only",
                          "reason": "report-only evidence"}},
            "waivers_dropped": {"odd_even": "waiver requires a "
                                             "measured native"},
        },
        "run": {"final_verdict": "CANDIDATE",
                "verdict_note": None,
                "skipped": [["transit_fit",
                             "skipped after diffimg failed"]],
                "cached": False,
                "context_hash": "abc123"},
    }


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


class TestDeskNativesValidation(unittest.TestCase):
    """P-18: desk_natives.json is the Phase 3 feature-list
    contract. The driver validates every record before writing
    it, so these pin the schema itself; the desk driver tests
    prove real payloads validate."""

    def test_complete_record_validates(self):
        validate_desk_natives(_complete_desk_natives())

    def test_missing_required_field_fails(self):
        rec = _complete_desk_natives()
        del rec["run"]
        with self.assertRaises(RecordValidationError):
            validate_desk_natives(rec)

    def test_extra_native_key_fails(self):
        rec = _complete_desk_natives()
        rec["natives"]["new_stage.native"] = {"method": "x"}
        with self.assertRaises(RecordValidationError):
            validate_desk_natives(rec)

    def test_wrong_type_fails(self):
        rec = _complete_desk_natives()
        rec["natives"]["shape.native"]["method"] = 42
        with self.assertRaises(RecordValidationError):
            validate_desk_natives(rec)

    def test_shape_method_only_validates(self):
        # Early exits return a subset: only method is required.
        rec = _complete_desk_natives()
        rec["natives"]["shape.native"] = {
            "method": "trapezoid_fit", "verdict": "unmeasured",
            "reason": "no usable in-transit points"}
        validate_desk_natives(rec)

    def test_flagged_fold_has_no_quality_mask(self):
        # _flagged_fold returns the clean_fold shape WITHOUT
        # quality_mask (its docstring claims otherwise). If the
        # code ever adds the mask, the schema must change with
        # it — the desk tests would fail loudly first.
        rec = _complete_desk_natives()
        flagged = rec["natives"]["clean_refold.native"][0]
        flagged = flagged["flagged_fold"]
        flagged["quality_mask"] = 1610629823
        with self.assertRaises(RecordValidationError):
            validate_desk_natives(rec)

    def test_skipped_is_stage_reason_pairs(self):
        rec = _complete_desk_natives()
        rec["run"]["skipped"] = ["transit_fit"]
        with self.assertRaises(RecordValidationError):
            validate_desk_natives(rec)

    def test_real_holdout_dict_validates(self):
        # The holdout dict shape as holdout_test returns it: the
        # identity + ephemeris fields on top, sigma_pct on usable
        # folds. (No driver path writes the dict today — the live
        # source returns only the verdict string — but the dict
        # branch must describe the real record, not a guess.)
        rec = _complete_desk_natives()
        rec["natives"]["holdout.native"] = {
            "tic": "999999999", "period_days": 2.5,
            "t0_btjd": 1502.0, "duration_hours": 2.4,
            "n_sectors_total": 3, "sectors": [96, 97, 98],
            "criteria": {"min_usable_folds": 3,
                         "min_total_full_events": 3,
                         "fold_signif_bar": 3.0, "opposite_bar": -3.0,
                         "pass_rule": "strict majority"},
            "folds": [{"fold": 0, "held_out_sectors": [96],
                       "tmin": 1500.0, "tmax": 1527.0,
                       "n_raw_points": 3888, "usable": True,
                       "reason": None,
                       "refined_period_days": 2.5,
                       "refined_t0_btjd": 1502.0,
                       "events_in_span": 10, "full_events": 10,
                       "depth_pct": 0.95, "signif": 40.0,
                       "n_chunks_out": 5, "sigma_pct": 0.02}],
            "verdict": "HOLDOUT-PASS", "n_folds": 3,
            "n_usable_folds": 3, "total_full_events_held_out": 30,
            "folds_at_or_above_bar": 3, "folds_opposite": 0,
            "combined_depth_pct": 0.95, "combined_signif": 40.0}
        validate_desk_natives(rec)


if __name__ == "__main__":
    unittest.main()
