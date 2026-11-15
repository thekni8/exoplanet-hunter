"""Deep-pipeline quality-mask tests (deep_v2).

M-11 verified hunter.py was exposed the same way as the bulk
screen: lightkurve downloads with no explicit quality_bitmask
keep TESS scattered-light bits 29/30 on QLP targets (the
majority). deep_v2 masks bits 29/30 at pipeline input
(quality_mask 1610629823 = lightkurve default 17087 + bits
29/30, the same integer as bulk_v3).

The pipeline tests run the REAL _run_pipeline through the
fixture seam (EXHUNT_FIXTURE_DIR) on synthetic stitched curves
with a QUALITY column (the deep_v2 fixture extension). Each
asserts BOTH halves: under deep_v1 the artifact is found (the
failure reproduction — if the fixture ever stops promoting
under v1, the test fails on the v1 half, not vacuously on v2)
and under deep_v2 it is not a hit.

The gauntlet tests run the REAL gates: download_author with a
mocked MAST download (bit-12 transit must survive the fetch
filter and measure in raw flux), and load_tpf with a stubbed
lk.read (bit-12 cadences kept in the pixel work).

Note: _run_pipeline renders a PNG and logs discoveries.csv per
call (original behaviour, preserved deliberately) — the PNGs
land in the repo's gitignored reports/ dir, as in the golden
fixture tests.
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import lightkurve as lk  # noqa: E402
import numpy as np  # noqa: E402

import hunter  # noqa: E402
import quality_flags as qf  # noqa: E402
from gauntlet import common as gcommon  # noqa: E402
from gauntlet import rawflux_check as rfc  # noqa: E402
from tests.calibration_guard import DeepCalibrationGuardCase  # noqa: E402

WASP29B_PERIOD = 3.9227
WASP29B_DEPTH = 0.0114
T0 = 1501.0
DUR_D = 0.105


def _times(start=1500.0, ndays=27.0, cadence_min=10.0):
    return start + np.arange(0, ndays, cadence_min / 1440.0)


def _inject_box(t, period, t0, dur, depth):
    """Box transit train multiplied into ones."""
    f = np.ones_like(t)
    ph = ((t - t0 + 0.5 * period) % period) - 0.5 * period
    f[np.abs(ph) <= dur / 2] -= depth
    return f


def _write_fixture(fixture_dir, tic, t, f, q):
    """A stitched-curve fixture npz (t, f, q, meta_json) in the
    EXHUNT_FIXTURE_DIR layout. q is the deep_v2 fixture
    extension — the stitched QUALITY column."""
    meta = {"tic": str(tic), "max_sectors": 1, "star_radius": 0.9,
            "n_sectors": 1, "n_points": int(len(t))}
    np.savez_compressed(
        Path(fixture_dir) / f"TIC_{tic}.npz",
        t=np.asarray(t, dtype=float),
        f=np.asarray(f, dtype=float),
        q=np.asarray(q, dtype=np.int64),
        meta_json=json.dumps(meta))


def _make_fixture(fixture_dir, tic, period=WASP29B_PERIOD,
                  depth=WASP29B_DEPTH, flag_bit=None,
                  flag_where="in_transit", noise_pct=0.001,
                  seed=42):
    """Synthetic single-sector stitched curve with a transit.
    flag_bit: QUALITY bit to set on in-transit (flag_where=
    'in_transit') or out-of-transit cadences; None = clean."""
    rng = np.random.default_rng(seed)
    t = _times()
    f = _inject_box(t, period, T0, DUR_D, depth)
    f = f * (1.0 + rng.normal(0, noise_pct, len(t)))
    ph = ((t - T0 + 0.5 * period) % period) - 0.5 * period
    in_tr = np.abs(ph) <= DUR_D / 2
    q = np.zeros(len(t), dtype=np.int64)
    if flag_bit is not None:
        if flag_where == "in_transit":
            q[in_tr] = np.int64(1 << flag_bit)
        else:
            q[~in_tr] = np.int64(1 << flag_bit)
    _write_fixture(fixture_dir, tic, t, f, q)
    return t, f, q


class TestApplyQualityMask(unittest.TestCase):
    def test_mask_removes_flagged_keeps_bit12(self):
        # Unit test of the helper: bit-30 and bit-0 rows are
        # removed under deep_v2; bit-12 rows (TOI-700 c) stay.
        t = np.arange(5, dtype=float)
        f = np.ones(5)
        q = np.array([0, 1 << 30, 4096, 1 << 29, 1], dtype=np.int64)
        lc = lk.LightCurve(time=t, flux=f, quality=q)
        out = hunter._apply_quality_mask(lc, qf.DEEP_V2_MASK)
        self.assertEqual(len(out), 2)
        np.testing.assert_array_equal(
            np.asarray(out.time.value), [0.0, 2.0])

    def test_mask_v1_keeps_bit30(self):
        # Under deep_v1 (17087) the scattered-light cadences
        # survive — the exposure deep_v2 closes.
        t = np.arange(3, dtype=float)
        f = np.ones(3)
        q = np.array([0, 1 << 30, 1 << 29], dtype=np.int64)
        lc = lk.LightCurve(time=t, flux=f, quality=q)
        out = hunter._apply_quality_mask(lc, qf.DEEP_V1_MASK)
        self.assertEqual(len(out), 3)

    def test_no_quality_column_passes_through(self):
        # Fixtures built before the deep_v2 seam and HLSP
        # products without QUALITY: nothing to mask, no-op.
        lc = lk.LightCurve(time=np.arange(4, dtype=float),
                           flux=np.ones(4))
        out = hunter._apply_quality_mask(lc)
        self.assertEqual(len(out), 4)

    def test_uint16_quality_does_not_overflow(self):
        # DF-5 (Gemini's catch): SPOC QUALITY columns are 16-bit,
        # and a bare uint16 & 1610629823 raises OverflowError
        # under numpy 2.x. The int64 cast is the defence — this
        # pins it, with exact row drops. A 16-bit column can only
        # carry bits 0-15: bit 0 and bit 14 are in the SPOC
        # default mask, bit 12 is not.
        t = np.arange(5, dtype=float)
        f = np.ones(5)
        q = np.array([0, 1, 4096, 16384, 0], dtype=np.uint16)
        lc = lk.LightCurve(time=t, flux=f, quality=q)
        out = hunter._apply_quality_mask(lc, qf.DEEP_V2_MASK)
        self.assertEqual(len(out), 3)
        np.testing.assert_array_equal(
            np.asarray(out.time.value), [0.0, 2.0, 4.0])

    def test_masked_array_quality_drops_masked_entries(self):
        # DF-5 (Claude's edge case): a masked quality entry has
        # unknown flags — unknown quality is not clean, so the
        # cadence is dropped. Unmasked entries mask normally.
        t = np.arange(5, dtype=float)
        f = np.ones(5)
        q = np.ma.array([0, 1 << 30, 4096, 1, 0],
                        mask=[False, True, False, True, False],
                        dtype=np.int64)
        lc = lk.LightCurve(time=t, flux=f, quality=q)
        out = hunter._apply_quality_mask(lc, qf.DEEP_V2_MASK)
        self.assertEqual(len(out), 3)
        np.testing.assert_array_equal(
            np.asarray(out.time.value), [0.0, 2.0, 4.0])

    def test_none_quality_column_passes_through(self):
        # DF-5 (Claude's edge case): a quality column of None
        # carries no flag information — the curve passes through
        # unchanged, like a curve with no quality column. (The
        # pre-DF-5 code crashed here with TypeError.) Both
        # constructor forms: an object array of Nones, and
        # quality=None.
        t = np.arange(4, dtype=float)
        f = np.ones(4)
        lc = lk.LightCurve(time=t, flux=f,
                           quality=np.array([None] * 4,
                                            dtype=object))
        out = hunter._apply_quality_mask(lc, qf.DEEP_V2_MASK)
        self.assertEqual(len(out), 4)
        lc_none = lk.LightCurve(time=t, flux=f, quality=None)
        out_none = hunter._apply_quality_mask(lc_none,
                                              qf.DEEP_V2_MASK)
        self.assertEqual(len(out_none), 4)

    def test_nan_flux_with_valid_quality(self):
        # DF-5 (Claude's edge case): NaN flux alongside valid
        # quality — the mask drops flagged rows only; a NaN-flux
        # cadence with clean quality is kept (NaN flux is the
        # downstream finite filter's job, not the mask's).
        t = np.arange(5, dtype=float)
        f = np.array([1.0, np.nan, 1.0, 1.0, 1.0])
        q = np.array([0, 0, 1 << 30, 0, 0], dtype=np.int64)
        lc = lk.LightCurve(time=t, flux=f, quality=q)
        out = hunter._apply_quality_mask(lc, qf.DEEP_V2_MASK)
        self.assertEqual(len(out), 4)
        np.testing.assert_array_equal(
            np.asarray(out.time.value), [0.0, 1.0, 3.0, 4.0])
        self.assertTrue(np.isnan(out.flux.value).any())


class TestDeepQualityMaskPipeline(DeepCalibrationGuardCase):
    """Through the real _run_pipeline, via the fixture seam."""

    def setUp(self):
        super().setUp()
        self._prev_env = os.environ.get("EXHUNT_FIXTURE_DIR")
        self._td = tempfile.TemporaryDirectory()
        os.environ["EXHUNT_FIXTURE_DIR"] = self._td.name

    def tearDown(self):
        # No manual calibration restore: _run switches through
        # calibration_context, which restores in a finally
        # block; the guard base class asserts deep_v2 is back
        # after every test.
        if self._prev_env is None:
            os.environ.pop("EXHUNT_FIXTURE_DIR", None)
        else:
            os.environ["EXHUNT_FIXTURE_DIR"] = self._prev_env
        self._td.cleanup()

    def _run(self, tic, calibration):
        with hunter.calibration_context(calibration):
            return hunter._run_pipeline(
                tic, star_radius=0.9, min_p=2.0, max_p=8.0,
                bls_points=8000, max_sectors=None)

    def test_flagged_artifact_found_under_v1_gone_under_v2(self):
        # The core regression: a dip living ONLY on bit-30
        # cadences (the 2026-11-14 rescore artifact class) is a
        # hit under deep_v1 and not a hit under deep_v2.
        _make_fixture(self._td.name, "900000001",
                      period=WASP29B_PERIOD, depth=0.02,
                      flag_bit=30)
        v1 = self._run("900000001", "deep_v1")
        self.assertAlmostEqual(v1["Period"], WASP29B_PERIOD,
                               delta=0.01 * WASP29B_PERIOD)
        self.assertGreaterEqual(v1["SDE"], hunter.HIT_SDE)
        v2 = self._run("900000001", "deep_v2")
        self.assertLess(v2["SDE"], hunter.HIT_SDE)

    def test_bit12_transit_survives_under_v2(self):
        # Selectivity guard: bit 12 (4096) is NOT in the mask —
        # TOI-700 c's transit sits on bit-12 cadences, and
        # masking them would delete real planets.
        _make_fixture(self._td.name, "900000002",
                      period=WASP29B_PERIOD, depth=WASP29B_DEPTH,
                      flag_bit=12)
        for cal in ("deep_v1", "deep_v2"):
            r = self._run("900000002", cal)
            self.assertAlmostEqual(r["Period"], WASP29B_PERIOD,
                                   delta=0.01 * WASP29B_PERIOD,
                                   msg=cal)
            self.assertGreaterEqual(r["SDE"], hunter.HIT_SDE,
                                    msg=cal)

    def test_clean_transit_survives_under_v2(self):
        # Sensitivity guard: a clean WASP-29b-equivalent transit
        # is found under both calibrations.
        _make_fixture(self._td.name, "900000003",
                      period=WASP29B_PERIOD, depth=WASP29B_DEPTH)
        for cal in ("deep_v1", "deep_v2"):
            r = self._run("900000003", cal)
            self.assertAlmostEqual(r["Period"], WASP29B_PERIOD,
                                   delta=0.01 * WASP29B_PERIOD,
                                   msg=cal)
            self.assertGreaterEqual(r["SDE"], hunter.HIT_SDE,
                                    msg=cal)


class TestGauntletMaskGates(unittest.TestCase):
    """Through the real gauntlet gates (M-8 fixes)."""

    def test_rawflux_bit12_transit_not_refuted(self):
        # A genuine bit-12 transit must survive the raw-flux
        # fetch filter and measure in raw flux — under the old
        # quality==0 filter it lost every in-transit cadence and
        # read RAW-REFUTED. The old semantics are reproduced
        # with quality_mask=all-bits (drop every flagged
        # cadence = quality==0); the new default keeps them.
        from astropy.table import Table

        t = _times()
        f = _inject_box(t, WASP29B_PERIOD, T0, DUR_D, 0.02)
        f = f * (1.0 + np.random.default_rng(7).normal(
            0, 0.001, len(t)))
        ph = ((t - T0 + 0.5 * WASP29B_PERIOD) % WASP29B_PERIOD) \
            - 0.5 * WASP29B_PERIOD
        in_tr = np.abs(ph) <= DUR_D / 2
        q = np.where(in_tr, np.int64(4096),
                     np.int64(0)).astype(np.int64)
        lc = lk.LightCurve(time=t, flux=f, quality=q)

        class _Row:
            def download(self):
                return lc

        class _SearchResult:
            def __init__(self):
                self.table = Table(
                    {"sequence_number": [96], "exptime": [120.0]})

            def __len__(self):
                return 1

            def __getitem__(self, i):
                return _Row()

        prev_data = rfc.DATA
        try:
            with tempfile.TemporaryDirectory() as td:
                with mock.patch.object(
                        lk, "search_lightcurve",
                        return_value=_SearchResult()):
                    # New default (deep_v2): bit-12 cadences kept.
                    got = rfc.download_author(
                        "QLP", "qlp", tic="900000004",
                        data_dir=td)
                self.assertEqual(got, [96])
                rfc.DATA = td
                m = rfc.raw_measure("qlp", [96], WASP29B_PERIOD,
                                    T0, DUR_D)
                self.assertIsNotNone(m.get("signif"))
                self.assertGreater(m["signif"], 3.0)
                self.assertAlmostEqual(m["depth_pct"], 2.0,
                                       delta=0.5)
                # Old semantics (quality==0): in-transit cadences
                # dropped, no dip measurable.
                with tempfile.TemporaryDirectory() as td_old:
                    with mock.patch.object(
                            lk, "search_lightcurve",
                            return_value=_SearchResult()):
                        got_old = rfc.download_author(
                            "QLP", "qlp", tic="900000004",
                            data_dir=td_old,
                            quality_mask=0xFFFFFFFF)
                    self.assertEqual(got_old, [96])
                    rfc.DATA = td_old
                    m_old = rfc.raw_measure("qlp", [96],
                                            WASP29B_PERIOD, T0,
                                            DUR_D)
                    # No significant dip: the transit was
                    # filtered out before the fold.
                    self.assertTrue(
                        m_old.get("signif") is None
                        or m_old["signif"] < 3.0)
        finally:
            rfc.DATA = prev_data

    def test_load_tpf_keeps_bit12_cadences(self):
        # load_tpf through the real function (only lk.read is
        # stubbed — building a lightkurve-parseable TPF FITS
        # from scratch is out of proportion; the test_desk.py
        # precedent). Bit-12 cadences stay, bit-30 go.
        t = np.arange(100, dtype=float)
        cube = np.ones((100, 5, 5))
        q = np.zeros(100, dtype=np.int64)
        q[10:30] = np.int64(4096)       # bit 12
        q[50:70] = np.int64(1 << 30)    # bit 30
        fake_tpf = SimpleNamespace(
            quality=q,
            time=SimpleNamespace(value=t),
            flux=SimpleNamespace(value=cube))
        with mock.patch.object(lk, "read",
                               return_value=fake_tpf):
            tt, flux, _tpf = gcommon.load_tpf("fake.fits")
        # 100 - 20 bit-30 cadences; the 20 bit-12 cadences stay.
        self.assertEqual(len(tt), 80)
        self.assertEqual(flux.shape, (80, 5, 5))
        np.testing.assert_array_equal(
            np.asarray(tt), np.concatenate([t[:50], t[70:]]))
        # Old semantics (quality==0): bit-12 cadences dropped too.
        with mock.patch.object(lk, "read",
                               return_value=fake_tpf):
            tt_old, _f, _t = gcommon.load_tpf(
                "fake.fits", quality_mask=0xFFFFFFFF)
        self.assertEqual(len(tt_old), 60)

    def test_rawflux_uint16_quality(self):
        # DF-5 through the rawflux site: a SPOC 16-bit QUALITY
        # column must not crash the fetch filter (the int64 cast
        # is the defence) and must drop exactly the masked rows.
        # Same mocked-MAST pattern as the bit-12 test above.
        from astropy.table import Table

        n = 500
        t = 1500.0 + np.arange(n) * (10.0 / 1440.0)
        f = np.ones(n)
        q = np.zeros(n, dtype=np.uint16)
        q[0:100] = np.uint16(1)       # bit 0: masked
        q[100:200] = np.uint16(4096)  # bit 12: kept
        lc = lk.LightCurve(time=t, flux=f, quality=q)

        class _Row:
            def download(self):
                return lc

        class _SearchResult:
            def __init__(self):
                self.table = Table(
                    {"sequence_number": [96], "exptime": [120.0]})

            def __len__(self):
                return 1

            def __getitem__(self, i):
                return _Row()

        prev_data = rfc.DATA
        try:
            with tempfile.TemporaryDirectory() as td:
                with mock.patch.object(
                        lk, "search_lightcurve",
                        return_value=_SearchResult()):
                    got = rfc.download_author(
                        "QLP", "qlp", tic="900000005",
                        data_dir=td)
                self.assertEqual(got, [96])
                z = np.load(os.path.join(td, "qlp_s096.npz"))
                # 500 - 100 bit-0 cadences; the 100 bit-12
                # cadences stay.
                self.assertEqual(len(z["time"]), 400)
        finally:
            rfc.DATA = prev_data

    def test_load_tpf_uint16_quality(self):
        # DF-5 through the load_tpf site: a SPOC 16-bit QUALITY
        # column must not crash the pixel work and must drop
        # exactly the masked cadences. Same stubbed-lk.read
        # pattern as the bit-12 test above.
        t = np.arange(100, dtype=float)
        cube = np.ones((100, 5, 5))
        q = np.zeros(100, dtype=np.uint16)
        q[10:30] = np.uint16(4096)   # bit 12: kept
        q[50:70] = np.uint16(1)      # bit 0: masked
        fake_tpf = SimpleNamespace(
            quality=q,
            time=SimpleNamespace(value=t),
            flux=SimpleNamespace(value=cube))
        with mock.patch.object(lk, "read",
                               return_value=fake_tpf):
            tt, flux, _tpf = gcommon.load_tpf("fake.fits")
        self.assertEqual(len(tt), 80)
        self.assertEqual(flux.shape, (80, 5, 5))
        np.testing.assert_array_equal(
            np.asarray(tt), np.concatenate([t[:50], t[70:]]))


if __name__ == "__main__":
    unittest.main()
