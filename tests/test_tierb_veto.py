"""Tests for the tier-B single-event veto (S12FIX F8; 5.2 null
diagnosis fix #3, DIAGNOSIS_5_2_NULL.md section 8 rank #3).

Rule: demote a final row iff it is tier B with exactly one
observed event (n_events == 1) — SINGLE-SECTOR inputs only.
Measured trade-off: 48 rows on the single leg at 0/144
final-row planet cost. The stitched application is REJECTED
(2/170 cost, kills 220576424:planet03, a reprieve-saved
planet) — stitched and multi-sector inputs must be untouched.

R10 caveat: the single-leg 0/144 safety is weakly tested —
only 1/144 M4 single-leg planets has a tier-B n1 row in its
recovery chain (220576424:planet05, pass-2 row). Recorded in
the module docstring and BUILD_TIERB.md, not hidden.

Offline: the rule reads tier + n_events off the rows — no
network anywhere in this module.
"""

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bulk import tierb_veto as tv  # noqa: E402
import search_health as _sh  # noqa: E402


def _row(tier="B", n_events=1, period_days=1.0):
    return {"period_days": period_days, "t0_btjd": 3900.0,
            "duration_hours": 2.0, "sde": 10.0,
            "mes_pink": 10.0, "max_event_snr": 9.0,
            "n_events": n_events, "n_strong_events": 1,
            "depth_percent": 0.2, "tier": tier,
            "status": "survivor", "flags": []}


def _host(tic, rows=None, sector=96, stitched=False):
    """A host record. `rows`: {pass: (tier, n_events)} for the
    surviving final rows; default one tier-B n1 pass-2 row.
    Single-sector by default (int `sector` key); `stitched`
    gives the record a `sectors` dict instead."""
    if rows is None:
        rows = {"pass2": ("B", 1)}
    rec = {"tic": str(tic), "calibration": "bulk_v6",
           "final_rows": len(rows), "final_survivor": True}
    if stitched:
        rec["sectors"] = {"95": {}, "96": {}, "97": {}}
        rec["stitch"] = {"n_sectors": 3}
    else:
        rec["sector"] = sector
    for pk, (tier, n_ev) in rows.items():
        rec[pk] = _row(tier=tier, n_events=n_ev)
        rec[f"{pk}_survivor"] = True
    return rec


class TestIsSingleSectorRecord(unittest.TestCase):
    def test_single_sector_record(self):
        self.assertTrue(tv.is_single_sector_record(
            _host("1")))
        self.assertTrue(tv.is_single_sector_record(
            {"tic": "1", "sector": 96}))

    def test_stitched_record_is_not_single_sector(self):
        self.assertFalse(tv.is_single_sector_record(
            _host("1", stitched=True)))
        # sectors dict alone (66 of the 2,720 5.2 null-p43
        # records carry no `stitch` key) is enough.
        self.assertFalse(tv.is_single_sector_record(
            {"tic": "1", "sectors": {"95": {}, "96": {}}}))
        # `stitch` alone is enough.
        self.assertFalse(tv.is_single_sector_record(
            {"tic": "1", "sector": 96, "stitch": {}}))

    def test_neither_key_is_not_single_sector(self):
        # Fail-closed: an ambiguous record keeps its rows.
        self.assertFalse(tv.is_single_sector_record(
            {"tic": "1"}))

    def test_non_int_sector_is_not_single_sector(self):
        self.assertFalse(tv.is_single_sector_record(
            {"tic": "1", "sector": "96"}))
        self.assertFalse(tv.is_single_sector_record(
            {"tic": "1", "sector": None}))
        self.assertFalse(tv.is_single_sector_record(
            {"tic": "1", "sector": True}))


class TestIsTierBN1(unittest.TestCase):
    def test_tier_b_one_event(self):
        self.assertTrue(tv.is_tierb_n1(_row("B", 1)))

    def test_non_triggers(self):
        self.assertFalse(tv.is_tierb_n1(_row("B", 2)))
        self.assertFalse(tv.is_tierb_n1(_row("A", 1)))
        self.assertFalse(tv.is_tierb_n1(_row(None, 1)))
        self.assertFalse(tv.is_tierb_n1(_row("B", None)))
        self.assertFalse(tv.is_tierb_n1({}))
        self.assertFalse(tv.is_tierb_n1(None))
        self.assertFalse(tv.is_tierb_n1("B"))


class TestApplyTierbVeto(unittest.TestCase):
    def test_single_leg_demotes_tierb_n1_final_rows(self):
        recs = [_host("141282117",
                      rows={"pass2": ("B", 1),
                            "pass1_carried": ("B", 1),
                            "pass3": ("A", 5)},
                      )]
        out, summary = tv.apply_tierb_veto(recs)
        new = out[0]
        for pk in ("pass2", "pass1_carried"):
            self.assertFalse(new[f"{pk}_survivor"])
            self.assertEqual(new[pk]["status"], "demoted")
            self.assertEqual(new[pk]["disposition"],
                             _sh.DEMOTED_TIERB_N1)
            self.assertIn(tv.TIERB_VETO_FLAG, new[pk]["flags"])
        # The tier-A multi-event row is untouched.
        self.assertTrue(new["pass3_survivor"])
        self.assertEqual(new["pass3"]["status"], "survivor")
        self.assertNotIn("disposition", new["pass3"])
        self.assertEqual(new["final_rows"], 1)
        self.assertTrue(new["final_survivor"])
        audit = new["tierb_veto"]
        self.assertTrue(audit["applied"])
        self.assertEqual(audit["trigger"],
                         {"tier": "B", "n_events": 1})
        self.assertEqual(sorted(audit["dropped_passes"]),
                         ["pass1_carried", "pass2"])
        self.assertEqual(summary["flagged_hosts"], 1)
        self.assertEqual(summary["rows_dropped"], 2)
        self.assertEqual(summary["dropped_keys"],
                         ["141282117:pass1_carried",
                          "141282117:pass2"])
        self.assertEqual(summary["flagged_tics"], ["141282117"])
        self.assertEqual(summary["checked"], 1)

    def test_stitched_record_untouched(self):
        recs = [_host("220576424", stitched=True)]
        out, summary = tv.apply_tierb_veto(recs)
        new = out[0]
        self.assertTrue(new["pass2_survivor"])
        self.assertEqual(new["pass2"]["status"], "survivor")
        self.assertNotIn("disposition", new["pass2"])
        self.assertEqual(new["final_rows"], 1)
        self.assertFalse(new["tierb_veto"]["applied"])
        self.assertIn("not single-sector",
                      new["tierb_veto"]["reason"])
        self.assertEqual(summary["rows_dropped"], 0)
        self.assertEqual(summary["skipped_not_single_sector"], 1)
        self.assertEqual(summary["skipped_tics"], ["220576424"])
        self.assertEqual(summary["checked"], 0)

    def test_leg_stitched_is_a_noop_even_for_single_records(self):
        recs = [_host("141282117")]
        out, summary = tv.apply_tierb_veto(recs, leg="stitched")
        self.assertTrue(out[0]["pass2_survivor"])
        self.assertFalse(out[0]["tierb_veto"]["applied"])
        self.assertIn("single-sector",
                      out[0]["tierb_veto"]["reason"])
        self.assertEqual(summary["rows_dropped"], 0)
        self.assertEqual(summary["leg"], "stitched")

    def test_leg_multi_is_a_noop(self):
        recs = [_host("141282117")]
        out, summary = tv.apply_tierb_veto(recs, leg="multi")
        self.assertTrue(out[0]["pass2_survivor"])
        self.assertEqual(summary["rows_dropped"], 0)

    def test_disabled_is_audit_only(self):
        recs = [_host("141282117")]
        out, summary = tv.apply_tierb_veto(recs, enabled=False)
        self.assertTrue(out[0]["pass2_survivor"])
        self.assertFalse(out[0]["tierb_veto"]["applied"])
        self.assertEqual(out[0]["tierb_veto"]["reason"],
                         "veto disabled")
        self.assertEqual(summary["rows_dropped"], 0)
        self.assertFalse(summary["enabled"])

    def test_tier_b_two_event_and_tier_a_one_event_kept(self):
        recs = [_host("1", rows={"pass2": ("B", 2),
                                 "pass3": ("A", 1)})]
        out, summary = tv.apply_tierb_veto(recs)
        new = out[0]
        self.assertTrue(new["pass2_survivor"])
        self.assertTrue(new["pass3_survivor"])
        self.assertEqual(new["final_rows"], 2)
        self.assertTrue(new["tierb_veto"]["applied"])
        self.assertEqual(new["tierb_veto"]["dropped_passes"], [])
        self.assertEqual(summary["rows_dropped"], 0)
        self.assertEqual(summary["checked"], 1)

    def test_pass1_row_is_not_a_final_row(self):
        # A tier-B n1 pass-1 row is not examined: only
        # pass2/pass3/pass1_carried are final rows.
        rec = _host("1", rows={"pass2": ("A", 5)})
        rec["pass1"] = _row("B", 1)
        rec["pass1_survivor"] = True
        out, summary = tv.apply_tierb_veto([rec])
        self.assertEqual(out[0]["pass1"]["status"], "survivor")
        self.assertNotIn("disposition", out[0]["pass1"])
        self.assertEqual(summary["rows_dropped"], 0)

    def test_host_with_no_final_rows_has_no_audit_key(self):
        rec = _host("1")
        rec["pass2_survivor"] = False
        rec["pass2"]["status"] = "recorded"
        rec["final_rows"] = 0
        rec["final_survivor"] = False
        out, summary = tv.apply_tierb_veto([rec])
        self.assertNotIn("tierb_veto", out[0])
        self.assertEqual(summary["no_final_rows"], 1)
        self.assertEqual(summary["checked"], 0)

    def test_demote_not_delete(self):
        recs = [_host("1")]
        out, _ = tv.apply_tierb_veto(recs)
        row = out[0]["pass2"]
        # The row survives with its measurements intact.
        self.assertEqual(row["period_days"], 1.0)
        self.assertEqual(row["n_events"], 1)
        self.assertEqual(row["tier"], "B")
        self.assertEqual(row["sde"], 10.0)
        self.assertEqual(row["status"], "demoted")

    def test_inputs_not_mutated(self):
        recs = [_host("141282117",
                      rows={"pass2": ("B", 1),
                            "pass1_carried": ("B", 1)})]
        before = copy.deepcopy(recs)
        tv.apply_tierb_veto(recs)
        self.assertEqual(recs, before)

    def test_all_rows_dropped_clears_final_survivor(self):
        recs = [_host("1", rows={"pass2": ("B", 1)})]
        out, _ = tv.apply_tierb_veto(recs)
        self.assertEqual(out[0]["final_rows"], 0)
        self.assertFalse(out[0]["final_survivor"])


class TestVetoRunDir(unittest.TestCase):
    def test_writes_new_output_dir_leaves_run_dir_untouched(self):
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td) / "run"
            (run_dir / "null_hosts").mkdir(parents=True)
            rec = _host("141282117")
            (run_dir / "null_hosts"
             / "141282117_s0096.json").write_text(json.dumps(rec))
            before = (run_dir / "null_hosts"
                      / "141282117_s0096.json").read_bytes()
            out_dir = Path(td) / "vetoed"
            summary = tv.veto_run_dir(run_dir, "null_hosts",
                                      out_dir)
            # Run dir byte-identical.
            self.assertEqual((run_dir / "null_hosts"
                              / "141282117_s0096.json").read_bytes(),
                             before)
            # Vetoed copy + summary in the new dir.
            written = json.loads(
                (out_dir / "null_hosts"
                 / "141282117_s0096.json").read_text())
            self.assertFalse(written["pass2_survivor"])
            self.assertEqual(written["pass2"]["disposition"],
                             _sh.DEMOTED_TIERB_N1)
            saved = json.loads(
                (out_dir / "tierb_veto_summary.json").read_text())
            self.assertEqual(saved["rows_dropped"], 1)
            self.assertEqual(summary["rows_dropped"], 1)

    def test_out_dir_inside_run_dir_refused(self):
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td) / "run"
            (run_dir / "null_hosts").mkdir(parents=True)
            with self.assertRaises(ValueError):
                tv.veto_run_dir(run_dir, "null_hosts",
                                run_dir / "vetoed")


if __name__ == "__main__":
    unittest.main()
