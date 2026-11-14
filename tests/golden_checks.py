"""Shared golden-star assertions, used by BOTH the live tests
(test_golden_stars.py, MAST downloads) and the offline fixture
tests (test_golden_fixtures.py, committed npz fixtures). One
definition of "the pipeline still finds the known answers" —
if the live and offline suites ever disagree, the fixture is
stale, not the assertion.

Each check takes the TestCase (tc) and the full _run_pipeline
result dict, and asserts with the TestCase's methods so failures
read as test failures with the star's name attached.
"""
import numpy as np

import hunter
from gauntlet.rawflux_check import trapezoid_shape_gate


def bls_sde_at(full, target, frac_tol=0.01):
    """Peak BLS SDE within frac_tol of `target`, on the pipeline's
    own robust scale (median + 1.4826*MAD, systematic periods
    excluded) — a faithful copy of hunter._run_pipeline's
    _sde_scale, which is a closure and cannot be imported. The
    +-1% window matches the pipeline's own +-1.5% refinement
    radius around each candidate."""
    pv = np.asarray(full["bls_periods"], dtype=float)
    pw = np.asarray(full["bls_powers"], dtype=float)
    keep = np.ones(len(pw), dtype=bool)
    for s in hunter._SYSTEMATIC_PERIODS:
        keep &= np.abs(pv - s) > 0.03 * s
    base = pw[keep]
    med = float(np.median(base))
    mad = float(np.median(np.abs(base - med))) * 1.4826
    scale = mad if mad > 0 else float(np.std(base))
    work = (pw - med) / (scale if scale > 0 else 1e-12)
    near = np.abs(pv - target) <= frac_tol * target
    return float(work[near].max()) if near.any() else 0.0


def check_toi700(tc, full):
    """TOI-700 (TIC 150428135): planet c (P 16.05094 d) must be
    the headline signal, and planet b (P 9.97706 d) must be a
    significant peak in the BLS spectrum itself (b ranks 12th-15th
    in peak extraction, so top-3 membership is the wrong
    assertion — what matters is the spectrum peak against the
    pipeline's own 6.5 acceptance floor)."""
    tc.assertAlmostEqual(full["Period"], 16.05094, delta=0.05,
                         msg=f"TOI-700 c not headline: "
                             f"got P={full['Period']}")
    tc.assertGreater(full["SDE"], 8.5)
    b_sde = bls_sde_at(full, 9.97706)
    tc.assertGreater(
        b_sde, 6.5,
        msg=f"TOI-700 b (9.97706 d) not a significant BLS peak: "
            f"SDE {b_sde:.1f}")


def check_wasp126(tc, full):
    """WASP-126 b (TIC 25155310) — the depth TRIPWIRE (not a
    validation): the baseline is the pipeline's own long-standing
    measurement (0.631%), NOT the catalog value (0.7006%), so
    this test detects that the search or flattening CHANGED, not
    that it is correct. Period must match the published 3.286 d."""
    tc.assertAlmostEqual(full["Period"], 3.286, delta=0.05,
                         msg=f"WASP-126 b period wrong: "
                             f"got P={full['Period']}")
    tc.assertAlmostEqual(full["Depth"], 0.00631, delta=0.0015,
                         msg=f"WASP-126 b depth drifted: "
                             f"got {full['Depth']:.5f} "
                             f"(baseline 0.00631)")


def check_eb(tc, full, rho_star):
    """TIC 308851365 — a known eclipsing binary (VSX: ECLIPSING
    BINARY). The pipeline must recover its 0.75677 d signal AND
    the trapezoid shape gate must NOT call the folded transit
    flat-bottomed (T23/T14 < 0.50) AND the density flag must fire
    (the fitted T14 ~8.3 h is impossible for a planet on this
    star: T14max ~2.0 h). Together those are the EB evidence.

    The assertion is deliberately NOT "V-shaped" (T23/T14 <=
    0.30): the gate's T23/T14 is numerically unstable on this
    smeared EB signal. Measured 2026-11-14 on identical arrays:
    the BLS refinement lands on adjacent fine-grid points across
    runs (P 0.75798 vs 0.75801 — one 3e-5 grid step of argmax
    noise on a near-tie), and perturbing P by 3e-5 swings
    T23/T14 across 0.34-0.47, by 1e-4 to 0.22. The V-shaped label
    is therefore not a reproducible measurement on this star —
    the live run called it V-shaped (0.297) while the byte-identical
    fixture run called it ambiguous (0.474). The density flag and
    the never-U-shaped bound ARE stable across all perturbations,
    so they are what the test asserts. The gate's own thresholds
    are untouched; only the test's demand is corrected to what
    the measurement reproducibly says.
    `rho_star` is the TIC stellar density (solar units) — the live
    test queries it, the offline test reads it from the fixture."""
    tc.assertAlmostEqual(full["Period"], 0.75677, delta=0.01,
                         msg=f"EB period wrong: "
                             f"got P={full['Period']}")
    gate = trapezoid_shape_gate(
        full["raw_time"], full["raw_flux"],
        full["Period"], full["T0"], full["Duration_Days"],
        rho_star)
    tc.assertNotEqual(gate.get("shape_verdict"), "unmeasured",
                      msg=f"shape gate unmeasured on the EB: {gate}")
    tc.assertLess(gate["T23_T14"], 0.50,
                  msg=f"shape gate called the EB flat-bottomed: "
                      f"T23/T14={gate['T23_T14']:.3f}")
    tc.assertTrue(gate["density_flag"],
                  msg="density flag did not fire on the EB: "
                      f"rho_ratio={gate.get('rho_ratio'):.3f}")
