"""Tests for the 4.1-10 deep-sample curve harness (Phase 4.1, Stage 4).

Offline: synthetic data only, no downloads, no Mac, no BLS
screen, no hidden_files (the real census file is NOT read --
the synthetic census below reproduces the frozen strata and
combo structure by host index, so every FREEZE section 2.3
assertion value is pinned here).

Synthetic census construction: 49 hosts with the REAL frozen
strata-by-index and combo-by-index (FREEZE section 4 V-2),
the REAL demo host TIC 234333416 at its real index 23, and
synthetic TICs elsewhere chosen so numeric order == index
order. Three TICs are 8-digit and 46 are 9-digit (as in the
real list), so lexicographic order DIFFERS from numeric order
-- the numeric-sort test is live, not vacuous.
"""

import json
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import bulk_screen as bs  # noqa: E402
from bulk import p4110_finalise as fin  # noqa: E402
from bulk import p4110_manifest as man  # noqa: E402
from bulk import p4110_null as nul  # noqa: E402
from bulk import p4110_run as run  # noqa: E402
from bulk import p4110_score as score  # noqa: E402
from bulk import p43_run  # noqa: E402

# Frozen strata + combos by host index (numeric TIC order).
STRATA_BY_INDEX = [2, 4, 2, 4, 4, 2, 2, 3, 3, 4, 2, 2, 2, 2, 2, 2,
                   2, 2, 3, 3, 4, 2, 2, 2, 3, 2, 2, 3, 4, 3, 4, 4,
                   4, 3, 4, 4, 2, 3, 2, 4, 4, 4, 4, 4, 2, 2, 4, 2, 3]
COMBOS_BY_INDEX = [
    (95, 96), (95, 96, 97, 98), (95, 96), (95, 96, 97, 98),
    (95, 96, 97, 98), (96, 97), (96, 97), (95, 97, 98),
    (95, 96, 97), (95, 96, 97, 98), (96, 97), (96, 97),
    (96, 97), (96, 97), (97, 98), (96, 97), (96, 97), (96, 97),
    (95, 96, 97), (95, 96, 97), (95, 96, 97, 98), (95, 96),
    (96, 97), (95, 96), (95, 96, 97), (97, 98), (95, 96),
    (95, 96, 97), (95, 96, 97, 98), (95, 96, 97),
    (95, 96, 97, 98), (95, 96, 97, 98), (95, 96, 97, 98),
    (95, 96, 98), (95, 96, 97, 98), (95, 96, 97, 98), (97, 98),
    (96, 97, 98), (96, 97), (95, 96, 97, 98), (95, 96, 97, 98),
    (95, 96, 97, 98), (95, 96, 97, 98), (95, 96, 97, 98),
    (96, 97), (95, 97), (95, 96, 97, 98), (96, 97), (96, 97, 98),
]
DEMO_INDEX = 23
SECTOR_BASE = {95: 2000.0, 96: 2027.0, 97: 2054.0, 98: 2081.0}


def synthetic_hosts():
    """49 census-shaped host dicts (numeric TIC order == index
    order; demo host at index 23; mixed digit lengths)."""
    hosts = []
    for i, (nsec, combo) in enumerate(
            zip(STRATA_BY_INDEX, COMBOS_BY_INDEX)):
        assert len(combo) == nsec
        if i == DEMO_INDEX:
            tic = man.DEMO_TIC
            cdpp = man.DEMO_CDPP_PPM
        elif i < 3:
            tic = str([31513988, 31531129, 50491833][i])
            cdpp = 200.0
        elif i < DEMO_INDEX:
            tic = str(110000000 + i)
            cdpp = 200.0
        else:
            tic = str(240000000 + i)
            cdpp = 200.0
        hosts.append({
            "tic": tic, "tmag": 10.5, "radius_rsun": 0.7,
            "contratio": 0.001, "sectors": list(combo),
            "n_sectors": nsec,
            "combo": "+".join(f"S{s}" for s in combo),
            "stitched_cdpp_ppm_2p39h": cdpp,
            "contratio_cut_pass": True,
        })
    assert [int(h["tic"]) for h in hosts] == sorted(
        int(h["tic"]) for h in hosts)
    return hosts


def synthetic_spans(hosts):
    spans = {}
    for h in hosts:
        spans[str(h["tic"])] = {
            str(s): [SECTOR_BASE[s], SECTOR_BASE[s] + 27.0]
            for s in h["sectors"]}
    return spans


def synthetic_manifest():
    hosts = synthetic_hosts()
    trials = man.build_trials(hosts, synthetic_spans(hosts))
    return man.assemble_manifest(hosts, trials, "synthetic",
                                 "synthetic", "synthetic.json")


class TestSelectFreshHosts(unittest.TestCase):
    def test_numeric_sort_not_lexicographic(self):
        hosts = synthetic_hosts()
        # The trap is live: lexicographic order differs.
        tics = [h["tic"] for h in hosts]
        self.assertNotEqual(sorted(tics), sorted(tics, key=int))
        # select_fresh_hosts returns NUMERIC order.
        shuffled = list(reversed(hosts))
        got, _ex, _rm = man.select_fresh_hosts(shuffled, set())
        self.assertEqual([h["tic"] for h in got], tics)

    def test_contratio_and_dev_exclusions(self):
        hosts = synthetic_hosts()
        hosts[0]["contratio_cut_pass"] = False
        dev = {hosts[1]["tic"]}
        got, excluded, removed = man.select_fresh_hosts(hosts, dev)
        self.assertEqual(len(got), 47)
        self.assertEqual([r["tic"] for r in removed],
                         [hosts[0]["tic"]])
        self.assertEqual(excluded, dev)


class TestAllocation(unittest.TestCase):
    def test_all_freeze_assertions(self):
        # assemble_manifest runs assert_manifest: TOTAL 801,
        # per-depth 200, per-period table, per-host 16/17,
        # per-stratum 362/162/276 + per-depth, P<5d @0.05% 121,
        # seeds, demo pin, trial-index order.
        m = synthetic_manifest()
        self.assertEqual(m["n_trials"], 801)
        self.assertEqual(m["n_curve_trials"], 800)
        self.assertEqual(m["n_hosts"], 49)

    def test_per_period_table_is_rotation_arithmetic(self):
        m = synthetic_manifest()
        curve = [t for t in m["trials"] if not t["is_demo"]]
        for j in range(4):
            got = [sum(1 for t in curve
                       if t["depth_idx"] == j
                       and t["period_idx"] == p)
                   for p in range(5)]
            self.assertEqual(
                got, man.EXPECTED_PER_PERIOD_PER_DEPTH[j])

    def test_completion_hosts_carry_17(self):
        m = synthetic_manifest()
        per_host = Counter(t["tic"] for t in m["trials"]
                           if not t["is_demo"])
        order = [h["tic"] for h in m["hosts"]]
        for tic in order[:16]:
            self.assertEqual(per_host[tic], 17)
        for tic in order[16:]:
            self.assertEqual(per_host[tic], 16)

    def test_seed_map_ranges(self):
        m = synthetic_manifest()
        by_depth = {}
        for t in m["trials"]:
            if t["is_demo"]:
                self.assertEqual(t["seed"], 41010801)
                continue
            by_depth.setdefault(t["depth_idx"], []).append(
                t["seed"])
        self.assertEqual(min(by_depth[0]), 41010001)
        self.assertEqual(max(by_depth[0]), 41010200)
        self.assertEqual(min(by_depth[1]), 41010201)
        self.assertEqual(max(by_depth[3]), 41010800)

    def test_epoch_drawn_from_trial_seed(self):
        m = synthetic_manifest()
        for t in m["trials"]:
            rng = np.random.default_rng(t["seed"])
            off = float(rng.uniform(0.0, t["period_d"]))
            self.assertAlmostEqual(off, t["epoch_offset_d"],
                                   places=12)

    def test_demo_pin(self):
        m = synthetic_manifest()
        demo = [t for t in m["trials"] if t["is_demo"]][0]
        self.assertEqual(demo["tic"], "234333416")
        self.assertEqual(demo["depth_frac"], 0.00046)
        self.assertEqual(demo["period_d"], 3.1827878)
        self.assertEqual(demo["trial_index"], 800)
        self.assertEqual(demo["trial_id"], "demo")

    def test_lexicographic_order_would_fail_strata(self):
        # The documented caution, verified mechanically: run the
        # rotation rule over the LEXICOGRAPHIC host order and
        # the per-stratum counts come out 362/163/275, not
        # 362/162/276 -- so assert_manifest would catch it.
        hosts = synthetic_hosts()
        lex = sorted(hosts, key=lambda h: h["tic"])
        self.assertNotEqual([h["tic"] for h in lex],
                            [h["tic"] for h in hosts])
        nsec = {h["tic"]: h["n_sectors"] for h in hosts}
        counts = Counter()
        for j in range(4):
            for h in range(49):
                dropped = (h + j) % 5
                n = 5 if 4 * j <= h <= 4 * j + 3 else 4
                counts[nsec[lex[h]["tic"]]] += n
        self.assertEqual(dict(counts), {2: 362, 3: 163, 4: 275})
        self.assertNotEqual(dict(counts), man.EXPECTED_PER_STRATUM)


class TestNullTable(unittest.TestCase):
    def test_combo_counts_sum_and_strata(self):
        total = sum(n for _c, n in nul.COMBO_COUNTS)
        self.assertEqual(total, nul.N_NULL_TRIALS)
        strata = Counter()
        for combo, n in nul.COMBO_COUNTS:
            strata[len(combo)] += n
        self.assertEqual(dict(strata), nul.EXPECTED_STRATA)

    def test_draw_is_deterministic_and_disjoint(self):
        pools = {str(s): [str(100000000 + 1000 * s + i)
                          for i in range(500)]
                 for s in (95, 96, 97, 98)}
        # Overlapping pools: every TIC in every sector's pool.
        pools = {str(s): [str(200000000 + i) for i in range(500)]
                 for s in (95, 96, 97, 98)}
        excluded = {"200000000", "200000001"}
        orig = nul.COMBO_COUNTS
        try:
            nul.COMBO_COUNTS = [((95, 96), 10), ((97, 98), 10),
                                ((95, 96, 97, 98), 10)]
            nul.EXPECTED_STRATA = {2: 20, 4: 10}
            t1, rec1 = nul.draw_nulls(pools, excluded)
            t2, _ = nul.draw_nulls(pools, excluded)
        finally:
            nul.COMBO_COUNTS = orig
            nul.EXPECTED_STRATA = {2: 3591, 3: 1633, 4: 2776}
        self.assertEqual([t["tic"] for t in t1],
                         [t["tic"] for t in t2])
        self.assertEqual(len({t["tic"] for t in t1}), 30)
        self.assertFalse({t["tic"] for t in t1} & excluded)
        # Every host is in all four sectors here, so the 2-sec
        # exact pools are empty and both 2-sec combos top up
        # from their superset pools; the 4-sec combo is exact.
        self.assertEqual(rec1["S95+S96"]["exact_drawn"], 0)
        self.assertEqual(rec1["S95+S96"]["topup_drawn"], 10)
        self.assertEqual(rec1["S97+S98"]["topup_drawn"], 10)
        self.assertEqual(
            rec1["S95+S96+S97+S98"]["exact_drawn"], 10)
        self.assertEqual(
            rec1["S95+S96+S97+S98"]["topup_drawn"], 0)


class TestMesGateOverride(unittest.TestCase):
    def setUp(self):
        self._prev = bs.CALIBRATION_VERSION

    def tearDown(self):
        bs.set_calibration(self._prev)

    def test_override_sets_tier_a_mes(self):
        bs.set_calibration("bulk_v5")
        self.assertEqual(bs.TIER_A_MES, 9.0)
        bs.set_mes_gate(7.0)
        self.assertEqual(bs.TIER_A_MES, 7.0)
        bs.set_mes_gate(8.0)
        self.assertEqual(bs.TIER_A_MES, 8.0)

    def test_out_of_range_refused(self):
        bs.set_calibration("bulk_v5")
        for bad in (6.9, 9.1, 0.0):
            with self.assertRaises(ValueError):
                bs.set_mes_gate(bad)

    def test_set_calibration_restores_profile_value(self):
        bs.set_calibration("bulk_v5")
        bs.set_mes_gate(7.0)
        bs.set_calibration("bulk_v5")
        self.assertEqual(bs.TIER_A_MES, 9.0)


class TestBuildJobsSectors(unittest.TestCase):
    def _manifest(self, sectors_by_host=None):
        m = synthetic_manifest()
        m["_sha256"] = "test-sha"
        if sectors_by_host is not None:
            m["sectors_by_host"] = sectors_by_host
        # Trim to 2 hosts for speed (the job builder only reads
        # trials + sectors_by_host).
        keep = {m["hosts"][0]["tic"], m["hosts"][1]["tic"]}
        m["trials"] = [t for t in m["trials"]
                       if t["tic"] in keep]
        return m

    def _cache(self, tmp, tics_sectors):
        cache = Path(tmp) / "cache"
        for tic, secs in tics_sectors.items():
            for sec in secs:
                d = cache / f"s{sec:04d}"
                d.mkdir(parents=True, exist_ok=True)
                (d / f"{tic}.fits").write_bytes(b"")

    def test_per_host_sectors_used(self):
        m = self._manifest()
        h0, h1 = m["hosts"][0], m["hosts"][1]
        self.assertEqual(h0["n_sectors"], 2)
        self.assertEqual(h1["n_sectors"], 4)
        with tempfile.TemporaryDirectory() as tmp:
            self._cache(tmp, {h0["tic"]: h0["sectors"],
                              h1["tic"]: h1["sectors"]})
            _s, stitched, missing = p43_run._build_jobs(
                m, Path(tmp) / "cache", Path(tmp) / "out",
                Path(tmp) / "w43", Path(tmp) / "w1", False,
                "bulk_v5")
            self.assertEqual(missing, [])
            self.assertEqual(len(stitched), 2)
            by_tic = {j["tic"]: j for j in stitched}
            self.assertEqual(by_tic[h0["tic"]]["sectors"],
                             h0["sectors"])
            self.assertEqual(by_tic[h1["tic"]]["sectors"],
                             h1["sectors"])

    def test_missing_sector_skips_host(self):
        m = self._manifest()
        h0, h1 = m["hosts"][0], m["hosts"][1]
        with tempfile.TemporaryDirectory() as tmp:
            # h1 lacks its S98 FITS.
            self._cache(tmp, {h0["tic"]: h0["sectors"],
                              h1["tic"]: [95, 96, 97]})
            single, stitched, missing = p43_run._build_jobs(
                m, Path(tmp) / "cache", Path(tmp) / "out",
                Path(tmp) / "w43", Path(tmp) / "w1", False,
                "bulk_v5")
            self.assertEqual(len(stitched), 1)
            self.assertEqual(stitched[0]["tic"], h0["tic"])
            self.assertEqual(len(single), 1)
            self.assertEqual(missing, [(h1["tic"], 98)])

    def test_default_sectors_when_no_map(self):
        m = self._manifest(sectors_by_host={})
        h0 = m["hosts"][0]
        with tempfile.TemporaryDirectory() as tmp:
            self._cache(tmp, {h0["tic"]: [95, 96, 97],
                              m["hosts"][1]["tic"]: [95, 96, 97]})
            _s, stitched, _m = p43_run._build_jobs(
                m, Path(tmp) / "cache", Path(tmp) / "out",
                Path(tmp) / "w43", Path(tmp) / "w1", False,
                "bulk_v5")
            self.assertEqual(stitched[0]["sectors"], [95, 96, 97])

    def test_original_sector_must_be_in_list(self):
        m = self._manifest()
        h0 = m["hosts"][0]
        m["sectors_by_host"][h0["tic"]] = [96, 97]  # orig is 95
        with tempfile.TemporaryDirectory() as tmp:
            self._cache(tmp, {h0["tic"]: [95, 96, 97],
                              m["hosts"][1]["tic"]: [95, 96, 97,
                                                    98]})
            with self.assertRaises(AssertionError):
                p43_run._build_jobs(
                    m, Path(tmp) / "cache", Path(tmp) / "out",
                    Path(tmp) / "w43", Path(tmp) / "w1", False,
                    "bulk_v5")

    def test_mes_gate_carried_on_jobs(self):
        m = self._manifest()
        h0, h1 = m["hosts"][0], m["hosts"][1]
        with tempfile.TemporaryDirectory() as tmp:
            self._cache(tmp, {h0["tic"]: h0["sectors"],
                              h1["tic"]: h1["sectors"]})
            single, stitched, _ = p43_run._build_jobs(
                m, Path(tmp) / "cache", Path(tmp) / "out",
                Path(tmp) / "w43", Path(tmp) / "w1", False,
                "bulk_v5", mes_gate=7.0)
            self.assertEqual(single[0]["mes_gate"], 7.0)
            self.assertEqual(stitched[0]["mes_gate"], 7.0)


class TestFinalise(unittest.TestCase):
    def _pass1_dir(self, tmp, manifest, drop=None, error=None):
        p1 = Path(tmp) / "pass1"
        (p1 / "hosts").mkdir(parents=True)
        pre_sha = "pre-sha"
        by_host = {}
        for tr in manifest["trials"]:
            by_host.setdefault((tr["tic"], tr["sector"]),
                               []).append(tr)
        for (tic, sector), trials in by_host.items():
            recs = []
            for tr in trials:
                if drop == (tic, tr["trial_id"]):
                    continue
                r = {"trial_id": tr["trial_id"], "tic": tic,
                     "sector": sector,
                     "inject_epoch_delta_d": 0.0,
                     "inject_dur_delta_d": 0.0,
                     "epoch_btjd": tr["epoch_btjd"],
                     "duration_d": tr["duration_d"],
                     "screen": {"status": "recorded",
                                "tier": None,
                                "period_days": tr["period_d"],
                                "depth_percent": 0.05,
                                "sde": 8.0, "mes_pink": 5.0,
                                "flags": [],
                                "n_events_found": 5,
                                "n_strong_events": 2,
                                "max_event_snr": 4.0},
                     "recovered": False}
                if error == (tic, tr["trial_id"]):
                    r["error"] = "boom"
                recs.append(r)
            (p1 / "hosts" / f"{tic}_s{sector:04d}.json").write_text(
                json.dumps({"tic": tic, "sector": sector,
                            "complete": True,
                            "pre_manifest_sha": pre_sha,
                            "calibration": "bulk_v5",
                            "trials": recs}))
        return p1, pre_sha

    def test_finalise_attaches_recorded(self):
        m = synthetic_manifest()
        with tempfile.TemporaryDirectory() as tmp:
            pre_path = Path(tmp) / "pre.json"
            pre_path.write_text(json.dumps(m))
            # finalise hashes the file; the pass-1 files must
            # carry that sha.
            import hashlib as _hl
            pre_sha = _hl.sha256(pre_path.read_bytes()).hexdigest()
            p1, _ = self._pass1_dir(tmp, m)
            for p in (p1 / "hosts").glob("*.json"):
                rec = json.loads(p.read_text())
                rec["pre_manifest_sha"] = pre_sha
                p.write_text(json.dumps(rec))
            out = fin.finalise(str(pre_path), str(p1))
            self.assertEqual(len(out["trials"]), 801)
            self.assertTrue(all("recorded" in t
                                for t in out["trials"]))
            self.assertEqual(out["pre_manifest_sha256"], pre_sha)

    def test_missing_pass1_record_fails(self):
        m = synthetic_manifest()
        first = m["trials"][0]
        with tempfile.TemporaryDirectory() as tmp:
            pre_path = Path(tmp) / "pre.json"
            pre_path.write_text(json.dumps(m))
            import hashlib as _hl
            pre_sha = _hl.sha256(pre_path.read_bytes()).hexdigest()
            p1, _ = self._pass1_dir(
                tmp, m, drop=(first["tic"], first["trial_id"]))
            for p in (p1 / "hosts").glob("*.json"):
                rec = json.loads(p.read_text())
                rec["pre_manifest_sha"] = pre_sha
                p.write_text(json.dumps(rec))
            with self.assertRaises(AssertionError):
                fin.finalise(str(pre_path), str(p1))


class TestValidateManifest(unittest.TestCase):
    def test_campaign_refuses_premanifest(self):
        m = synthetic_manifest()
        with self.assertRaises(SystemExit):
            run._validate_manifest(m, "campaign")

    def test_campaign_accepts_finalised(self):
        m = synthetic_manifest()
        for t in m["trials"]:
            t["recorded"] = {"period_days": t["period_d"]}
        run._validate_manifest(m, "campaign")  # no raise

    def test_null_refuses_injection_trials(self):
        m = synthetic_manifest()
        with self.assertRaises(SystemExit):
            run._validate_manifest(m, "null")


def _leg(period, mes, sde=10.0, nev=5, nst=3, status="survivor",
         tier="A"):
    return {"period_days": period, "mes_pink": mes, "sde": sde,
            "n_events": nev, "n_strong_events": nst,
            "status": status, "tier": tier}


class TestScorerRules(unittest.TestCase):
    def setUp(self):
        self._prev = bs.CALIBRATION_VERSION

    def tearDown(self):
        bs.set_calibration(self._prev)

    def test_tier_a_at_gate(self):
        b9 = score.GateBars("bulk_v5", 9.0)
        b7 = score.GateBars("bulk_v5", 7.0)
        self.assertTrue(score.tier_a_at_gate(_leg(3.0, 9.5), b9))
        self.assertFalse(score.tier_a_at_gate(_leg(3.0, 8.5), b9))
        self.assertTrue(score.tier_a_at_gate(_leg(3.0, 8.5), b7))
        self.assertFalse(score.tier_a_at_gate(_leg(3.0, 6.9), b7))
        # Demoted (EB veto) never counts, at any gate.
        self.assertFalse(score.tier_a_at_gate(
            _leg(3.0, 12.0, status="demoted"), b7))
        # Missing fields fail closed.
        self.assertFalse(score.tier_a_at_gate(
            {"period_days": 3.0}, b7))
        # Tier-B shape (too few events) is not tier-A.
        self.assertFalse(score.tier_a_at_gate(
            _leg(3.0, 12.0, nev=2), b7))
        # Weak SDE fails.
        self.assertFalse(score.tier_a_at_gate(
            _leg(3.0, 12.0, sde=6.5), b7))

    def test_leg_recovers(self):
        b = score.GateBars("bulk_v5", 9.0)
        trial = {"period_d": 3.5, "duration_d": 0.1}
        self.assertTrue(score.leg_recovers(
            _leg(3.5, 9.5), trial, False, 0.4, b, 1.0))
        # Epoch beyond one duration fails; half-duration fails
        # at tol 0.5 but passes at tol 1.0.
        self.assertFalse(score.leg_recovers(
            _leg(3.5, 9.5), trial, False, 1.01, b, 1.0))
        self.assertTrue(score.leg_recovers(
            _leg(3.5, 9.5), trial, False, 0.6, b, 1.0))
        self.assertFalse(score.leg_recovers(
            _leg(3.5, 9.5), trial, False, 0.6, b, 0.5))
        # Period outside 1% fails.
        self.assertFalse(score.leg_recovers(
            _leg(3.6, 9.5), trial, False, 0.4, b, 1.0))
        # Vetoed fails.
        self.assertFalse(score.leg_recovers(
            _leg(3.5, 9.5), trial, True, 0.4, b, 1.0))

    def test_trial_recovers_pass2_or_pass3(self):
        b = score.GateBars("bulk_v5", 9.0)
        trial = {"period_d": 3.5, "duration_d": 0.1}
        rec = {"pass2": _leg(7.0, 9.5),  # wrong period
               "alias_veto": {"vetoed": False},
               "epoch_delta_over_d": 0.1,
               "pass3": _leg(3.5, 9.5),
               "alias_veto_pass3": {"vetoed": False},
               "epoch_delta_over_d_pass3": 0.2}
        self.assertTrue(score.trial_recovers(rec, trial, b, 1.0))
        rec["pass3"] = None
        self.assertFalse(score.trial_recovers(rec, trial, b, 1.0))

    def test_null_survivor(self):
        b = score.GateBars("bulk_v5", 8.0)
        self.assertTrue(score.null_survivor_at_gate(
            {"pass2": _leg(3.0, 8.5), "pass3": None}, b))
        self.assertFalse(score.null_survivor_at_gate(
            {"pass2": _leg(3.0, 7.5), "pass3": None}, b))

    def test_intervals(self):
        lo, hi = score.wilson(50, 100)
        self.assertLess(lo, 0.5)
        self.assertGreater(hi, 0.5)
        lo, hi = score.clopper_pearson(0, 100)
        self.assertEqual(lo, 0.0)
        self.assertLess(hi, 0.05)
        lo, hi = score.clopper_pearson(100, 100)
        self.assertGreater(lo, 0.95)
        self.assertEqual(hi, 1.0)
        lo, hi = score.host_clustered_bootstrap([(10, 0)] * 5)
        self.assertEqual((lo, hi), (0.0, 0.0))
        a = score.host_clustered_bootstrap([(10, 5)] * 5)
        b = score.host_clustered_bootstrap([(10, 5)] * 5)
        self.assertEqual(a, b)  # deterministic seed


class TestScoreCampaignSynthetic(unittest.TestCase):
    def setUp(self):
        self._prev = bs.CALIBRATION_VERSION

    def tearDown(self):
        bs.set_calibration(self._prev)

    def _write_run(self, tmp, manifest):
        # Stitched leg: every trial recovered (pass2 survivor at
        # the injected period, mes 9.5). Single leg: none
        # recovered (pass2 recorded, mes 5.0).
        run_dir = Path(tmp) / "run"
        (run_dir / "hosts-p43").mkdir(parents=True)
        (run_dir / "hosts").mkdir(parents=True)
        by_host = {}
        for tr in manifest["trials"]:
            by_host.setdefault(tr["tic"], []).append(tr)
        for tic, trials in by_host.items():
            st, si = [], []
            for tr in trials:
                st.append({
                    "tic": tic, "sector": tr["sector"],
                    "trial_id": tr["trial_id"],
                    "pass2": _leg(tr["period_d"], 9.5),
                    "alias_veto": {"vetoed": False},
                    "epoch_delta_over_d": 0.2,
                    "pass3": None,
                    "alias_veto_pass3": {"vetoed": False},
                    "epoch_delta_over_d_pass3": None,
                    "final_genuine": True})
                si.append({
                    "tic": tic, "sector": tr["sector"],
                    "trial_id": tr["trial_id"],
                    "pass2": _leg(tr["period_d"], 5.0,
                                  status="recorded", tier=None),
                    "alias_veto": {"vetoed": False},
                    "epoch_delta_over_d": 0.2,
                    "pass3": None,
                    "alias_veto_pass3": {"vetoed": False},
                    "epoch_delta_over_d_pass3": None,
                    "final_genuine": False})
            (run_dir / "hosts-p43" / f"{tic}_p43.json").write_text(
                json.dumps({"tic": tic, "complete": True,
                            "trials": st}))
            (run_dir / "hosts" /
             f"{tic}_s{trials[0]['sector']:04d}.json").write_text(
                json.dumps({"tic": tic, "complete": True,
                            "trials": si}))
        return run_dir

    def test_full_curve_synthetic(self):
        m = synthetic_manifest()
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = self._write_run(tmp, m)
            bars = score.GateBars("bulk_v5", 9.0)
            curve = score.score_campaign(m, run_dir, bars, 9.0)
            st = curve["stitched"]["by_depth"]
            for _depth, entry in st.items():
                row = entry["section_0.4_one_duration"]
                self.assertEqual(row["k"], 200)
                self.assertEqual(row["rate"], 1.0)
                self.assertEqual(row["n_hosts"], 49)
            si = curve["single"]["by_depth"]
            for _depth, entry in si.items():
                row = entry["section_0.4_one_duration"]
                self.assertEqual(row["k"], 0)
            asp = curve["stitched"][
                "aspirational_0.05pct_P_lt_5d"]
            self.assertEqual(
                asp["section_0.4_one_duration"]["n"], 121)
            self.assertTrue(
                curve["stitched"]["demo"]["recovered_at_gate"])
            self.assertEqual(
                curve["stitched"]["demo"]["tic"], "234333416")
            # Nesting: all-recovered at every gate.
            for _g, counts in curve[
                    "nesting_stitched_9_8_7"].items():
                self.assertTrue(all(v == 200
                                    for v in counts.values()))

    def test_partial_scores_subset_and_full_refuses(self):
        m = synthetic_manifest()
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = self._write_run(tmp, m)
            # Keep only the first host's files (both legs).
            first_tic = m["hosts"][0]["tic"]
            for sub in ("hosts-p43", "hosts"):
                for p in (run_dir / sub).glob("*.json"):
                    if first_tic not in p.name:
                        p.unlink()
            bars = score.GateBars("bulk_v5", 9.0)
            with self.assertRaises(SystemExit):
                score.score_campaign(m, run_dir, bars, 9.0)
            curve = score.score_campaign(m, run_dir, bars, 9.0,
                                         partial=True)
            self.assertTrue(curve["partial"])
            self.assertEqual(curve["stitched"]["n_hosts"], 1)
            self.assertEqual(curve["stitched"]["n_trials"], 17)

    def test_threshold_above_run_gate_refused(self):
        m = synthetic_manifest()
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = self._write_run(tmp, m)
            bars = score.GateBars("bulk_v5", 8.0)
            with self.assertRaises(SystemExit):
                score.score_campaign(m, run_dir, bars, 7.0)

    def test_null_scoring(self):
        null_man = {"trials": [
            {"tic": str(300000000 + i), "n_sectors": 2}
            for i in range(10)]}
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            (run_dir / "null-p43").mkdir(parents=True)
            for i in range(10):
                rec = {"tic": str(300000000 + i),
                       "complete": True,
                       "pass2": _leg(3.0, 9.5 if i == 0 else 5.0),
                       "pass3": None}
                (run_dir / "null-p43" /
                 f"{300000000 + i}_p43.json").write_text(
                    json.dumps(rec))
            bars = score.GateBars("bulk_v5", 9.0)
            out = score.score_null(null_man, run_dir, bars)
            st = out["stitched"]
            self.assertEqual(st["n_false_survivors"], 1)
            self.assertEqual(st["rate_per_1000"], 100.0)


if __name__ == "__main__":
    unittest.main()
