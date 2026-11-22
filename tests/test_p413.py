"""Tests for the 4.1-3 stacked-floor measurement harness.

Offline: synthetic data only, no downloads, no Mac, no BLS
screen, no hidden_files (the real draw/manifest files are
NOT read -- the real-file verification is the allocation
verifier + the 413 gate, run on the VM, not in CI).

Covers: the draw shuffle (determinism, disjointness, slice
sizes), the manifest builder (grid, seeds, epochs, guard),
the runner's interval override, the scorer's any-stage rule
(the PIPE50-9 primary rule, incl. the pass-1-only case), and
the finaliser (recorded attachment + completeness failures).
"""
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import bulk_screen as bs  # noqa: E402
from bulk import p413_draw as draw  # noqa: E402
from bulk import p413_finalise as fin  # noqa: E402
from bulk import p413_manifest as man  # noqa: E402
from bulk import p413_run as run  # noqa: E402
from bulk import p413_score as score  # noqa: E402
from bulk.p4110_score import GateBars  # noqa: E402

SECTOR_BASE = {95: 2000.0, 96: 2027.0, 97: 2054.0, 98: 2081.0}
PREREG_TEXT = (
    "# Pre-reg (synthetic, for the guard test)\n\n"
    "| 4.1-3 stacked floor | 41030001 | 41030000\u201341032999 | "
    "P4-5 window definition, fresh | 46 | P4-5 design |\n\n"
    "### 413-SEED-20261118\n\nlog entry\n")


def synthetic_hosts(n=46):
    """n host dicts in the builder's shape, TIC-ascending
    (numeric), all 4-sector. Three TICs are 8-digit so
    lexicographic order DIFFERS from numeric order -- the
    numeric-sort test is live, not vacuous."""
    hosts = []
    for i in range(n):
        if i == 0:
            tic = "55368621"
        elif i == 1:
            tic = "29830371"
        elif i == 2:
            tic = "29831821"
        else:
            tic = str(100000000 + i)
        hosts.append({
            "tic": tic, "sectors": [95, 96, 97, 98],
            "n_sectors": 4, "combo": "S95+S96+S97+S98",
            "original_sector": 95, "draw_position": i + 1,
        })
    hosts.sort(key=lambda h: int(h["tic"]))
    return hosts


def synthetic_spans(hosts):
    return {str(h["tic"]): {str(s): [SECTOR_BASE[s],
                                     SECTOR_BASE[s] + 27.0]
                            for s in (95, 96, 97, 98)}
            for h in hosts}


def synthetic_manifest(n_hosts=46):
    hosts = synthetic_hosts(n_hosts)
    trials = man.build_trials(hosts, synthetic_spans(hosts))
    row_sha = hashlib.sha256(
        [ln for ln in PREREG_TEXT.splitlines()
         if ln.startswith("| 4.1-3 stacked floor |")][0]
        .encode()).hexdigest()
    return man.assemble_manifest(hosts, trials, "drawn-sha",
                                 "dev-sha", "drawn.json", row_sha)


def tier_a_subset(period=1.7, mes=12.0, sde=9.0, nev=5, nst=3,
                  status="survivor", tier="A"):
    return {"period_days": period, "mes_pink": mes, "sde": sde,
            "n_events": nev, "n_strong_events": nst,
            "status": status, "tier": tier,
            "t0_btjd": 2001.0}


def trial_rec(pass1=None, pass2=None, pass3=None, od1=None,
              od2=None, od3=None, veto2=False, veto3=False):
    return {
        "tic": "100000003", "sector": 95, "trial_id": "d1p1",
        "pass1": pass1, "pass2": pass2, "pass3": pass3,
        "epoch_delta_over_d_pass1": od1,
        "epoch_delta_over_d": od2,
        "epoch_delta_over_d_pass3": od3,
        "alias_veto": {"vetoed": veto2},
        "alias_veto_pass3": {"vetoed": veto3},
        "final_genuine": False,
    }


def manifest_trial(period=1.7, depth_idx=1, period_idx=1):
    return {"tic": "100000003", "sector": 95,
            "trial_id": "d1p1", "period_d": period,
            "depth_idx": depth_idx, "period_idx": period_idx,
            "epoch_btjd": 2001.0,
            "duration_d": (2.0 * period ** (1.0 / 3.0)) / 24.0,
            "depth_frac": 0.0005, "is_demo": False}


class TestDrawShuffle(unittest.TestCase):
    def test_deterministic(self):
        pool = [str(100000000 + i) for i in range(339)]
        o1, _c1, _r1, _n1 = draw.shuffle_slices(pool, 41030001)
        o2, _c2, _r2, _n2 = draw.shuffle_slices(pool, 41030001)
        self.assertEqual(o1, o2)

    def test_slices_disjoint_and_sized(self):
        pool = [str(100000000 + i) for i in range(339)]
        ordered, camp, res, null = draw.shuffle_slices(
            pool, 41030001)
        self.assertEqual(len(ordered), 339)
        self.assertEqual(len(camp), 46)
        self.assertEqual(len(res), 46)
        self.assertEqual(len(null), 247)
        self.assertEqual(camp, ordered[:46])
        self.assertEqual(res, ordered[46:92])
        self.assertEqual(null, ordered[92:])
        self.assertFalse(set(camp) & set(res))
        self.assertFalse(set(camp) & set(null))
        self.assertFalse(set(res) & set(null))

    def test_numeric_sort_before_shuffle(self):
        # Lexicographic order differs from numeric order for
        # mixed digit lengths; the shuffle input must be
        # numeric-sorted (the sort is deterministic, so two
        # differently-ordered inputs give the same shuffle).
        pool_a = ["55368621", "100000003", "29830371",
                  "100000004"]
        pool_b = list(reversed(pool_a))
        o1, _, _, _ = draw.shuffle_slices(pool_a, 41030001,
                                          n_campaign=2,
                                          n_reserve=1)
        o2, _, _, _ = draw.shuffle_slices(pool_b, 41030001,
                                          n_campaign=2,
                                          n_reserve=1)
        self.assertEqual(o1, o2)


class TestManifestBuilder(unittest.TestCase):
    def test_full_manifest_asserts(self):
        manifest = synthetic_manifest()
        self.assertEqual(len(manifest["trials"]), 1150)
        self.assertEqual(len(manifest["hosts"]), 46)
        self.assertTrue(man.assert_manifest(manifest))

    def test_host_major_order(self):
        manifest = synthetic_manifest()
        keys = [(int(t["tic"]), t["depth_idx"], t["period_idx"])
                for t in manifest["trials"]]
        self.assertEqual(keys, sorted(keys))
        # First trial: lowest TIC, depth 0, period 0.
        t0 = manifest["trials"][0]
        self.assertEqual(t0["trial_index"], 0)
        self.assertEqual(t0["seed"], 41030001)
        self.assertEqual(t0["depth_idx"], 0)
        self.assertEqual(t0["period_idx"], 0)
        # Last trial: highest TIC, depth 4, period 4.
        t_last = manifest["trials"][-1]
        self.assertEqual(t_last["trial_index"], 1149)
        self.assertEqual(t_last["seed"], 41031150)

    def test_seed_map_and_header(self):
        manifest = synthetic_manifest()
        self.assertEqual(manifest["amendment_ref"],
                         "413-SEED-20261118")
        self.assertEqual(manifest["block_bounds"],
                         [41030000, 41032999])
        self.assertEqual(manifest["trial_index_span"], [0, 1149])
        self.assertEqual(manifest["host_pool"],
                         "S95-S98_intersection_6820")
        self.assertEqual(manifest["seed_map"]["first_run"],
                         [41030001, 41031150])
        self.assertEqual(manifest["seed_map"]["re_run_reserve"],
                         [41031151, 41032300])
        self.assertEqual(manifest["seed_map"]["spare"],
                         [41032301, 41032999])
        self.assertTrue(manifest["hosts_sha256"])
        self.assertTrue(manifest["amended_row_sha256"])

    def test_epochs_from_trial_seeds(self):
        manifest = synthetic_manifest()
        for t in manifest["trials"][::101]:
            rng = np.random.default_rng(t["seed"])
            off = float(rng.uniform(0.0, t["period_d"]))
            self.assertAlmostEqual(off, t["epoch_offset_d"],
                                   places=12)

    def test_event_counts_by_interval(self):
        manifest = synthetic_manifest()
        for t in manifest["trials"]:
            by = t["n_events_expected_by_interval"]
            self.assertLessEqual(by["2"], by["3"])
            self.assertLessEqual(by["3"], by["4"])
            self.assertEqual(by["4"],
                             t["n_events_expected_stitched"])

    def test_guard_refuses_wrong_ref(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "prereg.md"
            p.write_text(PREREG_TEXT)
            with self.assertRaises(AssertionError):
                man.assert_amendment(p, "FAKE-REF", 41032999)
            with self.assertRaises(AssertionError):
                man.assert_amendment(p, "413-SEED-20261118",
                                     41032998)
            row, sha = man.assert_amendment(
                p, "413-SEED-20261118", 41032999)
            self.assertEqual(row["master"], 41030001)
            self.assertEqual((row["block_lo"], row["block_hi"]),
                             (41030000, 41032999))
            self.assertEqual(len(sha), 64)

    def test_guard_trial_index_bounds(self):
        man.assert_trial_index(0)
        man.assert_trial_index(1149)
        with self.assertRaises(AssertionError):
            man.assert_trial_index(1150)
        man.assert_trial_index(1150, burn_logged=True)
        man.assert_trial_index(2998, burn_logged=True)
        with self.assertRaises(AssertionError):
            man.assert_trial_index(2999, burn_logged=True)


class TestIntervalOverride(unittest.TestCase):
    def test_campaign_override(self):
        manifest = synthetic_manifest()
        manifest["_sha256"] = "fakesha"
        for interval, sectors in ((2, [95, 96]),
                                  (3, [95, 96, 97]),
                                  (4, [95, 96, 97, 98])):
            out = run.apply_interval(manifest, interval,
                                     "campaign")
            self.assertEqual(len(out["trials"]), 1150)
            self.assertTrue(all(
                v == sectors
                for v in out["sectors_by_host"].values()))
            self.assertEqual(out["_sha256"], "fakesha")
            # The original manifest is NOT modified.
            self.assertTrue(all(
                v == [95, 96, 97, 98]
                for v in manifest["sectors_by_host"].values()))

    def test_null_filtering(self):
        manifest = {
            "_sha256": "fakesha",
            "trials": [
                {"tic": "111", "sector": 95, "sectors": [95, 96,
                 97, 98], "intervals": [2, 3, 4],
                 "kind": "null_placeholder"},
                {"tic": "222", "sector": 95, "sectors": [95, 96],
                 "intervals": [2], "kind": "null_placeholder"},
            ],
            "sectors_by_host": {"111": [95, 96, 97, 98],
                                "222": [95, 96]},
        }
        out2 = run.apply_interval(manifest, 2, "null")
        self.assertEqual(len(out2["trials"]), 2)
        self.assertEqual(out2["sectors_by_host"]["111"],
                         [95, 96])
        out4 = run.apply_interval(manifest, 4, "null")
        self.assertEqual(len(out4["trials"]), 1)
        self.assertEqual(out4["trials"][0]["tic"], "111")
        self.assertEqual(out4["sectors_by_host"]["111"],
                         [95, 96, 97, 98])

    def test_null_missing_sector_refuses(self):
        manifest = {
            "_sha256": "fakesha",
            "trials": [
                {"tic": "222", "sector": 95, "sectors": [95, 96],
                 "intervals": [2, 3, 4],
                 "kind": "null_placeholder"},
            ],
            "sectors_by_host": {"222": [95, 96]},
        }
        with self.assertRaises(SystemExit):
            run.apply_interval(manifest, 4, "null")


class TestAnyStageScoring(unittest.TestCase):
    def setUp(self):
        bs.set_calibration("bulk_v5")
        self.bars = GateBars("bulk_v5", 9.0)

    def test_pass1_only_counts(self):
        # Pass 1 finds it (right period, epoch within one
        # duration, tier-A at gate); pass 2/3 find nothing.
        # Any-stage MUST count it (PIPE50-9b); final-only
        # MUST NOT. This is the K=2 mask case.
        rec = trial_rec(
            pass1=tier_a_subset(), od1=0.5,
            pass2=tier_a_subset(period=3.5), od2=0.1,
            pass3=None, od3=None)
        tr = manifest_trial()
        self.assertTrue(score.trial_recovers_anystage(
            rec, tr, self.bars, 1.0))
        self.assertFalse(score.trial_recovers(
            rec, tr, self.bars, 1.0))

    def test_pass1_wrong_period_does_not_count(self):
        rec = trial_rec(
            pass1=tier_a_subset(period=3.5), od1=0.1,
            pass2=None, pass3=None)
        self.assertFalse(score.trial_recovers_anystage(
            rec, manifest_trial(), self.bars, 1.0))

    def test_pass1_epoch_beyond_one_duration(self):
        rec = trial_rec(
            pass1=tier_a_subset(), od1=1.5,
            pass2=None, pass3=None)
        self.assertFalse(score.trial_recovers_anystage(
            rec, manifest_trial(), self.bars, 1.0))
        # Half-duration rule is stricter still.
        rec2 = trial_rec(
            pass1=tier_a_subset(), od1=0.7,
            pass2=None, pass3=None)
        self.assertTrue(score.trial_recovers_anystage(
            rec2, manifest_trial(), self.bars, 1.0))
        self.assertFalse(score.trial_recovers_anystage(
            rec2, manifest_trial(), self.bars, 0.5))

    def test_pass1_below_gate_does_not_count(self):
        rec = trial_rec(
            pass1=tier_a_subset(mes=8.5), od1=0.1,
            pass2=None, pass3=None)
        self.assertFalse(score.trial_recovers_anystage(
            rec, manifest_trial(), self.bars, 1.0))

    def test_pass1_demoted_does_not_count(self):
        rec = trial_rec(
            pass1=tier_a_subset(status="demoted"), od1=0.1,
            pass2=None, pass3=None)
        self.assertFalse(score.trial_recovers_anystage(
            rec, manifest_trial(), self.bars, 1.0))

    def test_pass1_missing_epoch_derived_from_t0(self):
        # 5.1 scorer half (S3, RATIFIED): the pass-1 epoch
        # delta is DERIVED from the stored t0 when the record
        # predates PIPE50-9b — the t0 is stored in every
        # record, so a missing recorded delta no longer means
        # "unmeasurable". This test formerly asserted False
        # (no derivation); the ratified rule counts the trial
        # when the derived delta is within tolerance.
        rec = trial_rec(
            pass1=tier_a_subset(), od1=None,
            pass2=None, pass3=None)
        self.assertTrue(score.trial_recovers_anystage(
            rec, manifest_trial(), self.bars, 1.0))

    def test_pass1_missing_t0_does_not_count(self):
        # The true "missing epoch" case under 5.1: no
        # recorded delta AND no stored t0 — nothing to
        # derive from, so the trial does not count.
        p1 = tier_a_subset()
        p1["t0_btjd"] = None
        rec = trial_rec(
            pass1=p1, od1=None,
            pass2=None, pass3=None)
        self.assertFalse(score.trial_recovers_anystage(
            rec, manifest_trial(), self.bars, 1.0))

    def test_final_only_still_counts(self):
        # Pass 2 finds it; pass 1 does not. Both rules count.
        rec = trial_rec(
            pass1=tier_a_subset(period=3.5), od1=0.1,
            pass2=tier_a_subset(), od2=0.2,
            pass3=None, od3=None)
        tr = manifest_trial()
        self.assertTrue(score.trial_recovers_anystage(
            rec, tr, self.bars, 1.0))
        self.assertTrue(score.trial_recovers(
            rec, tr, self.bars, 1.0))

    def test_pass2_veto_blocks_final_but_not_pass1(self):
        # The alias veto applies to pass 2/3 only; a vetoed
        # pass 2 does not block a genuine pass-1 recovery.
        rec = trial_rec(
            pass1=tier_a_subset(), od1=0.1,
            pass2=tier_a_subset(), od2=0.1, veto2=True,
            pass3=None, od3=None)
        tr = manifest_trial()
        self.assertTrue(score.trial_recovers_anystage(
            rec, tr, self.bars, 1.0))
        self.assertFalse(score.trial_recovers(
            rec, tr, self.bars, 1.0))

    def test_null_anystage_counts_pass1(self):
        rec = {"pass1": tier_a_subset(), "pass2": None,
               "pass3": None}
        self.assertTrue(score.null_survivor_anystage(
            rec, self.bars))
        self.assertFalse(score.null_survivor_finalonly(
            rec, self.bars))

    def test_null_finalonly_counts_pass2(self):
        rec = {"pass1": None,
               "pass2": tier_a_subset(), "pass3": None}
        self.assertTrue(score.null_survivor_anystage(
            rec, self.bars))
        self.assertTrue(score.null_survivor_finalonly(
            rec, self.bars))

    def test_null_below_gate_is_clean(self):
        rec = {"pass1": tier_a_subset(mes=8.0),
               "pass2": tier_a_subset(mes=7.5),
               "pass3": None}
        self.assertFalse(score.null_survivor_anystage(
            rec, self.bars))
        self.assertFalse(score.null_survivor_finalonly(
            rec, self.bars))


class TestFinalise(unittest.TestCase):
    def test_finalise_attaches_recorded(self):
        manifest = synthetic_manifest()
        with tempfile.TemporaryDirectory() as td:
            pre_path = Path(td) / "pre.json"
            pre_path.write_text(json.dumps(manifest))
            pre_sha = hashlib.sha256(
                pre_path.read_bytes()).hexdigest()
            p1_dir = Path(td) / "pass1"
            (p1_dir / "hosts").mkdir(parents=True)
            by_host = {}
            for tr in manifest["trials"]:
                by_host.setdefault((tr["tic"], tr["sector"]),
                                   []).append(tr)
            for (tic, sector), trials in by_host.items():
                recs = [{
                    "trial_id": tr["trial_id"], "tic": tic,
                    "sector": sector,
                    "inject_epoch_delta_d": 0.0,
                    "inject_dur_delta_d": 0.0,
                    "epoch_btjd": tr["epoch_btjd"],
                    "duration_d": tr["duration_d"],
                    "recovered": False,
                    "screen": {
                        "status": "rejected", "tier": None,
                        "period_days": tr["period_d"],
                        "depth_percent": 0.05, "sde": 5.0,
                        "mes_pink": 4.0, "flags": [],
                        "n_events_found": 2,
                        "n_strong_events": 1,
                        "max_event_snr": 3.0},
                } for tr in trials]
                rec = {"tic": tic, "sector": sector,
                       "complete": True,
                       "pre_manifest_sha": pre_sha,
                       "calibration": "bulk_v5", "trials": recs}
                (p1_dir / "hosts" / f"{tic}_s{sector:04d}.json"
                 ).write_text(json.dumps(rec))
            (p1_dir / "pass1_summary.json").write_text(
                json.dumps({"n_trials": 1150}))
            out = fin.finalise(str(pre_path), str(p1_dir))
            self.assertEqual(len(out["trials"]), 1150)
            self.assertTrue(all("recorded" in t
                                for t in out["trials"]))
            self.assertEqual(out["trial_index_span"], [0, 1149])
            self.assertEqual(out["pass1_recovered"]["n_trials"],
                             1150)

    def test_finalise_refuses_missing_pass1(self):
        manifest = synthetic_manifest()
        with tempfile.TemporaryDirectory() as td:
            pre_path = Path(td) / "pre.json"
            pre_path.write_text(json.dumps(manifest))
            p1_dir = Path(td) / "pass1"
            (p1_dir / "hosts").mkdir(parents=True)
            with self.assertRaises(AssertionError):
                fin.finalise(str(pre_path), str(p1_dir))


if __name__ == "__main__":
    unittest.main()
