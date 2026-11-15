"""Tests for the grid-edge disposition (Phase 3, P3-14).

Offline, no downloads. The disposition logic is pure (dicts in,
disposition out); the wiring test runs _screen_one on a synthetic
FITS and checks the new fields flow through the production emit
path and validate against the schema.
"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np  # noqa: E402
import provenance as prov  # noqa: E402
import search_health as health  # noqa: E402
from bulk.grid_edge import (GRID_EDGE_MIN_IN_TRANSIT_CADENCES,  # noqa: E402
                            LEDGER_DEFERRED, build_handoff_record,
                            disposition_grid_edge,
                            is_grid_edge_record)
from bulk_screen import (_attach_grid_edge_disposition,  # noqa: E402
                         _raw_in_transit_flags, _screen_one,
                         emit_survivor_record)
from synth_fits import make_qlp_fits, screen_job  # noqa: E402
from validation import validate_survivor  # noqa: E402

FIXED_PROV = prov.provenance_header(
    "test-run-grid-edge", {"bulk": "v1"}, sha="abc1234",
    timestamp_utc="2026-11-15T20:30:00+00:00")


def _edge_rec(**over):
    rec = {"tic": "123456789", "sector": 96, "period_days": 20.0,
           "t0_btjd": 3910.0, "duration_hours": 2.4,
           "depth_percent": 0.9, "sde": 23.0, "n_events": 1,
           "n_strong_events": 1, "max_event_snr": 14.0,
           "mes_pink": 14.0, "tier": "B", "status": "survivor",
           "flagged_in_transit_frac": 0.0,
           "unmasked_bits_in_transit": {}, "n_in_transit": 6}
    rec.update(over)
    return rec


class TestIsGridEdge(unittest.TestCase):
    def test_period_20_is_edge(self):
        self.assertTrue(is_grid_edge_record({"period_days": 20.0}))

    def test_period_199_is_not_edge(self):
        self.assertFalse(is_grid_edge_record({"period_days": 19.9}))

    def test_low_edge_is_not_grid_edge(self):
        # P3-14 is the P = 20.0 singles; the 0.5 d edge is out
        # of scope (no pile-up observed there).
        self.assertFalse(is_grid_edge_record({"period_days": 0.5}))

    def test_missing_period_is_not_edge(self):
        self.assertFalse(is_grid_edge_record({}))
        self.assertFalse(is_grid_edge_record({"period_days": None}))


class TestDisposition(unittest.TestCase):
    def test_non_edge_is_undispositioned(self):
        disp, reason = disposition_grid_edge(
            _edge_rec(period_days=5.0))
        self.assertIsNone(disp)
        self.assertIn("not a grid-edge", reason)

    def test_multi_event_edge_stays_periodic(self):
        disp, reason = disposition_grid_edge(
            _edge_rec(n_events=3))
        self.assertEqual(disp, health.PERIODIC_CANDIDATE)
        self.assertIn("multi-event", reason)

    def test_floor_pass_pools(self):
        disp, _reason = disposition_grid_edge(_edge_rec())
        self.assertEqual(disp, health.SINGLE_TRANSIT_POOL)

    def test_unmasked_flags_reject_without_cadence_count(self):
        # The flag leg fails on evidence alone — no n_in_transit
        # needed. This is what makes legacy rescore rows with a
        # non-empty unmasked tally dispositionable.
        rec = _edge_rec(unmasked_bits_in_transit={"12": 3})
        del rec["n_in_transit"]
        disp, reason = disposition_grid_edge(rec)
        self.assertEqual(disp, health.GRID_EDGE_REJECT)
        self.assertIn("unmasked", reason)

    def test_few_cadences_reject(self):
        disp, reason = disposition_grid_edge(
            _edge_rec(n_in_transit=2))
        self.assertEqual(disp, health.GRID_EDGE_REJECT)
        self.assertIn("fewer than 4", reason)

    def test_floor_boundary_four_cadences_pools(self):
        disp, _reason = disposition_grid_edge(
            _edge_rec(n_in_transit=GRID_EDGE_MIN_IN_TRANSIT_CADENCES))
        self.assertEqual(disp, health.SINGLE_TRANSIT_POOL)

    def test_missing_cadence_count_is_unevaluable(self):
        # Legacy rescore rows carry no n_in_transit: with a clean
        # flag state they are NOT pooled or rejected by fiat.
        rec = _edge_rec()
        del rec["n_in_transit"]
        disp, reason = disposition_grid_edge(rec)
        self.assertIsNone(disp)
        self.assertIn("unevaluable", reason)

    def test_missing_everything_is_unevaluable(self):
        rec = _edge_rec()
        del rec["n_in_transit"]
        del rec["unmasked_bits_in_transit"]
        disp, reason = disposition_grid_edge(rec)
        self.assertIsNone(disp)
        self.assertIn("unevaluable", reason)

    def test_unknown_event_count_is_unevaluable(self):
        rec = _edge_rec()
        del rec["n_events"]
        disp, reason = disposition_grid_edge(rec)
        self.assertIsNone(disp)
        self.assertIn("unevaluable", reason)

    def test_explicit_fraction_field(self):
        # The DF-13 deep-pipeline field, when present, governs.
        disp, _ = disposition_grid_edge(_edge_rec(
            in_transit_unmasked_flag_fraction=0.0))
        self.assertEqual(disp, health.SINGLE_TRANSIT_POOL)
        disp, _ = disposition_grid_edge(_edge_rec(
            in_transit_unmasked_flag_fraction=0.25))
        self.assertEqual(disp, health.GRID_EDGE_REJECT)

    def test_positive_flag_cap_is_unsupported(self):
        # The floor is a zero test; a positive cap needs its own
        # vote, so the function refuses rather than guessing.
        disp, reason = disposition_grid_edge(
            _edge_rec(), max_unmasked_fraction=0.1)
        self.assertIsNone(disp)
        self.assertIn("zero test", reason)


class TestHandoffRecord(unittest.TestCase):
    def test_handoff_is_complete_and_deferred(self):
        rec = _edge_rec()
        handoff = build_handoff_record(rec, camera=1, ccd=2)
        self.assertEqual(handoff["tic"], "123456789")
        self.assertEqual(handoff["epoch_btjd"], 3910.0)
        self.assertEqual(handoff["depth_percent"], 0.9)
        self.assertEqual(handoff["duration_hours"], 2.4)
        self.assertEqual(handoff["max_event_snr"], 14.0)
        self.assertEqual(handoff["camera_ccd"], {"camera": 1,
                                                 "ccd": 2})
        self.assertEqual(handoff["flagged_in_transit_frac"], 0.0)
        self.assertEqual(handoff["n_in_transit"], 6)
        self.assertEqual(handoff["disposition"],
                         health.SINGLE_TRANSIT_POOL)
        self.assertEqual(handoff["ledger_status"], LEDGER_DEFERRED)

    def test_handoff_missing_camera_is_none(self):
        handoff = build_handoff_record(_edge_rec())
        self.assertEqual(handoff["camera_ccd"],
                         {"camera": None, "ccd": None})


class TestRawInTransitFlags(unittest.TestCase):
    def test_returns_n_in_transit(self):
        t = np.arange(0.0, 10.0, 0.02)
        q = np.zeros(len(t), dtype=np.int64)
        # One cadence in transit carries unmasked bit 12.
        q[250] = 4096
        frac, tally, n_in = _raw_in_transit_flags(
            t, q, period=5.0, t0=5.0, duration=0.1)
        self.assertGreater(n_in, 0)
        self.assertEqual(tally, {12: 1})
        self.assertAlmostEqual(frac, 1.0 / n_in)

    def test_no_cadence_in_transit(self):
        # Baseline phases [-0.5, -0.4) at P = 5, t0 = 52.5: the
        # in-transit window (|phase| < 0.01) is nowhere covered.
        t = np.arange(0.0, 0.5, 0.02)
        q = np.zeros(len(t), dtype=np.int64)
        frac, tally, n_in = _raw_in_transit_flags(
            t, q, period=5.0, t0=52.5, duration=0.1)
        self.assertIsNone(frac)
        self.assertEqual(tally, {})
        self.assertEqual(n_in, 0)


class TestWiring(unittest.TestCase):
    def test_screen_one_records_n_in_transit(self):
        with tempfile.TemporaryDirectory() as td:
            p = make_qlp_fits(Path(td) / "planet.fits", period_d=2.5,
                              depth_frac=0.01, duration_d=0.1,
                              noise_pct=0.003, seed=42)
            raw = _screen_one(screen_job(p))
            self.assertEqual(raw["status"], "survivor")
            self.assertIn("n_in_transit", raw)
            self.assertIsInstance(raw["n_in_transit"], int)
            self.assertGreater(raw["n_in_transit"], 0)
            # A 2.5 d periodic record is not grid-edge: no
            # disposition field is attached.
            self.assertNotIn("disposition", raw)
            rec = emit_survivor_record(raw, FIXED_PROV)
            validate_survivor(rec)  # must not raise

    def test_attach_helper_sets_fields(self):
        rec = _edge_rec()
        _attach_grid_edge_disposition(rec, camera=3, ccd=4)
        self.assertEqual(rec["disposition"],
                         health.SINGLE_TRANSIT_POOL)
        self.assertIn("grid_edge", rec)
        self.assertEqual(rec["grid_edge"]["camera_ccd"],
                         {"camera": 3, "ccd": 4})
        self.assertEqual(rec["grid_edge"]["ledger_status"],
                         LEDGER_DEFERRED)

    def test_attach_helper_noop_when_unevaluable(self):
        rec = _edge_rec()
        del rec["n_in_transit"]
        _attach_grid_edge_disposition(rec)
        self.assertNotIn("disposition", rec)
        self.assertNotIn("grid_edge", rec)

    def test_grid_edge_record_validates(self):
        rec = _edge_rec()
        _attach_grid_edge_disposition(rec, camera=1, ccd=1)
        out = {k: rec[k] for k in (
            "tic", "sector", "period_days", "t0_btjd",
            "duration_hours", "depth_percent", "sde", "status",
            "tier", "mes_pink", "n_events", "n_strong_events",
            "max_event_snr", "flagged_in_transit_frac",
            "unmasked_bits_in_transit", "n_in_transit",
            "disposition", "grid_edge") if rec.get(k) is not None}
        out.update(FIXED_PROV)
        out["product"] = "QLP"
        validate_survivor(out)  # must not raise


if __name__ == "__main__":
    unittest.main()
