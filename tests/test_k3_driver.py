"""Tests for the 4.1-1a production K=3 stage (bulk/k3_driver.py)
and its wiring into bulk/run_chunked.py.

Offline: synthetic QLP FITS only, no downloads, no Mac. The
end-to-end tests run the real _screen_one on synthetic curves —
they exercise the exact path a production K=3 run takes, minus
the real FITS.

The smoke-parity test (TestSmokeParity) is a SMOKE check, not
Stage 5 acceptance: it proves the driver's K=3 calls agree with
the campaign null leg on a few synthetic stars. The frozen-set
per-trial parity (69/451, zero regressions) is Stage 5's job
(PHASE41_PREREG §2.1) and is NOT claimed here.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import bulk_screen as bs  # noqa: E402
import provenance as prov  # noqa: E402
from bulk import k3_driver  # noqa: E402
from bulk import k3_run as k3run  # noqa: E402
from bulk.inject_real_s96 import write_injected_fits  # noqa: E402
from bulk.recipe import apply_overrides, load_recipe  # noqa: E402
from bulk.run_chunked import (  # noqa: E402
    _checkpoint_entry, _checkpoint_entry_status, check_conservation)
from synth_fits import make_qlp_fits, screen_job  # noqa: E402
from tests.test_resume import (  # noqa: E402
    EXPECTED_SURVIVORS, TICS, _build_workdir, _run_driver)

RECIPES = Path(__file__).resolve().parent.parent / "bulk" / "recipes"

PROV = {"run_id": "test-run", "pipeline_git_sha": "test",
        "calibration_version": {"bulk": "v5"},
        "schema_version": "1.2",
        "timestamp_utc": "2026-11-18T00:00:00+00:00"}
META = {"ra": 100.0, "dec": -65.0, "tmag": 12.0, "radius": 0.7}


def _two_signal_fits(path, seed=7):
    """Synthetic curve: a deep EB-like contaminant (2%, P=3 d)
    hiding a shallow planet (0.5%, P=5.3 d). Pass 1 finds the
    contaminant; pass 2 must find the planet's period."""
    rng = np.random.default_rng(seed)
    t = 1500.0 + np.arange(1296) * 30.0 / 1440.0
    f = 1.0 + rng.normal(0.0, 0.003, len(t))
    q = np.zeros(len(t), dtype=int)
    for period, t0, duration, depth in (
            (3.0, 1502.0, 0.12, 0.02),
            (5.3, 1501.5, 0.10, 0.005)):
        phase = ((t - t0 + 0.5 * period) % period) - 0.5 * period
        f = np.where(np.abs(phase) < duration / 2.0, f - depth, f)
    write_injected_fits(str(path), t, f, q, "KSPSAP_FLUX")
    return path


def _k3_job(path, p1, workdir, tic="424242", sector=95):
    return {"tic": tic, "sector": sector, "path": str(path),
            "pass1": p1, "meta": dict(META),
            "workdir": str(workdir), "keep_fits": False,
            "prov": dict(PROV)}


class K3Calibration(unittest.TestCase):
    """Base: run under bulk_v5, restore the previous calibration."""

    def setUp(self):
        self._previous = bs.CALIBRATION_VERSION
        bs.set_calibration("bulk_v5")

    def tearDown(self):
        bs.set_calibration(self._previous)


class TestEntryFilter(unittest.TestCase):
    def test_recorded_and_demoted_enter(self):
        hits = [{"period_days": 3.0, "status": "recorded"},
                {"period_days": 2.0, "status": "demoted"}]
        self.assertEqual(len(k3_driver.k3_entry_candidates(hits)), 2)

    def test_survivors_do_not_enter(self):
        # A pass-1 survivor is already a queue row; looking
        # behind it is multi-planet search (out of 4.1-1a scope).
        hits = [{"period_days": 3.0, "status": "survivor"}]
        self.assertEqual(k3_driver.k3_entry_candidates(hits), [])

    def test_no_period_or_below_floor_do_not_enter(self):
        hits = [{"period_days": None, "status": "recorded"},
                {"period_days": 2.0, "status": "below_floor"},
                {"period_days": 2.0, "status": "error"},
                {"period_days": 2.0, "status": "search_invalid"},
                {"status": "recorded"}]
        self.assertEqual(k3_driver.k3_entry_candidates(hits), [])


class TestRunK3Star(K3Calibration):
    def test_two_signal_rescue(self):
        # Pass 1 finds the 3 d contaminant; pass 2 finds the
        # 5.3 d planet behind it, and the emitted row carries
        # the K=3 provenance + the job's real meta.
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            fits = _two_signal_fits(base / "424242.fits")
            p1 = bs._screen_one(screen_job(fits, tic="424242",
                                           sector=95))
            self.assertEqual(p1.get("status"), "survivor")
            self.assertAlmostEqual(p1["period_days"], 3.0, places=2)
            res = k3_driver.run_k3_star(
                _k3_job(fits, p1, base / "work"))
            self.assertIsNone(res.get("error"))
            self.assertIsNone(res.get("stopped_pass"))
            p2 = res["pass2"]
            self.assertIsNotNone(p2)
            self.assertAlmostEqual(p2["period_days"], 5.3,
                                   places=1)
            # Pass-2 peak is 0.41% and not a survivor: not a
            # confirmed contaminant, so no pass 3.
            self.assertEqual(res["pass3_eligibility"]["reason"],
                             "not-confirmed-contaminant")
            self.assertIsNone(res.get("pass3"))
            rows = res["rows"]["hits"]
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["k3_pass"], 2)
            self.assertAlmostEqual(
                rows[0]["k3_masked_period_days"], 3.0, places=2)
            self.assertEqual(rows[0]["ra"], META["ra"])
            self.assertEqual(rows[0]["tmag"], META["tmag"])
            self.assertNotIn("work_item_id", rows[0])

    def test_missing_fits_is_an_error_not_a_crash(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            p1 = {"period_days": 3.0, "depth_percent": 1.5,
                  "status": "recorded"}
            job = _k3_job(base / "nope.fits", p1, base / "work")
            res = k3_driver.run_k3_star(job)
            self.assertIn("load_real_fits", res.get("error", ""))
            self.assertEqual(res["rows"]["survivors"], [])

    def test_no_pass1_period_is_an_error_not_a_crash(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            fits = base / "424242.fits"
            make_qlp_fits(fits, period_d=None, seed=1)
            p1 = {"period_days": None, "depth_percent": None,
                  "status": "below_floor"}
            res = k3_driver.run_k3_star(
                _k3_job(fits, p1, base / "work"))
            self.assertEqual(res.get("error"), "no-pass1-period")


class TestEmitRows(K3Calibration):
    def _detail(self, p2, p3=None):
        return {"tic": "424242", "sector": 95,
                "ephemeris": {"period_ref_d": 3.0},
                "k3_ephemeris": ({"period_ref_d": 5.3}
                                 if p3 is not None else None),
                "pass2": p2, "pass3": p3}

    def test_pass2_survivor_row(self):
        p2 = {"status": "survivor", "tier": "A", "period_days": 5.3,
              "t0_btjd": 1501.5, "duration_hours": 2.4,
              "depth_percent": 0.5, "sde": 12.0, "mes_pink": 10.0,
              "n_events": 4, "n_strong_events": 3,
              "max_event_snr": 8.0, "flags": []}
        rows = k3_driver.k3_emit_rows(
            self._detail(p2), dict(p2), dict(PROV), dict(META))
        self.assertEqual(len(rows["survivors"]), 1)
        self.assertEqual(len(rows["hits"]), 1)
        row = rows["survivors"][0]
        self.assertEqual(row["k3_pass"], 2)
        self.assertEqual(row["k3_masked_period_days"], 3.0)
        self.assertEqual(row["sector"], 95)

    def test_pass3_row_from_subset(self):
        p2 = {"status": "survivor", "tier": "B", "period_days": 5.3,
              "t0_btjd": 1501.5, "duration_hours": 2.4,
              "depth_percent": 1.5, "sde": 12.0, "mes_pink": 10.0,
              "n_events": 2, "n_strong_events": 2,
              "max_event_snr": 8.0, "flags": []}
        p3 = {"status": "survivor", "tier": "A", "period_days": 7.1,
              "t0_btjd": 1501.0, "duration_hours": 2.4,
              "depth_percent": 0.4, "sde": 11.0, "mes_pink": 9.5,
              "n_events": 3, "n_strong_events": 2,
              "max_event_snr": 7.0, "flags": []}
        rows = k3_driver.k3_emit_rows(
            self._detail(p2, p3), dict(p2), dict(PROV), dict(META))
        self.assertEqual(len(rows["survivors"]), 2)
        p3row = [r for r in rows["survivors"]
                 if r["k3_pass"] == 3][0]
        self.assertEqual(p3row["k3_masked_period_days"], 5.3)
        self.assertEqual(p3row["period_days"], 7.1)

    def test_below_floor_pass2_emits_nothing(self):
        p2 = {"status": "below_floor", "tier": None,
              "period_days": 5.3, "t0_btjd": 1501.5,
              "duration_hours": 2.4, "depth_percent": 0.1,
              "sde": 4.0, "flags": []}
        rows = k3_driver.k3_emit_rows(
            self._detail(p2), dict(p2), dict(PROV), dict(META))
        self.assertEqual(rows["survivors"], [])
        self.assertEqual(rows["hits"], [])


class TestSmokeParity(K3Calibration):
    """SMOKE check (not Stage 5 acceptance): the driver's K=3
    calls agree with the campaign null leg on synthetic stars —
    same pass-2/pass-3 screen subsets, same eligibility. The
    driver and the campaign share the code; this proves the
    wiring feeds it identical inputs."""

    def _compare(self, fits, tic, sector=95):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            p1 = bs._screen_one(screen_job(fits, tic=tic,
                                           sector=sector))
            driver = k3_driver.run_k3_star(
                _k3_job(fits, p1, base / "work", tic=tic,
                        sector=sector))
            (base / "null_hosts").mkdir()
            (base / "null_injected").mkdir()
            camp = k3run.run_host_null_k3({
                "tic": tic, "sector": sector,
                "path": str(fits), "out_dir": str(base),
                "workdir": str(base / "null_injected"),
                "calibration": "bulk_v5", "keep_fits": False,
                "arm": "prototype", "spans": None})
            self.assertEqual(camp["status"], "done")
            null_rec = json.loads(
                (base / "null_hosts"
                 / f"{tic}_s{sector:04d}.json").read_text())
            self.assertEqual(driver.get("pass2"),
                             null_rec.get("pass2"))
            self.assertEqual(driver.get("pass3"),
                             null_rec.get("pass3"))
            self.assertEqual(
                driver["pass3_eligibility"]["reason"],
                null_rec["pass3_eligibility"]["reason"])

    def test_two_signal_star(self):
        with tempfile.TemporaryDirectory() as d:
            fits = _two_signal_fits(Path(d) / "424242.fits")
            self._compare(fits, "424242")

    def test_single_deep_eb_star(self):
        with tempfile.TemporaryDirectory() as d:
            fits = Path(d) / "515151.fits"
            make_qlp_fits(fits, period_d=3.0, depth_frac=0.02,
                          duration_d=0.12, noise_pct=0.003, seed=11)
            self._compare(fits, "515151")


class TestSliceStage(K3Calibration):
    def _slice_dir(self, base):
        """A fake screened slice: summary + hits for 2 candidates
        (one with a cached FITS, one without) + slice CSV."""
        out = base / "chunk_00"
        out.mkdir(parents=True)
        cache = base / "cache" / "s0095"
        cache.mkdir(parents=True)
        _two_signal_fits(cache / "424242.fits")
        hits = [
            {"tic": "424242", "sector": 95, "status": "recorded",
             "period_days": 3.0, "t0_btjd": 1502.0,
             "duration_hours": 2.9, "depth_percent": 1.8,
             "sde": 40.0, "mes_pink": 5.0, "n_events": 8,
             "n_strong_events": 8, "max_event_snr": 9.0,
             "flags": [], "tier": None},
            {"tic": "999999", "sector": 95, "status": "demoted",
             "period_days": 2.0, "t0_btjd": 1501.0,
             "duration_hours": 2.4, "depth_percent": 2.5,
             "sde": 30.0, "mes_pink": 4.0, "n_events": 6,
             "n_strong_events": 6, "max_event_snr": 8.0,
             "flags": ["DEPTH_EB"], "tier": None},
            {"tic": "777777", "sector": 95, "status": "survivor",
             "period_days": 4.0, "t0_btjd": 1501.0,
             "duration_hours": 2.4, "depth_percent": 0.5,
             "sde": 15.0, "mes_pink": 10.0, "n_events": 4,
             "n_strong_events": 3, "max_event_snr": 8.0,
             "flags": [], "tier": "A"},
        ]
        with open(out / "screen_hits.jsonl", "w") as fh:
            for r in hits:
                fh.write(json.dumps(r) + "\n")
        (out / "summary.json").write_text(json.dumps(
            {"stars_searched": 3, "survivors": 1}))
        slice_csv = base / "slice_00.csv"
        slice_csv.write_text(
            "tic,ra,dec,tmag,radius\n"
            "424242,100.0,-65.0,12.0,0.7\n"
            "999999,101.0,-65.1,12.1,0.6\n"
            "777777,102.0,-65.2,12.2,0.5\n")
        return out, slice_csv, base / "cache"

    def test_stage_serial_and_idempotent(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            out, slice_csv, cache = self._slice_dir(base)
            log = []
            block = k3_driver.run_k3_slice(
                out, slice_csv=slice_csv, cache_dir=cache,
                sector=95, calibration="bulk_v5", prov=dict(PROV),
                workers=1, log=log.append)
            # 2 candidates (recorded + demoted); the survivor
            # does not enter; 1 FITS missing.
            self.assertEqual(block["n_candidates"], 2)
            self.assertEqual(block["n_entered"], 1)
            self.assertEqual(block["n_missing_fits"], 1)
            self.assertEqual(block["n_pass2_screened"], 1)
            self.assertTrue(block["enabled"])
            self.assertTrue(k3_driver.slice_k3_done(out))
            summary = json.loads((out / "summary.json").read_text())
            self.assertEqual(summary["k3"]["n_entered"], 1)
            details = [json.loads(l) for l in open(
                out / k3_driver.K3_DETAIL_FILE)]
            self.assertEqual(len(details), 2)
            missing = [r for r in details
                       if r.get("error") == "missing-fits"]
            self.assertEqual(len(missing), 1)
            # Re-run: same counts, no duplicated rows.
            block2 = k3_driver.run_k3_slice(
                out, slice_csv=slice_csv, cache_dir=cache,
                sector=95, calibration="bulk_v5", prov=dict(PROV),
                workers=1, log=log.append)
            self.assertEqual(block2["n_k3_survivors"],
                             block["n_k3_survivors"])
            self.assertEqual(block2["n_k3_hits"],
                             block["n_k3_hits"])

    def test_stage_pool(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            out, slice_csv, cache = self._slice_dir(base)
            block = k3_driver.run_k3_slice(
                out, slice_csv=slice_csv, cache_dir=cache,
                sector=95, calibration="bulk_v5", prov=dict(PROV),
                workers=2, log=lambda m: None)
            self.assertEqual(block["n_entered"], 1)
            self.assertTrue(k3_driver.slice_k3_done(out))

    def test_slice_k3_done_false_without_block(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            out = base / "chunk_00"
            out.mkdir(parents=True)
            (out / "summary.json").write_text(json.dumps(
                {"stars_searched": 3}))
            self.assertFalse(k3_driver.slice_k3_done(out))


class TestConservationK3(unittest.TestCase):
    def _slice(self):
        return {"stars_in": 4, "skipped_known": {"toi": 0,
                                                 "vsx": 0},
                "stars_after_filter": 4,
                "download": {"no_product": 0, "errors": 0},
                "stars_searched": 4,
                "screen_counts": {"survivor": 1, "recorded": 3},
                "zooniverse_known_survivors": []}

    def test_k3_bucket_balances(self):
        # 1 screened survivor + 1 K=3 survivor row, both merged.
        ok, buckets, problems = check_conservation(
            4, [self._slice()], merged_survivors=2,
            toi_removed=0, vsx_removed=0, k3_survivors=1)
        self.assertTrue(ok, msg=problems)
        self.assertEqual(buckets["survivors_k3"], 1)

    def test_k3_bucket_is_load_bearing(self):
        # Without the K=3 count the same merge fails: 1 screened
        # survivor cannot account for 2 merged rows.
        ok, _, problems = check_conservation(
            4, [self._slice()], merged_survivors=2,
            toi_removed=0, vsx_removed=0)
        self.assertFalse(ok)
        self.assertTrue(any("K=3" in p for p in problems))

    def test_k3_default_zero_preserves_k1(self):
        ok, _, problems = check_conservation(
            4, [self._slice()], merged_survivors=1,
            toi_removed=0, vsx_removed=0)
        self.assertTrue(ok, msg=problems)


class TestCheckpointK3(unittest.TestCase):
    def _slice_out(self, base):
        out = base / "chunk_00"
        out.mkdir(parents=True)
        (out / "summary.json").write_text("{}")
        (out / "survivors.jsonl").write_text("{}\n")
        (out / "screen_hits.jsonl").write_text("{}\n")
        (out / "k3_survivors.jsonl").write_text("{}\n")
        (out / "k3_screen_hits.jsonl").write_text("{}\n")
        (out / "k3_detail.jsonl").write_text("{}\n")
        return out

    def test_k3_files_hashed_and_verified(self):
        with tempfile.TemporaryDirectory() as d:
            out = self._slice_out(Path(d))
            entry = _checkpoint_entry(out, {"stars_searched": 1,
                                            "survivors": 1})
            self.assertIn("k3_files", entry)
            self.assertEqual(len(entry["k3_files"]), 3)
            self.assertEqual(
                _checkpoint_entry_status(out, entry), "ok")
            # Tamper with a k3 file: outputs-changed, like a
            # tampered pass-1 file (C-2).
            (out / "k3_survivors.jsonl").write_text("{}\n{}\n")
            self.assertEqual(
                _checkpoint_entry_status(out, entry),
                "outputs-changed")

    def test_entry_without_k3_files_verifies_ok(self):
        # Pre-K=3 entries carry no k3 key — they verify as ok
        # (the same transitional rule as pre-C-2 entries).
        with tempfile.TemporaryDirectory() as d:
            out = self._slice_out(Path(d))
            entry = _checkpoint_entry(out, {"stars_searched": 1,
                                            "survivors": 1})
            del entry["k3_files"]
            self.assertEqual(
                _checkpoint_entry_status(out, entry), "ok")


class TestRecipeK3Fingerprint(unittest.TestCase):
    def test_k3_changes_the_recipe_hash(self):
        # The resume fingerprint covers the recipe hash, so a
        # K=1 run resumed with K=3 refuses instead of silently
        # mixing K=1 and K=3 slices in one sector.
        base = load_recipe(RECIPES / "default.yaml")
        with_k3 = apply_overrides(base, {"k3": True})
        self.assertNotEqual(prov.recipe_hash(base),
                            prov.recipe_hash(with_k3))


class TestDriverK3E2E(unittest.TestCase):
    def test_k3_run_with_stub_screen(self):
        # Full driver run with --k3 behind the stub screen: no
        # cache FITS, so every candidate is missing — the run
        # still completes, the K=1 queue is unchanged, and the
        # merged summary carries the k3 block.
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            work, recipe = _build_workdir(base)
            rc, out = _run_driver(work, recipe, base / "stub.log",
                                  extra_args=("--k3",))
            self.assertEqual(rc, 0, msg=out[-2000:])
            run = work / "run_s0999"
            summary = json.loads((run / "summary.json").read_text())
            self.assertTrue(summary["k3"]["enabled"])
            self.assertEqual(summary["k3"]["n_missing_fits"], 7)
            self.assertEqual(summary["k3"]["n_entered"], 0)
            self.assertTrue(summary["conservation"]["ok"])
            survivors = [json.loads(l) for l in open(
                run / "survivors.jsonl")]
            self.assertEqual(sorted(r["tic"] for r in survivors),
                             EXPECTED_SURVIVORS)
            # Every slice carries its k3 block (merge fail-loud
            # precondition) and its k3 files.
            for i in range(3):
                chunk = run / f"chunk_{i:02d}"
                self.assertTrue(k3_driver.slice_k3_done(chunk))

    def test_k3_run_with_one_real_fits(self):
        # One recorded star gets a real synthetic two-signal
        # FITS in the cache: the stage enters it for real, and
        # the run still completes with conservation intact.
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            work, recipe = _build_workdir(base)
            # 100000001 is recorded under the stub rule (n%3=2).
            cache = work / "cache" / "s0999"
            cache.mkdir(parents=True)
            _two_signal_fits(cache / "100000001.fits")
            rc, out = _run_driver(work, recipe, base / "stub.log",
                                  extra_args=("--k3",))
            self.assertEqual(rc, 0, msg=out[-2000:])
            run = work / "run_s0999"
            summary = json.loads((run / "summary.json").read_text())
            self.assertEqual(summary["k3"]["n_entered"], 1)
            self.assertEqual(summary["k3"]["n_missing_fits"], 6)
            self.assertTrue(summary["conservation"]["ok"])

    def test_k1_default_unchanged(self):
        # No --k3: the merged summary records k3 disabled, and
        # no slice carries a k3 block.
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            work, recipe = _build_workdir(base)
            rc, out = _run_driver(work, recipe, base / "stub.log")
            self.assertEqual(rc, 0, msg=out[-2000:])
            run = work / "run_s0999"
            summary = json.loads((run / "summary.json").read_text())
            self.assertEqual(summary["k3"], {"enabled": False})
            for i in range(3):
                chunk = run / f"chunk_{i:02d}"
                self.assertFalse(k3_driver.slice_k3_done(chunk))


if __name__ == "__main__":
    unittest.main()
