"""Corrupt-data tests (Phase 1.1, item 9).

Corrupt input must fail GRACEFULLY and LOUDLY: the screen
returns a record with an explicit failure status (error /
too_few_points) and a reason — never a crash, never a survivor,
and never a silent skip. A silently skipped star is the worst
outcome: the run reports success and nobody knows a star was
never screened. _screen_one's contract is that it ALWAYS returns
a record dict with a status; these tests hold it to that on
every corruption class:

  * truncated FITS (cut mid-file) -> error
  * empty table (0 rows) -> too_few_points
  * NaN-only light curve -> too_few_points
  * all cadences quality-flagged -> too_few_points
  * missing flux column -> error (the S98 chunk_00 lesson:
    every star KeyError'd on KSPSAP_FLUX and the run only
    noticed because chunk_ok counts errors)
  * missing file -> error
"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np  # noqa: E402
from astropy.io import fits  # noqa: E402

from bulk_screen import _screen_one  # noqa: E402
from synth_fits import make_qlp_fits, screen_job  # noqa: E402


def _write_fits(path, time, flux, quality, flux_col="KSPSAP_FLUX"):
    cols = [fits.Column(name="TIME", format="D", array=time)]
    if flux_col is not None:
        cols.append(fits.Column(name=flux_col, format="D",
                                array=flux))
    cols.append(fits.Column(name="QUALITY", format="J",
                            array=quality))
    fits.BinTableHDU.from_columns(cols).writeto(path, overwrite=True)


def _base_arrays(n=1296):
    t = 1500.0 + np.arange(n) * 30.0 / 1440.0
    f = np.ones(n)
    q = np.zeros(n, dtype=np.int32)
    return t, f, q


class TestCorruptData(unittest.TestCase):
    def test_truncated_fits_is_error(self):
        with tempfile.TemporaryDirectory() as td:
            good = make_qlp_fits(Path(td) / "good.fits",
                                 period_d=2.5, depth_frac=0.01,
                                 seed=42)
            data = good.read_bytes()
            bad = Path(td) / "trunc.fits"
            bad.write_bytes(data[:len(data) // 2])
            r = _screen_one(screen_job(bad))
            self.assertEqual(r["status"], "error")
            self.assertTrue(r.get("error"))

    def test_empty_table_is_too_few_points(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "empty.fits"
            _write_fits(p, np.array([]), np.array([]),
                        np.array([], dtype=np.int32))
            r = _screen_one(screen_job(p))
            self.assertEqual(r["status"], "too_few_points")

    def test_nan_only_light_curve(self):
        with tempfile.TemporaryDirectory() as td:
            t, _f, q = _base_arrays()
            f = np.full(len(t), np.nan)
            p = Path(td) / "nan.fits"
            _write_fits(p, t, f, q)
            r = _screen_one(screen_job(p))
            self.assertEqual(r["status"], "too_few_points")

    def test_all_cadences_flagged(self):
        with tempfile.TemporaryDirectory() as td:
            t, f, _q = _base_arrays()
            # Quality bit 1 (in the 17087 mask) on every cadence.
            q = np.full(len(t), 1, dtype=np.int32)
            p = Path(td) / "flagged.fits"
            _write_fits(p, t, f, q)
            r = _screen_one(screen_job(p))
            self.assertEqual(r["status"], "too_few_points")

    def test_missing_flux_column_is_error(self):
        with tempfile.TemporaryDirectory() as td:
            t, f, q = _base_arrays()
            p = Path(td) / "noflux.fits"
            _write_fits(p, t, f, q, flux_col=None)
            r = _screen_one(screen_job(p))
            self.assertEqual(r["status"], "error")
            self.assertIn("flux column", r.get("error", ""))

    def test_missing_file_is_error(self):
        with tempfile.TemporaryDirectory() as td:
            r = _screen_one(
                screen_job(Path(td) / "does_not_exist.fits"))
            self.assertEqual(r["status"], "error")
            self.assertTrue(r.get("error"))

    def test_no_case_is_a_silent_skip(self):
        # Every corruption class above returns a RECORD with an
        # explicit failure status — the parent counts it in
        # screen_counts instead of never knowing the star existed.
        # This test re-runs the classes and asserts the invariant
        # directly: status is present and is never survivor.
        with tempfile.TemporaryDirectory() as td:
            good = make_qlp_fits(Path(td) / "good.fits",
                                 period_d=2.5, depth_frac=0.01,
                                 seed=42)
            trunc = Path(td) / "trunc.fits"
            trunc.write_bytes(good.read_bytes()[:1000])
            cases = [trunc, Path(td) / "missing.fits"]
            t, _f, q = _base_arrays()
            nan = Path(td) / "nan.fits"
            _write_fits(nan, t, np.full(len(t), np.nan), q)
            cases.append(nan)
            for path in cases:
                r = _screen_one(screen_job(path))
                self.assertIsNotNone(r)
                self.assertIn("status", r)
                self.assertNotEqual(r["status"], "survivor")
                self.assertIn(r["status"],
                              ("error", "too_few_points"))


if __name__ == "__main__":
    unittest.main()
