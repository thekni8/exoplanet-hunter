"""Tests for versioned calibration profiles (calibration.py).

No downloads. Two kinds of guard:
  * PIN tests: the v1 profile values are the frozen, measured
    numbers — a silent edit to a profile YAML goes red here.
    Changing a threshold is deliberate: new profile version +
    code + suite, together.
  * DRIFT tests: the deep/gauntlet profiles are snapshots of the
    code's named constants — if code and profile disagree, the
    suite goes red. (The bulk profile is the source of truth
    instead: bulk_screen.py loads it at import.)
"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import bulk_screen  # noqa: E402
import calibration  # noqa: E402
import hunter  # noqa: E402
import persistence  # noqa: E402
from calibration import CalibrationError, load_profile  # noqa: E402
from gauntlet import rawflux_check, transit_fit  # noqa: E402


class TestBulkProfile(unittest.TestCase):
    def test_bulk_v1_values_are_the_frozen_v11_numbers(self):
        p = load_profile("bulk_v1")
        self.assertEqual(p["version"], "bulk_v1")
        self.assertEqual(p["record_floor_sde"], 6.0)
        self.assertEqual(p["survivor_sde"], 7.0)
        self.assertEqual(p["depth_min_pct"], 0.02)
        self.assertEqual(p["depth_eb_pct"], 3.0)
        self.assertEqual(p["tier_a_mes"], 9.0)
        self.assertEqual(p["tier_a_min_events"], 3)
        self.assertEqual(p["tier_a_min_strong"], 2)
        self.assertEqual(p["strong_event_snr"], 3.0)
        self.assertEqual(p["tier_b_event_snr"], 8.0)
        self.assertEqual(p["tier_b_max_depth_pct"], 1.0)
        self.assertEqual(p["min_period_d"], 0.5)
        self.assertEqual(p["max_period_d"], 20.0)
        self.assertEqual(p["bls_grid_points"], 12000)
        self.assertEqual(p["bls_durations_d"],
                         [0.04, 0.06, 0.09, 0.13, 0.18, 0.25])
        self.assertEqual(p["systematic_periods"], [13.7, 6.85, 27.4])

    def test_bulk_screen_loads_the_profile(self):
        # The module constants are derived from the profile — the
        # wiring, not just the file, is what the screen runs on.
        p = load_profile("bulk_v1")
        self.assertEqual(bulk_screen.CALIBRATION_VERSION, "bulk_v1")
        self.assertEqual(bulk_screen.RECORD_FLOOR_SDE,
                         p["record_floor_sde"])
        self.assertEqual(bulk_screen.SURVIVOR_SDE, p["survivor_sde"])
        self.assertEqual(bulk_screen.TIER_A_MES, p["tier_a_mes"])
        self.assertEqual(bulk_screen.TIER_B_EVENT_SNR,
                         p["tier_b_event_snr"])
        self.assertEqual(bulk_screen.BLS_GRID_POINTS,
                         p["bls_grid_points"])
        self.assertEqual(bulk_screen.BLS_DURATIONS_D,
                         tuple(p["bls_durations_d"]))
        self.assertEqual(bulk_screen.SYSTEMATIC_PERIODS,
                         tuple(p["systematic_periods"]))


class TestDeepDrift(unittest.TestCase):
    def test_deep_profile_matches_hunter_constants(self):
        p = load_profile("deep_v1")
        self.assertEqual(p["hit_sde"], hunter.HIT_SDE)
        self.assertEqual(p["acceptance_floor_sde"], hunter.ACCEPT_SDE)
        self.assertEqual(tuple(p["systematic_periods"]),
                         hunter._SYSTEMATIC_PERIODS)
        self.assertEqual(p["hit_sde"], 8.5)
        self.assertEqual(p["acceptance_floor_sde"], 6.5)


class TestGauntletDrift(unittest.TestCase):
    def test_gauntlet_profile_matches_code_constants(self):
        p = load_profile("gauntlet_v1")
        self.assertEqual(p["shape_v_max_t23_t14"],
                         rawflux_check.V_SHAPE_MAX_T23_T14)
        self.assertEqual(p["shape_u_min_t23_t14"],
                         rawflux_check.U_SHAPE_MIN_T23_T14)
        self.assertEqual(p["density_ratio_min"],
                         rawflux_check.DENSITY_RATIO_MIN)
        self.assertEqual(p["chi2_sys_frac"],
                         persistence.CHI2_SYS_FRAC)
        self.assertEqual(p["mad_clip_floor_frac"],
                         rawflux_check.MAD_CLIP_FLOOR_FRAC)
        self.assertEqual(p["mad_clip_floor_frac"],
                         transit_fit.MAD_CLIP_FLOOR_FRAC)
        self.assertEqual(p["shape_v_max_t23_t14"], 0.30)
        self.assertEqual(p["shape_u_min_t23_t14"], 0.50)
        self.assertEqual(p["chi2_sys_frac"], 0.15)


class TestLoader(unittest.TestCase):
    def test_missing_profile_raises(self):
        with self.assertRaises(CalibrationError):
            load_profile("bulk_v999")

    def test_version_mismatch_raises(self):
        # A copied profile that forgets the version bump fails
        # loudly at load time instead of stamping the wrong version.
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "bulk_v2.yaml").write_text(
                "version: bulk_v1\nsurvivor_sde: 7.0\n")
            old = calibration.CALIBRATION_DIR
            calibration.CALIBRATION_DIR = Path(td)
            try:
                with self.assertRaises(CalibrationError):
                    load_profile("bulk_v2")
            finally:
                calibration.CALIBRATION_DIR = old

    def test_available_profiles(self):
        names = calibration.available_profiles()
        self.assertIn("bulk_v1", names)
        self.assertIn("deep_v1", names)
        self.assertIn("gauntlet_v1", names)


if __name__ == "__main__":
    unittest.main()
