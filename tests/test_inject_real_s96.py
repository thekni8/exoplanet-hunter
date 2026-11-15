"""Injection into a REAL S96 light curve (mask-fix follow-up M-6).

Claude's item (d): one injection-recovery into a real S96 light
curve carrying bits 29/30 flags, v2 vs v3. The substrate is
TIC 31852076 (committed, tests/fixtures/injection/
substrate_s96_31852076.npz): 28.0% of its cadences carry bit 29
and 9.9% carry bit 30 -- the most heavily flagged of the six VM
S96 files, and the star where v3's win is largest.

The full run (bulk/inject_real_s96.py, 6 stars x 2 trials) is
recorded in bulk/inject_real_s96_summary.json: v2 recovered
2/12, v3 recovered 8/12, v3 lost 0/12 relative to v2. The 4 v3
non-recoveries are host-confusion (BLS finds the host's own
stronger signal under BOTH calibrations), not mask losses.
This test pins the headline on one star, both trials: under v2
the 13.1 d flagged-cadence systematic wins BLS and DEPTH_EB
demotes the star; under v3 the mask removes the systematic and
both injected transits recover.
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
from bulk.inject_real_s96 import (TRIALS, load_real_fits,  # noqa: E402
                                  write_injected_fits)
from synth_fits import screen_job  # noqa: E402

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "injection"
SUBSTRATE = FIXTURE_DIR / "substrate_s96_31852076.npz"


class TestInjectRealS96(unittest.TestCase):
    def setUp(self):
        self._previous = bs.CALIBRATION_VERSION

    def tearDown(self):
        bs.set_calibration(self._previous)

    def test_host_carries_bits_29_and_30(self):
        d = np.load(SUBSTRATE)
        q = np.asarray(d["q"])
        self.assertGreater((((q >> 29) & 1).sum()) / len(q), 0.05)
        self.assertGreater((((q >> 30) & 1).sum()) / len(q), 0.05)
        meta = json.loads(str(d["meta_json"]))
        self.assertEqual(meta["tic"], "31852076")
        self.assertEqual(meta["sector"], 96)

    def test_v3_recovers_what_v2_demotes(self):
        d = np.load(SUBSTRATE)
        t = np.asarray(d["t"], dtype=float)
        f = np.asarray(d["f"], dtype=float)
        q = np.asarray(d["q"], dtype=np.int64)
        meta = json.loads(str(d["meta_json"]))
        fcol = meta["flux_col"]
        job_meta = {"ra": meta.get("ra"), "dec": meta.get("dec"),
                    "tmag": meta.get("tmag"), "radius": None}
        with tempfile.TemporaryDirectory() as td:
            for label, depth, period, epoch_off in TRIALS:
                epoch = float(np.nanmin(t)) + epoch_off
                f_inj, _dur = ih.inject_transit(t, f, depth, period,
                                                epoch)
                path = Path(td) / f"inj{label}.fits"
                write_injected_fits(path, t, f_inj, q, fcol)
                bs.set_calibration("bulk_v2")
                v2 = bs._screen_one(screen_job(
                    path, tic="31852076", sector=96, meta=job_meta))
                # v2: the 13.1 d flagged-cadence systematic wins
                # BLS and the DEPTH_EB veto demotes the star.
                self.assertEqual(v2["status"], "demoted", label)
                self.assertIn("DEPTH_EB", v2["flags"], label)
                bs.set_calibration("bulk_v3")
                v3 = bs._screen_one(screen_job(
                    path, tic="31852076", sector=96, meta=job_meta))
                self.assertEqual(v3["status"], "survivor", label)
                self.assertIsNotNone(v3["period_days"], label)
                self.assertAlmostEqual(v3["period_days"], period,
                                       delta=0.01 * period, msg=label)


if __name__ == "__main__":
    unittest.main()
