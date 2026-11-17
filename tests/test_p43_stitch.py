"""Tests for bulk/p43_stitch.py (P4-3 multi-sector stitching).

Offline: synthetic arrays only, no downloads, no Mac. The stitch
is the P4-3 pre-registered design (P43_PREREG.md): per-sector
preprocess + inverse-variance weighting + concatenate/time-sort,
CROWDSAP tracking (None for QLP headers), per-sector
transit-consistency record.
"""

import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
from astropy.io import fits

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import bulk_screen as bs  # noqa: E402
import injection_harness as ih  # noqa: E402
from bulk import p43_stitch as p43  # noqa: E402

CADENCE_D = 1.0 / 48.0  # QLP 30-min cadence


def _synth_sector(t0, n, period, epoch, depth, duration, sigma, rng):
    """Synthetic sector: flat flux + noise + a box transit train."""
    t = t0 + CADENCE_D * np.arange(n)
    f = 1.0 + rng.normal(0.0, sigma, n)
    q = np.zeros(n, dtype=int)
    k_min = int(np.ceil((t[0] - epoch) / period))
    k_max = int(np.floor((t[-1] - epoch) / period))
    for k in range(k_min, k_max + 1):
        tc = epoch + k * period
        m = np.abs(t - tc) <= duration / 2.0
        f[m] -= depth
    return t, f, q


class TestSectorSigma(unittest.TestCase):
    def test_recovers_noise(self):
        rng = np.random.default_rng(0)
        f = 1.0 + rng.normal(0.0, 0.01, 10000)
        self.assertAlmostEqual(p43.sector_sigma(None, f), 0.01,
                               delta=0.0005)


class TestStitchWeighted(unittest.TestCase):
    def test_single_sector_is_identity(self):
        rng = np.random.default_rng(1)
        t, f, q = _synth_sector(3800.0, 1300, 5.0, 3801.0, 0.01,
                                0.15, 0.005, rng)
        t_s, f_s, q_s, tr = p43.stitch_weighted(
            [{"sector": 95, "t": t, "f": f, "q": q,
              "fcol": "SYS_RM_FLUX", "crowdsap": None}], {95: 0.005})
        self.assertEqual(len(t_s), 1300)
        self.assertTrue(np.allclose(f_s, f))  # reference unscaled
        self.assertAlmostEqual(tr["sigma_ref"], 0.005)
        self.assertAlmostEqual(tr["sectors"][95]["scale"], 1.0)

    def test_damps_noisy_sector(self):
        rng = np.random.default_rng(2)
        t1, f1, q1 = _synth_sector(3800.0, 1300, 5.0, 3801.0, 0.01,
                                   0.15, 0.005, rng)
        t2, f2, q2 = _synth_sector(3828.0, 1300, 5.0, 3801.0, 0.01,
                                   0.15, 0.02, rng)
        t_s, f_s, q_s, tr = p43.stitch_weighted(
            [{"sector": 95, "t": t1, "f": f1, "q": q1,
              "fcol": "SYS_RM_FLUX", "crowdsap": None},
             {"sector": 96, "t": t2, "f": f2, "q": q2,
              "fcol": "SYS_RM_FLUX", "crowdsap": None}],
            {95: 0.005, 96: 0.02})
        self.assertAlmostEqual(tr["sigma_ref"], 0.005)
        self.assertAlmostEqual(tr["sectors"][96]["scale"], 0.25)
        # the stitched noisy half has robust sigma ~0.005 (damped)
        m2 = t_s >= 3828.0
        self.assertAlmostEqual(
            p43.sector_sigma(t_s[m2], f_s[m2]), 0.005, delta=0.0008)
        self.assertTrue(np.all(np.diff(t_s) > 0))
        self.assertEqual(len(t_s), 2600)

    def test_depth_preserved_for_equal_sigma(self):
        rng = np.random.default_rng(3)
        t1, f1, q1 = _synth_sector(3800.0, 1300, 5.0, 3801.0, 0.01,
                                   0.15, 0.005, rng)
        t2, f2, q2 = _synth_sector(3828.0, 1300, 5.0, 3801.0, 0.01,
                                   0.15, 0.005, rng)
        t_s, f_s, q_s, tr = p43.stitch_weighted(
            [{"sector": 95, "t": t1, "f": f1, "q": q1,
              "fcol": "SYS_RM_FLUX", "crowdsap": None},
             {"sector": 96, "t": t2, "f": f2, "q": q2,
              "fcol": "SYS_RM_FLUX", "crowdsap": None}],
            {95: 0.005, 96: 0.005})
        depth, n_in, _ = bs._fold_depth(t_s, f_s, 5.0, 3801.0, 0.15)
        self.assertAlmostEqual(depth, 0.01, delta=0.0025)
        self.assertGreaterEqual(n_in, 20)


class TestCrowdsap(unittest.TestCase):
    def test_none_for_qlp_style_header(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "fake.fits"
            hdu = fits.PrimaryHDU()
            hdu.header["OBJECT"] = "TIC 123"
            hdu.writeto(path, overwrite=True)
            self.assertIsNone(p43.read_crowdsap(str(path)))

    def test_present(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "fake2.fits"
            hdu = fits.PrimaryHDU()
            hdu.header["CROWDSAP"] = 0.87
            hdu.writeto(path, overwrite=True)
            self.assertAlmostEqual(p43.read_crowdsap(str(path)), 0.87)


class TestSectorConsistency(unittest.TestCase):
    def _two_sector_stitch(self, depth2, seed):
        rng = np.random.default_rng(seed)
        t1, f1, q1 = _synth_sector(3800.0, 1300, 5.0, 3801.0, 0.01,
                                   0.15, 0.005, rng)
        t2, f2, q2 = _synth_sector(3828.0, 1300, 5.0, 3801.0, depth2,
                                   0.15, 0.005, rng)
        t_s, f_s, q_s, _tr = p43.stitch_weighted(
            [{"sector": 95, "t": t1, "f": f1, "q": q1,
              "fcol": "SYS_RM_FLUX", "crowdsap": None},
             {"sector": 96, "t": t2, "f": f2, "q": q2,
              "fcol": "SYS_RM_FLUX", "crowdsap": None}],
            {95: 0.005, 96: 0.005})
        return (t_s, f_s, q_s,
                [(95, float(t1[0]), float(t1[-1])),
                 (96, float(t2[0]), float(t2[-1]))])

    def test_all_sectors_show_signal(self):
        t_s, f_s, q_s, bounds = self._two_sector_stitch(0.01, 4)
        out = p43.sector_consistency(t_s, f_s, q_s, bounds,
                                     5.0, 3801.0, 0.15)
        self.assertAlmostEqual(out[95]["depth_frac"], 0.01,
                               delta=0.003)
        self.assertAlmostEqual(out[96]["depth_frac"], 0.01,
                               delta=0.003)
        self.assertGreater(out[95]["n_in_transit"], 0)
        self.assertGreater(out[96]["n_in_transit"], 0)

    def test_one_sector_only_signal(self):
        t_s, f_s, q_s, bounds = self._two_sector_stitch(0.0, 5)
        out = p43.sector_consistency(t_s, f_s, q_s, bounds,
                                     5.0, 3801.0, 0.15)
        self.assertAlmostEqual(out[95]["depth_frac"], 0.01,
                               delta=0.003)
        self.assertLess(abs(out[96]["depth_frac"] or 0.0), 0.003)


class TestAbsoluteEpochInjection(unittest.TestCase):
    def test_same_planet_same_absolute_times_across_sectors(self):
        """The P4-3 injection rule: the SAME planet injected into
        two sectors with different t_min via the ABSOLUTE epoch_btjd
        lands at the same absolute times. Using epoch_offset
        (relative to each sector's t_min) would shift the second
        sector's epoch by the t_min difference -- this test pins
        the absolute rule.
        """
        rng = np.random.default_rng(6)
        period, epoch, depth = 5.0, 3801.0, 0.01
        t1, f1, q1 = _synth_sector(3800.0, 1300, period, epoch, 0.0,
                                   0.15, 0.005, rng)
        t2, f2, q2 = _synth_sector(3828.0, 1300, period, epoch, 0.0,
                                   0.15, 0.005, rng)
        f1i, duration = ih.inject_transit(t1, f1, depth, period, epoch)
        f2i, _ = ih.inject_transit(t2, f2, depth, period, epoch)
        d1, _, _ = bs._fold_depth(t1, f1i, period, epoch, duration)
        d2, _, _ = bs._fold_depth(t2, f2i, period, epoch, duration)
        self.assertAlmostEqual(d1, 0.01, delta=0.003)
        self.assertAlmostEqual(d2, 0.01, delta=0.003)
        # and the wrong rule (epoch_offset relative to t_min) MISSES:
        off = epoch - t1[0]
        f2w, _ = ih.inject_transit(t2, f2, depth, period, t2[0] + off)
        d2w, _, _ = bs._fold_depth(t2, f2w, period, epoch, duration)
        self.assertLess(abs(d2w or 0.0), 0.003)


if __name__ == "__main__":
    unittest.main()
