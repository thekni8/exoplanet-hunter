"""Driver-wiring tests for bulk/p43_run.py (P4-3).

Offline: synthetic arrays only, no downloads, no Mac, no BLS
screen. These pin the two defects the 2026-11-18 smoke test
caught (both would otherwise fail silently in the trial records):

1. check_recovery lives in bulk.inject_campaign, NOT in
   injection_harness -- the smoke's 24/24 stitched trials errored
   with AttributeError: module 'injection_harness' has no
   attribute 'check_recovery' because the driver called
   ih.check_recovery. The import is pinned here.
2. The mask-seed diagnostic built a recorded-period mask even
   when the fresh peak was not eligible (no fresh mask) -- which
   manufactured a jaccard_dropped of 0.0 out of an eligibility
   difference, not a seed difference. The diagnostic must return
   "fresh-not-masked" then.
"""

import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bulk import inject_campaign as ic  # noqa: E402
from bulk import k2_prototype as k2  # noqa: E402
from bulk import oracle_run as orc  # noqa: E402
from bulk import p43_run  # noqa: E402

CADENCE_D = 1.0 / 48.0


def _synth_sector(t0, n, period, epoch, depth, duration, sigma, rng):
    t = t0 + CADENCE_D * np.arange(n)
    f = 1.0 + rng.normal(0.0, sigma, n)
    q = np.zeros(n, dtype=int)
    k_min = int(np.ceil((t[0] - epoch) / period))
    k_max = int(np.floor((t[-1] - epoch) / period))
    for k in range(k_min, k_max + 1):
        tc = epoch + k * period
        m = np.abs(t - tc) <= duration / 2.0
        f[m] -= depth
    return t, f, q


class TestCheckRecoveryImport(unittest.TestCase):
    def test_driver_uses_inject_campaign_check_recovery(self):
        # Regression: the driver called ih.check_recovery, but
        # check_recovery lives in bulk.inject_campaign (k3_run
        # imports it from there). injection_harness has no such
        # attribute -- every stitched trial errored in the smoke.
        self.assertIs(p43_run.check_recovery, ic.check_recovery)
        self.assertTrue(callable(p43_run.check_recovery))

    def test_no_ih_check_recovery_reference(self):
        # The exact bug class: a bare "ih.check_recovery" in the
        # driver source. (ih is injection_harness here.)
        src = Path(p43_run.__file__).read_text()
        self.assertNotIn("ih.check_recovery", src)


class TestMaskSeedDiagnostic(unittest.TestCase):
    def _fresh_mask(self, period=3.0, depth_pct=2.0):
        rng = np.random.default_rng(7)
        t, f, q = _synth_sector(3800.0, 1300, period, 3801.0, 0.02,
                                0.12, 0.005, rng)
        t_p, f_p = orc.preprocess_arrays(t, f, q)
        eph = k2.estimate_ephemeris(t_p, f_p, period)
        sec = k2.scan_secondary(t_p, f_p, eph["period_ref_d"],
                                eph["t0_est_btjd"],
                                eph["duration_est_d"])
        keep, mstats = k2.build_k2_mask(
            t, f, q, eph, depth_pct, secondary=sec, duty_cap=0.25,
            depth_trigger=False)
        return t, f, q, keep, mstats, eph

    def test_fresh_not_masked_returns_note(self):
        rng = np.random.default_rng(8)
        t, f, q = _synth_sector(3800.0, 1300, 3.0, 3801.0, 0.005,
                                0.12, 0.005, rng)
        trial = {"recorded": {"period_days": 3.0}}
        fresh_rec = {"pass1": {"period_days": 3.0,
                               "depth_percent": 0.5},
                     "k2_mask": None}
        out = p43_run._mask_seed_diagnostic(t, f, q, trial,
                                            fresh_rec, None)
        self.assertEqual(out["note"], "fresh-not-masked")
        self.assertIsNone(out["duty_recorded"])
        self.assertIsNone(out["jaccard_dropped"])
        self.assertAlmostEqual(out["period_diff_pct"], 0.0)

    def test_agreeing_seeds_agree(self):
        t, f, q, keep, mstats, _eph = self._fresh_mask()
        trial = {"recorded": {"period_days": 3.0}}
        fresh_rec = {"pass1": {"period_days": 3.0,
                               "depth_percent": 2.0},
                     "k2_mask": mstats}
        out = p43_run._mask_seed_diagnostic(t, f, q, trial,
                                            fresh_rec, keep)
        self.assertAlmostEqual(out["period_diff_pct"], 0.0,
                               delta=0.5)
        self.assertIsNotNone(out["duty_recorded"])
        # Same seed period -> the two masks agree (jaccard ~1).
        self.assertGreater(out["jaccard_dropped"], 0.9)


if __name__ == "__main__":
    unittest.main()
