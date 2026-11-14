"""Unit tests for the shared MAD clip (mad_clip.py, Phase 1.2 B-2).

No downloads. Each option is pinned on constructed arrays with
known outliers — the clip is the one function the screen and the
gauntlet share, so its behaviour is tested here, once, rather
than re-asserted at every call site.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402

from mad_clip import (ALL_OPTIONS, PROFILE_OPTIONS,  # noqa: E402
                      mad_clip_mask, mad_sigma)


def _quiet_star(n=1000, noise_pct=0.003, seed=42):
    rng = np.random.default_rng(seed)
    return 1.0 + rng.normal(0.0, noise_pct, n)


class TestMadSigma(unittest.TestCase):
    def test_mad_sigma_of_gaussian(self):
        _med, sig = mad_sigma(_quiet_star())
        self.assertAlmostEqual(sig, 0.003, delta=0.0005)

    def test_constant_flux_has_zero_sigma(self):
        _med, sig = mad_sigma(np.ones(100))
        self.assertEqual(sig, 0.0)


class TestSymmetric(unittest.TestCase):
    def test_matches_the_old_inline_expression(self):
        # The screen's v1 clip, verbatim: normalised flux, sd
        # around 1.0, |f - 1| < 5 sd. The shared function must
        # reproduce it bit-for-bit on the same array.
        rng = np.random.default_rng(7)
        f = 1.0 + rng.normal(0.0, 0.003, 2000)
        f[100] = 0.90  # deep dip: 33 sigma
        f[200] = 1.05  # high outlier
        med = np.median(f)
        fn = f / med
        sd = 1.4826 * np.median(np.abs(fn - 1.0))
        old_keep = np.abs(fn - 1.0) < 5 * sd
        new_keep = mad_clip_mask(fn, "symmetric")
        np.testing.assert_array_equal(new_keep, old_keep)

    def test_clips_both_sides(self):
        f = _quiet_star()
        f[10] = 0.90
        f[20] = 1.10
        keep = mad_clip_mask(f, "symmetric")
        self.assertFalse(keep[10])
        self.assertFalse(keep[20])
        self.assertTrue(keep.sum() > 990)


class TestUpwardOnly(unittest.TestCase):
    def test_keeps_every_dip(self):
        f = _quiet_star()
        f[10:14] = 0.985  # 1.5% transit, 5 sigma deep
        f[20] = 1.10  # high outlier still clipped
        keep = mad_clip_mask(f, "upward_only")
        self.assertTrue(keep[10:14].all())
        self.assertFalse(keep[20])


class TestIsolatedLowOnly(unittest.TestCase):
    def test_keeps_a_run_of_low_points(self):
        f = _quiet_star()
        f[10:14] = 0.985  # 4-point dip: each point has a low neighbour
        keep = mad_clip_mask(f, "isolated_low_only")
        self.assertTrue(keep[10:14].all())

    def test_clips_a_lone_low_point(self):
        f = _quiet_star()
        f[10] = 0.985  # lone dip: neighbours are normal
        keep = mad_clip_mask(f, "isolated_low_only")
        self.assertFalse(keep[10])

    def test_two_point_dip_survives(self):
        # A 1-2 h transit at 30-min cadence is only 2-4 points;
        # a 2-point dip must survive (each point's neighbour is low).
        f = _quiet_star()
        f[10:12] = 0.985
        keep = mad_clip_mask(f, "isolated_low_only")
        self.assertTrue(keep[10:12].all())


class TestFloor10pct(unittest.TestCase):
    def test_matches_the_gauntlet_expression(self):
        # gauntlet/rawflux_check.py + transit_fit.py, verbatim.
        rng = np.random.default_rng(7)
        f = 1.0 + rng.normal(0.0, 0.0008, 2000)
        f[100:104] = 0.94  # 6% eclipse on a 0.08%-MAD star
        f[200] = 1.30  # huge positive outlier
        med = np.median(f)
        sig = 1.4826 * np.median(np.abs(f - med))
        old_keep = ((f < med + 5 * sig)
                    & (f > med - max(5 * sig, 0.10)))
        new_keep = mad_clip_mask(f, "floor_10pct")
        np.testing.assert_array_equal(new_keep, old_keep)

    def test_keeps_deep_transit_clips_huge_excursion(self):
        f = _quiet_star(noise_pct=0.0008)
        f[10:14] = 0.94  # 6% eclipse: 75 sigma, kept by the floor
        f[20] = 0.75  # 25% excursion: beyond the floor, clipped
        keep = mad_clip_mask(f, "floor_10pct")
        self.assertTrue(keep[10:14].all())
        self.assertFalse(keep[20])


class TestNoneAndEdgeCases(unittest.TestCase):
    def test_none_keeps_everything(self):
        f = _quiet_star()
        f[10] = 0.5
        f[20] = 1.5
        keep = mad_clip_mask(f, "none")
        self.assertTrue(keep.all())

    def test_constant_flux_keeps_everything(self):
        keep = mad_clip_mask(np.ones(100), "symmetric")
        self.assertTrue(keep.all())

    def test_unknown_option_raises(self):
        with self.assertRaises(ValueError):
            mad_clip_mask(_quiet_star(), "sideways")

    def test_option_sets(self):
        self.assertEqual(set(ALL_OPTIONS),
                         set(PROFILE_OPTIONS) | {"none"})
        self.assertNotIn("none", PROFILE_OPTIONS)


if __name__ == "__main__":
    unittest.main()
