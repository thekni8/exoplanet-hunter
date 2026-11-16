"""Golden-suite tests for bulk_v4 (Phase 3, P3-15).

bulk_v4 is ACTIVE (2026-11-16, P3-15 gate landing): all bulk_v3
gates carried over verbatim, plus the P3-14 grid-edge floor
constants, plus the two tier-B gates the P3-11 decision adopted
(parent 2026-11-16, Amendment A approved) — EPOCH-CLUSTER +
TWO-COMBINED. PHASE-DEPTH is held, DEMOTE-SYS/DEMOTE-ALL
rejected, SDE bars unchanged. These tests pin the landed state
— status active, gates as decided, frozen profiles
byte-identical — so a later drift is a deliberate, reviewed
update, not a silent change. The gate BEHAVIOUR tests live in
test_bulk_v4_gates.py; this file pins the profile shape.

Offline, no downloads.
"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import bulk_screen as bs  # noqa: E402
from calibration import (load_profile, load_registry,  # noqa: E402
                         profile_sha256)
from synth_fits import make_qlp_fits, screen_job  # noqa: E402

# Gate fields that must be identical between bulk_v3 and bulk_v4
# in the scaffold (any difference is a threshold change, which
# needs the adoption rule + the campaign measurement behind it).
GATE_FIELDS = (
    "record_floor_sde", "survivor_sde", "depth_min_pct",
    "depth_eb_pct", "tier_a_mes", "tier_a_min_events",
    "tier_a_min_strong", "strong_event_snr", "tier_b_event_snr",
    "tier_b_max_depth_pct", "min_period_d", "max_period_d",
    "bls_grid_points", "bls_durations_d", "systematic_periods",
    "systematic_windows", "quality_mask", "clip_option",
)

# Frozen profiles: sha256 pinned in the registry, verified here
# so a byte change anywhere in the tree fails loudly.
FROZEN = {
    "bulk_v1": "54e9c35c1df5bd8de9684af23f6e99d2e6f4d99066222eedee9adf20ef3c7856",
    "bulk_v2": "6032dec0ff6555ef453c51100183220a65fe7af97942790349d5a66233630223",
    "bulk_v3": "685ea756536e7a6600975c00d09d97350fd218c2377e6ac680237aa3b35c2aab",
    "deep_v1": "d30457270abf3b91f5896d405bf50328bd33cad03aa1d03d36adc6e566a602c5",
    "deep_v2": "ab622ac5e9c1070a74fe280a097ae9ef485b05a48dc27fdc70299e7f6fb40df1",
}


class TestBulkV4Scaffold(unittest.TestCase):
    def test_v4_loads_and_is_active(self):
        prof = load_profile("bulk_v4")
        self.assertEqual(prof["version"], "bulk_v4")
        # The landed state (P3-15, 2026-11-16): the gates are
        # adopted and the profile is the screening profile.
        # This assertion changed from "provisional" in the
        # landing commit, with the parent decision behind it
        # (phase3-vote/p3-11-decision.md §9).
        self.assertEqual(prof["status"], "active")
        self.assertTrue(prof["rationale"].strip())

    def test_v4_registry_sha_matches(self):
        registry = load_registry()
        self.assertIn("bulk_v4", registry)
        self.assertEqual(registry["bulk_v4"]["sha256"],
                         profile_sha256("bulk_v4"))
        self.assertEqual(registry["bulk_v4"]["supersedes"], "bulk_v3")
        self.assertEqual(registry["bulk_v4"]["status"], "active")

    def test_v4_adopted_gates_enabled(self):
        # The P3-11 decision (§9): ADOPT EPOCH-CLUSTER +
        # TWO-COMBINED; HOLD PHASE-DEPTH; REJECT DEMOTE-SYS /
        # DEMOTE-ALL. The profile enables exactly the two
        # adopted gates — no enablement key exists for the
        # held/rejected ones.
        v4 = load_profile("bulk_v4")
        self.assertIs(v4["two_combined_enabled"], True)
        self.assertIs(v4["epoch_cluster_veto_enabled"], True)
        self.assertEqual(v4["epoch_cluster_tol_p"], 0.01)
        self.assertEqual(v4["epoch_cluster_tol_t0_d"], 0.125)
        self.assertEqual(v4["epoch_cluster_min_size"], 21)
        for key in v4:
            self.assertNotIn("phase_depth", key)
            self.assertNotIn("demote_sys", key)
            self.assertNotIn("demote_all", key)

    def test_v4_gates_identical_to_v3(self):
        v3 = load_profile("bulk_v3")
        v4 = load_profile("bulk_v4")
        for field in GATE_FIELDS:
            self.assertEqual(
                v4[field], v3[field],
                f"bulk_v4 {field} differs from bulk_v3 — a gate "
                f"change needs the adoption rule + campaign "
                f"measurement (P3-11/P3-10)")

    def test_v4_sde_bars_unchanged(self):
        # The vote fixed the bars (bulk 7.0, deep 8.5); v4 does
        # not move them.
        v4 = load_profile("bulk_v4")
        self.assertEqual(v4["survivor_sde"], 7.0)
        self.assertEqual(v4["record_floor_sde"], 6.0)

    def test_v4_carries_grid_edge_floor(self):
        v4 = load_profile("bulk_v4")
        self.assertEqual(v4["grid_edge_min_in_transit_cadences"], 4)
        self.assertEqual(v4["grid_edge_max_unmasked_flag_fraction"],
                         0.0)

    def test_frozen_profiles_byte_identical(self):
        for name, want in FROZEN.items():
            self.assertEqual(profile_sha256(name), want,
                             f"{name} changed — frozen profiles "
                             f"are immutable")

    def test_set_calibration_v4_derives_floor(self):
        previous = bs.CALIBRATION_VERSION
        try:
            bs.set_calibration("bulk_v4")
            self.assertEqual(bs.CALIBRATION_VERSION, "bulk_v4")
            self.assertEqual(bs.GRID_EDGE_MIN_IN_TRANSIT, 4)
            self.assertEqual(bs.GRID_EDGE_MAX_UNMASKED_FRACTION, 0.0)
            self.assertEqual(bs.QUALITY_MASK, 1610629823)
            self.assertEqual(bs.SURVIVOR_SDE, 7.0)
        finally:
            bs.set_calibration(previous)

    def test_screen_under_v4_records_floor_fields(self):
        previous = bs.CALIBRATION_VERSION
        try:
            bs.set_calibration("bulk_v4")
            with tempfile.TemporaryDirectory() as td:
                p = make_qlp_fits(Path(td) / "planet.fits",
                                  period_d=2.5, depth_frac=0.01,
                                  duration_d=0.1, noise_pct=0.003,
                                  seed=42)
                raw = bs._screen_one(screen_job(p))
                self.assertEqual(raw["status"], "survivor")
                self.assertIn("n_in_transit", raw)
                self.assertIn("flagged_in_transit_frac", raw)
        finally:
            bs.set_calibration(previous)


if __name__ == "__main__":
    unittest.main()
