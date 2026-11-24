"""Phase 5.7 two-pass transit-masked detrending tests (DESIGN_5_7.md
Rev 1, vote V57-20261124).

- D10 flag-off regression: pinned flag-off records byte-identical;
  default == explicit v6; no detrend keys flag-off.
- R6 extended no-sag: flat + curved baselines; gaps, edges,
  durations, repeated masks; the masked trend in-transit stays
  within 0.1x depth of the true trend, with a negative control
  showing the unmasked trend sags past it.
- R7 deterministic mask coverage: four-sector synthetic curves;
  refined-ephemeris errors at the refinement-grid edges; epoch
  offsets; ingress/egress; gaps; sector boundaries; every true
  transit cadence masked -- including a control showing the
  UNREFINED coarse mask FAILS to cover (proving D3's necessity).
- CDPP: the frozen §3 measure_cdpp (white-noise value, constant
  curve, <5 segments, 50% trailing rule, paired boundary identity,
  gap splitting) + the Mac-only baseline reproduction test.
- D6 raw-flux gate: unit-level pass/fail, the threshold pinned
  equal to hunter._PASS2_GATE_MIN_SIGNIF, function agreement with
  hunter._raw_fold_depth, and a screen-level veto.
- D4 mask guard + D8 fallback (pass 1 stands in both cases).
- Adoption invariant: the record headline matches the adopted pass.
- Preprocessing: preprocess_arrays / preprocess_sector under v7,
  _subset detrend keys, screen_job 6-tuple, driver threading,
  joint_fit.period_in_top15 (B1).

Calibration: bulk_v6 throughout (setUp/tearDown restores the
previous profile).
"""

import json
import math
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import bulk_screen as bs  # noqa: E402
from bulk import cdpp_repro_57 as repro  # noqa: E402
from bulk import detrend as dt  # noqa: E402
from bulk import joint_fit as jf  # noqa: E402
from bulk import k3_run as k3run  # noqa: E402
from bulk import oracle_run as orc  # noqa: E402
from bulk import p43_run as p43run  # noqa: E402
from bulk import p43_stitch as p43  # noqa: E402
from synth_fits import make_qlp_fits, screen_job  # noqa: E402

PINS_PATH = (Path(__file__).resolve().parent / "fixtures"
             / "detrend57_flagoff_pins.json")

# The 4.1-10 manifest (frozen, sha 2876b703...) on the VM; the
# Mac run sets EXHUNT_CDPP_REPRO_MANIFEST to its copy.
DEFAULT_MANIFEST = (Path.home() / "workspace" / "goals"
                    / "exoplanet-hunter" / "hidden_files"
                    / "science-vet" / "phase41-vote"
                    / "p4110_manifest.json")


class _BulkV6Case(unittest.TestCase):
    def setUp(self):
        bs.set_calibration("bulk_v6")

    def tearDown(self):
        bs.set_calibration("bulk_v1")


def _hunter():
    """hunter.py, lazily (it imports lightkurve: ~12 s). Cached."""
    if not hasattr(_hunter, "mod"):
        import hunter  # noqa: PLC0415
        _hunter.mod = hunter
    return _hunter.mod


def _four_sector_times(cadence_min=2.0):
    """4 sectors x 27.4 d with 1.4 d downlink gaps (the p6p9 toy's
    time structure at 2-min cadence). The fine cadence matters:
    at 30-min cadence no cadence falls in the ~0.005 d sliver the
    coarse mask misses, and the D3 control would be vacuous.
    Returns t (sorted)."""
    t = np.concatenate(
        [np.arange(0, 27.4, cadence_min / 1440.0) + s * 27.4
         for s in range(4)])
    return t[(t % 27.4) < 26.0]


def _bls_periodogram(t, f):
    """A real BLS periodogram dict (the A8 helper's shape) for
    period_in_top15 tests."""
    from astropy.timeseries import BoxLeastSquares
    bs.set_calibration("bulk_v6")
    periods = 1.0 / np.linspace(1.0 / bs.MAX_PERIOD_D,
                                1.0 / bs.MIN_PERIOD_D,
                                bs.BLS_GRID_POINTS)
    bls = BoxLeastSquares(np.asarray(t, dtype=float),
                          np.asarray(f, dtype=float))
    res = bls.power(periods, list(bs.BLS_DURATIONS_D))
    pv = np.asarray(res.period, dtype=float)
    pw = np.asarray(res.power, dtype=float)
    med, scale = bs._robust_sde(pw, pv)
    return {"periods": pv, "powers": pw,
            "depths": np.asarray(res.depth, dtype=float),
            "durations": np.asarray(res.duration, dtype=float),
            "transit_times": np.asarray(res.transit_time,
                                        dtype=float),
            "med": med, "scale": scale}


class TestDetrendModule(unittest.TestCase):
    """Pure-function sanity for bulk/detrend.py."""

    def test_window_points(self):
        # 30-min cadence, 1.0 d window -> 48 pts -> forced odd 49.
        self.assertEqual(dt.window_points(0.5 / 24.0, 1.0, 1296), 49)
        # 2-min cadence, 1.0 d window -> 720 pts -> 721.
        self.assertEqual(dt.window_points(2.0 / 1440.0, 1.0, 20000),
                         721)
        # Too few points for any valid window.
        self.assertIsNone(dt.window_points(0.5 / 24.0, 1.0, 20))

    def test_segments_split_at_gaps(self):
        t = np.array([0.0, 0.02, 0.04, 5.0, 5.02, 5.04])
        self.assertEqual(dt.segments_from_times(t),
                         [(0, 3), (3, 6)])
        self.assertEqual(dt.segments_from_times(np.array([])), [])

    def test_masked_trend_equals_unmasked_with_empty_mask(self):
        rng = np.random.default_rng(0)
        t = np.arange(500) * 0.02
        f = 1.0 + rng.normal(0, 0.001, 500)
        mask = np.zeros(500, dtype=bool)
        np.testing.assert_allclose(
            dt.masked_savgol_trend(t, f, mask, 1.0),
            dt.savgol_trend(t, f, 1.0))

    def test_masked_trend_all_masked_raises(self):
        t = np.arange(500) * 0.02
        f = np.ones(500)
        with self.assertRaises(ValueError):
            dt.masked_savgol_trend(t, f, np.ones(500, dtype=bool),
                                   1.0)

    def test_transit_mask_geometry(self):
        # P=3 d, T0=5.0, D=0.1 d: cadences at the centre and at
        # +/-D/2 are masked; D/2 + pad is the boundary. (5.07 is
        # NOT used: 5.07-5.0 in float64 is 0.07000000000000006,
        # a hair past the 0.07 boundary -- the mask is right, the
        # test value would be a float artefact.)
        t = np.array([5.0, 5.05, 5.06, 5.065, 5.08, 8.0, 4.95])
        m = dt.transit_mask(t, 3.0, 5.0, 0.1)
        # |dt| <= 0.05 + 0.02 = 0.07: 5.0, 5.05, 5.06, 5.065
        # masked; 5.08 (0.08) not; 8.0 is the next transit centre;
        # 4.95 is 0.05 before the centre.
        np.testing.assert_array_equal(
            m, [True, True, True, True, False, True, True])

    def test_folded_time_offset_wraps(self):
        off = dt.folded_time_offset(np.array([4.9, 5.0, 6.4, 6.6]),
                                    3.0, 5.0)
        np.testing.assert_allclose(off, [-0.1, 0.0, 1.4, -1.4])


class TestNoSag(_BulkV6Case):
    """R6: the masked trend does not sag into the transit.

    Noiseless curves: the sag is a deterministic bias, and the
    trend estimate's own noise (white noise through SavGol) would
    swamp the 0.1x-depth bar at realistic noise levels -- the
    noisy comparison is a separate test below.
    """

    def _curve(self, baseline, period=0.8, t0=1502.0, depth=0.0005,
               duration=0.09, t_start=1500.0, n=1296):
        t = t_start + np.arange(n) * 0.5 / 24.0
        trend = baseline(t)
        ph = ((t - t0 + 0.5 * period) % period) - 0.5 * period
        in_tr = np.abs(ph) < duration / 2.0
        f = np.where(in_tr, trend - depth, trend)
        return t, f, trend, in_tr

    @staticmethod
    def _flat(t):
        return np.ones_like(t)

    @staticmethod
    def _curved(t):
        # 0.5% sinusoid (7 d) + 1% linear ramp over 27 d.
        return (1.0 + 0.005 * np.sin(2 * np.pi * (t - 1500.0) / 7.0)
                + 0.01 * (t - 1500.0) / 27.0)

    def test_masked_trend_within_tenth_depth(self):
        # Flat + curved baselines; durations 0.04/0.09/0.25 d;
        # P=0.8 d gives ~33 repeated transits (repeated masks).
        for label, base in (("flat", self._flat),
                            ("curved", self._curved)):
            for duration in (0.04, 0.09, 0.25):
                t, f, trend, in_tr = self._curve(
                    base, duration=duration)
                mask = dt.transit_mask(t, 0.8, 1502.0, duration)
                tr = dt.masked_savgol_trend(t, f, mask, 1.0)
                dev = float(np.max(np.abs(tr[in_tr]
                                           - trend[in_tr])))
                self.assertLess(dev, 0.1 * 0.0005,
                                f"{label} D={duration}: "
                                f"dev {dev:.2e}")

    def test_masked_trend_with_gap_and_edge_transit(self):
        # A 1.5 d gap mid-curve + a transit centred 0.15 d after
        # the first cadence (edge mask: np.interp end behaviour).
        t = 1500.0 + np.arange(1296) * 0.5 / 24.0
        keep = ~((t > 1510.0) & (t < 1511.5))
        t = t[keep]
        trend = self._curved(t)
        ph = ((t - 1500.15 + 0.5 * 0.8) % 0.8) - 0.5 * 0.8
        in_tr = np.abs(ph) < 0.09 / 2.0
        f = np.where(in_tr, trend - 0.0005, trend)
        mask = dt.transit_mask(t, 0.8, 1500.15, 0.09)
        tr = dt.masked_savgol_trend(t, f, mask, 1.0)
        dev = float(np.max(np.abs(tr[in_tr] - trend[in_tr])))
        self.assertLess(dev, 0.1 * 0.0005, f"dev {dev:.2e}")

    def test_unmasked_trend_sags_negative_control(self):
        # The control that proves the test discriminates: the
        # UNMASKED trend sags past 0.1x depth at D=0.25 d (measured
        # ~0.83x) and at D=0.09 d (~0.23x). At D=0.04 d the sag is
        # ~0.09x -- below the bar, so it is NOT a control there.
        for duration, floor in ((0.25, 0.5), (0.09, 0.15)):
            t, f, trend, in_tr = self._curve(
                self._curved, duration=duration)
            tr = dt.savgol_trend(t, f, 1.0)
            dev = float(np.max(np.abs(tr[in_tr] - trend[in_tr])))
            self.assertGreater(dev, floor * 0.0005,
                               f"D={duration}: dev {dev:.2e}")

    def test_masked_beats_unmasked_with_noise(self):
        # With realistic white noise the absolute bar is swamped
        # by the trend estimate's own noise, but the masked trend
        # must still be CLOSER to the truth than the unmasked one
        # (the sag is a bias on top of the noise).
        rng = np.random.default_rng(0)
        t, f, trend, in_tr = self._curve(self._curved,
                                         duration=0.25)
        f = f + rng.normal(0, 0.0001, len(t))
        mask = dt.transit_mask(t, 0.8, 1502.0, 0.25)
        dev_m = float(np.mean(np.abs(
            dt.masked_savgol_trend(t, f, mask, 1.0)[in_tr]
            - trend[in_tr])))
        dev_u = float(np.mean(np.abs(
            dt.savgol_trend(t, f, 1.0)[in_tr] - trend[in_tr])))
        self.assertLess(dev_m, dev_u)


class TestMaskCoverage(unittest.TestCase):
    """R7: the D-mask covers every true transit cadence.

    Deterministic geometry (no noise, no BLS): the mask is built
    from a refined ephemeris with errors at the refinement grid's
    edges, and must still cover all true in-transit cadences on a
    four-sector curve with downlink gaps.
    """

    P_TRUE, T0_TRUE, D_TRUE = 3.0, 5.0, 0.1

    def _true_in_transit(self, t):
        ph = ((t - self.T0_TRUE + 0.5 * self.P_TRUE)
              % self.P_TRUE) - 0.5 * self.P_TRUE
        return np.abs(ph) <= self.D_TRUE / 2.0

    def test_refined_mask_covers_all_transits(self):
        t = _four_sector_times()
        in_tr = self._true_in_transit(t)
        self.assertGreater(in_tr.sum(), 100)  # sane fixture
        # Refinement grid: +-1.5% over 800 points -> step
        # 0.03*P/800; worst refined error is half a step.
        step = 0.03 * self.P_TRUE / 800.0
        for dp in (-step, -step / 2.0, 0.0, step / 2.0, step):
            for dt0 in (-0.01, 0.0, 0.01):
                mask = dt.transit_mask(t, self.P_TRUE + dp,
                                       self.T0_TRUE + dt0,
                                       self.D_TRUE)
                missed = int((in_tr & ~mask).sum())
                self.assertEqual(
                    missed, 0, f"dP={dp:.2e} dT0={dt0}: "
                    f"{missed} true in-transit cadences unmasked")

    def test_refined_mask_covers_ingress_egress(self):
        # Cadences exactly at the transit edges (|dt| == D/2) are
        # covered even with a half-step period error.
        t = _four_sector_times()
        step = 0.03 * self.P_TRUE / 800.0
        ph = ((t - self.T0_TRUE + 0.5 * self.P_TRUE)
              % self.P_TRUE) - 0.5 * self.P_TRUE
        edge = np.abs(np.abs(ph) - self.D_TRUE / 2.0) < 0.005
        self.assertGreater(edge.sum(), 0)
        mask = dt.transit_mask(t, self.P_TRUE + step / 2.0,
                               self.T0_TRUE, self.D_TRUE)
        self.assertEqual(int((edge & ~mask).sum()), 0)

    def test_coarse_mask_fails_without_refinement(self):
        # The control proving D3's necessity: the mask built from
        # the UNREFINED coarse-grid ephemeris MISSES true transit
        # cadences at the far end of a 4-sector baseline. The
        # coarse grid is uniform in frequency (12000 points over
        # [0.5, 20] d); its half-step at P=3 d is ~0.00073 d, and
        # ~36 cycles of drift (~0.027 d) exceed the 0.02 d pad.
        t = _four_sector_times()
        in_tr = self._true_in_transit(t)
        df = (1.0 / 0.5 - 1.0 / 20.0) / (12000 - 1)
        d_p = self.P_TRUE ** 2 * df / 2.0
        mask = dt.transit_mask(t, self.P_TRUE + d_p,
                               self.T0_TRUE, self.D_TRUE)
        missed = int((in_tr & ~mask).sum())
        self.assertGreater(missed, 0,
                           "coarse mask covered everything -- "
                           "the D3 control is vacuous")
        # ...and the same error AFTER refinement (half a
        # refinement step) covers everything (the companion
        # assertion to test_refined_mask_covers_all_transits).
        step = 0.03 * self.P_TRUE / 800.0
        mask_r = dt.transit_mask(t, self.P_TRUE + step / 2.0,
                                 self.T0_TRUE, self.D_TRUE)
        self.assertEqual(int((in_tr & ~mask_r).sum()), 0)

    def test_mask_covers_transit_at_sector_boundary(self):
        # A transit centred just inside a sector start (one
        # cadence after the downlink gap) is still fully masked.
        t = _four_sector_times()
        t0_edge = 27.4 + 0.02  # first cadences of sector 2
        ph = ((t - t0_edge + 0.5 * self.P_TRUE)
              % self.P_TRUE) - 0.5 * self.P_TRUE
        in_tr = np.abs(ph) <= self.D_TRUE / 2.0
        self.assertGreater(in_tr.sum(), 0)
        mask = dt.transit_mask(t, self.P_TRUE, t0_edge,
                               self.D_TRUE)
        self.assertEqual(int((in_tr & ~mask).sum()), 0)


class TestMeasureCdpp(unittest.TestCase):
    """The frozen §3 measure_cdpp."""

    def test_white_noise_value(self):
        # 27 d at 2-min cadence, sigma 0.1%: 0.1 d segments hold
        # 72 cadences, so CDPP ~ 1000/sqrt(72) ~ 118 ppm.
        rng = np.random.default_rng(0)
        t = np.arange(27.0 * 720) * 2.0 / 1440.0
        f = 1.0 + rng.normal(0, 0.001, len(t))
        out = dt.measure_cdpp(t, f, 0.1)
        self.assertIsNotNone(out["cdpp_ppm"])
        self.assertAlmostEqual(out["cdpp_ppm"], 1000.0 / math.sqrt(72),
                               delta=0.20 * 1000.0 / math.sqrt(72))
        self.assertGreater(out["n_segments"], 200)

    def test_constant_curve_is_zero(self):
        t = np.arange(2000) * 0.02
        out = dt.measure_cdpp(t, np.ones(2000), 0.1)
        self.assertEqual(out["cdpp_ppm"], 0.0)
        self.assertEqual(out["mad_ppm"], 0.0)

    def test_fewer_than_five_segments_is_none(self):
        # 0.3 d at 30-min cadence, 0.1 d windows -> 3 segments.
        t = np.arange(15) * 0.02
        out = dt.measure_cdpp(t, np.ones(15), 0.1)
        self.assertEqual(out["n_segments"], 3)
        self.assertIsNone(out["cdpp_ppm"])

    def test_trailing_partial_fifty_percent_rule(self):
        # dt=0.02 d, duration=1.0 d -> 50 cadences per full segment.
        # 5.4 d chunk: trailing window holds 20 (<50%) -> dropped.
        t = np.arange(0, 5.4, 0.02)
        out = dt.measure_cdpp(t, np.ones(len(t)), 1.0)
        self.assertEqual(out["n_segments"], 5)
        # 5.6 d chunk: trailing window holds 30 (>=50%) -> kept.
        t = np.arange(0, 5.6, 0.02)
        out = dt.measure_cdpp(t, np.ones(len(t)), 1.0)
        self.assertEqual(out["n_segments"], 6)

    def test_paired_boundary_identity(self):
        # The segment boundaries depend on the time array alone,
        # so two legs over the same host get identical bounds.
        rng = np.random.default_rng(1)
        t = np.arange(2000) * 0.02
        f1 = 1.0 + rng.normal(0, 0.001, len(t))
        f2 = f1 + 0.002 * np.sin(2 * np.pi * t / 5.0)
        b1 = dt.measure_cdpp(t, f1, 0.1)["segment_bounds"]
        b2 = dt.measure_cdpp(t, f2, 0.1)["segment_bounds"]
        self.assertEqual(b1, b2)

    def test_no_segment_spans_a_gap(self):
        t = np.concatenate([np.arange(0, 14.0, 0.02),
                            np.arange(15.0, 29.0, 0.02)])
        out = dt.measure_cdpp(t, np.ones(len(t)), 0.1)
        for a, b in out["segment_bounds"]:
            self.assertFalse(t[a] < 14.0 and t[b - 1] > 15.0,
                             f"segment {(a, b)} spans the gap")

    def test_mid_chunk_windows_keep_available_cadences(self):
        # A mid-chunk window with a missing cadence (a 0.04 d hole,
        # under the 0.05 d gap split) still contributes its mean
        # over the available cadences.
        t = np.arange(0, 5.0, 0.02)
        t = t[~((t > 2.1) & (t < 2.14))]  # drop t=2.12, window 2
        out = dt.measure_cdpp(t, np.ones(len(t)), 1.0)
        self.assertEqual(out["n_segments"], 5)
        self.assertEqual(out["segment_counts"][2], 49)


class TestFlagOffRegression(_BulkV6Case):
    """D10: flag-off output is byte-identical to pre-5.7 code.

    The pins were generated from the pre-change code (tip 2f5fb6d)
    under bulk_v6; the FITS filename is part of the record
    (product_ids), so each case is rebuilt under its own name.
    """

    def _pins(self):
        return json.loads(PINS_PATH.read_text())

    def test_pinned_records_byte_identical(self):
        with tempfile.TemporaryDirectory() as td:
            for name, case in sorted(self._pins().items()):
                path = make_qlp_fits(Path(td) / f"{name}.fits",
                                     **case["fits_kw"])
                rec = bs._screen_one(screen_job(path))
                self.assertEqual(rec, case["record"], name)

    def test_explicit_v6_equals_default(self):
        # The 6-tuple with an explicit "v6" takes the detrend-
        # parsing branch; it must produce the same record as the
        # 4-tuple default.
        with tempfile.TemporaryDirectory() as td:
            path = make_qlp_fits(
                Path(td) / "synth.fits", period_d=3.0,
                depth_frac=0.01, duration_d=0.1, noise_pct=0.003,
                seed=42)
            rec_default = bs._screen_one(screen_job(path))
            job6 = (str("999999999"), str(path), 1,
                    {"ra": 100.0, "dec": -65.0, "tmag": 12.0,
                     "radius": 0.7}, False, "v6")
            rec_v6 = bs._screen_one(job6)
            self.assertEqual(rec_default, rec_v6)

    def test_no_detrend_keys_flag_off(self):
        with tempfile.TemporaryDirectory() as td:
            for name, case in sorted(self._pins().items()):
                path = make_qlp_fits(Path(td) / f"{name}.fits",
                                     **case["fits_kw"])
                rec = bs._screen_one(screen_job(path))
                for key in dt.DETREND_RECORD_KEYS:
                    self.assertNotIn(key, rec, f"{name}:{key}")

    def test_unknown_detrend_is_an_error_record(self):
        # An invalid flag value is a per-star error record, not an
        # exception escaping the screen.
        with tempfile.TemporaryDirectory() as td:
            path = make_qlp_fits(Path(td) / "synth.fits",
                                 period_d=None, seed=3)
            job = (str("999999999"), str(path), 1,
                   {"ra": 100.0, "dec": -65.0, "tmag": 12.0,
                    "radius": 0.7}, False, "v9")
            rec = bs._screen_one(job)
            self.assertIn("error", rec.get("status", "")
                          + rec.get("search_health", ""))


class TestScreenV7(_BulkV6Case):
    """End-to-end v7 screens: adoption, skips, guard, fallback."""

    def _screen_v7(self, td, name, **fits_kw):
        path = make_qlp_fits(Path(td) / f"{name}.fits", **fits_kw)
        return bs._screen_one(screen_job(path, detrend="v7"))

    def test_adoption_replaces_headline(self):
        # transit_p3: a real 1% transit adopts (SDE 51.6 -> 66.9
        # measured) and the headline IS the pass-2 result.
        with tempfile.TemporaryDirectory() as td:
            rec = self._screen_v7(
                td, "transit_p3", period_d=3.0, depth_frac=0.01,
                duration_d=0.1, noise_pct=0.003, seed=42)
            self.assertTrue(rec["detrend_adopted"])
            self.assertTrue(rec["detrend_gate_passed"])
            self.assertEqual(rec["period_days"],
                             rec["detrend_pass2_period_days"])
            self.assertEqual(rec["sde"], rec["detrend_pass2_sde"])
            self.assertEqual(rec["depth_percent"],
                             rec["detrend_pass2_depth_percent"])
            self.assertEqual(rec["duration_hours"],
                             rec["detrend_pass2_duration_hours"])
            self.assertEqual(rec["t0_btjd"],
                             rec["detrend_pass2_t0_btjd"])
            self.assertGreater(rec["detrend_gate_raw_depth_pct"],
                               0.0)
            self.assertGreaterEqual(rec["detrend_gate_raw_signif"],
                                    dt.PASS2_GATE_MIN_SIGNIF)
            # All four stages timed.
            for stage in ("flatten", "refine", "reflatten",
                          "bls2"):
                self.assertIn(stage, rec["detrend_seconds"])

    def test_v7_pass1_differs_from_v6(self):
        # The v7 pass 1 flattens at 1.0 d, not 2.0 d, so its SDE
        # differs from the v6 headline on the same curve (51.65 vs
        # 58.58 measured on transit_p3). The v7 second pass is a
        # comparison against the V7 pass 1, not against v6.
        with tempfile.TemporaryDirectory() as td:
            path = make_qlp_fits(
                Path(td) / "transit_p3.fits", period_d=3.0,
                depth_frac=0.01, duration_d=0.1, noise_pct=0.003,
                seed=42)
            rec6 = bs._screen_one(screen_job(path))
            rec7 = bs._screen_one(screen_job(path, detrend="v7"))
            self.assertNotEqual(rec7["detrend_pass1_sde"],
                                rec6["sde"])

    def test_below_floor_skips_second_pass(self):
        # Pure noise, seed 8: the v7 pass-1 SDE is 5.90 (< 6.0),
        # so the second pass is skipped with the below_floor
        # reason and only the flatten stage is timed.
        with tempfile.TemporaryDirectory() as td:
            rec = self._screen_v7(td, "noise8", period_d=None,
                                  seed=8)
            self.assertEqual(rec["status"], "below_floor")
            self.assertEqual(rec["detrend_pass2_skip_reason"],
                             "below_floor")
            self.assertNotIn("detrend_pass2_sde", rec)
            self.assertNotIn("detrend_adopted", rec)
            self.assertEqual(sorted(rec["detrend_seconds"]),
                             ["flatten"])

    def test_mask_guard_skips_and_pass1_stands(self):
        # P=0.5 d, D=0.25 d: duty 50% + pad -> mask fraction 0.58
        # > 0.50, so the second pass is skipped (D4) and no pass-2
        # metrics or adoption appear.
        with tempfile.TemporaryDirectory() as td:
            rec = self._screen_v7(
                td, "guard", period_d=0.5, depth_frac=0.01,
                duration_d=0.25, noise_pct=0.003, seed=5)
            self.assertEqual(rec["detrend_pass2_skip_reason"],
                             "mask_fraction_gt_50pct")
            self.assertGreater(rec["detrend_mask_fraction"], 0.5)
            self.assertNotIn("detrend_pass2_sde", rec)
            self.assertNotIn("detrend_adopted", rec)
            self.assertAlmostEqual(rec["period_days"], 0.5,
                                   delta=0.01)

    def test_second_pass_failure_falls_back_to_pass1(self):
        # D8: a failure in the second pass records the failure and
        # leaves the pass-1 headline standing.
        with tempfile.TemporaryDirectory() as td:
            path = make_qlp_fits(
                Path(td) / "transit_p3.fits", period_d=3.0,
                depth_frac=0.01, duration_d=0.1, noise_pct=0.003,
                seed=42)
            rec_ok = bs._screen_one(screen_job(path, detrend="v7"))
            self.assertTrue(rec_ok["detrend_adopted"])
            with mock.patch.object(
                    dt, "masked_savgol_trend",
                    side_effect=RuntimeError("boom")):
                rec = bs._screen_one(screen_job(path,
                                                detrend="v7"))
            self.assertIn("detrend_pass2_failed", rec)
            self.assertIn("RuntimeError", rec["detrend_pass2_failed"])
            self.assertNotIn("detrend_adopted", rec)
            # Headline == the unpatched run's pass-1 values.
            self.assertEqual(rec["period_days"],
                             rec_ok["detrend_pass1_period_days"])
            self.assertEqual(rec["sde"],
                             rec_ok["detrend_pass1_sde"])
            self.assertEqual(rec["depth_percent"],
                             rec_ok["detrend_pass1_depth_percent"])

    def test_raw_flux_gate_vetoes_adoption(self):
        # D6: with the raw-flux gate forced to fail, the second
        # pass still runs (its metrics are recorded) but the
        # adoption is vetoed and pass 1 stands -- even though the
        # SDE condition passes (SDE2 66.9 >= SDE1 - 1.0).
        with tempfile.TemporaryDirectory() as td:
            path = make_qlp_fits(
                Path(td) / "transit_p3.fits", period_d=3.0,
                depth_frac=0.01, duration_d=0.1, noise_pct=0.003,
                seed=42)
            with mock.patch.object(dt, "raw_fold_depth",
                                   return_value=(0.0, 0.0)):
                rec = bs._screen_one(screen_job(path,
                                                detrend="v7"))
            self.assertFalse(rec["detrend_gate_passed"])
            self.assertFalse(rec["detrend_adopted"])
            self.assertIn("detrend_pass2_sde", rec)
            self.assertGreaterEqual(
                rec["detrend_pass2_sde"],
                rec["detrend_pass1_sde"] - dt.ADOPT_SDE_DROP)
            self.assertEqual(rec["sde"],
                             rec["detrend_pass1_sde"])
            self.assertEqual(rec["period_days"],
                             rec["detrend_pass1_period_days"])

    def test_short_period_adopts(self):
        # short_p0p8: a second adoption case (SDE 96.2 -> 99.5).
        with tempfile.TemporaryDirectory() as td:
            rec = self._screen_v7(
                td, "short_p0p8", period_d=0.8, depth_frac=0.005,
                duration_d=0.06, noise_pct=0.002, seed=11)
            self.assertTrue(rec["detrend_adopted"])
            self.assertEqual(rec["sde"], rec["detrend_pass2_sde"])


class TestRawFluxGate(_BulkV6Case):
    """D6: the raw-flux gate measurement itself."""

    def _fold_curve(self, depth_frac=0.005, noise_pct=0.001,
                    seed=0, period=3.0, t0=1502.0, duration=0.1):
        rng = np.random.default_rng(seed)
        t = 1500.0 + np.arange(1296) * 0.5 / 24.0
        ph = ((t - t0 + 0.5 * period) % period) - 0.5 * period
        in_tr = np.abs(ph) <= duration / 2.0
        f = np.where(in_tr, 1.0 - depth_frac, 1.0)
        f = f + rng.normal(0, noise_pct, len(t))
        return t, f

    def test_real_transit_passes(self):
        t, f = self._fold_curve()
        depth, signif = dt.raw_fold_depth(t, f, 3.0, 1502.0, 0.1)
        self.assertAlmostEqual(depth, 0.5, delta=0.1)
        self.assertGreaterEqual(signif, dt.PASS2_GATE_MIN_SIGNIF)

    def test_noise_fails(self):
        t, f = self._fold_curve(depth_frac=0.0)
        depth, signif = dt.raw_fold_depth(t, f, 3.0, 1502.0, 0.1)
        self.assertLess(signif, dt.PASS2_GATE_MIN_SIGNIF)

    def test_inverted_transit_fails(self):
        # A brightening (negative depth) fails the depth > 0 leg.
        t, f = self._fold_curve(depth_frac=-0.005)
        depth, signif = dt.raw_fold_depth(t, f, 3.0, 1502.0, 0.1)
        self.assertLess(depth, 0.0)

    def test_threshold_pinned_to_hunter(self):
        # The gate uses hunter.py's EXISTING threshold -- do not
        # invent a new one. If hunter.py moves, this test fails
        # and the two must be reconciled deliberately.
        try:
            hunter = _hunter()
        except ImportError as exc:
            self.skipTest(f"hunter.py not importable: {exc}")
        self.assertEqual(dt.PASS2_GATE_MIN_SIGNIF,
                         hunter._PASS2_GATE_MIN_SIGNIF)

    def test_agrees_with_hunter_function(self):
        # raw_fold_depth is a verbatim copy of hunter.py's
        # _raw_fold_depth; the two must agree exactly.
        try:
            hunter = _hunter()
        except ImportError as exc:
            self.skipTest(f"hunter.py not importable: {exc}")
        t, f = self._fold_curve()
        a = dt.raw_fold_depth(t, f, 3.0, 1502.0, 0.1)
        b = hunter._raw_fold_depth(t, f, 3.0, 1502.0, 0.1)
        self.assertEqual(a, b)
        t2, f2 = self._fold_curve(depth_frac=0.0, seed=5)
        self.assertEqual(dt.raw_fold_depth(t2, f2, 3.0, 1502.0,
                                           0.1),
                         hunter._raw_fold_depth(t2, f2, 3.0,
                                                1502.0, 0.1))


class TestPreprocessV7(_BulkV6Case):
    """R3: pre-SavGol stitching under v7."""

    def _trend_curve(self, seed=0):
        rng = np.random.default_rng(seed)
        t = 1500.0 + np.arange(1296) * 0.5 / 24.0
        # A slow trend (1% ramp + 0.5% sinusoid) + white noise.
        trend = (1.0 + 0.01 * (t - 1500.0) / 27.0
                 + 0.005 * np.sin(2 * np.pi * (t - 1500.0) / 7.0))
        f = trend + rng.normal(0, 0.001, len(t))
        q = np.zeros(len(t), dtype=np.int32)
        return t, f, q, trend

    def test_preprocess_arrays_v7_keeps_trend(self):
        t, f, q, trend = self._trend_curve()
        t7, f7 = orc.preprocess_arrays(t, f, q, detrend="v7")
        # No flatten: the output still tracks the input trend
        # (correlation 0.974 measured; the ceiling is set by the
        # white noise, trend_std/sqrt(trend_std^2+noise_std^2) ~
        # 0.977 -- not by any processing), and the median is
        # exactly 1.0.
        self.assertEqual(len(t7), len(t))
        self.assertAlmostEqual(float(np.median(f7)), 1.0, places=12)
        corr = float(np.corrcoef(f7, trend)[0, 1])
        self.assertGreater(corr, 0.95)
        # v6 flattens it away.
        _t6, f6 = orc.preprocess_arrays(t, f, q, detrend="v6")
        corr6 = float(np.corrcoef(f6, trend)[0, 1])
        self.assertLess(abs(corr6), 0.2)

    def test_preprocess_arrays_v7_masks_quality(self):
        t, f, q, _trend = self._trend_curve()
        q[100:200] = 1 << 29  # a flagged block
        t7, f7 = orc.preprocess_arrays(t, f, q, detrend="v7")
        self.assertEqual(len(t7), len(t) - 100)

    def test_preprocess_arrays_invalid_detrend_raises(self):
        t, f, q, _trend = self._trend_curve()
        with self.assertRaises(ValueError):
            orc.preprocess_arrays(t, f, q, detrend="v9")

    def test_preprocess_sector_v7_sigma_from_flattened_copy(self):
        # Under v7 the stitched arrays are pre-SavGol, but sigma
        # comes from the temporary 1.0 d flattened copy -- so it
        # tracks the white noise (~0.001), not the trend (~0.01).
        t, f, q, _trend = self._trend_curve()
        _t7, f7, sig7 = p43.preprocess_sector(t, f, q,
                                              detrend="v7")
        self.assertAlmostEqual(sig7, 0.001, delta=0.0005)
        corr = float(np.corrcoef(f7, _trend)[0, 1])
        self.assertGreater(corr, 0.95)  # noise-limited ceiling
        # v6 sigma is the same quantity (same flattened curve).
        _t6, _f6, sig6 = p43.preprocess_sector(t, f, q,
                                               detrend="v6")
        self.assertAlmostEqual(sig7, sig6, delta=0.0005)

    def test_subset_copies_detrend_keys_when_present(self):
        rec = {"period_days": 3.0, "sde": 10.0,
               "detrend": "v7", "detrend_adopted": True,
               "detrend_pass1_sde": 9.0,
               "detrend_pass2_sde": 10.0,
               "detrend_gate_passed": True,
               "detrend_seconds": {"flatten": 0.01}}
        sub = orc._subset(rec)
        for key in ("detrend", "detrend_adopted",
                    "detrend_pass1_sde", "detrend_pass2_sde",
                    "detrend_gate_passed", "detrend_seconds"):
            self.assertIn(key, sub)
            self.assertEqual(sub[key], rec[key])
        # Flag-off records carry none of them.
        sub_off = orc._subset({"period_days": 3.0, "sde": 10.0})
        for key in dt.DETREND_RECORD_KEYS:
            self.assertNotIn(key, sub_off)


class TestDriverThreading(_BulkV6Case):
    """screen_job shapes, k3/p43 threading, B1 helper."""

    def test_screen_job_tuple_shapes(self):
        job4 = screen_job("x.fits")
        self.assertEqual(len(job4), 4)
        job5 = screen_job("x.fits", return_periodogram=True)
        self.assertEqual(len(job5), 5)
        self.assertTrue(job5[4])
        job6 = screen_job("x.fits", detrend="v7")
        self.assertEqual(len(job6), 6)
        self.assertEqual(job6[4], False)
        self.assertEqual(job6[5], "v7")
        job6b = screen_job("x.fits", return_periodogram=True,
                           detrend="v7")
        self.assertEqual(len(job6b), 6)
        self.assertEqual(job6b[4], True)
        self.assertEqual(job6b[5], "v7")
        # Explicit v6 is the 4-tuple (no flag carried).
        self.assertEqual(len(screen_job("x.fits", detrend="v6")),
                         4)

    def test_k3_screen_threads_detrend(self):
        with tempfile.TemporaryDirectory() as td:
            path = make_qlp_fits(
                Path(td) / "synth.fits", period_d=3.0,
                depth_frac=0.01, duration_d=0.1, noise_pct=0.003,
                seed=42)
            rec_off = k3run._screen(str(path), "999999999", 1)
            self.assertNotIn("detrend", rec_off)
            rec_on = k3run._screen(str(path), "999999999", 1,
                                   detrend="v7")
            self.assertEqual(rec_on["detrend"], "v7")
            self.assertTrue(rec_on["detrend_adopted"])

    def _fake_cache_manifest(self, td):
        cache = Path(td) / "cache"
        for sec in (95, 96, 97):
            (cache / f"s{sec:04d}").mkdir(parents=True)
            make_qlp_fits(cache / f"s{sec:04d}" / "999999999.fits",
                          period_d=None, seed=sec)
        manifest = {"trials": [{"tic": "999999999", "sector": 95}],
                    "_sha256": "x" * 64}
        mpath = Path(td) / "manifest.json"
        mpath.write_text(json.dumps(
            {"trials": manifest["trials"]}))
        return cache, mpath

    def test_p43_build_jobs_carries_flags(self):
        with tempfile.TemporaryDirectory() as td:
            cache, _mpath = self._fake_cache_manifest(td)
            manifest = {"trials": [{"tic": "999999999",
                                    "sector": 95}],
                        "_sha256": "x" * 64}
            single, stitched, missing = p43run._build_jobs(
                manifest, cache, Path(td) / "out",
                Path(td) / "w43", Path(td) / "w1", False,
                "bulk_v6", detrend="v7", b1_periodogram=True)
            self.assertEqual(missing, [])
            self.assertEqual(len(single), 1)
            self.assertEqual(len(stitched), 1)
            self.assertEqual(single[0]["detrend"], "v7")
            self.assertEqual(stitched[0]["detrend"], "v7")
            self.assertTrue(stitched[0]["b1_periodogram"])
            # Defaults: v6, no B1.
            single0, stitched0, _m = p43run._build_jobs(
                manifest, cache, Path(td) / "out",
                Path(td) / "w43", Path(td) / "w1", False,
                "bulk_v6")
            self.assertEqual(single0[0]["detrend"], "v6")
            self.assertEqual(stitched0[0]["detrend"], "v6")
            self.assertFalse(stitched0[0]["b1_periodogram"])

    def test_p43_cli_accepts_flags_dry_run(self):
        with tempfile.TemporaryDirectory() as td:
            cache, mpath = self._fake_cache_manifest(td)
            out = Path(td) / "out"
            rc = p43run.main([
                "--mode", "campaign", "--manifest", str(mpath),
                "--cache", str(cache), "--out-dir", str(out),
                "--calibration", "bulk_v6",
                "--detrend", "v7", "--b1-periodogram",
                "--dry-run"])
            self.assertEqual(rc, 0)
            rc = p43run.main([
                "--mode", "null", "--manifest", str(mpath),
                "--cache", str(cache), "--out-dir", str(out),
                "--calibration", "bulk_v6",
                "--detrend", "v7", "--dry-run"])
            self.assertEqual(rc, 0)

    def test_period_in_top15(self):
        # A 1% transit at P=3.0 d: the injected period is the BLS
        # argmax, so it is in the top 15 at rank 0.
        rng = np.random.default_rng(0)
        t = 1500.0 + np.arange(1296) * 0.5 / 24.0
        ph = ((t - 1502.0 + 1.5) % 3.0) - 1.5
        f = np.where(np.abs(ph) < 0.05, 0.99, 1.0)
        f = f + rng.normal(0, 0.003, len(t))
        pg = _bls_periodogram(t, f)
        found, rank = jf.period_in_top15(pg, 3.0)
        self.assertTrue(found)
        self.assertIsNotNone(rank)
        found2, rank2 = jf.period_in_top15(pg, 7.77)
        self.assertFalse(found2)
        self.assertIsNone(rank2)
        self.assertEqual(jf.period_in_top15(None, 3.0),
                         (False, None))
        self.assertEqual(jf.period_in_top15(pg, None),
                         (False, None))


class TestCdppRepro(unittest.TestCase):
    """Protocol §7: the CDPP baseline reproduction test.

    Mac-only: the 4.1-10 hosts' sector files live in the Mac's
    S95-S98 caches, not on the VM. Skips unless
    EXHUNT_CDPP_REPRO_CACHE is set; the manifest defaults to the
    VM science-vet path (override with
    EXHUNT_CDPP_REPRO_MANIFEST).

    The assertion is on the CENSUS replica (the harness proof):
    it must match the manifest within 0.1% on every host. The §3
    values are computed for every host and recorded in the report
    -- they measure a different quantity by construction (no
    masking, different chunking), so the test does NOT assert
    them against the manifest; the gate decision is made from the
    report (protocol §7 sanctions documenting a proven procedural
    difference).
    """

    def test_census_replica_matches_manifest(self):
        cache = os.environ.get("EXHUNT_CDPP_REPRO_CACHE")
        if not cache:
            self.skipTest(
                "EXHUNT_CDPP_REPRO_CACHE unset (Mac-only)")
        manifest = os.environ.get("EXHUNT_CDPP_REPRO_MANIFEST",
                                  str(DEFAULT_MANIFEST))
        with tempfile.TemporaryDirectory() as td:
            report = repro.run_repro(
                manifest, cache, Path(td) / "repro.json",
                calibration="bulk_v4")
        self.assertEqual(report["n_errors"], 0,
                         [r for r in report["hosts"]
                          if "error" in r][:3])
        self.assertEqual(report["n_hosts"], 49)
        self.assertEqual(report["census_replica_within_tol"],
                         report["n_ok"],
                         "census replica misses the 0.1% bar -- "
                         "the harness does not reproduce the "
                         "manifest procedure")
        for row in report["hosts"]:
            self.assertIsNotNone(row.get("s3_cdpp_ppm"),
                                 row["tic"])
        print(f"\n[cdpp-repro] census max |rel diff| "
              f"{report['census_replica_max_abs_rel_diff']:.2e}; "
              f"§3 median rel diff "
              f"{report['s3_median_rel_diff']:+.4f}; "
              f"§3 within 0.1%: {report['s3_within_tol']}/"
              f"{report['n_ok']}")


if __name__ == "__main__":
    unittest.main()
