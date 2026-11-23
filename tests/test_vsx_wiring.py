"""Runner-wiring tests for the nearby-E VSX filter (S12FIX F2).

The filter module itself is tested in test_vsx_filter.py; these
pin the p43_run merge wiring: the null merge applies the filter
to both legs before aggregating, the campaign merge applies it
to both legs' trial records before the paired list is built,
demotions land in the host files (atomically, demoted files
only), re-merging is idempotent, and failures fail open.
Offline: every VSX response is mocked (fake query_fn + coords).
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import bulk_screen as bs  # noqa: E402
from bulk import p43_run  # noqa: E402
from bulk import vsx_filter as vf  # noqa: E402
import search_health as _sh  # noqa: E402

# The 5.2 diagnosis's real nearby-E hit for 276788366
# (vsx_results.json, verbatim).
HIT_276788366 = [
    {"name": "Gaia DR3 4658412964832354048", "vartype": "E",
     "period_days": "1.07897", "sep_arcsec": 4.9},
]

COORDS = {"276788366": {"ra": 1.0, "dec": -2.0},
          "999": {"ra": 3.0, "dec": -4.0},
          "555": {"ra": 5.0, "dec": -6.0}}


def _qfn(fail_tics=()):
    """A fake query_fn: 276788366 flagged, 999 clean, the
    fail_tics error out (fail open)."""
    rev = {(c["ra"], c["dec"]): t for t, c in COORDS.items()}

    def q(ra, dec):
        tic = rev.get((ra, dec))
        if tic in fail_tics:
            return {"error": "HTTP 500"}
        if tic == "276788366":
            return {"hits": HIT_276788366}
        return {"hits": []}

    return q


def _null_host(tic, t0, passes=("pass2",)):
    """A null-leg host record with surviving final rows
    (multi-event, distinct T0s — never T0-veto inputs)."""
    rec = {"tic": str(tic), "calibration": "bulk_v6",
           "complete": True, "arm": "no-depth-trigger",
           "pass1_survivor": True,
           "final_rows": len(passes), "final_survivor": True}
    for pk in passes:
        rec[pk] = {"period_days": 1.0, "t0_btjd": t0,
                   "duration_hours": 2.0, "sde": 10.0,
                   "mes_pink": 10.0, "max_event_snr": 9.0,
                   "n_events": 5, "n_strong_events": 3,
                   "depth_percent": 0.2, "tier": "A",
                   "status": "survivor", "flags": []}
        rec[f"{pk}_survivor"] = True
    return rec


def _ctrial(tic, trial_id, recovered=(), driver="p43"):
    """A campaign-leg trial (mirrors test_vsx_filter._ctrial):
    `recovered` passes carry a recovered row; `driver` picks
    the stem set ("p43": p2/p3; "k3": k2/k3)."""
    stem_for = {"p43": {"pass2": "p2", "pass3": "p3"},
                "k3": {"pass2": "k2", "pass3": "k3"}}[driver]
    tr = {"tic": str(tic), "sector": 95, "trial_id": trial_id,
          "group": "lockon_207", "period_d": 12.0,
          "seconds": 1.0, "inj_check_ok": True,
          "pass1": {"period_days": 12.0},
          "sectors": {"95": {"pass1": {"period_days": 12.0}}}}
    final = False
    for pk in ("pass2", "pass3", "pass1_carried"):
        stem = (stem_for.get(pk) if pk != "pass1_carried"
                else "p1_carried")
        got = pk in recovered
        tr[f"{stem}_recovered"] = got
        tr[f"{stem}_genuine"] = got
        if got:
            final = True
            tr[pk] = {"period_days": 1.0, "t0_btjd": 3900.0,
                      "duration_hours": 2.0, "sde": 10.0,
                      "n_events": 5, "tier": "A",
                      "status": "survivor", "flags": []}
    tr["final_recovered"] = final
    tr["final_genuine"] = final
    return tr


class TestNullMergeVsxWiring(unittest.TestCase):
    def _write_fixture(self, out_dir):
        (out_dir / "null-p43").mkdir()
        (out_dir / "null_hosts").mkdir()
        hosts = [
            _null_host("276788366", 3900.0,
                       passes=("pass2", "pass1_carried")),
            _null_host("999", 3910.0),
            _null_host("555", 3920.0),
        ]
        for h in hosts:
            (out_dir / "null-p43"
             / f"{h['tic']}_p43.json").write_text(json.dumps(h))
            (out_dir / "null_hosts"
             / f"{h['tic']}_s0096.json").write_text(
                 json.dumps(h))
        return hosts

    def _read(self, out_dir, subdir, tic):
        suf = "_p43.json" if subdir == "null-p43" else "_s0096.json"
        return json.loads(
            (out_dir / subdir / f"{tic}{suf}").read_text())

    def test_null_merge_applies_filter_both_legs(self):
        with tempfile.TemporaryDirectory() as d:
            out_dir = Path(d)
            self._write_fixture(out_dir)
            summary = p43_run.merge_null_p43(
                out_dir, vsx_query_fn=_qfn(fail_tics=("555",)),
                vsx_coords=COORDS)
            # The T0 veto ran (bulk_v6 stamps) and demoted
            # nothing: multi-event rows at distinct T0s.
            veto = summary["stitched_t0_cluster_veto"]
            self.assertTrue(veto["applied"])
            self.assertEqual(veto["demoted"], 0)
            for key in ("vsx_filter_stitched",
                        "vsx_filter_single"):
                sec = summary[key]
                self.assertTrue(sec["applied"], key)
                self.assertEqual(sec["queried"], 3, key)
                self.assertEqual(sec["flagged_hosts"], 1, key)
                self.assertEqual(sec["flagged_tics"],
                                 ["276788366"], key)
                self.assertEqual(sec["rows_dropped"], 2, key)
                self.assertEqual(sec["dropped_pass2"], 1, key)
                self.assertEqual(sec["dropped_pass1_carried"],
                                 1, key)
                self.assertEqual(sec["query_failed"], 1, key)
                self.assertEqual(sec["failed_tics"], ["555"],
                                 key)
                self.assertEqual(sec["demoted_total"], 2, key)
                # F3: every queried host's result persisted.
                self.assertEqual(
                    sorted(sec["query_results"]),
                    ["276788366", "555", "999"], key)
            # Headline counts reflect the filter (the merge's
            # _agg counts pass2+pass3 only, not the carry:
            # 3 -> 2 per leg).
            self.assertEqual(summary["stitched"]["final_rows"], 2)
            self.assertEqual(summary["single"]["final_rows"], 2)
            # Demotions landed in the host files, both legs.
            for subdir in ("null-p43", "null_hosts"):
                rec = self._read(out_dir, subdir, "276788366")
                for pk in ("pass2", "pass1_carried"):
                    self.assertEqual(rec[pk]["status"], "demoted")
                    self.assertEqual(rec[pk]["disposition"],
                                     _sh.DEMOTED_VSX_NEARBY_E)
                    self.assertIn(vf.VSX_FILTER_FLAG,
                                  rec[pk]["flags"])
                    self.assertIs(rec[f"{pk}_survivor"], False)
                self.assertEqual(rec["final_rows"], 0)
                self.assertIs(rec["final_survivor"], False)
                audit = rec["vsx_filter"]
                self.assertEqual(audit["trigger"]["sep_arcsec"],
                                 4.9)
                # The clean host's rows are untouched and its
                # file carries NO audit key (clean results
                # live in the summary's query_results only).
                clean = self._read(out_dir, subdir, "999")
                self.assertEqual(clean["pass2"]["status"],
                                 "survivor")
                self.assertNotIn("vsx_filter", clean)
                # The failed host's rows are kept (fail open).
                failed = self._read(out_dir, subdir, "555")
                self.assertEqual(failed["pass2"]["status"],
                                 "survivor")
                self.assertNotIn("vsx_filter", failed)
            # Re-merge: idempotent — no new demotions, same
            # totals, same headline counts.
            summary2 = p43_run.merge_null_p43(
                out_dir, vsx_query_fn=_qfn(fail_tics=("555",)),
                vsx_coords=COORDS)
            for key in ("vsx_filter_stitched",
                        "vsx_filter_single"):
                sec2 = summary2[key]
                self.assertEqual(sec2["rows_dropped"], 0, key)
                self.assertEqual(sec2["demoted_total"], 2, key)
            self.assertEqual(summary2["stitched"]["final_rows"],
                             2)
            self.assertEqual(summary2["single"]["final_rows"], 2)

    def test_null_merge_disabled_skips_filter(self):
        with tempfile.TemporaryDirectory() as d:
            out_dir = Path(d)
            self._write_fixture(out_dir)
            called = []

            def spy(ra, dec):
                called.append((ra, dec))
                return {"hits": HIT_276788366}

            summary = p43_run.merge_null_p43(
                out_dir, vsx_query_fn=spy, vsx_coords=COORDS,
                vsx_filter=False)
            self.assertEqual(called, [])
            for key in ("vsx_filter_stitched",
                        "vsx_filter_single"):
                sec = summary[key]
                self.assertFalse(sec["applied"], key)
                self.assertIn("disabled", sec["reason"], key)
            self.assertEqual(summary["stitched"]["final_rows"], 3)
            rec = self._read(out_dir, "null-p43", "276788366")
            self.assertEqual(rec["pass2"]["status"], "survivor")

    def test_null_merge_no_coords_keeps_rows(self):
        with tempfile.TemporaryDirectory() as d:
            out_dir = Path(d)
            self._write_fixture(out_dir)
            summary = p43_run.merge_null_p43(
                out_dir, vsx_query_fn=_qfn(), vsx_coords={})
            sec = summary["vsx_filter_stitched"]
            self.assertTrue(sec["applied"])
            self.assertEqual(sec["no_coords"], 3)
            self.assertEqual(sec["queried"], 0)
            self.assertEqual(sec["rows_dropped"], 0)
            self.assertEqual(summary["stitched"]["final_rows"], 3)


class TestCampaignMergeVsxWiring(unittest.TestCase):
    def _write_fixture(self, out_dir):
        (out_dir / "hosts").mkdir()
        (out_dir / "hosts-p43").mkdir()
        manifest = {"_sha256": "x", "trials": [
            {"tic": "276788366", "sector": 95,
             "trial_id": "planet01", "group": "lockon_207",
             "period_d": 12.0, "n_events_expected": 5},
            {"tic": "999", "sector": 95, "trial_id": "planet01",
             "group": "lockon_207", "period_d": 12.0,
             "n_events_expected": 5}]}
        # Single leg (k3 stems): both trials recovered.
        single = {"tic": "276788366", "sector": 95,
                  "complete": True, "arm": "no-depth-trigger",
                  "calibration": "bulk_v6",
                  "trials": [
                      _ctrial("276788366", "planet01",
                              recovered=("pass2",), driver="k3"),
                      _ctrial("999", "planet01",
                              recovered=("pass2",), driver="k3"),
                  ]}
        # Stitched leg (p43 stems): both trials recovered.
        stitched = {"tic": "276788366",
                    "sectors": [95, 96, 97], "complete": True,
                    "arm": "no-depth-trigger",
                    "calibration": "bulk_v6",
                    "trials": [
                        _ctrial("276788366", "planet01",
                                recovered=("pass2",)),
                        _ctrial("999", "planet01",
                                recovered=("pass2",)),
                    ]}
        (out_dir / "hosts" / "276788366_s0095.json").write_text(
            json.dumps(single))
        (out_dir / "hosts-p43" / "276788366_p43.json").write_text(
            json.dumps(stitched))
        return manifest

    def _read_trial(self, out_dir, subdir, fname, tic):
        rec = json.loads(
            (out_dir / subdir / fname).read_text())
        return next(t for t in rec["trials"]
                    if t["tic"] == tic)

    def test_campaign_merge_applies_filter_both_legs(self):
        with tempfile.TemporaryDirectory() as d:
            out_dir = Path(d)
            manifest = self._write_fixture(out_dir)
            summary = p43_run.merge_campaign_p43(
                out_dir, manifest, vsx_query_fn=_qfn(),
                vsx_coords=COORDS)
            sec = summary["vsx_filter"]
            self.assertTrue(sec["applied"])
            self.assertEqual(sec["queried"], 2)
            self.assertEqual(sec["flagged_hosts"], 1)
            self.assertEqual(sec["flagged_tics"], ["276788366"])
            # One trial lost per leg, one row per leg.
            self.assertEqual(sec["trials_lost"], 2)
            self.assertEqual(sec["rows_dropped"], 2)
            self.assertEqual(sec["dropped_pass2"], 2)
            self.assertEqual(sec["demoted_total"], 2)
            # The paired list saw the demotions: the
            # long-period cell lost the flagged host on both
            # legs (2 -> 1 each). This pins the filter-before-
            # paired-list order.
            cell = summary["cells"]["long_period"]
            self.assertEqual(cell["n_trials"], 2)
            self.assertEqual(cell["single"], 1)
            self.assertEqual(cell["stitched"], 1)
            # Demotions landed in the host files, both legs.
            for subdir, fname in (
                    ("hosts", "276788366_s0095.json"),
                    ("hosts-p43", "276788366_p43.json")):
                tr = self._read_trial(out_dir, subdir, fname,
                                      "276788366")
                self.assertFalse(tr["final_recovered"])
                self.assertEqual(tr["pass2"]["status"], "demoted")
                self.assertEqual(tr["pass2"]["disposition"],
                                 _sh.DEMOTED_VSX_NEARBY_E)
                clean = self._read_trial(out_dir, subdir, fname,
                                         "999")
                self.assertTrue(clean["final_recovered"])
                self.assertEqual(clean["pass2"]["status"],
                                 "survivor")
            # Re-merge: idempotent.
            summary2 = p43_run.merge_campaign_p43(
                out_dir, manifest, vsx_query_fn=_qfn(),
                vsx_coords=COORDS)
            sec2 = summary2["vsx_filter"]
            self.assertEqual(sec2["rows_dropped"], 0)
            self.assertEqual(sec2["trials_lost"], 0)
            self.assertEqual(sec2["demoted_total"], 2)
            cell2 = summary2["cells"]["long_period"]
            self.assertEqual(cell2["single"], 1)
            self.assertEqual(cell2["stitched"], 1)

    def test_campaign_merge_disabled_skips_filter(self):
        with tempfile.TemporaryDirectory() as d:
            out_dir = Path(d)
            manifest = self._write_fixture(out_dir)
            called = []

            def spy(ra, dec):
                called.append((ra, dec))
                return {"hits": HIT_276788366}

            summary = p43_run.merge_campaign_p43(
                out_dir, manifest, vsx_query_fn=spy,
                vsx_coords=COORDS, vsx_filter=False)
            self.assertEqual(called, [])
            sec = summary["vsx_filter"]
            self.assertFalse(sec["applied"])
            self.assertIn("disabled", sec["reason"])
            cell = summary["cells"]["long_period"]
            self.assertEqual(cell["single"], 2)
            self.assertEqual(cell["stitched"], 2)


class TestFetchVsxCoords(unittest.TestCase):
    def test_batches_and_fails_open_per_batch(self):
        calls = []

        def fake_batch(ids):
            calls.append(list(ids))
            if "3" in ids:
                raise RuntimeError("MAST down")
            return {str(i): {"ra": float(i), "dec": -1.0,
                             "tmag": 10.0, "radius": 0.5}
                    for i in ids}

        with mock.patch.object(bs, "_tic_batch",
                               side_effect=fake_batch):
            with mock.patch.object(p43_run,
                                   "_VSX_COORD_BATCH", 2):
                coords, failed = p43_run._fetch_vsx_coords(
                    ["1", "2", "3", "4", "5"])
        # Batches of 2: [1,2] ok, [3,4] failed, [5] ok.
        self.assertEqual(coords, {"1": {"ra": 1.0, "dec": -1.0},
                                  "2": {"ra": 2.0, "dec": -1.0},
                                  "5": {"ra": 5.0, "dec": -1.0}})
        self.assertEqual(failed, ["3", "4"])
        self.assertEqual(len(calls), 3)

    def test_tics_missing_ra_dec_are_dropped(self):
        def fake_batch(ids):
            return {"1": {"ra": 1.0, "dec": None,
                          "tmag": 10.0, "radius": 0.5},
                    "2": {"ra": 2.0, "dec": -1.0,
                          "tmag": 10.0, "radius": 0.5}}

        with mock.patch.object(bs, "_tic_batch",
                               side_effect=fake_batch):
            coords, failed = p43_run._fetch_vsx_coords(["1", "2"])
        self.assertEqual(coords, {"2": {"ra": 2.0, "dec": -1.0}})
        self.assertEqual(failed, [])


if __name__ == "__main__":
    unittest.main()
