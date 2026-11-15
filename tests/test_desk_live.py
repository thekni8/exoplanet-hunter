"""Live desk-gate tests (Phase 2, 2A) — DOWNLOAD-BACKED.

Runs the driver's clean-data re-fold gate on REAL S96 QLP light
curves, downloaded from MAST. The regression material is the
2026-11-14 rescore gauntlet's 25 leads:

  * TIC 355401152 (SDE 26.5, P 6.5138 d): the manual gauntlet
    killed it as a flagged-cadence artifact (signal only in
    bit-30 cadences, 0 clean in-transit). The automated gate
    must FAIL it.
  * TIC 382571558 (SDE 25.4, P 12.2903 d): same class (8.7%
    dip only in bit-29/30 cadences). Must FAIL.
  * TIC 183537452 (SDE 29.2, P 3.9227 d): TOI-192.01 = WASP-29b,
    a known planet bulk_v2 recovered — its signal is in CLEAN
    data. Must PASS (the control: the gate must not kill real
    planets).

Ephemerides are the rescore-v2 filed values (leads25.json).
Like test_golden_stars, this module is in DOWNLOAD_TESTS: it
runs in live.yml (weekly + on merge to main), never in the PR
gate. A failure here while the PR gate stays green means MAST
changed its data (or the gate regressed on real data — the
offline synthetic tests in test_desk.py distinguish the two).
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gauntlet.desk import LiveDataSource, clean_refold_native  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

# (tic, period_d, t0_btjd, duration_h, expected verdict)
CASES = [
    ("355401152", 6.513761467889909, 3914.255264976005, 3.168,
     "FAIL"),
    ("382571558", 12.290279627163782, 3908.9433141040063, 6.048,
     "FAIL"),
    ("183537452", 3.9226519337016574, 3910.099656135258, 2.208,
     "PASS"),
]


class TestDeskLive(unittest.TestCase):
    def test_clean_gate_on_real_leads(self):
        source = LiveDataSource(repo_root=str(ROOT))
        for tic, period, t0, dur_h, expected in CASES:
            with self.subTest(tic=tic):
                got = source.discovery_lc(tic, 96)
                self.assertIsNotNone(
                    got, f"TIC {tic}: no S96 QLP light curve")
                t, f, q = got
                fold, verdict = clean_refold_native(
                    t, f, q, period, t0, dur_h)
                self.assertEqual(
                    verdict, expected,
                    msg=f"TIC {tic}: clean fold {fold}")


if __name__ == "__main__":
    unittest.main()
