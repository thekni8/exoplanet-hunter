"""S3 QLP fetch tests (P3-9 panel retry fallback, 2026-11-16).

Offline: the URL builder and the FITS->npz converter are pure
functions tested on synthetic files; the download path is
tested against a local HTTP server standing in for S3 (the
module's S3_BASE is monkeypatched). No network leaves the
machine. The live S3 path itself was verified on the Mac
(2026-11-16): real QLP files fetched for all 6 panel targets.
"""
import functools
import http.server
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402
from astropy.io import fits  # noqa: E402

from gauntlet import s3qlp  # noqa: E402


def _synthetic_qlp(path, n=1000, flux_cols=("SYS_RM_FLUX",),
                   flagged=10, bit12=10, nan_flux=5):
    """A minimal QLP-like FITS: TIME/QUALITY + flux columns.

    `flagged` rows carry quality bit 0 (in the deep_v2 mask —
    removed); `bit12` rows carry bit 12 (NOT in the mask —
    kept, the TOI-700 c lesson); `nan_flux` rows have NaN flux
    (removed by the finite filter). Flux columns get distinct
    values so the column-preference test can tell them apart.
    """
    rng = np.random.default_rng(42)
    t = 3907.0 + np.arange(n) * 0.02
    q = np.zeros(n, dtype=np.int64)
    q[:flagged] = 1
    q[flagged:flagged + bit12] = 4096
    cols = [fits.Column(name="TIME", format="D", array=t),
            fits.Column(name="QUALITY", format="J", array=q)]
    for i, c in enumerate(flux_cols):
        f = 1.0 + 0.001 * rng.standard_normal(n) + 0.1 * i
        f[-nan_flux:] = np.nan
        cols.append(fits.Column(name=c, format="D", array=f))
    hdu = fits.BinTableHDU.from_columns(cols)
    hdu.writeto(path, overwrite=True)
    return n - flagged - nan_flux  # expected good points


class TestUrl(unittest.TestCase):
    def test_verified_example(self):
        # The parent's verified example (2026-11-16 07:48 IST).
        self.assertEqual(
            s3qlp.qlp_s3_url(2733031, 96),
            "https://stpubdata.s3.us-east-1.amazonaws.com/mast/hlsp/qlp"
            "/s0096/0000/0000/0273/3031/"
            "hlsp_qlp_tess_ffi_s0096-0000000002733031_tess_v01_llc.fits")

    def test_panel_target(self):
        # TIC 27966179 S96 — downloaded and verified 2026-11-16.
        self.assertEqual(
            s3qlp.qlp_s3_url(27966179, 96),
            "https://stpubdata.s3.us-east-1.amazonaws.com/mast/hlsp/qlp"
            "/s0096/0000/0000/2796/6179/"
            "hlsp_qlp_tess_ffi_s0096-0000000027966179_tess_v01_llc.fits")

    def test_nine_digit_tic_shards(self):
        url = s3qlp.qlp_s3_url(209310912, 28)
        self.assertIn("/0000/0002/0931/0912/", url)
        self.assertIn("s0028-0000000209310912_tess_v01_llc.fits", url)

    def test_sector_zero_padding(self):
        self.assertIn("/s0002/", s3qlp.qlp_s3_url(12999193, 2))
        self.assertIn("/s0107/", s3qlp.qlp_s3_url(12999193, 107))


class TestFitsToNpz(unittest.TestCase):
    def test_kspsap_preferred(self):
        with tempfile.TemporaryDirectory() as d:
            fp = os.path.join(d, "a.fits")
            n_good = _synthetic_qlp(
                fp, flux_cols=("KSPSAP_FLUX", "SYS_RM_FLUX"))
            npz = os.path.join(d, "a.npz")
            n = s3qlp.qlp_fits_to_npz(fp, npz)
            self.assertEqual(n, n_good)
            z = np.load(npz)
            # KSPSAP_FLUX is the first column (offset 0.0);
            # SYS_RM_FLUX carries +0.1 — the npz must match KSPSAP.
            self.assertAlmostEqual(float(np.median(z["flux"])), 1.0,
                                   delta=0.01)

    def test_sysrm_fallback(self):
        # The real S96 file has no KSPSAP_FLUX (verified
        # 2026-11-16) — SYS_RM_FLUX is the column load_fits picks.
        with tempfile.TemporaryDirectory() as d:
            fp = os.path.join(d, "a.fits")
            n_good = _synthetic_qlp(fp, flux_cols=("SYS_RM_FLUX",))
            npz = os.path.join(d, "a.npz")
            n = s3qlp.qlp_fits_to_npz(fp, npz)
            self.assertEqual(n, n_good)
            z = np.load(npz)
            self.assertEqual(len(z["time"]), n_good)
            self.assertEqual(z["flux"].dtype, np.float32)

    def test_mask_semantics(self):
        # Bit-0 rows removed, bit-12 rows kept, NaN flux removed.
        with tempfile.TemporaryDirectory() as d:
            fp = os.path.join(d, "a.fits")
            n_good = _synthetic_qlp(fp, n=1000, flagged=10,
                                    bit12=10, nan_flux=5)
            npz = os.path.join(d, "a.npz")
            n = s3qlp.qlp_fits_to_npz(fp, npz)
            # 1000 - 10 (bit 0) - 5 (NaN) = 985; the 10 bit-12
            # rows survive.
            self.assertEqual(n, 985)
            self.assertEqual(n, n_good)

    def test_too_few_points(self):
        with tempfile.TemporaryDirectory() as d:
            fp = os.path.join(d, "a.fits")
            _synthetic_qlp(fp, n=50, flagged=0, bit12=0,
                           nan_flux=0)
            with self.assertRaises(ValueError):
                s3qlp.qlp_fits_to_npz(fp, os.path.join(d, "a.npz"))

    def test_no_flux_column(self):
        with tempfile.TemporaryDirectory() as d:
            fp = os.path.join(d, "a.fits")
            t = 3907.0 + np.arange(500) * 0.02
            q = np.zeros(500, dtype=np.int64)
            hdu = fits.BinTableHDU.from_columns([
                fits.Column(name="TIME", format="D", array=t),
                fits.Column(name="QUALITY", format="J", array=q)])
            hdu.writeto(fp, overwrite=True)
            with self.assertRaises(ValueError):
                s3qlp.qlp_fits_to_npz(fp, os.path.join(d, "a.npz"))


class _LocalS3:
    """A local HTTP server standing in for S3 (offline tests)."""

    def __init__(self, root):
        handler = functools.partial(
            http.server.SimpleHTTPRequestHandler, directory=root)
        self.httpd = http.server.ThreadingHTTPServer(
            ("127.0.0.1", 0), handler)
        self.thread = threading.Thread(
            target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.base = (f"http://127.0.0.1:"
                     f"{self.httpd.server_address[1]}"
                     f"/mast/hlsp/qlp")

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)


class TestFetch(unittest.TestCase):
    def test_skips_existing_npz_without_network(self):
        # A cached npz short-circuits before any download: point
        # S3_BASE at an unroutable address — if the fetch tried
        # the network, it would fail.
        with tempfile.TemporaryDirectory() as d:
            np.savez_compressed(
                os.path.join(d, "qlp_s096.npz"),
                time=np.arange(200, dtype=float),
                flux=np.ones(200, dtype=np.float32))
            orig = s3qlp.S3_BASE
            s3qlp.S3_BASE = "http://127.0.0.1:1/nowhere"
            try:
                got = s3qlp.fetch_qlp_s3(27966179, [96], d)
            finally:
                s3qlp.S3_BASE = orig
            self.assertEqual(got, [96])

    def test_download_and_convert(self):
        with tempfile.TemporaryDirectory() as root:
            # Lay out the S3 path inside the fake bucket.
            rel = ("mast/hlsp/qlp/s0096/0000/0000/2796/6179/"
                   "hlsp_qlp_tess_ffi_s0096-0000000027966179"
                   "_tess_v01_llc.fits")
            fp = os.path.join(root, rel)
            os.makedirs(os.path.dirname(fp), exist_ok=True)
            n_good = _synthetic_qlp(fp)
            srv = _LocalS3(root)
            try:
                orig = s3qlp.S3_BASE
                s3qlp.S3_BASE = srv.base
                try:
                    with tempfile.TemporaryDirectory() as d:
                        got = s3qlp.fetch_qlp_s3(27966179, [96], d)
                        self.assertEqual(got, [96])
                        # FITS kept for audit, npz converted.
                        self.assertTrue(os.path.exists(
                            os.path.join(d, "qlp_s096.fits")))
                        z = np.load(os.path.join(d, "qlp_s096.npz"))
                        self.assertEqual(len(z["time"]), n_good)
                finally:
                    s3qlp.S3_BASE = orig
            finally:
                srv.close()

    def test_404_sector_skipped(self):
        with tempfile.TemporaryDirectory() as root:
            srv = _LocalS3(root)
            try:
                orig = s3qlp.S3_BASE
                s3qlp.S3_BASE = srv.base
                try:
                    with tempfile.TemporaryDirectory() as d:
                        # No file laid out -> 404 -> skipped.
                        got = s3qlp.fetch_qlp_s3(27966179, [96], d,
                                                 attempts=1)
                        self.assertEqual(got, [])
                        self.assertFalse(os.path.exists(
                            os.path.join(d, "qlp_s096.npz")))
                finally:
                    s3qlp.S3_BASE = orig
            finally:
                srv.close()


if __name__ == "__main__":
    unittest.main()
