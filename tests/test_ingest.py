"""Shared float64 ingest tests (Phase 1.2 follow-up F-4).

One ingest function (ingest.py) normalises time/flux/flux_err
to float64 at the FITS-read boundary, used by hunter, the bulk
screen, and both gauntlet fetch paths (_fetch_stitched,
_fetch_flattened). The C-4 failure was dtype-dependent numerics:
FITS flux is typically float32, scipy's savgol accumulates in
the input dtype, and the live/fixture trends differed by ~4e-7
— enough to flip a BLS argmax on a near-tie.

  * as_float64 / normalise_lightcurve convert exactly (the
    upcast loses no value) and preserve flux_err;
  * the gauntlet detrender (lightkurve flatten) gives
    bit-identical output for float32 vs float64 inputs once
    both pass through the shared ingest;
  * assert_float64 fails loudly on a float32 array at
    detrend/BLS entry;
  * the fetchers are wired: _fetch_stitched and
    _fetch_flattened return float64 curves even when the
    downloaded products are float32 (mocked download — no
    network, no fixture seam).

No downloads anywhere: the fetcher tests mock the download
boundary itself.
"""
import sys
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import ingest  # noqa: E402
import hunter  # noqa: E402
import lightkurve as lk  # noqa: E402


def _synthetic_lc(dtype=np.float32, n=500, seed=3):
    """A 500-point light curve with a 1% box dip (period 2.17 d).
    TIME is always float64 (the detrend window is in points, and
    float32 would round the BTJD values before the upcast could
    save them — the dtype question under test is the FLUX, the
    savgol input). The flux is built in float32 FIRST and
    upcast for the float64 variant — like the real fixtures,
    which store the live float32 values upcast exactly — so
    both variants hold IDENTICAL values and only the dtype
    differs. That is the C-4 situation: same values, different
    storage dtype, and the detrend must not care."""
    rng = np.random.default_rng(seed)
    t = 1500.0 + np.arange(n) * (2.0 / 1440.0)
    ph = (((t - 1500.5) / 2.17 + 0.5) % 1.0) - 0.5
    in_tr = np.abs(ph) < 0.5 * 0.1 / 2.17
    f = np.ones(n) - 0.01 * in_tr + rng.normal(0, 0.002, n)
    f32 = f.astype(np.float32)
    ferr32 = np.full(n, 0.002, dtype=np.float32)
    f_out = f32 if dtype == np.float32 else f32.astype(np.float64)
    ferr_out = (ferr32 if dtype == np.float32
                else ferr32.astype(np.float64))
    return lk.LightCurve(time=t, flux=f_out, flux_err=ferr_out)


class TestAsFloat64(unittest.TestCase):
    def test_converts_float32_exactly(self):
        t32 = np.array([1500.0, 1500.5], dtype=np.float32)
        f32 = np.array([1.0, 0.99], dtype=np.float32)
        t, f, ferr = ingest.as_float64(t32, f32)
        self.assertEqual(t.dtype, np.float64)
        self.assertEqual(f.dtype, np.float64)
        self.assertIsNone(ferr)
        np.testing.assert_array_equal(t, t32.astype(np.float64))
        np.testing.assert_array_equal(f, f32.astype(np.float64))

    def test_flux_err_converted_and_preserved(self):
        t, f, ferr = ingest.as_float64(
            [1500.0], [1.0],
            np.array([0.002], dtype=np.float32))
        self.assertEqual(ferr.dtype, np.float64)
        self.assertAlmostEqual(float(ferr[0]), 0.002, places=6)

    def test_float64_input_is_unchanged(self):
        t = np.array([1500.0], dtype=np.float64)
        f = np.array([1.0], dtype=np.float64)
        t2, f2, _ = ingest.as_float64(t, f)
        np.testing.assert_array_equal(t2, t)
        np.testing.assert_array_equal(f2, f)


class TestNormaliseLightcurve(unittest.TestCase):
    def test_float32_curve_becomes_float64(self):
        lc = _synthetic_lc(dtype=np.float32)
        out = ingest.normalise_lightcurve(lc)
        self.assertEqual(out.time.value.dtype, np.float64)
        self.assertEqual(out.flux.value.dtype, np.float64)
        self.assertEqual(out.flux_err.value.dtype, np.float64)
        np.testing.assert_array_equal(
            out.flux.value, lc.flux.value.astype(np.float64))

    def test_curve_without_flux_err_stays_without(self):
        lc = lk.LightCurve(time=np.array([1500.0], dtype=np.float32),
                           flux=np.array([1.0], dtype=np.float32))
        out = ingest.normalise_lightcurve(lc)
        self.assertEqual(out.flux.value.dtype, np.float64)
        # lightkurve always materialises flux_err (NaN when the
        # input carries none) — the point is no REAL errors are
        # invented: the output's flux_err is all-NaN.
        self.assertTrue(np.all(np.isnan(out.flux_err.value)))


class TestDetrenderDtypeInsensitive(unittest.TestCase):
    def test_float32_vs_float64_flatten_identical(self):
        # The C-4 failure, replayed through the shared ingest:
        # the same curve in float32 and float64 must detrend to
        # bit-identical output once both pass through ingest.
        lc32 = _synthetic_lc(dtype=np.float32)
        lc64 = _synthetic_lc(dtype=np.float64)
        flat32 = ingest.normalise_lightcurve(lc32).flatten(
            window_length=101)
        flat64 = ingest.normalise_lightcurve(lc64).flatten(
            window_length=101)
        np.testing.assert_array_equal(flat32.time.value,
                                      flat64.time.value)
        np.testing.assert_array_equal(flat32.flux.value,
                                      flat64.flux.value)

    def test_assert_float64_raises_on_float32(self):
        t32 = np.array([1500.0], dtype=np.float32)
        f64 = np.array([1.0], dtype=np.float64)
        with self.assertRaises(TypeError) as ctx:
            ingest.assert_float64(t32, f64, "test entry")
        self.assertIn("test entry", str(ctx.exception))
        self.assertIn("float32", str(ctx.exception))
        # float64 passes silently.
        ingest.assert_float64(f64, f64, "test entry")


class TestFetcherWiring(unittest.TestCase):
    """The gauntlet fetch paths return float64 even when the
    downloaded products are float32. The download boundary is
    mocked (no network, no fixture seam): _select_products
    returns a fake sector list and _download_products returns a
    LightCurveCollection of float32 curves."""

    def _mocked_fetch(self):
        coll = lk.LightCurveCollection(
            [_synthetic_lc(dtype=np.float32, seed=3),
             _synthetic_lc(dtype=np.float32, seed=4)])
        patches = [
            mock.patch.object(hunter, "_select_products",
                              return_value=["fake-sector"]),
            mock.patch.object(hunter, "_download_products",
                              return_value=coll),
        ]
        for p in patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in patches])

    def test_fetch_stitched_returns_float64(self):
        self._mocked_fetch()
        lc_raw, n_sectors = hunter._fetch_stitched("238620464")
        self.assertEqual(n_sectors, 2)
        self.assertEqual(lc_raw.time.value.dtype, np.float64)
        self.assertEqual(lc_raw.flux.value.dtype, np.float64)
        self.assertGreater(len(lc_raw), 0)

    def test_fetch_flattened_returns_float64(self):
        self._mocked_fetch()
        t, f, n_sectors, total = hunter._fetch_flattened(
            "238620464")
        self.assertEqual(n_sectors, 2)
        self.assertEqual(t.dtype, np.float64)
        self.assertEqual(f.dtype, np.float64)
        self.assertEqual(total, len(t))  # flatten keeps length
        self.assertGreater(len(t), 0)

    def test_fetch_raw_returns_float64(self):
        self._mocked_fetch()
        t, f, _n, _total = hunter._fetch_raw("238620464")
        self.assertEqual(t.dtype, np.float64)
        self.assertEqual(f.dtype, np.float64)


if __name__ == "__main__":
    unittest.main()
