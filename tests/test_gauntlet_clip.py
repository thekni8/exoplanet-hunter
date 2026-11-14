"""Behavioural test for the gauntlet MAD-clip floor (C-6 follow-up).

The mutation canary for the MAD-clip floor
(mad_clip.DEFAULT_FLOOR_FRAC — the single definition since
F-11) went red only via the constant-equality test in
test_calibration — no test pinned what the floor DOES. This
test pins the behaviour the floor exists for
(rawflux_check.load_stitched, TIC 139526205 case): a 6%
eclipse on a 0.08%-MAD star is 75 sigma, so an unfloored
5-sigma cut deletes every in-transit point and the star reads
as refuted; the 10% floor keeps the transit while still
clipping genuine outliers (excursions >> 10%).
"""
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gauntlet import rawflux_check  # noqa: E402


def _synthetic_stitched(path, seed=7):
    """One sector npz: quiet star (0.08% noise) + a 6% box
    eclipse (100 points) + 5 lone 50% glitches. Returns the
    in-transit time range."""
    rng = np.random.default_rng(seed)
    t = np.linspace(0.0, 27.0, 2000)
    f = 1.0 + rng.normal(0.0, 0.0008, size=len(t))
    in_transit = (t >= 13.0) & (t < 15.0)
    f[in_transit] = 0.94 + rng.normal(0.0, 0.0008,
                                      size=int(in_transit.sum()))
    glitch_idx = [100, 500, 900, 1500, 1900]
    f[glitch_idx] = 0.5
    np.savez(path, time=t, flux=f)
    return 13.0, 15.0, int(in_transit.sum())


class TestGauntletClipFloor(unittest.TestCase):
    def test_deep_transit_survives_the_clip(self):
        with tempfile.TemporaryDirectory() as td:
            pfx = "testclip"
            t0, t1, n_in = _synthetic_stitched(
                Path(td) / f"{pfx}_s001.npz")
            prev = rawflux_check.DATA
            rawflux_check.DATA = td
            try:
                t, f, spans = rawflux_check.load_stitched(pfx, [1])
            finally:
                rawflux_check.DATA = prev
            self.assertEqual(spans[0][0], 1)
            # The eclipse is n_in points at 0.94: with the 10%
            # floor they survive (0.94 > 1.0 - 0.10); without
            # it the 5-sigma cut (0.004) deletes all of them.
            kept_in_transit = int(
                ((t >= t0) & (t < t1)).sum())
            self.assertGreaterEqual(
                kept_in_transit, n_in - 2,
                msg=f"only {kept_in_transit}/{n_in} in-transit "
                    f"points survived the clip — the floor is "
                    f"not protecting deep transits")
            # ...while the 50% glitches are still clipped.
            self.assertFalse(bool((f < 0.6).any()),
                             msg="lone 50% glitches survived — "
                                 "the clip is not clipping")

    def test_quiet_star_keeps_its_points(self):
        # Sanity: a transit-free quiet star loses ~nothing to
        # the clip (only >5-sigma noise excursions).
        with tempfile.TemporaryDirectory() as td:
            pfx = "quiet"
            rng = np.random.default_rng(11)
            t = np.linspace(0.0, 27.0, 2000)
            f = 1.0 + rng.normal(0.0, 0.0008, size=len(t))
            np.savez(Path(td) / f"{pfx}_s001.npz",
                     time=t, flux=f)
            prev = rawflux_check.DATA
            rawflux_check.DATA = td
            try:
                t2, _f2, _s = rawflux_check.load_stitched(pfx,
                                                          [1])
            finally:
                rawflux_check.DATA = prev
            self.assertGreaterEqual(len(t2), 1990)


if __name__ == "__main__":
    unittest.main()
