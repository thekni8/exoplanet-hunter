"""Desk-driver external-tools wiring tests (Phase 2, 2B-3).

The driver runs LATTE/TRICERATOPS as post-runner EVIDENCE
stages after pass 2, only on a survivor no stage failed.
These tests drive run_desk_gauntlet with a fake LATTE
wrapper (a script that writes a canned LATTE output JSON
and touches a marker file, so the test can prove whether
the tool ran) on synthetic light curves:

  1. a clean planet -> CANDIDATE + a LATTE result in
     extra_evidence (inconclusive, report-only), raw output
     recorded, tool_lc.npz + stage0_census.json written and
     hashed;
  2. a flagged-cadence artifact -> REFUTED at the cheap
     gate, the tool never runs (no marker file);
  3. a pass-2 FAIL (diffimg off-target) -> BLEND, the tool
     never runs;
  4. a missing venv python -> the LATTE result reads
     unmeasured + EXEC_ERROR and the verdict is unaffected
     (still CANDIDATE);
  5. a census target missing Teff -> the tool is skipped
     with the error recorded, the run completes.

Plus unit tests for external_tool_sections and for the
policy loader (load_external_tool_configs on the real
external_tools_v1 policy).

The synthetic data + fake source are a slim copy of
tests/test_desk.py's fake (same seeds, same clean-planet
scenario) so this module stands alone.
"""
import hashlib
import json
import os
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gauntlet.desk import (DeskDataSource, Survivor,  # noqa: E402
                           external_tool_sections,
                           run_desk_gauntlet)
from gauntlet.external_tool import (  # noqa: E402
    ToolConfig, load_external_tool_configs)

P_BOX = 3.9227
T0_BOX = 1500.5
DUR_BOX = 0.105
DEPTH = 0.01
R_STAR, M_STAR = 0.9, 0.8


def _sector_times(start, ndays=27.0, cadence_min=10.0):
    return start + np.arange(0, ndays, cadence_min / 1440.0)


def _inject(t, P, T0, DUR, depth):
    f = np.ones_like(t)
    ph = ((t - T0 + 0.5 * P) % P) - 0.5 * P
    f[np.abs(ph) <= DUR / 2] -= depth
    return f


def _stitched(P=P_BOX, T0=T0_BOX, DUR=DUR_BOX, depth=DEPTH,
              n_sectors=3, seed=11):
    rng = np.random.default_rng(seed)
    ts, fs = [], []
    for i in range(n_sectors):
        t = _sector_times(1500.0 + 30.0 * i)
        f = _inject(t, P, T0, DUR, depth)
        f = f * (1.0 + rng.normal(0, 0.0005, len(t)))
        ts.append(t)
        fs.append(f)
    return np.concatenate(ts), np.concatenate(fs)


def _discovery(P=P_BOX, T0=T0_BOX, DUR=DUR_BOX, depth=DEPTH,
               mode="clean", seed=13):
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


def _census(drop_teff=False):
    target = {"ID": "999999999", "ra": 10.0, "dec": -60.0,
              "Tmag": 10.25, "rad": R_STAR, "mass": M_STAR,
              "Teff": 5000.0, "contratio": 0.1,
              "GAIA": "0", "dstArcSec": 0.1}
    if drop_teff:
        del target["Teff"]
    return {"target": target, "tic_cone_180arcsec": [],
            "tic_cone_search": [], "radius_arcsec": 180.0,
            "gaia_dr3_cone": None, "vsx_cone_180arcsec": [],
            "toi": {"is_toi": False, "rows": []},
            "pht": {"is_discussed": False, "n_hits": 0},
            "flags": [], "errors": []}


class FakeDataSource(DeskDataSource):
    def __init__(self, census=None, discovery_mode="clean",
                 diffimg_on_target=True):
        self._census = census if census is not None else _census()
        self.discovery_mode = discovery_mode
        self.diffimg_on_target = diffimg_on_target
        self.calls = []

    def census(self, tic, period, workdir):
        self.calls.append("census")
        with open(os.path.join(workdir, "stage0_census.json"),
                  "w") as fh:
            json.dump(self._census, fh)
        return self._census

    def discovery_lc(self, tic, sector):
        self.calls.append("discovery_lc")
        return _discovery(mode=self.discovery_mode)

    def stitched_lc(self, tic, workdir):
        self.calls.append("stitched_lc")
        t, f = _stitched()
        return {"pfx": "qlp", "sectors": [96, 97, 98],
                "t": t, "f": f, "spans": [],
                "sets": {"qlp": [96, 97, 98]}}

    def neighbour_lc(self, tic, workdir):
        self.calls.append("neighbour_lc")
        t = _sector_times(1500.0)
        f = 1.0 + np.random.default_rng(3).normal(
            0, 0.0005, len(t))
        return t, f

    def tesscut(self, tic, sectors, workdir, ra, dec, neighbour):
        self.calls.append("tesscut")
        tesscut_dir = os.path.join(workdir, "tesscut")
        os.makedirs(tesscut_dir, exist_ok=True)
        ident = {"target": {"tic": int(tic), "ra": ra,
                            "dec": dec},
                 "neighbour": None, "cutout_size_px": 15,
                 "sectors": {str(s): {"status": "OK",
                                      "target_px": [7.0, 7.0]}
                             for s in sectors}}
        path = os.path.join(workdir, "identity.json")
        with open(path, "w") as fh:
            json.dump(ident, fh)
        return tesscut_dir, path

    def holdout(self, tic, period, t0, duration_h,
                star_radius=1.0):
        self.calls.append("holdout")
        return "HOLDOUT-PASS"

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
        return {"theta_ls": [P_BOX, T0_BOX, 0.1, 10.8, 0.3,
                             0.4, 0.3],
                "chi2": 1000.0, "npts": 11000}


def _survivor(**over):
    base = {"tic": "999999999", "period_d": P_BOX + 0.001,
            "t0_btjd": T0_BOX, "duration_h": DUR_BOX * 24,
            "depth_pct": 1.0, "sde": 15.0, "sector": 96,
            "bulk_survivor": True}
    base.update(over)
    return Survivor(**base)


FAKE_LATTE_WRAPPER = textwrap.dedent("""\
    import argparse, json, os
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()
    inp = json.load(open(args.input))
    marker = os.environ.get("FAKE_TOOL_MARKER")
    if marker:
        open(marker, "w").write("ran")
    json.dump({
        "tool": "latte", "tool_version": "1.0.21",
        "seed": inp["seed"], "config_hash": inp["config_hash"],
        "status": "completed", "value": None,
        "metrics": {"report_pdf": "/tmp/fake/DV_report.pdf",
                    "output_dir": "/tmp/fake",
                    "n_artifacts": 12,
                    "latte_indir": "/tmp/fake"},
        "input_hashes": {
            "lightcurve": inp["lightcurve"]["input_hash"],
            "neighbours": inp["neighbours"]["input_hash"]},
        "artifacts": ["/tmp/fake/DV_report.pdf"],
        "warnings": [], "wall_time_s": 187.0,
        "n_transits": inp["signal"]["n_transits"],
    }, open(args.output, "w"))
    """)


FAKE_TRI_WRAPPER = textwrap.dedent("""\
    import argparse, json, os
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()
    inp = json.load(open(args.input))
    marker = os.environ.get("FAKE_TRI_MARKER")
    if marker:
        open(marker, "w").write("ran")
    json.dump({
        "tool": "triceratops", "tool_version": "1.1.0",
        "seed": inp["seed"], "config_hash": inp["config_hash"],
        "status": "completed", "value": 0.0032,
        "metrics": {"fpp": 0.0032, "nfpp": 0.0008,
                    "prob_planet": 0.9968,
                    "prob_eb_target": 0.0021,
                    "prob_eb_neighbour": 0.0009,
                    "prob_hierarchical_eb": 0.0002,
                    "n_samples": 1000000,
                    "most_likely_false_positive":
                        "EB on TIC 999999999",
                    "fpp_degenerate": False,
                    "dilution_corrected":
                        inp.get("dilution_corrected", False),
                    "contrast_curve_used": False},
        "input_hashes": {
            "lightcurve": inp["lightcurve"]["input_hash"],
            "neighbours": inp["neighbours"]["input_hash"]},
        "artifacts": ["/tmp/fake/triceratops_probs.csv"],
        "warnings": ["no contrast curve: NFPP is an upper "
                     "bound"],
        "wall_time_s": 412.5,
        "n_transits": inp["signal"]["n_transits"],
    }, open(args.output, "w"))
    """)


class TestDeskExternalTools(unittest.TestCase):

    def _configs(self, tmp, python=sys.executable):
        wrapper = Path(tmp) / "fake_latte.py"
        wrapper.write_text(FAKE_LATTE_WRAPPER)
        marker = str(Path(tmp) / "latte_ran.marker")
        os.environ["FAKE_TOOL_MARKER"] = marker
        self.addCleanup(os.environ.pop, "FAKE_TOOL_MARKER", None)
        return {"latte": ToolConfig(
            tool="latte", python=python, wrapper=str(wrapper),
            timeout_s=30, memory_mb=2048, seed=20261114,
            tool_version="1.0.21", config_hash="c" * 64)}, marker

    def _both_configs(self, tmp):
        configs, latte_marker = self._configs(tmp)
        wrapper = Path(tmp) / "fake_tri.py"
        wrapper.write_text(FAKE_TRI_WRAPPER)
        tri_marker = str(Path(tmp) / "tri_ran.marker")
        os.environ["FAKE_TRI_MARKER"] = tri_marker
        self.addCleanup(os.environ.pop, "FAKE_TRI_MARKER", None)
        configs["triceratops"] = ToolConfig(
            tool="triceratops", python=sys.executable,
            wrapper=str(wrapper), timeout_s=30, memory_mb=2048,
            seed=20261114, tool_version="1.1.0",
            config_hash="c" * 64)
        return configs, latte_marker, tri_marker

    def _run(self, source, configs, **kw):
        # Everything is extracted inside the block: the
        # tempdir is deleted on exit.
        with tempfile.TemporaryDirectory() as wd:
            result = run_desk_gauntlet(
                _survivor(), wd, source=source,
                waivers={"pixel_check": "P 3.92 d < 8 d"},
                external_tools=configs, **kw)
            natives = json.load(open(os.path.join(
                wd, "desk_natives.json")))
            verdict = json.load(open(os.path.join(
                wd, "verdict_record.json")))
            files = sorted(os.listdir(wd))
            lc_hash = None
            lc_path = os.path.join(wd, "tool_lc.npz")
            if os.path.exists(lc_path):
                lc_hash = hashlib.sha256(
                    open(lc_path, "rb").read()).hexdigest()
            return result, natives, verdict, files, lc_hash

    def test_latte_runs_on_clean_planet(self):
        with tempfile.TemporaryDirectory() as tmp:
            configs, marker = self._configs(tmp)
            result, _n, verdict, files, lc_hash = self._run(
                FakeDataSource(), configs)
            self.assertEqual(result.run.final_verdict,
                             "CANDIDATE")
            # The tool ran (marker) and its result is in the
            # extra evidence — inconclusive, report-only.
            self.assertTrue(os.path.exists(marker))
            tools = result.extra_evidence["external_tools"]
            self.assertEqual(tools["latte"]["status"],
                             "inconclusive")
            self.assertEqual(tools["latte"]["tool_version"],
                             "1.0.21")
            raw = result.extra_evidence["external_tools_raw"]
            self.assertEqual(raw["latte"]["status"], "completed")
            # The tool input files were written + hashed.
            self.assertIn("tool_lc.npz", files)
            self.assertIn("stage0_census.json", files)
            self.assertEqual(
                tools["latte"]["input_hashes"]["lightcurve"],
                lc_hash)
            # The tool result is evidence only: it is NOT in
            # the verdict's stages (it never feeds aggregation).
            self.assertNotIn("latte", verdict["stages"])

    def test_tools_skipped_after_cheap_kill(self):
        with tempfile.TemporaryDirectory() as tmp:
            configs, marker = self._configs(tmp)
            result, _n, _v, _f, _h = self._run(
                FakeDataSource(discovery_mode="artifact"),
                configs)
            self.assertEqual(result.run.final_verdict,
                             "REFUTED")
            self.assertTrue(result.cheap_kill)
            self.assertFalse(os.path.exists(marker))
            self.assertNotIn("external_tools",
                             result.extra_evidence)

    def test_tools_skipped_after_pass2_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            configs, marker = self._configs(tmp)
            result, _n, _v, _f, _h = self._run(
                FakeDataSource(diffimg_on_target=False),
                configs)
            self.assertEqual(result.run.final_verdict, "BLEND")
            self.assertFalse(os.path.exists(marker))
            self.assertNotIn("external_tools",
                             result.extra_evidence)

    def test_missing_venv_is_unmeasured_verdict_unaffected(self):
        with tempfile.TemporaryDirectory() as tmp:
            configs, _marker = self._configs(
                tmp, python="/nonexistent/python3.12")
            result, _n, _v, _f, _h = self._run(
                FakeDataSource(), configs)
            self.assertEqual(result.run.final_verdict,
                             "CANDIDATE")
            latte = result.extra_evidence["external_tools"][
                "latte"]
            self.assertEqual(latte["status"], "unmeasured")
            self.assertEqual(latte["execution_status"], "error")
            self.assertIn("missing_venv", latte["reason"])

    def test_both_tools_run_on_clean_planet(self):
        with tempfile.TemporaryDirectory() as tmp:
            configs, latte_marker, tri_marker = (
                self._both_configs(tmp))
            result, _n, _v, _f, _h = self._run(
                FakeDataSource(), configs)
            self.assertEqual(result.run.final_verdict,
                             "CANDIDATE")
            self.assertTrue(os.path.exists(latte_marker))
            self.assertTrue(os.path.exists(tri_marker))
            tools = result.extra_evidence["external_tools"]
            self.assertEqual(set(tools),
                             {"latte", "triceratops"})
            # The TRICERATOPS result is policy-mapped under
            # the REAL default policy (external_tools_v1):
            # FPP 0.0032 / NFPP 0.0008 clear the provisional
            # validation bars -> pass. It is still evidence
            # only (not in the verdict's stages).
            tri = tools["triceratops"]
            self.assertEqual(tri["status"], "pass")
            self.assertEqual(tri["value"], 0.0032)
            self.assertEqual(tri["threshold"], 0.015)
            raw = result.extra_evidence["external_tools_raw"]
            # The fake's light curve is QLP (KSPSAP): not
            # dilution-corrected.
            self.assertFalse(
                raw["triceratops"]["metrics"]
                ["dilution_corrected"])

    def test_missing_census_field_skips_tool(self):
        with tempfile.TemporaryDirectory() as tmp:
            configs, marker = self._configs(tmp)
            result, _n, _v, _f, _h = self._run(
                FakeDataSource(census=_census(drop_teff=True)),
                configs)
            # The run completes (the planet still promotes);
            # the tool is skipped with the error recorded.
            self.assertEqual(result.run.final_verdict,
                             "CANDIDATE")
            self.assertFalse(os.path.exists(marker))
            self.assertIn("Teff",
                          result.extra_evidence["latte_error"])
            self.assertNotIn("external_tools",
                             result.extra_evidence)


class TestExternalToolSections(unittest.TestCase):

    def test_sections_and_hashes(self):
        with tempfile.TemporaryDirectory() as tmp:
            t, f = _stitched()
            census = _census()
            sections, ffi_mode = external_tool_sections(
                "999999999", census["target"], P_BOX, T0_BOX,
                DUR_BOX * 24, 1.0, t, f, [96, 97, 98], "qlp",
                census, tmp)
            self.assertEqual(sections["target"]["tmag"], 10.25)
            self.assertEqual(sections["target"]["teff_k"],
                             5000.0)
            self.assertEqual(sections["signal"]["depth_frac"],
                             0.01)
            self.assertGreater(sections["signal"]["n_transits"],
                               10)
            self.assertEqual(sections["lightcurve"]["sectors"],
                             [96, 97, 98])
            self.assertAlmostEqual(
                sections["lightcurve"]["cadence_s"], 600.0)
            self.assertEqual(
                sections["neighbours"]["radius_arcsec"], 180.0)
            # QLP is not SPOC 2-minute data -> FFI mode.
            self.assertTrue(ffi_mode)
            # The files exist and the hashes match their bytes.
            for key, name in (("lightcurve", "tool_lc.npz"),
                              ("neighbours",
                               "stage0_census.json")):
                path = sections[key]["path"]
                self.assertTrue(os.path.exists(path), name)
                digest = hashlib.sha256(
                    open(path, "rb").read()).hexdigest()
                self.assertEqual(sections[key]["input_hash"],
                                 digest)

    def test_spoc_is_not_ffi_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            t, f = _stitched()
            _sections, ffi_mode = external_tool_sections(
                "999999999", _census()["target"], P_BOX, T0_BOX,
                DUR_BOX * 24, 1.0, t, f, [96], "spoc",
                _census(), tmp)
            self.assertFalse(ffi_mode)

    def test_census_json_written_when_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            t, f = _stitched()
            sections, _ffi = external_tool_sections(
                "999999999", _census()["target"], P_BOX, T0_BOX,
                DUR_BOX * 24, 1.0, t, f, [96], "qlp",
                _census(), tmp)
            # The helper wrote it from the census dict.
            on_disk = json.load(open(
                sections["neighbours"]["path"]))
            self.assertEqual(on_disk["target"]["Tmag"], 10.25)

    def test_missing_teff_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            t, f = _stitched()
            target = _census(drop_teff=True)["target"]
            with self.assertRaises(ValueError):
                external_tool_sections(
                    "999999999", target, P_BOX, T0_BOX,
                    DUR_BOX * 24, 1.0, t, f, [96], "qlp",
                    _census(drop_teff=True), tmp)


class TestPolicyLoader(unittest.TestCase):

    def test_loads_real_policy(self):
        from calibration import profile_sha256
        configs = load_external_tool_configs()
        self.assertEqual(set(configs), {"latte", "triceratops"})
        latte = configs["latte"]
        self.assertEqual(latte.tool_version, "1.0.21")
        self.assertEqual(latte.seed, 20261114)
        self.assertEqual(latte.timeout_s, 1800)
        self.assertEqual(latte.memory_mb, 2048)
        self.assertIn("/Volumes/NVME/", latte.python)
        self.assertEqual(latte.config_hash,
                         profile_sha256("external_tools_v1"))
        # The LATTE wrapper exists in-repo (the TRICERATOPS
        # wrapper lands in 2C).
        self.assertTrue(os.path.exists(latte.wrapper))
        self.assertTrue(configs["triceratops"].wrapper.endswith(
            "run_triceratops.py"))


if __name__ == "__main__":
    unittest.main()
