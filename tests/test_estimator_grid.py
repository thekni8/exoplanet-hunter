"""Estimator grid tests (Phase 4.1, item 4.1-8).

Pins the EXACT optimisation: bs.fold_depth_grid must reproduce
bs._fold_depth cell-by-cell (n_in exact, median bit-identical,
depth/noise within floating-point reassociation of the mean/std
prefix sums — far inside the 1e-6 preservation bar), and the
k2_prototype estimators built on it must return bit-identical
outputs to the original per-call loops (two-pass exact selection).

Offline only: synthetic curves built in memory. No downloads.
"""

import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import bulk_screen as bs  # noqa: E402
from bulk import k2_prototype as k2  # noqa: E402

# Agreement tolerance for grid-vs-reference depth/noise: absolute floor
# plus a relative term, ~1000x tighter than the 1e-6 preservation bar
# and ~1000x looser than the measured reassociation error (~1e-12).
ABS_TOL = 1e-12
REL_TOL = 1e-9


def _box_curve(period, t0, duration, depth, noise=0.002, seed=42,
               n=8000, span=27.0, secondary=None):
    rng = np.random.default_rng(seed)
    t = np.sort(rng.uniform(0, span, n))
    f = np.ones_like(t)
    phase = ((t - t0) / period + 0.5) % 1.0 - 0.5
    f[np.abs(phase) < duration / (2.0 * period)] -= depth
    if secondary is not None:
        ph2, dep2 = secondary
        phase2 = ((t - (t0 + ph2 * period)) / period + 0.5) % 1.0 - 0.5
        f[np.abs(phase2) < duration / (2.0 * period)] -= dep2
    f += rng.normal(0.0, noise, size=len(t))
    return t, f


def _reference_grid(t, f, period, t_ref, durations, phases):
    """Per-call _fold_depth over the grid — the oracle."""
    dep = np.zeros((len(durations), len(phases)))
    nin = np.zeros((len(durations), len(phases)), dtype=np.int64)
    noi = np.zeros((len(durations), len(phases)))
    for di, dur in enumerate(durations):
        for pi, ph in enumerate(phases):
            d, n, s = bs._fold_depth(t, f, period, t_ref, float(dur),
                                     phase_center=float(ph))
            dep[di, pi], nin[di, pi], noi[di, pi] = d, n, s
    return dep, nin, noi


def _assert_grid_equal(test, grid, ref):
    gd, gn, gs = grid
    rd, rn, rs = ref
    test.assertTrue(np.array_equal(gn, rn),
                    "n_in must match _fold_depth exactly")
    test.assertTrue(np.array_equal(np.isinf(gs), np.isinf(rs)),
                    "guard (inf noise) cells must agree")
    ok = np.isfinite(rs)
    test.assertTrue(
        np.all(np.abs(gd[ok] - rd[ok])
               <= ABS_TOL + REL_TOL * np.abs(rd[ok])),
        "depth agreement beyond reassociation tolerance")
    test.assertTrue(
        np.all(np.abs(gs[ok] - rs[ok])
               <= ABS_TOL + REL_TOL * np.abs(rs[ok])),
        "noise agreement beyond reassociation tolerance")
    # Guard cells return depth 0.0 exactly.
    test.assertTrue(np.all(gd[~ok] == 0.0))


class GridCalibration(unittest.TestCase):
    """Base: run under bulk_v4, restore the previous calibration."""

    def setUp(self):
        self._previous = bs.CALIBRATION_VERSION
        bs.set_calibration("bulk_v4")

    def tearDown(self):
        bs.set_calibration(self._previous)


class TestPartitionMedian(GridCalibration):
    def test_matches_np_median_bit_exact(self):
        rng = np.random.default_rng(11)
        for _ in range(200):
            n = int(rng.integers(1, 5000))
            a = rng.normal(0.0, 1.0, size=n)
            self.assertEqual(bs._partition_median(a.copy()),
                             float(np.median(a)))

    def test_single_element_and_pairs(self):
        self.assertEqual(bs._partition_median(np.array([3.5])), 3.5)
        self.assertEqual(bs._partition_median(np.array([1.0, 2.0])),
                         1.5)
        self.assertEqual(bs._partition_median(np.array([2.0, 1.0])),
                         1.5)


class TestFoldDepthGrid(GridCalibration):
    def test_transit_curve_full_grid(self):
        t, f = _box_curve(3.7, 5.2, 0.13, 0.01)
        durations = list(bs.BLS_DURATIONS_D)
        phases = np.linspace(-0.5, 0.5, 400, endpoint=False)
        grid = bs.fold_depth_grid(t, f, 3.7, 13.5, durations, phases)
        ref = _reference_grid(t, f, 3.7, 13.5, durations, phases)
        _assert_grid_equal(self, grid, ref)

    def test_randomised_sweep(self):
        # Periods x durations x phase grids x seeds: every cell
        # checked against the reference, including wrap-around
        # phases (pc = -0.5 is the first grid point).
        rng = np.random.default_rng(20261118)
        durations = list(bs.BLS_DURATIONS_D)
        for seed in (1, 2, 3):
            period = float(rng.uniform(0.6, 20.0))
            t, f = _box_curve(period, 5.2, 0.13, 0.01, seed=seed,
                              noise=float(rng.uniform(0.0005, 0.005)))
            phases = np.linspace(-0.5, 0.5, 120, endpoint=False)
            grid = bs.fold_depth_grid(t, f, period, 13.5, durations,
                                      phases)
            ref = _reference_grid(t, f, period, 13.5, durations,
                                  phases)
            _assert_grid_equal(self, grid, ref)

    def test_points_exactly_on_boundaries(self):
        # Cadences placed so their phases land exactly on inwin /
        # outwin boundary values (fp-exact multiples): the verified
        # searchsorted cut must agree with the predicate, not just
        # approximately.
        period, t0 = 2.0, 0.0
        # Phases at exact multiples of 0.05 in [-0.5, 0.5).
        ph = np.arange(-0.5, 0.5, 0.05)
        t = (ph + 0.5) * period + t0
        # Repeat each phase 40x with jitter below fp noise of the
        # boundary (jitter 0 keeps them exactly on the boundary).
        t = np.repeat(t, 40)
        rng = np.random.default_rng(5)
        f = 1.0 + rng.normal(0.0, 0.002, size=len(t))
        durations = [0.2, 0.1, 0.04]  # half = 0.05, 0.025, 0.01
        phases = np.array([-0.5, -0.25, 0.0, 0.25, 0.45])
        grid = bs.fold_depth_grid(t, f, period, t0, durations, phases)
        ref = _reference_grid(t, f, period, t0, durations, phases)
        _assert_grid_equal(self, grid, ref)

    def test_repeated_phases(self):
        # Quantised cadence times produce long runs of identical
        # phases (the failure mode the ulp-band verification was
        # written for): the cut must land on the run's edge, never
        # inside it or at a neighbouring transition.
        rng = np.random.default_rng(21)
        # Times on a coarse grid: only 200 distinct phases.
        t_base = np.arange(0.0, 27.0, 27.0 / 200)
        t = np.repeat(t_base, 40) + rng.uniform(0, 1e-9, 8000)
        t = np.sort(t)
        f = 1.0 + rng.normal(0.0, 0.002, size=len(t))
        phase = ((t - 5.2) / 3.7 + 0.5) % 1.0 - 0.5
        f[np.abs(phase) < 0.13 / (2 * 3.7)] -= 0.01
        durations = list(bs.BLS_DURATIONS_D)
        phases = np.linspace(-0.5, 0.5, 400, endpoint=False)
        grid = bs.fold_depth_grid(t, f, 3.7, 13.5, durations, phases)
        ref = _reference_grid(t, f, 3.7, 13.5, durations, phases)
        _assert_grid_equal(self, grid, ref)

    def test_guard_cells(self):
        # Tiny duration (inwin < 3 at most phases) and a duration so
        # wide that 2*half >= 0.45 (outwin empty): all guard cells.
        t, f = _box_curve(3.7, 5.2, 0.13, 0.01, n=2000)
        phases = np.linspace(-0.5, 0.5, 50, endpoint=False)
        grid = bs.fold_depth_grid(t, f, 3.7, 13.5, [0.001, 3.5],
                                  phases)
        ref = _reference_grid(t, f, 3.7, 13.5, [0.001, 3.5], phases)
        _assert_grid_equal(self, grid, ref)
        # The wide-duration row is all guard (outwin empty).
        self.assertTrue(np.all(np.isinf(grid[2][1])))

    def test_constant_flux_matches_reference(self):
        # Exactly constant data: np.std is 0.0, so every non-guard
        # cell has noise 0.0 in both implementations (the grid's
        # degenerate zero-variance guard exists for this case).
        t = np.arange(0.0, 27.0, 27.0 / 4000)
        f = np.ones_like(t)
        durations = list(bs.BLS_DURATIONS_D)
        phases = np.linspace(-0.5, 0.5, 100, endpoint=False)
        grid = bs.fold_depth_grid(t, f, 3.7, 13.5, durations, phases)
        ref = _reference_grid(t, f, 3.7, 13.5, durations, phases)
        _assert_grid_equal(self, grid, ref)
        self.assertTrue(np.all(grid[2][np.isfinite(grid[2])] == 0.0))

    def test_tiny_noise_transit(self):
        # Near-noiseless transit: outwin scatter 1e-5 (100x below
        # real QLP noise), real depth — the degenerate guard must
        # NOT zero a genuine variance. (At scatter << 1e-6 the
        # one-pass variance itself degrades by cancellation —
        # var << E[x^2] — which no float64 one-pass formula avoids;
        # real preprocessed curves have var/E[x^2] ~ 0.5-1.0, so
        # that regime is out of scope. See the fold_depth_grid
        # docstring.)
        t, f = _box_curve(3.7, 5.2, 0.13, 0.01, noise=1e-5, seed=9)
        durations = list(bs.BLS_DURATIONS_D)
        phases = np.linspace(-0.5, 0.5, 100, endpoint=False)
        grid = bs.fold_depth_grid(t, f, 3.7, 13.5, durations, phases)
        ref = _reference_grid(t, f, 3.7, 13.5, durations, phases)
        _assert_grid_equal(self, grid, ref)

    def test_deterministic(self):
        t, f = _box_curve(5.1, 7.7, 0.09, 0.008, seed=3)
        durations = list(bs.BLS_DURATIONS_D)
        phases = np.linspace(-0.5, 0.5, 200, endpoint=False)
        g1 = bs.fold_depth_grid(t, f, 5.1, 13.5, durations, phases)
        g2 = bs.fold_depth_grid(t, f, 5.1, 13.5, durations, phases)
        for a, b in zip(g1, g2):
            self.assertTrue(np.array_equal(a, b))

    def test_empty_and_single_phase(self):
        t, f = _box_curve(3.7, 5.2, 0.13, 0.01, n=1000)
        dep, nin, noi = bs.fold_depth_grid(t, f, 3.7, 13.5, [0.13],
                                           [0.0])
        self.assertEqual(dep.shape, (1, 1))
        d, n, s = bs._fold_depth(t, f, 3.7, 13.5, 0.13,
                                 phase_center=0.0)
        self.assertEqual(int(nin[0, 0]), n)
        self.assertAlmostEqual(float(dep[0, 0]), d, delta=1e-12)
        self.assertAlmostEqual(float(noi[0, 0]), s, delta=1e-12)
        dep, _, _ = bs.fold_depth_grid(t, f, 3.7, 13.5, [], [0.0])
        self.assertEqual(dep.shape, (0, 1))


# --- Reference (pre-optimisation) estimator loops, as the oracle ---
# Copied from bulk/k2_prototype.py at ff6fa31 (before the 4.1-8 grid
# change); the production code must match these bit-for-bit.

def _best_phase_snr_ref(t, f, period, t_ref, duration, n_phase):
    phases = np.linspace(-0.5, 0.5, n_phase, endpoint=False)
    best_snr, best_phase, best_depth = -np.inf, 0.0, 0.0
    for ph in phases:
        depth, n_in, noise = bs._fold_depth(
            t, f, period, t_ref, duration, phase_center=float(ph))
        if n_in < 2 or noise <= 0 or not np.isfinite(depth):
            continue
        snr = depth / noise
        if snr > best_snr:
            best_snr, best_phase, best_depth = snr, float(ph), \
                float(depth)
    if not np.isfinite(best_snr):
        return 0.0, 0.0, 0.0
    return best_phase, best_depth, float(best_snr)


def _estimate_ephemeris_ref(t, f, period_recorded):
    t = np.asarray(t, dtype=float)
    f = np.asarray(f, dtype=float)
    t_mid = 0.5 * (float(np.nanmin(t)) + float(np.nanmax(t)))
    df = k2.grid_df()
    f0 = 1.0 / float(period_recorded)
    _, _, snr_at_recorded = _best_phase_snr_ref(
        t, f, float(period_recorded), t_mid, k2.REFINE_DURATION_D,
        k2.N_PHASE_COARSE)
    best_period, best_snr = float(period_recorded), snr_at_recorded
    tried = []
    for j in range(-k2.REFINE_HALF_STEPS, k2.REFINE_HALF_STEPS + 1):
        if j == 0:
            continue
        fj = f0 + j * k2.REFINE_STEP_FRAC * df
        if fj <= 0:
            continue
        pj = 1.0 / fj
        _, _, snr_j = _best_phase_snr_ref(
            t, f, pj, t_mid, k2.REFINE_DURATION_D, k2.N_PHASE_COARSE)
        tried.append({"period_d": float(pj), "snr": float(snr_j)})
        if snr_j > best_snr:
            best_snr, best_period = snr_j, float(pj)
    if snr_at_recorded > 0:
        gain = (best_snr - snr_at_recorded) / snr_at_recorded
    else:
        gain = 0.0 if best_snr <= 0 else float("inf")
    refined = bool(best_period != float(period_recorded)
                   and gain >= k2.REFINE_MIN_GAIN)
    if not refined:
        best_period = float(period_recorded)
    durations = list(bs.BLS_DURATIONS_D)
    phases = np.linspace(-0.5, 0.5, k2.N_PHASE_FINE, endpoint=False)
    best = {"snr": -np.inf, "phase": 0.0, "duration": durations[0],
            "depth": 0.0}
    for dur in durations:
        for ph in phases:
            depth, n_in, noise = bs._fold_depth(
                t, f, best_period, t_mid, float(dur),
                phase_center=float(ph))
            if n_in < 2 or noise <= 0 or not np.isfinite(depth):
                continue
            snr = depth / noise
            if snr > best["snr"]:
                best = {"snr": float(snr), "phase": float(ph),
                        "duration": float(dur), "depth": float(depth)}
    if not np.isfinite(best["snr"]):
        best = {"snr": 0.0, "phase": 0.0, "duration": durations[0],
                "depth": 0.0}
    return {
        "period_recorded_d": float(period_recorded),
        "period_ref_d": float(best_period),
        "period_refined": bool(refined),
        "refine_snr_at_recorded": float(snr_at_recorded),
        "refine_snr_best": float(best_snr),
        "refine_snr_gain": float(gain),
        "refine_tried": tried,
        "t_ref_btjd": float(t_mid),
        "t0_est_btjd": float(t_mid + best["phase"] * best_period),
        "phase_est": float(best["phase"]),
        "duration_est_d": float(best["duration"]),
        "depth_est_frac": float(best["depth"]),
        "snr_est": float(best["snr"]),
        "low_snr": bool(best["snr"] < k2.LOW_SNR_FLAG),
    }


def _scan_secondary_ref(t, f, period, t0, duration):
    phases = np.linspace(k2.COMASK_PHASE_LO, k2.COMASK_PHASE_HI,
                         k2.N_PHASE_COMASK)
    best_snr, best_phase, best_depth = -np.inf, 0.5, 0.0
    for ph in phases:
        pc = float(ph) if ph < 0.5 else float(ph) - 1.0
        depth, n_in, noise = bs._fold_depth(
            t, f, period, t0, duration, phase_center=pc)
        if n_in < 2 or noise <= 0 or not np.isfinite(depth):
            continue
        snr = depth / noise
        if snr > best_snr:
            best_snr, best_phase, best_depth = snr, float(ph), \
                float(depth)
    if not np.isfinite(best_snr):
        return 0.5, 0.0, 0.0
    return best_phase, float(best_depth), float(best_snr)


class TestEstimatorEquivalence(GridCalibration):
    """estimate_ephemeris / scan_secondary must match the reference
    loops bit-for-bit (the two-pass selection recomputes the winner
    exactly, so this is equality, not tolerance)."""

    def _check_case(self, t, f, p_rec):
        new = k2.estimate_ephemeris(t, f, p_rec)
        old = _estimate_ephemeris_ref(t, f, p_rec)
        self.assertEqual(new, old)
        s_new = k2.scan_secondary(t, f, new["period_ref_d"],
                                  new["t0_est_btjd"],
                                  new["duration_est_d"])
        s_old = _scan_secondary_ref(t, f, old["period_ref_d"],
                                    old["t0_est_btjd"],
                                    old["duration_est_d"])
        self.assertEqual(s_new, s_old)

    def test_transit(self):
        t, f = _box_curve(3.7, 5.2, 0.13, 0.01)
        self._check_case(t, f, 3.7)

    def test_transit_with_secondary(self):
        t, f = _box_curve(13.0, 5.2, 0.09, 0.015,
                          secondary=(0.5, 0.008))
        self._check_case(t, f, 13.0)

    def test_off_grid_period_refines(self):
        df = k2.grid_df()
        p_rec = 1.0 / (1.0 / 13.0 + 1.0 * df)
        t, f = _box_curve(13.0, 5.2, 0.09, 0.015)
        self._check_case(t, f, p_rec)

    def test_shallow_signal(self):
        t, f = _box_curve(2.1, 3.0, 0.06, 0.0005, noise=0.001)
        self._check_case(t, f, 2.1)

    def test_noise_only(self):
        rng = np.random.default_rng(7)
        t = np.sort(rng.uniform(0, 27.0, 8000))
        f = 1.0 + rng.normal(0.0, 0.002, size=len(t))
        self._check_case(t, f, 3.7)

    def test_constant_flux(self):
        t = np.arange(0.0, 27.0, 27.0 / 8000)
        f = np.ones_like(t)
        self._check_case(t, f, 3.7)

    def test_short_and_long_periods(self):
        t, f = _box_curve(0.6, 5.2, 0.04, 0.02)
        self._check_case(t, f, 0.6)
        t, f = _box_curve(20.0, 5.2, 0.25, 0.02)
        self._check_case(t, f, 20.0)


if __name__ == "__main__":
    unittest.main()
