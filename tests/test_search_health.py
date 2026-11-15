"""Search-health tests (Phase 3, P3-1 / DF-20).

A degenerate periodogram search must record SEARCH_INVALID, never
pass as a valid search. deep_v1's unmasked BLS went NaN on
heavily-flagged QLP hosts and read as an ordinary non-detection;
the DF-17 census found 0 NaN-SDE rows in the stored ledger, so
the degenerate cases were invisible in the records, not absent
from the searches.

Coverage:
  * assess_periodogram unit tests — every branch, including
    Claude's _robust_sde catch: a systematic-family peak on a
    zero-variance noise floor reads as a HUGE finite SDE via the
    1e-12 fallback scale, and must still be SEARCH_INVALID.
  * Bulk integration: a constant-flux FITS through the real
    _screen_one records status search_invalid (never survivor,
    never below_floor).
  * Deep integration: the real _run_pipeline through the fixture
    seam — a constant-flux curve records SEARCH_INVALID, and a
    signal injected exactly at the grid edge (P = max_p) records
    BOUNDARY_LIMITED, not SEARCH_INVALID (TB-10: a boundary
    peak is a real signal near a boundary, not an invalid
    search). A valid WASP-29b-equivalent injection records
    VALID_DETECTION (the guard that health does not eat real
    signals).

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

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np  # noqa: E402

import bulk_screen as bs  # noqa: E402
import hunter  # noqa: E402
import search_health as sh  # noqa: E402
from synth_fits import make_qlp_fits, screen_job  # noqa: E402
from tests.calibration_guard import DeepCalibrationGuardCase  # noqa: E402

SYSTEMATIC = (13.7, 6.85, 27.4)
HIT_SDE = 8.5
T0 = 1501.0


def _valid_powers(n=2000, seed=7):
    """A realistic periodogram: noisy base + one strong peak
    mid-grid. Returns (periods, powers, peak_index)."""
    rng = np.random.default_rng(seed)
    periods = np.linspace(0.5, 25.0, n)
    powers = 1.0 + rng.normal(0.0, 0.1, n)
    peak = n // 2
    powers[peak] = 5.0
    return periods, powers, peak


class TestAssessPeriodogram(unittest.TestCase):
    def test_valid_detection_above_bar(self):
        periods, powers, peak = _valid_powers()
        status, _ = sh.assess_periodogram(
            powers, periods, peak, 12.0, SYSTEMATIC, HIT_SDE)
        self.assertEqual(status, sh.VALID_DETECTION)

    def test_valid_no_detection_below_bar(self):
        periods, powers, peak = _valid_powers()
        status, _ = sh.assess_periodogram(
            powers, periods, peak, 3.0, SYSTEMATIC, HIT_SDE)
        self.assertEqual(status, sh.VALID_NO_DETECTION)

    def test_nan_powers_invalid(self):
        periods, powers, peak = _valid_powers()
        powers[100] = np.nan
        status, _ = sh.assess_periodogram(
            powers, periods, peak, 12.0, SYSTEMATIC, HIT_SDE)
        self.assertEqual(status, sh.SEARCH_INVALID)

    def test_inf_powers_invalid(self):
        periods, powers, peak = _valid_powers()
        powers[100] = np.inf
        status, _ = sh.assess_periodogram(
            powers, periods, peak, 12.0, SYSTEMATIC, HIT_SDE)
        self.assertEqual(status, sh.SEARCH_INVALID)

    def test_nan_sde_invalid(self):
        periods, powers, peak = _valid_powers()
        status, reason = sh.assess_periodogram(
            powers, periods, peak, float("nan"), SYSTEMATIC, HIT_SDE)
        self.assertEqual(status, sh.SEARCH_INVALID)
        self.assertIn("non-finite SDE", reason)

    def test_empty_periodogram_invalid(self):
        status, _ = sh.assess_periodogram(
            [], [], 0, 0.0, SYSTEMATIC, HIT_SDE)
        self.assertEqual(status, sh.SEARCH_INVALID)

    def test_zero_variance_floor_invalid_despite_huge_sde(self):
        # Claude's _robust_sde catch: the noise floor is all
        # identical (MAD == 0, std == 0), so the robust scale
        # falls back to 1e-12 — and a peak that sits OUTSIDE the
        # noise-floor sample (a systematic-family peak, excluded
        # from the base) reads as a huge FINITE SDE. That is a
        # degenerate search, not a detection.
        periods = np.linspace(0.5, 25.0, 2000)
        powers = np.ones(2000)
        peak = int(np.argmin(np.abs(periods - 13.7)))
        powers[peak] = 5.0
        huge_sde = (5.0 - 1.0) / 1e-12
        status, reason = sh.assess_periodogram(
            powers, periods, peak, huge_sde, SYSTEMATIC, HIT_SDE)
        self.assertEqual(status, sh.SEARCH_INVALID)
        self.assertIn("floating-point level", reason)

    def test_floating_point_scale_floor_invalid_despite_huge_sde(self):
        # The constant-flux case, at the unit level: BLS on
        # constant flux produces ~1e-27 powers (floating-point
        # residue from the detrend, not exactly zero), and the
        # scale-invariant SDE amplifies them to a max SDE of
        # 44.4. The floor scale is ~1e-27, far below
        # DEGENERATE_SCALE_MAX — still SEARCH_INVALID.
        rng = np.random.default_rng(7)
        periods = np.linspace(0.5, 25.0, 2000)
        powers = 1e-27 * (1.0 + rng.normal(0.0, 0.1, 2000))
        peak = 1000
        powers[peak] = 1e-25
        status, reason = sh.assess_periodogram(
            powers, periods, peak, 44.4, SYSTEMATIC, HIT_SDE)
        self.assertEqual(status, sh.SEARCH_INVALID)
        self.assertIn("floating-point level", reason)

    def test_quiet_but_real_floor_is_valid(self):
        # Guard the other side of the threshold: a very quiet
        # star (0.01% noise — quieter than any real TESS star)
        # has a floor scale of ~1.7e-08, four orders above
        # DEGENERATE_SCALE_MAX. It must stay a valid search.
        rng = np.random.default_rng(7)
        periods = np.linspace(0.5, 25.0, 2000)
        powers = 4.6e-08 * (1.0 + rng.normal(0.0, 0.4, 2000))
        peak = 1000
        powers[peak] = 5e-07
        status, _ = sh.assess_periodogram(
            powers, periods, peak, 12.0, SYSTEMATIC, HIT_SDE)
        self.assertEqual(status, sh.VALID_DETECTION)

    def test_all_constant_powers_invalid(self):
        # Constant flux -> BLS powers all 0 -> zero-variance
        # base. The peak index is 0 (argmax of zeros), which is
        # also the grid edge — degenerate beats boundary.
        periods = np.linspace(0.5, 25.0, 2000)
        powers = np.zeros(2000)
        status, _ = sh.assess_periodogram(
            powers, periods, 0, 0.0, SYSTEMATIC, HIT_SDE)
        self.assertEqual(status, sh.SEARCH_INVALID)

    def test_peak_at_first_grid_point_boundary(self):
        periods, powers, _ = _valid_powers()
        powers[0] = 5.0
        powers[len(powers) // 2] = 1.0
        status, _ = sh.assess_periodogram(
            powers, periods, 0, 12.0, SYSTEMATIC, HIT_SDE)
        self.assertEqual(status, sh.BOUNDARY_LIMITED)

    def test_peak_at_last_grid_point_boundary(self):
        periods, powers, _ = _valid_powers()
        powers[-1] = 5.0
        powers[len(powers) // 2] = 1.0
        status, _ = sh.assess_periodogram(
            powers, periods, len(powers) - 1, 12.0, SYSTEMATIC, HIT_SDE)
        self.assertEqual(status, sh.BOUNDARY_LIMITED)

    def test_boundary_is_not_invalid_below_bar(self):
        # A boundary peak below the hit bar is still boundary
        # limited — the search ran, the peak is just at the
        # edge. It is not a valid no-detection either: the
        # search could not look past the edge.
        periods, powers, _ = _valid_powers()
        powers[-1] = 5.0
        powers[len(powers) // 2] = 1.0
        status, _ = sh.assess_periodogram(
            powers, periods, len(powers) - 1, 3.0, SYSTEMATIC, HIT_SDE)
        self.assertEqual(status, sh.BOUNDARY_LIMITED)


class TestBulkSearchInvalid(unittest.TestCase):
    def test_constant_flux_records_search_invalid(self):
        # Constant flux: BLS powers are ~1e-27 floating-point
        # residue, and the scale-invariant SDE amplifies them
        # to a max SDE of 44.4 — above the deep HIT_SDE. Before
        # P3-1 the record proceeded to the vetoes (44.4 is above
        # the record floor) and was only saved by a veto; in the
        # deep pipeline it would have recorded as a hit. Now it
        # stops here.
        with tempfile.TemporaryDirectory() as td:
            path = make_qlp_fits(Path(td) / "const.fits",
                                 period_d=None, noise_pct=0.0)
            rec = bs._screen_one(screen_job(path))
        self.assertEqual(rec["status"], "search_invalid")
        self.assertEqual(rec["search_health"], sh.SEARCH_INVALID)
        self.assertIn("floating-point level", rec["search_health_reason"])

    def test_pure_noise_is_a_valid_search(self):
        # Guard: ordinary noise is a valid search (below the
        # record floor), not search_invalid — the health check
        # must not eat the normal null case.
        with tempfile.TemporaryDirectory() as td:
            path = make_qlp_fits(Path(td) / "noise.fits",
                                 period_d=None, noise_pct=0.003)
            rec = bs._screen_one(screen_job(path))
        self.assertEqual(rec["search_health"], sh.VALID_NO_DETECTION)
        self.assertEqual(rec["status"], "below_floor")


def _times(start=1500.0, ndays=27.0, cadence_min=10.0):
    return start + np.arange(0, ndays, cadence_min / 1440.0)


def _inject_box(t, period, t0, dur, depth):
    f = np.ones_like(t)
    ph = ((t - t0 + 0.5 * period) % period) - 0.5 * period
    f[np.abs(ph) <= dur / 2] -= depth
    return f


def _write_fixture(fixture_dir, tic, t, f, q):
    meta = {"tic": str(tic), "max_sectors": 1, "star_radius": 0.9,
            "n_sectors": 1, "n_points": int(len(t))}
    np.savez_compressed(
        Path(fixture_dir) / f"TIC_{tic}.npz",
        t=np.asarray(t, dtype=float),
        f=np.asarray(f, dtype=float),
        q=np.asarray(q, dtype=np.int64),
        meta_json=json.dumps(meta))


class TestDeepSearchHealth(DeepCalibrationGuardCase):
    """Through the real _run_pipeline, via the fixture seam."""

    def setUp(self):
        super().setUp()
        self._prev_env = os.environ.get("EXHUNT_FIXTURE_DIR")
        self._td = tempfile.TemporaryDirectory()
        os.environ["EXHUNT_FIXTURE_DIR"] = self._td.name

    def tearDown(self):
        if self._prev_env is None:
            os.environ.pop("EXHUNT_FIXTURE_DIR", None)
        else:
            os.environ["EXHUNT_FIXTURE_DIR"] = self._prev_env
        self._td.cleanup()

    def _run(self, tic):
        return hunter._run_pipeline(
            tic, star_radius=0.9, min_p=2.0, max_p=8.0,
            bls_points=8000, max_sectors=None)

    def test_constant_flux_records_search_invalid(self):
        t = _times()
        f = np.ones_like(t)
        _write_fixture(self._td.name, "900000101", t, f,
                       np.zeros(len(t), dtype=np.int64))
        full = self._run("900000101")
        self.assertEqual(full["search_health"], sh.SEARCH_INVALID)
        self.assertEqual(full["pass1_search_health"], sh.SEARCH_INVALID)
        # The JSON metrics carry the health and the
        # classification is never "Strong Transit" for a
        # degenerate search.
        metrics = hunter.full_result_to_json_dict(full)["metrics"]
        self.assertEqual(metrics["search_health"], sh.SEARCH_INVALID)
        self.assertEqual(metrics["classification"], "Search Invalid")

    def test_signal_at_grid_edge_is_boundary_limited(self):
        # Injected exactly at max_p: the coarse grid's last
        # point IS 8.0 d (linspace endpoint), so the coarse
        # argmax pins the grid edge. TB-10: that is a real
        # signal near a boundary, not an invalid search.
        t = _times()
        rng = np.random.default_rng(42)
        f = _inject_box(t, 8.0, T0, 0.105, 0.0114)
        f = f * (1.0 + rng.normal(0, 0.001, len(t)))
        _write_fixture(self._td.name, "900000102", t, f,
                       np.zeros(len(t), dtype=np.int64))
        full = self._run("900000102")
        self.assertEqual(full["search_health"], sh.BOUNDARY_LIMITED)
        self.assertEqual(full["pass1_search_health"],
                         sh.BOUNDARY_LIMITED)

    def test_valid_planet_signal_is_valid_detection(self):
        # Guard: a WASP-29b-equivalent transit (P 3.9227 d,
        # 1.14%) is a valid detection — the health check must
        # not eat real signals.
        t = _times()
        rng = np.random.default_rng(42)
        f = _inject_box(t, 3.9227, T0, 0.105, 0.0114)
        f = f * (1.0 + rng.normal(0, 0.001, len(t)))
        _write_fixture(self._td.name, "900000103", t, f,
                       np.zeros(len(t), dtype=np.int64))
        full = self._run("900000103")
        self.assertEqual(full["search_health"], sh.VALID_DETECTION)
        self.assertGreaterEqual(full["SDE"], hunter.HIT_SDE)


if __name__ == "__main__":
    unittest.main()
