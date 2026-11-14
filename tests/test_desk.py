"""Desk-driver tests (Phase 2, 2A).

The driver (gauntlet/desk.py) automates the vetting-manual desk
checks into the A-5 runner. These tests drive it end to end on
synthetic light curves through a FakeDataSource — no downloads,
no network — extending the F-7 7-scenario pattern to the
automated stages:

  1. a clean planet (box transit, 3 sectors) -> CANDIDATE
     (pixel_check waived: P < 8 d);
  2. a flagged-cadence artifact (dip only in quality-bit-29/30
     cadences, 0 clean in-transit — the 18-artifact class of
     the 2026-11-14 rescore gauntlet) -> REFUTED at the clean
     re-fold gate, cheap kill, expensive stages never called;
  3. a catalogued TOI at a matching period -> REFUTED;
  4. a V-shaped (triangular) transit -> EB at the shape gate;
  5. a neighbour showing a 5x dip -> BLEND;
  6. a single-sector planet + holdout/pixel waivers -> CANDIDATE;
  7. P >= 8 d with a clean TPF -> pixel_check PASS, CANDIDATE;
  8. a TPF pixel brightening in transit -> REFUTED;
  9. no data at all -> INCONCLUSIVE (not a crash);
 10. a dip in one sector only -> REFUTED at persistence;
 11. diffimg centroid off-target -> BLEND;
 12. a grazing transit fit (b = 1.1) -> EB.

Plus unit tests for the pure native builders (clean gate
flagcheck, diffimg/transit-fit native derivation, persistence,
stellar density).

The TPF load is the one stubbed seam: the fake writes a real
identity JSON, and load_tpf is monkeypatched to return the
synthetic cube (building a lightkurve-parseable TPF FITS from
scratch is out of proportion — load_tpf is a 6-line wrapper
around lk.read, proven by the live diffimg runs).
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

from gauntlet.desk import (DeskDataSource, Survivor,  # noqa: E402
                           clean_refold_native,
                           diffimg_native_for,
                           persistence_native,
                           rho_star_from_census,
                           run_desk_gauntlet,
                           transit_fit_native_for)
from validation import validate_verdict  # noqa: E402

P_BOX = 3.9227
T0_BOX = 1500.5
DUR_BOX = 0.105
DEPTH = 0.01
R_STAR, M_STAR = 0.9, 0.8


def _sector_times(start, ndays=27.0, cadence_min=10.0):
    return start + np.arange(0, ndays, cadence_min / 1440.0)


def _inject(t, P, T0, DUR, depth, profile="box"):
    f = np.ones_like(t)
    ph = ((t - T0 + 0.5 * P) % P) - 0.5 * P
    if profile == "box":
        f[np.abs(ph) <= DUR / 2] -= depth
    elif profile == "triangle":
        m = np.abs(ph) <= DUR / 2
        f[m] -= depth * (1.0 - np.abs(ph[m]) / (DUR / 2))
    return f


def _stitched(P=P_BOX, T0=T0_BOX, DUR=DUR_BOX, depth=DEPTH,
              n_sectors=3, profile="box", per_sector_depth=None,
              seed=11):
    """Multi-sector synthetic LC: 27 d sectors, 3 d gaps."""
    rng = np.random.default_rng(seed)
    ts, fs = [], []
    for i in range(n_sectors):
        t = _sector_times(1500.0 + 30.0 * i)
        d = depth if per_sector_depth is None \
            else per_sector_depth[i]
        f = _inject(t, P, T0, DUR, d, profile)
        f = f * (1.0 + rng.normal(0, 0.0005, len(t)))
        ts.append(t)
        fs.append(f)
    return np.concatenate(ts), np.concatenate(fs)


def _discovery(P=P_BOX, T0=T0_BOX, DUR=DUR_BOX, depth=DEPTH,
               mode="clean", seed=13):
    """One sector with quality flags. mode='artifact': the dip
    exists ONLY in flagged (bit-29/30) cadences, 0 clean
    in-transit — the 2026-11-14 rescore artifact class."""
    rng = np.random.default_rng(seed)
    t = _sector_times(1500.0)
    q = np.zeros(len(t), dtype=np.int64)
    ph = ((t - T0 + 0.5 * P) % P) - 0.5 * P
    in_tr = np.abs(ph) <= DUR / 2
    f = 1.0 + rng.normal(0, 0.0005, len(t))
    if mode == "clean":
        f[in_tr] -= depth
        flag = rng.random(len(t)) < 0.02
        q[flag & ~in_tr] = 1 << 29
    elif mode == "artifact":
        q[in_tr] = (1 << 29) | (1 << 30)
        f[in_tr] -= depth
    return t, f, q


def _census(toi=False, vsx=False, pht=False, neighbour=None):
    cone = []
    if neighbour is not None:
        cone.append({"tic_id": neighbour, "ra": 10.01, "dec": -60.01,
                     "sep_arcsec": 40.0, "Tmag": 9.0,
                     "rad_rsun": 1.0, "contratio": 0.5,
                     "gaia_id": "1", "is_target": False})
    return {"target": {"ID": "999999999", "ra": 10.0, "dec": -60.0,
                       "Tmag": 10.25, "rad": R_STAR, "mass": M_STAR,
                       "Teff": 5000.0, "contratio": 0.1,
                       "GAIA": "0", "dstArcSec": 0.1},
            "tic_cone_180arcsec": cone,
            "tic_cone_search": cone, "radius_arcsec": 180.0,
            "gaia_dr3_cone": None, "vsx_cone_180arcsec": [],
            "toi": {"is_toi": toi,
                    "rows": [{"toi": "192.01", "period_d": P_BOX,
                              "disposition": "KP"}] if toi else []},
            "pht": {"is_discussed": pht, "n_hits": 3 if pht else 0},
            "flags": [], "errors": []}


def _tpf_cube(P=P_BOX, T0=T0_BOX, DUR=DUR_BOX, depth=DEPTH,
              bright_px=None, seed=5):
    """A synthetic 15x15 TPF cube (5 d, 10-min cadence)."""
    rng = np.random.default_rng(seed)
    t = _sector_times(1500.0, ndays=5.0)
    yy, xx = np.mgrid[0:15, 0:15]
    base = 100.0 + 10000.0 * np.exp(
        -((xx - 7) ** 2 + (yy - 7) ** 2) / (2 * 1.5 ** 2))
    cube = (base[None, :, :]
            * (1.0 + rng.normal(0, 0.001, (len(t), 15, 15))))
    ph = ((t - T0 + 0.5 * P) % P) - 0.5 * P
    in_m = np.abs(ph) <= DUR / 2
    cube[in_m, 7, 7] *= (1.0 - depth)
    if bright_px is not None:
        y, x = bright_px
        cube[in_m, y, x] *= 1.02
    return t, cube


class FakeDataSource(DeskDataSource):
    """Serves synthetic data; records which methods were called
    (proves the cheap-pass short-circuit: expensive stages must
    never be called after a cheap kill)."""

    def __init__(self, census=None, discovery_mode="clean",
                 stitched_kwargs=None, neighbour_mode="flat",
                 holdout_verdict="HOLDOUT-PASS",
                 diffimg_on_target=True, transit_fit_b=0.3,
                 tpf_bright_px=None, stitched_none=False,
                 discovery_none=False):
        self._census = census if census is not None else _census()
        self.discovery_mode = discovery_mode
        self.stitched_kwargs = stitched_kwargs or {}
        self.neighbour_mode = neighbour_mode
        self.holdout_verdict = holdout_verdict
        self.diffimg_on_target = diffimg_on_target
        self.transit_fit_b = transit_fit_b
        self.tpf_bright_px = tpf_bright_px
        self.stitched_none = stitched_none
        self.discovery_none = discovery_none
        self.calls = []

    def census(self, tic, period, workdir):
        self.calls.append("census")
        with open(os.path.join(workdir, "stage0_census.json"),
                  "w") as fh:
            json.dump(self._census, fh)
        return self._census

    def discovery_lc(self, tic, sector):
        self.calls.append("discovery_lc")
        if self.discovery_none:
            return None
        return _discovery(mode=self.discovery_mode)

    def stitched_lc(self, tic, workdir):
        self.calls.append("stitched_lc")
        if self.stitched_none:
            return None
        n = self.stitched_kwargs.get("n_sectors", 3)
        t, f = _stitched(**self.stitched_kwargs)
        return {"pfx": "qlp", "sectors": [96 + i for i in range(n)],
                "t": t, "f": f, "spans": [],
                "sets": {"qlp": [96 + i for i in range(n)]}}

    def neighbour_lc(self, tic, workdir):
        self.calls.append("neighbour_lc")
        t = _sector_times(1500.0)
        if self.neighbour_mode == "flat":
            f = 1.0 + np.random.default_rng(3).normal(
                0, 0.0005, len(t))
        else:  # a 5% dip at the ephemeris — the blend host
            # (5x the 1% target dip, clear of the 3x policy bar)
            f = _inject(t, P_BOX, T0_BOX, DUR_BOX, 0.05)
            f = f * (1.0 + np.random.default_rng(3).normal(
                0, 0.0005, len(t)))
        return t, f

    def tesscut(self, tic, sectors, workdir, ra, dec, neighbour):
        self.calls.append("tesscut")
        tesscut_dir = os.path.join(workdir, "tesscut")
        os.makedirs(tesscut_dir, exist_ok=True)
        ident = {"target": {"tic": int(tic), "ra": ra, "dec": dec},
                 "neighbour": None, "cutout_size_px": 15,
                 "sectors": {str(s): {"status": "OK",
                                      "target_px": [7.0, 7.0]}
                             for s in sectors}}
        path = os.path.join(workdir, "identity.json")
        with open(path, "w") as fh:
            json.dump(ident, fh)
        for s in sectors:
            open(os.path.join(tesscut_dir,
                              f"tesscut_s{int(s):03d}.fits"),
                 "w").close()
        return tesscut_dir, path

    def holdout(self, tic, period, t0, duration_h, star_radius=1.0):
        self.calls.append("holdout")
        return self.holdout_verdict

    def diffimg(self, tic, period, t0, duration_d, workdir,
                census_path, depth_pct):
        self.calls.append("diffimg")
        if self.diffimg_on_target:
            return {"stack": {"dist_to_target_px": 0.06,
                              "dist_to_neighbour_px": 5.0,
                              "centroid": [7.06, 7.0]},
                    "sectors": {"96": {}, "97": {}, "98": {}}}
        return {"stack": {"dist_to_target_px": 3.5,
                          "dist_to_neighbour_px": 0.4,
                          "centroid": [10.5, 7.0]},
                "sectors": {"96": {}, "97": {}, "98": {}}}

    def transit_fit(self, tic, period, t0, duration_d, workdir,
                    qlp_sectors, r_star, r_star_err, m_star,
                    m_star_err, depth_pct):
        self.calls.append("transit_fit")
        return {"theta_ls": [P_BOX, T0_BOX, 0.1, 10.8,
                             self.transit_fit_b, 0.4, 0.3],
                "chi2": 1000.0, "npts": 11000}


def _survivor(**over):
    base = {"tic": "999999999", "period_d": P_BOX + 0.001,
            "t0_btjd": T0_BOX, "duration_h": DUR_BOX * 24,
            "depth_pct": 1.0, "sde": 15.0, "sector": 96,
            "bulk_survivor": True}
    base.update(over)
    return Survivor(**base)


def _by_stage(run):
    return {r.stage: r for r in run.results}


class TestDeskDriver(unittest.TestCase):
    def _run(self, source, survivor=None, **kw):
        with tempfile.TemporaryDirectory() as wd:
            result = run_desk_gauntlet(
                survivor or _survivor(), wd, source=source, **kw)
            # Copy the verdict out before the tempdir vanishes.
            verdict = json.load(open(os.path.join(
                wd, "verdict_record.json")))
            natives = json.load(open(os.path.join(
                wd, "desk_natives.json")))
            return result, verdict, natives

    def test_planet_candidate(self):
        result, verdict, _n = self._run(
            FakeDataSource(),
            waivers={"pixel_check": "P 3.92 d < 8 d"})
        self.assertEqual(result.run.final_verdict, "CANDIDATE")
        self.assertFalse(result.cheap_kill)
        stages = _by_stage(result.run)
        for s in ("catalogue", "clean_refold", "refine", "raw_flux",
                  "persistence", "shape", "odd_even", "holdout",
                  "diffimg", "blend", "transit_fit"):
            self.assertEqual(stages[s].status, "pass", msg=s)
        self.assertEqual(stages["pixel_check"].status,
                         "not_applicable")
        validate_verdict(verdict)
        self.assertEqual(verdict["final_verdict"], "CANDIDATE")

    def test_flagged_cadence_artifact_killed(self):
        # The 18-artifact regression: dip only in flagged
        # cadences, flat clean flux.
        src = FakeDataSource(
            discovery_mode="artifact",
            stitched_kwargs={"depth": 0.0})
        result, verdict, _n = self._run(src)
        self.assertEqual(result.run.final_verdict, "REFUTED")
        self.assertTrue(result.cheap_kill)
        self.assertEqual(_by_stage(result.run)["clean_refold"].status,
                         "fail")
        for expensive in ("holdout", "diffimg", "transit_fit"):
            self.assertNotIn(expensive, src.calls,
                             msg=f"{expensive} ran after a cheap kill")

    def test_catalogued_toi_killed(self):
        src = FakeDataSource(census=_census(toi=True))
        result, _v, _n = self._run(src)
        self.assertEqual(result.run.final_verdict, "REFUTED")
        self.assertTrue(result.cheap_kill)
        self.assertEqual(_by_stage(result.run)["catalogue"].status,
                         "fail")

    def test_eb_shape_killed(self):
        src = FakeDataSource(
            stitched_kwargs={"profile": "triangle"})
        result, _v, _n = self._run(src)
        self.assertEqual(result.run.final_verdict, "EB")
        self.assertEqual(_by_stage(result.run)["shape"].status,
                         "fail")

    def test_blend_killed(self):
        src = FakeDataSource(census=_census(neighbour="888888888"),
                             neighbour_mode="dip")
        result, _v, _n = self._run(src)
        self.assertEqual(result.run.final_verdict, "BLEND")
        self.assertEqual(_by_stage(result.run)["blend"].status,
                         "fail")

    def test_single_sector_waivers(self):
        src = FakeDataSource(stitched_kwargs={"n_sectors": 1})
        result, _v, _n = self._run(
            src, waivers={"holdout": "single sector",
                          "pixel_check": "P 3.92 d < 8 d"})
        self.assertEqual(result.run.final_verdict, "CANDIDATE")
        stages = _by_stage(result.run)
        self.assertEqual(stages["holdout"].status, "not_applicable")
        self.assertNotIn("holdout", src.calls)

    def test_pixel_check_passes(self):
        # P >= 8 d: the TPF path runs for real (load_tpf stubbed
        # to return the synthetic cube — see the module docstring).
        t, cube = _tpf_cube(P=12.5, T0=T0_BOX, DUR=0.155)
        src = FakeDataSource(
            stitched_kwargs={"P": 12.5, "DUR": 0.155,
                             "n_sectors": 3})
        surv = _survivor(period_d=12.501, duration_h=0.155 * 24)
        with mock.patch("gauntlet.desk.load_tpf",
                        return_value=(t, cube, None)):
            result, _v, _n = self._run(src, survivor=surv)
        self.assertEqual(_by_stage(result.run)["pixel_check"].status,
                         "pass")
        self.assertEqual(result.run.final_verdict, "CANDIDATE")

    def test_pixel_check_brightening_kills(self):
        t, cube = _tpf_cube(P=12.5, T0=T0_BOX, DUR=0.155,
                            bright_px=(7, 8))
        src = FakeDataSource(
            stitched_kwargs={"P": 12.5, "DUR": 0.155,
                             "n_sectors": 3})
        surv = _survivor(period_d=12.501, duration_h=0.155 * 24)
        with mock.patch("gauntlet.desk.load_tpf",
                        return_value=(t, cube, None)):
            result, _v, _n = self._run(src, survivor=surv)
        self.assertEqual(result.run.final_verdict, "REFUTED")
        self.assertEqual(_by_stage(result.run)["pixel_check"].status,
                         "fail")

    def test_no_data_is_inconclusive(self):
        src = FakeDataSource(stitched_none=True, discovery_none=True)
        result, _v, _n = self._run(src)
        self.assertEqual(result.run.final_verdict, "INCONCLUSIVE")

    def test_persistence_mixed_kills(self):
        src = FakeDataSource(
            stitched_kwargs={"per_sector_depth": [0.01, 0.0, 0.0]})
        result, _v, _n = self._run(src)
        self.assertEqual(result.run.final_verdict, "REFUTED")
        self.assertEqual(_by_stage(result.run)["persistence"].status,
                         "fail")

    def test_diffimg_off_target_kills(self):
        src = FakeDataSource(diffimg_on_target=False)
        result, _v, _n = self._run(
            src, waivers={"pixel_check": "P 3.92 d < 8 d"})
        self.assertEqual(result.run.final_verdict, "BLEND")
        self.assertEqual(_by_stage(result.run)["diffimg"].status,
                         "fail")

    def test_transit_fit_grazing_kills(self):
        src = FakeDataSource(transit_fit_b=1.1)
        result, _v, _n = self._run(
            src, waivers={"pixel_check": "P 3.92 d < 8 d"})
        self.assertEqual(result.run.final_verdict, "EB")
        self.assertEqual(
            _by_stage(result.run)["transit_fit"].status, "fail")


class TestNativeBuilders(unittest.TestCase):
    def test_clean_refold_flagged_only_fails(self):
        t, f, q = _discovery(mode="artifact")
        fold, verdict = clean_refold_native(t, f, q, P_BOX, T0_BOX,
                                            DUR_BOX * 24)
        self.assertEqual(fold["n_in"], 0)
        self.assertEqual(verdict, "FAIL")
        self.assertIn("flagged_fold", fold)
        self.assertGreater(fold["flagged_fold"]["snr"], 3.0)

    def test_clean_refold_clean_passes(self):
        t, f, q = _discovery(mode="clean")
        _fold, verdict = clean_refold_native(t, f, q, P_BOX, T0_BOX,
                                             DUR_BOX * 24)
        self.assertEqual(verdict, "PASS")

    def test_diffimg_native_for(self):
        on = diffimg_native_for(
            {"stack": {"dist_to_target_px": 0.06,
                       "dist_to_neighbour_px": 5.0},
             "sectors": {"96": {}, "97": {}}}, "888")
        self.assertTrue(on["on_target"])
        self.assertAlmostEqual(on["offset_arcsec"], 0.06 * 21.0)
        self.assertIsNone(on["blend_host_tic"])
        self.assertEqual(on["n_sectors"], 2)
        off = diffimg_native_for(
            {"stack": {"dist_to_target_px": 3.5,
                       "dist_to_neighbour_px": 0.4},
             "sectors": {"96": {}}}, "888")
        self.assertFalse(off["on_target"])
        self.assertEqual(off["blend_host_tic"], "888")
        none = diffimg_native_for({"stack": {}, "sectors": {}})
        self.assertIsNone(none["on_target"])
        self.assertIsNone(diffimg_native_for(None))

    def test_transit_fit_native_for(self):
        ls = {"theta_ls": [P_BOX, T0_BOX, 0.1, 10.8, 0.3, 0.4, 0.3],
              "chi2": 1000.0, "npts": 11000}
        rho = rho_star_from_census({"mass": M_STAR, "rad": R_STAR})
        native = transit_fit_native_for(ls, R_STAR, rho)
        self.assertTrue(native["converged"])
        self.assertEqual(native["b"], 0.3)
        self.assertAlmostEqual(native["rp_re"], 0.1 * 0.9 * 109.2,
                               places=1)
        self.assertFalse(native["density_flag"])
        self.assertIsNotNone(native["t14_h"])
        grazing = dict(ls)
        grazing["theta_ls"] = [P_BOX, T0_BOX, 0.1, 10.8, 1.1, 0.4,
                               0.3]
        self.assertEqual(
            transit_fit_native_for(grazing, R_STAR, rho)["b"], 1.1)
        self.assertIsNone(transit_fit_native_for(ls, None, rho))
        self.assertIsNone(transit_fit_native_for({}, R_STAR, rho))

    def test_persistence_native(self):
        t, f = _stitched()
        stamp = persistence_native(t, f, P_BOX, T0_BOX, DUR_BOX)
        self.assertEqual(stamp["verdict"], "CONSISTENT")
        self.assertEqual(stamp["n_usable"], 3)
        t2, f2 = _stitched(per_sector_depth=[0.01, 0.0, 0.0])
        stamp2 = persistence_native(t2, f2, P_BOX, T0_BOX, DUR_BOX)
        self.assertEqual(stamp2["verdict"], "MIXED")
        t3, f3 = _stitched(depth=0.0)
        stamp3 = persistence_native(t3, f3, P_BOX, T0_BOX, DUR_BOX)
        self.assertEqual(stamp3["verdict"], "MIXED")

    def test_rho_star_from_census(self):
        # Solar units (mass/radius^3) — the units the shape gate
        # expects, not g/cm3.
        rho = rho_star_from_census({"mass": 0.8, "rad": 0.9})
        self.assertAlmostEqual(rho, 0.8 / 0.9 ** 3, places=3)
        self.assertIsNone(rho_star_from_census({"mass": 0.8}))
        self.assertIsNone(rho_star_from_census(None))


if __name__ == "__main__":
    unittest.main()
