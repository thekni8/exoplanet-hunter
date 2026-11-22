"""Tests for the stitched-leg few-event T0-cluster veto (ELIGFIX
follow-up, 2026-11-22; Dev approved "Build the veto fix" 2026-11-22
09:29 IST).

The veto (ELIGFIX_FOLLOWUP.md option #1): F-1 extended to the
stitched leg. The stitched leg had NO T0 veto at all — the scorer
removed clusters post-hoc (the diagnosis-style residual), which is
a measurement, not a fix. The veto clusters the stitched leg's
final rows by T0 ALONE within 0.125 d (union-find linkage, the
F-1/probe3 definition) and demotes rows in clusters of >=3 where
the row has n_events <= 2 (few-event scope).

The few-event scope is LOAD-BEARING: without it, a T0 veto at
bar >=3 would remove 145/170 (85%) of the M4-p43 planets —
short-period planets' first transits legitimately pile up within
a few days of the baseline start. With the scope, the cost is
0/170. The bar is >=3, not F-1's >20: the largest few-event
cluster is 14 (scales to ~19 at the full 3,688-host pool), so
F-1's bar would never fire on the stitched leg.

Placement: merge-time in p43_run (both merges), mirroring F-1's
merge-only placement in run_chunked — clusters span hosts, so a
per-host veto would under-demote. Vetoed rows are demoted in the
host files (status "demoted", disposition DEMOTED_T0_CLUSTER,
flag T0_CLUSTER) with the survivor flags updated, so scorers
reading the host files see the veto; the merge summary records
the veto section. Gated on the stitched profile keys (bulk_v6
only) — v5 reproductions stay bit-identical.

Offline: synthetic rows + two verbatim fixtures only, no
downloads, no Mac, no campaign.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import bulk_screen as bs  # noqa: E402
from bulk import p43_run as p43run  # noqa: E402
from bulk import replay_matrix as _rm  # noqa: E402
from calibration import CalibrationError, load_profile  # noqa: E402

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "golden"
PAIRED74 = FIXTURE_DIR / "stitched_veto_paired74.json"
M4P43_170 = FIXTURE_DIR / "stitched_veto_m4p43_170.json"

# The 7 tier-B gained rows (ELIGFIX follow-up table 1.2): the veto
# must remove all of them. The 5 tier-A gained rows must survive
# (n_ev 3-4, outside the few-event scope).
TIER_B_GAINED = {("141473804", "pass2"), ("141756964", "pass2"),
                 ("25081334", "pass2"), ("278728951", "pass2"),
                 ("358402715", "pass2"), ("55403890", "pass2"),
                 ("55403890", "pass3")}
TIER_A_GAINED = {("141214102", "pass2"), ("149503103", "pass2"),
                 ("220456623", "pass2"), ("279637932", "pass2"),
                 ("381924905", "pass2")}


def _vrow(tic, t0, n_events=1, tier="B", period=3.0, pk="pass2"):
    """A synthetic stitched final row for the veto tests."""
    return {"tic": str(tic), "pass": pk, "t0_btjd": t0,
            "period_days": period, "n_events": n_events,
            "tier": tier, "status": "survivor", "flags": []}


def _vcluster(n, t0=3920.0, tic0=30000, **kw):
    """n few-event rows sharing T0 within the tolerance."""
    return [_vrow(tic0 + i, t0 + 0.001 * i, **kw)
            for i in range(n)]


class TestStitchedVetoProfile(unittest.TestCase):
    """The stitched veto's profile plumbing (mirrors F-1)."""

    def test_bulk_v6_enables_stitched_veto(self):
        prof = load_profile("bulk_v6")
        self.assertEqual(prof["stitched_t0_cluster_tol_t0_d"],
                         _rm.STITCHED_T0_CLUSTER_TOL_T0_D)
        self.assertEqual(prof["stitched_t0_cluster_min_size"],
                         _rm.STITCHED_T0_CLUSTER_MIN_SIZE)
        self.assertEqual(prof["stitched_t0_cluster_max_events"],
                         _rm.STITCHED_T0_CLUSTER_MAX_EVENTS)
        previous = bs.CALIBRATION_VERSION
        try:
            bs.set_calibration("bulk_v6")
            self.assertIs(bs.STITCHED_T0_CLUSTER_VETO_ENABLED, True)
            self.assertEqual(bs.STITCHED_T0_CLUSTER_TOL_T0_D, 0.125)
            self.assertEqual(bs.STITCHED_T0_CLUSTER_MIN_SIZE, 3)
            self.assertEqual(bs.STITCHED_T0_CLUSTER_MAX_EVENTS, 2)
        finally:
            bs.set_calibration(previous)

    def test_earlier_profiles_leave_stitched_veto_off(self):
        # A frozen profile's behaviour must not change: v1-v5
        # predate the stitched keys, so the veto is OFF and the
        # criterion values are the inert defaults.
        previous = bs.CALIBRATION_VERSION
        try:
            for name in ("bulk_v1", "bulk_v2", "bulk_v3",
                         "bulk_v4", "bulk_v5"):
                bs.set_calibration(name)
                self.assertIs(
                    bs.STITCHED_T0_CLUSTER_VETO_ENABLED, False,
                    f"{name} must mean the stitched veto off")
                self.assertEqual(
                    bs.STITCHED_T0_CLUSTER_TOL_T0_D, 0.125)
                self.assertEqual(bs.STITCHED_T0_CLUSTER_MIN_SIZE, 3)
                self.assertEqual(bs.STITCHED_T0_CLUSTER_MAX_EVENTS, 2)
        finally:
            bs.set_calibration(previous)

    def test_apply_profile_fails_loud_on_stitched_mismatch(self):
        # Each stitched criterion value diverging from
        # replay_matrix's constants fails loudly — the P3-15
        # pattern. The loader must refuse the profile, never
        # silently screen under a different criterion.
        previous = bs.CALIBRATION_VERSION
        try:
            for key, bad in (
                    ("stitched_t0_cluster_tol_t0_d", 0.25),
                    ("stitched_t0_cluster_min_size", 5),
                    ("stitched_t0_cluster_max_events", 3)):
                prof = load_profile("bulk_v6")
                prof[key] = bad
                with self.assertRaises(CalibrationError,
                                       msg=f"{key}={bad} must "
                                       f"fail loud"):
                    bs._apply_profile(prof)
        finally:
            bs.set_calibration(previous)


class TestStitchedVetoUnits(unittest.TestCase):
    """The pure veto function (bulk_v6 criterion)."""

    def setUp(self):
        self.previous = bs.CALIBRATION_VERSION
        bs.set_calibration("bulk_v6")

    def tearDown(self):
        bs.set_calibration(self.previous)

    def test_demotes_clustered_few_event_rows(self):
        rows = _vcluster(3) + _vcluster(2, t0=3950.0, tic0=40000)
        kept, summary = bs.apply_stitched_t0_veto(rows)
        self.assertEqual(len(kept), 2)
        self.assertEqual(summary["demoted"], 3)
        self.assertEqual(summary["n_clusters"], 1)
        self.assertEqual(summary["cluster_sizes"], [3])
        self.assertEqual(summary["demoted_pass2"], 3)
        self.assertEqual(summary["demoted_pass3"], 0)

    def test_bar_edge(self):
        # A cluster of 2 survives; a cluster of 3 is vetoed.
        rows = _vcluster(2)
        kept, summary = bs.apply_stitched_t0_veto(rows)
        self.assertEqual(len(kept), 2)
        self.assertEqual(summary["demoted"], 0)
        rows = _vcluster(3)
        kept, summary = bs.apply_stitched_t0_veto(rows)
        self.assertEqual(len(kept), 0)
        self.assertEqual(summary["demoted"], 3)

    def test_tolerance_edge(self):
        # Exactly 0.125 d apart clusters (<= tol); 0.126 d does
        # not. Chaining: three rows spanning 0.25 d in 0.125 d
        # steps are ONE cluster (transitive linkage, not bins).
        rows = [_vrow(30000, 3920.0), _vrow(30001, 3920.125),
                _vrow(30002, 3920.25)]
        kept, summary = bs.apply_stitched_t0_veto(rows)
        self.assertEqual(summary["demoted"], 3)
        rows = [_vrow(30000, 3920.0), _vrow(30001, 3920.126),
                _vrow(30002, 3920.252)]
        kept, summary = bs.apply_stitched_t0_veto(rows)
        self.assertEqual(summary["demoted"], 0)
        self.assertEqual(len(kept), 3)

    def test_few_event_scope(self):
        # n_ev 1-2 vetoed in a cluster; n_ev >= 3 untouched even
        # inside a qualifying cluster — and multi-event rows
        # neither count toward the bar nor get demoted.
        rows = (_vcluster(2)
                + _vcluster(5, t0=3920.0, tic0=41000,
                            n_events=5, tier="A"))
        kept, summary = bs.apply_stitched_t0_veto(rows)
        self.assertEqual(len(kept), 7)
        self.assertEqual(summary["demoted"], 0)
        rows = (_vcluster(3)
                + _vcluster(5, t0=3920.0, tic0=41000,
                            n_events=5, tier="A"))
        kept, summary = bs.apply_stitched_t0_veto(rows)
        self.assertEqual(len(kept), 5)
        self.assertEqual(summary["demoted"], 3)
        self.assertTrue(all(r["n_events"] == 5 for r in kept))
        # n_ev = 3 is outside the scope even at the bar.
        rows = _vcluster(3, n_events=3, tier="A")
        kept, summary = bs.apply_stitched_t0_veto(rows)
        self.assertEqual(len(kept), 3)
        self.assertEqual(summary["demoted"], 0)

    def test_multi_event_cluster_never_fires(self):
        # The 145/170 hazard in miniature: five multi-event rows
        # at one epoch form no cluster at all — the veto sees
        # only few-event rows.
        rows = _vcluster(5, n_events=8, tier="A")
        kept, summary = bs.apply_stitched_t0_veto(rows)
        self.assertEqual(len(kept), 5)
        self.assertEqual(summary["demoted"], 0)
        self.assertEqual(summary["n_clusters"], 0)

    def test_rows_without_t0_or_events_kept(self):
        rows = _vcluster(3)
        no_t0 = _vrow("44000", None)
        no_events = _vrow("44001", 3920.0)
        del no_events["n_events"]
        rows += [no_t0, no_events]
        kept, summary = bs.apply_stitched_t0_veto(rows)
        self.assertEqual(summary["demoted"], 3)
        self.assertEqual(len(kept), 2)
        self.assertIn(no_t0, kept)
        self.assertIn(no_events, kept)

    def test_demoted_rows_carry_reason(self):
        rows = _vcluster(3)
        kept, summary = bs.apply_stitched_t0_veto(rows)
        self.assertEqual(len(kept), 0)
        for r in rows:
            self.assertEqual(r["status"], "demoted")
            self.assertEqual(r["disposition"],
                             "DEMOTED_T0_CLUSTER")
            self.assertIn("T0_CLUSTER", r["flags"])

    def test_idempotent(self):
        rows = _vcluster(3)
        kept, first = bs.apply_stitched_t0_veto(rows)
        self.assertEqual(first["demoted"], 3)
        kept2, second = bs.apply_stitched_t0_veto(kept)
        self.assertEqual(second["demoted"], 0)
        self.assertEqual(kept2, kept)

    def test_explicit_parameters_live(self):
        # Non-default min_size is live, not ignored.
        rows = _vcluster(4)
        _, summary = bs.apply_stitched_t0_veto(rows, min_size=4)
        self.assertEqual(summary["demoted"], 4)
        rows = _vcluster(4)
        _, summary = bs.apply_stitched_t0_veto(rows, min_size=5)
        self.assertEqual(summary["demoted"], 0)

    def test_summary_carries_pass_split(self):
        rows = (_vcluster(3, pk="pass2")
                + _vcluster(3, tic0=42000, pk="pass3"))
        _, summary = bs.apply_stitched_t0_veto(rows)
        self.assertEqual(summary["demoted"], 6)
        self.assertEqual(summary["demoted_pass2"], 3)
        self.assertEqual(summary["demoted_pass3"], 3)
        # The F-1 pass-1/K=3 split is meaningless on the
        # stitched leg and must not appear.
        self.assertNotIn("demoted_pass1", summary)
        self.assertNotIn("demoted_k3", summary)


class TestStitchedVetoReplay(unittest.TestCase):
    """Replay the veto on the frozen records (no re-run)."""

    @classmethod
    def setUpClass(cls):
        cls.paired = json.loads(PAIRED74.read_text())
        cls.m4 = json.loads(M4P43_170.read_text())

    def setUp(self):
        self.previous = bs.CALIBRATION_VERSION
        bs.set_calibration("bulk_v6")

    def tearDown(self):
        bs.set_calibration(self.previous)

    def test_fixture_shape(self):
        self.assertEqual(len(self.paired["rows"]), 74)
        self.assertEqual(len(self.m4["rows"]), 170)
        self.assertIn("provenance", self.paired)
        self.assertIn("provenance", self.m4)
        tiers = {}
        for r in self.m4["rows"]:
            tiers[r["tier"]] = tiers.get(r["tier"], 0) + 1
        self.assertEqual(tiers, {"A": 168, "B": 2})
        for r in self.paired["rows"] + self.m4["rows"]:
            self.assertIn("tic", r)
            self.assertIn("t0_btjd", r)
            self.assertIn("n_events", r)

    def test_paired74_replay(self):
        # The follow-up's measured effect, exactly: 74 -> 45
        # (29 removed, few-event clusters 14/9/3/3), all 7
        # tier-B gained rows removed, none of the 5 tier-A
        # gained rows touched.
        rows = [dict(r, flags=[]) for r in self.paired["rows"]]
        kept, summary = bs.apply_stitched_t0_veto(rows)
        self.assertEqual(len(kept), 45)
        self.assertEqual(summary["demoted"], 29)
        self.assertEqual(summary["cluster_sizes"], [14, 9, 3, 3])
        kept_keys = {(r["tic"], r["pass"]) for r in kept}
        removed_keys = {(r["tic"], r["pass"]) for r in rows} \
            - kept_keys
        self.assertTrue(TIER_B_GAINED <= removed_keys,
                        "a tier-B gained row survived the veto")
        self.assertTrue(TIER_A_GAINED <= kept_keys,
                        "a tier-A gained row was vetoed")

    def test_m4p43_170_zero_cost(self):
        # The E6 floor: the veto costs 0/170 planets. Only 2
        # rows are few-event (both tier B), and neither sits in
        # a >=3 few-event cluster.
        rows = [dict(r, flags=[]) for r in self.m4["rows"]]
        kept, summary = bs.apply_stitched_t0_veto(rows)
        self.assertEqual(len(kept), 170)
        self.assertEqual(summary["demoted"], 0)
        few_event = {(r["tic"], r["pass"]) for r in rows
                     if (r.get("n_events") or 99) <= 2}
        self.assertEqual(few_event,
                         {("220576424", "pass3"),
                          ("381977544", "pass2")})
        kept_keys = {(r["tic"], r["pass"]) for r in kept}
        self.assertTrue(few_event <= kept_keys)


def _null_host(tic, calibration, pass2=None, pass3=None):
    """A minimal stitched null-leg host record."""
    rec = {"tic": str(tic), "complete": True,
           "arm": "no-depth-trigger",
           "pass1": {"period_days": 3.0, "status": "recorded"},
           "pass1_survivor": False,
           "pass2": pass2, "pass3": pass3,
           "pass2_survivor": bool(pass2 is not None
                                  and pass2.get("status")
                                  == "survivor"),
           "pass3_survivor": bool(pass3 is not None
                                  and pass3.get("status")
                                  == "survivor")}
    rec["final_rows"] = (int(rec["pass2_survivor"])
                         + int(rec["pass3_survivor"]))
    rec["final_survivor"] = bool(rec["final_rows"])
    if calibration is not None:
        rec["calibration"] = calibration
    return rec


def _null_single(tic):
    return {"tic": str(tic), "complete": True,
            "arm": "no-depth-trigger",
            "pass1_survivor": False, "pass2_survivor": False,
            "pass3_survivor": False}


class TestStitchedVetoMergeNull(unittest.TestCase):
    """Merge-time veto on the null leg (run-time, not scoring)."""

    def setUp(self):
        self.previous = bs.CALIBRATION_VERSION
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name)
        (self.out / "null-p43").mkdir()
        (self.out / "null_hosts").mkdir()

    def tearDown(self):
        bs.set_calibration(self.previous)
        self.tmp.cleanup()

    def _write_fixture(self, calibration):
        # 3 clustered few-event pass-2 survivors (A/B/C) + 1
        # clustered few-event pass-3 survivor (F) + 1
        # unclustered few-event survivor (D) + 1 multi-event
        # survivor inside the cluster (E) + 1 non-survivor (G).
        hosts = [
            _null_host(1001, calibration,
                       pass2=_vrow(1001, 3920.00)),
            _null_host(1002, calibration,
                       pass2=_vrow(1002, 3920.05)),
            _null_host(1003, calibration,
                       pass2=_vrow(1003, 3920.10, n_events=2)),
            _null_host(1004, calibration,
                       pass2=_vrow(1004, 3950.00)),
            _null_host(1005, calibration,
                       pass2=_vrow(1005, 3920.02, n_events=5,
                                   tier="A")),
            _null_host(1006, calibration,
                       pass2={"period_days": 3.0,
                              "status": "recorded"},
                       pass3=_vrow(1006, 3920.08, pk="pass3")),
            _null_host(1007, calibration,
                       pass2={"period_days": 3.0,
                              "status": "recorded"}),
        ]
        for h in hosts:
            (self.out / "null-p43"
             / f"{h['tic']}_p43.json").write_text(json.dumps(h))
            (self.out / "null_hosts"
             / f"{h['tic']}_s0096.json").write_text(
                 json.dumps(_null_single(h["tic"])))
        return hosts

    def _read_null(self, tic):
        return json.loads(
            (self.out / "null-p43" / f"{tic}_p43.json").read_text())

    def test_null_merge_applies_veto_and_is_idempotent(self):
        self._write_fixture("bulk_v6")
        summary = p43run.merge_null_p43(self.out)
        veto = summary["stitched_t0_cluster_veto"]
        self.assertTrue(veto["applied"])
        self.assertEqual(veto["demoted"], 4)
        self.assertEqual(veto["demoted_total"], 4)
        self.assertEqual(veto["demoted_pass2"], 3)
        self.assertEqual(veto["demoted_pass3"], 1)
        self.assertEqual(veto["n_clusters"], 1)
        self.assertEqual(veto["cluster_sizes"], [4])
        # The headline counts reflect the veto: 6 -> 2 rows.
        self.assertEqual(summary["stitched"]["final_rows"], 2)
        # The demotions landed in the rewritten host files.
        for tic, pk in ((1001, "pass2"), (1002, "pass2"),
                        (1003, "pass2"), (1006, "pass3")):
            rec = self._read_null(tic)
            row = rec[pk]
            self.assertEqual(row["status"], "demoted", (tic, pk))
            self.assertEqual(row["disposition"],
                             "DEMOTED_T0_CLUSTER", (tic, pk))
            self.assertIn("T0_CLUSTER", row["flags"], (tic, pk))
            self.assertIs(rec[f"{pk}_survivor"], False, (tic, pk))
        self.assertEqual(self._read_null(1006)["final_rows"], 0)
        self.assertIs(self._read_null(1006)["final_survivor"],
                      False)
        # The unclustered and multi-event survivors are untouched.
        self.assertEqual(
            self._read_null(1004)["pass2"]["status"], "survivor")
        self.assertEqual(
            self._read_null(1005)["pass2"]["status"], "survivor")
        # Re-merge: idempotent — no new demotions, same counts,
        # same total.
        summary2 = p43run.merge_null_p43(self.out)
        veto2 = summary2["stitched_t0_cluster_veto"]
        self.assertTrue(veto2["applied"])
        self.assertEqual(veto2["demoted"], 0)
        self.assertEqual(veto2["demoted_total"], 4)
        self.assertEqual(summary2["stitched"]["final_rows"], 2)

    def test_null_merge_v5_gate_off(self):
        self._write_fixture("bulk_v5")
        summary = p43run.merge_null_p43(self.out)
        veto = summary["stitched_t0_cluster_veto"]
        self.assertFalse(veto["applied"])
        self.assertEqual(summary["stitched"]["final_rows"], 6)
        # No host file was touched: no disposition anywhere.
        for tic in (1001, 1002, 1003, 1006):
            rec = self._read_null(tic)
            for pk in ("pass2", "pass3"):
                row = rec.get(pk)
                if isinstance(row, dict):
                    self.assertNotIn("disposition", row, (tic, pk))

    def test_null_merge_missing_calibration_skips_veto(self):
        # Fixture host files without a calibration stamp (the
        # existing test fixtures' shape): the veto fails closed
        # — skipped, counts unchanged.
        self._write_fixture(None)
        summary = p43run.merge_null_p43(self.out)
        veto = summary["stitched_t0_cluster_veto"]
        self.assertFalse(veto["applied"])
        self.assertIn("calibration", veto["reason"])
        self.assertEqual(summary["stitched"]["final_rows"], 6)


class TestStitchedVetoMergeCampaign(unittest.TestCase):
    """Merge-time veto on the campaign leg."""

    def setUp(self):
        self.previous = bs.CALIBRATION_VERSION
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name)
        (self.out / "hosts").mkdir()
        (self.out / "hosts-p43").mkdir()

    def tearDown(self):
        bs.set_calibration(self.previous)
        self.tmp.cleanup()

    def _write_fixture(self, calibration):
        manifest = {"_sha256": "x",
                    "trials": [
                        {"tic": "1", "sector": 95,
                         "trial_id": "planet01",
                         "group": "lockon_207", "period_d": 3.0,
                         "n_events_expected": 5},
                        {"tic": "1", "sector": 95,
                         "trial_id": "planet02",
                         "group": "lockon_207", "period_d": 3.0,
                         "n_events_expected": 5},
                        {"tic": "1", "sector": 95,
                         "trial_id": "planet03",
                         "group": "lockon_207", "period_d": 3.0,
                         "n_events_expected": 5},
                        {"tic": "2", "sector": 95,
                         "trial_id": "planet01",
                         "group": "lockon_207", "period_d": 3.0,
                         "n_events_expected": 5}]}
        single1 = {"tic": "1", "sector": 95, "complete": True,
                   "arm": "no-depth-trigger",
                   "trials": [
                       {"tic": "1", "sector": 95,
                        "trial_id": tid, "group": "x",
                        "period_d": 3.0, "final_recovered": True,
                        "final_genuine": True, "seconds": 1.0,
                        "k2_recovered": True,
                        "pass1": {"period_days": 3.0},
                        "pass1_repro": {"ok": True}}
                       for tid in ("planet01", "planet02",
                                   "planet03")]}
        single2 = {"tic": "2", "sector": 95, "complete": True,
                   "arm": "no-depth-trigger",
                   "trials": [
                       {"tic": "2", "sector": 95,
                        "trial_id": "planet01", "group": "x",
                        "period_d": 3.0, "final_recovered": True,
                        "final_genuine": True, "seconds": 1.0,
                        "k2_recovered": True,
                        "pass1": {"period_days": 3.0},
                        "pass1_repro": {"ok": True}}]}
        t0s = {"planet01": 3920.00, "planet02": 3920.05,
               "planet03": 3920.10}

        def _stitched_trial(tic, tid, t0):
            return {"tic": tic, "sector": 95, "trial_id": tid,
                    "final_recovered": True,
                    "final_genuine": True, "seconds": 4.0,
                    "inj_check_ok": True,
                    "p2_recovered": True, "p3_recovered": False,
                    "p2_genuine": True, "p3_genuine": False,
                    "pass2": _vrow(tic, t0),
                    "pass3": None,
                    "sectors": {"95": {"pass1": {
                        "period_days": 3.0}}}}

        stitched1 = {"tic": "1", "sectors": [95, 96, 97],
                     "complete": True, "arm": "no-depth-trigger",
                     "trials": [_stitched_trial("1", tid, t0s[tid])
                                for tid in ("planet01", "planet02",
                                            "planet03")]}
        stitched2 = {"tic": "2", "sectors": [95, 96, 97],
                     "complete": True, "arm": "no-depth-trigger",
                     "trials": [_stitched_trial("2", "planet01",
                                                3950.0)]}
        if calibration is not None:
            stitched1["calibration"] = calibration
            stitched2["calibration"] = calibration
        (self.out / "hosts" / "1_s0095.json").write_text(
            json.dumps(single1))
        (self.out / "hosts" / "2_s0095.json").write_text(
            json.dumps(single2))
        (self.out / "hosts-p43" / "1_p43.json").write_text(
            json.dumps(stitched1))
        (self.out / "hosts-p43" / "2_p43.json").write_text(
            json.dumps(stitched2))
        return manifest

    def _read_stitched(self, tic):
        return json.loads(
            (self.out / "hosts-p43" / f"{tic}_p43.json").read_text())

    def test_campaign_merge_applies_veto(self):
        manifest = self._write_fixture("bulk_v6")
        summary = p43run.merge_campaign_p43(self.out, manifest)
        veto = summary["stitched_t0_cluster_veto"]
        self.assertTrue(veto["applied"])
        self.assertEqual(veto["demoted"], 3)
        self.assertEqual(veto["demoted_total"], 3)
        self.assertEqual(veto["demoted_pass2"], 3)
        self.assertEqual(summary["n_trials_paired"], 4)
        # The 3 clustered trials lost their recovery; the
        # unclustered trial kept it.
        st1 = self._read_stitched("1")
        for tr in st1["trials"]:
            self.assertIs(tr["final_recovered"], False,
                          tr["trial_id"])
            self.assertIs(tr["final_genuine"], False,
                          tr["trial_id"])
            self.assertIs(tr["p2_recovered"], False,
                          tr["trial_id"])
            self.assertEqual(tr["pass2"]["status"], "demoted",
                             tr["trial_id"])
            self.assertEqual(tr["pass2"]["disposition"],
                             "DEMOTED_T0_CLUSTER", tr["trial_id"])
            self.assertIn("T0_CLUSTER", tr["pass2"]["flags"],
                          tr["trial_id"])
        st2 = self._read_stitched("2")
        self.assertIs(st2["trials"][0]["final_recovered"], True)
        self.assertEqual(st2["trials"][0]["pass2"]["status"],
                         "survivor")
        # Re-merge: idempotent.
        summary2 = p43run.merge_campaign_p43(self.out, manifest)
        veto2 = summary2["stitched_t0_cluster_veto"]
        self.assertEqual(veto2["demoted"], 0)
        self.assertEqual(veto2["demoted_total"], 3)

    def test_campaign_merge_v5_gate_off(self):
        manifest = self._write_fixture("bulk_v5")
        summary = p43run.merge_campaign_p43(self.out, manifest)
        veto = summary["stitched_t0_cluster_veto"]
        self.assertFalse(veto["applied"])
        st1 = self._read_stitched("1")
        for tr in st1["trials"]:
            self.assertIs(tr["final_recovered"], True,
                          tr["trial_id"])
            self.assertNotIn("disposition", tr["pass2"],
                             tr["trial_id"])


if __name__ == "__main__":
    unittest.main()
