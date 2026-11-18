"""Golden-suite tests for bulk_v5 (post-merge fixes round 1).

bulk_v5 is ACTIVE (2026-11-18): all bulk_v4 gates carried over
verbatim, plus ONE change — the SECTOR_EPOCH_CLUSTER veto now
demotes tier-A cluster members too (epoch_cluster_veto_tier_a).
Under v4, tier-A members were flagged and KEPT, and the S98
one-shot showed why that fails: 210/498 (42.2%) of the final
queue sat in [13.5, 15.0] d, 184 of them flagged tier-A cluster
members. Measured effect on the frozen S98 run (read-only
replay): queue 498 -> 314, M6 42.2% -> 8.3%, 0/11 recovered
TOIs lost. systematic_windows UNCHANGED (zero flagged rows
below 13.5 d in S98). The discriminator is the (P, T0) cluster
criterion, not the period window — this is not DEMOTE-SYS.

These tests pin the profile shape AND the veto behaviour (the
v5 change is one gate, so shape + behaviour live in one file).
The S98 numbers are Mac-side run data, not repo fixtures — the
record (FIXES_ROUND1_RECORD.md) carries the measurement; these
tests prove the mechanism.

Offline, no downloads.
"""
import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import bulk_screen as bs  # noqa: E402
from calibration import (load_profile, load_registry,  # noqa: E402
                         profile_sha256)
from search_health import DEMOTED_SECTOR_EPOCH_CLUSTER  # noqa: E402

# Every gate field that must be identical between bulk_v4 and
# bulk_v5 (any difference besides the tier-A veto key is a
# threshold change, which needs the adoption rule + the campaign
# measurement behind it).
GATE_FIELDS = (
    "record_floor_sde", "survivor_sde", "depth_min_pct",
    "depth_eb_pct", "tier_a_mes", "tier_a_min_events",
    "tier_a_min_strong", "strong_event_snr", "tier_b_event_snr",
    "tier_b_max_depth_pct", "min_period_d", "max_period_d",
    "bls_grid_points", "bls_durations_d", "systematic_periods",
    "systematic_windows", "quality_mask", "clip_option",
    "two_combined_enabled", "epoch_cluster_veto_enabled",
    "epoch_cluster_tol_p", "epoch_cluster_tol_t0_d",
    "epoch_cluster_min_size",
    "grid_edge_min_in_transit_cadences",
    "grid_edge_max_unmasked_flag_fraction",
)

# Frozen profiles: bulk_v4 stamped the S98 one-shot (run
# bulk-20261118T022257Z-8c5d) and is immutable from here on.
FROZEN = {
    "bulk_v4": "ded60bd74dbb399c0a9a42d4f0e7aad43894b51db43d03d57d04e9ab0f2b206b",
}


def _row(tic, tier="B", period_days=13.2, t0_btjd=3920.0, **kw):
    r = {"tic": tic, "tier": tier, "period_days": period_days,
         "t0_btjd": t0_btjd, "status": "survivor", "flags": []}
    r.update(kw)
    return r


def _cluster(n, tier="B", period=13.2, t0=3920.0, tic0=1000):
    # n rows sharing (P, T0) within the P3-13 tolerances.
    return [_row(str(tic0 + i), tier=tier,
                 period_days=period + 0.001 * i,
                 t0_btjd=t0 + 0.001 * i) for i in range(n)]


class TestBulkV5Scaffold(unittest.TestCase):
    def test_v5_loads_and_is_active(self):
        prof = load_profile("bulk_v5")
        self.assertEqual(prof["version"], "bulk_v5")
        self.assertEqual(prof["status"], "active")
        self.assertTrue(prof["rationale"].strip())
        self.assertIs(prof["epoch_cluster_veto_tier_a"], True)

    def test_v5_registry_sha_matches(self):
        registry = load_registry()
        self.assertIn("bulk_v5", registry)
        self.assertEqual(registry["bulk_v5"]["sha256"],
                         profile_sha256("bulk_v5"))
        self.assertEqual(registry["bulk_v5"]["supersedes"], "bulk_v4")
        self.assertEqual(registry["bulk_v5"]["status"], "active")

    def test_v5_gates_identical_to_v4_except_tier_a(self):
        v4 = load_profile("bulk_v4")
        v5 = load_profile("bulk_v5")
        for field in GATE_FIELDS:
            self.assertEqual(
                v5[field], v4[field],
                f"bulk_v5 {field} differs from bulk_v4 — the v5 "
                f"change is the tier-A veto only")
        # The one difference: v4 has no tier-A key (means False);
        # v5 declares it True.
        self.assertNotIn("epoch_cluster_veto_tier_a", v4)
        self.assertIs(v5["epoch_cluster_veto_tier_a"], True)
        # SDE bars unchanged (the vote fixed them).
        self.assertEqual(v5["survivor_sde"], 7.0)
        self.assertEqual(v5["record_floor_sde"], 6.0)

    def test_frozen_v4_byte_identical(self):
        for name, want in FROZEN.items():
            self.assertEqual(profile_sha256(name), want,
                             f"{name} changed — frozen profiles "
                             f"are immutable")

    def test_set_calibration_derives_tier_a_flag(self):
        # True under v5, False under every earlier profile (a
        # frozen profile's behaviour must not change).
        previous = bs.CALIBRATION_VERSION
        try:
            bs.set_calibration("bulk_v5")
            self.assertEqual(bs.CALIBRATION_VERSION, "bulk_v5")
            self.assertIs(bs.EPOCH_CLUSTER_VETO_TIER_A, True)
            self.assertIs(bs.EPOCH_CLUSTER_VETO_ENABLED, True)
            for name in ("bulk_v1", "bulk_v2", "bulk_v3", "bulk_v4"):
                bs.set_calibration(name)
                self.assertIs(bs.EPOCH_CLUSTER_VETO_TIER_A, False,
                              f"{name} must mean tier-A flag-only")
        finally:
            bs.set_calibration(previous)


class TestTierAVeto(unittest.TestCase):
    def test_veto_demotes_clustered_tier_a_when_enabled(self):
        survivors = _cluster(21, tier="A")
        hits = copy.deepcopy(survivors)
        kept, summary = bs.apply_epoch_cluster_veto(
            survivors, hits, demote_tier_a=True)
        self.assertEqual(kept, [])
        self.assertEqual(summary["demoted_tier_a"], 21)
        self.assertEqual(summary["demoted_tier_b"], 0)
        self.assertEqual(summary["flagged_tier_a"], 0)
        self.assertEqual(summary["n_clusters"], 1)
        self.assertEqual(
            summary["demoted_tics"],
            sorted(r["tic"] for r in survivors))
        for h in hits:
            self.assertEqual(h["status"], "demoted")
            self.assertEqual(h["disposition"],
                             DEMOTED_SECTOR_EPOCH_CLUSTER)
            self.assertIn(bs.SECTOR_EPOCH_CLUSTER_FLAG, h["flags"])

    def test_veto_flags_tier_a_when_disabled(self):
        # The explicit-False path is the v4 behaviour.
        survivors = _cluster(21, tier="A")
        hits = copy.deepcopy(survivors)
        kept, summary = bs.apply_epoch_cluster_veto(
            survivors, hits, demote_tier_a=False)
        self.assertEqual(len(kept), 21)
        self.assertEqual(summary["demoted_tier_a"], 0)
        self.assertEqual(summary["flagged_tier_a"], 21)

    def test_veto_default_follows_loaded_calibration(self):
        # The wiring: the default parameter reads the profile
        # global, so v5 demotes and v4 flags with no explicit arg.
        previous = bs.CALIBRATION_VERSION
        try:
            bs.set_calibration("bulk_v5")
            kept, summary = bs.apply_epoch_cluster_veto(
                _cluster(21, tier="A"),
                copy.deepcopy(_cluster(21, tier="A")))
            self.assertEqual(kept, [])
            self.assertEqual(summary["demoted_tier_a"], 21)
            bs.set_calibration("bulk_v4")
            kept, summary = bs.apply_epoch_cluster_veto(
                _cluster(21, tier="A"),
                copy.deepcopy(_cluster(21, tier="A")))
            self.assertEqual(len(kept), 21)
            self.assertEqual(summary["flagged_tier_a"], 21)
        finally:
            bs.set_calibration(previous)

    def test_veto_mixed_cluster_demotes_both_tiers(self):
        survivors = (_cluster(11, tier="A", tic0=1000)
                     + _cluster(11, tier="B", tic0=2000))
        hits = copy.deepcopy(survivors)
        kept, summary = bs.apply_epoch_cluster_veto(
            survivors, hits, demote_tier_a=True)
        self.assertEqual(kept, [])
        self.assertEqual(summary["demoted_tier_a"], 11)
        self.assertEqual(summary["demoted_tier_b"], 11)
        self.assertEqual(summary["n_clustered"], 22)

    def test_veto_tier_a_idempotent(self):
        survivors = _cluster(25, tier="A") + [_row(
            "9000", tier="A", period_days=2.5, t0_btjd=3900.0)]
        hits = copy.deepcopy(survivors)
        kept, _ = bs.apply_epoch_cluster_veto(
            survivors, hits, demote_tier_a=True)
        kept2, summary2 = bs.apply_epoch_cluster_veto(
            kept, hits, demote_tier_a=True)
        self.assertEqual(len(kept2), 1)
        self.assertEqual(summary2["demoted_tier_a"], 0)
        self.assertEqual(summary2["demoted_tier_b"], 0)
        for h in hits:
            self.assertEqual(
                h["flags"].count(bs.SECTOR_EPOCH_CLUSTER_FLAG),
                1 if h["tic"] != "9000" else 0)


if __name__ == "__main__":
    unittest.main()
