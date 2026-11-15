"""3B replay-matrix tests (Phase 3, P3-11).

Offline, synthetic survivor rows only — no rescore file, no
network. The gates are pure functions over row dicts, so each
one is pinned here with a passing row, a failing row, and its
boundary value. The adoption-rule checker is pinned the same
way: a candidate that drops a known planet is RULE-REJECTED,
and a candidate satisfying the rule (zero planet losses +
campaign loss within the bar) is ADOPTABLE.
"""
import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bulk import replay_matrix as rm  # noqa: E402


def _row(tic="1", **over):
    """A synthetic survivor row; overrides set the field under test."""
    row = {
        "tic": str(tic),
        "period_days": 3.0,
        "t0_btjd": 3910.0,
        "sde": 12.0,
        "n_events": 3,
        "n_strong_events": 3,
        "mes_pink": 12.0,
        "odd_even_ratio": 0.9,
        "tier": "A",
        "near_systematic": False,
    }
    row.update(over)
    return row


class TestSdeBar(unittest.TestCase):
    def test_pass(self):
        self.assertTrue(rm.sde_bar(_row(sde=9.5), 9.0))

    def test_fail(self):
        self.assertFalse(rm.sde_bar(_row(sde=8.9), 9.0))

    def test_boundary_is_kept(self):
        self.assertTrue(rm.sde_bar(_row(sde=9.0), 9.0))


class TestTwoEventStrong(unittest.TestCase):
    def test_two_strong_pass(self):
        self.assertTrue(rm.two_event_strong(
            _row(n_events=2, n_strong_events=2)))

    def test_one_strong_fails(self):
        self.assertFalse(rm.two_event_strong(
            _row(n_events=2, n_strong_events=1)))

    def test_zero_strong_fails(self):
        self.assertFalse(rm.two_event_strong(
            _row(n_events=2, n_strong_events=0)))

    def test_single_event_unaffected(self):
        # 1-event rows are P3-14's singles, not this gate's business.
        self.assertTrue(rm.two_event_strong(
            _row(n_events=1, n_strong_events=1)))

    def test_three_event_unaffected(self):
        self.assertTrue(rm.two_event_strong(
            _row(n_events=3, n_strong_events=1)))


class TestTwoEventCombined(unittest.TestCase):
    def test_pass(self):
        self.assertTrue(rm.two_event_combined(
            _row(n_events=2, n_strong_events=2, mes_pink=10.0)))

    def test_weak_combined_fails(self):
        # Both events strong, but the combined significance is
        # below the tier-A MES bar.
        self.assertFalse(rm.two_event_combined(
            _row(n_events=2, n_strong_events=2, mes_pink=8.9)))

    def test_boundary_is_kept(self):
        self.assertTrue(rm.two_event_combined(
            _row(n_events=2, n_strong_events=2, mes_pink=9.0)))

    def test_one_strong_fails_even_if_combined_high(self):
        self.assertFalse(rm.two_event_combined(
            _row(n_events=2, n_strong_events=1, mes_pink=20.0)))

    def test_single_event_unaffected(self):
        self.assertTrue(rm.two_event_combined(
            _row(n_events=1, n_strong_events=1, mes_pink=5.0)))


class TestPhaseDepth(unittest.TestCase):
    def test_pass(self):
        self.assertTrue(rm.phase_depth_consistent(
            _row(n_events=2, odd_even_ratio=0.8)))

    def test_fail(self):
        self.assertFalse(rm.phase_depth_consistent(
            _row(n_events=2, odd_even_ratio=0.2)))

    def test_boundary_is_kept(self):
        self.assertTrue(rm.phase_depth_consistent(
            _row(n_events=2, odd_even_ratio=0.5)))

    def test_zero_ratio_fails(self):
        # One parity fold has no dip at all.
        self.assertFalse(rm.phase_depth_consistent(
            _row(n_events=2, odd_even_ratio=0.0)))

    def test_single_event_untestable_passes_through(self):
        self.assertTrue(rm.phase_depth_consistent(
            _row(n_events=1, odd_even_ratio=0.0)))


class TestDemoteSystematic(unittest.TestCase):
    def test_tier_b_flagged_demoted(self):
        self.assertFalse(rm.demote_systematic(
            _row(tier="B", near_systematic=True)))

    def test_tier_b_unflagged_kept(self):
        self.assertTrue(rm.demote_systematic(
            _row(tier="B", near_systematic=False)))

    def test_tier_a_flagged_untouched(self):
        self.assertTrue(rm.demote_systematic(
            _row(tier="A", near_systematic=True)))


class TestEpochClusters(unittest.TestCase):
    def _cluster_rows(self, n, period=13.2, t0=3920.0, tier="B"):
        # n rows sharing (P, T0) within the tolerances.
        return [_row(tic=str(1000 + i), period_days=period + 0.001 * i,
                     t0_btjd=t0 + 0.001 * i, tier=tier)
                for i in range(n)]

    def test_cluster_over_20_flagged(self):
        rows = self._cluster_rows(25)
        clustered, clusters = rm.sector_epoch_cluster_tics(rows)
        self.assertEqual(len(clustered), 25)
        self.assertEqual(len(clusters), 1)
        self.assertEqual(len(clusters[0]), 25)

    def test_cluster_of_exactly_20_not_flagged(self):
        # The rule is >20 stars, not >=20.
        rows = self._cluster_rows(20)
        clustered, clusters = rm.sector_epoch_cluster_tics(rows)
        self.assertEqual(len(clustered), 0)
        self.assertEqual(clusters, [])

    def test_cluster_of_21_flagged(self):
        rows = self._cluster_rows(21)
        clustered, _ = rm.sector_epoch_cluster_tics(rows)
        self.assertEqual(len(clustered), 21)

    def test_scattered_set_not_flagged(self):
        # 25 rows, all periods and epochs far apart.
        rows = [_row(tic=str(2000 + i), period_days=1.0 + i,
                     t0_btjd=3908.0 + i, tier="B") for i in range(25)]
        clustered, clusters = rm.sector_epoch_cluster_tics(rows)
        self.assertEqual(len(clustered), 0)
        self.assertEqual(clusters, [])

    def test_same_period_different_epoch_not_clustered(self):
        # Shared period alone is not a cluster (the veto is on
        # shared epochs, never on periods).
        rows = [_row(tic=str(3000 + i), period_days=13.2,
                     t0_btjd=3908.0 + i, tier="B") for i in range(25)]
        clustered, _ = rm.sector_epoch_cluster_tics(rows)
        self.assertEqual(len(clustered), 0)

    def test_same_epoch_different_period_not_clustered(self):
        rows = [_row(tic=str(4000 + i), period_days=1.0 + 0.5 * i,
                     t0_btjd=3920.0, tier="B") for i in range(25)]
        clustered, _ = rm.sector_epoch_cluster_tics(rows)
        self.assertEqual(len(clustered), 0)


class TestRunMatrix(unittest.TestCase):
    def test_sde_bars_report_reduction_without_mutating_rows(self):
        rows = [_row(tic=str(i), sde=float(sde))
                for i, sde in enumerate([7.5, 8.5, 9.5, 12.0])]
        before = copy.deepcopy(rows)
        results = rm.run_matrix(rows, {})
        self.assertEqual(rows, before)  # input rows untouched
        self.assertEqual(results["SDE-8.0"]["removed"], 1)
        self.assertEqual(results["SDE-9.0"]["removed"], 2)
        self.assertEqual(results["SDE-10.0"]["removed"], 3)
        self.assertEqual(results["SDE-9.0"]["removed_tier_a"], 2)

    def test_per_class_losses_reported(self):
        rows = [
            _row(tic="183537452", sde=7.5),   # WASP-29b, weak SDE
            _row(tic="999", sde=7.5),         # unlabelled
            _row(tic="888", sde=12.0),        # EB, strong SDE
        ]
        labels = {"183537452": rm.CLASS_PLANET,
                  "888": rm.CLASS_EB}
        results = rm.run_matrix(rows, labels)
        self.assertEqual(results["SDE-8.0"]["losses"][rm.CLASS_PLANET],
                         1)
        self.assertEqual(results["SDE-8.0"]["losses"][rm.CLASS_EB], 0)
        self.assertEqual(results["SDE-8.0"]["lost_tics"][rm.CLASS_PLANET],
                         ["183537452"])

    def test_epoch_cluster_demotes_tier_b_flags_tier_a(self):
        rows = [_row(tic=str(5000 + i), period_days=13.2,
                     t0_btjd=3920.0, tier="B", sde=12.0)
                for i in range(21)]
        rows.append(_row(tic="7777", period_days=13.2, t0_btjd=3920.0,
                         tier="A", sde=12.0))
        results = rm.run_matrix(rows, {})
        res = results["EPOCH-CLUSTER"]
        self.assertEqual(res["removed"], 21)
        self.assertEqual(res["removed_tier_b"], 21)
        self.assertEqual(res["removed_tier_a"], 0)
        self.assertEqual(res["flagged_tier_a"], 1)

    def test_demote_all_is_union(self):
        rows = [_row(tic=str(6000 + i), period_days=13.2,
                     t0_btjd=3920.0, tier="B", sde=12.0)
                for i in range(21)]
        # A flagged tier-B row outside any cluster.
        rows.append(_row(tic="6666", period_days=5.0, t0_btjd=3911.0,
                         tier="B", near_systematic=True, sde=12.0))
        results = rm.run_matrix(rows, {})
        self.assertEqual(results["DEMOTE-ALL"]["removed"], 22)
        self.assertEqual(results["DEMOTE-SYS"]["removed"], 1)
        self.assertEqual(results["EPOCH-CLUSTER"]["removed"], 21)


class TestCheckAdoption(unittest.TestCase):
    def _result(self, name, planet_losses=0):
        return {
            "candidate": name,
            "losses": {rm.CLASS_PLANET: planet_losses,
                       rm.CLASS_EB: 0,
                       rm.CLASS_REFUTED_OTHER: 0},
            "lost_tics": {rm.CLASS_PLANET:
                          ["183537452"] if planet_losses else [],
                          rm.CLASS_EB: [],
                          rm.CLASS_REFUTED_OTHER: []},
        }

    def test_planet_loss_is_rule_rejected(self):
        verdict, _ = rm.check_adoption(
            self._result("TWO-STRONG", planet_losses=1),
            campaign={"n_1_2_event": 300, "losses_1_2_event": 0})
        self.assertEqual(verdict, "RULE-REJECTED")

    def test_planet_loss_rejected_even_for_sde_bar(self):
        verdict, _ = rm.check_adoption(
            self._result("SDE-10.0", planet_losses=2))
        self.assertEqual(verdict, "RULE-REJECTED")

    def test_sde_bar_is_evidence_only(self):
        verdict, _ = rm.check_adoption(self._result("SDE-9.0"))
        self.assertEqual(verdict, "EVIDENCE-ONLY")

    def test_no_campaign_is_undecided(self):
        verdict, _ = rm.check_adoption(self._result("TWO-STRONG"))
        self.assertEqual(verdict, "UNDECIDED")

    def test_campaign_within_bar_is_adoptable(self):
        verdict, _ = rm.check_adoption(
            self._result("TWO-STRONG"),
            campaign={"n_1_2_event": 300, "losses_1_2_event": 9})
        self.assertEqual(verdict, "ADOPTABLE")

    def test_campaign_above_bar_is_rejected(self):
        # 30/500 = 6.0% point estimate with a tight interval
        # (95% upper ~8.4%) — a confident rejection.
        verdict, _ = rm.check_adoption(
            self._result("TWO-STRONG"),
            campaign={"n_1_2_event": 500, "losses_1_2_event": 30})
        self.assertEqual(verdict, "REJECTED")

    def test_small_n_is_undecided_not_a_pass(self):
        verdict, _ = rm.check_adoption(
            self._result("TWO-STRONG"),
            campaign={"n_1_2_event": 50, "losses_1_2_event": 0})
        self.assertEqual(verdict, "UNDECIDED")

    def test_wide_interval_is_undecided(self):
        # 12/200 = 6.0% point estimate, but the 95% upper bound
        # (~10.2%) exceeds the 10% bar — the measurement is too
        # noisy to reject on, so it is inconclusive, not a pass
        # and not a rejection.
        verdict, _ = rm.check_adoption(
            self._result("TWO-STRONG"),
            campaign={"n_1_2_event": 200, "losses_1_2_event": 12})
        self.assertEqual(verdict, "UNDECIDED")


class TestWilsonUpper(unittest.TestCase):
    def test_zero_losses_bounds_below_ten_percent_at_n300(self):
        self.assertLess(rm.wilson_upper(0, 300), 0.10)

    def test_empty_sample_is_uninformative(self):
        self.assertEqual(rm.wilson_upper(0, 0), 1.0)


if __name__ == "__main__":
    unittest.main()
