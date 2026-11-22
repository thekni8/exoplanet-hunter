"""Tests for the 5.2 paired-D2 guardrail scorer
(bulk/paired_d2_score.py; BP3_TEMPLATE.md §2.3).

The scorer is the adapted copy of the FROZEN ELIGFIX E6 scorer
(`science-vet/bulkv6/eligfix-vote/paired_d2_score.py` — that
file is NOT edited). The adaptation counts the 5.1 carried
row (`pass1_carried`) as a per-pass final row, so the guardrail
does not undercount the null side on 5.1 records (BUILD_5_1).

Offline: synthetic host records only, no downloads, no Mac,
no campaign. The backward-compatibility gate (dry-run on the
E6 paired records reproducing paired_d2_score.json exactly)
runs on the Mac at 5.2 run prep, not here.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bulk import paired_d2_score as pds  # noqa: E402


def _row(period=5.0, t0=100.0, tier="A", status="survivor",
         flags=None, carried_from=None, flags_carried_from=None):
    r = {"period_days": period, "t0_btjd": t0, "tier": tier,
         "status": status, "flags": list(flags or []),
         "depth_percent": 0.5, "sde": 9.0, "n_events": 3}
    if carried_from is not None:
        r["carried_from"] = carried_from
    if flags_carried_from is not None:
        r["flags_carried_from"] = flags_carried_from
    return r


def _rec(pass1_survivor=False, pass2=None, pass2_survivor=False,
         pass3=None, pass3_survivor=False, carried=None,
         carried_survivor=None, final_rows=None, sectors=None):
    r = {"tic": "123", "pass1_survivor": pass1_survivor,
         "pass2_survivor": pass2_survivor,
         "pass3_survivor": pass3_survivor,
         "sectors": sectors or {}}
    if pass2 is not None:
        r["pass2"] = pass2
    if pass3 is not None:
        r["pass3"] = pass3
    if carried is not None:
        r["pass1_carried"] = carried
    if carried_survivor is not None:
        r["pass1_carried_survivor"] = carried_survivor
    if final_rows is not None:
        r["final_rows"] = final_rows
    return r


class TestFinalRows(unittest.TestCase):
    def test_carried_row_counts(self):
        # §2.3 item 1: the carried row is its own per-pass row.
        recs = {"123": _rec(
            pass1_survivor=True,
            carried=_row(), carried_survivor=True)}
        rows = pds.final_rows(recs)
        self.assertEqual(rows, {("123", "pass1_carried"): _row()})

    def test_carried_row_not_counted_when_not_survivor(self):
        recs = {"123": _rec(
            pass1_survivor=True,
            carried=_row(status="demoted"), carried_survivor=False)}
        self.assertEqual(pds.final_rows(recs), {})

    def test_pre51_record_unchanged(self):
        # No pass1_carried keys at all: old two-pass behavior.
        recs = {"123": _rec(pass2=_row(), pass2_survivor=True,
                            pass3=_row(period=7.0),
                            pass3_survivor=False)}
        rows = pds.final_rows(recs)
        self.assertEqual(set(rows), {("123", "pass2")})

    def test_no_dedupe_same_signal(self):
        # §2.3 item 2: a carried row counts even when it
        # dedupes against a pass-2 row (same signal) — the
        # guardrail unit is per-pass, not distinct-row.
        recs = {"123": _rec(
            pass1_survivor=True,
            pass2=_row(), pass2_survivor=True,
            carried=_row(), carried_survivor=True)}
        rows = pds.final_rows(recs)
        self.assertEqual(set(rows),
                         {("123", "pass2"), ("123", "pass1_carried")})

    def test_missing_row_dict_is_empty(self):
        recs = {"123": _rec(carried_survivor=True)}
        rows = pds.final_rows(recs)
        self.assertEqual(rows, {("123", "pass1_carried"): {}})

    def test_final_passes_constant(self):
        self.assertEqual(pds.FINAL_PASSES,
                         ("pass2", "pass3", "pass1_carried"))


class TestTrueF2(unittest.TestCase):
    def _flagged_sectors(self):
        return {"95": {"pass1": {"period_days": 5.0,
                                 "flags": ["ODD_EVEN_EB"]}}}

    def test_carried_row_copy_branch_true(self):
        # §2.3 item 4: carried row, F-2 flags, tier A,
        # pass-1 baseline a survivor -> outcome-changing.
        recs = {"123": _rec(
            pass1_survivor=True,
            sectors=self._flagged_sectors(),
            carried=_row(flags=["ODD_EVEN_EB"],
                         carried_from="pass1",
                         flags_carried_from="pass1",
                         status="demoted"),
            carried_survivor=False)}
        scorer, true, details = pds.true_f2(recs)
        self.assertEqual(scorer, {"123"})
        self.assertEqual(true, {"123"})
        self.assertEqual(len(details), 1)
        self.assertEqual(details[0]["pass"], "pass1_carried")
        self.assertEqual(details[0]["kind"], "copy")
        self.assertTrue(details[0]["true"])

    def test_carried_row_copy_branch_runs_not_assumed(self):
        # The pass-1-baseline check runs: a carried row whose
        # baseline was already demoted is NOT outcome-changing
        # (cannot happen by construction — the carry exists
        # only for a pass-1 survivor — but the check must run).
        recs = {"123": _rec(
            pass1_survivor=False,
            sectors=self._flagged_sectors(),
            carried=_row(flags=["ODD_EVEN_EB"],
                         carried_from="pass1",
                         flags_carried_from="pass1",
                         status="demoted"),
            carried_survivor=False)}
        scorer, true, details = pds.true_f2(recs)
        self.assertEqual(scorer, {"123"})
        self.assertEqual(true, set())
        self.assertFalse(details[0]["true"])
        self.assertEqual(details[0]["why"], "baseline already demoted")

    def test_carried_row_without_f2_flags_ignored(self):
        recs = {"123": _rec(
            pass1_survivor=True,
            carried=_row(carried_from="pass1"),
            carried_survivor=True)}
        scorer, true, details = pds.true_f2(recs)
        self.assertEqual((scorer, true, details), (set(), set(), []))

    def test_carried_row_tier_b_ignored(self):
        recs = {"123": _rec(
            pass1_survivor=True,
            carried=_row(tier="B", flags=["ODD_EVEN_EB"],
                         carried_from="pass1",
                         flags_carried_from="pass1"),
            carried_survivor=False)}
        scorer, true, details = pds.true_f2(recs)
        self.assertEqual((scorer, true, details), (set(), set(), []))

    def test_pass2_rescreen_branch_unchanged(self):
        # Measured-only empty -> true; a measured flag -> false.
        base = {"pass1_survivor": True,
                "sectors": self._flagged_sectors()}
        recs_true = {"123": _rec(
            **base,
            pass2=_row(flags=["ODD_EVEN_EB"],
                       flags_carried_from="pass1"),
            pass2_survivor=False)}
        _, true, _ = pds.true_f2(recs_true)
        self.assertEqual(true, {"123"})
        recs_false = {"123": _rec(
            **base,
            pass2=_row(flags=["ODD_EVEN_EB", "VSHAPE_EB"],
                       flags_carried_from="pass1"),
            pass2_survivor=False)}
        _, true, details = pds.true_f2(recs_false)
        self.assertEqual(true, set())
        self.assertEqual(details[0]["kind"], "rescreen")


class TestArmTotals(unittest.TestCase):
    def test_carried_survivors_counted(self):
        recs = {
            "1": _rec(pass1_survivor=True, carried=_row(),
                      carried_survivor=True),
            "2": _rec(pass1_survivor=True, carried=_row(),
                      carried_survivor=False),
            "3": _rec(pass2=_row(), pass2_survivor=True),
        }
        tot = pds.arm_totals(recs)
        self.assertEqual(tot["n"], 3)
        self.assertEqual(tot["pass1_survivors"], 2)
        self.assertEqual(tot["pass2_survivors"], 1)
        self.assertEqual(tot["pass3_survivors"], 0)
        self.assertEqual(tot["pass1_carried_survivors"], 1)

    def test_pre51_records_zero_carried(self):
        recs = {"1": _rec(pass2=_row(), pass2_survivor=True)}
        self.assertEqual(pds.arm_totals(recs)["pass1_carried_survivors"],
                         0)


class TestDriverFinalRows(unittest.TestCase):
    def test_sums_driver_field(self):
        recs = {"1": _rec(final_rows=2), "2": _rec(final_rows=1),
                "3": _rec(final_rows=0)}
        out = pds.driver_final_rows(recs)
        self.assertEqual(out, {"total": 3, "n_present": 3,
                               "n_records": 3})

    def test_missing_key_is_none_not_zero(self):
        # Pre-5.1 records carry no final_rows key: the total
        # is undefined (None), not 0 — 0 would be a wrong claim.
        recs = {"1": _rec(pass2=_row(), pass2_survivor=True)}
        out = pds.driver_final_rows(recs)
        self.assertEqual(out, {"total": None, "n_present": 0,
                               "n_records": 1})

    def test_partial_presence(self):
        recs = {"1": _rec(final_rows=2), "2": _rec()}
        out = pds.driver_final_rows(recs)
        self.assertEqual(out, {"total": 2, "n_present": 1,
                               "n_records": 2})


class TestRowDetail(unittest.TestCase):
    def test_carried_row_detail(self):
        # §2.3 item 6: row_detail works unchanged for the
        # carried row (reads r.get(pk)).
        sectors = {
            "95": {"k2_mask": {"stopped": False}},
            "96": {"k2_mask": {"stopped": True}},
        }
        recs = {"123": _rec(
            pass1_survivor=True, sectors=sectors,
            carried=_row(period=5.0, t0=100.0),
            carried_survivor=True)}
        d = pds.row_detail(recs, ("123", "pass1_carried"),
                           affected={"123"})
        self.assertEqual(d["tic"], "123")
        self.assertEqual(d["pass"], "pass1_carried")
        self.assertEqual(d["period_days"], 5.0)
        self.assertEqual(d["t0_btjd"], 100.0)
        self.assertTrue(d["in_890_affected"])
        self.assertEqual(d["masked_sectors_live"], ["95"])
        self.assertEqual(d["masked_sectors_stopped"], ["96"])


class TestTripwireBand(unittest.TestCase):
    def test_bands(self):
        self.assertEqual(pds.tripwire_band(0), "proceed")
        self.assertEqual(pds.tripwire_band(3), "proceed")
        self.assertEqual(pds.tripwire_band(-3), "proceed")
        self.assertEqual(pds.tripwire_band(4), "investigate")
        self.assertEqual(pds.tripwire_band(-5), "investigate")
        self.assertEqual(pds.tripwire_band(6), "back-to-dev")
        self.assertEqual(pds.tripwire_band(-8), "back-to-dev")


class TestBackwardCompat(unittest.TestCase):
    def test_pre51_records_match_two_pass_scoring(self):
        # On records without any 5.1 keys, the adapted
        # functions equal the frozen two-pass computation.
        recs = {
            "1": _rec(pass1_survivor=True,
                      pass2=_row(), pass2_survivor=True),
            "2": _rec(pass2=_row(period=7.0), pass2_survivor=False,
                      pass3=_row(period=9.0), pass3_survivor=True),
            "3": _rec(),
        }
        rows = pds.final_rows(recs)
        self.assertEqual(set(rows),
                         {("1", "pass2"), ("2", "pass3")})
        scorer, true, details = pds.true_f2(recs)
        self.assertEqual((scorer, true, details),
                         (set(), set(), []))
        tot = pds.arm_totals(recs)
        self.assertEqual(tot["pass1_carried_survivors"], 0)
        self.assertEqual(tot["pass2_survivors"], 1)
        self.assertEqual(tot["pass3_survivors"], 1)


if __name__ == "__main__":
    unittest.main()
