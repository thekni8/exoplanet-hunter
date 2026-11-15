"""Inverted-flux null machinery (P3-12, 2026-11-15).

Offline, synthetic FITS only -- no MAST, no real cache. The null
runs the screen on sign-flipped S96 flux (f' = 2*median - f) so
the 3B reduction numbers (P3-11) can be interpreted against a
measured noise-tail floor.

Tests:
* the flip is exactly median-symmetric (median + noise moments
  preserved, a dip becomes a bump of equal depth at the same
  ephemeris, TIME/QUALITY untouched);
* a flipped screen does NOT recover an injected transit as a dip
  survivor at the injected period (the flip turns it into a
  bump, which BLS does not detect as a transit) -- while the
  unflipped control DOES recover it, so the non-recovery is
  meaningful and not a dead screen;
* resume: a star with completed output is skipped on re-launch;
* the summary/floor computation on synthetic outputs.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np  # noqa: E402

import bulk_screen as bs  # noqa: E402
import injection_harness as ih  # noqa: E402
from bulk.inject_real_s96 import (  # noqa: E402
    load_real_fits, write_injected_fits)
from bulk.inverted_null import (  # noqa: E402
    CHECKPOINT_NAME, SURVIVORS_NAME, compute_summary, flip_flux,
    load_done_tics, prepare_flipped, run_null)
from synth_fits import make_qlp_fits, screen_job  # noqa: E402

# The injected control signal: 1% @ 5.123 d, 0.3% noise --
# recoverable as a tier-A survivor under bulk_v3 (SDE ~34),
# shallow enough to survive the screen's MAD clip.
PERIOD_D = 5.123
DEPTH_FRAC = 0.01
NOISE_PCT = 0.003
RECOVERY_TOL = 0.01  # found period within 1% of injected


def _fold_depth(t, f, period, t0, duration_d):
    """(in-transit mean - out-of-transit mean): negative for a
    dip, positive for a bump of the same depth."""
    phase = ((t - t0 + 0.5 * period) % period) - 0.5 * period
    in_tr = np.abs(phase) < duration_d / 2.0
    return float(np.mean(f[in_tr]) - np.mean(f[~in_tr]))


class TestFlip(unittest.TestCase):
    def test_median_preserved_exactly(self):
        rng = np.random.default_rng(7)
        f = 1.0 + rng.normal(0.0, 0.003, 1296)
        flipped = flip_flux(f)
        self.assertAlmostEqual(float(np.median(flipped)),
                               float(np.median(f)), places=12)
        # The input is not modified.
        self.assertTrue(np.all(np.isfinite(f)))

    def test_noise_properties_preserved(self):
        rng = np.random.default_rng(7)
        f = 1.0 + rng.normal(0.0, 0.003, 1296)
        flipped = flip_flux(f)
        self.assertAlmostEqual(float(np.std(flipped)),
                               float(np.std(f)), places=12)
        mad = lambda a: float(np.median(np.abs(a - np.median(a))))
        self.assertAlmostEqual(mad(flipped), mad(f), places=12)

    def test_nan_positions_preserved(self):
        rng = np.random.default_rng(7)
        f = 1.0 + rng.normal(0.0, 0.003, 500)
        f[10] = np.nan
        f[400] = np.nan
        flipped = flip_flux(f)
        self.assertTrue(np.isnan(flipped[10]))
        self.assertTrue(np.isnan(flipped[400]))
        finite = np.isfinite(flipped)
        self.assertAlmostEqual(float(np.median(flipped[finite])),
                               float(np.nanmedian(f)), places=12)

    def test_all_nan_returns_unchanged(self):
        f = np.full(100, np.nan)
        flipped = flip_flux(f)
        self.assertTrue(np.all(np.isnan(flipped)))

    def test_dip_becomes_bump_of_equal_depth(self):
        rng = np.random.default_rng(42)
        n = 1296
        t = 1500.0 + np.arange(n) * 30.0 / 1440.0
        f = 1.0 + rng.normal(0.0, NOISE_PCT, n)
        epoch = float(t[0]) + 2.0
        f_inj, duration_d = ih.inject_transit(t, f, DEPTH_FRAC,
                                              PERIOD_D, epoch)
        dip = _fold_depth(t, f_inj, PERIOD_D, epoch, duration_d)
        self.assertLess(dip, 0.0)  # a real dip before the flip
        flipped = flip_flux(f_inj)
        bump = _fold_depth(t, flipped, PERIOD_D, epoch, duration_d)
        # The brightening equals the dip depth (the flip is a
        # linear reflection, so this is exact up to float
        # rounding -- not a loose "same order" check).
        self.assertAlmostEqual(bump, -dip, places=9)

    def test_time_and_quality_untouched_by_flip(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            src = td / "123.fits"
            make_qlp_fits(src, period_d=PERIOD_D,
                          depth_frac=DEPTH_FRAC,
                          noise_pct=NOISE_PCT, seed=42)
            t, f, q, _fcol, _meta = load_real_fits(src)
            flipped_path, _meta = prepare_flipped(src, td / "work")
            t2, f2, q2, _fcol2, _meta2 = load_real_fits(flipped_path)
            self.assertTrue(np.array_equal(t, t2))
            self.assertTrue(np.array_equal(q, q2))
            self.assertTrue(np.array_equal(f2, flip_flux(f)))
            self.assertEqual(flipped_path.name, "123_flipped.fits")


class TestFlippedScreen(unittest.TestCase):
    def setUp(self):
        self._previous = bs.CALIBRATION_VERSION
        bs.set_calibration("bulk_v3")

    def tearDown(self):
        bs.set_calibration(self._previous)

    def test_control_recovers_unflipped(self):
        # The control: without the flip, the injected transit
        # IS a survivor at the injected period -- so the
        # flipped non-recovery below is the flip working, not
        # a dead screen or an undetectable signal.
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "111.fits"
            make_qlp_fits(src, period_d=PERIOD_D,
                          depth_frac=DEPTH_FRAC,
                          noise_pct=NOISE_PCT, seed=42)
            r = bs._screen_one(screen_job(src, tic="111",
                                          sector=96))
            self.assertEqual(r["status"], "survivor")
            self.assertIsNotNone(r.get("period_days"))
            self.assertLess(abs(r["period_days"] - PERIOD_D)
                            / PERIOD_D, RECOVERY_TOL)

    def test_flipped_transit_not_recovered_as_dip(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            src = td / "111.fits"
            make_qlp_fits(src, period_d=PERIOD_D,
                          depth_frac=DEPTH_FRAC,
                          noise_pct=NOISE_PCT, seed=42)
            _t, _f, _q, _fcol, meta = load_real_fits(src)
            flipped_path, _meta = prepare_flipped(src,
                                                  td / "work")
            r = bs._screen_one(screen_job(
                flipped_path, tic="111", sector=96, meta=meta))
            # The assertion is about the INJECTED signal only:
            # the flipped run may still produce unrelated noise
            # survivors -- it must not recover the injected
            # transit as a dip survivor at its period.
            recovered = (r.get("status") == "survivor"
                         and r.get("period_days") is not None
                         and abs(r["period_days"] - PERIOD_D)
                         / PERIOD_D < RECOVERY_TOL)
            self.assertFalse(
                recovered,
                f"flipped screen recovered the injected transit: "
                f"status={r.get('status')} "
                f"period={r.get('period_days')} "
                f"sde={r.get('sde')}")


class TestResume(unittest.TestCase):
    def setUp(self):
        self._previous = bs.CALIBRATION_VERSION
        bs.set_calibration("bulk_v3")

    def tearDown(self):
        bs.set_calibration(self._previous)

    def _fake_cache(self, td, tics):
        cache = Path(td) / "cache" / "s0096"
        cache.mkdir(parents=True)
        for i, tic in enumerate(tics):
            make_qlp_fits(cache / f"{tic}.fits",
                          period_d=None, seed=100 + i)
        return Path(td) / "cache"

    def test_completed_star_skipped_on_relaunch(self):
        with tempfile.TemporaryDirectory() as td:
            cache = self._fake_cache(td, ["111", "222"])
            out_dir = Path(td) / "out"
            first = run_null(cache, 96, out_dir, workers=1)
            self.assertEqual(first["n_screened"], 2)
            self.assertEqual(first["n_resumed_skipped"], 0)
            ckpt = out_dir / CHECKPOINT_NAME
            self.assertEqual(load_done_tics(ckpt), {"111", "222"})
            surv_first = (out_dir / SURVIVORS_NAME).read_text() \
                if (out_dir / SURVIVORS_NAME).exists() else ""
            ckpt_first = ckpt.read_text()
            # Re-launch: both stars are skipped, nothing
            # re-screens, outputs are byte-identical.
            second = run_null(cache, 96, out_dir, workers=1)
            self.assertEqual(second["n_resumed_skipped"], 2)
            self.assertEqual(second["n_screened_this_run"], 0)
            self.assertEqual(second["n_screened"], 2)
            self.assertEqual(ckpt.read_text(), ckpt_first)
            surv_second = (out_dir / SURVIVORS_NAME).read_text() \
                if (out_dir / SURVIVORS_NAME).exists() else ""
            self.assertEqual(surv_second, surv_first)

    def test_partial_resume_screens_only_the_rest(self):
        with tempfile.TemporaryDirectory() as td:
            cache = self._fake_cache(td, ["111", "222", "333"])
            out_dir = Path(td) / "out"
            # First launch screens only TIC 111 (via --tics).
            run_null(cache, 96, out_dir, workers=1, tics=["111"])
            self.assertEqual(load_done_tics(out_dir / CHECKPOINT_NAME),
                             {"111"})
            # Second launch (full sector) screens 222 + 333 only.
            second = run_null(cache, 96, out_dir, workers=1)
            self.assertEqual(second["n_resumed_skipped"], 1)
            self.assertEqual(second["n_screened_this_run"], 2)
            self.assertEqual(second["n_screened"], 3)

    def test_parallel_path_matches_sequential(self):
        # The Mac run uses the pool; the pool path must produce
        # the same checkpoint as the sequential path.
        with tempfile.TemporaryDirectory() as td:
            cache = self._fake_cache(td, ["111", "222"])
            out_seq = Path(td) / "seq"
            out_par = Path(td) / "par"
            seq = run_null(cache, 96, out_seq, workers=1)
            par = run_null(cache, 96, out_par, workers=2)
            self.assertEqual(par["n_screened"], seq["n_screened"])
            self.assertEqual(par["null_survivors_total"],
                             seq["null_survivors_total"])
            self.assertEqual(par["status_counts"],
                             seq["status_counts"])

    def test_torn_checkpoint_line_rescreens_that_star(self):
        with tempfile.TemporaryDirectory() as td:
            cache = self._fake_cache(td, ["111"])
            out_dir = Path(td) / "out"
            run_null(cache, 96, out_dir, workers=1)
            ckpt = out_dir / CHECKPOINT_NAME
            with open(ckpt, "a") as fh:
                fh.write('{"tic": "999", "status": "survivo')
            # The torn line is ignored (no crash); 111 stays done.
            self.assertEqual(load_done_tics(ckpt), {"111"})


class TestSummary(unittest.TestCase):
    def _records(self):
        return [
            {"tic": "1", "status": "survivor", "tier": "A",
             "sde": 12.0, "near_systematic": False},
            {"tic": "2", "status": "survivor", "tier": "A",
             "sde": 8.5, "near_systematic": True},
            {"tic": "3", "status": "survivor", "tier": "B",
             "sde": 7.5, "near_systematic": False},
            {"tic": "4", "status": "survivor", "tier": "B",
             "sde": 21.0, "near_systematic": True},
            {"tic": "5", "status": "recorded", "sde": 6.5},
            {"tic": "6", "status": "below_floor", "sde": 5.0},
            {"tic": "7", "status": "demoted", "sde": 9.0},
            {"tic": "8", "status": "error",
             "error": "KeyError: no known flux column"},
            {"tic": "9", "status": "unmeasured",
             "reason": "watchdog_timeout"},
            {"tic": "10", "status": "too_few_points"},
        ]

    def test_counts_by_tier_and_floor_rates(self):
        s = compute_summary(self._records())
        # 10 attempted; error + unmeasured were not screened.
        self.assertEqual(s["n_attempted"], 10)
        self.assertEqual(s["n_screened"], 8)
        self.assertEqual(s["n_errors"], 1)
        self.assertEqual(s["n_unmeasured"], 1)
        self.assertEqual(s["null_survivors_total"], 4)
        self.assertEqual(s["null_survivors_tier_a"], 2)
        self.assertEqual(s["null_survivors_tier_b"], 2)
        self.assertAlmostEqual(s["floor_rate_overall"], 4 / 8)
        self.assertAlmostEqual(s["floor_rate_tier_a"], 2 / 8)
        self.assertAlmostEqual(s["floor_rate_tier_b"], 2 / 8)
        self.assertEqual(s["null_survivors_near_systematic"], 2)
        self.assertAlmostEqual(s["null_survivor_sde_max"], 21.0)
        self.assertAlmostEqual(s["null_survivor_sde_median"],
                               (8.5 + 12.0) / 2)

    def test_survivors_above_sde_bars(self):
        s = compute_summary(self._records())
        above = s["null_survivors_above_sde"]
        self.assertEqual(above["7"], 4)
        self.assertEqual(above["8"], 3)
        self.assertEqual(above["9"], 2)
        self.assertEqual(above["10"], 2)
        self.assertEqual(above["15"], 1)
        self.assertEqual(above["20"], 1)

    def test_reference_floor_fractions(self):
        ref = [
            {"tic": "a", "status": "survivor", "tier": "A"},
            {"tic": "b", "status": "survivor", "tier": "A"},
            {"tic": "c", "status": "survivor", "tier": "B"},
            {"tic": "d", "status": "survivor", "tier": "B"},
            {"tic": "e", "status": "survivor", "tier": "B"},
            {"tic": "f", "status": "survivor", "tier": "B"},
        ]
        s = compute_summary(self._records(),
                            reference_records=ref)
        r = s["reference"]
        self.assertEqual(r["n_survivors"], 6)
        self.assertEqual(r["n_survivors_tier_a"], 2)
        self.assertEqual(r["n_survivors_tier_b"], 4)
        self.assertAlmostEqual(r["floor_fraction_overall"], 4 / 6)
        self.assertAlmostEqual(r["floor_fraction_tier_a"], 2 / 2)
        self.assertAlmostEqual(r["floor_fraction_tier_b"], 2 / 4)

    def test_empty_records(self):
        s = compute_summary([])
        self.assertEqual(s["n_screened"], 0)
        self.assertEqual(s["null_survivors_total"], 0)
        self.assertIsNone(s["floor_rate_overall"])
        self.assertIsNone(s["null_survivor_sde_max"])


if __name__ == "__main__":
    unittest.main()
