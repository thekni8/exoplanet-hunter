"""Tests for the ELIGFIX flag bypass (ELIGFIX-20261121, RATIFIED
2026-11-22; adoption list E1-E10).

The defect (M2NULL zero-compute section (a)): the P4-3 eligibility
pre-filter (depth > 1% OR status survivor) ran BEFORE the mask gate
in the stitched path, so shallow demoted EB-flagged records never
reached the gate -- 1,065/1,552 flagged records (68.6%) starved,
across 890 trials. E1 adds a third disjunct (EB flag); E2 puts it
in ONE shared predicate (bulk/k2_prototype.py:mask_eligibility)
called by both the p43 null leg and the shared campaign helper's
fresh path, frozen path OUT; E3 makes the bypass active only when
MASK_GATE_ENABLED (frozen profiles reproduce bit-identically) and
adds an `eligible_via` field written on a record only when the
bypass fires (the auditable diff).

Offline: synthetic arrays and a verbatim fixture only, no
downloads, no Mac, no campaign. The null-leg end-to-end test runs
one synthetic pure-noise host through run_host_null_p43 (the N6
pattern) and cross-checks every per-sector record against the
predicate -- relational assertions, so whatever noise peaks the
screen finds, the test holds.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import bulk_screen as bs  # noqa: E402
from bulk import k2_prototype as k2  # noqa: E402
from bulk import oracle_run as orc  # noqa: E402
from bulk import p43_run as p43run  # noqa: E402
from synth_fits import make_qlp_fits  # noqa: E402

CADENCE_D = 1.0 / 48.0

EB_FLAGS = ("ODD_EVEN_EB", "DEPTH_EB", "DURATION_EB",
            "SECONDARY_EB", "HARMONIC_P2_SUSPECT",
            "HARMONIC_P3_SUSPECT")


def _synth_multi(t0, n, signals, sigma, rng):
    """t, f, q with several box signals.

    signals is a list of (period, epoch, depth, duration)."""
    t = t0 + CADENCE_D * np.arange(n)
    f = 1.0 + rng.normal(0.0, sigma, n)
    q = np.zeros(n, dtype=int)
    for (period, epoch, depth, duration) in signals:
        k_min = int(np.ceil((t[0] - epoch) / period))
        k_max = int(np.floor((t[-1] - epoch) / period))
        for k in range(k_min, k_max + 1):
            tc = epoch + k * period
            m = np.abs(t - tc) <= duration / 2.0
            f[m] -= depth
    return t, f, q


def _sector_with_3d_signal():
    """Synthetic sector with a 0.5% signal at 3.0 d (the
    TestFreshPathUnchanged setup): the helper's fresh path can
    estimate an ephemeris at the seed period."""
    rng = np.random.default_rng(14)
    t, f, q = _synth_multi(
        3800.0, 1300, [(3.0, 3801.7, 0.005, 0.12)], 0.003, rng)
    t_p, f_p = orc.preprocess_arrays(t, f, q)
    return t, f, q, t_p, f_p


def _old_rule(p1):
    """The pre-fix eligibility rule (P4-3, verbatim): depth > 1%
    OR status survivor. No flag clause."""
    depth = p1.get("depth_percent")
    return bool((depth is not None and depth > 1.0)
                or p1.get("status") == "survivor")


class TestMaskEligibility(unittest.TestCase):
    """The shared predicate (E1-E3), gate ON (bulk_v6)."""

    def setUp(self):
        self.previous = bs.CALIBRATION_VERSION
        bs.set_calibration("bulk_v6")

    def tearDown(self):
        bs.set_calibration(self.previous)

    def _shallow_demoted(self, flags=(), period=2.0, depth=0.5):
        return {"period_days": period, "depth_percent": depth,
                "status": "demoted", "flags": list(flags)}

    def test_each_eb_flag_bypasses(self):
        # Every observed EB flag on a shallow demoted record:
        # eligible, and ONLY via the bypass.
        for flag in EB_FLAGS:
            eligible, via = k2.mask_eligibility(
                self._shallow_demoted(flags=(flag,)))
            self.assertTrue(eligible, f"{flag} must bypass")
            self.assertEqual(via, "eb-flag", flag)
            # And the gate it now reaches allows the mask (flag
            # clause) -- the bypass routes the record to a mask,
            # not to a gated-off dead end.
            self.assertTrue(k2.mask_gate_allows(
                self._shallow_demoted(flags=(flag,))), flag)

    def test_shallow_demoted_unflagged_ineligible(self):
        # No flag, no bypass -- including long periods, where
        # the GATE would allow the mask but eligibility must
        # not (this is what keeps (a) from leaking into (b)
        # gate-first: the 2,389 unflagged P >= 13.7 d records
        # stay ineligible).
        for period in (2.0, 13.7, 14.0, 20.0):
            eligible, via = k2.mask_eligibility(
                self._shallow_demoted(period=period))
            self.assertFalse(eligible, f"P={period}")
            self.assertIsNone(via, f"P={period}")

    def test_deep_and_survivor_unchanged(self):
        # The old disjuncts keep their exact behaviour.
        eligible, via = k2.mask_eligibility(
            self._shallow_demoted(depth=1.5))
        self.assertTrue(eligible)
        self.assertEqual(via, "depth")
        rec = self._shallow_demoted()
        rec["status"] = "survivor"
        eligible, via = k2.mask_eligibility(rec)
        self.assertTrue(eligible)
        self.assertEqual(via, "survivor")
        # Exactly 1.0% is NOT deep (strictly greater).
        eligible, via = k2.mask_eligibility(
            self._shallow_demoted(depth=1.0))
        self.assertFalse(eligible)
        self.assertIsNone(via)
        # "recorded" is not a survivor.
        rec = self._shallow_demoted()
        rec["status"] = "recorded"
        self.assertFalse(k2.mask_eligibility(rec)[0])

    def test_precedence_depth_survivor_flag(self):
        # via names the disjunct that matters: "eb-flag" means
        # eligible ONLY via the bypass (the auditable diff).
        # A deep flagged record was eligible before the fix.
        eligible, via = k2.mask_eligibility(
            self._shallow_demoted(flags=("ODD_EVEN_EB",),
                                  depth=1.5))
        self.assertTrue(eligible)
        self.assertEqual(via, "depth")
        rec = self._shallow_demoted(flags=("SECONDARY_EB",))
        rec["status"] = "survivor"
        eligible, via = k2.mask_eligibility(rec)
        self.assertTrue(eligible)
        self.assertEqual(via, "survivor")

    def test_non_eb_flag_unchanged(self):
        # Only the EB family bypasses (is_eb_flag: endswith
        # "_EB" or "HARMONIC" in the name).
        for flag in ("DEPTH_TOO_SHALLOW", "TWO_EVENT_WEAK",
                     "SINGLE_EVENT", "EB_LIKE"):
            eligible, via = k2.mask_eligibility(
                self._shallow_demoted(flags=(flag,)))
            self.assertFalse(eligible, flag)
            self.assertIsNone(via, flag)

    def test_none_edges(self):
        # No record at all: ineligible (unlike the gate, which
        # fails open -- eligibility is a precondition, not the
        # mask decision).
        self.assertEqual(k2.mask_eligibility(None), (False, None))
        # Missing depth + no flags: nothing to be eligible on.
        rec = {"period_days": 2.0, "depth_percent": None,
               "status": "demoted", "flags": None}
        self.assertEqual(k2.mask_eligibility(rec), (False, None))
        # Missing depth + an EB flag: the flag alone bypasses.
        rec["flags"] = ["DEPTH_EB"]
        self.assertEqual(k2.mask_eligibility(rec),
                         (True, "eb-flag"))
        # Missing "flags" key entirely: treated as no flags.
        rec = {"period_days": 2.0, "depth_percent": 0.5,
               "status": "demoted"}
        self.assertEqual(k2.mask_eligibility(rec), (False, None))
        # Missing depth key + survivor: the survivor disjunct
        # does not need a depth.
        rec = {"period_days": 2.0, "status": "survivor"}
        self.assertEqual(k2.mask_eligibility(rec),
                         (True, "survivor"))

    def test_planet_like_survivor_gate_denies(self):
        # Shallow, unflagged, short-period survivor: eligible
        # (survivor disjunct) but the GATE denies the mask --
        # the caller records mask_gated_off, it does not mask
        # a planet-like signal.
        rec = {"period_days": 2.0, "depth_percent": 0.05,
               "status": "survivor", "flags": []}
        eligible, via = k2.mask_eligibility(rec)
        self.assertTrue(eligible)
        self.assertEqual(via, "survivor")
        self.assertFalse(k2.mask_gate_allows(rec))


class TestMaskEligibilityGateOff(unittest.TestCase):
    """E3(ii): with the gate OFF (bulk_v5, a frozen profile),
    the bypass is inert and the rule is exactly the P4-3
    rule -- v5 reproductions stay bit-identical."""

    def setUp(self):
        self.previous = bs.CALIBRATION_VERSION
        bs.set_calibration("bulk_v5")

    def tearDown(self):
        bs.set_calibration(self.previous)

    def test_bypass_inert_gate_off(self):
        for flag in EB_FLAGS:
            rec = {"period_days": 2.0, "depth_percent": 0.5,
                   "status": "demoted", "flags": [flag]}
            self.assertEqual(k2.mask_eligibility(rec),
                             (False, None), flag)

    def test_old_rule_intact_gate_off(self):
        rec = {"period_days": 2.0, "depth_percent": 1.5,
               "status": "demoted", "flags": []}
        self.assertEqual(k2.mask_eligibility(rec),
                         (True, "depth"))
        rec = {"period_days": 2.0, "depth_percent": 0.5,
               "status": "survivor", "flags": []}
        self.assertEqual(k2.mask_eligibility(rec),
                         (True, "survivor"))
        rec = {"period_days": 2.0, "depth_percent": 0.5,
               "status": "recorded", "flags": []}
        self.assertEqual(k2.mask_eligibility(rec), (False, None))


class TestGoldenMaskGate(unittest.TestCase):
    """Golden table for mask_gate_allows (E6): the ELIGFIX
    change touches eligibility, never the gate. This table
    pins the gate's behaviour so any future edit to it fails
    loudly here instead of silently changing masks."""

    def setUp(self):
        self.previous = bs.CALIBRATION_VERSION
        bs.set_calibration("bulk_v6")

    def tearDown(self):
        bs.set_calibration(self.previous)

    def test_golden_table(self):
        rows = []
        for flag in EB_FLAGS:
            rows.append((f"flag {flag} allows",
                         {"flags": [flag], "depth_percent": 0.05,
                          "period_days": 2.0}, True))
        rows += [
            ("deep allows",
             {"flags": [], "depth_percent": 1.5,
              "period_days": 2.0}, True),
            ("exactly 1.0% does not allow",
             {"flags": [], "depth_percent": 1.0,
              "period_days": 2.0}, False),
            ("period 13.69 blocks",
             {"flags": [], "depth_percent": 0.05,
              "period_days": 13.69}, False),
            ("period 13.7 allows (inclusive)",
             {"flags": [], "depth_percent": 0.05,
              "period_days": 13.7}, True),
            ("period 20.0 allows",
             {"flags": [], "depth_percent": 0.05,
              "period_days": 20.0}, True),
            ("planet-like blocks",
             {"flags": [], "depth_percent": 0.05,
              "period_days": 2.0}, False),
            ("non-EB flags block",
             {"flags": ["DEPTH_TOO_SHALLOW", "TWO_EVENT_WEAK"],
              "depth_percent": 0.05, "period_days": 2.0}, False),
            ("missing period masks (fail open)",
             {"flags": [], "depth_percent": 0.05}, True),
            ("None period masks (fail open)",
             {"flags": [], "depth_percent": 0.05,
              "period_days": None}, True),
            ("None record masks (fail open)", None, True),
            ("missing depth + short + unflagged blocks",
             {"flags": [], "depth_percent": None,
              "period_days": 2.0}, False),
            ("flagged deep long allows",
             {"flags": ["ODD_EVEN_EB"], "depth_percent": 1.5,
              "period_days": 20.0}, True),
        ]
        for label, record, expected in rows:
            self.assertEqual(k2.mask_gate_allows(record),
                             expected, label)


class TestHelperEligibility(unittest.TestCase):
    """The shared helper's fresh path (E2, second site): the
    helper delegates to the shared predicate, so its
    eligibility matches the predicate record for record."""

    def setUp(self):
        self.previous = bs.CALIBRATION_VERSION
        bs.set_calibration("bulk_v6")

    def tearDown(self):
        bs.set_calibration(self.previous)

    def _fresh(self, p1):
        _t, _f, _q, t_p, f_p = _sector_with_3d_signal()
        trial = {"recorded": {"period_days": 3.0,
                              "depth_percent": 0.5}}
        return p43run._mask_seed_and_eligibility(
            t_p, f_p, trial, p1, "fresh")

    def test_flagged_shallow_demoted_eligible_and_masked(self):
        # The defect's core case, end to end at the helper:
        # eligible via the bypass, the gate allows, and a mask
        # builds from the helper's ephemeris (the sector that
        # M2 left unmasked now gets masked).
        t, f, q, t_p, f_p = _sector_with_3d_signal()
        trial = {"recorded": {"period_days": 3.0,
                              "depth_percent": 0.5}}
        p1 = {"period_days": 3.0, "depth_percent": 0.5,
              "status": "demoted", "flags": ["DURATION_EB"]}
        out = p43run._mask_seed_and_eligibility(
            t_p, f_p, trial, p1, "fresh")
        self.assertEqual(out["seed_source"], "fresh")
        self.assertTrue(out["eligible"])
        self.assertEqual(out["reason"], "confirmed-contaminant")
        self.assertEqual(out.get("eligible_via"), "eb-flag")
        self.assertTrue(k2.mask_gate_allows(p1))
        keep, mstats = k2.build_k2_mask(
            t, f, q, out["ephemeris"], out["depth_for_mask"],
            secondary=out["secondary"],
            duty_cap=p43run.DUTY_CAP, depth_trigger=False)
        self.assertFalse(mstats["stopped"])
        # The mask drops cadences (it is a real mask, not a
        # no-op): the 3.0 d signal's transits go.
        self.assertLess(int(keep.sum()), len(t))

    def test_helper_parity_with_predicate(self):
        # Battery: helper fresh-path eligibility == predicate
        # output on every record, and eligible_via appears on
        # the seed dict exactly when the bypass fires.
        battery = [
            {"period_days": 3.0, "depth_percent": 1.5,
             "status": "demoted", "flags": []},
            {"period_days": 3.0, "depth_percent": 0.5,
             "status": "survivor", "flags": []},
            {"period_days": 3.0, "depth_percent": 0.5,
             "status": "recorded", "flags": []},
            {"period_days": 3.0, "depth_percent": 0.5,
             "status": "demoted", "flags": ["DURATION_EB"]},
            {"period_days": 3.0, "depth_percent": 1.5,
             "status": "demoted", "flags": ["ODD_EVEN_EB"]},
            {"period_days": 3.0, "depth_percent": 0.5,
             "status": "survivor", "flags": ["SECONDARY_EB"]},
            {"period_days": 3.0, "depth_percent": None,
             "status": "demoted", "flags": ["DEPTH_EB"]},
            {"period_days": 3.0, "depth_percent": None,
             "status": "recorded", "flags": []},
            {"period_days": 3.0, "depth_percent": 0.5,
             "status": "demoted", "flags": None},
            {"period_days": 3.0, "depth_percent": 0.5,
             "status": "demoted", "flags": ["TWO_EVENT_WEAK"]},
        ]
        for p1 in battery:
            eligible, via = k2.mask_eligibility(p1)
            out = self._fresh(p1)
            self.assertEqual(out["eligible"], eligible, p1)
            self.assertEqual(
                out["reason"],
                "confirmed-contaminant" if eligible
                else "not-confirmed", p1)
            self.assertEqual("eligible_via" in out,
                             via == "eb-flag", p1)
            if via == "eb-flag":
                self.assertEqual(out["eligible_via"],
                                 "eb-flag", p1)

    def test_unflagged_long_period_stays_ineligible(self):
        # The (b)-only population stays out: an unflagged
        # P >= 13.7 d record is ineligible at the helper too.
        p1 = {"period_days": 14.0, "depth_percent": 0.4,
              "status": "recorded", "flags": []}
        out = self._fresh(p1)
        self.assertFalse(out["eligible"])
        self.assertEqual(out["reason"], "not-confirmed")
        self.assertNotIn("eligible_via", out)

    def test_gate_off_helper_uses_old_rule(self):
        # Gate off: the helper's fresh path is the P4-3 rule
        # exactly, even for a flagged record.
        bs.set_calibration("bulk_v5")
        p1 = {"period_days": 3.0, "depth_percent": 0.5,
              "status": "demoted", "flags": ["DURATION_EB"]}
        out = self._fresh(p1)
        self.assertFalse(out["eligible"])
        self.assertEqual(out["reason"], "not-confirmed")
        self.assertNotIn("eligible_via", out)


class TestFrozenPathInvariance(unittest.TestCase):
    """E2: the frozen path is OUT. An EB flag on the fresh
    peak must not change the frozen path's fold test in
    either direction -- eligibility follows fold depth > 1%
    OR fold SNR >= 7.0 alone, and no eligible_via is ever
    written there."""

    def setUp(self):
        self.previous = bs.CALIBRATION_VERSION
        bs.set_calibration("bulk_v6")

    def tearDown(self):
        bs.set_calibration(self.previous)

    def test_flagged_frozen_record_confirmed_by_fold(self):
        # Contaminant present at the frozen period (2% at
        # 3.0 d) + an EB-flagged fresh peak that disagrees:
        # eligible by the FOLD test, not the flag.
        rng = np.random.default_rng(11)
        t, f, q = _synth_multi(
            3800.0, 1300,
            [(1.3, 3801.0, 0.01, 0.08),
             (3.0, 3801.7, 0.02, 0.12)],
            0.003, rng)
        t_p, f_p = orc.preprocess_arrays(t, f, q)
        trial = {"recorded": {"period_days": 3.0,
                              "depth_percent": 2.0}}
        p1 = {"period_days": 1.3, "depth_percent": 1.0,
              "status": "demoted", "flags": ["DURATION_EB"]}
        out = p43run._mask_seed_and_eligibility(
            t_p, f_p, trial, p1, "frozen")
        self.assertEqual(out["seed_source"], "frozen")
        self.assertTrue(out["eligible"])
        self.assertEqual(out["reason"], "frozen-contaminant")
        self.assertNotIn("eligible_via", out)

    def test_flagged_frozen_record_not_confirmed_by_flag(self):
        # No signal at the frozen period (pure noise + a
        # planet elsewhere) + an EB-flagged fresh peak: the
        # flag must NOT rescue it -- not confirmed, no mask.
        rng = np.random.default_rng(12)
        t, f, q = _synth_multi(
            3800.0, 1300, [(1.3, 3801.0, 0.01, 0.08)], 0.003,
            rng)
        t_p, f_p = orc.preprocess_arrays(t, f, q)
        trial = {"recorded": {"period_days": 3.7,
                              "depth_percent": 2.0}}
        p1 = {"period_days": 1.3, "depth_percent": 1.0,
              "status": "demoted", "flags": ["DURATION_EB"]}
        out = p43run._mask_seed_and_eligibility(
            t_p, f_p, trial, p1, "frozen")
        self.assertEqual(out["seed_source"], "frozen")
        self.assertFalse(out["eligible"])
        self.assertEqual(out["reason"], "frozen-not-confirmed")
        self.assertNotIn("eligible_via", out)
        self.assertLess(out["ephemeris"]["depth_est_frac"],
                        0.01)
        self.assertLess(out["ephemeris"]["snr_est"], 7.0)


class TestEligfixF2FiveReplay(unittest.TestCase):
    """Replay of the five true F-2-only trials (E6): the
    trials where F-2's carry is the ONLY thing demoting a
    would-be survivor (M2NULL zero-compute section (a)).
    Fixture: per-sector pass-1 subsets copied verbatim from
    the M2 stitched null-leg records. Decision-level replay:
    the null leg's eligibility decision IS the shared
    predicate, so applying it to the recorded pass-1 records
    replays the fix's decision on the real data without a
    re-run (the paired re-run itself is an E6 Mac gate, not
    a unit test)."""

    FIXTURE = Path(__file__).resolve().parent / "fixtures" \
        / "golden" / "eligfix_f2_five.json"

    # The eight flagged shallow demoted sectors M2 left
    # unmasked: (tic, sector). Under the fix these flip to
    # eligible via the bypass; every other sector is
    # unchanged.
    EXPECTED_FLIPS = {
        ("177258779", "95"), ("271891311", "95"),
        ("271891311", "97"), ("149036941", "96"),
        ("231810586", "96"), ("231810586", "97"),
        ("300939631", "95"), ("300939631", "96"),
    }

    @classmethod
    def setUpClass(cls):
        cls.fx = json.loads(cls.FIXTURE.read_text())

    def setUp(self):
        self.previous = bs.CALIBRATION_VERSION
        bs.set_calibration("bulk_v6")

    def tearDown(self):
        bs.set_calibration(self.previous)

    def test_fixture_shape(self):
        trials = self.fx["trials"]
        self.assertEqual(set(trials),
                         {"177258779", "271891311", "149036941",
                          "231810586", "300939631"})
        kinds = {tic: t["kind"] for tic, t in trials.items()}
        self.assertEqual(kinds,
                         {"177258779": "copy",
                          "271891311": "copy",
                          "149036941": "re-screen",
                          "231810586": "re-screen",
                          "300939631": "re-screen"})
        for tic, trial in trials.items():
            self.assertEqual(set(trial["sectors"]),
                             {"95", "96", "97"}, tic)
            self.assertEqual(trial["pass2_status"],
                             "demoted", tic)
            self.assertEqual(trial["final_rows"], 0, tic)
            for sec, s in trial["sectors"].items():
                self.assertIn("flags", s["pass1"], (tic, sec))
                self.assertIn("m2_eligible", s, (tic, sec))

    def test_old_rule_reproduces_m2(self):
        # The fixture is faithful: the pre-fix rule, applied
        # to the recorded pass-1 records, reproduces M2's
        # recorded eligibility on all 15 sectors -- including
        # the 8 flagged sectors it left ineligible (the
        # starvation, measured not hypothesised).
        starved = set()
        for tic, trial in self.fx["trials"].items():
            for sec, s in trial["sectors"].items():
                self.assertEqual(_old_rule(s["pass1"]),
                                 s["m2_eligible"], (tic, sec))
                self.assertEqual(
                    s["m2_reason"],
                    "confirmed-contaminant"
                    if s["m2_eligible"] else "not-confirmed",
                    (tic, sec))
                p1 = s["pass1"]
                if (not s["m2_eligible"] and any(
                        orc.is_eb_flag(f)
                        for f in (p1.get("flags") or []))):
                    starved.add((tic, sec))
        self.assertEqual(starved, self.EXPECTED_FLIPS)

    def test_bypass_flips_exactly_the_starved_sectors(self):
        # Under the fix, exactly the 8 starved sectors flip to
        # eligible via the bypass, the gate allows their mask,
        # and the other 7 sectors are unchanged.
        flips = set()
        for tic, trial in self.fx["trials"].items():
            for sec, s in trial["sectors"].items():
                eligible, via = k2.mask_eligibility(
                    s["pass1"])
                if eligible != s["m2_eligible"]:
                    flips.add((tic, sec))
                    self.assertTrue(eligible, (tic, sec))
                    self.assertEqual(via, "eb-flag", (tic, sec))
                    self.assertTrue(
                        k2.mask_gate_allows(s["pass1"]),
                        (tic, sec))
                else:
                    # Unchanged sectors keep their old via:
                    # depth/survivor where eligible, None
                    # where not -- never eb-flag.
                    self.assertNotEqual(via, "eb-flag",
                                        (tic, sec))
        self.assertEqual(flips, self.EXPECTED_FLIPS)

    def test_unflagged_persistent_signal_stays_ineligible(self):
        # R11: TIC 177258779's EB signal persists in the
        # UNFLAGGED s96 sector (SDE 29.1) -- the fix does not
        # touch it, which is why the 66 +/- ~2 expectation is
        # soft. The sector stays ineligible.
        s96 = self.fx["trials"]["177258779"]["sectors"]["96"]
        self.assertEqual(s96["pass1"]["flags"], [])
        self.assertFalse(s96["m2_eligible"])
        self.assertEqual(k2.mask_eligibility(s96["pass1"]),
                         (False, None))

    def test_flagged_deep_stays_via_depth(self):
        # TIC 300939631 s97 is flagged AND deep (1.30%): it
        # was eligible before the fix via depth, and the
        # bypass does not re-attribute it.
        s97 = self.fx["trials"]["300939631"]["sectors"]["97"]
        self.assertTrue(s97["m2_eligible"])
        self.assertIn("ODD_EVEN_EB", s97["pass1"]["flags"])
        self.assertEqual(k2.mask_eligibility(s97["pass1"]),
                         (True, "depth"))


class TestNullLegEligibleVia(unittest.TestCase):
    """End-to-end through the null leg (E2, first site): one
    synthetic pure-noise host through run_host_null_p43. Every
    per-sector record's eligibility, reason, eligible_via, and
    mask decision are cross-checked against the shared
    predicate + gate applied to the recorded pass-1 subset --
    so the test holds for whatever noise peaks the screen
    finds. Fails on unfixed code: the predicate does not
    exist, and no record carries eligible_via."""

    def setUp(self):
        self.previous = bs.CALIBRATION_VERSION
        bs.set_calibration("bulk_v6")

    def tearDown(self):
        bs.set_calibration(self.previous)

    def _null_job(self, tmp, tic):
        (tmp / "null-p43").mkdir(exist_ok=True)
        (tmp / "w").mkdir(exist_ok=True)
        paths = {}
        for sec, t0 in ((95, 1500.0), (96, 1527.0),
                        (97, 1554.0)):
            # String keys: the driver looks paths up by the
            # JSON-manifest key (str(sector)).
            paths[str(sec)] = str(make_qlp_fits(
                tmp / f"{tic}_s{sec:04d}.fits",
                period_d=None, depth_frac=0.008,
                t0=1502.0, t_start=t0))
        return {"tic": tic, "sectors": [95, 96, 97],
                "paths": paths, "out_dir": str(tmp),
                "workdir": str(tmp / "w"), "manifest_sha": "test",
                "calibration": "bulk_v6", "keep_fits": False}

    def test_null_leg_records_match_predicate(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            res = p43run.run_host_null_p43(
                self._null_job(tmp, "515151"))
            self.assertEqual(res["status"], "done")
            rec = json.loads(
                (tmp / "null-p43" / "515151_p43.json")
                .read_text())
            self.assertNotIn("error", rec)
            self.assertEqual(set(rec["sectors"]),
                             {"95", "96", "97"})
            for sec, s in rec["sectors"].items():
                p1 = s["pass1"]
                if p1.get("period_days") is None:
                    # No pass-1 period: the early branch --
                    # eligible False without consulting the
                    # predicate, no mask, no eligible_via.
                    self.assertFalse(s["eligible"], sec)
                    self.assertEqual(s["reason"],
                                     "no-pass1-period", sec)
                    self.assertIsNone(s["k2_mask"], sec)
                    self.assertNotIn("eligible_via", s, sec)
                    continue
                eligible, via = k2.mask_eligibility(p1)
                self.assertEqual(s["eligible"], eligible, sec)
                self.assertEqual(
                    s["reason"],
                    "confirmed-contaminant" if eligible
                    else "not-confirmed", sec)
                self.assertEqual("eligible_via" in s,
                                 via == "eb-flag", sec)
                if via == "eb-flag":
                    self.assertEqual(s["eligible_via"],
                                     "eb-flag", sec)
                # Mask invariant: a mask exists iff eligible
                # AND the gate allows; gated-off iff eligible
                # AND the gate denies.
                gate = k2.mask_gate_allows(p1)
                if eligible and gate:
                    self.assertIsNotNone(s["k2_mask"], sec)
                    self.assertNotIn("mask_gated_off", s, sec)
                elif eligible and not gate:
                    self.assertIsNone(s["k2_mask"], sec)
                    self.assertTrue(s.get("mask_gated_off"),
                                    sec)
                else:
                    self.assertIsNone(s["k2_mask"], sec)
                    self.assertNotIn("mask_gated_off", s, sec)


if __name__ == "__main__":
    unittest.main()
