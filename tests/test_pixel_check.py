"""Pixel-check tests (Phase 2, 2A).

The pixel check (manual §7) is new code — the manual gauntlet
did it by eye on TESSCut cutouts. These tests drive it on
synthetic TPF cubes (5 d, 10-min cadence, 15x15 pixels):

  * a clean dip at the target pixel -> PASS;
  * a neighbour pixel brightening in transit -> FAIL, naming
    the pixel;
  * no dip at the target pixel -> UNMEASURED (the off-target
    question belongs to difference imaging);
  * no in-transit cadences -> UNMEASURED;
  * the tested-pixel set: the 3x3 around the target plus bright
    neighbours, not the whole cutout.
"""
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gauntlet.pixel_check import (  # noqa: E402
    pixel_check_native, tested_pixels)
from gauntlet.stage_result import pixel_check_result  # noqa: E402

P, T0, DUR = 2.0, 1500.5, 0.1


def _cube(dip_px=None, dip_pct=1.0, bright_px=None, bright_pct=2.0,
          seed=5):
    """A synthetic TPF: PSF-like flux centred on (7, 7), white
    noise, an optional dip at dip_px and an optional brightening
    at bright_px, both in transit."""
    rng = np.random.default_rng(seed)
    t = 1500.0 + np.arange(0, 5.0, 10.0 / 1440.0)
    yy, xx = np.mgrid[0:15, 0:15]
    base = 100.0 + 10000.0 * np.exp(
        -((xx - 7) ** 2 + (yy - 7) ** 2) / (2 * 1.5 ** 2))
    cube = (base[None, :, :]
            * (1.0 + rng.normal(0, 0.001, (len(t), 15, 15))))
    ph = ((t - T0 + 0.5 * P) % P) - 0.5 * P
    in_m = np.abs(ph) <= DUR / 2
    if dip_px is not None:
        y, x = dip_px
        cube[in_m, y, x] *= (1.0 - dip_pct / 100.0)
    if bright_px is not None:
        y, x = bright_px
        cube[in_m, y, x] *= (1.0 + bright_pct / 100.0)
    return t, cube


class TestPixelCheck(unittest.TestCase):
    def test_clean_dip_passes(self):
        t, cube = _cube(dip_px=(7, 7))
        native = pixel_check_native(cube, t, P, T0, DUR, (7, 7))
        self.assertEqual(native["verdict"], "pass")
        self.assertEqual(pixel_check_result(native).status, "pass")
        tp = native["details"]["target_pixel"]
        self.assertAlmostEqual(tp["depth_pct"], 1.0, delta=0.15)
        self.assertGreater(tp["signif"], 3.0)

    def test_brightening_pixel_fails(self):
        t, cube = _cube(dip_px=(7, 7), bright_px=(7, 8))
        native = pixel_check_native(cube, t, P, T0, DUR, (7, 7))
        self.assertEqual(native["verdict"], "fail")
        self.assertEqual(pixel_check_result(native).status, "fail")
        bp = native["details"]["brightening_pixel"]
        self.assertEqual((bp["y"], bp["x"]), (7, 8))
        self.assertLess(bp["signif"], -3.0)

    def test_no_dip_is_unmeasured(self):
        t, cube = _cube()
        native = pixel_check_native(cube, t, P, T0, DUR, (7, 7))
        self.assertEqual(native["verdict"], "unmeasured")
        self.assertEqual(pixel_check_result(native).status,
                         "unmeasured")

    def test_no_in_transit_is_unmeasured(self):
        # A transit narrower than the cadence has no in-transit
        # points (a shifted T0 would not — the fold is periodic).
        t, cube = _cube(dip_px=(7, 7))
        native = pixel_check_native(cube, t, P, T0, 0.0001, (7, 7))
        self.assertEqual(native["verdict"], "unmeasured")
        self.assertLess(native["details"]["n_in"], 5)

    def test_tested_pixel_set(self):
        t, cube = _cube()
        mask = tested_pixels(cube, (7, 7))
        # The 3x3 core is in; everything outside it is out, even a
        # bright PSF-tail pixel — it is not in the aperture.
        self.assertTrue(mask[6:9, 6:9].all())
        self.assertEqual(int(mask.sum()), 9)
        self.assertFalse(mask[7, 10])
        self.assertFalse(mask[0, 0])


class TestNullCalibration(unittest.TestCase):
    """P-1 (Phase 2 vote follow-up): the false-fail rate on
    null stars. The 3-sigma brightening bar applies to the 9
    tested pixels (the 3x3 aperture), so the nominal one-sided
    false-fail rate is 1 - (1 - 0.00135)**9 ~= 1.2% — NOT
    Claude's ~1-in-4, which is the correct arithmetic for a
    225-pixel population this code does not test. These tests
    measure the rate on synthetic nulls (fixed seeds, so the
    counts are deterministic) and bound it well below 25%: if
    anyone widens the tested set to the whole cutout, the rate
    jumps to ~26% and this test fails loudly. Two populations:
    pure noise (no dip anywhere) and clean targets (a real 3%
    dip at the target pixel + noise elsewhere)."""

    N = 300
    NT = 2000
    PERIOD, T0, DUR = 10.0, 5.0, 0.1
    TARGET = (7, 7)

    def _rate(self, with_dip, seed):
        rng = np.random.default_rng(seed)
        t = np.linspace(0, 27.0, self.NT)
        ph = ((t - self.T0 + 0.5 * self.PERIOD) % self.PERIOD) \
            - 0.5 * self.PERIOD
        in_m = np.abs(ph) <= self.DUR / 2
        fails = 0
        for _ in range(self.N):
            cube = 1000.0 + 10.0 * rng.standard_normal(
                (self.NT, 15, 15))
            if with_dip:
                cube[in_m, self.TARGET[1], self.TARGET[0]] -= 30.0
            res = pixel_check_native(
                cube, t, self.PERIOD, self.T0, self.DUR,
                self.TARGET)
            if res["verdict"] == "fail":
                fails += 1
        return fails

    def test_pure_noise_null_rate(self):
        # Measured 2026-11-15: 0/300. Bound is 5% (15/300) —
        # far above the nominal 1.2%, far below 25%.
        fails = self._rate(False, 20261115)
        self.assertLess(fails, 0.05 * self.N,
                        msg=f"pure-noise false-fails: {fails}/"
                            f"{self.N}")

    def test_clean_target_null_rate(self):
        # Measured 2026-11-15: 5/300 (1.7%), consistent with
        # the nominal 1.2%. Same 5% bound.
        fails = self._rate(True, 20261116)
        self.assertLess(fails, 0.05 * self.N,
                        msg=f"clean-target false-fails: {fails}/"
                            f"{self.N}")


if __name__ == "__main__":
    unittest.main()
