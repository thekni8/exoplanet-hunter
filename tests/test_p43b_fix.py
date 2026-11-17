"""Tests for the P4-3b frozen-seed fix (bulk/p43_run.py).

P4-3 FAILED on short-period regression because the per-sector
pre-mask seeded from each sector's FRESH pass-1 peak -- which, on
an injected curve, is the planet itself in 68% of trials, so the
planet was masked out of 1-2 sectors before stitching
(P43_RECORD.md section 4). The fix (P43B_PREREG.md section 0.4)
seeds the NON-ORIGINAL sectors' pre-masks from the FROZEN recorded
period and masks only when the contaminant is confirmed present
in that sector (fold depth > 1% OR fold SNR >= 7.0).

Offline: synthetic arrays only, no downloads, no Mac, no BLS
screen. The seed/eligibility decision lives in the pure helper
_mask_seed_and_eligibility (no I/O), so these tests pin it
without a screen run; the smoke run on the Mac exercises
_process_sector end to end.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bulk import k2_prototype as k2  # noqa: E402
from bulk import oracle_run as orc  # noqa: E402
from bulk import p43_run  # noqa: E402

CADENCE_D = 1.0 / 48.0


def _synth_multi(t0, n, signals, sigma, rng):
    """t, f, q with several box signals.

    signals is a list of (period, epoch, depth, duration)."""
    t = t0 + CADENCE_D * np.arange(n)
    f = 1.0 + rng.normal(0.0, sigma, n)
    q = np.zeros(n, dtype=int)
    for (period, epoch, depth, duration) in signals:
        k_min = int(np.ceil((t[0] - epoch) / period))
        k_max = int(np.floor((t[-1] - epoch) / period))
        for k in range(k_min, k_max + 1):
            tc = epoch + k * period
            m = np.abs(t - tc) <= duration / 2.0
            f[m] -= depth
    return t, f, q


def _in_transit_frac_kept(t, keep, period, epoch, duration):
    """Fraction of in-transit cadences (at the given ephemeris)
    that the keep mask retains."""
    phase = ((t - epoch) % period)
    phase = np.minimum(phase, period - phase)
    in_tr = phase <= duration / 2.0
    if in_tr.sum() == 0:
        return None
    return float(keep[in_tr].mean())


class TestFrozenSeed(unittest.TestCase):
    def _sector(self):
        # Planet P=1.3 d (short-period, deep -- the fresh peak on
        # an injected curve) + contaminant P=3.0 d (deep EB).
        # Non-harmonic periods (3.0/1.3 = 2.31), epochs offset so
        # the two signals' windows do not coincide by construction.
        rng = np.random.default_rng(11)
        t, f, q = _synth_multi(
            3800.0, 1300,
            [(1.3, 3801.0, 0.01, 0.08),
             (3.0, 3801.7, 0.02, 0.12)],
            0.003, rng)
        t_p, f_p = orc.preprocess_arrays(t, f, q)
        return t, f, q, t_p, f_p

    def test_fresh_seed_is_the_planet(self):
        # The P4-3 failure mode, reproduced in miniature: the
        # fresh pass-1 peak is the planet (P=1.3 d), so the fresh
        # path seeds the mask on the planet.
        t, f, q, t_p, f_p = self._sector()
        trial = {"recorded": {"period_days": 3.0,
                              "depth_percent": 2.0}}
        p1 = {"period_days": 1.3, "depth_percent": 1.0,
              "status": "survivor"}
        out = p43_run._mask_seed_and_eligibility(
            t_p, f_p, trial, p1, "fresh")
        self.assertEqual(out["seed_source"], "fresh")
        self.assertAlmostEqual(out["seed_period"], 1.3)
        self.assertTrue(out["eligible"])
        self.assertAlmostEqual(
            out["ephemeris"]["period_ref_d"], 1.3, delta=0.02)

    def test_frozen_seed_masks_contaminant_not_planet(self):
        # The fix: the frozen path seeds from the recorded
        # contaminant period (3.0 d), and the mask it builds drops
        # the contaminant's transits while keeping the planet's.
        t, f, q, t_p, f_p = self._sector()
        trial = {"recorded": {"period_days": 3.0,
                              "depth_percent": 2.0}}
        p1 = {"period_days": 1.3, "depth_percent": 1.0,
              "status": "survivor"}
        out = p43_run._mask_seed_and_eligibility(
            t_p, f_p, trial, p1, "frozen")
        self.assertEqual(out["seed_source"], "frozen")
        self.assertAlmostEqual(out["seed_period"], 3.0)
        self.assertTrue(out["eligible"])
        self.assertEqual(out["reason"], "frozen-contaminant")
        self.assertAlmostEqual(
            out["ephemeris"]["period_ref_d"], 3.0, delta=0.05)
        self.assertGreater(out["ephemeris"]["depth_est_frac"],
                           0.01)
        # The depth passed to the mask is the FROZEN recorded
        # depth (mirroring k2_run), not the fresh peak's.
        self.assertAlmostEqual(out["depth_for_mask"], 2.0)
        keep, mstats = k2.build_k2_mask(
            t, f, q, out["ephemeris"], out["depth_for_mask"],
            secondary=out["secondary"], duty_cap=0.25,
            depth_trigger=False)
        self.assertFalse(mstats["stopped"])
        # The contaminant's transits are (mostly) dropped...
        kept_cont = _in_transit_frac_kept(
            t, keep, 3.0, 3801.7, 0.12)
        self.assertLess(kept_cont, 0.3)
        # ...while the planet's transits are (mostly) kept.
        kept_planet = _in_transit_frac_kept(
            t, keep, 1.3, 3801.0, 0.08)
        self.assertGreater(kept_planet, 0.7)

    def test_frozen_not_confirmed_when_absent(self):
        # No signal at the recorded period (pure noise + a planet
        # elsewhere): the contaminant is NOT confirmed, so no mask
        # -- the fix must not delete data on a noise fold.
        rng = np.random.default_rng(12)
        t, f, q = _synth_multi(
            3800.0, 1300, [(1.3, 3801.0, 0.01, 0.08)], 0.003, rng)
        t_p, f_p = orc.preprocess_arrays(t, f, q)
        trial = {"recorded": {"period_days": 3.7,
                              "depth_percent": 2.0}}
        p1 = {"period_days": 1.3, "depth_percent": 1.0,
              "status": "survivor"}
        out = p43_run._mask_seed_and_eligibility(
            t_p, f_p, trial, p1, "frozen")
        self.assertEqual(out["seed_source"], "frozen")
        self.assertAlmostEqual(out["seed_period"], 3.7)
        self.assertFalse(out["eligible"])
        self.assertEqual(out["reason"], "frozen-not-confirmed")
        self.assertLess(out["ephemeris"]["depth_est_frac"], 0.01)
        self.assertLess(out["ephemeris"]["snr_est"], 7.0)

    def test_frozen_snr_branch_confident_shallow(self):
        # A shallow (0.5%) contaminant at high fold SNR is
        # confirmed via the SNR branch even though the depth
        # branch does not fire -- mirroring P4-1b section 0.3's
        # "OR survivor" branch.
        rng = np.random.default_rng(13)
        t, f, q = _synth_multi(
            3800.0, 1300, [(3.0, 3801.7, 0.005, 0.12)], 0.002, rng)
        t_p, f_p = orc.preprocess_arrays(t, f, q)
        trial = {"recorded": {"period_days": 3.0,
                              "depth_percent": 0.5}}
        p1 = {"period_days": 3.0, "depth_percent": 0.5,
              "status": "recorded"}
        out = p43_run._mask_seed_and_eligibility(
            t_p, f_p, trial, p1, "frozen")
        self.assertTrue(out["eligible"])
        self.assertEqual(out["reason"], "frozen-contaminant")
        # The depth branch did NOT fire (fold depth < 1%) -- the
        # SNR branch did.
        self.assertLess(out["ephemeris"]["depth_est_frac"], 0.01)
        self.assertGreaterEqual(out["ephemeris"]["snr_est"], 7.0)

    def test_frozen_fallback_without_recorded(self):
        # No recorded period: fall back to the fresh peak (P4-3
        # behavior) and record it -- a missing record must never
        # silently shrink the paired set.
        _t, _f, _q, t_p, f_p = self._sector()
        trial = {}
        p1 = {"period_days": 1.3, "depth_percent": 1.0,
              "status": "survivor"}
        out = p43_run._mask_seed_and_eligibility(
            t_p, f_p, trial, p1, "frozen")
        self.assertEqual(out["seed_source"], "fresh-fallback")
        self.assertEqual(out["seed_fallback_reason"],
                         "no-recorded-period")
        self.assertAlmostEqual(out["seed_period"], 1.3)
        self.assertTrue(out["eligible"])
        self.assertEqual(out["reason"], "confirmed-contaminant")

    def test_frozen_with_no_fresh_peak(self):
        # Frozen mode does not need the fresh peak: with no fresh
        # pass-1 period, the ephemeris is still estimated from the
        # frozen seed (new behavior vs P4-3, where a missing fresh
        # peak meant no mask at all).
        rng = np.random.default_rng(16)
        t, f, q = _synth_multi(
            3800.0, 1300, [(3.0, 3801.7, 0.02, 0.12)], 0.003, rng)
        t_p, f_p = orc.preprocess_arrays(t, f, q)
        trial = {"recorded": {"period_days": 3.0,
                              "depth_percent": 2.0}}
        p1 = {"period_days": None}
        out = p43_run._mask_seed_and_eligibility(
            t_p, f_p, trial, p1, "frozen")
        self.assertEqual(out["seed_source"], "frozen")
        self.assertIsNotNone(out["ephemeris"])
        self.assertAlmostEqual(
            out["ephemeris"]["period_ref_d"], 3.0, delta=0.05)
        self.assertTrue(out["eligible"])

    def test_invalid_seed_mode_raises(self):
        rng = np.random.default_rng(17)
        t, f, q = _synth_multi(3800.0, 1300, [], 0.003, rng)
        t_p, f_p = orc.preprocess_arrays(t, f, q)
        with self.assertRaises(ValueError):
            p43_run._mask_seed_and_eligibility(
                t_p, f_p, {}, {"period_days": 1.0}, "bogus")


class TestFreshPathUnchanged(unittest.TestCase):
    def test_shallow_non_survivor_not_eligible(self):
        rng = np.random.default_rng(14)
        t, f, q = _synth_multi(
            3800.0, 1300, [(3.0, 3801.7, 0.005, 0.12)], 0.003, rng)
        t_p, f_p = orc.preprocess_arrays(t, f, q)
        trial = {"recorded": {"period_days": 3.0,
                              "depth_percent": 0.5}}
        p1 = {"period_days": 3.0, "depth_percent": 0.5,
              "status": "recorded"}
        out = p43_run._mask_seed_and_eligibility(
            t_p, f_p, trial, p1, "fresh")
        self.assertEqual(out["seed_source"], "fresh")
        self.assertFalse(out["eligible"])
        self.assertEqual(out["reason"], "not-confirmed")

    def test_no_pass1_period(self):
        rng = np.random.default_rng(15)
        t, f, q = _synth_multi(3800.0, 1300, [], 0.003, rng)
        t_p, f_p = orc.preprocess_arrays(t, f, q)
        trial = {"recorded": {"period_days": 3.0,
                              "depth_percent": 2.0}}
        p1 = {"period_days": None}
        out = p43_run._mask_seed_and_eligibility(
            t_p, f_p, trial, p1, "fresh")
        self.assertIsNone(out["ephemeris"])
        self.assertFalse(out["eligible"])
        self.assertEqual(out["reason"], "no-pass1-period")


class TestMergePreregRef(unittest.TestCase):
    def _fixture(self, out_dir):
        (out_dir / "hosts").mkdir()
        (out_dir / "hosts-p43").mkdir()
        manifest = {"_sha256": "x",
                    "trials": [
                        {"tic": "1", "sector": 95,
                         "trial_id": "planet01",
                         "group": "lockon_207", "period_d": 12.0,
                         "n_events_expected": 2}]}
        single = {"tic": "1", "sector": 95, "complete": True,
                  "arm": "no-depth-trigger", "trials": [
                      {"tic": "1", "sector": 95,
                       "trial_id": "planet01", "group": "x",
                       "period_d": 12.0, "final_recovered": True,
                       "final_genuine": True, "seconds": 1.0,
                       "k2_recovered": True,
                       "pass1": {"period_days": 12.0},
                       "pass1_repro": {"ok": True}}]}
        stitched = {"tic": "1", "sectors": [95, 96, 97],
                    "complete": True, "arm": "no-depth-trigger",
                    "trials": [
                        {"tic": "1", "sector": 95,
                         "trial_id": "planet01",
                         "final_recovered": True,
                         "final_genuine": True, "seconds": 4.0,
                         "inj_check_ok": True,
                         "sectors": {"95": {"pass1": {
                             "period_days": 12.0}}}}]}
        (out_dir / "hosts" / "1_s0095.json").write_text(
            json.dumps(single))
        (out_dir / "hosts-p43" / "1_p43.json").write_text(
            json.dumps(stitched))
        return manifest

    def test_default_prereg_ref(self):
        with tempfile.TemporaryDirectory() as d:
            out_dir = Path(d)
            manifest = self._fixture(out_dir)
            summary = p43_run.merge_campaign_p43(out_dir, manifest)
            self.assertIn("P43_PREREG.md", summary["note"])

    def test_custom_prereg_ref(self):
        with tempfile.TemporaryDirectory() as d:
            out_dir = Path(d)
            manifest = self._fixture(out_dir)
            summary = p43_run.merge_campaign_p43(
                out_dir, manifest, None,
                "P43B_PREREG.md section 0.7")
            self.assertIn("P43B_PREREG.md", summary["note"])


if __name__ == "__main__":
    unittest.main()
