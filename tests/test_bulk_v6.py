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
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import bulk_screen as bs  # noqa: E402
from bulk import replay_matrix as _rm  # noqa: E402
from calibration import (CalibrationError, load_profile,  # noqa: E402
                         load_registry, profile_sha256)

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


if __name__ == "__main__":
    unittest.main()
