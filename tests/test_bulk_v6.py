"""Golden-suite tests for bulk_v6 (bulk_v6 build, PIPE50 vote).

bulk_v6 is ACTIVE (2026-11-20): all bulk_v5 gates carried over
verbatim, plus FOUR changes — F-1 merge-time T0-cluster veto
(few-event rows, T0-only union-find linkage, 3 h, clusters >20
stars; disposition DEMOTED_T0_CLUSTER), B-1 K=3 join after the
(P, T0) veto, mask gating (mask only when pass-1 is
contaminant-like: EB flag or depth > 1.0%), stitched pass-1
recording default-on. PIPE50 vote ref PIPE50-20261119
(RATIFIED 2026-11-19 14:00 IST). F-1 evidence
(NULL_DIAGNOSIS, PROVEN): 158/213 null finals T0-clustered.
The 8.33/1,000 bound is KEPT (PIPE50-5).

These tests pin the profile shape AND the loader wiring (the
v6 change is profile + wiring; each gate's behaviour lives in
its own test module). Offline, no downloads.
"""
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import bulk_screen as bs  # noqa: E402
from bulk import k2_prototype as k2  # noqa: E402
from bulk import k3_run as k3run  # noqa: E402
from bulk import oracle_run as orc  # noqa: E402
from bulk import p43_run as p43run  # noqa: E402
from bulk import p4110_score as s4110  # noqa: E402
from bulk import p413_score as s413  # noqa: E402
from bulk import replay_matrix as _rm  # noqa: E402
from bulk.p4110_score import GateBars  # noqa: E402
from calibration import (CalibrationError, load_profile,  # noqa: E402
                         load_registry, profile_sha256)
from synth_fits import make_qlp_fits  # noqa: E402

# Every gate field that must be identical between bulk_v5 and
# bulk_v6 (any difference besides the 8 new keys is a threshold
# change, which needs the adoption rule + the campaign
# measurement behind it).
GATE_FIELDS = (
    "record_floor_sde", "survivor_sde", "depth_min_pct",
    "depth_eb_pct", "tier_a_mes", "tier_a_min_events",
    "tier_a_min_strong", "strong_event_snr", "tier_b_event_snr",
    "tier_b_max_depth_pct", "min_period_d", "max_period_d",
    "bls_grid_points", "bls_durations_d", "systematic_periods",
    "systematic_windows", "quality_mask", "clip_option",
    "two_combined_enabled", "epoch_cluster_veto_enabled",
    "epoch_cluster_veto_tier_a",
    "epoch_cluster_tol_p", "epoch_cluster_tol_t0_d",
    "epoch_cluster_min_size",
    "grid_edge_min_in_transit_cadences",
    "grid_edge_max_unmasked_flag_fraction",
)

# The 8 new bulk_v6 keys and their adopted values (design §1).
NEW_KEYS = {
    "t0_cluster_veto_enabled": True,
    "t0_cluster_tol_t0_d": 0.125,
    "t0_cluster_min_size": 21,
    "t0_cluster_max_events": 2,
    "k3_join_after_veto": True,
    "mask_gate_enabled": True,
    "mask_gate_depth_pct": 1.0,
    "record_pass1_stitched": True,
}

# Frozen profiles: bulk_v5 stamped the Phase 4.1 campaigns
# (4.1-2/4.1-3/4.1-10, bright-star curve) and is immutable
# from here on.
FROZEN = {
    "bulk_v5": "d8792db9de7ba0848d936931e103e2fc1b64a213c8848932c0152a560627f6d1",
}


class TestBulkV6Scaffold(unittest.TestCase):
    def test_v6_loads_and_is_active(self):
        prof = load_profile("bulk_v6")
        self.assertEqual(prof["version"], "bulk_v6")
        self.assertEqual(prof["status"], "active")
        self.assertTrue(prof["rationale"].strip())
        for key, want in NEW_KEYS.items():
            self.assertIn(key, prof)
            self.assertEqual(prof[key], want,
                             f"bulk_v6 {key} is {prof[key]!r}, "
                             f"expected {want!r}")

    def test_v6_registry_sha_matches(self):
        registry = load_registry()
        self.assertIn("bulk_v6", registry)
        self.assertEqual(registry["bulk_v6"]["sha256"],
                         profile_sha256("bulk_v6"))
        self.assertEqual(registry["bulk_v6"]["supersedes"], "bulk_v5")
        self.assertEqual(registry["bulk_v6"]["status"], "active")

    def test_v6_gates_identical_to_v5_except_new_keys(self):
        v5 = load_profile("bulk_v5")
        v6 = load_profile("bulk_v6")
        for field in GATE_FIELDS:
            self.assertEqual(
                v6[field], v5[field],
                f"bulk_v6 {field} differs from bulk_v5 — the v6 "
                f"change is the 8 new keys only")
        # The only differences: v5 has none of the 8 new keys.
        for key in NEW_KEYS:
            self.assertNotIn(key, v5)
        # SDE bars unchanged (the vote fixed them).
        self.assertEqual(v6["survivor_sde"], 7.0)
        self.assertEqual(v6["record_floor_sde"], 6.0)

    def test_frozen_v5_byte_identical(self):
        for name, want in FROZEN.items():
            self.assertEqual(profile_sha256(name), want,
                             f"{name} changed — frozen profiles "
                             f"are immutable")

    def test_f1_constants_match_replay_matrix(self):
        # The profile's F-1 criterion and the implementation's
        # constants are the same numbers, in two homes — the
        # loader enforces this, and this test pins both sides.
        prof = load_profile("bulk_v6")
        self.assertEqual(prof["t0_cluster_tol_t0_d"],
                         _rm.T0_CLUSTER_TOL_T0_D)
        self.assertEqual(prof["t0_cluster_min_size"],
                         _rm.T0_CLUSTER_MIN_SIZE)
        self.assertEqual(prof["t0_cluster_max_events"],
                         _rm.T0_CLUSTER_MAX_EVENTS)

    def test_set_calibration_derives_v6_globals(self):
        # True under v6, off under every earlier profile (a
        # frozen profile's behaviour must not change).
        previous = bs.CALIBRATION_VERSION
        try:
            bs.set_calibration("bulk_v6")
            self.assertEqual(bs.CALIBRATION_VERSION, "bulk_v6")
            self.assertIs(bs.T0_CLUSTER_VETO_ENABLED, True)
            self.assertEqual(bs.T0_CLUSTER_TOL_T0_D, 0.125)
            self.assertEqual(bs.T0_CLUSTER_MIN_SIZE, 21)
            self.assertEqual(bs.T0_CLUSTER_MAX_EVENTS, 2)
            self.assertIs(bs.K3_JOIN_AFTER_VETO, True)
            self.assertIs(bs.MASK_GATE_ENABLED, True)
            self.assertEqual(bs.MASK_GATE_DEPTH_PCT, 1.0)
            self.assertIs(bs.RECORD_PASS1_STITCHED, True)
            # Carried from v5.
            self.assertIs(bs.EPOCH_CLUSTER_VETO_TIER_A, True)
            for name in ("bulk_v1", "bulk_v2", "bulk_v3",
                         "bulk_v4", "bulk_v5"):
                bs.set_calibration(name)
                self.assertIs(bs.T0_CLUSTER_VETO_ENABLED, False,
                              f"{name} must mean the F-1 veto off")
                self.assertIs(bs.K3_JOIN_AFTER_VETO, False,
                              f"{name} must mean join-before-veto")
                self.assertIs(bs.MASK_GATE_ENABLED, False,
                              f"{name} must mean the mask gate off")
                self.assertIs(bs.RECORD_PASS1_STITCHED, False,
                              f"{name} must mean no pass-1 "
                              f"recording")
                # Criterion defaults are the F-1 values, inert
                # while the veto is off.
                self.assertEqual(bs.T0_CLUSTER_TOL_T0_D, 0.125)
                self.assertEqual(bs.T0_CLUSTER_MIN_SIZE, 21)
                self.assertEqual(bs.T0_CLUSTER_MAX_EVENTS, 2)
        finally:
            bs.set_calibration(previous)

    def test_apply_profile_fails_loud_on_f1_mismatch(self):
        # Each F-1 criterion value diverging from
        # replay_matrix's constants fails loudly — the P3-15
        # pattern. The loader must refuse the profile, never
        # silently screen under a different criterion.
        previous = bs.CALIBRATION_VERSION
        try:
            for key, bad in (("t0_cluster_tol_t0_d", 0.25),
                             ("t0_cluster_min_size", 10),
                             ("t0_cluster_max_events", 3)):
                prof = load_profile("bulk_v6")
                prof[key] = bad
                with self.assertRaises(CalibrationError,
                                       msg=f"{key}={bad} must "
                                       f"fail loud"):
                    bs._apply_profile(prof)
        finally:
            bs.set_calibration(previous)

    def test_apply_profile_fails_loud_on_bad_mask_depth(self):
        previous = bs.CALIBRATION_VERSION
        try:
            for bad in (0.0, -1.0):
                prof = load_profile("bulk_v6")
                prof["mask_gate_depth_pct"] = bad
                with self.assertRaises(CalibrationError,
                                       msg=f"mask depth {bad} "
                                       f"must fail loud"):
                    bs._apply_profile(prof)
        finally:
            bs.set_calibration(previous)


def _vrow(tic, t0, n_events=1, tier="B", k3_pass=None,
          period=3.0):
    """A synthetic survivor row for the F-1 veto tests."""
    row = {"tic": str(tic), "t0_btjd": t0,
           "period_days": period, "n_events": n_events,
           "tier": tier, "status": "survivor", "flags": []}
    if k3_pass is not None:
        row["k3_pass"] = k3_pass
    return row


def _vcluster(n, t0=3920.0, tic0=30000, **kw):
    """n few-event rows sharing T0 within the tolerance."""
    return [_vrow(tic0 + i, t0 + 0.001 * i, **kw)
            for i in range(n)]


class TestT0ClusterVeto(unittest.TestCase):
    """F-1 (bulk_v6): merge-time T0-cluster veto behaviour."""

    def test_demotes_clustered_few_event_rows(self):
        rows = _vcluster(25) + _vcluster(5, t0=3950.0,
                                         tic0=40000)
        kept, summary = bs.apply_t0_cluster_veto(rows)
        self.assertEqual(len(kept), 5)
        self.assertEqual(summary["demoted"], 25)
        self.assertEqual(summary["n_clusters"], 1)
        self.assertEqual(summary["cluster_sizes"], [25])
        self.assertEqual(summary["demoted_pass1"], 25)
        self.assertEqual(summary["demoted_k3"], 0)

    def test_few_event_only(self):
        # 20 few-event + 5 multi-event rows at one epoch: the
        # multi-event rows neither count toward the bar nor
        # get demoted — 20 < 21, so nothing fires.
        rows = (_vcluster(20)
                + _vcluster(5, t0=3920.0, tic0=41000,
                            n_events=5, tier="A"))
        kept, summary = bs.apply_t0_cluster_veto(rows)
        self.assertEqual(len(kept), 25)
        self.assertEqual(summary["demoted"], 0)
        # 25 few-event + 5 multi-event at the same epoch: the
        # 25 fire, the 5 multi-event rows survive.
        rows = (_vcluster(25)
                + _vcluster(5, t0=3920.0, tic0=41000,
                            n_events=5, tier="A"))
        kept, summary = bs.apply_t0_cluster_veto(rows)
        self.assertEqual(len(kept), 5)
        self.assertEqual(summary["demoted"], 25)
        self.assertTrue(all(r["n_events"] == 5 for r in kept))

    def test_demoted_rows_stay_in_hits(self):
        # Demote-not-delete: demoted rows leave the kept
        # survivors but carry the demotion in the hits list.
        rows = _vcluster(25)
        hits = [dict(r) for r in rows]
        kept, summary = bs.apply_t0_cluster_veto(rows, hits)
        self.assertEqual(len(kept), 0)
        self.assertEqual(len(hits), 25)
        for h in hits:
            self.assertEqual(h["status"], "demoted")
            self.assertEqual(h["disposition"],
                             "DEMOTED_T0_CLUSTER")
            self.assertIn("T0_CLUSTER", h["flags"])

    def test_hits_consistent_k3_keying(self):
        # A star with a pass-1 row and a K=3 row: when the K=3
        # row is demoted, the demotion lands on the K=3 hit
        # record — NOT on the pass-1 hit (the (P, T0) veto's
        # tic-only keying would misattribute it).
        p1 = _vcluster(21)
        k3rows = _vcluster(5, tic0=42000, k3_pass=3)
        rows = p1 + k3rows
        hits = [dict(r) for r in rows]
        kept, summary = bs.apply_t0_cluster_veto(rows, hits)
        self.assertEqual(summary["demoted"], 26)
        self.assertEqual(summary["demoted_k3"], 5)
        k3_hits = [h for h in hits if h.get("k3_pass") == 3]
        self.assertEqual(len(k3_hits), 5)
        for h in k3_hits:
            self.assertEqual(h["disposition"],
                             "DEMOTED_T0_CLUSTER")
        p1_hits = [h for h in hits if h.get("k3_pass") is None]
        self.assertEqual(len(p1_hits), 21)
        for h in p1_hits:
            self.assertEqual(h["disposition"],
                             "DEMOTED_T0_CLUSTER")

    def test_row_level_demotion(self):
        # A star whose pass-1 row sits in a cluster but whose
        # K=3 row sits at a different epoch: the pass-1 row is
        # demoted, the K=3 row survives (row-level, not
        # TIC-level demotion).
        rows = _vcluster(21)
        k3row = _vrow("30000", 3950.0, k3_pass=2)
        rows.append(k3row)
        kept, summary = bs.apply_t0_cluster_veto(rows)
        self.assertEqual(summary["demoted"], 21)
        self.assertEqual(len(kept), 1)
        self.assertIs(kept[0], k3row)
        self.assertNotIn("T0_CLUSTER", k3row["flags"])

    def test_d_f1k3_counting(self):
        # 15 pass-1 + 10 K=3 rows in one cluster: the bar
        # counts pass-1 only (15 < 21) — nothing fires, and
        # the K=3 rows do not push it over.
        rows = _vcluster(15) + _vcluster(10, tic0=43000,
                                         k3_pass=3)
        kept, summary = bs.apply_t0_cluster_veto(rows)
        self.assertEqual(len(kept), 25)
        self.assertEqual(summary["demoted"], 0)
        # 21 pass-1 + 5 K=3: the cluster qualifies on pass-1
        # alone, and the K=3 rows inside it are demoted too.
        rows = _vcluster(21) + _vcluster(5, tic0=43000,
                                         k3_pass=2)
        kept, summary = bs.apply_t0_cluster_veto(rows)
        self.assertEqual(len(kept), 0)
        self.assertEqual(summary["demoted"], 26)
        self.assertEqual(summary["demoted_pass1"], 21)
        self.assertEqual(summary["demoted_k3"], 5)

    def test_rows_without_t0_or_events_kept(self):
        rows = _vcluster(21)
        no_t0 = _vrow("44000", None)
        no_events = _vrow("44001", 3920.0)
        del no_events["n_events"]
        rows += [no_t0, no_events]
        kept, summary = bs.apply_t0_cluster_veto(rows)
        self.assertEqual(summary["demoted"], 21)
        self.assertEqual(len(kept), 2)
        self.assertIn(no_t0, kept)
        self.assertIn(no_events, kept)

    def test_idempotent(self):
        rows = _vcluster(25)
        kept, first = bs.apply_t0_cluster_veto(rows)
        self.assertEqual(first["demoted"], 25)
        kept2, second = bs.apply_t0_cluster_veto(kept)
        self.assertEqual(second["demoted"], 0)
        self.assertEqual(kept2, kept)

    def test_explicit_parameters_live(self):
        # Non-default min_size is live, not ignored.
        rows = _vcluster(6)
        _, summary = bs.apply_t0_cluster_veto(rows, min_size=5)
        self.assertEqual(summary["demoted"], 6)
        rows = _vcluster(6)
        _, summary = bs.apply_t0_cluster_veto(rows, min_size=7)
        self.assertEqual(summary["demoted"], 0)

    def test_summary_carries_cluster_identity(self):
        rows = _vcluster(25) + _vcluster(22, t0=3950.0,
                                         tic0=45000)
        _, summary = bs.apply_t0_cluster_veto(rows)
        self.assertEqual(summary["n_clusters"], 2)
        self.assertEqual(summary["cluster_sizes"], [25, 22])
        clusters = summary["clusters"]
        self.assertEqual(clusters[0]["cluster_id"], 0)
        self.assertEqual(clusters[0]["size"], 25)
        self.assertEqual(clusters[0]["n_pass1_counted"], 25)
        self.assertEqual(clusters[0]["members"],
                         sorted(clusters[0]["members"]))
        self.assertEqual(len(clusters[0]["members"]), 25)
        self.assertEqual(clusters[1]["cluster_id"], 1)
        self.assertEqual(clusters[1]["size"], 22)


class TestT0ClusterVocabulary(unittest.TestCase):
    """DEMOTED_T0_CLUSTER in the search_health vocabulary AND
    the survivor schema — the two homes of the disposition
    vocabulary must stay in sync."""

    def test_disposition_in_search_health(self):
        import search_health as sh
        self.assertIn("DEMOTED_T0_CLUSTER",
                      sh.DISPOSITION_VALUES)
        self.assertEqual(sh.DEMOTED_T0_CLUSTER,
                         "DEMOTED_T0_CLUSTER")

    def test_disposition_in_schema_enum(self):
        import json
        repo = Path(__file__).resolve().parent.parent
        schema = json.loads(
            (repo / "schema" / "survivor-schema.json").read_text())
        enum = set(schema["properties"]["disposition"]["enum"])
        self.assertIn("DEMOTED_T0_CLUSTER", enum)
        import search_health as sh
        self.assertEqual(enum, set(sh.DISPOSITION_VALUES),
                         "schema disposition enum and "
                         "search_health.DISPOSITION_VALUES "
                         "must stay in sync")

    def test_queue_query_docs_mention_t0_cluster(self):
        repo = Path(__file__).resolve().parent.parent
        schema = json.loads(
            (repo / "schema" / "survivor-schema.json").read_text())
        desc = schema["properties"]["gate_reason"]["description"]
        self.assertIn("DEMOTED_T0_CLUSTER", desc)


class TestS97F1GoldenFixture(unittest.TestCase):
    """F-1 on the real S97 re-screened queue (golden fixture,
    tests/fixtures/golden/s97_f1_queue.jsonl). Pins F-1's
    behaviour on production data: the counts below were
    measured once with the implemented veto (2026-11-20) and
    are a regression guard — a change means F-1 moved on real
    data. The fixture is the v5-order run, so the pinned
    counts are not the v6 production counts (see the fixtures
    README)."""

    @classmethod
    def setUpClass(cls):
        repo = Path(__file__).resolve().parent.parent
        path = (repo / "tests" / "fixtures" / "golden"
                / "s97_f1_queue.jsonl")
        cls.rows = [json.loads(line)
                    for line in path.read_text().splitlines()
                    if line.strip()]

    def test_fixture_shape(self):
        self.assertEqual(len(self.rows), 749)
        n_k3 = sum(1 for r in self.rows
                   if r.get("k3_pass") is not None)
        self.assertEqual(n_k3, 373)
        n_few = sum(1 for r in self.rows
                    if r.get("n_events", 99) <= 2)
        self.assertEqual(n_few, 236)
        self.assertTrue(all(r.get("t0_btjd") is not None
                            for r in self.rows))

    def test_f1_demotes_25_on_s97(self):
        previous = bs.CALIBRATION_VERSION
        try:
            bs.set_calibration("bulk_v6")
            rows = copy.deepcopy(self.rows)
            kept, summary = bs.apply_t0_cluster_veto(rows)
            self.assertEqual(summary["demoted"], 25)
            self.assertEqual(summary["demoted_pass1"], 23)
            self.assertEqual(summary["demoted_k3"], 2)
            self.assertEqual(summary["n_clusters"], 1)
            self.assertEqual(summary["cluster_sizes"], [25])
            self.assertEqual(len(kept), 724)
            # The demoted rows are the T0-cluster members:
            # few-event, tier B, at the 3946.6 artifact epoch.
            demoted = [r for r in rows
                       if r.get("disposition")
                       == "DEMOTED_T0_CLUSTER"]
            self.assertEqual(len(demoted), 25)
            self.assertTrue(all(r["n_events"] <= 2
                                for r in demoted))
            self.assertTrue(all(r.get("tier") == "B"
                                for r in demoted))
            t0s = [r["t0_btjd"] for r in demoted]
            self.assertGreaterEqual(min(t0s), 3946.6)
            self.assertLessEqual(max(t0s), 3946.8)
            # No known planet demoted (TIC 349410350, the one
            # known-planet TIC in the fixture, is an 11-event
            # tier-A row — outside F-1's input by construction).
            self.assertEqual(
                {r["tic"] for r in demoted}
                & set(_rm.KNOWN_PLANET_TICS), set())
        finally:
            bs.set_calibration(previous)


class TestB1JoinOrder(unittest.TestCase):
    """B-1 (bulk_v6): the K=3 join moves to AFTER the (P, T0)
    veto. These tests replicate the two merge orders with the
    REAL veto functions on synthetic rows — the K=3 stage has
    no stub seam, so there is no e2e driver test (see the
    build record). The S97 reconstruction
    (s97_reconstruct.py, in the bulkv6 record dir) verifies
    the same orders on real data: 32 tier-B pass-1
    restorations, 293 K=3 rows escaping the veto."""

    def setUp(self):
        self._previous = bs.CALIBRATION_VERSION
        bs.set_calibration("bulk_v6")

    def tearDown(self):
        bs.set_calibration(self._previous)

    def _merge_orders(self, p1, k3):
        """Run the (P, T0) veto + K=3 join + F-1 in the v5
        order (join first) and the v6 order (join after the
        veto). Returns (v5_kept, v6_kept, v5_veto, v6_veto,
        v5_t0, v6_t0). Rows are deep-copied per order (the
        vetoes mutate)."""
        surv5 = copy.deepcopy(p1) + copy.deepcopy(k3)
        kept5, vsum5 = bs.apply_epoch_cluster_veto(surv5)
        kept5, t0sum5 = bs.apply_t0_cluster_veto(kept5)
        kept6, vsum6 = bs.apply_epoch_cluster_veto(
            copy.deepcopy(p1))
        kept6 = kept6 + copy.deepcopy(k3)
        kept6, t0sum6 = bs.apply_t0_cluster_veto(kept6)
        return kept5, kept6, vsum5, vsum6, t0sum5, t0sum6

    def test_k3_inflation_demotes_pass1_in_v5_order_only(self):
        # 19 pass-1 tier-B rows at one (P, T0) — below the
        # >20 bar alone — plus 5 K=3 rows at the same
        # (P, T0). The v5 order demotes all 24 (the K=3 rows
        # inflate the cluster over the bar); the v6 order
        # keeps all 24 (the pass-1-only cluster never
        # qualifies, and F-1's pass-1-only count stays 19).
        # This is the Stage 5 B-1 mechanism in miniature.
        p1 = _vcluster(19, tic0=50000)
        k3 = _vcluster(5, tic0=51000, k3_pass=2)
        kept5, kept6, vsum5, vsum6, t0sum5, t0sum6 = (
            self._merge_orders(p1, k3))
        self.assertEqual(vsum5["demoted_tier_b"], 24)
        self.assertEqual(len(kept5), 0)
        self.assertEqual(vsum6["demoted_tier_b"], 0)
        self.assertEqual(vsum6["n_clusters"], 0)
        self.assertEqual(t0sum6["demoted"], 0)
        self.assertEqual(len(kept6), 24)
        p1_tics = {r["tic"] for r in p1}
        self.assertEqual(p1_tics,
                         {r["tic"] for r in kept6
                          if r.get("k3_pass") is None})

    def test_k3_rows_escape_epoch_veto_in_v6_order(self):
        # 25 pass-1 tier-B rows at one (P, T0) — the cluster
        # qualifies on pass-1 alone — plus 5 K=3 rows at the
        # same (P, T0). The v5 order demotes all 30; the v6
        # order demotes the 25 pass-1 rows and the 5 K=3 rows
        # survive (they never see the (P, T0) veto, and F-1
        # counts pass-1 rows only — 0 here — so it cannot
        # fire on a K=3-only input).
        p1 = _vcluster(25, tic0=52000)
        k3 = _vcluster(5, tic0=53000, k3_pass=3)
        kept5, kept6, vsum5, vsum6, t0sum5, t0sum6 = (
            self._merge_orders(p1, k3))
        self.assertEqual(vsum5["demoted_tier_b"], 30)
        self.assertEqual(len(kept5), 0)
        self.assertEqual(vsum6["demoted_tier_b"], 25)
        self.assertEqual(t0sum6["demoted"], 0)
        self.assertEqual(len(kept6), 5)
        self.assertTrue(all(r.get("k3_pass") == 3
                            for r in kept6))

    def test_unclustered_tier_a_kept_in_both_orders(self):
        # Tier-A pass-1 rows at a (P, T0) with no cluster are
        # kept under both orders — the reorder changes only
        # what the veto SEES, not tier-A treatment (under
        # bulk_v6 a tier-A row IN a qualifying cluster is
        # demoted in both orders; these rows are not in one).
        p1 = (_vcluster(19, tic0=54000)
              + _vcluster(3, t0=3950.0, tic0=55000, period=5.0,
                          n_events=5, tier="A"))
        k3 = _vcluster(5, tic0=56000, k3_pass=2)
        kept5, kept6, vsum5, vsum6, _t0sum5, _t0sum6 = (
            self._merge_orders(p1, k3))
        self.assertEqual(vsum5["demoted_tier_b"], 24)
        self.assertEqual(vsum5["demoted_tier_a"], 0)
        self.assertEqual(vsum6["demoted_tier_b"], 0)
        tier_a_kept5 = [r for r in kept5 if r.get("tier") == "A"]
        tier_a_kept6 = [r for r in kept6 if r.get("tier") == "A"]
        self.assertEqual(len(tier_a_kept5), 3)
        self.assertEqual(len(tier_a_kept6), 3)


class TestF2FlagCarry(unittest.TestCase):
    """F-2 (bulk_v6): EB-flag carry-forward helper behaviour
    (bulk/oracle_run.py)."""

    def test_harmonic_matching_all_ratios(self):
        # Each of the 7 ratios matches within 1% and misses
        # at 2% off. The flagged signal is P 3.0 d.
        flagged = orc.flagged_periods(
            {"period_days": 3.0, "flags": ["DURATION_EB"]})
        self.assertEqual(flagged, [(3.0, ["DURATION_EB"])])
        for h in (1.0 / 3.0, 0.5, 2.0 / 3.0, 1.0, 1.5, 2.0, 3.0):
            self.assertEqual(
                orc.carried_eb_flags(3.0 * h, flagged),
                ["DURATION_EB"], f"ratio {h} must match")
            self.assertEqual(
                orc.carried_eb_flags(3.0 * h * 0.995, flagged),
                ["DURATION_EB"], f"ratio {h} at -0.5% must match")
            self.assertEqual(
                orc.carried_eb_flags(3.0 * h * 1.02, flagged),
                [], f"ratio {h} at +2% must not match")

    def test_eb_family_carried(self):
        flags = ["ODD_EVEN_EB", "SECONDARY_EB", "DURATION_EB",
                 "DEPTH_EB", "HARMONIC_P2_SUSPECT",
                 "HARMONIC_P3_SUSPECT"]
        flagged = orc.flagged_periods(
            {"period_days": 2.0, "flags": flags})
        self.assertEqual(flagged, [(2.0, flags)])

    def test_non_eb_flags_not_carried(self):
        # DEPTH_TOO_SHALLOW is demoting but NOT carried (a
        # property of the new measurement); TWO_EVENT_WEAK is
        # re-evaluated per pass; veto flags are not EB flags.
        for flag in ("DEPTH_TOO_SHALLOW", "TWO_EVENT_WEAK",
                     "SECTOR_EPOCH_CLUSTER", "T0_CLUSTER"):
            flagged = orc.flagged_periods(
                {"period_days": 2.0, "flags": [flag]})
            self.assertEqual(flagged, [],
                             f"{flag} must not be carried")
        # Mixed: only the EB flag survives.
        flagged = orc.flagged_periods(
            {"period_days": 2.0,
             "flags": ["DEPTH_TOO_SHALLOW", "SECONDARY_EB"]})
        self.assertEqual(flagged, [(2.0, ["SECONDARY_EB"])])

    def test_no_period_no_carry(self):
        flagged = orc.flagged_periods(
            {"period_days": None, "flags": ["DURATION_EB"]})
        self.assertEqual(flagged, [])
        self.assertEqual(
            orc.carried_eb_flags(
                None, [(3.0, ["DURATION_EB"])]), [])
        self.assertEqual(orc.carried_eb_flags(3.0, []), [])

    def test_carried_flags_union_sorted(self):
        flagged = [(3.0, ["DURATION_EB"]),
                   (1.5, ["SECONDARY_EB", "HARMONIC_P2_SUSPECT"])]
        # 3.0 d matches the first at 1.0 and the second at 2.0.
        self.assertEqual(
            orc.carried_eb_flags(3.0, flagged),
            ["DURATION_EB", "HARMONIC_P2_SUSPECT",
             "SECONDARY_EB"])
        # 5.0 d matches neither.
        self.assertEqual(orc.carried_eb_flags(5.0, flagged), [])

    def test_apply_eb_carry(self):
        rec = {"period_days": 3.0, "status": "survivor",
               "flags": ["SOME_FLAG"]}
        orc.apply_eb_carry(rec, ["DURATION_EB"])
        self.assertEqual(rec["status"], "demoted")
        self.assertEqual(rec["flags"],
                         ["SOME_FLAG", "DURATION_EB"])
        self.assertEqual(rec["flags_carried_from"], "pass1")
        # Idempotent on the flags list (no duplicates).
        orc.apply_eb_carry(rec, ["DURATION_EB"])
        self.assertEqual(rec["flags"],
                         ["SOME_FLAG", "DURATION_EB"])


class TestF2Regression38516539(unittest.TestCase):
    """F-2 on the frozen evidence case (TIC 38516539,
    fixture tests/fixtures/golden/f2_38516539.json): the
    stitched pass-2 row must carry the EB flag after the fix.
    Built from the extracted record, not a re-run."""

    @classmethod
    def setUpClass(cls):
        repo = Path(__file__).resolve().parent.parent
        path = (repo / "tests" / "fixtures" / "golden"
                / "f2_38516539.json")
        cls.fx = json.loads(path.read_text())

    def test_fixture_shape(self):
        p1 = self.fx["stitched_pass1"]
        p2 = self.fx["stitched_pass2"]
        self.assertEqual(p1["status"], "demoted")
        self.assertEqual(p1["flags"], ["DURATION_EB"])
        self.assertAlmostEqual(p1["period_days"], 0.68686, 4)
        self.assertEqual(p2["status"], "survivor")
        self.assertEqual(p2["tier"], "A")
        self.assertEqual(p2["flags"], [])
        self.assertAlmostEqual(p2["period_days"], 0.68994, 4)
        per_sector = self.fx["per_sector_pass1"]
        self.assertEqual(set(per_sector), {"95", "96", "97"})
        self.assertEqual(per_sector["96"]["flags"],
                         ["SECONDARY_EB", "HARMONIC_P2_SUSPECT"])

    def test_stitched_source_carries_duration_eb(self):
        flagged = orc.flagged_periods(
            self.fx["stitched_pass1"])
        self.assertEqual(len(flagged), 1)
        p2 = copy.deepcopy(self.fx["stitched_pass2"])
        carried = orc.carried_eb_flags(
            p2["period_days"], flagged)
        self.assertEqual(carried, ["DURATION_EB"])
        orc.apply_eb_carry(p2, carried)
        self.assertEqual(p2["status"], "demoted")
        self.assertEqual(p2["flags"], ["DURATION_EB"])
        self.assertEqual(p2["flags_carried_from"], "pass1")

    def test_per_sector_source_carries_all_three(self):
        # The p43 stitched leg's source: the per-sector
        # pass-1 records. All three periods sit within 1% of
        # the pass-2 period at ratio 1.0, so the union of
        # their EB flags carries.
        flagged = orc.flagged_periods(
            list(self.fx["per_sector_pass1"].values()))
        self.assertEqual(len(flagged), 3)
        p2 = copy.deepcopy(self.fx["stitched_pass2"])
        carried = orc.carried_eb_flags(
            p2["period_days"], flagged)
        self.assertEqual(
            carried,
            ["DURATION_EB", "HARMONIC_P2_SUSPECT",
             "SECONDARY_EB"])
        orc.apply_eb_carry(p2, carried)
        self.assertEqual(p2["status"], "demoted")
        self.assertEqual(p2["flags_carried_from"], "pass1")


class TestMaskGate(unittest.TestCase):
    """The bulk_v6 mask gate (design section 5.2, PIPE50-9a +
    GATEFIX-20261120): the mask applies only when the pass-1
    record is contaminant-like (EB flag OR depth > 1.0% OR
    period >= 13.7 d). Gate OFF = mask unconditional (the
    frozen-profile behaviour). Planet-like records here carry
    a short period so each test exercises its intended clause
    (a missing period masks — GATEFIX G6)."""

    def setUp(self):
        self.previous = bs.CALIBRATION_VERSION

    def tearDown(self):
        bs.set_calibration(self.previous)

    def test_gate_on_eb_flag_allows(self):
        bs.set_calibration("bulk_v6")
        for flag in ("DURATION_EB", "SECONDARY_EB",
                     "HARMONIC_P2_SUSPECT", "HARMONIC_P3_SUSPECT",
                     "ODD_EVEN_EB", "DEPTH_EB"):
            self.assertTrue(
                k2.mask_gate_allows(
                    {"flags": [flag], "depth_percent": 0.05,
                     "period_days": 2.0}),
                f"{flag} must allow the mask")

    def test_gate_on_deep_allows(self):
        bs.set_calibration("bulk_v6")
        self.assertTrue(k2.mask_gate_allows(
            {"flags": [], "depth_percent": 1.5,
             "period_days": 2.0}))
        # Exactly 1.0% does NOT allow (strictly greater).
        self.assertFalse(k2.mask_gate_allows(
            {"flags": [], "depth_percent": 1.0,
             "period_days": 2.0}))

    def test_gate_on_planet_like_blocks(self):
        bs.set_calibration("bulk_v6")
        # Shallow, unflagged, short-period: the planet case —
        # no mask.
        self.assertFalse(k2.mask_gate_allows(
            {"flags": [], "depth_percent": 0.05,
             "period_days": 2.0}))
        # Non-EB flags do not allow.
        self.assertFalse(k2.mask_gate_allows(
            {"flags": ["DEPTH_TOO_SHALLOW", "TWO_EVENT_WEAK"],
             "depth_percent": 0.05, "period_days": 2.0}))
        # Missing depth + no flags + short period: nothing
        # contaminant-like. (The missing-depth path fails the
        # other way — flagged, not changed; GATEFIX G6.)
        self.assertFalse(k2.mask_gate_allows(
            {"flags": [], "depth_percent": None,
             "period_days": 2.0}))

    def test_gate_on_none_record_fails_open(self):
        bs.set_calibration("bulk_v6")
        # No record to gate on: preserve the old behaviour
        # (mask), rather than inventing a decision.
        self.assertTrue(k2.mask_gate_allows(None))

    def test_gate_off_unconditional(self):
        bs.set_calibration("bulk_v5")
        # Frozen profiles predate the gate: even a
        # planet-like record is masked (old behaviour).
        self.assertTrue(k2.mask_gate_allows(
            {"flags": [], "depth_percent": 0.05}))
        self.assertTrue(k2.mask_gate_allows(None))

    def test_gated_off_mask_stats_shape(self):
        stats = k2.gated_off_mask_stats()
        self.assertTrue(stats["gated_off"])
        self.assertFalse(stats["mask_applied"])
        # Not a duty-cycle stop: stopped is False.
        self.assertFalse(stats["stopped"])
        self.assertIsNone(stats["stop_reason"])
        # Fresh dict per call (the caller stores it).
        self.assertIsNot(stats, k2.gated_off_mask_stats())


class TestMaskGatePeriod(unittest.TestCase):
    """The GATEFIX period clause (GATEFIX-20261120, G1): the
    mask applies when the recorded period is at least 13.7 d
    — the T/2 boundary for a ~27.4 d sector, where a
    single-event fit is forced to land and periodicity cannot
    be tested. Tests the derivation (boundary values, missing
    period), not the four lost trials."""

    def setUp(self):
        self.previous = bs.CALIBRATION_VERSION

    def tearDown(self):
        bs.set_calibration(self.previous)

    def _record(self, period, depth=0.05, flags=()):
        return {"flags": list(flags), "depth_percent": depth,
                "period_days": period}

    def test_period_boundary(self):
        bs.set_calibration("bulk_v6")
        # Just below the boundary: planet-like, no mask.
        self.assertFalse(k2.mask_gate_allows(
            self._record(13.69)))
        # At the boundary (inclusive): mask.
        self.assertTrue(k2.mask_gate_allows(
            self._record(13.7)))
        # Just above: mask.
        self.assertTrue(k2.mask_gate_allows(
            self._record(13.71)))
        # The grid edge: mask.
        self.assertTrue(k2.mask_gate_allows(
            self._record(20.0)))

    def test_missing_period_masks(self):
        bs.set_calibration("bulk_v6")
        # No period key: fail toward the parity-proven
        # behaviour (mask), like a None record.
        self.assertTrue(k2.mask_gate_allows(
            {"flags": [], "depth_percent": 0.05}))
        # Explicit None period: same.
        self.assertTrue(k2.mask_gate_allows(
            {"flags": [], "depth_percent": 0.05,
             "period_days": None}))

    def test_eb_and_depth_still_fire_short_period(self):
        bs.set_calibration("bulk_v6")
        # The clauses are OR-ed: an EB flag or a deep record
        # allows the mask even at a short period.
        self.assertTrue(k2.mask_gate_allows(
            self._record(2.0, flags=("DURATION_EB",))))
        self.assertTrue(k2.mask_gate_allows(
            self._record(2.0, depth=1.5)))

    def test_short_shallow_blocks(self):
        bs.set_calibration("bulk_v6")
        # Planet protection survives the clause: a shallow,
        # unflagged short-period record still blocks the mask.
        self.assertFalse(k2.mask_gate_allows(
            self._record(2.0)))
        self.assertFalse(k2.mask_gate_allows(
            self._record(5.75)))


def _tier_a_subset(period=1.7, mes=12.0, sde=9.0, nev=5, nst=3,
                   status="survivor"):
    return {"period_days": period, "mes_pink": mes, "sde": sde,
            "n_events": nev, "n_strong_events": nst,
            "status": status, "tier": "A", "t0_btjd": 2001.0}


def _trial_rec(pass1=None, pass2=None, pass3=None, od1=None,
               od2=None, od3=None):
    return {"tic": "100000003", "sector": 95,
            "trial_id": "d1p1", "pass1": pass1, "pass2": pass2,
            "pass3": pass3, "epoch_delta_over_d_pass1": od1,
            "epoch_delta_over_d": od2,
            "epoch_delta_over_d_pass3": od3,
            "alias_veto": {"vetoed": False},
            "alias_veto_pass3": {"vetoed": False}}


def _manifest_trial(period=1.7):
    return {"tic": "100000003", "sector": 95, "trial_id": "d1p1",
            "period_d": period, "depth_idx": 1, "period_idx": 1,
            "epoch_btjd": 2001.0,
            "duration_d": (2.0 * period ** (1.0 / 3.0)) / 24.0,
            "depth_frac": 0.0005, "is_demo": False}


class TestAnystagePromotion(unittest.TestCase):
    """Any-stage scoring promoted to the shared home
    (bulk/p4110_score.py, PIPE50-9b) and reported alongside
    final-only. p413_score re-exports the same functions."""

    def setUp(self):
        self.previous = bs.CALIBRATION_VERSION
        bs.set_calibration("bulk_v5")
        self.bars = GateBars("bulk_v5", 9.0)

    def tearDown(self):
        bs.set_calibration(self.previous)

    def test_functions_live_in_p4110_score(self):
        for name in ("pass1_recovers",
                     "trial_recovers_anystage",
                     "null_survivor_anystage",
                     "null_survivor_finalonly"):
            self.assertTrue(hasattr(s4110, name), name)
            # p413_score re-exports the SAME function object.
            self.assertIs(getattr(s413, name),
                          getattr(s4110, name), name)

    def test_pass1_only_counts_anystage_not_final(self):
        # The K=2 mask case: pass 1 finds it, pass 2/3 find
        # nothing. Any-stage counts it; final-only does not.
        rec = _trial_rec(
            pass1=_tier_a_subset(), od1=0.5,
            pass2=_tier_a_subset(period=3.5), od2=0.1)
        tr = _manifest_trial()
        self.assertTrue(s4110.trial_recovers_anystage(
            rec, tr, self.bars, 1.0))
        self.assertFalse(s4110.trial_recovers(
            rec, tr, self.bars, 1.0))

    def test_no_pass1_degenerates_to_final_only(self):
        # Old runs carry no pass-1 screen: any-stage ==
        # final-only, so old curves re-derive unchanged.
        rec = _trial_rec(
            pass1=None, od1=None,
            pass2=_tier_a_subset(), od2=0.2)
        tr = _manifest_trial()
        self.assertTrue(s4110.trial_recovers_anystage(
            rec, tr, self.bars, 1.0))
        self.assertTrue(s4110.trial_recovers(
            rec, tr, self.bars, 1.0))
        rec2 = _trial_rec(
            pass1=None, od1=None,
            pass2=_tier_a_subset(period=3.5), od2=0.1)
        self.assertFalse(s4110.trial_recovers_anystage(
            rec2, tr, self.bars, 1.0))

    def test_null_rules_both_reported(self):
        # Pass-1-only tier-A null: anystage counts it,
        # final-only does not.
        null_rec = {"tic": "111", "pass1": _tier_a_subset(),
                    "pass2": None, "pass3": None}
        self.assertTrue(s4110.null_survivor_anystage(
            null_rec, self.bars))
        self.assertFalse(s4110.null_survivor_finalonly(
            null_rec, self.bars))
        self.assertFalse(s4110.null_survivor_at_gate(
            null_rec, self.bars))

    def test_score_null_reports_both_rules(self):
        # Two null hosts: one pass-1-only tier-A survivor,
        # one clean. Final-only k=0; anystage k=1.
        man = {"trials": [{"tic": "111", "n_sectors": 3},
                          {"tic": "222", "n_sectors": 3}]}
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp) / "null-p43"
            d.mkdir()
            (d / "111_p43.json").write_text(json.dumps(
                {"tic": "111", "complete": True,
                 "pass1": _tier_a_subset(), "pass2": None,
                 "pass3": None}))
            (d / "222_p43.json").write_text(json.dumps(
                {"tic": "222", "complete": True,
                 "pass1": None, "pass2": None, "pass3": None}))
            out = s4110.score_null(man, tmp, self.bars)
        st = out["stitched"]
        self.assertEqual(st["n_null_hosts"], 2)
        self.assertEqual(st["n_false_survivors"], 0)
        self.assertEqual(st["rate_per_1000"], 0.0)
        self.assertEqual(st["n_false_survivors_anystage"], 1)
        self.assertEqual(st["rate_per_1000_anystage"], 500.0)
        stratum = st["by_stratum"]["3_sector"]
        self.assertEqual(stratum["k"], 0)
        self.assertEqual(stratum["k_anystage"], 1)


class TestM4GateOffCrashes(unittest.TestCase):
    """M4-p43 (2026-11-20): the mask gate's gated-off branch
    crashed two campaign paths -- k3_run's veto["vetoed"]
    subscript on a None veto (138/272 single-leg trials) and
    p43_run's _contaminant_dict on a gated-off sector
    (187/272 stitched trials). Both crashes fire only when
    the gated-off trial/sector is otherwise fine (a
    recovering carry-forward / an eligible sector), which is
    why the k3 parity set (whose gated-off trials were all
    non-recoveries, so `m6 and ...` short-circuited) never
    hit them. Synthetic-FITS end-to-end tests: a planet-like
    recorded row (shallow, unflagged, P < 13.7 d) gates the
    mask off; the trial must complete with no error."""

    def setUp(self):
        self.previous = bs.CALIBRATION_VERSION
        bs.set_calibration("bulk_v6")

    def tearDown(self):
        bs.set_calibration(self.previous)

    def _trial(self, sector=95):
        return {"trial_id": "planet01", "tic": "424242",
                "sector": sector, "group": "recovered_412",
                "period_d": 5.0, "epoch_btjd": 1505.0,
                "epoch_offset_d": 5.0, "duration_d": 0.1422,
                "depth_frac": 0.008,
                "recorded": {"status": "survivor", "tier": "A",
                             "period_days": 5.0,
                             "depth_percent": 0.8, "sde": 15.0,
                             "mes_pink": 12.0, "flags": [],
                             "n_events_found": 5,
                             "n_strong_events": 5,
                             "max_event_snr": 8.0}}

    def test_k3_gated_off_recovery_does_not_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / "hosts").mkdir()
            (tmp / "w").mkdir()
            fits = make_qlp_fits(tmp / "424242.fits",
                                 period_d=None)
            job = {"tic": "424242", "sector": 95,
                   "arm": "prototype", "spans": None,
                   "path": str(fits), "trials": [self._trial()],
                   "out_dir": str(tmp), "workdir": str(tmp / "w"),
                   "manifest_sha": "test",
                   "calibration": "bulk_v6", "keep_fits": False}
            res = k3run.run_host_campaign_k3(job)
            self.assertEqual(res["status"], "done")
            rec = json.loads(
                (tmp / "hosts" / "424242_s0095.json").read_text())
            tr = rec["trials"][0]
            self.assertNotIn("error", tr)
            # The gate denied the mask: pass 2 carries pass 1.
            self.assertEqual(tr["pass2"].get("carried_from"),
                             "pass1")
            # No mask, no veto: the carried recovery stands.
            self.assertTrue(tr["k2_recovered"])
            self.assertTrue(tr["final_recovered"])

    def test_p43_gated_off_sector_does_not_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / "hosts-p43").mkdir()
            (tmp / "w").mkdir()
            paths = {}
            for sec, t0 in ((95, 1500.0), (96, 1527.0),
                            (97, 1554.0)):
                # String keys: the driver looks paths up by the
                # JSON-manifest key (str(sector)).
                paths[str(sec)] = str(make_qlp_fits(
                    tmp / f"424242_s{sec:04d}.fits",
                    period_d=None, t_start=t0))
            job = {"tic": "424242", "sectors": [95, 96, 97],
                   "paths": paths, "trials": [self._trial()],
                   "out_dir": str(tmp), "workdir": str(tmp / "w"),
                   "manifest_sha": "test",
                   "calibration": "bulk_v6", "keep_fits": False,
                   "seed_mode": "frozen", "agreement_only": False}
            res = p43run.run_host_campaign_p43(job)
            self.assertEqual(res["status"], "done")
            rec = json.loads(
                (tmp / "hosts-p43" / "424242_p43.json").read_text())
            tr = rec["trials"][0]
            self.assertNotIn("error", tr)
            # At least one sector took the gated-off path
            # (otherwise the test never exercises the fix).
            gated = [s for s in tr["sectors"].values()
                     if s.get("mask_gated_off")]
            self.assertGreaterEqual(len(gated), 1)


class TestN6StitchedNullFinalSurvivor(unittest.TestCase):
    """N6 (M2NULL-20261121, RATIFIED): p43_run's stitched null
    leg never wrote `final_survivor` — the M2 scorer's
    flag-based D2st host count read 0.00 (the gate verdict was
    unaffected: it comes from kept rows). The key was never
    written by the driver on any branch: BP-1's extract
    synthesised it as bool(final_rows)
    (nulldiag_extract.py), and BP1_RECORD.md section 5
    already documented the gap at BP-1 time. The driver now
    writes it with k3_run's semantics: pass-2 OR pass-3
    survivor. Synthetic-FITS end-to-end: one pure-noise host
    and one with a coherent signal in every sector; every
    record carries the key, the flag matches the OR (and
    bool(final_rows)) on every record, and the flag-based
    host count matches the OR count — the scorer's
    cross-check (m2_score.py analyse_arm). Fails on unfixed
    code: the key is absent, so the presence assertion fails
    outright."""

    def setUp(self):
        self.previous = bs.CALIBRATION_VERSION
        bs.set_calibration("bulk_v6")

    def tearDown(self):
        bs.set_calibration(self.previous)

    def _null_job(self, tmp, tic, period_d):
        (tmp / "null-p43").mkdir(exist_ok=True)
        (tmp / "w").mkdir(exist_ok=True)
        paths = {}
        for sec, t0 in ((95, 1500.0), (96, 1527.0),
                        (97, 1554.0)):
            # String keys: the driver looks paths up by the
            # JSON-manifest key (str(sector)). One absolute
            # epoch (t0=1502.0) so the signal is coherent
            # across the stitch.
            paths[str(sec)] = str(make_qlp_fits(
                tmp / f"{tic}_s{sec:04d}.fits",
                period_d=period_d, depth_frac=0.008,
                t0=1502.0, t_start=t0))
        return {"tic": tic, "sectors": [95, 96, 97],
                "paths": paths, "out_dir": str(tmp),
                "workdir": str(tmp / "w"), "manifest_sha": "test",
                "calibration": "bulk_v6", "keep_fits": False}

    def test_stitched_null_records_carry_final_survivor(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            recs = []
            for tic, period_d in (("424242", None),
                                  ("434343", 5.0)):
                res = p43run.run_host_null_p43(
                    self._null_job(tmp, tic, period_d))
                self.assertEqual(res["status"], "done")
                rec = json.loads(
                    (tmp / "null-p43"
                     / f"{tic}_p43.json").read_text())
                self.assertNotIn("error", rec)
                recs.append(rec)
            for rec in recs:
                # The key itself (absent pre-fix).
                self.assertIn("final_survivor", rec)
                # k3_run semantics: pass-2 OR pass-3.
                self.assertEqual(
                    rec["final_survivor"],
                    bool(rec["pass2_survivor"]
                         or rec["pass3_survivor"]))
                # Identical to the BP-1 extract's synthesis
                # rule (bool(final_rows)).
                self.assertEqual(rec["final_survivor"],
                                 bool(rec["final_rows"]))
            # The scorer's cross-check: flag-based host count
            # == OR count (m2_score.py analyse_arm).
            flag_hosts = sum(1 for r in recs
                             if r["final_survivor"] is True)
            or_hosts = sum(1 for r in recs
                           if r["pass2_survivor"] is True
                           or r["pass3_survivor"] is True)
            self.assertEqual(flag_hosts, or_hosts)
            # The signal host must exercise the True branch
            # (otherwise the OR is only ever tested False).
            self.assertTrue(recs[1]["final_survivor"])


if __name__ == "__main__":
    unittest.main()
