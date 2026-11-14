"""False-positive fixtures: the pipeline must kill known junk.

No downloads. The golden suite proves the pipeline FINDS real
planets; these fixtures prove it REJECTS known false positives —
the failure mode Phase 2 (automated vetting) makes more likely.
Each fixture is a synthetic QLP FITS with a labelled signal, run
through the real screen and gauntlet code:

  * odd/even EB — killed by the screen's ODD_EVEN_EB veto.
  * equal-secondary EB — the screen promotes it at HALF the true
    period (pinned limitation: BLS takes the P/2 alias when the
    eclipses are equal); the gauntlet's 2x parity check measures
    EQUAL depths (honest: odd/even cannot exclude it) and the
    trapezoid shape gate kills it (V-shaped + density flag).
  * 14.4-day artifact — the screen PROMOTES it (pinned: the
    14.4 d pile-up is real, and 14.4 d falls outside the 13.7 d
    systematic family's +-3% window, so near_systematic is False).
    The recalibration step is the defense, not the screen.
  * flagged-cadence spike (TIC 344334378 class) — under bulk_v2
    the screen promotes it (its 17087 bitmask keeps bit-30
    cadences) and the clean-data re-fold gate FAILs it; under
    bulk_v3 the screen does NOT promote it (the v3 mask excludes
    bits 29/30 at screen input, so the dip never reaches BLS).
  * pure noise — the screen must not promote noise.

Where the pinned behaviour is a LIMITATION rather than a kill,
the test says so in its comment: pinning current behaviour is
what makes a future fix (or a silent regression) visible.
"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np  # noqa: E402
from astropy.io import fits  # noqa: E402

from bulk.clean_refold_gate import (clean_fold, load_fits,  # noqa: E402
                                    verdict_for)
from bulk_screen import _screen_one  # noqa: E402
import bulk_screen as bs  # noqa: E402
from gauntlet.common import event_parity_depths  # noqa: E402
from gauntlet.rawflux_check import trapezoid_shape_gate  # noqa: E402
from synth_fits import make_qlp_fits, screen_job  # noqa: E402


def _screen(path):
    return _screen_one(screen_job(path))


def _load_arrays(path):
    with fits.open(path) as hdul:
        d = hdul[1].data
        return (np.asarray(d["TIME"], dtype=float),
                np.asarray(d["KSPSAP_FLUX"], dtype=float))


class TestFalsePositives(unittest.TestCase):
    def test_odd_even_eb_demoted_by_screen(self):
        # Alternating 2% / 0.8% dips every 12 d: the true EB
        # period is 24 d, outside the screen's 20 d search range,
        # so BLS finds the 12 d half-period under BOTH
        # calibrations and the screen's free veto must fire
        # ODD_EVEN_EB and demote the star. (The record still
        # carries a tier under v2 — tier is computed before
        # demotion; status is what the gauntlet reads.)
        #
        # Why 12 d and not 3 d: with 3 d spacing the true period
        # (6 d) is in range, and whether BLS finds the half- or
        # the true period depends on the clip — under v1 the clip
        # degrades the deep family enough that 3 d wins and the
        # veto fires, while under v2 the clean signal finds 6 d
        # and the veto never applies (see
        # test_deep_eb_found_at_true_period_under_v2). The veto
        # itself is calibration-independent; only the period BLS
        # prefers changes.
        with tempfile.TemporaryDirectory() as td:
            p = make_qlp_fits(Path(td) / "eb.fits", period_d=12.0,
                              depth_frac=0.02, duration_d=0.1,
                              noise_pct=0.005, odd_even_ratio=0.4,
                              seed=42)
            r = _screen(p)
            self.assertEqual(r["status"], "demoted")
            self.assertIn("ODD_EVEN_EB", r["flags"])
            self.assertAlmostEqual(r["period_days"], 12.0, delta=0.05)

    def test_deep_eb_found_at_true_period_under_v2(self):
        # The 3 d-spacing EB (alternating 2% / 0.8%) under v2:
        # the floored clip preserves the deep transits, so BLS
        # finds the TRUE 6 d period with the 2% family alone
        # (odd/even ratio 0.96 — the veto is a half-period check
        # and does not apply), and the 0.8% secondary is measured
        # and recorded (0.78%) but below the 80%-of-primary bar,
        # so the star survives the screen. Under v1 the same star
        # demotes: the clip degrades the deep family, BLS finds
        # 3 d, and the odd/even veto fires. This is the known
        # v2 behaviour, pinned — the screen is a net, not a
        # verdict, and the gauntlet's secondary/parity checks are
        # the defence for true-period EBs that survive it.
        with tempfile.TemporaryDirectory() as td:
            p = make_qlp_fits(Path(td) / "eb.fits", period_d=3.0,
                              depth_frac=0.02, duration_d=0.1,
                              noise_pct=0.005, odd_even_ratio=0.4,
                              seed=42)
            previous = bs.CALIBRATION_VERSION
            try:
                bs.set_calibration("bulk_v1")
                r1 = _screen(p)
                self.assertEqual(r1["status"], "demoted")
                self.assertIn("ODD_EVEN_EB", r1["flags"])
                bs.set_calibration("bulk_v2")
                r2 = _screen(p)
                self.assertEqual(r2["status"], "survivor")
                self.assertAlmostEqual(r2["period_days"], 6.0,
                                       delta=0.05)
                self.assertAlmostEqual(
                    r2["secondary_depth_percent"], 0.78, delta=0.1)
            finally:
                bs.set_calibration(previous)

    def test_odd_even_parity_separates_families(self):
        # The gauntlet's 2x check on the same EB: folding at the
        # true period, the odd and even families must measure
        # clearly DIFFERENT depths (2% vs 0.8%).
        with tempfile.TemporaryDirectory() as td:
            p = make_qlp_fits(Path(td) / "eb.fits", period_d=3.0,
                              depth_frac=0.02, duration_d=0.1,
                              noise_pct=0.005, odd_even_ratio=0.4,
                              seed=42)
            t, f = _load_arrays(p)
            odd, even = event_parity_depths(t, f, 3.0, 1502.0, 0.1)
            self.assertIsNotNone(odd)
            self.assertIsNotNone(even)
            # Even events carry the full 2% depth, odd events the
            # 0.8% depth (odd_even_ratio=0.4 in the fixture).
            self.assertAlmostEqual(odd["depth_pct"], 0.8, delta=0.5)
            self.assertAlmostEqual(even["depth_pct"], 2.0, delta=0.5)
            self.assertGreater(abs(odd["depth_pct"]
                                   - even["depth_pct"]), 0.8)

    def test_equal_secondary_eb_alias_then_density_kill(self):
        # Equal 2% primary + secondary at 3 d. BLS takes the P/2
        # alias (1.5 d) — the screen PROMOTES it, and that is the
        # pinned limitation: no screen veto can see an equal EB
        # at half period. The gauntlet must do the work: the 2x
        # parity check measures EQUAL depths (odd/even cannot
        # exclude it — honest, per the 2P-check lesson), and the
        # shape gate is honest too — a box eclipse IS flat-bottomed
        # (U-shaped, T23/T14 0.62), so shape alone cannot kill it.
        # The kill is the DENSITY check: at the P/2 alias the
        # transit (T14 2.9 h) is far too long for the period and
        # stellar density (T14max 1.7 h), so density_flag fires.
        with tempfile.TemporaryDirectory() as td:
            p = make_qlp_fits(Path(td) / "eb.fits", period_d=3.0,
                              depth_frac=0.02, duration_d=0.1,
                              noise_pct=0.005,
                              secondary_depth_frac=0.02, seed=42)
            r = _screen(p)
            self.assertEqual(r["status"], "survivor")
            self.assertAlmostEqual(r["period_days"], 1.5, delta=0.05)
            t, f = _load_arrays(p)
            odd, even = event_parity_depths(t, f, 3.0, 1502.0, 0.1)
            combined_sig = np.sqrt(odd["sig_white_pct"] ** 2
                                   + even["sig_white_pct"] ** 2)
            self.assertLess(abs(odd["depth_pct"]
                                - even["depth_pct"]),
                            3.0 * combined_sig)
            gate = trapezoid_shape_gate(
                t, f, r["period_days"], r["t0_btjd"],
                r["duration_hours"] / 24.0, 2.7)
            self.assertEqual(gate.get("shape_verdict"), "U-shaped")
            self.assertTrue(gate["density_flag"])

    def test_14day_artifact_pinned(self):
        # A 14.4 d periodic dip (the S98 pile-up class): the screen
        # PROMOTES it — this pins current behaviour, it is not a
        # kill. Note near_systematic is False: 14.4 d falls outside
        # the 13.7 d family's +-3% window, so the screen does not
        # flag it. If a future calibration adds 14.4 d to the
        # systematic family, this test goes red deliberately.
        with tempfile.TemporaryDirectory() as td:
            p = make_qlp_fits(Path(td) / "pileup.fits", period_d=14.4,
                              depth_frac=0.009, duration_d=0.15,
                              noise_pct=0.002, seed=42)
            r = _screen(p)
            self.assertEqual(r["status"], "survivor")
            self.assertEqual(r["tier"], "B")
            self.assertAlmostEqual(r["period_days"], 14.4, delta=0.1)
            self.assertFalse(r["near_systematic"])

    def test_flagged_cadence_signal_gate_fails(self):
        # TIC 344334378 class: the dip exists only on quality-bit-30
        # cadences. BEHAVIOUR CHANGE (bulk_v3, 2026-11-15): under
        # bulk_v2 the screen's 17087 bitmask keeps those cadences,
        # so the screen PROMOTES the signal — and the clean-data
        # re-fold gate (v3 mask excludes bit 30) FAILs it. Under
        # bulk_v3 the screen mask excludes bits 29/30 at input, so
        # the screen itself rejects the signal (below the record
        # floor) and the gate is never needed. The gate's FAIL
        # verdict is still pinned on the v2-promoted signal: the
        # gate is the second line of defence, unchanged by v3.
        with tempfile.TemporaryDirectory() as td:
            p = make_qlp_fits(Path(td) / "flag.fits", period_d=2.0,
                              depth_frac=0.01, duration_d=0.15,
                              noise_pct=0.003, seed=42,
                              flagged_only_frac=0.7)
            previous = bs.CALIBRATION_VERSION
            try:
                bs.set_calibration("bulk_v2")
                r = _screen(p)
                self.assertEqual(r["status"], "survivor")
                bs.set_calibration("bulk_v3")
                r3 = _screen(p)
                self.assertEqual(r3["status"], "below_floor")
                self.assertLess(r3["sde"], 6.0)
            finally:
                bs.set_calibration(previous)
            t, f, q, _col = load_fits(str(p))
            fold = clean_fold(t, f, q, r["period_days"],
                              r["t0_btjd"], r["duration_hours"])
            self.assertGreaterEqual(fold["n_in"], 20)
            self.assertGreaterEqual(fold["n_events"], 2)
            self.assertEqual(verdict_for(fold, 3.0), "FAIL")

    def test_bit12_transit_passes_gate(self):
        # M-2 (ChatGPT's catch, 2026-11-15 vote): a genuine transit
        # whose in-transit cadences ALL carry quality bit 12
        # (Straylight2, 4096 -- the TOI-700 c lesson). The screen
        # keeps bit-12 cadences under every calibration, so it
        # promotes the signal; the gate must then PASS it, not
        # stall it. Under the gate's old quality==0 definition of
        # "clean" this fixture folded to zero clean in-transit
        # cadences (INSUFFICIENT -> UNMEASURED at the clean_refold
        # stage, promotion-blocking). The all-bits control below
        # pins that old behaviour so the regression stays visible.
        with tempfile.TemporaryDirectory() as td:
            p = make_qlp_fits(Path(td) / "bit12.fits", period_d=2.0,
                              depth_frac=0.01, duration_d=0.15,
                              noise_pct=0.003, seed=42,
                              quality=lambda t, in_tr: np.where(
                                  in_tr, 4096, 0))
            previous = bs.CALIBRATION_VERSION
            try:
                bs.set_calibration("bulk_v3")
                r = _screen(p)
            finally:
                bs.set_calibration(previous)
            self.assertEqual(r["status"], "survivor")
            t, f, q, _col = load_fits(str(p))
            fold = clean_fold(t, f, q, r["period_days"],
                              r["t0_btjd"], r["duration_hours"])
            self.assertGreaterEqual(fold["n_in"], 20)
            self.assertGreaterEqual(fold["n_events"], 2)
            self.assertEqual(verdict_for(fold, 3.0), "PASS")
            # Control: quality==0 semantics (every flag drops the
            # cadence) collapse the fold -- the old failure. n_in
            # is not exactly 0: the BLS duration is approximate,
            # so the fold window catches a couple of unflagged edge
            # cadences outside the true transit. The point is it
            # collapses from ~90 to a handful, far below MIN_IN.
            fold_old = clean_fold(t, f, q, r["period_days"],
                                  r["t0_btjd"], r["duration_hours"],
                                  quality_mask=0xFFFFFFFF)
            self.assertLess(fold_old["n_in"], 20)
            self.assertEqual(verdict_for(fold_old, 3.0), "INSUFFICIENT")

    def test_pure_noise_not_promoted(self):
        # Control: pure noise must not reach the survivor bar on
        # any of three seeds (SDE stays under the 6.0 record floor).
        with tempfile.TemporaryDirectory() as td:
            for seed in (42, 7, 123):
                p = make_qlp_fits(Path(td) / f"n{seed}.fits",
                                  period_d=None, noise_pct=0.003,
                                  seed=seed)
                r = _screen(p)
                self.assertNotEqual(r["status"], "survivor")
                self.assertLess(r["sde"], 6.0)


if __name__ == "__main__":
    unittest.main()
