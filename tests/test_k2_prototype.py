"""K=2 prototype pure-function tests (Phase 4, item 4-1a).

Offline only: all light curves are synthetic box transits + white noise
built in memory. No downloads, no FITS, no BLS search anywhere — the
estimator is fold-based by design, and these tests pin that: the recorded
period is an input, never re-derived by a search.

Covers: fold-based ephemeris estimation (T0/D recovery, local period
refinement, noise-only behaviour), the mask width rule + 1.75x buffer,
the 25% duty-cycle cap, the secondary co-mask triggers, the anti-alias
veto (harmonic + coincident vs disjoint epochs), the secondary phase
scan, and the epoch rule (P4-1a pre-registration: |delta_T0| <= 0.5*D).
"""

import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import bulk_screen as bs  # noqa: E402
from bulk import k2_prototype as k2  # noqa: E402

CADENCE_D = 1.0 / 48.0  # QLP 30-min cadence
SPAN_D = 27.0


def _box_curve(period, t0, duration, depth, noise=0.002, seed=42,
               secondary=None):
    """Synthetic light curve: box transit(s) + white noise.

    secondary: optional (phase, depth) for an EB-like secondary dip.
    Returns (t, f) with t in [0, 27) d and f ~ 1.0 outside transit.
    """
    rng = np.random.default_rng(seed)
    t = np.arange(0.0, SPAN_D, CADENCE_D)
    f = np.ones_like(t)
    phase = ((t - t0) / period + 0.5) % 1.0 - 0.5
    f[np.abs(phase) < duration / (2.0 * period)] -= depth
    if secondary is not None:
        ph2, dep2 = secondary
        t02 = t0 + ph2 * period
        phase2 = ((t - t02) / period + 0.5) % 1.0 - 0.5
        f[np.abs(phase2) < duration / (2.0 * period)] -= dep2
    f += rng.normal(0.0, noise, size=len(t))
    return t, f


def _wrap_delta(t_a, t_b, period):
    d = (t_a - t_b) % period
    if d > period / 2.0:
        d -= period
    return d


class K2Calibration(unittest.TestCase):
    """Base: run under bulk_v4, restore the previous calibration."""

    def setUp(self):
        self._previous = bs.CALIBRATION_VERSION
        bs.set_calibration("bulk_v4")

    def tearDown(self):
        bs.set_calibration(self._previous)


class TestEstimateEphemeris(K2Calibration):
    def test_recovers_known_t0_and_duration(self):
        p, t0, dur, depth = 3.7, 5.2, 0.13, 0.01
        t, f = _box_curve(p, t0, dur, depth)
        est = k2.estimate_ephemeris(t, f, p)
        self.assertLess(abs(_wrap_delta(est["t0_est_btjd"], t0, p)),
                        0.25 * dur)
        self.assertEqual(est["duration_est_d"], dur)
        self.assertGreater(est["snr_est"], 5.0)
        self.assertAlmostEqual(est["depth_est_frac"], depth,
                               delta=0.003)
        self.assertFalse(est["low_snr"])

    def test_local_refinement_improves_off_grid_period(self):
        # A full grid step off at P=13 d smears the fold by ~0.057 d
        # (63% of the 0.09 d duration), so the refinement must engage
        # and land on the true period.
        p_true, t0, dur, depth = 13.0, 5.2, 0.09, 0.015
        df = k2.grid_df()
        p_rec = 1.0 / (1.0 / p_true + 1.0 * df)
        t, f = _box_curve(p_true, t0, dur, depth)
        est = k2.estimate_ephemeris(t, f, p_rec)
        self.assertTrue(est["period_refined"])
        self.assertLess(abs(est["period_ref_d"] - p_true),
                        abs(p_rec - p_true))
        self.assertAlmostEqual(est["period_ref_d"], p_true,
                               delta=0.002)
        self.assertLess(abs(_wrap_delta(est["t0_est_btjd"], t0,
                                        p_true)),
                        0.25 * dur)

    def test_refinement_gate_rejects_negligible_gain(self):
        # Half a grid step off at P=3.7 d smears the fold by only
        # ~0.008 d (6% of the 0.13 d duration): the 10% gate must
        # reject the refinement and keep the recorded period.
        p_true, t0, dur, depth = 3.7, 5.2, 0.13, 0.01
        df = k2.grid_df()
        p_rec = 1.0 / (1.0 / p_true + 0.5 * df)
        t, f = _box_curve(p_true, t0, dur, depth)
        est = k2.estimate_ephemeris(t, f, p_rec)
        self.assertFalse(est["period_refined"])
        self.assertEqual(est["period_ref_d"], p_rec)

    def test_noise_only_returns_low_snr_without_crashing(self):
        rng = np.random.default_rng(7)
        t = np.arange(0.0, SPAN_D, CADENCE_D)
        f = 1.0 + rng.normal(0.0, 0.002, size=len(t))
        est = k2.estimate_ephemeris(t, f, 3.7)
        self.assertTrue(np.isfinite(est["t0_est_btjd"]))
        self.assertTrue(np.isfinite(est["snr_est"]))
        self.assertLess(est["depth_est_frac"], 0.01)

    def test_t0_anchored_near_sector_midpoint(self):
        # The estimated T0 is the transit centre nearest the sector
        # midpoint (t_mid = 13.5 d here), not the data start.
        p, t0, dur, depth = 3.7, 5.2, 0.13, 0.01
        t, f = _box_curve(p, t0, dur, depth)
        est = k2.estimate_ephemeris(t, f, p)
        self.assertLess(abs(est["t0_est_btjd"] - 13.5), p / 2.0)


class TestScanSecondary(K2Calibration):
    def test_finds_eb_secondary_at_phase_half(self):
        p, t0, dur = 3.7, 5.2, 0.13
        t, f = _box_curve(p, t0, dur, 0.02,
                          secondary=(0.5, 0.008))
        phase, depth, snr = k2.scan_secondary(t, f, p, t0, dur)
        self.assertAlmostEqual(phase, 0.5, delta=0.02)
        self.assertAlmostEqual(depth, 0.008, delta=0.003)
        self.assertGreater(snr, 3.0)

    def test_no_secondary_gives_low_snr(self):
        p, t0, dur = 3.7, 5.2, 0.13
        t, f = _box_curve(p, t0, dur, 0.01)
        _, _, snr = k2.scan_secondary(t, f, p, t0, dur)
        self.assertLess(snr, 3.0)


class TestBuildMask(K2Calibration):
    def _ephemeris(self, period, t0, duration):
        return {"period_ref_d": period, "t0_est_btjd": t0,
                "duration_est_d": duration}

    def _arrays(self):
        t = np.arange(0.0, SPAN_D, CADENCE_D)
        f = np.ones_like(t)
        q = np.zeros(len(t), dtype=np.int32)
        return t, f, q

    def test_width_rule_depth_dominated(self):
        # P=5, D=0.13: drift=0.022, max(1.25*0.13, 0.13+2*0.022)=0.174.
        t, f, q = self._arrays()
        ep = self._ephemeris(5.0, 13.0, 0.13)
        _, stats = k2.build_k2_mask(t, f, q, ep, 0.3)
        self.assertFalse(stats["stopped"])
        self.assertFalse(stats["buffer_applied"])
        self.assertAlmostEqual(stats["mask_width_d"], 0.174,
                               delta=0.002)

    def test_width_rule_drift_dominated(self):
        # P=13, D=0.04: drift=0.057, max(0.05, 0.04+2*0.057)=0.154.
        t, f, q = self._arrays()
        ep = self._ephemeris(13.0, 13.0, 0.04)
        _, stats = k2.build_k2_mask(t, f, q, ep, 0.3)
        self.assertFalse(stats["stopped"])
        self.assertAlmostEqual(stats["mask_width_d"], 0.154,
                               delta=0.002)

    def test_buffer_applies_above_half_percent(self):
        t, f, q = self._arrays()
        ep = self._ephemeris(5.0, 13.0, 0.13)
        _, plain = k2.build_k2_mask(t, f, q, ep, 0.3)
        _, buffered = k2.build_k2_mask(t, f, q, ep, 0.6)
        self.assertTrue(buffered["buffer_applied"])
        self.assertAlmostEqual(buffered["mask_width_d"],
                               1.75 * plain["mask_width_d"],
                               delta=1e-9)

    def test_duty_cycle_cap_stops(self):
        # P=0.6, D=0.25: width 0.3125 d -> ~52% duty -> STOPPED.
        t, f, q = self._arrays()
        ep = self._ephemeris(0.6, 13.0, 0.25)
        keep, stats = k2.build_k2_mask(t, f, q, ep, 0.3)
        self.assertTrue(stats["stopped"])
        self.assertEqual(stats["stop_reason"],
                         "STOPPED_MASK_DUTY_CYCLE")
        self.assertGreater(stats["duty_cycle"], 0.25)
        self.assertTrue(keep.all())

    def test_comask_trigger_secondary_snr(self):
        t, f, q = self._arrays()
        ep = self._ephemeris(5.0, 13.0, 0.13)
        _, stats = k2.build_k2_mask(t, f, q, ep, 0.3,
                                    secondary=(0.5, 0.01, 4.0))
        self.assertTrue(stats["secondary_comasked"])
        self.assertEqual(stats["comask_trigger"],
                         "secondary_snr_gte_3")
        self.assertGreater(stats["n_comask_centres"], 0)

    def test_comask_trigger_depth(self):
        # Deep primary triggers the co-mask even with a weak secondary.
        t, f, q = self._arrays()
        ep = self._ephemeris(5.0, 13.0, 0.13)
        _, stats = k2.build_k2_mask(t, f, q, ep, 1.5,
                                    secondary=(0.5, 0.001, 1.0))
        self.assertTrue(stats["secondary_comasked"])
        self.assertEqual(stats["comask_trigger"], "depth_gt_1pct")

    def test_no_comask_without_trigger(self):
        t, f, q = self._arrays()
        ep = self._ephemeris(5.0, 13.0, 0.13)
        _, stats = k2.build_k2_mask(t, f, q, ep, 0.3,
                                    secondary=(0.5, 0.001, 1.0))
        self.assertFalse(stats["secondary_comasked"])
        self.assertEqual(stats["n_comask_centres"], 0)


class TestAliasVeto(K2Calibration):
    def test_harmonic_coincident_vetoed(self):
        v = k2.alias_veto(10.0, 100.0, 5.0, 100.0, 0.1)
        self.assertTrue(v["is_alias"])
        self.assertEqual((v["harmonic_m"], v["harmonic_n"]), (2, 1))
        self.assertTrue(v["coincident"])
        self.assertTrue(v["vetoed"])

    def test_harmonic_disjoint_kept(self):
        # Same 2:1 harmonic, but the pass-2 epochs sit at phase 0.5
        # of the masked period — a true MMR, not leakage.
        v = k2.alias_veto(10.0, 102.5, 5.0, 100.0, 0.1)
        self.assertTrue(v["is_alias"])
        self.assertFalse(v["coincident"])
        self.assertFalse(v["vetoed"])

    def test_non_harmonic_kept(self):
        v = k2.alias_veto(7.3, 100.0, 5.0, 100.0, 0.1)
        self.assertFalse(v["is_alias"])
        self.assertFalse(v["vetoed"])

    def test_coincident_with_comasked_secondary_vetoed(self):
        v = k2.alias_veto(5.0, 102.5, 5.0, 100.0, 0.1,
                          comask_phase=0.5)
        self.assertTrue(v["is_alias"])
        self.assertTrue(v["coincident"])
        self.assertTrue(v["vetoed"])

    def test_null_epoch_cannot_veto(self):
        v = k2.alias_veto(10.0, None, 5.0, 100.0, 0.1)
        self.assertTrue(v["is_alias"])
        self.assertFalse(v["vetoed"])

    def test_subharmonic_vetoed(self):
        # P2 = P1/2 is a 1:2 harmonic.
        v = k2.alias_veto(2.5, 100.0, 5.0, 100.0, 0.1)
        self.assertTrue(v["is_alias"])
        self.assertEqual((v["harmonic_m"], v["harmonic_n"]), (1, 2))
        self.assertTrue(v["vetoed"])


class TestEpochRule(K2Calibration):
    def test_delta_wraps_to_half_period(self):
        self.assertAlmostEqual(k2.epoch_delta(100.0 + 5.0 - 0.01,
                                              100.0, 5.0), -0.01,
                               delta=1e-9)
        self.assertAlmostEqual(k2.epoch_delta(100.0 + 2.51,
                                              100.0, 5.0), -2.49,
                               delta=1e-9)

    def test_match_within_half_duration(self):
        self.assertTrue(k2.epoch_match(0.4 * 0.13, 0.13))
        self.assertTrue(k2.epoch_match(0.5 * 0.13, 0.13))
        self.assertFalse(k2.epoch_match(0.6 * 0.13, 0.13))
        self.assertFalse(k2.epoch_match(-0.6 * 0.13, 0.13))

    def test_missing_epoch_fails(self):
        self.assertIsNone(k2.epoch_delta(None, 100.0, 5.0))
        self.assertFalse(k2.epoch_match(None, 0.13))


if __name__ == "__main__":
    unittest.main()
