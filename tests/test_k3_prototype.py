"""K=3 prototype pure-function tests (Phase 4, item 4-1b).

Offline only: all light curves are synthetic box transits + white noise
built in memory. No downloads, no FITS, no BLS search anywhere.

Covers: the stitch (single-sector identity, two-sector concat +
time-sort), the artifact keep-mask (against oracle_run's
apply_artifact_mask), the union duty-cycle + cap, the pass-3
eligibility rule ("confirmed contaminant", pre-registered), the
combined pass-3 alias veto, the trial cap rule (primary 25%,
cap-aware 25%/75% at P=5 d), and the build_k2_mask parameter
extension (P4-1b: duty_cap + depth_trigger — defaults preserve
P4-1a behaviour exactly). The epoch rule is NOT redefined here:
it is k2's (|delta_T0| <= 0.5*D_inj), asserted as such.
"""

import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import bulk_screen as bs  # noqa: E402
from bulk import k2_prototype as k2  # noqa: E402
from bulk import k3_prototype as k3  # noqa: E402
from bulk import oracle_run as orc  # noqa: E402

CADENCE_D = 1.0 / 48.0  # QLP 30-min cadence
SPAN_D = 27.0


def _box_curve(period, t0, duration, depth, noise=0.002, seed=42,
               secondary=None):
    """Synthetic light curve: box transit(s) + white noise."""
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


def _ephemeris_for(period, t0, duration, depth):
    """Fold-estimated ephemeris for a synthetic curve (as the driver
    builds it)."""
    t, f = _box_curve(period, t0, duration, depth)
    t_p, f_p = orc.preprocess_arrays(
        t, f, np.zeros(len(t), dtype=int))
    return k2.estimate_ephemeris(t_p, f_p, period), t, f


class K3Calibration(unittest.TestCase):
    """Base: run under bulk_v4, restore the previous calibration."""

    def setUp(self):
        self._previous = bs.CALIBRATION_VERSION
        bs.set_calibration("bulk_v4")

    def tearDown(self):
        bs.set_calibration(self._previous)


class TestStitch(K3Calibration):
    def test_single_sector_is_identity(self):
        t = np.arange(0.0, 10.0, CADENCE_D)
        f = np.ones_like(t)
        q = np.zeros(len(t), dtype=int)
        t_s, f_s, q_s = k3.stitch_sectors([(t, f, q)])
        np.testing.assert_array_equal(t_s, t)
        np.testing.assert_array_equal(f_s, f)
        np.testing.assert_array_equal(q_s, q)

    def test_two_sectors_concatenate_and_time_sort(self):
        t1 = np.arange(0.0, 13.5, CADENCE_D)
        t2 = np.arange(13.5, 27.0, CADENCE_D)
        f1 = np.ones_like(t1)
        f2 = np.ones_like(t2) * 2.0
        q = np.zeros(len(t1), dtype=int)
        # Pass them out of order: the stitch must sort by time.
        t_s, f_s, q_s = k3.stitch_sectors(
            [(t2, f2, q), (t1, f1, q)])
        self.assertEqual(len(t_s), len(t1) + len(t2))
        self.assertTrue(np.all(np.diff(t_s) > 0))
        self.assertEqual(f_s[0], 1.0)
        self.assertEqual(f_s[-1], 2.0)

    def test_empty_input_returns_empty_arrays(self):
        t_s, f_s, q_s = k3.stitch_sectors([])
        self.assertEqual(len(t_s), 0)
        self.assertEqual(len(f_s), 0)
        self.assertEqual(len(q_s), 0)


class TestArtifactMask(K3Calibration):
    def test_keep_mask_matches_apply_artifact_mask(self):
        t = np.arange(0.0, SPAN_D, CADENCE_D)
        f = np.ones_like(t)
        q = np.zeros(len(t), dtype=int)
        spans = [[5.0, 5.5], [10.0, 10.2], [20.0, 20.05]]
        keep = k3.artifact_keep_mask(t, spans)
        t2, _f2, _q2, stats = orc.apply_artifact_mask(t, f, q, spans)
        self.assertEqual(len(t2), int(keep.sum()))
        self.assertEqual(stats["n_cadences_dropped"],
                         int((~keep).sum()))
        self.assertEqual(stats["n_spans"], 3)

    def test_empty_spans_keep_everything(self):
        t = np.arange(0.0, SPAN_D, CADENCE_D)
        keep = k3.artifact_keep_mask(t, [])
        self.assertTrue(np.all(keep))


class TestUnionCap(K3Calibration):
    def _valid_arrays(self, n=1296, n_invalid=0):
        t = np.arange(0.0, n * CADENCE_D, CADENCE_D)
        f = np.ones(n)
        q = np.zeros(n, dtype=int)
        if n_invalid:
            q[:n_invalid] = 1  # fails the quality mask
        return t, f, q

    def test_combined_duty_cycle_on_valid_cadences(self):
        t, f, q = self._valid_arrays()
        keep = np.ones(len(t), dtype=bool)
        keep[:324] = False  # exactly 25% of 1296
        self.assertAlmostEqual(
            k3.combined_duty_cycle(t, f, q, keep), 0.25, places=6)

    def test_combined_duty_cycle_excludes_invalid_cadences(self):
        t, f, q = self._valid_arrays(n_invalid=96)
        keep = np.ones(len(t), dtype=bool)
        keep[96:396] = False  # 300 of 1200 valid = 25%
        self.assertAlmostEqual(
            k3.combined_duty_cycle(t, f, q, keep), 0.25, places=6)

    def test_union_under_cap_keeps_union(self):
        t, f, q = self._valid_arrays()
        ka = np.ones(len(t), dtype=bool)
        ka[:130] = False  # ~10%
        kb = np.ones(len(t), dtype=bool)
        kb[130:260] = False  # ~10%, disjoint
        keep_u, duty, stopped = k3.apply_union_cap(t, f, q, ka, kb,
                                                   0.25)
        self.assertFalse(stopped)
        self.assertAlmostEqual(duty, 260 / 1296, places=6)
        self.assertFalse(keep_u[0])
        self.assertFalse(keep_u[200])
        self.assertTrue(keep_u[300])

    def test_union_over_cap_stops_and_keeps_everything(self):
        t, f, q = self._valid_arrays()
        ka = np.ones(len(t), dtype=bool)
        ka[:260] = False  # 20%
        kb = np.ones(len(t), dtype=bool)
        kb[260:520] = False  # 20%, disjoint -> union 40%
        keep_u, duty, stopped = k3.apply_union_cap(t, f, q, ka, kb,
                                                   0.25)
        self.assertTrue(stopped)
        self.assertAlmostEqual(duty, 520 / 1296, places=6)
        self.assertTrue(np.all(keep_u))


class TestPass3Eligible(K3Calibration):
    def _p2(self, status="recorded", period=3.7, depth=0.3):
        return {"status": status, "period_days": period,
                "depth_percent": depth}

    def test_rescued_trial_is_not_eligible(self):
        elig, reason = k3.pass3_eligible(
            self._p2(status="survivor", depth=2.0),
            {"vetoed": False}, True)
        self.assertFalse(elig)
        self.assertEqual(reason, "pass2-rescued")

    def test_no_period_is_not_eligible(self):
        elig, reason = k3.pass3_eligible(
            {"status": "recorded", "period_days": None,
             "depth_percent": 2.0},
            {"vetoed": False}, False)
        self.assertFalse(elig)
        self.assertEqual(reason, "no-pass2-period")

    def test_alias_leakage_is_not_eligible(self):
        elig, reason = k3.pass3_eligible(
            self._p2(status="survivor", depth=2.0),
            {"vetoed": True}, False)
        self.assertFalse(elig)
        self.assertEqual(reason, "alias-leakage")

    def test_survivor_is_eligible(self):
        elig, reason = k3.pass3_eligible(
            self._p2(status="survivor", depth=0.2),
            {"vetoed": False}, False)
        self.assertTrue(elig)
        self.assertEqual(reason, "eligible-survivor")

    def test_deep_recorded_is_eligible(self):
        elig, reason = k3.pass3_eligible(
            self._p2(status="recorded", depth=2.0),
            {"vetoed": False}, False)
        self.assertTrue(elig)
        self.assertEqual(reason, "eligible-depth-gt-1pct")

    def test_shallow_recorded_is_not_eligible(self):
        elig, reason = k3.pass3_eligible(
            self._p2(status="recorded", depth=0.3),
            {"vetoed": False}, False)
        self.assertFalse(elig)
        self.assertEqual(reason, "not-confirmed-contaminant")

    def test_missing_depth_is_not_eligible(self):
        elig, reason = k3.pass3_eligible(
            self._p2(status="recorded", depth=None),
            {"vetoed": False}, False)
        self.assertFalse(elig)
        self.assertEqual(reason, "not-confirmed-contaminant")


class TestPass3Veto(K3Calibration):
    def _contaminant(self, period=3.0, t0=5.0, half=0.1):
        return {"period_d": period, "t0_btjd": t0,
                "mask_half_width_d": half, "comask_phase": None}

    def test_vetoed_when_any_contaminant_fires(self):
        out = k3.pass3_veto(
            6.0, 5.0, [self._contaminant(), self._contaminant(
                period=7.0, t0=2.0)])
        self.assertTrue(out["vetoed"])
        self.assertTrue(out["per_contaminant"][0]["vetoed"])
        self.assertFalse(out["per_contaminant"][1]["vetoed"])

    def test_not_vetoed_when_epochs_are_disjoint(self):
        # 6.0 d is the 2/1 harmonic of 3.0 d, but the epochs are a
        # full half-period apart: the MMR exception keeps it.
        out = k3.pass3_veto(
            6.0, 6.5, [self._contaminant()])
        self.assertFalse(out["vetoed"])

    def test_not_vetoed_for_unrelated_period(self):
        out = k3.pass3_veto(7.3, 5.0, [self._contaminant()])
        self.assertFalse(out["vetoed"])


class TestTrialCap(K3Calibration):
    def test_primary_cap_is_25pct_for_all_periods(self):
        for arm in ("prototype", "combined", "no-depth-trigger"):
            self.assertEqual(k3.trial_cap(arm, 0.5), 0.25)
            self.assertEqual(k3.trial_cap(arm, 10.0), 0.25)

    def test_cap_aware_short_period_is_75pct(self):
        self.assertEqual(k3.trial_cap("cap-aware", 0.525), 0.75)
        self.assertEqual(k3.trial_cap("cap-aware", 4.99), 0.75)

    def test_cap_aware_long_period_is_25pct(self):
        self.assertEqual(k3.trial_cap("cap-aware", 5.0), 0.25)
        self.assertEqual(k3.trial_cap("cap-aware", 10.0), 0.25)

    def test_secondary_queue_cap_is_one(self):
        self.assertEqual(k3.SECONDARY_QUEUE_CAP, 1)


class TestBuildK2MaskParams(K3Calibration):
    def test_default_cap_preserves_p41a_behaviour(self):
        # Short-period deep contaminant: raw duty must land in
        # (0.25, 0.75) so the default cap stops it and the 75% cap
        # does not. The range is asserted first: if the synthetic
        # setup ever stops producing it, this fails loudly instead
        # of silently testing nothing.
        eph, t, f = _ephemeris_for(0.8, 5.2, 0.13, 0.02)
        q = np.zeros(len(t), dtype=int)
        _keep, raw = k2.build_k2_mask(
            t, f, q, eph, 2.0, secondary=(0.5, 0.01, 1.0),
            duty_cap=1.0)
        self.assertGreater(raw["duty_cycle"], 0.25)
        self.assertLess(raw["duty_cycle"], 0.75)
        keep_d, stats_d = k2.build_k2_mask(
            t, f, q, eph, 2.0, secondary=(0.5, 0.01, 1.0))
        self.assertTrue(stats_d["stopped"])
        self.assertEqual(stats_d["stop_reason"],
                         "STOPPED_MASK_DUTY_CYCLE")
        self.assertTrue(np.all(keep_d))
        keep_75, stats_75 = k2.build_k2_mask(
            t, f, q, eph, 2.0, secondary=(0.5, 0.01, 1.0),
            duty_cap=0.75)
        self.assertFalse(stats_75["stopped"])
        self.assertFalse(np.all(keep_75))
        self.assertEqual(stats_75["duty_cap"], 0.75)

    def test_depth_trigger_false_disables_depth_comask(self):
        # Deep recorded depth (2%) + a weak secondary (SNR 1.0):
        # the depth trigger fires by default; with depth_trigger
        # False the co-mask must not fire (SNR < 3.0).
        eph, t, f = _ephemeris_for(3.7, 5.2, 0.13, 0.02)
        q = np.zeros(len(t), dtype=int)
        _k, s_on = k2.build_k2_mask(
            t, f, q, eph, 2.0, secondary=(0.5, 0.01, 1.0))
        self.assertTrue(s_on["secondary_comasked"])
        self.assertEqual(s_on["comask_trigger"], "depth_gt_1pct")
        _k, s_off = k2.build_k2_mask(
            t, f, q, eph, 2.0, secondary=(0.5, 0.01, 1.0),
            depth_trigger=False)
        self.assertFalse(s_off["secondary_comasked"])
        self.assertIsNone(s_off["comask_trigger"])
        self.assertFalse(s_off["depth_trigger"])

    def test_snr_trigger_still_fires_without_depth_trigger(self):
        # Strong secondary (SNR 5.0) with a shallow recorded depth
        # (0.3%): the SNR trigger fires either way.
        eph, t, f = _ephemeris_for(3.7, 5.2, 0.13, 0.005)
        q = np.zeros(len(t), dtype=int)
        _k, s_off = k2.build_k2_mask(
            t, f, q, eph, 0.3, secondary=(0.5, 0.01, 5.0),
            depth_trigger=False)
        self.assertTrue(s_off["secondary_comasked"])
        self.assertEqual(s_off["comask_trigger"],
                         "secondary_snr_gte_3")


class TestEpochRuleReused(K3Calibration):
    def test_epoch_rule_is_k2s_not_redefined(self):
        # P4-1b reuses P4-1a's pre-registered epoch rule; k3 must
        # not define its own tolerance.
        self.assertEqual(k2.EPOCH_TOL_DUR_FRAC, 0.5)
        self.assertFalse(hasattr(k3, "EPOCH_TOL_DUR_FRAC"))
        self.assertTrue(k2.epoch_match(0.04, 0.13))
        self.assertFalse(k2.epoch_match(0.10, 0.13))
        self.assertFalse(k2.epoch_match(None, 0.13))


if __name__ == "__main__":
    unittest.main()
