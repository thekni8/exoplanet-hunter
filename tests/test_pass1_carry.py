"""Phase 5 item 5.1 (K=2 mask fix + any-stage scoring).

Unit tests for bulk/pass1_carry.py (the shared carry module),
scorer tests for the carried leg in bulk/p4110_score.py, veto
binding tests for the carried row in bulk/p43_run.py, and
driver end-to-end tests on synthetic FITS (k3_run, p43_run,
k2_run campaign + null legs).

Design reference: science-vet/phase5-vote/PHASE5_PREREG.md
section 4 (the frozen 5.1 design note, choice (A): retain
pass-1 candidates in the final list).
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import bulk_screen as bs  # noqa: E402
from bulk import k2_run as k2run  # noqa: E402
from bulk import k3_run as k3run  # noqa: E402
from bulk import oracle_run as orc  # noqa: E402
from bulk import p43_run as p43run  # noqa: E402
from bulk import p4110_score as s4110  # noqa: E402
from bulk import pass1_carry as p1c  # noqa: E402
from bulk.p4110_score import GateBars  # noqa: E402
from synth_fits import make_qlp_fits  # noqa: E402


def _p1(period=5.0, t0=1502.0, status="survivor", tier="A",
        sde=15.0, mes=12.0, n_events=5, n_strong=5,
        duration_hours=3.4, flags=None):
    """A pass-1 subset-shaped screen row (orc._subset shape)."""
    return {"period_days": period, "t0_btjd": t0,
            "status": status, "tier": tier, "sde": sde,
            "mes_pink": mes, "n_events": n_events,
            "n_strong_events": n_strong,
            "duration_hours": duration_hours,
            "flags": list(flags or [])}


def _trial(period=5.0, epoch=1502.0, duration=0.1422):
    return {"period_d": period, "epoch_btjd": epoch,
            "duration_d": duration}


class TestSameSignal(unittest.TestCase):
    def test_match(self):
        self.assertTrue(p1c.same_signal(
            5.0, 1502.0, 5.0, 1502.05, 0.1422))

    def test_period_mismatch(self):
        self.assertFalse(p1c.same_signal(
            5.1, 1502.0, 5.0, 1502.0, 0.1422))

    def test_epoch_mismatch(self):
        self.assertFalse(p1c.same_signal(
            5.0, 1502.5, 5.0, 1502.0, 0.1422))

    def test_missing_inputs(self):
        self.assertFalse(p1c.same_signal(
            5.0, None, 5.0, 1502.0, 0.1422))
        self.assertFalse(p1c.same_signal(
            None, 1502.0, 5.0, 1502.0, 0.1422))
        self.assertFalse(p1c.same_signal(
            5.0, 1502.0, 5.0, 1502.0, None))


class TestBuildCarriedRow(unittest.TestCase):
    def test_non_survivor_returns_none(self):
        row, audit = p1c.build_carried_row(
            _p1(status="demoted"))
        self.assertIsNone(row)
        self.assertEqual(audit["reason"], "pass1-not-survivor")

    def test_none_pass1_returns_none(self):
        row, audit = p1c.build_carried_row(None)
        self.assertIsNone(row)
        self.assertEqual(audit["reason"], "no-pass1-record")

    def test_survivor_copied_with_provenance(self):
        src = _p1(flags=["SOME_FLAG"])
        row, audit = p1c.build_carried_row(
            src, veto_skipped_reason="test-skip")
        self.assertIsNotNone(row)
        self.assertEqual(row["carried_from"], "pass1")
        self.assertEqual(row["period_days"], 5.0)
        self.assertEqual(row["status"], "survivor")
        # Fresh flags list: mutating the copy must not
        # mutate the stored pass-1 record.
        row["flags"].append("MUTATED")
        self.assertNotIn("MUTATED", src["flags"])
        self.assertFalse(audit["f2_demoted"])
        self.assertEqual(
            audit["alias_veto"]["skipped_reason"], "test-skip")
        self.assertFalse(audit["alias_veto"]["vetoed"])

    def test_f2_demotes_on_harmonic_eb_match(self):
        # The flagged source is a per-sector pass-1 carrying
        # an EB flag at the same period (stitched-leg case).
        flagged = orc.flagged_periods(
            [_p1(period=5.0, flags=["ODD_EVEN_EB"])])
        row, audit = p1c.build_carried_row(
            _p1(), flagged=flagged,
            veto_skipped_reason="test-skip")
        self.assertIsNotNone(row)
        self.assertEqual(row["status"], "demoted")
        self.assertIn("ODD_EVEN_EB", row["flags"])
        self.assertEqual(row["flags_carried_from"], "pass1")
        self.assertTrue(audit["f2_demoted"])
        self.assertEqual(audit["f2_flags"], ["ODD_EVEN_EB"])

    def test_f2_no_match_keeps_survivor(self):
        flagged = orc.flagged_periods(
            [_p1(period=7.3, flags=["ODD_EVEN_EB"])])
        row, audit = p1c.build_carried_row(
            _p1(), flagged=flagged,
            veto_skipped_reason="test-skip")
        self.assertEqual(row["status"], "survivor")
        self.assertFalse(audit["f2_demoted"])

    def test_alias_veto_fires_on_harmonic(self):
        # Candidate at half the reference period, coincident
        # epochs: a genuine harmonic alias of the masked
        # signal — the veto must fire.
        row, audit = p1c.build_carried_row(
            _p1(period=2.5, t0=1502.0),
            veto_ref={"period_ref_d": 5.0, "t0_est_btjd": 1502.0,
                      "mask_half_width_d": 0.5,
                      "comask_phase": None})
        self.assertIsNotNone(row)
        # The veto never changes the row's status (pass-2
        # pattern: the veto is a separate key).
        self.assertEqual(row["status"], "survivor")
        self.assertTrue(audit["alias_veto"]["vetoed"])

    def test_alias_veto_same_signal_reference_skipped(self):
        # The reference IS the same signal (the stitched
        # leg's original-sector entry is seeded from the
        # fresh pass-1 itself) — vetoing against it would
        # veto every carried row by construction.
        row, audit = p1c.build_carried_row(
            _p1(period=5.0, t0=1502.0),
            veto_ref={"period_ref_d": 5.0, "t0_est_btjd": 1502.0,
                      "mask_half_width_d": 0.5,
                      "comask_phase": None})
        self.assertFalse(audit["alias_veto"]["vetoed"])
        self.assertEqual(
            audit["alias_veto"]["skipped_reason"],
            "same-signal-as-reference")
        self.assertEqual(audit["n_veto_refs_excluded"], 1)

    def test_alias_veto_no_harmonic_kept(self):
        row, audit = p1c.build_carried_row(
            _p1(period=4.1, t0=1502.0),
            veto_ref={"period_ref_d": 5.0, "t0_est_btjd": 1502.0,
                      "mask_half_width_d": 0.5,
                      "comask_phase": None})
        self.assertFalse(audit["alias_veto"]["vetoed"])

    def test_contaminants_veto_fires(self):
        row, audit = p1c.build_carried_row(
            _p1(period=2.5, t0=1502.0),
            contaminants=[{"period_d": 5.0, "t0_btjd": 1502.0,
                           "mask_half_width_d": 0.5,
                           "comask_phase": None}])
        self.assertTrue(audit["alias_veto"]["vetoed"])
        self.assertEqual(audit["n_veto_refs_excluded"], 0)

    def test_contaminants_same_period_excluded(self):
        row, audit = p1c.build_carried_row(
            _p1(period=5.0, t0=1502.0),
            contaminants=[{"period_d": 5.0, "t0_btjd": 1502.0,
                           "mask_half_width_d": 0.5,
                           "comask_phase": None},
                          {"period_d": 4.1, "t0_btjd": 1502.0,
                           "mask_half_width_d": 0.5,
                           "comask_phase": None}])
        # The same-period reference is excluded; the other
        # is not a harmonic, so nothing vetoes.
        self.assertEqual(audit["n_veto_refs_excluded"], 1)
        self.assertFalse(audit["alias_veto"]["vetoed"])


class TestDedupeAndCounting(unittest.TestCase):
    def test_dedupe_with_pass2(self):
        self.assertEqual(
            p1c.dedupe_carried(_p1(), _p1(t0=1502.05), None,
                              0.1422),
            "pass2")

    def test_dedupe_with_pass3(self):
        self.assertEqual(
            p1c.dedupe_carried(_p1(), None, _p1(t0=1502.05),
                              0.1422),
            "pass3")

    def test_no_dedupe_different_signal(self):
        self.assertIsNone(p1c.dedupe_carried(
            _p1(), _p1(period=7.3), None, 0.1422))

    def test_no_dedupe_demoted_partner(self):
        # A demoted later row is not a final row — nothing
        # to merge with.
        self.assertIsNone(p1c.dedupe_carried(
            _p1(), _p1(status="demoted"), None, 0.1422))

    def test_count_all_three(self):
        self.assertEqual(
            p1c.count_final_rows(_p1(), _p1(period=7.3),
                                _p1(period=9.1), 0.1422), 3)

    def test_count_dedupe_subtracts_one(self):
        self.assertEqual(
            p1c.count_final_rows(_p1(), _p1(t0=1502.05), None,
                                0.1422), 1)

    def test_count_demoted_not_counted(self):
        self.assertEqual(
            p1c.count_final_rows(_p1(status="demoted"),
                                _p1(period=7.3), None, 0.1422),
            1)

    def test_count_no_carry(self):
        self.assertEqual(
            p1c.count_final_rows(None, _p1(period=7.3),
                                _p1(period=9.1), 0.1422), 2)


class TestCarriedRecoveryVerdict(unittest.TestCase):
    def test_recovered_and_genuine(self):
        rec, gen = p1c.carried_recovery_verdict(
            _p1(), {"vetoed": False}, _trial())
        self.assertTrue(rec)
        self.assertTrue(gen)

    def test_vetoed_not_recovered(self):
        rec, gen = p1c.carried_recovery_verdict(
            _p1(), {"vetoed": True}, _trial())
        self.assertFalse(rec)
        self.assertFalse(gen)

    def test_period_mismatch_not_recovered(self):
        rec, gen = p1c.carried_recovery_verdict(
            _p1(period=7.3), {"vetoed": False}, _trial())
        self.assertFalse(rec)
        self.assertFalse(gen)

    def test_epoch_beyond_half_duration_not_genuine(self):
        # t0 0.1 d off a 0.1422 d duration: within the
        # scorer's one-duration rule, beyond the runner's
        # half-duration genuine rule.
        rec, gen = p1c.carried_recovery_verdict(
            _p1(t0=1502.1), {"vetoed": False}, _trial())
        self.assertTrue(rec)
        self.assertFalse(gen)

    def test_none_row(self):
        rec, gen = p1c.carried_recovery_verdict(
            None, {"vetoed": False}, _trial())
        self.assertFalse(rec)
        self.assertFalse(gen)


class TestVetoRefFrom(unittest.TestCase):
    def test_normal(self):
        ref = p1c.veto_ref_from(
            {"period_ref_d": 5.0, "t0_est_btjd": 1502.0},
            {"mask_half_width_d": 0.5, "secondary_phase": 0.5})
        self.assertEqual(ref["period_ref_d"], 5.0)
        self.assertEqual(ref["mask_half_width_d"], 0.5)
        self.assertEqual(ref["comask_phase"], 0.5)

    def test_gated_off_no_half_width(self):
        self.assertIsNone(p1c.veto_ref_from(
            {"period_ref_d": 5.0, "t0_est_btjd": 1502.0},
            {"mask_half_width_d": None}))

    def test_no_ephemeris(self):
        self.assertIsNone(p1c.veto_ref_from(
            None, {"mask_half_width_d": 0.5}))


class TestCarriedScorer(unittest.TestCase):
    def setUp(self):
        self.bars = GateBars(calibration="bulk_v5", mes_gate=9.0)

    def _rec(self, **kw):
        rec = {"pass1": _p1(), "pass2": None, "pass3": None,
               "epoch_delta_over_d_pass1": 0.0}
        rec.update(kw)
        return rec

    def test_carried_recovers(self):
        rec = self._rec(pass1_carried=_p1(),
                        alias_veto_carried={"vetoed": False})
        self.assertTrue(
            s4110.carried_recovers(rec, _trial(), self.bars))

    def test_carried_vetoed_does_not_recover(self):
        rec = self._rec(pass1_carried=_p1(),
                        alias_veto_carried={"vetoed": True})
        self.assertFalse(
            s4110.carried_recovers(rec, _trial(), self.bars))

    def test_carried_demoted_does_not_recover(self):
        # F-2 demotion is handled by tier_a_at_gate.
        rec = self._rec(pass1_carried=_p1(status="demoted"),
                        alias_veto_carried={"vetoed": False})
        self.assertFalse(
            s4110.carried_recovers(rec, _trial(), self.bars))

    def test_carried_recovers_pre51_record_false(self):
        # No pass1_carried key: the carried leg is absent.
        self.assertFalse(
            s4110.carried_recovers(self._rec(), _trial(),
                                   self.bars))

    def test_carried_recovers_derives_delta(self):
        # No recorded pass-1 epoch delta (pre-PIPE50-9b
        # record): derived from the stored t0 — the same
        # fallback as pass1_recovers.
        rec = self._rec(pass1_carried=_p1(),
                        alias_veto_carried={"vetoed": False})
        del rec["epoch_delta_over_d_pass1"]
        self.assertTrue(
            s4110.carried_recovers(rec, _trial(), self.bars))

    def test_trial_recovers_backward_compat(self):
        # A pre-5.1 record (no pass1_carried key) scores
        # exactly as the old pass-2 OR pass-3 rule.
        rec = self._rec(pass2=_p1(period=7.3))
        self.assertFalse(
            s4110.trial_recovers(rec, _trial(), self.bars))
        rec["pass2"] = _p1()
        rec["epoch_delta_over_d"] = 0.0
        rec["alias_veto"] = {"vetoed": False}
        self.assertTrue(
            s4110.trial_recovers(rec, _trial(), self.bars))

    def test_trial_recovers_carry_only(self):
        # Pass 2/3 miss; the carried row recovers — the 5.1
        # fix in one trial.
        rec = self._rec(pass2=_p1(period=7.3),
                        pass1_carried=_p1(),
                        alias_veto_carried={"vetoed": False})
        self.assertTrue(
            s4110.trial_recovers(rec, _trial(), self.bars))

    def test_null_finalonly_carried_only(self):
        rec = {"pass1": _p1(), "pass2": None, "pass3": None,
               "pass1_carried": _p1()}
        self.assertTrue(
            s4110.null_survivor_finalonly(rec, self.bars))
        self.assertTrue(
            s4110.null_survivor_at_gate(rec, self.bars))

    def test_null_finalonly_pre51_unchanged(self):
        rec = {"pass1": _p1(), "pass2": None, "pass3": None}
        self.assertFalse(
            s4110.null_survivor_finalonly(rec, self.bars))
        rec["pass2"] = _p1()
        self.assertTrue(
            s4110.null_survivor_finalonly(rec, self.bars))

    def test_null_finalonly_carried_demoted(self):
        rec = {"pass1": _p1(), "pass2": None, "pass3": None,
               "pass1_carried": _p1(status="demoted")}
        self.assertFalse(
            s4110.null_survivor_finalonly(rec, self.bars))


class TestDerivationBitIdentity(unittest.TestCase):
    """The 5.1 scorer half derives the pass-1 epoch delta from
    the stored t0 when the record predates PIPE50-9b. The
    expected values below are hand-computed (not produced by
    the code under test): no-wrap and wrap cases."""

    def test_no_wrap(self):
        rec = {"pass1": _p1(t0=1502.1)}
        trial = _trial(epoch=1502.0, duration=0.1)
        # |1502.1 - 1502.0| / 0.1 = 1.0 (float arithmetic:
        # equal to ~1e-12, not bit-exact).
        self.assertAlmostEqual(
            s4110._derive_epoch_delta_over_d_pass1(rec, trial),
            1.0, places=9)

    def test_wrap(self):
        rec = {"pass1": _p1(t0=1504.9)}
        trial = _trial(period=5.0, epoch=1500.1, duration=0.1)
        # Raw diff 4.8 wraps to -0.2 in [-2.5, 2.5);
        # |-0.2| / 0.1 = 2.0 (float arithmetic: ~1e-12).
        self.assertAlmostEqual(
            s4110._derive_epoch_delta_over_d_pass1(rec, trial),
            2.0, places=9)

    def test_missing_t0(self):
        rec = {"pass1": _p1(t0=None)}
        self.assertIsNone(
            s4110._derive_epoch_delta_over_d_pass1(
                rec, _trial()))


class TestNullVetoBindings51(unittest.TestCase):
    """The merge-time stitched T0 veto covers the carried row
    (it is a final row), and demoting a dedupe partner
    un-dedupes the carry."""

    def _rec(self):
        return {"tic": "424242",
                "pass1_carried": _p1(),
                "pass1_carried_survivor": True,
                "pass2": _p1(t0=1502.05),
                "pass2_survivor": True,
                "pass3": None,
                "pass3_survivor": False,
                "final_rows": 1,
                "final_survivor": True}

    def test_carried_row_gets_binding(self):
        bindings = p43run._null_veto_bindings(self._rec())
        passes = [c["pass"] for c, _ in bindings]
        self.assertIn("pass1_carried", passes)
        self.assertIn("pass2", passes)
        self.assertEqual(len(bindings), 2)

    def test_demoting_pass2_un_dedupes_carry(self):
        from search_health import DEMOTED_T0_CLUSTER
        rec = self._rec()
        bindings = p43run._null_veto_bindings(rec)
        # Demote pass-2: the carry was deduped with it, so
        # the carry becomes the distinct row — final_rows
        # stays 1, and the dedupe marker clears. (The copy
        # carries what apply_stitched_t0_veto would set.)
        for copy, demote in bindings:
            if copy["pass"] == "pass2":
                copy["status"] = "demoted"
                copy["disposition"] = DEMOTED_T0_CLUSTER
                demote()
        self.assertFalse(rec["pass2_survivor"])
        self.assertTrue(rec["pass1_carried_survivor"])
        self.assertEqual(rec["final_rows"], 1)
        self.assertTrue(rec["final_survivor"])
        self.assertIsNone(rec["pass1_carried"]["deduped_with"])

    def test_demoting_carried_row_recomputes(self):
        from search_health import DEMOTED_T0_CLUSTER
        rec = self._rec()
        bindings = p43run._null_veto_bindings(rec)
        for copy, demote in bindings:
            if copy["pass"] == "pass1_carried":
                copy["status"] = "demoted"
                copy["disposition"] = DEMOTED_T0_CLUSTER
                demote()
        self.assertFalse(rec["pass1_carried_survivor"])
        # Pass-2 survives alone: one row.
        self.assertEqual(rec["final_rows"], 1)
        self.assertTrue(rec["final_survivor"])
        self.assertEqual(rec["pass1_carried"]["status"],
                         "demoted")

    def test_demoted_count_includes_carried(self):
        rec = self._rec()
        rec["pass1_carried"]["disposition"] = (
            "DEMOTED_T0_CLUSTER")
        # The disposition constant lives in search_health;
        # mirror the binding's own check via the module.
        from search_health import DEMOTED_T0_CLUSTER
        rec["pass1_carried"]["disposition"] = (
            DEMOTED_T0_CLUSTER)
        self.assertEqual(p43run._null_veto_demoted_count(rec), 1)


class TestCampaignVetoBindings51(unittest.TestCase):
    def _rec(self):
        return {"trials": [{
            "tic": "424242",
            "pass2": _p1(period=7.3),
            "p2_recovered": False, "p2_genuine": False,
            "pass3": None,
            "p3_recovered": False, "p3_genuine": False,
            "pass1_carried": _p1(),
            "p1_carried_recovered": True,
            "p1_carried_genuine": True,
            "final_recovered": True, "final_genuine": True}]}

    def test_carried_row_gets_binding(self):
        bindings = p43run._campaign_veto_bindings(self._rec())
        passes = [c["pass"] for c, _ in bindings]
        self.assertEqual(passes, ["pass1_carried"])

    def test_demoting_carried_clears_final(self):
        from search_health import DEMOTED_T0_CLUSTER
        rec = self._rec()
        bindings = p43run._campaign_veto_bindings(rec)
        self.assertEqual(len(bindings), 1)
        copy, demote = bindings[0]
        copy["status"] = "demoted"
        copy["disposition"] = DEMOTED_T0_CLUSTER
        demote()
        tr = rec["trials"][0]
        self.assertFalse(tr["p1_carried_recovered"])
        self.assertFalse(tr["p1_carried_genuine"])
        self.assertFalse(tr["final_recovered"])
        self.assertFalse(tr["final_genuine"])

    def test_demoted_count_includes_carried(self):
        from search_health import DEMOTED_T0_CLUSTER
        rec = self._rec()
        rec["trials"][0]["pass1_carried"]["disposition"] = (
            DEMOTED_T0_CLUSTER)
        self.assertEqual(
            p43run._campaign_veto_demoted_count(rec), 1)


class _DriverBase(unittest.TestCase):
    def setUp(self):
        self.previous = bs.CALIBRATION_VERSION
        bs.set_calibration("bulk_v6")

    def tearDown(self):
        bs.set_calibration(self.previous)

    @staticmethod
    def _trial(sector=95):
        return {"trial_id": "planet01", "tic": "424242",
                "sector": sector, "group": "recovered_412",
                "period_d": 5.0, "epoch_btjd": 1505.0,
                "epoch_offset_d": 5.0, "duration_d": 0.1422,
                "depth_frac": 0.008,
                "recorded": {"status": "survivor", "tier": "A",
                             "period_days": 5.0,
                             "depth_percent": 0.8, "sde": 15.0,
                             "mes_pink": 12.0, "flags": [],
                             "n_events_found": 5,
                             "n_strong_events": 5,
                             "max_event_snr": 8.0}}


class TestK3CarryEndToEnd(_DriverBase):
    def test_campaign_carries_pass1_survivor(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / "hosts").mkdir()
            (tmp / "w").mkdir()
            fits = make_qlp_fits(tmp / "424242.fits",
                                 period_d=None)
            job = {"tic": "424242", "sector": 95,
                   "arm": "prototype", "spans": None,
                   "path": str(fits), "trials": [self._trial()],
                   "out_dir": str(tmp), "workdir": str(tmp / "w"),
                   "manifest_sha": "test",
                   "calibration": "bulk_v6", "keep_fits": False}
            res = k3run.run_host_campaign_k3(job)
            self.assertEqual(res["status"], "done")
            rec = json.loads(
                (tmp / "hosts" / "424242_s0095.json").read_text())
            tr = rec["trials"][0]
            self.assertNotIn("error", tr)
            # The gate denied the mask here (pure-noise host):
            # pass 2 carries pass 1, and the 5.1 row carries
            # it too — deduped with pass 2.
            self.assertIsNotNone(tr.get("pass1_carried"))
            self.assertEqual(
                tr["pass1_carried"].get("carried_from"), "pass1")
            self.assertEqual(
                tr["pass1_carried"].get("deduped_with"), "pass2")
            self.assertTrue(tr["p1_carried_recovered"])
            self.assertTrue(tr["final_recovered"])

    def test_null_carries_pass1_survivor(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / "null_hosts").mkdir()
            (tmp / "w").mkdir()
            fits = make_qlp_fits(tmp / "424242.fits",
                                 period_d=5.0, depth_frac=0.008,
                                 t0=1502.0)
            job = {"tic": "424242", "sector": 95,
                   "arm": "prototype", "spans": None,
                   "path": str(fits),
                   "out_dir": str(tmp), "workdir": str(tmp / "w"),
                   "manifest_sha": "test",
                   "calibration": "bulk_v6", "keep_fits": False}
            res = k3run.run_host_null_k3(job)
            self.assertEqual(res["status"], "done")
            rec = json.loads(
                (tmp / "null_hosts"
                 / "424242_s0095.json").read_text())
            self.assertNotIn("error", rec)
            self.assertTrue(rec["pass1_survivor"])
            self.assertIsNotNone(rec.get("pass1_carried"))
            self.assertTrue(rec["pass1_carried_survivor"])
            self.assertIn("final_rows", rec)
            self.assertEqual(rec["final_survivor"],
                             bool(rec["final_rows"]))
            self.assertEqual(
                rec["final_survivor"],
                bool(rec["pass1_carried_survivor"]
                     or rec["pass2_survivor"]
                     or rec["pass3_survivor"]))


class TestP43CarryEndToEnd(_DriverBase):
    def _paths(self, tmp, tic, period_d):
        paths = {}
        for sec, t0 in ((95, 1500.0), (96, 1527.0),
                        (97, 1554.0)):
            paths[str(sec)] = str(make_qlp_fits(
                tmp / f"{tic}_s{sec:04d}.fits",
                period_d=period_d, depth_frac=0.008,
                t0=1502.0, t_start=t0))
        return paths

    def test_campaign_carries_pass1_survivor(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / "hosts-p43").mkdir()
            (tmp / "w").mkdir()
            job = {"tic": "424242", "sectors": [95, 96, 97],
                   "paths": self._paths(tmp, "424242", None),
                   "trials": [self._trial()],
                   "out_dir": str(tmp), "workdir": str(tmp / "w"),
                   "manifest_sha": "test",
                   "calibration": "bulk_v6", "keep_fits": False,
                   "seed_mode": "frozen", "agreement_only": False}
            res = p43run.run_host_campaign_p43(job)
            self.assertEqual(res["status"], "done")
            rec = json.loads(
                (tmp / "hosts-p43"
                 / "424242_p43.json").read_text())
            tr = rec["trials"][0]
            self.assertNotIn("error", tr)
            # record_pass1_stitched is on under bulk_v6, so
            # the stitched pass-1 survivor is carried.
            self.assertIsNotNone(tr.get("pass1"))
            self.assertIsNotNone(tr.get("pass1_carried"))
            self.assertEqual(
                tr["pass1_carried"].get("carried_from"), "pass1")
            self.assertIn("p1_carried_recovered", tr)
            self.assertEqual(
                tr["final_recovered"],
                bool(tr["p2_recovered"] or tr["p3_recovered"]
                     or tr["p1_carried_recovered"]))

    def test_null_carries_pass1_survivor(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / "null-p43").mkdir()
            (tmp / "w").mkdir()
            job = {"tic": "434343", "sectors": [95, 96, 97],
                   "paths": self._paths(tmp, "434343", 5.0),
                   "out_dir": str(tmp), "workdir": str(tmp / "w"),
                   "manifest_sha": "test",
                   "calibration": "bulk_v6", "keep_fits": False}
            res = p43run.run_host_null_p43(job)
            self.assertEqual(res["status"], "done")
            rec = json.loads(
                (tmp / "null-p43" / "434343_p43.json").read_text())
            self.assertNotIn("error", rec)
            self.assertTrue(rec["pass1_survivor"])
            self.assertIsNotNone(rec.get("pass1_carried"))
            self.assertTrue(rec["pass1_carried_survivor"])
            self.assertTrue(rec["final_survivor"])
            self.assertEqual(rec["final_survivor"],
                             bool(rec["final_rows"]))
            self.assertEqual(
                rec["final_survivor"],
                bool(rec["pass1_carried_survivor"]
                     or rec["pass2_survivor"]
                     or rec["pass3_survivor"]))


class TestK2CarryEndToEnd(_DriverBase):
    def test_campaign_carries_pass1_survivor(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / "hosts").mkdir()
            (tmp / "w").mkdir()
            fits = make_qlp_fits(tmp / "424242.fits",
                                 period_d=None)
            job = {"tic": "424242", "sector": 95,
                   "path": str(fits), "trials": [self._trial()],
                   "out_dir": str(tmp), "workdir": str(tmp / "w"),
                   "manifest_sha": "test",
                   "calibration": "bulk_v6", "keep_fits": False}
            res = k2run.run_host_campaign(job)
            self.assertEqual(res["status"], "done")
            rec = json.loads(
                (tmp / "hosts" / "424242_s0095.json").read_text())
            tr = rec["trials"][0]
            self.assertNotIn("error", tr)
            self.assertIsNotNone(tr.get("pass1_carried"))
            self.assertEqual(
                tr["pass1_carried"].get("carried_from"), "pass1")
            self.assertIn("final_recovered", tr)
            self.assertIn("final_genuine", tr)
            self.assertEqual(
                tr["final_recovered"],
                bool(tr["k2_recovered"]
                     or tr["p1_carried_recovered"]))

    def test_null_carries_pass1_survivor(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / "null_hosts").mkdir()
            (tmp / "w").mkdir()
            fits = make_qlp_fits(tmp / "424242.fits",
                                 period_d=5.0, depth_frac=0.008,
                                 t0=1502.0)
            job = {"tic": "424242", "sector": 95,
                   "path": str(fits),
                   "out_dir": str(tmp), "workdir": str(tmp / "w"),
                   "manifest_sha": "test",
                   "calibration": "bulk_v6", "keep_fits": False}
            res = k2run.run_host_null(job)
            self.assertEqual(res["status"], "done")
            rec = json.loads(
                (tmp / "null_hosts"
                 / "424242_s0095.json").read_text())
            self.assertNotIn("error", rec)
            self.assertTrue(rec["pass1_survivor"])
            self.assertIsNotNone(rec.get("pass1_carried"))
            self.assertTrue(rec["pass1_carried_survivor"])
            self.assertIn("final_rows", rec)
            self.assertIn("final_survivor", rec)
            self.assertEqual(rec["final_survivor"],
                             bool(rec["final_rows"]))


if __name__ == "__main__":
    unittest.main()
