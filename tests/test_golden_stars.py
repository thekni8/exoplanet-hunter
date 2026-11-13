"""Download-backed golden tests: the pipeline end to end on known objects.

These are the tests that prove the SEARCH still works, not just the
plumbing. Each one downloads real TESS light curves (capped sectors,
tens of MB, cached by lightkurve for later runs) and runs the full
pipeline (`hunter._run_pipeline`) on a star whose answer is known:

* TOI-700 (TIC 150428135) — the multi-planet control. Planet c
  (P 16.05094 d) must come back as the headline signal. Planet b
  (P 9.97706 d) is checked in the BLS spectrum itself, not in the
  top-3 refined list: b ranks 12th–15th in the pipeline's own
  peak extraction (see the comment in hunter._bls_best), so
  top-3 membership is the wrong assertion for it — what matters
  is that the BLS stage still sees b as a significant peak
  (SDE above the pipeline's 6.5 acceptance floor). This is the
  star the 2026-11-13 BLS fix was built against: the old coarse
  grid locked onto the P/2 alias (8.026 d) and missed c entirely.
  If c stops being the headline, the grid or the refinement
  regressed.
* WASP-126 b (TIC 25155310) — the depth regression. The pipeline has
  always measured this transit at 0.631% (vs the 0.7006% TOI catalog
  value); a drift in the recovered depth means the search or the
  flattening changed. Period must match the published 3.286 d.
* TIC 308851365 — a known eclipsing binary (VSX: ECLIPSING BINARY).
  The pipeline must recover its 0.75677 d signal AND the trapezoid
  shape gate must call the folded transit V-shaped (T23/T14 <= 0.30),
  i.e. an EB suspect, not a planet. This guards the shape gate that
  caught the 423498314 grazing transit.

Run with the suite (`python tests/run_golden.py`) or directly:
`python -m unittest tests.test_golden_stars -v`. The `--fast` flag on
the runner skips this module (no downloads).

Tolerances are deliberately loose on period (0.05 d) and tight on
identity (the right star, the right signal, the right shape call):
a golden test guards against the pipeline finding the WRONG thing,
not against sub-percent numerical wobble.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402

import hunter  # noqa: E402
from gauntlet.rawflux_check import tic_density, trapezoid_shape_gate  # noqa: E402


def _near(periods, target, tol=0.05):
    """True if any period in the list is within tol days of target."""
    return any(abs(float(p) - target) <= tol for p in periods)


def _bls_sde_at(full, target, frac_tol=0.01):
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


class TestGoldenStars(unittest.TestCase):
    def test_toi700_c_headline_b_recovered(self):
        # TOI-700 is a 0.42 Rsun M dwarf; SPOC 2-min data. Two sectors
        # give ~3 transits of c — enough for the headline at SDE >> 8.5.
        full = hunter._run_pipeline("150428135", star_radius=0.42,
                                    max_sectors=2)
        self.assertAlmostEqual(full["Period"], 16.05094, delta=0.05,
                               msg=f"TOI-700 c not headline: "
                                   f"got P={full['Period']}")
        self.assertGreater(full["SDE"], 8.5)
        # b is a real peak in the BLS spectrum (measured SDE 8.4 with
        # 2 sectors) but ranks 12th-15th in extraction, so it never
        # reaches the top-3 refined list — assert the spectrum peak
        # against the pipeline's own 6.5 acceptance floor instead.
        b_sde = _bls_sde_at(full, 9.97706)
        self.assertGreater(
            b_sde, 6.5,
            msg=f"TOI-700 b (9.97706 d) not a significant BLS peak: "
                f"SDE {b_sde:.1f}")

    def test_wasp126_depth_regression(self):
        # QA benchmark setup: 1 sector, R* = 1.30 Rsun. Depth is the
        # pipeline's own long-standing measurement (0.631%), NOT the
        # catalog value — this test guards the pipeline against
        # itself, so the baseline is what the code has always found.
        full = hunter._run_pipeline("25155310", star_radius=1.30,
                                    max_sectors=1)
        self.assertAlmostEqual(full["Period"], 3.286, delta=0.05,
                               msg=f"WASP-126 b period wrong: "
                                   f"got P={full['Period']}")
        self.assertAlmostEqual(full["Depth"], 0.00631, delta=0.0015,
                               msg=f"WASP-126 b depth drifted: "
                                   f"got {full['Depth']:.5f} "
                                   f"(baseline 0.00631)")

    def test_eb_shape_gate_calls_v_shaped(self):
        # 6%-deep eclipses: one sector is plenty. The period check
        # proves the search found the signal; the shape gate must
        # then refuse to call it a planet.
        full = hunter._run_pipeline("308851365", star_radius=1.0,
                                    max_sectors=1)
        self.assertAlmostEqual(full["Period"], 0.75677, delta=0.01,
                               msg=f"EB period wrong: "
                                   f"got P={full['Period']}")
        rho_star, _src = tic_density("308851365")
        gate = trapezoid_shape_gate(
            full["raw_time"], full["raw_flux"],
            full["Period"], full["T0"], full["Duration_Days"],
            rho_star)
        self.assertEqual(gate.get("shape_verdict"), "V-shaped",
                         msg=f"shape gate did not call the EB "
                             f"V-shaped: {gate}")
        self.assertLessEqual(gate["T23_T14"], 0.30)


if __name__ == "__main__":
    unittest.main()
