"""Behaviour tests for the bulk_v4 tier-B gates (Phase 3, P3-15).

The adopted gates (parent decision 2026-11-16, Amendment A
approved): EPOCH-CLUSTER (SECTOR_EPOCH_CLUSTER veto, applied at
merge) + TWO-COMBINED (2-event tier-B rows need both events
strong AND mes_pink >= 9.0). PHASE-DEPTH is HELD and
DEMOTE-SYS/DEMOTE-ALL REJECTED — the negatives below prove they
are not active under bulk_v4. Nothing is deleted: a
veto-demoted row keeps disposition DEMOTED_SECTOR_EPOCH_CLUSTER
and a TWO-COMBINED failure keeps gate_reason FAILED_TWO_COMBINED
— both stay in screen_hits.jsonl, queryable as the
manual-review ("unsure") queue.

Offline, no downloads. The _screen_one tests use synthetic QLP
FITS. The TWO-COMBINED failure region (tier-B + mes < 9 or
n_strong < 2) is not reachable with white-noise synthetics —
mes tracks max_event_snr too closely, and an n_strong failure
needs an odd/even ratio the screen's own ODD_EVEN_EB veto would
already demote — so those tests patch bulk_screen._rescore to
steer the rescore measurements while the BLS detection stays
real. The gate logic itself is unit-tested in
test_replay_matrix.py; these tests prove the wiring.
"""
import copy
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import bulk_screen as bs  # noqa: E402
import provenance as prov  # noqa: E402
from search_health import DEMOTED_SECTOR_EPOCH_CLUSTER  # noqa: E402
from synth_fits import make_qlp_fits, screen_job  # noqa: E402
from validation import validate_survivor  # noqa: E402

FIXED_PROV = prov.provenance_header(
    "test-run-1", {"bulk": "v1"}, sha="abc1234",
    timestamp_utc="2026-11-14T06:00:00+00:00")


def _row(tic, tier="B", period_days=13.2, t0_btjd=3920.0, **kw):
    """A survivor-shaped record for the veto tests."""
    r = {"tic": tic, "tier": tier, "period_days": period_days,
         "t0_btjd": t0_btjd, "status": "survivor", "flags": []}
    r.update(kw)
    return r


def _cluster(n, tier="B", period=13.2, t0=3920.0, tic0=1000):
    # n rows sharing (P, T0) within the P3-13 tolerances.
    return [_row(str(tic0 + i), tier=tier,
                 period_days=period + 0.001 * i,
                 t0_btjd=t0 + 0.001 * i) for i in range(n)]


def _screen_fixture(period_d, depth_frac, duration_d, seed=42,
                    profile="bulk_v4", rescore_override=None):
    """Screen one synthetic FITS under `profile`; optionally
    steer the rescore measurements (see module docstring).
    Returns the raw _screen_one record."""
    previous = bs.CALIBRATION_VERSION
    try:
        bs.set_calibration(profile)
        with tempfile.TemporaryDirectory() as td:
            p = make_qlp_fits(Path(td) / "x.fits",
                              period_d=period_d, depth_frac=depth_frac,
                              duration_d=duration_d, noise_pct=0.003,
                              seed=seed)
            if rescore_override is None:
                return bs._screen_one(screen_job(p))
            real_rescore = bs._rescore

            def _patched(*args, **kwargs):
                rs = real_rescore(*args, **kwargs)
                if rs is not None:
                    rs.update(rescore_override)
                return rs

            with mock.patch.object(bs, "_rescore",
                                   side_effect=_patched):
                return bs._screen_one(screen_job(p))
    finally:
        bs.set_calibration(previous)


class TestEpochClusterVeto(unittest.TestCase):
    def test_veto_demotes_clustered_tier_b(self):
        survivors = _cluster(25)
        hits = copy.deepcopy(survivors)
        kept, summary = bs.apply_epoch_cluster_veto(survivors, hits)
        self.assertEqual(kept, [])
        self.assertEqual(summary["demoted_tier_b"], 25)
        self.assertEqual(summary["flagged_tier_a"], 0)
        self.assertEqual(summary["n_clusters"], 1)
        self.assertEqual(summary["cluster_sizes"], [25])
        for h in hits:
            self.assertEqual(h["status"], "demoted")
            self.assertEqual(h["disposition"],
                             DEMOTED_SECTOR_EPOCH_CLUSTER)
            self.assertIn(bs.SECTOR_EPOCH_CLUSTER_FLAG, h["flags"])
        # The dropped survivor copies are untouched — the hit
        # carries the demotion.
        self.assertEqual(survivors[0]["status"], "survivor")
        self.assertNotIn("disposition", survivors[0])

    def test_veto_flags_tier_a_never_demotes(self):
        survivors = _cluster(21, tier="A")
        hits = copy.deepcopy(survivors)
        kept, summary = bs.apply_epoch_cluster_veto(survivors, hits)
        self.assertEqual(len(kept), 21)
        self.assertEqual(summary["demoted_tier_b"], 0)
        self.assertEqual(summary["flagged_tier_a"], 21)
        for r in kept:
            self.assertEqual(r["status"], "survivor")
            self.assertNotIn("disposition", r)
            self.assertIn(bs.SECTOR_EPOCH_CLUSTER_FLAG, r["flags"])
        for h in hits:
            self.assertEqual(h["status"], "survivor")
            self.assertIn(bs.SECTOR_EPOCH_CLUSTER_FLAG, h["flags"])

    def test_veto_keeps_unclustered(self):
        survivors = [_row(str(2000 + i), period_days=1.0 + i,
                          t0_btjd=3908.0 + i) for i in range(25)]
        kept, summary = bs.apply_epoch_cluster_veto(
            survivors, copy.deepcopy(survivors))
        self.assertEqual(len(kept), 25)
        self.assertEqual(summary["demoted_tier_b"], 0)
        self.assertEqual(summary["flagged_tier_a"], 0)
        self.assertEqual(summary["n_clusters"], 0)

    def test_veto_20_vs_21_boundary(self):
        # The rule is clusters of >20 stars, not >=20.
        survivors = _cluster(20)
        kept, summary = bs.apply_epoch_cluster_veto(
            survivors, copy.deepcopy(survivors))
        self.assertEqual(len(kept), 20)
        self.assertEqual(summary["demoted_tier_b"], 0)
        survivors = _cluster(21)
        kept, summary = bs.apply_epoch_cluster_veto(
            survivors, copy.deepcopy(survivors))
        self.assertEqual(kept, [])
        self.assertEqual(summary["demoted_tier_b"], 21)

    def test_veto_idempotent(self):
        survivors = _cluster(25) + [_row("9000", period_days=2.5,
                                         t0_btjd=3900.0)]
        hits = copy.deepcopy(survivors)
        kept, _ = bs.apply_epoch_cluster_veto(survivors, hits)
        kept2, summary2 = bs.apply_epoch_cluster_veto(kept, hits)
        self.assertEqual(len(kept2), 1)
        self.assertEqual(summary2["demoted_tier_b"], 0)
        self.assertEqual(summary2["flagged_tier_a"], 0)
        for h in hits:
            self.assertEqual(
                h["flags"].count(bs.SECTOR_EPOCH_CLUSTER_FLAG),
                1 if h["tic"] != "9000" else 0)

    def test_veto_p3_14_handoff_preserved(self):
        # Veto first, P3-14 second is WRONG — the order is
        # P3-14 at screen time, veto at merge time. The veto
        # overwrites the top-level disposition (it is the
        # later, stronger verdict) and the P3-14 finding
        # survives inside the grid_edge hand-off record.
        survivors = _cluster(21)
        survivors[0]["disposition"] = "SINGLE_TRANSIT_POOL"
        survivors[0]["grid_edge"] = {
            "disposition": "SINGLE_TRANSIT_POOL",
            "ledger_status": "deferred"}
        hits = copy.deepcopy(survivors)
        kept, summary = bs.apply_epoch_cluster_veto(survivors, hits)
        self.assertEqual(len(kept), 0)
        self.assertEqual(summary["demoted_tier_b"], 21)
        hit0 = hits[0]
        self.assertEqual(hit0["disposition"],
                         DEMOTED_SECTOR_EPOCH_CLUSTER)
        self.assertEqual(hit0["grid_edge"]["disposition"],
                         "SINGLE_TRANSIT_POOL")
        self.assertEqual(hit0["grid_edge"]["ledger_status"],
                         "deferred")

    def test_veto_clusters_two_combined_demoted_rows(self):
        # TWO-COMBINED runs at screen time, before the veto;
        # without the demoted rows in the clustering input, a
        # 21-star cluster would shrink to 19 and escape. The
        # veto clusters the v3-tier survivor set (survivors +
        # TWO-COMBINED-demoted rows), as the replay measured.
        survivors = _cluster(19, tic0=1000)
        two_combined = _cluster(2, tic0=1019)
        for r in two_combined:
            r["status"] = "demoted"
            r["gate_reason"] = "FAILED_TWO_COMBINED"
            r["flags"] = ["TWO_EVENT_WEAK"]
        hits = copy.deepcopy(survivors) + copy.deepcopy(two_combined)
        kept, summary = bs.apply_epoch_cluster_veto(survivors, hits)
        self.assertEqual(kept, [])
        self.assertEqual(summary["demoted_tier_b"], 19)
        self.assertEqual(summary["n_clustered"], 21)
        # Control: the same 19 survivors without the demoted
        # rows in the input are not a cluster.
        kept, summary = bs.apply_epoch_cluster_veto(
            _cluster(19, tic0=1000), [])
        self.assertEqual(len(kept), 19)
        self.assertEqual(summary["demoted_tier_b"], 0)

    def test_veto_missing_ephemeris_kept(self):
        survivors = _cluster(25)
        for r in survivors:
            r["period_days"] = None
        kept, summary = bs.apply_epoch_cluster_veto(
            survivors, copy.deepcopy(survivors))
        self.assertEqual(len(kept), 25)
        self.assertEqual(summary["demoted_tier_b"], 0)

    def test_veto_no_tier_row_kept(self):
        # Matches the replay: only tier A (flag) and tier B
        # (demote) are veto targets.
        survivors = _cluster(21, tier=None)
        kept, summary = bs.apply_epoch_cluster_veto(
            survivors, copy.deepcopy(survivors))
        self.assertEqual(len(kept), 21)
        self.assertEqual(summary["demoted_tier_b"], 0)
        self.assertEqual(summary["flagged_tier_a"], 0)


class TestTwoCombinedScreen(unittest.TestCase):
    # Base fixture: a genuine 2-event tier-B detection
    # (P 13.2 d, depth 0.8%, duration 0.2 d) — mes 9.86,
    # n_strong 2, max_event_snr 8.07 under bulk_v4.
    BASE = dict(period_d=13.2, depth_frac=0.008, duration_d=0.2)

    def test_two_combined_mes_failure_demotes(self):
        raw = _screen_fixture(rescore_override={"mes_pink": 8.5},
                              **self.BASE)
        # The tier-B preconditions still hold — the fixture did
        # not drift out of the gate's regime.
        self.assertEqual(raw["n_events"], 2)
        self.assertGreaterEqual(raw["max_event_snr"], 8.0)
        self.assertEqual(raw["tier"], "B")
        self.assertEqual(raw["status"], "demoted")
        self.assertEqual(raw["gate_reason"], "FAILED_TWO_COMBINED")
        self.assertIn("TWO_EVENT_WEAK", raw["flags"])

    def test_two_combined_strong_failure_demotes(self):
        raw = _screen_fixture(
            rescore_override={"n_strong_events": 1}, **self.BASE)
        self.assertEqual(raw["n_events"], 2)
        self.assertEqual(raw["tier"], "B")
        self.assertEqual(raw["status"], "demoted")
        self.assertEqual(raw["gate_reason"], "FAILED_TWO_COMBINED")
        self.assertIn("TWO_EVENT_WEAK", raw["flags"])

    def test_two_combined_pass_survives(self):
        raw = _screen_fixture(**self.BASE)
        self.assertEqual(raw["n_events"], 2)
        self.assertEqual(raw["tier"], "B")
        self.assertEqual(raw["status"], "survivor")
        self.assertNotIn("gate_reason", raw)
        self.assertNotIn("TWO_EVENT_WEAK", raw["flags"])

    def test_two_combined_inactive_under_v3(self):
        # The same mes failure under bulk_v3 is a survivor —
        # the demotion is the v4 gate, not the fixture.
        raw = _screen_fixture(profile="bulk_v3",
                              rescore_override={"mes_pink": 8.5},
                              **self.BASE)
        self.assertEqual(raw["status"], "survivor")
        self.assertNotIn("gate_reason", raw)

    def test_two_combined_multi_event_unaffected(self):
        # n_events != 2 rows are exempt: even with mes and
        # n_strong steered below the gate's bars, no
        # TWO-COMBINED marker appears. (The row reads
        # "recorded" because the same values fail tier A —
        # the tier gates, not TWO-COMBINED, decide it.)
        raw = _screen_fixture(period_d=2.5, depth_frac=0.01,
                              duration_d=0.1,
                              rescore_override={"mes_pink": 8.5,
                                                "n_strong_events": 1})
        self.assertEqual(raw["n_events"], 11)
        self.assertEqual(raw["status"], "recorded")
        self.assertNotIn("gate_reason", raw)
        self.assertNotIn("TWO_EVENT_WEAK", raw["flags"])


class TestHeldAndRejectedGatesNotActive(unittest.TestCase):
    def test_demote_sys_not_active_13p2_survives(self):
        # A 13.7 d planet, near_systematic=True, tier-B
        # survivor under bulk_v4 — exactly the row DEMOTE-SYS
        # would have eaten (6/7 pricing). The profile carries
        # no demote_sys key (test_bulk_v4.py) and the screen
        # never looks at near_systematic for tier B.
        raw = _screen_fixture(period_d=13.7, depth_frac=0.009,
                              duration_d=0.2)
        self.assertTrue(raw["near_systematic"])
        self.assertEqual(raw["tier"], "B")
        self.assertEqual(raw["status"], "survivor")
        self.assertNotIn("gate_reason", raw)

    def test_phase_depth_not_active(self):
        # An unclustered tier-B row with odd_even_ratio 0.0 —
        # PHASE-DEPTH's failure value — is kept by the veto:
        # the veto never looks at odd/even. The profile carries
        # no phase_depth key (test_bulk_v4.py).
        survivors = [_row("5000", odd_even_ratio=0.0)]
        kept, summary = bs.apply_epoch_cluster_veto(
            survivors, copy.deepcopy(survivors))
        self.assertEqual(len(kept), 1)
        self.assertEqual(summary["demoted_tier_b"], 0)


class TestManualReviewQueue(unittest.TestCase):
    def test_review_queue_query(self):
        # The "unsure" queue, as documented in the bulk_v4
        # profile header: disposition ==
        # DEMOTED_SECTOR_EPOCH_CLUSTER OR gate_reason present.
        # An EB-demoted row and a P3-14 pool row are NOT in
        # this queue — they have their own dispositions.
        hits = [
            _row("100", status="demoted",
                 disposition=DEMOTED_SECTOR_EPOCH_CLUSTER,
                 flags=["SECTOR_EPOCH_CLUSTER"]),
            _row("101", status="demoted",
                 gate_reason="FAILED_TWO_COMBINED",
                 flags=["TWO_EVENT_WEAK"]),
            _row("102", status="survivor"),
            _row("103", status="demoted", flags=["DURATION_EB"]),
            _row("104", status="survivor",
                 disposition="SINGLE_TRANSIT_POOL"),
        ]
        unsure = [r for r in hits
                  if r.get("disposition")
                  == DEMOTED_SECTOR_EPOCH_CLUSTER
                  or r.get("gate_reason")]
        self.assertEqual([r["tic"] for r in unsure], ["100", "101"])

    def test_gated_records_validate_against_schema(self):
        # Both "unsure" markers are schema-legal: a real
        # TWO-COMBINED failure emitted through
        # emit_survivor_record validates, and a veto-demoted
        # record validates.
        raw = _screen_fixture(
            rescore_override={"mes_pink": 8.5},
            period_d=13.2, depth_frac=0.008, duration_d=0.2)
        emitted = bs.emit_survivor_record(raw, FIXED_PROV)
        self.assertEqual(emitted["gate_reason"],
                         "FAILED_TWO_COMBINED")
        validate_survivor(emitted)  # raises on failure
        vetoed = dict(emitted)
        vetoed["status"] = "demoted"
        vetoed["disposition"] = DEMOTED_SECTOR_EPOCH_CLUSTER
        vetoed.pop("gate_reason", None)
        validate_survivor(vetoed)  # raises on failure


if __name__ == "__main__":
    unittest.main()
