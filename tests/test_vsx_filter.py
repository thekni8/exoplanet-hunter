"""Tests for the nearby-eclipsing VSX filter (5.2 null diagnosis
fix #2; DIAGNOSIS_5_2_NULL.md section 5, section 8 rank #2).

Rule: drop a host's final rows iff VSX lists a variable of
vartype E (eclipsing binary) at separation 2-30 arcsec — a
nearby blend, NOT the target itself (self-hits, sep < 2", are
excluded: a blanket VSX filter costs 16/170 planets). Measured
trade-off: 5 + 5 rows at 0/170 + 0/144 planet cost. The blend
link is solid for only 1 of the 3 triggering hosts (31109583:
period match) — the build record carries that caveat.

Offline: every VSX response is mocked (a fake http_get / a fake
query_fn). No live network anywhere in this module.
"""

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bulk import vsx_filter as vf  # noqa: E402
import search_health as _sh  # noqa: E402

# Query centre for the synthetic VOTable: (100.0, -60.0).
# Offsets are in declination so the separation is exactly the
# offset in arcseconds.
RA0, DEC0 = 100.0, -60.0


def _row(idx, name, dec_offset_arcsec, vartype, period):
    """One synthetic VSX votable row (12 cells; cells[3] is
    'ra, dec', cells[11] is the period)."""
    dec = DEC0 + dec_offset_arcsec / 3600.0
    cells = [str(idx), name, "x", f"{RA0:.6f}, {dec:.6f}",
             vartype, "x", "x", "x", "x", "x", "x", period]
    tds = "".join(f"<TD>{c}</TD>" for c in cells)
    return f"<TR>{tds}</TR>"


VOTABLE = (
    "<VOTABLE><RESOURCE><TABLE>"
    + _row(1, "Gaia DR3 111", 4.9, "E", "1.07897")
    + _row(2, "Gaia DR3 222", 0.14, "ROT", "0.75629")
    + _row(3, "Gaia DR3 333", 25.0, "RRAB", "0.55")
    + _row(4, "Gaia DR3 444", 45.0, "E", "2.0")
    # Too few cells: skipped.
    + "<TR><TD>5</TD><TD>short</TD></TR>"
    # No coordinate cell: skipped.
    + "<TR>" + "".join("<TD>x</TD>" for _ in range(12)) + "</TR>"
    + "</TABLE></RESOURCE></VOTABLE>"
)

# The 5.2 diagnosis's real nearby-E hits (vsx_results.json,
# verbatim): three hosts, five hits.
REAL_HITS = {
    "276788366": [
        {"name": "Gaia DR3 4658412964832354048", "vartype": "E",
         "period_days": "1.07897", "sep_arcsec": 4.9},
        {"name": "Gaia DR3 4658412964854082944", "vartype": "E",
         "period_days": "0.339939", "sep_arcsec": 16.89},
        {"name": "Gaia DR3 4658412964832347392", "vartype": "E",
         "period_days": "0.285401", "sep_arcsec": 17.39},
    ],
    "31109583": [
        {"name": "Gaia DR3 4662018091674261632", "vartype": "E",
         "period_days": "1.92511", "sep_arcsec": 15.35},
    ],
    "41255134": [
        {"name": "Gaia DR3 5282835994864469120", "vartype": "E",
         "period_days": "1.34645", "sep_arcsec": 28.26},
    ],
}


def _host(tic, passes=("pass2",), final_rows=1):
    """A null-leg host record with surviving final rows."""
    rec = {"tic": str(tic), "calibration": "bulk_v6",
           "final_rows": final_rows,
           "final_survivor": True}
    for pk in passes:
        rec[pk] = {"period_days": 1.0, "t0_btjd": 3900.0,
                   "duration_hours": 2.0, "sde": 10.0,
                   "mes_pink": 10.0, "max_event_snr": 9.0,
                   "n_events": 5, "n_strong_events": 3,
                   "depth_percent": 0.2, "tier": "A",
                   "status": "survivor", "flags": []}
        rec[f"{pk}_survivor"] = True
    return rec


class FakeResponse:
    def __init__(self, status_code, text):
        self.status_code = status_code
        self.text = text


class TestParseVsxHits(unittest.TestCase):
    def test_parses_hits_with_local_separations(self):
        hits = vf.parse_vsx_hits(VOTABLE, RA0, DEC0)
        by_name = {h["name"]: h for h in hits}
        # The 45" E hit is outside the 30" cone: not returned.
        self.assertEqual(sorted(by_name),
                         ["Gaia DR3 111", "Gaia DR3 222",
                          "Gaia DR3 333"])
        e = by_name["Gaia DR3 111"]
        self.assertEqual(e["vartype"], "E")
        self.assertEqual(e["period_days"], "1.07897")
        self.assertAlmostEqual(e["sep_arcsec"], 4.9, delta=0.05)
        self.assertAlmostEqual(by_name["Gaia DR3 222"]["sep_arcsec"],
                               0.14, delta=0.05)
        self.assertAlmostEqual(by_name["Gaia DR3 333"]["sep_arcsec"],
                               25.0, delta=0.05)

    def test_empty_response_parses_to_no_hits(self):
        self.assertEqual(vf.parse_vsx_hits("<VOTABLE/>", RA0, DEC0),
                         [])


class TestFindNearbyEclipsing(unittest.TestCase):
    def test_nearest_e_wins(self):
        hit = vf.find_nearby_eclipsing(REAL_HITS["276788366"])
        self.assertEqual(hit["sep_arcsec"], 4.9)
        self.assertEqual(hit["period_days"], "1.07897")

    def test_real_5_2_hosts_trigger(self):
        for tic in ("31109583", "41255134"):
            hit = vf.find_nearby_eclipsing(REAL_HITS[tic])
            self.assertIsNotNone(hit, tic)
            self.assertEqual(hit["vartype"], "E")

    def test_self_hit_excluded(self):
        self.assertIsNone(vf.find_nearby_eclipsing(
            [{"name": "self", "vartype": "E",
              "period_days": "1.0", "sep_arcsec": 1.5}]))

    def test_boundaries_inclusive(self):
        for sep in (2.0, 30.0):
            hit = vf.find_nearby_eclipsing(
                [{"name": "b", "vartype": "E",
                  "period_days": "1.0", "sep_arcsec": sep}])
            self.assertIsNotNone(hit, sep)
        for sep in (1.99, 30.01):
            self.assertIsNone(vf.find_nearby_eclipsing(
                [{"name": "b", "vartype": "E",
                  "period_days": "1.0", "sep_arcsec": sep}]), sep)

    def test_non_e_vartypes_do_not_trigger(self):
        for vt in ("ROT", "RRAB", "EA", "EB", "EW", "BY", "VAR"):
            self.assertIsNone(vf.find_nearby_eclipsing(
                [{"name": "n", "vartype": vt,
                  "period_days": "1.0", "sep_arcsec": 5.0}]), vt)

    def test_empty_or_none(self):
        self.assertIsNone(vf.find_nearby_eclipsing([]))
        self.assertIsNone(vf.find_nearby_eclipsing(None))


class TestQueryVsxHits(unittest.TestCase):
    def test_success_parses(self):
        seen = {}

        def fake_get(url, timeout):
            seen["url"] = url
            seen["timeout"] = timeout
            return FakeResponse(200, VOTABLE)

        res = vf.query_vsx_hits(RA0, DEC0, http_get=fake_get)
        self.assertIn("hits", res)
        self.assertEqual(len(res["hits"]), 3)
        self.assertIn("vsx.aavso.org", seen["url"])
        self.assertIn("100.0+-60.0", seen["url"])
        self.assertEqual(seen["timeout"], vf.VSX_QUERY_TIMEOUT_S)

    def test_non_200_is_fail_open_error(self):
        res = vf.query_vsx_hits(
            RA0, DEC0,
            http_get=lambda url, timeout: FakeResponse(500, ""))
        self.assertEqual(res, {"error": "HTTP 500"})

    def test_exception_is_fail_open_error(self):
        def boom(url, timeout):
            raise TimeoutError("timed out")

        res = vf.query_vsx_hits(RA0, DEC0, http_get=boom)
        self.assertIn("error", res)
        self.assertIn("timed out", res["error"])


class TestApplyVsxFilter(unittest.TestCase):
    def test_flagged_host_drops_all_final_rows(self):
        recs = [_host("276788366",
                      passes=("pass2", "pass1_carried"),
                      final_rows=2)]
        coords = {"276788366": {"ra": 1.0, "dec": -2.0}}
        out, summary = vf.apply_vsx_filter(
            recs, coords,
            query_fn=lambda ra, dec: {
                "hits": REAL_HITS["276788366"]})
        new = out[0]
        for pk in ("pass2", "pass1_carried"):
            self.assertFalse(new[f"{pk}_survivor"])
            self.assertEqual(new[pk]["status"], "demoted")
            self.assertEqual(new[pk]["disposition"],
                             _sh.DEMOTED_VSX_NEARBY_E)
            self.assertIn(vf.VSX_FILTER_FLAG, new[pk]["flags"])
        self.assertEqual(new["final_rows"], 0)
        self.assertFalse(new["final_survivor"])
        audit = new["vsx_filter"]
        self.assertTrue(audit["applied"])
        # Nearest of the three E hits is the recorded trigger.
        self.assertEqual(audit["trigger"]["sep_arcsec"], 4.9)
        self.assertEqual(audit["trigger"]["period_days"], "1.07897")
        self.assertEqual(audit["trigger"]["name"],
                         "Gaia DR3 4658412964832354048")
        self.assertEqual(sorted(audit["dropped_passes"]),
                         ["pass1_carried", "pass2"])
        self.assertEqual(summary["flagged_hosts"], 1)
        self.assertEqual(summary["rows_dropped"], 2)
        self.assertEqual(summary["flagged_tics"], ["276788366"])

    def test_clean_host_keeps_rows(self):
        recs = [_host("999")]
        coords = {"999": {"ra": 1.0, "dec": -2.0}}
        out, summary = vf.apply_vsx_filter(
            recs, coords,
            query_fn=lambda ra, dec: {
                "hits": [{"name": "r", "vartype": "ROT",
                          "period_days": "1.0",
                          "sep_arcsec": 0.14}]})
        self.assertTrue(out[0]["pass2_survivor"])
        self.assertEqual(out[0]["pass2"]["status"], "survivor")
        self.assertIsNone(out[0]["vsx_filter"]["trigger"])
        self.assertEqual(summary["clean"], 1)
        self.assertEqual(summary["rows_dropped"], 0)

    def test_query_failure_keeps_rows_fail_open(self):
        recs = [_host("999")]
        coords = {"999": {"ra": 1.0, "dec": -2.0}}
        out, summary = vf.apply_vsx_filter(
            recs, coords,
            query_fn=lambda ra, dec: {"error": "HTTP 500"})
        self.assertTrue(out[0]["pass2_survivor"])
        self.assertFalse(out[0]["vsx_filter"]["applied"])
        self.assertIn("HTTP 500", out[0]["vsx_filter"]["reason"])
        self.assertEqual(summary["query_failed"], 1)
        self.assertEqual(summary["failed_tics"], ["999"])
        self.assertEqual(summary["rows_dropped"], 0)

    def test_no_coords_keeps_rows(self):
        recs = [_host("999")]
        out, summary = vf.apply_vsx_filter(
            recs, {}, query_fn=lambda ra, dec: {"hits": []})
        self.assertTrue(out[0]["pass2_survivor"])
        self.assertEqual(out[0]["vsx_filter"]["reason"],
                         "no coordinates")
        self.assertEqual(summary["no_coords"], 1)
        self.assertEqual(summary["queried"], 0)

    def test_host_with_no_final_rows_is_not_queried(self):
        rec = _host("999")
        rec["pass2_survivor"] = False
        rec["pass2"]["status"] = "recorded"
        rec["final_rows"] = 0
        rec["final_survivor"] = False
        called = []

        def spy(ra, dec):
            called.append((ra, dec))
            return {"hits": []}

        out, summary = vf.apply_vsx_filter(
            [rec], {"999": {"ra": 1.0, "dec": -2.0}}, query_fn=spy)
        self.assertEqual(called, [])
        self.assertNotIn("vsx_filter", out[0])
        self.assertEqual(summary["queried"], 0)

    def test_inputs_not_mutated(self):
        recs = [_host("276788366")]
        before = copy.deepcopy(recs)
        vf.apply_vsx_filter(
            recs, {"276788366": {"ra": 1.0, "dec": -2.0}},
            query_fn=lambda ra, dec: {
                "hits": REAL_HITS["276788366"]})
        self.assertEqual(recs, before)


class TestF3Logging(unittest.TestCase):
    """S12FIX F3 (1c/1d): re-query on failure, per-host result
    persistence with timestamps, BLS P / VSX P in the audit
    key (logging only)."""

    def test_retry_succeeds_after_one_failure(self):
        calls = []

        def flaky(ra, dec):
            calls.append(1)
            if len(calls) == 1:
                return {"error": "HTTP 500"}
            return {"hits": REAL_HITS["31109583"]}

        recs = [_host("31109583")]
        out, summary = vf.apply_vsx_filter(
            recs, {"31109583": {"ra": 1.0, "dec": -2.0}},
            query_fn=flaky)
        self.assertEqual(len(calls), 2)
        self.assertFalse(out[0]["pass2_survivor"])
        self.assertEqual(summary["query_retries"], 1)
        self.assertEqual(summary["query_failed"], 0)
        self.assertEqual(summary["queried"], 1)
        qr = summary["query_results"]["31109583"]
        self.assertEqual(qr["attempts"], 2)
        self.assertEqual(len(qr["hits"]), 1)

    def test_retry_fails_twice_keeps_rows_fail_open(self):
        recs = [_host("999")]
        out, summary = vf.apply_vsx_filter(
            recs, {"999": {"ra": 1.0, "dec": -2.0}},
            query_fn=lambda ra, dec: {"error": "HTTP 500"})
        self.assertTrue(out[0]["pass2_survivor"])
        self.assertEqual(summary["query_retries"], 1)
        self.assertEqual(summary["query_failed"], 1)
        qr = summary["query_results"]["999"]
        self.assertEqual(qr["attempts"], 2)
        self.assertEqual(qr["error"], "HTTP 500")

    def test_query_results_persisted_with_timestamp(self):
        recs = [_host("999")]
        _, summary = vf.apply_vsx_filter(
            recs, {"999": {"ra": 1.0, "dec": -2.0}},
            query_fn=lambda ra, dec: {
                "hits": [{"name": "r", "vartype": "ROT",
                          "period_days": "1.0",
                          "sep_arcsec": 0.14}]})
        qr = summary["query_results"]["999"]
        self.assertEqual(qr["attempts"], 1)
        self.assertEqual(len(qr["hits"]), 1)
        # Parseable ISO-8601 UTC timestamp.
        from datetime import datetime
        ts = datetime.fromisoformat(qr["queried_at"])
        self.assertIsNotNone(ts.tzinfo)

    def test_period_ratio_logged_for_dropped_rows(self):
        # 31109583's trigger period is 1.92511 d; a BLS period
        # of half that (the half-harmonic the diagnosis found)
        # logs a ratio of 0.5.
        rec = _host("31109583")
        rec["pass2"]["period_days"] = 0.962555
        out, _ = vf.apply_vsx_filter(
            [rec], {"31109583": {"ra": 1.0, "dec": -2.0}},
            query_fn=lambda ra, dec: {
                "hits": REAL_HITS["31109583"]})
        ratios = out[0]["vsx_filter"]["period_ratios"]
        self.assertAlmostEqual(ratios["pass2"], 0.5, places=6)

    def test_period_ratio_none_when_period_missing(self):
        # Trigger with no period: ratio is None, not an error.
        rec = _host("999")
        out, _ = vf.apply_vsx_filter(
            [rec], {"999": {"ra": 1.0, "dec": -2.0}},
            query_fn=lambda ra, dec: {
                "hits": [{"name": "n", "vartype": "E",
                          "period_days": None,
                          "sep_arcsec": 5.0}]})
        self.assertIsNone(
            out[0]["vsx_filter"]["period_ratios"]["pass2"])
        # Row with no period: ratio is None too.
        rec2 = _host("999")
        del rec2["pass2"]["period_days"]
        out2, _ = vf.apply_vsx_filter(
            [rec2], {"999": {"ra": 1.0, "dec": -2.0}},
            query_fn=lambda ra, dec: {
                "hits": REAL_HITS["31109583"]})
        self.assertIsNone(
            out2[0]["vsx_filter"]["period_ratios"]["pass2"])

    def test_queried_at_on_every_audit_key(self):
        from datetime import datetime
        recs = [_host("31109583"), _host("999")]
        coords = {"31109583": {"ra": 1.0, "dec": -2.0},
                  "999": {"ra": 3.0, "dec": -4.0}}

        def q(ra, dec):
            if ra == 1.0:
                return {"hits": REAL_HITS["31109583"]}
            return {"hits": []}

        out, _ = vf.apply_vsx_filter(recs, coords, query_fn=q)
        for rec in out:
            ts = datetime.fromisoformat(
                rec["vsx_filter"]["queried_at"])
            self.assertIsNotNone(ts.tzinfo)

    def test_no_coords_host_has_no_query_result(self):
        recs = [_host("999")]
        _, summary = vf.apply_vsx_filter(
            recs, {}, query_fn=lambda ra, dec: {"hits": []})
        self.assertNotIn("999", summary["query_results"])
        self.assertEqual(summary["query_retries"], 0)


class TestFilterRunDir(unittest.TestCase):
    def test_writes_new_output_dir_leaves_run_dir_untouched(self):
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td) / "run"
            (run_dir / "null-p43").mkdir(parents=True)
            rec = _host("276788366")
            (run_dir / "null-p43" / "276788366.json").write_text(
                json.dumps(rec))
            before = (run_dir / "null-p43"
                      / "276788366.json").read_bytes()
            out_dir = Path(td) / "filtered"
            summary = vf.filter_run_dir(
                run_dir, "null-p43",
                {"276788366": {"ra": 1.0, "dec": -2.0}},
                out_dir,
                query_fn=lambda ra, dec: {
                    "hits": REAL_HITS["276788366"]})
            # Run dir byte-identical.
            self.assertEqual((run_dir / "null-p43"
                              / "276788366.json").read_bytes(),
                             before)
            # Filtered copy + summary in the new dir.
            written = json.loads(
                (out_dir / "null-p43"
                 / "276788366.json").read_text())
            self.assertFalse(written["pass2_survivor"])
            self.assertEqual(
                written["vsx_filter"]["trigger"]["sep_arcsec"],
                4.9)
            saved = json.loads(
                (out_dir / "vsx_filter_summary.json").read_text())
            self.assertEqual(saved["rows_dropped"], 1)
            self.assertEqual(summary["rows_dropped"], 1)

    def test_out_dir_inside_run_dir_refused(self):
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td) / "run"
            (run_dir / "null-p43").mkdir(parents=True)
            with self.assertRaises(ValueError):
                vf.filter_run_dir(run_dir, "null-p43", {},
                                  run_dir / "filtered")


if __name__ == "__main__":
    unittest.main()
