"""Live concordance replay (Phase 2 vote follow-up P-12) —
DOWNLOAD-BACKED.

Replays all 25 hand-vetted rescore-v2 S96 leads through the
automated desk driver on REAL MAST data and asserts
concordance with the manual verdicts (18 flagged-cadence
artifacts, 4 single-event/weak dips, 1 catalogued planet,
1 era-confined V-shaped lead). TIC 307433122 (harmonic
alias) is the EXPECTED MISMATCH — its outcome is recorded,
never asserted.

Like test_golden_stars, this module is in DOWNLOAD_TESTS: it
runs in live.yml (weekly + on merge to main), never in the
PR gate. The full replay takes ~1-2 h (one desk run per
lead, MAST downloads + BLS refines); for a subset use
scripts/concordance_replay.py --only TIC,... directly.
"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent
                       / "scripts"))

from concordance_replay import load_fixture, run_replay  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


class TestConcordanceLive(unittest.TestCase):
    def test_full_replay_agrees_with_manual_verdicts(self):
        leads = load_fixture()
        self.assertEqual(len(leads), 25)
        with tempfile.TemporaryDirectory(
                prefix="concordance-") as tmp:
            report = run_replay(
                leads, tmp, str(ROOT),
                log=lambda *a, **k: None)
        by_tic = {r["tic"]: r for r in report["results"]}
        for lead in leads:
            entry = by_tic[lead["tic"]]
            with self.subTest(tic=lead["tic"],
                              manual=lead["manual_verdict"]):
                if lead["expected"] == "mismatch":
                    # Recorded, not asserted — no stage covers
                    # harmonic-alias grounds.
                    self.assertIsNone(entry["concordant"])
                    continue
                self.assertTrue(
                    entry["concordant"],
                    msg=(f"TIC {lead['tic']}: manual "
                         f"{lead['manual_verdict']}, automated "
                         f"{entry['automated_verdict']} killed "
                         f"at {entry['automated_kill_stages']}; "
                         f"{entry['note']}"
                         + (f" error: {entry['error']}"
                            if entry.get("error") else "")))


if __name__ == "__main__":
    unittest.main()
