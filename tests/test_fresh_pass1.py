"""Tests for the fresh pass-1 establishment driver
(bulk/fresh_pass1.py, Phase 4.1 item 4.1-4).

Offline: synthetic QLP FITS only, no downloads, no Mac. The
end-to-end test runs the real _screen_one on a synthetic
injected curve (slow-ish by design -- it exercises the exact
path the Mac run takes, minus the real FITS).
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import bulk_screen as bs  # noqa: E402
from bulk import fresh_pass1  # noqa: E402
from synth_fits import make_qlp_fits  # noqa: E402


class TestScreenRecord(unittest.TestCase):
    def test_field_mapping(self):
        # The P3-10 mapping: the screen's n_events becomes
        # n_events_found; the group logic reads n_events_found.
        r = {"sde": 9.1, "mes_pink": 8.0, "status": "recorded",
             "tier": None, "period_days": 3.0, "t0_btjd": 1501.0,
             "duration_hours": 2.4, "depth_percent": 0.5,
             "flags": [], "odd_even_ratio": 1.0,
             "search_health": "ok", "n_events": 4,
             "n_strong_events": 2, "max_event_snr": 7.5,
             "gate_reason": None}
        out = fresh_pass1._screen_record(r)
        self.assertEqual(out["n_events_found"], 4)
        self.assertEqual(out["period_days"], 3.0)
        self.assertEqual(out["status"], "recorded")
        self.assertEqual(out["t0_btjd"], 1501.0)
        self.assertNotIn("n_events", out)

    def test_below_floor_record(self):
        # A below-floor screen has no rs fields -- the record
        # carries Nones, not a crash.
        r = {"sde": 4.0, "status": "below_floor", "tier": None,
             "period_days": None, "depth_percent": None,
             "flags": []}
        out = fresh_pass1._screen_record(r)
        self.assertEqual(out["status"], "below_floor")
        self.assertIsNone(out["period_days"])
        self.assertIsNone(out["n_events_found"])


class TestRunHostPass1(unittest.TestCase):
    def test_end_to_end_synthetic(self):
        # One synthetic host, two trials: a deep short-period
        # planet (should be found) and a shallow one. The trial
        # records carry epoch_btjd, duration_d,
        # n_events_expected, the screen, and recovered.
        bs.set_calibration("bulk_v5")
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            fits = base / "123.fits"
            make_qlp_fits(fits, n_points=1296, cadence_min=30.0,
                          t_start=1500.0, period_d=None,
                          noise_pct=0.003, seed=42)
            job = {"tic": "123", "sector": 95,
                   "path": str(fits),
                   "trials": [
                       {"trial_id": "planet01", "period_d": 2.0,
                        "epoch_offset_d": 1.0, "depth_frac": 0.01,
                        "duration_d": 2.0 * 2.0 ** (1 / 3) / 24.0,
                        "seed": 41040001, "trial_index": 0},
                       {"trial_id": "planet02", "period_d": 5.0,
                        "epoch_offset_d": 2.0, "depth_frac": 0.002,
                        "duration_d": 2.0 * 5.0 ** (1 / 3) / 24.0,
                        "seed": 41040002, "trial_index": 1}],
                   "out_dir": str(base / "out"),
                   "workdir": str(base / "out" / "injected"),
                   "calibration": "bulk_v5",
                   "pre_manifest_sha": "test-sha"}
            (base / "out" / "hosts").mkdir(parents=True)
            (base / "out" / "injected").mkdir(parents=True)
            res = fresh_pass1.run_host_pass1(job)
            self.assertEqual(res["status"], "done")
            self.assertEqual(res["n_trials"], 2)
            rec = json.loads(
                (base / "out" / "hosts" / "123_s0095.json")
                .read_text())
            self.assertTrue(rec["complete"])
            self.assertEqual(rec["calibration"], "bulk_v5")
            self.assertEqual(len(rec["trials"]), 2)
            tr0 = rec["trials"][0]
            self.assertEqual(tr0["trial_id"], "planet01")
            # epoch_btjd = t_min + offset; duration from the law.
            self.assertAlmostEqual(tr0["epoch_btjd"], 1501.0,
                                   places=6)
            self.assertAlmostEqual(tr0["inject_epoch_delta_d"],
                                   0.0, places=9)
            self.assertAlmostEqual(tr0["inject_dur_delta_d"], 0.0,
                                   places=9)
            self.assertGreater(tr0["n_events_expected"], 0)
            self.assertIn("screen", tr0)
            self.assertIn("recovered", tr0)
            # The deep 2 d planet on a quiet synthetic curve is
            # found (the screen sees a 1% transit at SDE >> 7).
            self.assertTrue(tr0["recovered"])
            self.assertIsNotNone(
                tr0["screen"]["period_days"])
            self.assertAlmostEqual(
                tr0["screen"]["period_days"], 2.0, delta=0.05)

    def test_resume_skips(self):
        # A second run with the same pre-manifest sha +
        # calibration skips the host (resume); a different sha
        # re-runs it.
        bs.set_calibration("bulk_v5")
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            fits = base / "123.fits"
            make_qlp_fits(fits, n_points=1296, cadence_min=30.0,
                          t_start=1500.0, period_d=None,
                          noise_pct=0.003, seed=42)
            job = {"tic": "123", "sector": 95,
                   "path": str(fits),
                   "trials": [
                       {"trial_id": "planet01", "period_d": 2.0,
                        "epoch_offset_d": 1.0, "depth_frac": 0.01,
                        "duration_d": 2.0 * 2.0 ** (1 / 3) / 24.0,
                        "seed": 41040001, "trial_index": 0}],
                   "out_dir": str(base / "out"),
                   "workdir": str(base / "out" / "injected"),
                   "calibration": "bulk_v5",
                   "pre_manifest_sha": "test-sha"}
            (base / "out" / "hosts").mkdir(parents=True)
            (base / "out" / "injected").mkdir(parents=True)
            self.assertEqual(
                fresh_pass1.run_host_pass1(job)["status"], "done")
            self.assertEqual(
                fresh_pass1.run_host_pass1(job)["status"],
                "skipped")
            job2 = dict(job, pre_manifest_sha="other-sha")
            self.assertEqual(
                fresh_pass1.run_host_pass1(job2)["status"],
                "done")


if __name__ == "__main__":
    unittest.main()
