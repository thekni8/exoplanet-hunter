"""Neighbour-census tests (Phase 1.2 follow-up F-1).

The 180-arcsecond neighbour search is a policy parameter
(gauntlet_v2: neighbour_search_radius_arcsec), not a code
default: the old 60-arcsecond census missed a blend host at
66.5 arcseconds (S97, TIC 139524628). These tests are offline
except the no-false-kill run, which drives the pipeline through
the committed golden fixtures (the EXHUNT_FIXTURE_DIR seam —
no downloads).

  * the census fixture (tests/fixtures/census/s97_case.json)
    FINDS the 66.5-arcsecond host at 180" and MISSES it at 60";
  * the policy radius is 180.0, and the live census query uses
    it by default (mocked MAST call — no network);
  * the census JSON format is tic_cone_search + radius_arcsec,
    with the old tic_cone_60arcsec key accepted as a deprecated
    60-arcsecond fallback;
  * every blend check records census_radius_arcsec in its
    evidence;
  * the planet goldens (TOI-700, WASP-126 b) are NOT killed by
    the wider census: a neighbour showing no dip at the
    ephemeris leaves the verdict on_target.
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import hunter  # noqa: E402
from calibration import load_profile  # noqa: E402
from gauntlet.blend import check_blend  # noqa: E402
from gauntlet.diffimg import (  # noqa: E402
    census_from_rows, census_radius_from_policy,
    load_census_json, tic_cone_census)
from gauntlet.stage_result import blend_result  # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures" / "census"
BLEND_FIX = Path(__file__).resolve().parent / "fixtures" / "blend"
GOLDEN_FIX = Path(__file__).resolve().parent / "fixtures" / "golden"
PROV = {"calibration_version": "gauntlet_v2",
        "pipeline_git_sha": "test",
        "run_id": "test-run-1",
        "timestamp_utc": "2026-11-14T00:00:00+00:00"}


def _load_case():
    return json.loads((FIX / "s97_case.json").read_text())


class TestCensusFixture(unittest.TestCase):
    """The census itself, offline: the S97 host at 66.5" is the
    regression the 60" default would have failed."""

    def test_finds_host_at_180_misses_at_60(self):
        case = _load_case()
        tgt = case["target"]
        at_180 = census_from_rows(
            case["rows"], tgt["ra"], tgt["dec"], tgt["tmag"],
            180.0)
        at_60 = census_from_rows(
            case["rows"], tgt["ra"], tgt["dec"], tgt["tmag"],
            60.0)
        ids_180 = [r["tic_id"] for r in at_180]
        ids_60 = [r["tic_id"] for r in at_60]
        self.assertEqual(ids_180,
                         case["expected"]["at_180_arcsec"])
        self.assertEqual(ids_60,
                         case["expected"]["at_60_arcsec"])
        self.assertIn(139524628, ids_180)
        self.assertNotIn(139524628, ids_60)

    def test_census_boundaries_and_filters(self):
        case = _load_case()
        tgt = case["target"]
        at_180 = census_from_rows(
            case["rows"], tgt["ra"], tgt["dec"], tgt["tmag"],
            180.0)
        by_tic = {r["tic_id"]: r for r in at_180}
        # 150" is inside 180" only; 200" is outside both.
        self.assertIn(100000002, by_tic)
        self.assertNotIn(100000003, by_tic)
        # The Tmag 19.5 row is beyond the 18.5 limit; the
        # null-Tmag row is dropped, not crashed on.
        self.assertNotIn(100000004, by_tic)
        self.assertNotIn(100000005, by_tic)
        # Sorted by separation; the target is flagged.
        seps = [r["sep_arcsec"] for r in at_180]
        self.assertEqual(seps, sorted(seps))
        self.assertTrue(by_tic[139526205]["is_target"])
        self.assertFalse(by_tic[139524628]["is_target"])
        self.assertAlmostEqual(by_tic[139524628]["sep_arcsec"],
                               66.5, places=3)


class TestPolicyRadius(unittest.TestCase):
    def test_policy_radius_is_180(self):
        self.assertEqual(census_radius_from_policy(), 180.0)
        self.assertEqual(
            load_profile("gauntlet_v2")
            ["neighbour_search_radius_arcsec"], 180.0)

    def test_explicit_policy_dict_overrides(self):
        self.assertEqual(
            census_radius_from_policy(
                {"neighbour_search_radius_arcsec": 120.0}),
            120.0)

    def test_live_census_defaults_to_policy_radius(self):
        # The MAST call is mocked (no network): the query must
        # go out at the policy radius, and the host must be in
        # the returned census — proving the default is 180", not
        # the old 60".
        case = _load_case()
        seen = {}

        def fake_query_region(coord, catalog, radius):
            seen["radius_arcsec"] = radius.to("arcsec").value
            seen["catalog"] = catalog
            return case["rows"]

        with mock.patch(
                "astroquery.mast.Catalogs.query_region",
                side_effect=fake_query_region):
            out = tic_cone_census(case["target"]["ra"],
                                  case["target"]["dec"],
                                  case["target"]["tmag"])
        self.assertEqual(seen["catalog"], "TIC")
        self.assertEqual(seen["radius_arcsec"], 180.0)
        self.assertIn(139524628, [r["tic_id"] for r in out])


class TestLoadCensusJson(unittest.TestCase):
    def _write(self, obj):
        fd, path = tempfile.mkstemp(suffix=".json")
        with os.fdopen(fd, "w") as fh:
            json.dump(obj, fh)
        return path

    def test_new_format(self):
        path = self._write({
            "target": {"Tmag": 11.3},
            "tic_cone_search": [{"tic_id": 1, "sep_arcsec": 5.0,
                                 "Tmag": 11.3, "is_target": True}],
            "radius_arcsec": 180.0})
        try:
            tmag, cone, radius = load_census_json(path)
        finally:
            os.unlink(path)
        self.assertEqual(tmag, 11.3)
        self.assertEqual(len(cone), 1)
        self.assertEqual(radius, 180.0)

    def test_old_format_is_deprecated_60(self):
        path = self._write({
            "target": {"Tmag": 11.3},
            "tic_cone_60arcsec": [{"tic_id": 1, "sep_arcsec": 5.0,
                                   "Tmag": 11.3,
                                   "is_target": True}]})
        try:
            tmag, cone, radius = load_census_json(path)
        finally:
            os.unlink(path)
        # The old key means what it says: a 60-arcsecond census,
        # never silently upgraded to 180.
        self.assertEqual(radius, 60.0)
        self.assertEqual(len(cone), 1)

    def test_missing_key_raises(self):
        path = self._write({"target": {"Tmag": 11.3}})
        try:
            with self.assertRaises(ValueError):
                load_census_json(path)
        finally:
            os.unlink(path)


class TestBlendEvidenceRadius(unittest.TestCase):
    def test_check_blend_records_policy_radius(self):
        case = json.loads((BLEND_FIX / "case.json").read_text())
        t = np.load(BLEND_FIX / "tic139526205_target.npz")
        n = np.load(BLEND_FIX / "tic139526205_neighbour.npz")
        r = check_blend(t["time"], t["flux"], n["time"],
                        n["flux"], case["period_d"], case["t0"],
                        case["duration_h"] / 24.0,
                        neighbour_tic=case["neighbour_tic"],
                        separation_arcsec=
                        case["separation_arcsec"])
        self.assertEqual(r["verdict"], "blend")
        self.assertEqual(r["census_radius_arcsec"], 180.0)

    def test_explicit_radius_overrides_policy(self):
        case = json.loads((BLEND_FIX / "case.json").read_text())
        t = np.load(BLEND_FIX / "tic139526205_target.npz")
        n = np.load(BLEND_FIX / "tic139526205_neighbour.npz")
        r = check_blend(t["time"], t["flux"], n["time"],
                        n["flux"], case["period_d"], case["t0"],
                        case["duration_h"] / 24.0,
                        census_radius_arcsec=60.0)
        self.assertEqual(r["census_radius_arcsec"], 60.0)

    def test_adapter_carries_radius_into_details(self):
        case = json.loads((BLEND_FIX / "case.json").read_text())
        t = np.load(BLEND_FIX / "tic139526205_target.npz")
        n = np.load(BLEND_FIX / "tic139526205_neighbour.npz")
        native = {"target_t": t["time"], "target_f": t["flux"],
                  "neighbour_t": n["time"],
                  "neighbour_f": n["flux"],
                  "period_d": case["period_d"], "t0": case["t0"],
                  "duration_d": case["duration_h"] / 24.0,
                  "neighbour_tic": case["neighbour_tic"],
                  "separation_arcsec":
                      case["separation_arcsec"]}
        res = blend_result(native, PROV)
        self.assertEqual(res.status, "fail")  # blend -> FAIL
        self.assertEqual(res.details["census_radius_arcsec"],
                         180.0)


# The no-false-kill run: the pipeline runs once per golden at
# module level (the EXHUNT_FIXTURE_DIR seam — no downloads) and
# the tests share the results. ~90 s for both stars; this module
# is NOT in the smoke tier (F-10).
_FULL = {}
_PREV = None


def setUpModule():
    global _PREV
    missing = [f"TIC_{t}.npz" for t in ("150428135", "25155310")
               if not (GOLDEN_FIX / f"TIC_{t}.npz").exists()]
    if missing:
        raise RuntimeError(
            "golden fixtures missing: " + ", ".join(missing))
    _PREV = os.environ.get("EXHUNT_FIXTURE_DIR")
    os.environ["EXHUNT_FIXTURE_DIR"] = str(GOLDEN_FIX)
    _FULL["150428135"] = hunter._run_pipeline(
        "150428135", star_radius=0.42, max_sectors=2)
    _FULL["25155310"] = hunter._run_pipeline(
        "25155310", star_radius=1.30, max_sectors=1)


def tearDownModule():
    _FULL.clear()
    if _PREV is None:
        os.environ.pop("EXHUNT_FIXTURE_DIR", None)
    else:
        os.environ["EXHUNT_FIXTURE_DIR"] = _PREV


def _dip_free_neighbour(t, f, period, t0, duration_d):
    """The target's own light curve with the transit removed:
    in-transit cadences replaced by the out-of-transit median.
    A neighbour in the wider census that shows no dip — the
    blend check must not kill the planet on it."""
    ph = (((t - t0) / period + 0.5) % 1.0) - 0.5
    in_tr = np.abs(ph) < (0.5 * duration_d / period)
    out = ~in_tr
    f_nb = np.asarray(f, dtype=float).copy()
    f_nb[in_tr] = np.median(f[out])
    return t, f_nb


class TestNoFalseKill(unittest.TestCase):
    """More neighbours must not turn known planets into
    spurious BLENDs: for each planet golden, a neighbour with
    no dip at the ephemeris leaves the verdict on_target."""

    def _check(self, tic):
        full = _FULL[tic]
        z = np.load(GOLDEN_FIX / f"TIC_{tic}.npz")
        t = np.asarray(z["t"], dtype=float)
        f = np.asarray(z["f"], dtype=float)
        f = f / np.median(f)
        period = full["Period"]
        t0 = full["T0"]
        dur = full["Duration_Days"]
        t_nb, f_nb = _dip_free_neighbour(t, f, period, t0, dur)
        f_nb = f_nb / np.median(f_nb)
        r = check_blend(t, f, t_nb, f_nb, period, t0, dur,
                        neighbour_tic="dip-free-neighbour")
        # Guard against a vacuous pass: the target must show a
        # real dip, or the verdict would be inconclusive rather
        # than on_target.
        self.assertGreaterEqual(r["target_signif"], 3.0)
        self.assertEqual(r["verdict"], "on_target",
                         msg=f"TIC {tic}: a dip-free neighbour "
                             f"must not kill a known planet — "
                             f"{r['reason']}")
        self.assertEqual(r["census_radius_arcsec"], 180.0)

    def test_toi700_not_killed(self):
        self._check("150428135")

    def test_wasp126_not_killed(self):
        self._check("25155310")


if __name__ == "__main__":
    unittest.main()
