"""Injection campaign at scale (Phase 3, P3-10) -- offline tests.

No MAST, no real FITS: periods/splits/labels/effective-n/resume
are pure functions of the committed definition, and the one
end-to-end runs inject+screen on a synthetic FITS (synth_fits).
"""
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np  # noqa: E402

import bulk_screen as bs  # noqa: E402
from bulk.inject_campaign import (GRID_PERIODS, RECOVERY_TOL,  # noqa: E402
                                  assign_split, check_recovery,
                                  definition_sha,
                                  effective_n_summary, host_out_path,
                                  host_rng, inject_eb,
                                  inject_flagged_dip, inject_sinusoid,
                                  inject_trial, load_definition,
                                  plan_trials, resolve_hosts,
                                  run_host,
                                  sample_period_loguniform,
                                  validate_definition)
from bulk.inject_real_s96 import load_real_fits  # noqa: E402
from synth_fits import make_qlp_fits  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DEFINITION_PATH = ROOT / "bulk" / "inject_campaign_definition.json"


def _load():
    return load_definition(DEFINITION_PATH)


class TestCampaignDefinition(unittest.TestCase):
    def test_definition_loads_and_validates(self):
        d = _load()
        self.assertEqual(d["calibration"], "bulk_v3")
        self.assertEqual(d["holdout_sector"], 97)
        self.assertEqual(d["locked_sector"], 98)
        self.assertEqual(len(d["trial_templates"]), 13)

    def test_expected_counts_match_templates(self):
        d = _load()
        n_hosts = sum(d["inject_sectors"].values())
        self.assertEqual(n_hosts, 120)
        self.assertGreaterEqual(n_hosts, 100)
        kinds = [t["kind"] for t in d["trial_templates"]]
        self.assertEqual(kinds.count("planet"), 8)
        self.assertEqual(kinds.count("pricing_13p2"), 1)
        self.assertEqual(kinds.count("eb"), 2)
        self.assertEqual(kinds.count("sinusoid"), 1)
        self.assertEqual(kinds.count("flagged_dip"), 1)
        positives = (kinds.count("planet")
                     + kinds.count("pricing_13p2")) * n_hosts
        self.assertEqual(positives, 1080)
        self.assertEqual(len(kinds) * n_hosts, 1560)
        self.assertEqual(d["expected_counts"]["planet_like_positives"],
                         1080)
        self.assertEqual(d["expected_counts"]["n_trials"], 1560)

    def test_s98_and_s97_rejected_as_inject_sectors(self):
        for bad in (97, 98):
            d = _load()
            d["inject_sectors"] = {str(bad): 5}
            with self.assertRaises(ValueError):
                validate_definition(d)

    def test_wrong_calibration_rejected(self):
        d = _load()
        d["calibration"] = "bulk_v2"
        with self.assertRaises(ValueError):
            validate_definition(d)

    def test_inconclusive_label_rejected(self):
        d = _load()
        d["labels"]["by_kind"]["planet"]["fine"] = "INCONCLUSIVE"
        with self.assertRaises(ValueError):
            validate_definition(d)


class TestPeriodSampler(unittest.TestCase):
    def test_loguniform_bounds_respected(self):
        rng = np.random.default_rng(123)
        draws = [sample_period_loguniform(rng) for _ in range(500)]
        self.assertTrue(all(0.5 <= p <= 15.0 for p in draws))
        # And the draws actually span the range (not collapsed).
        self.assertLess(min(draws), 1.0)
        self.assertGreater(max(draws), 10.0)

    def test_seed_reproducibility(self):
        a = [sample_period_loguniform(np.random.default_rng(7))
             for _ in range(20)]
        b = [sample_period_loguniform(np.random.default_rng(7))
             for _ in range(20)]
        self.assertEqual(a, b)

    def test_no_discrete_grid_memorisation(self):
        # Draws must not be confined to the old grid periods: at
        # most a handful of 1000 draws may land within 0.1% of any
        # grid period (chance level for a continuous distribution).
        rng = np.random.default_rng(99)
        draws = np.array([sample_period_loguniform(rng)
                          for _ in range(1000)])
        near_grid = sum(
            np.min(np.abs(draws[:, None]
                          - np.array(GRID_PERIODS)[None, :])
                   / np.array(GRID_PERIODS)[None, :], axis=1) < 0.001)
        self.assertLess(near_grid, 50)

    def test_host_rng_deterministic_per_host(self):
        d = _load()
        specs_a = plan_trials(
            d, host_rng(d["master_seed"], 123456789, 96))
        specs_b = plan_trials(
            d, host_rng(d["master_seed"], 123456789, 96))
        self.assertEqual(specs_a, specs_b)
        # A different host draws different trials.
        specs_c = plan_trials(
            d, host_rng(d["master_seed"], 987654321, 96))
        self.assertNotEqual(
            [t["period_d"] for t in specs_a],
            [t["period_d"] for t in specs_c])

    def test_pricing_subset_periods_in_13p1_13p3(self):
        d = _load()
        rng = np.random.default_rng(5)
        for _ in range(20):
            specs = plan_trials(d, rng)
            p13 = [s for s in specs if s["kind"] == "pricing_13p2"]
            self.assertEqual(len(p13), 1)
            self.assertTrue(13.1 <= p13[0]["period_d"] <= 13.3)


class TestDepthGrid(unittest.TestCase):
    def test_sub_one_percent_depths_present(self):
        d = _load()
        sub = [g for g in d["depth_grid_frac"] if 0 < g < 0.01]
        self.assertEqual(sorted(sub), [0.002, 0.005, 0.008])

    def test_tier_b_regime_covered(self):
        # Planet trials span the sub-1% regime + the 1% cap; the
        # 2%/5% depths belong to the EB class only.
        d = _load()
        planet_depths = sorted({t["depth_frac"] for t in
                                d["trial_templates"]
                                if t["kind"] == "planet"})
        self.assertEqual(planet_depths, [0.002, 0.005, 0.008, 0.01])
        eb_depths = sorted({t["depth_frac"] for t in
                            d["trial_templates"] if t["kind"] == "eb"})
        self.assertEqual(eb_depths, [0.02, 0.05])


class TestSplits(unittest.TestCase):
    def test_no_tic_straddles_train_test(self):
        d = _load()
        tics = [str(100000000 + i * 7919) for i in range(200)]
        # The same TIC in two sectors gets the same split.
        for tic in tics:
            self.assertEqual(
                assign_split(tic, d["master_seed"], 0.7),
                assign_split(tic, d["master_seed"], 0.7))
        splits = {assign_split(t, d["master_seed"], 0.7)
                  for t in tics}
        self.assertEqual(splits, {"train", "test"})
        n_test = sum(1 for t in tics
                     if assign_split(t, d["master_seed"], 0.7)
                     == "test")
        # 30% test, hash-uniform: allow a wide band, not a pin.
        self.assertTrue(30 <= n_test <= 90, n_test)

    def test_holdout_sector_excluded_from_training(self):
        d = _load()
        self.assertNotIn(str(d["holdout_sector"]),
                         d["inject_sectors"])
        self.assertNotIn(str(d["locked_sector"]),
                         d["inject_sectors"])
        self.assertTrue(
            d["splits"]["holdout_sector_excluded_from_training"])

    def test_split_deterministic(self):
        self.assertEqual(assign_split("12345", 20261115, 0.7),
                         assign_split("12345", 20261115, 0.7))


class TestEffectiveN(unittest.TestCase):
    def test_hosts_are_the_independent_unit(self):
        records = [
            {"tic": "111", "trials": [{}, {}, {}]},
            {"tic": "111", "trials": [{}, {}]},  # same TIC, 2nd sector
            {"tic": "222", "trials": [{}]},
        ]
        eff = effective_n_summary(records)
        self.assertEqual(eff["n_rows"], 6)
        self.assertEqual(eff["n_host_sectors"], 3)
        self.assertEqual(eff["n_hosts"], 2)
        self.assertEqual(eff["effective_n"], 2)


class TestLabels(unittest.TestCase):
    def test_three_class_schema_valid(self):
        d = _load()
        kinds = {t["kind"] for t in d["trial_templates"]}
        by_kind = d["labels"]["by_kind"]
        self.assertEqual(set(by_kind), kinds)
        classes = {v["class"] for v in by_kind.values()}
        self.assertEqual(classes, {"planet_like", "astrophysical_fp",
                                   "instrumental_fp"})
        fine = {v["fine"] for v in by_kind.values()}
        self.assertTrue(fine <= set(d["labels"]["fine_classes"]))

    def test_inconclusive_never_labelled(self):
        d = _load()
        rng = np.random.default_rng(11)
        for _ in range(10):
            for spec in plan_trials(d, rng):
                self.assertNotEqual(spec["label_class"].lower(),
                                    "inconclusive")
                self.assertNotEqual(spec["label_fine"].lower(),
                                    "inconclusive")


class TestInjectors(unittest.TestCase):
    def test_eb_is_v_shaped_with_secondary(self):
        rng = np.random.default_rng(0)
        t = 1500.0 + np.arange(1296) * 0.5 / 24.0
        f = np.ones_like(t)
        f_inj, dur = inject_eb(t, f, 0.05, 5.0, 1502.0,
                               odd_even_ratio=0.5,
                               secondary_frac=0.3)
        self.assertGreater(dur, 0)
        # Centre of a primary transit is the deepest point...
        centre = np.argmin(np.abs(t - 1502.0))
        self.assertAlmostEqual(f_inj[centre], 0.95, places=6)
        # ...and the profile ramps (V-shaped), not flat-bottomed.
        off = np.argmin(np.abs(t - (1502.0 + dur * 0.4)))
        self.assertTrue(0.95 < f_inj[off] < 1.0)
        # Secondary eclipse at phase 0.5, 30% of primary depth.
        sec = np.argmin(np.abs(t - 1504.5))
        self.assertAlmostEqual(f_inj[sec], 1.0 - 0.05 * 0.3,
                               places=6)
        # Odd event is shallower (odd/even ratio 0.5).
        odd = np.argmin(np.abs(t - 1507.0))
        self.assertAlmostEqual(f_inj[odd], 1.0 - 0.05 * 0.5,
                               places=6)

    def test_sinusoid_varies_smoothly(self):
        t = 1500.0 + np.arange(1296) * 0.5 / 24.0
        f = np.ones_like(t)
        f_inj, dur = inject_sinusoid(t, f, 0.01, 3.0, phase_rad=0.0)
        self.assertIsNone(dur)
        self.assertAlmostEqual(f_inj.max(), 1.01, places=6)
        self.assertAlmostEqual(f_inj.min(), 0.99, places=6)

    def test_flagged_dip_only_on_flagged_cadences(self):
        rng = np.random.default_rng(1)
        t = 1500.0 + np.arange(1296) * 0.5 / 24.0
        f = 1.0 + rng.normal(0, 0.001, len(t))
        q = np.zeros(len(t), dtype=np.int64)
        q[::3] |= (1 << 29)  # every 3rd cadence flagged bit 29
        f_inj, _ = inject_flagged_dip(t, f, q, 0.01, 5.0, 1502.0)
        unflagged = (q == 0)
        np.testing.assert_array_equal(f_inj[unflagged],
                                      f[unflagged])
        # And the dip does exist on flagged in-transit cadences.
        self.assertLess(f_inj.min(), 0.995)


class TestHostResolution(unittest.TestCase):
    def _window_cache(self, tmp):
        cache = Path(tmp) / "cache"
        (cache / "target_lists").mkdir(parents=True)
        tics = [str(200000000 + i) for i in range(500)]
        (cache / "target_lists" / "s0096_window_default.json"
         ).write_text(json.dumps({"stats": {}, "tics": tics}))
        (cache / "s0096").mkdir()
        return cache, tics

    def test_resolve_is_deterministic_and_seeded(self):
        d = _load()
        d["inject_sectors"] = {"96": 10}
        d.setdefault("host_selection", {})["min_hosts"] = 1
        with tempfile.TemporaryDirectory() as tmp:
            cache, _ = self._window_cache(tmp)
            # Fake the FITS files so nothing is "missing".
            for h in json.loads(
                    (cache / "target_lists"
                     / "s0096_window_default.json").read_text())["tics"]:
                (cache / "s0096" / f"{h}.fits").touch()
            hosts1, missing1, _ = resolve_hosts(d, cache)
            hosts2, missing2, _ = resolve_hosts(d, cache)
            self.assertEqual(hosts1, hosts2)
            self.assertEqual(missing1, missing2)
            self.assertEqual(len(hosts1), 10)
            self.assertEqual(missing1, [])
            self.assertEqual([h["tic"] for h in hosts1],
                             sorted([h["tic"] for h in hosts1],
                                    key=int))

    def test_missing_fits_excluded_and_recorded(self):
        d = _load()
        d["inject_sectors"] = {"96": 10}
        # min_hosts 0: this test exercises the missing-file path,
        # not the scale floor (which refuses 0 hosts, correctly).
        d.setdefault("host_selection", {})["min_hosts"] = 0
        with tempfile.TemporaryDirectory() as tmp:
            cache, _ = self._window_cache(tmp)
            hosts, missing, _ = resolve_hosts(d, cache)
            self.assertEqual(hosts, [])
            self.assertEqual(len(missing), 10)

    def test_missing_window_file_fails_loud(self):
        d = _load()
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(SystemExit):
                resolve_hosts(d, Path(tmp) / "cache")


class TestResumeAndEndToEnd(unittest.TestCase):
    def setUp(self):
        self._previous = bs.CALIBRATION_VERSION
        bs.set_calibration("bulk_v3")
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        bs.set_calibration(self._previous)
        self._tmp.cleanup()

    def _tiny_definition(self):
        """One planet trial only -- the e2e runs one real screen."""
        d = _load()
        d["trial_templates"] = [t for t in d["trial_templates"]
                                if t["kind"] == "planet"][:1]
        return d

    def _host_job(self, definition, tic="999888777"):
        cache = self.tmp / "cache" / "s0096"
        cache.mkdir(parents=True)
        # Pure-noise synthetic host; the campaign injects the signal.
        make_qlp_fits(cache / f"{tic}.fits", period_d=None, seed=42)
        out_dir = self.tmp / "out"
        return {"tic": tic, "sector": 96,
                "path": str(cache / f"{tic}.fits"),
                "definition": definition,
                "definition_sha": definition_sha(definition),
                "out_dir": str(out_dir),
                "workdir": str(out_dir / "injected")}

    def test_end_to_end_inject_screen_recover(self):
        d = self._tiny_definition()
        job = self._host_job(d)
        res = run_host(job)
        self.assertEqual(res["status"], "done")
        self.assertEqual(res["n_trials"], 1)
        out_path = host_out_path(Path(job["out_dir"]), job["tic"], 96)
        rec = json.loads(out_path.read_text())
        self.assertTrue(rec["complete"])
        self.assertEqual(rec["split"], assign_split(
            job["tic"], d["master_seed"], 0.7))
        trial = rec["trials"][0]
        self.assertEqual(trial["label_class"], "planet_like")
        # The injected 0.2% transit on 0.3% noise is a weak signal
        # and may or may not survive; the path is what this test
        # proves -- the screen ran and the recovery rule was applied
        # consistently with the screen record.
        self.assertEqual(
            trial["recovered"],
            check_recovery(trial["screen"], trial["period_d"]))
        self.assertIn(trial["screen"]["status"],
                      ("survivor", "below_floor", "demoted",
                       "recorded", "search_invalid",
                       "too_few_points", "error"))
        self.assertIsNotNone(trial["n_events_expected"])
        self.assertGreater(trial["n_events_expected"], 0)

    def test_end_to_end_strong_signal_recovers(self):
        # A deep transit on quiet noise MUST recover -- the
        # inject+screen path finds what it injected.
        d = self._tiny_definition()
        d["trial_templates"][0] = dict(d["trial_templates"][0],
                                       depth_frac=0.01)
        cache = self.tmp / "cache" / "s0096"
        cache.mkdir(parents=True)
        # 1% depth on the default 0.3% noise (~3 sigma per point):
        # deep enough to recover, shallow enough to survive the
        # screen's own 5-sigma MAD clip (1% on 0.1% noise would be
        # clipped as outliers before BLS ever sees it).
        make_qlp_fits(cache / "999888777.fits", period_d=None,
                      seed=42)
        out_dir = self.tmp / "out"
        job = {"tic": "999888777", "sector": 96,
               "path": str(cache / "999888777.fits"),
               "definition": d,
               "definition_sha": definition_sha(d),
               "out_dir": str(out_dir),
               "workdir": str(out_dir / "injected")}
        res = run_host(job)
        self.assertEqual(res["status"], "done")
        rec = json.loads(host_out_path(
            out_dir, "999888777", 96).read_text())
        trial = rec["trials"][0]
        self.assertTrue(trial["recovered"], trial["screen"])
        self.assertEqual(trial["screen"]["status"], "survivor")
        self.assertLess(
            abs(trial["screen"]["period_days"] - trial["period_d"])
            / trial["period_d"], RECOVERY_TOL)

    def test_resume_skips_completed_host(self):
        d = self._tiny_definition()
        job = self._host_job(d)
        res1 = run_host(job)
        self.assertEqual(res1["status"], "done")
        out_path = host_out_path(Path(job["out_dir"]), job["tic"], 96)
        before = out_path.read_bytes()
        res2 = run_host(job)
        self.assertEqual(res2["status"], "skipped")
        self.assertEqual(out_path.read_bytes(), before)

    def test_resume_reruns_on_definition_change(self):
        d = self._tiny_definition()
        job = self._host_job(d)
        self.assertEqual(run_host(job)["status"], "done")
        d2 = copy.deepcopy(d)
        d2["trial_templates"][0] = dict(d2["trial_templates"][0],
                                        depth_frac=0.005)
        job2 = dict(job, definition=d2,
                    definition_sha=definition_sha(d2))
        res = run_host(job2)
        self.assertEqual(res["status"], "done")
        rec = json.loads(host_out_path(
            Path(job["out_dir"]), job["tic"], 96).read_text())
        self.assertEqual(rec["trials"][0]["depth_frac"], 0.005)


if __name__ == "__main__":
    unittest.main()
