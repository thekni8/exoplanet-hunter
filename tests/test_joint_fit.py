"""Phase 5.6 joint-fit tests (DESIGN_5_6.md, vote V56-20261123).

C1 unit test: J2 moves P continuously off J1's 800-point grid onto
the true injected period -- with the least_squares control proving
the test discriminates the old design (the control asserts the old
optimizer moves P by exactly 0.0, so the C1 test FAILS on it).
A8 regression test: the periodogram exposure does not alter baseline
screening output. J1 golden test (TOI-700-style): the right period
is in the top-15 but not the argmax, and survives refinement + dedup
into the top 3. C2 selection test: two candidates differing by a
real-planet dchi2 are NOT tied. Fallback tests + B1 diagnostics +
the driver helper (_joint_fit_pass2).

Calibration: bulk_v6 throughout (setUp/tearDown restores the
previous profile).
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import bulk_screen as bs  # noqa: E402
from bulk import joint_fit as jf  # noqa: E402
from bulk import k3_run as k3run  # noqa: E402
from bulk import p43_run as p43run  # noqa: E402
from synth_fits import make_qlp_fits, screen_job  # noqa: E402

# The drift bar (P17): |dP| < 2.857e-4 d == median drift < 0.01 d
# over 35 cycles. The C1 test asserts J2 lands inside it.
DRIFT_BAR_DP = 0.01 / 35.0


def _p6p9_toy(seed=0):
    """The p6p9_check.py toy: 4 sectors x ~18k 2-min cadences over
    ~108 d with downlink gaps, one box transit (P 3.1827878 d,
    depth 0.1%). Returns (t, f, sectors, sigma)."""
    rng = np.random.default_rng(seed)
    t = np.concatenate([np.arange(0, 27.4, 2 / 1440) + s * 27.4
                        for s in range(4)])
    t = t[(t % 27.4 < 26.0)]
    P_true, T0_true, D_true, depth_true = 3.1827878, 5.0, 0.076, 0.001
    ph = ((t - T0_true + 0.5 * P_true) % P_true) - 0.5 * P_true
    f = np.where(np.abs(ph) < 0.5 * D_true, 1.0 - depth_true, 1.0)
    f = f + rng.normal(0, 0.001, len(t))
    sectors = []
    for s in range(4):
        m = (t >= s * 27.4) & (t < (s + 1) * 27.4)
        sectors.append({"sector": 95 + s, "t": t[m], "f": f[m],
                        "sigma": 0.001})
    truth = {"period": P_true, "t0": T0_true, "duration": D_true,
             "depth": depth_true}
    return t, f, sectors, truth


def _coarse_toy(signals, seed=7, cadence_min=30.0, noise=0.003,
                with_gaps=True):
    """4 sectors x 27.4 d at 30-min cadence. signals: list of
    (P, T0, D, depth). Returns (t, f)."""
    rng = np.random.default_rng(seed)
    t = np.concatenate([np.arange(0, 27.4, cadence_min / 1440.0)
                        + s * 27.4 for s in range(4)])
    if with_gaps:
        t = t[(t % 27.4 < 26.0)]
    f = 1.0 + rng.normal(0, noise, len(t))
    for (P, T0, D, depth) in signals:
        ph = ((t - T0 + 0.5 * P) % P) - 0.5 * P
        f = np.where(np.abs(ph) < 0.5 * D, f - depth, f)
    return t, f


def _periodogram(t, f):
    """Coarse BLS periodogram in the _screen_one exposure shape."""
    from astropy.timeseries import BoxLeastSquares
    periods = 1.0 / np.linspace(1.0 / bs.MAX_PERIOD_D,
                                1.0 / bs.MIN_PERIOD_D,
                                bs.BLS_GRID_POINTS)
    bls = BoxLeastSquares(np.asarray(t, dtype=float),
                          np.asarray(f, dtype=float))
    res = bls.power(periods, list(bs.BLS_DURATIONS_D))
    pv = np.asarray(res.period, dtype=float)
    pw = np.asarray(res.power, dtype=float)
    med, scale = bs._robust_sde(pw, pv)
    return {"periods": pv, "powers": pw,
            "depths": np.asarray(res.depth, dtype=float),
            "durations": np.asarray(res.duration, dtype=float),
            "transit_times": np.asarray(res.transit_time,
                                        dtype=float),
            "med": med, "scale": scale}


class _BulkV6Case(unittest.TestCase):
    def setUp(self):
        # The documented restore target is bulk_v1 (the
        # import-time default; see set_calibration's docstring).
        bs.set_calibration("bulk_v6")

    def tearDown(self):
        bs.set_calibration("bulk_v1")


class TestC1MovesPeriod(_BulkV6Case):
    """C1: J2 moves P continuously off J1's grid onto the truth."""

    def test_j2_moves_p_off_grid_onto_true_period(self):
        _t, _f, sectors, truth = _p6p9_toy()
        data = jf.JointFitData(sectors)
        # J1-style start: half a coarse-grid step off in P, 0.01 d
        # off in T0, depth 10% low (the p6p9_check start).
        cand = {"period": truth["period"] + 0.0005,
                "t0": truth["t0"] + 0.01,
                "duration": truth["duration"],
                "depth": truth["depth"] * 0.9, "sde": 20.0}
        fit = jf.fit_signal(data, cand)
        self.assertTrue(fit["converged"], fit)
        self.assertGreater(fit["depth"], 0.0)
        self.assertGreater(fit["dchi2"], 0.0)
        # Moved off the grid: more than one J1 fine-grid spacing
        # (3% * P / 800 = 1.19e-4 d at P = 3.18 d).
        fine_spacing = 0.03 * truth["period"] / 800.0
        self.assertGreater(abs(fit["period"] - cand["period"]),
                           fine_spacing)
        # Onto the truth: inside the P17 drift bar.
        self.assertLess(abs(fit["period"] - truth["period"]),
                        DRIFT_BAR_DP)
        # And strictly closer to the truth than the start was.
        self.assertLess(abs(fit["period"] - truth["period"]),
                        abs(cand["period"] - truth["period"]))
        self.assertLess(abs(fit["duration"] - truth["duration"]),
                        0.01)
        self.assertLessEqual(fit["n_evaluations"], jf.MAX_NFEV)

    def test_least_squares_control_moves_p_by_zero(self):
        """The R1 control: the OLD design (box + least_squares/trf)
        moves P by exactly 0.0 on the same toy -- so the C1 test
        above FAILS on the old design and PASSES on Powell. This
        is the numerical proof from 5-6-vote/p6p9_check.py, kept
        as a regression guard against reintroducing trf."""
        from scipy.optimize import least_squares
        t, f, _sectors, truth = _p6p9_toy()
        P_true, T0_true = truth["period"], truth["t0"]
        D_true, depth_true = truth["duration"], truth["depth"]
        sig = 0.001

        def box(tt, P, T0, D, depth):
            ph = ((tt - T0 + 0.5 * P) % P) - 0.5 * P
            return np.where(np.abs(ph) < 0.5 * D, 1.0 - depth, 1.0)

        def resid(x):
            P, T0, D, depth = x
            return (f - box(t, P, T0, D, depth)) / sig

        x0 = np.array([P_true + 0.0005, T0_true + 0.01, D_true,
                       depth_true * 0.9])
        res = least_squares(
            resid, x0, method="trf",
            bounds=([P_true * 0.985, T0_true - 0.5 * P_true, 0.04,
                     0.0],
                    [P_true * 1.015, T0_true + 0.5 * P_true, 0.25,
                     0.05]),
            max_nfev=200)
        self.assertEqual(res.x[0] - x0[0], 0.0)
        self.assertEqual(res.x[1] - x0[1], 0.0)
        self.assertEqual(res.x[2] - x0[2], 0.0)

    def test_variable_projection_matches_lstsq(self):
        """The closed-form solve is exact weighted LS: chi2 and
        depth agree with a brute-force design-matrix lstsq."""
        _t, f, sectors, truth = _p6p9_toy()
        data = jf.JointFitData(sectors)
        t_all = data.t
        g = data._g
        w = data.w
        sec_idx = data.sec_idx
        S = data.n_sectors
        for (P, T0, D) in [
                (truth["period"], truth["t0"], truth["duration"]),
                (truth["period"] + 0.0005, truth["t0"] + 0.01,
                 truth["duration"]),
                (truth["period"] * 1.01, truth["t0"] + 0.3, 0.1)]:
            c1, d1, _ = data.solve(P, T0, D)
            ph = ((t_all - T0 + 0.5 * P) % P) - 0.5 * P
            in_tr = (np.abs(ph) < 0.5 * D).astype(float)
            A = np.zeros((len(t_all), S + 1))
            for s in range(S):
                A[sec_idx == s, s] = 1.0
            A[:, S] = -in_tr
            sw = np.sqrt(w)
            x, *_ = np.linalg.lstsq(A * sw[:, None], g * sw,
                                    rcond=None)
            resid = g - A @ x
            c2 = float(np.sum(w * resid * resid))
            d2 = float(x[S])
            self.assertAlmostEqual(c1, c2, delta=1e-6 * max(c2, 1.0))
            self.assertAlmostEqual(d1, d2, delta=1e-9)

    def test_fit_never_returns_worse_than_start(self):
        _t, _f, sectors, truth = _p6p9_toy()
        data = jf.JointFitData(sectors)
        cand = {"period": truth["period"] + 0.0005,
                "t0": truth["t0"] + 0.01,
                "duration": truth["duration"],
                "depth": truth["depth"] * 0.9, "sde": 20.0}
        chi2_start, _d, _o = data.solve(
            cand["period"], cand["t0"], cand["duration"])
        fit = jf.fit_signal(data, cand)
        self.assertLessEqual(fit["chi2"], chi2_start)

    def test_bounds_enforced_on_output(self):
        _t, _f, sectors, truth = _p6p9_toy()
        data = jf.JointFitData(sectors)
        cand = {"period": truth["period"] + 0.0005,
                "t0": truth["t0"] + 0.01,
                "duration": truth["duration"],
                "depth": truth["depth"] * 0.9, "sde": 20.0}
        fit = jf.fit_signal(data, cand)
        self.assertGreaterEqual(fit["period"], cand["period"] * 0.985)
        self.assertLessEqual(fit["period"], cand["period"] * 1.015)
        self.assertGreaterEqual(fit["duration"], 0.04)
        self.assertLessEqual(fit["duration"], 0.25)

    def test_a6_cap_hit_converges_when_valid(self):
        """A6: hitting the evaluation cap with finite chi2, dchi2
        > 0, depth > 0 counts as CONVERGED, flagged hit_max_nfev.
        max_nfev=5 forces the cap on the toy (the start point
        alone already satisfies the conditions)."""
        _t, _f, sectors, truth = _p6p9_toy()
        data = jf.JointFitData(sectors)
        cand = {"period": truth["period"] + 0.0005,
                "t0": truth["t0"] + 0.01,
                "duration": truth["duration"],
                "depth": truth["depth"] * 0.9, "sde": 20.0}
        fit = jf.fit_signal(data, cand, max_nfev=5)
        self.assertTrue(fit["hit_max_nfev"])
        self.assertTrue(fit["converged"])
        self.assertGreater(fit["depth"], 0.0)
        self.assertGreater(fit["dchi2"], 0.0)


class TestA8PeriodogramExposure(_BulkV6Case):
    """A8: exposing the periodogram does not alter baseline
    screening output (argmax + 2 alternates unchanged)."""

    def _screen_pair(self, **fits_kw):
        with tempfile.TemporaryDirectory() as td:
            path = make_qlp_fits(Path(td) / "synth.fits", **fits_kw)
            rec_off = bs._screen_one(screen_job(path))
            rec_on = bs._screen_one(
                screen_job(path, return_periodogram=True))
            return rec_off, rec_on

    def test_exposure_does_not_change_screen_output(self):
        rec_off, rec_on = self._screen_pair(
            period_d=3.0, depth_frac=0.01, duration_d=0.1,
            noise_pct=0.003, seed=42)
        self.assertNotIn("periodogram", rec_off)
        self.assertIn("periodogram", rec_on)
        pg = rec_on["periodogram"]
        self.assertEqual(len(pg["periods"]), bs.BLS_GRID_POINTS)
        self.assertEqual(len(pg["powers"]), bs.BLS_GRID_POINTS)
        # The periodogram's argmax is the record's argmax.
        i = int(np.argmax((pg["powers"] - pg["med"]) / pg["scale"]))
        self.assertAlmostEqual(float(pg["periods"][i]),
                               rec_on["period_days"])
        # Every other output identical (argmax + alternates + all).
        for key in sorted(set(rec_off) | set(rec_on)):
            if key == "periodogram":
                continue
            self.assertEqual(rec_off.get(key), rec_on.get(key),
                             key)

    def test_below_floor_record_still_exposes(self):
        # Pure noise: below the record floor, but the periodogram
        # is attached before the early return.
        rec_off, rec_on = self._screen_pair(period_d=None, seed=3)
        self.assertEqual(rec_on["status"], "below_floor")
        self.assertEqual(rec_off["status"], "below_floor")
        self.assertIn("periodogram", rec_on)
        self.assertNotIn("periodogram", rec_off)

    def test_screen_job_tuple_shape(self):
        job4 = screen_job("x.fits")
        self.assertEqual(len(job4), 4)
        job5 = screen_job("x.fits", return_periodogram=True)
        self.assertEqual(len(job5), 5)
        self.assertTrue(job5[4])

    def test_k3_screen_threads_exposure(self):
        with tempfile.TemporaryDirectory() as td:
            path = make_qlp_fits(
                Path(td) / "synth.fits", period_d=3.0,
                depth_frac=0.01, duration_d=0.1, noise_pct=0.003,
                seed=42)
            rec_off = k3run._screen(str(path), "999999999", 1)
            rec_on = k3run._screen(str(path), "999999999", 1,
                                   return_periodogram=True)
            self.assertNotIn("periodogram", rec_off)
            self.assertIn("periodogram", rec_on)
            self.assertEqual(rec_off["period_days"],
                             rec_on["period_days"])


class TestJ1Extraction(_BulkV6Case):
    """J1: top-15 extraction, refinement, harmonic dedup."""

    def test_toi700_style_right_period_not_argmax_survives(self):
        # Strong P=7.0 d signal is the argmax; the P=3.17 d planet
        # is in the top-15 (rank 1, not the argmax) and survives
        # refinement + dedup into the top 3. (Periods chosen so no
        # small-rational dedup kills the planet: 7.0/3.17 = 2.208,
        # 1.9% from the nearest m/n <= 8 ratio.)
        t, f = _coarse_toy([(7.0, 5.0, 0.10, 0.015),
                            (3.17, 3.0, 0.12, 0.008)],
                           with_gaps=False)
        pg = _periodogram(t, f)
        j1 = jf.extract_top3(pg, t, f)
        coarse_periods = [c["period"] for c in j1["top15_coarse"]]
        self.assertEqual(len(coarse_periods), jf.N_PEAKS)
        # Strong signal is the argmax.
        self.assertAlmostEqual(coarse_periods[0], 7.0, delta=0.07)
        # Planet in the top-15, NOT the argmax.
        ranks = [i for i, p in enumerate(coarse_periods)
                 if abs(p - 3.17) / 3.17 <= 0.01]
        self.assertTrue(ranks, coarse_periods)
        self.assertGreater(ranks[0], 0)
        # Planet survives refinement + dedup into the top 3.
        top3_periods = [c["period"] for c in j1["top3"]]
        self.assertTrue(any(abs(p - 3.17) / 3.17 <= 0.01
                            for p in top3_periods), top3_periods)
        self.assertLessEqual(len(top3_periods), jf.N_FIT_SIGNALS)
        self.assertGreater(j1["seconds_j1"], 0.0)

    def test_subharmonic_masking_keeps_multiples(self):
        # Synthetic periodogram: peaks at 5.0 (strongest), its
        # sub-harmonics 2.5/1.667/1.25, and its multiple 10.0.
        periods = 1.0 / np.linspace(1.0 / 20.0, 1.0 / 0.5, 12000)
        powers = np.full(12000, -1.0)
        n = {5.0: 100.0, 2.5: 80.0, 1.0 / 0.6: 70.0, 1.25: 60.0,
             10.0: 90.0}
        for p, v in n.items():
            powers[int(np.argmin(np.abs(periods - p)))] = v
        pg = {"periods": periods, "powers": powers,
              "depths": np.zeros(12000),
              "durations": np.full(12000, 0.1),
              "transit_times": np.zeros(12000),
              "med": 0.0, "scale": 1.0}
        cands = jf.extract_peaks(pg)
        got = [c["period"] for c in cands]
        self.assertAlmostEqual(got[0], 5.0, delta=0.05)
        self.assertAlmostEqual(got[1], 10.0, delta=0.1)
        for sub in (2.5, 1.0 / 0.6, 1.25):
            self.assertFalse(
                any(abs(p - sub) / sub <= 0.02 for p in got),
                "sub-harmonic %s leaked into the extraction" % sub)

    def test_dedup_drops_harmonic_family(self):
        refined = [
            {"period": 3.0, "sde": 50.0},
            {"period": 6.0, "sde": 40.0},   # 2x the leader
            {"period": 2.0, "sde": 30.0},   # 2/3 of the leader
            # Independent: 5.37/3.0 = 1.79, 0.56% from the nearest
            # m/n <= 8 ratio (9/5) -- outside the 0.2% window.
            {"period": 5.37, "sde": 20.0},
        ]
        out = jf.dedup_peaks(refined)
        self.assertEqual([c["period"] for c in out], [3.0, 5.37])

    def test_refine_rejects_when_sde_drops(self):
        # A candidate with a fake-high coarse SDE at a wrong period:
        # the refined SDE is far below coarse - 1.0, so the coarse
        # values stand.
        t, f = _coarse_toy([(3.17, 3.0, 0.12, 0.008)],
                           with_gaps=False)
        pg = _periodogram(t, f)
        from astropy.timeseries import BoxLeastSquares
        bls = BoxLeastSquares(t, f)
        cand = {"period": 3.5, "sde": 100.0, "depth": 0.008,
                "duration": 0.12, "t0": 3.0, "detector": "BLS"}
        out = jf.refine_peak(bls, cand, pg["med"], pg["scale"],
                             list(bs.BLS_DURATIONS_D))
        self.assertEqual(out["period"], 3.5)
        self.assertEqual(out["sde"], 100.0)


class TestC2Selection(unittest.TestCase):
    """C2: maximum dchi2 wins; the 1% tie-breaker applies to dchi2,
    never to total chi2."""

    def _fit(self, dchi2, sde, converged=True):
        return {"dchi2": dchi2, "origin_sde": sde,
                "converged": converged, "chi2": 60000.0 - dchi2}

    def test_real_planet_dchi2_difference_is_not_a_tie(self):
        # Two candidates differing by dchi2 = 125 -- a real
        # threshold-planet signal (MES^2 ~ 81-225). Under the old
        # total-chi2 rule (1% of ~60,000 = 600) these would tie and
        # the higher-SDE peak would win; under C2 the higher dchi2
        # wins outright.
        fits = [self._fit(225.0, 10.0), self._fit(100.0, 50.0)]
        self.assertIs(jf.select_winner(fits), fits[0])

    def test_tie_goes_to_higher_sde(self):
        fits = [self._fit(100.5, 10.0), self._fit(100.0, 50.0)]
        self.assertIs(jf.select_winner(fits), fits[1])

    def test_absolute_tie_band(self):
        fits = [self._fit(0.5, 10.0), self._fit(0.2, 50.0)]
        self.assertIs(jf.select_winner(fits), fits[1])

    def test_no_converged_fit_returns_none(self):
        fits = [self._fit(500.0, 10.0, converged=False),
                self._fit(400.0, 50.0, converged=False)]
        self.assertIsNone(jf.select_winner(fits))

    def test_failed_fits_excluded_from_selection(self):
        fits = [self._fit(50.0, 10.0, converged=True),
                self._fit(500.0, 50.0, converged=False)]
        self.assertIs(jf.select_winner(fits), fits[0])


class TestFallback(_BulkV6Case):
    """Fallback: all 3 fits fail -> BLS ephemeris stands, flagged."""

    def test_inverted_transit_fails_depth_gate(self):
        # A BRIGHTENING at the candidate ephemeris: the linear
        # solve finds depth < 0, so the fit fails (P10: a
        # non-positive fitted depth is a fit failure).
        t, f, sectors, truth = _p6p9_toy()
        # Flip the transit into a brightening.
        ph = ((t - truth["t0"] + 0.5 * truth["period"])
              % truth["period"]) - 0.5 * truth["period"]
        in_tr = np.abs(ph) < 0.5 * truth["duration"]
        f2 = f.copy()
        f2[in_tr] += 2.0 * truth["depth"]
        sectors2 = []
        for s in sectors:
            m = (t >= (s["sector"] - 95) * 27.4) & (
                t < (s["sector"] - 94) * 27.4)
            sectors2.append({"sector": s["sector"], "t": t[m],
                             "f": f2[m], "sigma": 0.001})
        data = jf.JointFitData(sectors2)
        cand = {"period": truth["period"], "t0": truth["t0"],
                "duration": truth["duration"],
                "depth": truth["depth"], "sde": 20.0}
        fit = jf.fit_signal(data, cand)
        self.assertFalse(fit["converged"])
        self.assertLess(fit["depth"], 0.0)

    def test_run_joint_fit_all_failed(self):
        t, f = _coarse_toy([(3.1827878, 5.0, 0.076, 0.003)],
                           seed=11, noise=0.001)
        pg = _periodogram(t, f)
        sectors = []
        for s in range(4):
            m = (t >= s * 27.4) & (t < (s + 1) * 27.4)
            sectors.append({"sector": 95 + s, "t": t[m], "f": f[m],
                            "sigma": 0.001})

        def _fail(data, cand, max_nfev=jf.MAX_NFEV):
            return {"period": cand["period"], "t0": cand["t0"],
                    "duration": cand["duration"], "depth": -0.001,
                    "chi2": 1.0, "dchi2": 0.0, "chi2_null": 1.0,
                    "converged": False, "hit_max_nfev": False,
                    "powell_success": True, "n_evaluations": 10,
                    "seconds": 0.01,
                    "origin_sde": float(cand["sde"]), "error": None}

        with mock.patch.object(jf, "fit_signal", _fail):
            res = jf.run_joint_fit(pg, t, f, sectors,
                                   period_inj=3.1827878)
        self.assertFalse(res["fitted"])
        self.assertTrue(res["fallback"])
        self.assertTrue(res["joint_fit_failed"])
        self.assertIsNone(res["winner"])
        self.assertEqual(res["diagnostics"]["n_failed"],
                         res["diagnostics"]["n_fitted"])
        self.assertGreater(res["diagnostics"]["n_fitted"], 0)

    def test_fewer_than_two_sectors_is_no_candidate(self):
        t, f = _coarse_toy([(3.1827878, 5.0, 0.076, 0.003)],
                           seed=11, noise=0.001)
        pg = _periodogram(t, f)
        m = t < 27.4
        one = [{"sector": 95, "t": t[m], "f": f[m], "sigma": 0.001}]
        res = jf.run_joint_fit(pg, t, f, one)
        self.assertFalse(res["fitted"])
        self.assertTrue(res["no_usable_candidate"])
        self.assertEqual(res["no_candidate_reason"],
                         "fewer-than-2-sectors")
        self.assertFalse(res["diagnostics"]["entered"])

    def test_driver_helper_no_pass2_period(self):
        p2 = {"status": "below_floor", "period_days": None,
              "sde": 3.0}
        out, res = p43run._joint_fit_pass2(p2, {}, None, None, None,
                                           [], {})
        self.assertIs(out, p2)
        self.assertTrue(res["no_usable_candidate"])
        self.assertEqual(res["no_candidate_reason"],
                         "no-pass2-period")

    def test_driver_helper_missing_periodogram(self):
        p2 = {"status": "survivor", "period_days": 3.0, "sde": 10.0}
        out, res = p43run._joint_fit_pass2(p2, {}, None, None, None,
                                           [], {})
        self.assertIs(out, p2)
        self.assertEqual(res["no_candidate_reason"],
                         "no-periodogram")

    def test_driver_helper_below_floor(self):
        p2 = {"status": "below_floor", "period_days": 3.0, "sde": 5.0}
        out, res = p43run._joint_fit_pass2(p2, {}, None, None, None,
                                           [], {})
        self.assertIs(out, p2)
        self.assertEqual(res["no_candidate_reason"], "below-floor")

    def test_driver_helper_all_failed_keeps_bls(self):
        t, f = _coarse_toy([(3.1827878, 5.0, 0.076, 0.003)],
                           seed=11, noise=0.001)
        pg = _periodogram(t, f)
        p2 = {"status": "survivor", "tier": "A",
              "period_days": 3.183, "t0_btjd": 5.0,
              "duration_hours": 1.8, "depth_percent": 0.3,
              "sde": 25.0, "mes_pink": 20.0, "n_events": 30,
              "n_strong_events": 25, "max_event_snr": 6.0,
              "cdpp_pct": 0.1, "v_ratio": 1.0, "flags": [],
              "gate_reason": None, "secondary_depth_percent": 0.0,
              "search_health": "OK"}
        masked = []
        sigmas = {}
        for s in range(4):
            m = (t >= s * 27.4) & (t < (s + 1) * 27.4)
            masked.append({"sector": 95 + s, "t": t[m], "f": f[m],
                           "q": np.zeros(int(m.sum()), dtype=int)})
            sigmas[95 + s] = 0.001
        failed = {"fitted": False, "fallback": True,
                  "joint_fit_failed": True,
                  "no_usable_candidate": False,
                  "no_candidate_reason": None, "winner": None,
                  "signals": [], "seconds_j1": 1.0,
                  "seconds_j2": 0.1, "diagnostics": {}}
        with mock.patch.object(jf, "run_joint_fit",
                               return_value=failed):
            out, res = p43run._joint_fit_pass2(
                p2, {"periodogram": pg}, t, f,
                np.zeros(len(t), dtype=int), masked, sigmas)
        # The BLS ephemeris stands, flagged; the input is unmutated.
        self.assertEqual(out["period_days"], 3.183)
        self.assertEqual(out["status"], "survivor")
        self.assertTrue(out["joint_fit_failed"])
        self.assertNotIn("joint_fit_failed", p2)
        self.assertTrue(res["joint_fit_failed"])


class TestEndToEnd(_BulkV6Case):
    """Full J1 -> J2 -> selection -> driver record on a toy."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        bs.set_calibration("bulk_v6")
        cls.t, cls.f = _coarse_toy(
            [(3.1827878, 5.0, 0.076, 0.003)], seed=11, noise=0.001)
        cls.pg = _periodogram(cls.t, cls.f)
        cls.sectors = []
        cls.masked = []
        cls.sigmas = {}
        for s in range(4):
            m = (cls.t >= s * 27.4) & (cls.t < (s + 1) * 27.4)
            cls.sectors.append({"sector": 95 + s, "t": cls.t[m],
                                "f": cls.f[m], "sigma": 0.001})
            cls.masked.append(
                {"sector": 95 + s, "t": cls.t[m], "f": cls.f[m],
                 "q": np.zeros(int(m.sum()), dtype=int)})
            cls.sigmas[95 + s] = 0.001

    def test_single_planet_recovered(self):
        res = jf.run_joint_fit(self.pg, self.t, self.f,
                               self.sectors,
                               period_inj=3.1827878)
        self.assertTrue(res["fitted"])
        self.assertFalse(res["fallback"])
        w = res["winner"]
        self.assertLess(abs(w["period"] - 3.1827878) / 3.1827878,
                        0.01)
        self.assertLess(abs(w["period"] - 3.1827878), DRIFT_BAR_DP)
        self.assertGreater(w["depth"], 0.0)
        self.assertGreater(w["dchi2"], 0.0)
        self.assertGreater(res["seconds_j1"], 0.0)
        self.assertGreater(res["seconds_j2"], 0.0)
        # The whole result is JSON-safe (it lands in host files).
        json.dumps(res)

    def test_b1_diagnostics(self):
        res = jf.run_joint_fit(self.pg, self.t, self.f,
                               self.sectors,
                               period_inj=3.1827878)
        d = res["diagnostics"]
        self.assertTrue(d["entered"])
        self.assertTrue(d["in_top15"])
        self.assertEqual(d["top15_rank"], 0)
        self.assertTrue(d["in_top3"])
        self.assertTrue(d["injected_fitted"])
        self.assertTrue(d["injected_won"])
        self.assertEqual(d["n_candidates"], len(res["signals"]))
        self.assertEqual(d["n_failed"], 0)
        self.assertEqual(d["sectors_used"], [95, 96, 97, 98])

    def test_driver_helper_replaces_ephemeris(self):
        pg = self.pg
        pv, pw = pg["periods"], pg["powers"]
        med, scale = pg["med"], pg["scale"]
        i = int(np.argmax((pw - med) / scale))
        p2 = {"status": "survivor", "tier": "A",
              "period_days": float(pv[i]),
              "t0_btjd": float(pg["transit_times"][i]),
              "duration_hours": float(pg["durations"][i]) * 24.0,
              "depth_percent": float(pg["depths"][i]) * 100.0,
              "sde": float((pw[i] - med) / scale),
              "mes_pink": 25.0, "n_events": 30,
              "n_strong_events": 25, "max_event_snr": 6.0,
              "cdpp_pct": 0.1, "v_ratio": 1.0, "flags": [],
              "gate_reason": None, "secondary_depth_percent": 0.0,
              "search_health": "OK"}
        p2_before = dict(p2)
        out, res = p43run._joint_fit_pass2(
            p2, {"periodogram": pg}, self.t, self.f,
            np.zeros(len(self.t), dtype=int), self.masked,
            self.sigmas, period_inj=3.1827878)
        self.assertTrue(res["fitted"])
        # The input record is untouched (the caller keeps it as
        # pass2_bls); the output carries the fitted ephemeris.
        self.assertEqual(p2, p2_before)
        self.assertLess(abs(out["period_days"] - 3.1827878),
                        DRIFT_BAR_DP)
        self.assertNotEqual(out["period_days"],
                            p2["period_days"])
        # Rescored at the fitted ephemeris with unchanged bars:
        # a strong toy planet tiers A.
        self.assertEqual(out["tier"], "A")
        self.assertEqual(out["status"], "survivor")
        self.assertGreater(out["mes_pink"], 9.0)
        json.dumps(res)


if __name__ == "__main__":
    unittest.main()
