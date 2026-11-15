"""Injection into a REAL S96 light curve, deep pipeline
(deep_v2 sensitivity re-measurement, 2026-11-15).

The deep mirror of the bulk M-6 test (test_inject_real_s96.py):
one injection-recovery into a real S96 light curve carrying
bits 29/30 flags, deep_v1 vs deep_v2, through the REAL
hunter._run_pipeline via the fixture seam. The substrate is
TIC 31852076 (committed, tests/fixtures/injection/
substrate_s96_31852076.npz — shared with the bulk test):
28.0% of its cadences carry bit 29 and 9.9% carry bit 30.

The full run (bulk/inject_deep_real_s96.py, 6 stars x 2
trials) is recorded in
bulk/inject_deep_real_s96_summary.json: deep_v1 recovered
0/12, deep_v2 recovered 7/12. The v1 story is not false
positives — on 5 of 6 hosts the unmasked pipeline's BLS
periodogram is degenerate (SDE NaN, period pinned at the
25 d search ceiling), so it finds nothing at all; the
bit-29/30 cadences destroy sensitivity, they do not just add
artifacts. Two of the five v2 misses are harmonic aliases
of the injected signal (3:2, 2:1), so v2 detects 9/12.

This test pins trial B on 31852076 (1.0% @ 3.317 d): under
deep_v1 the pipeline finds nothing (measured P=25.0, SDE
NaN); under deep_v2 it recovers the transit (measured
P=3.3165, SDE 48.1). Trial A on this host is NOT pinned:
under v2 it lands on the 3:2 alias (7.683 d, SDE 25.5) —
detected, but not recovered by the headline criterion.
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402

import hunter  # noqa: E402
import injection_harness as ih  # noqa: E402
from bulk.inject_deep_real_s96 import TRIALS, write_fixture  # noqa: E402
from tests.calibration_guard import DeepCalibrationGuardCase  # noqa: E402

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "injection"
SUBSTRATE = FIXTURE_DIR / "substrate_s96_31852076.npz"
TIC = "31852076"
# Trial B (see the module docstring): the pinned trial.
_LABEL, DEPTH, PERIOD, EPOCH_OFF = TRIALS[1]
RECOVERY_TOL = 0.01


class TestInjectDeepRealS96(DeepCalibrationGuardCase):
    def setUp(self):
        super().setUp()
        self._prev_env = os.environ.get("EXHUNT_FIXTURE_DIR")
        self._td = tempfile.TemporaryDirectory()
        os.environ["EXHUNT_FIXTURE_DIR"] = self._td.name

    def tearDown(self):
        # No manual calibration restore: the runs switch
        # through calibration_context, which restores in a
        # finally block; the guard base class asserts deep_v2
        # is back after every test.
        if self._prev_env is None:
            os.environ.pop("EXHUNT_FIXTURE_DIR", None)
        else:
            os.environ["EXHUNT_FIXTURE_DIR"] = self._prev_env
        self._td.cleanup()

    def test_host_carries_bits_29_and_30(self):
        d = np.load(SUBSTRATE)
        q = np.asarray(d["q"])
        self.assertGreater((((q >> 29) & 1).sum()) / len(q), 0.05)
        self.assertGreater((((q >> 30) & 1).sum()) / len(q), 0.05)
        meta = json.loads(str(d["meta_json"]))
        self.assertEqual(meta["tic"], TIC)
        self.assertEqual(meta["sector"], 96)

    def test_v2_recovers_what_v1_cannot_find(self):
        # The measured run (bulk/inject_deep_real_s96_summary.json,
        # star 31852076 trial B): v1 P=25.0 SDE NaN (not
        # recovered), v2 P=3.3165 SDE 48.1 (recovered). The
        # assertions pin the verdicts, not the exact numbers —
        # the v1 half asserts NOT-recovered, so a future
        # pipeline change that made v1 find it would fail here
        # rather than pass vacuously.
        d = np.load(SUBSTRATE)
        t = np.asarray(d["t"], dtype=float)
        f = np.asarray(d["f"], dtype=float)
        q = np.asarray(d["q"], dtype=np.int64)
        epoch = float(np.nanmin(t)) + EPOCH_OFF
        f_inj, _dur = ih.inject_transit(t, f, DEPTH, PERIOD, epoch)
        write_fixture(self._td.name, TIC, t, f_inj, q)

        def _recovered(result):
            found = result.get("Period")
            return (
                found is not None
                and abs(found - PERIOD) / PERIOD < RECOVERY_TOL
                and result.get("SDE", 0.0) >= hunter.HIT_SDE)

        with hunter.calibration_context("deep_v1"):
            v1 = hunter._run_pipeline(TIC, star_radius=1.0,
                                      max_sectors=None)
        self.assertFalse(_recovered(v1),
                         f"v1 unexpectedly recovered: {v1}")
        with hunter.calibration_context("deep_v2"):
            v2 = hunter._run_pipeline(TIC, star_radius=1.0,
                                      max_sectors=None)
        self.assertTrue(_recovered(v2), f"v2 missed: {v2}")
        self.assertAlmostEqual(v2["Period"], PERIOD,
                               delta=RECOVERY_TOL * PERIOD)
        self.assertGreaterEqual(v2["SDE"], hunter.HIT_SDE)


if __name__ == "__main__":
    unittest.main()
