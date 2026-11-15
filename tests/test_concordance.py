"""Concordance fixture validation (Phase 2 vote follow-up P-12)
— OFFLINE.

Validates tests/fixtures/concordance/manual_verdicts.json: the
25 hand-vetted rescore-v2 S96 leads transcribed from the
2026-11-14 gauntlet LEDGER. The live replay itself is
tests/test_concordance_live.py (DOWNLOAD_TESTS — live.yml
only); this module pins the fixture the replay runs against,
so a transcription error fails in the PR gate, not on the Mac.
"""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gauntlet.stage_result import REQUIRED_STAGES  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = (ROOT / "tests" / "fixtures" / "concordance"
           / "manual_verdicts.json")

# The LEDGER tally (2026-11-14, 25/25 vetted, 0 survivors).
EXPECTED_TALLY = {
    "killed_flagged_cadence": 18,
    "killed_single_event_weak": 4,
    "killed_catalogued": 1,
    "killed_v_shaped_era_confined": 1,
    "killed_harmonic_alias": 1,
}

# Fields the replay needs to build a Survivor.
EPHEMERIS_FIELDS = ("period_d", "t0_btjd", "duration_h",
                    "depth_pct", "sde", "sector")


class TestConcordanceFixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = json.loads(FIXTURE.read_text())
        cls.leads = cls.fixture["leads"]

    def test_twenty_five_leads(self):
        self.assertEqual(len(self.leads), 25)
        tics = [l["tic"] for l in self.leads]
        self.assertEqual(len(set(tics)), 25)

    def test_tally_matches_ledger(self):
        tally = {}
        for lead in self.leads:
            v = lead["manual_verdict"]
            tally[v] = tally.get(v, 0) + 1
        self.assertEqual(tally, EXPECTED_TALLY)

    def test_every_lead_has_an_ephemeris(self):
        for lead in self.leads:
            with self.subTest(tic=lead["tic"]):
                for field in EPHEMERIS_FIELDS:
                    self.assertIn(field, lead)
                    self.assertIsNotNone(lead[field])
                self.assertGreater(lead["period_d"], 0)
                self.assertGreater(lead["duration_h"], 0)
                self.assertEqual(lead["sector"], 96)

    def test_expected_stages_are_real_stages(self):
        for lead in self.leads:
            with self.subTest(tic=lead["tic"]):
                for stage in lead["expected_kill_stages"]:
                    self.assertIn(stage, REQUIRED_STAGES)

    def test_exactly_one_expected_mismatch(self):
        mismatches = [l for l in self.leads
                      if l["expected"] == "mismatch"]
        self.assertEqual(len(mismatches), 1)
        self.assertEqual(mismatches[0]["tic"], "307433122")
        self.assertEqual(mismatches[0]["manual_verdict"],
                         "killed_harmonic_alias")
        self.assertEqual(
            mismatches[0]["expected_kill_stages"], [])
        self.assertIn("mismatch_reason", mismatches[0])
        for lead in self.leads:
            if lead["expected"] == "agree":
                self.assertTrue(lead["expected_kill_stages"],
                                lead["tic"])

    def test_compare_lead_rule(self):
        # The concordance rule itself, unit-tested without a
        # live run: a kill at an expected stage agrees; a
        # CANDIDATE or a kill on an unexpected stage does not;
        # the mismatch lead is recorded, never asserted.
        sys.path.insert(0, str(ROOT / "scripts"))
        from concordance_replay import compare_lead
        agree_lead = next(
            l for l in self.leads if l["tic"] == "355401152")
        ok, _ = compare_lead(agree_lead, "REFUTED",
                             ["clean_refold"])
        self.assertTrue(ok)
        ok, _ = compare_lead(agree_lead, "CANDIDATE", [])
        self.assertFalse(ok)
        ok, _ = compare_lead(agree_lead, "BLEND", ["blend"])
        self.assertFalse(ok)
        ok, _ = compare_lead(agree_lead, None, [])
        self.assertFalse(ok)
        mismatch = next(
            l for l in self.leads if l["tic"] == "307433122")
        ok, _ = compare_lead(mismatch, "CANDIDATE", [])
        self.assertIsNone(ok)
        ok, _ = compare_lead(mismatch, "REFUTED",
                             ["persistence"])
        self.assertIsNone(ok)


if __name__ == "__main__":
    unittest.main()
