"""P4-2 tests: the event-count fix + the pool-initializer fix.

(1) Event-count rule (PB-2): an event counts only if its full
[centre-D/2, centre+D/2] window lies within one contiguous valid
segment (a gap is a jump > 0.05 d between consecutive valid
cadences) with guard clearance from the segment edges, with
in-window coverage >= 50% of the expected cadences and >= 3
cadences. The pre-P4-2 rule counted an event on >= 1 in-window
cadence — the P3-13 finding (114/120 spurious 13.7 d signals
from events at sector start / orbit gap / sector end) was the
consequence.

(2) Initializer fix (PB-2 finding): bulk_screen.py's main() set
the calibration in the PARENT only and the ProcessPoolExecutor
had NO initializer, so on macOS (spawn) workers re-imported the
module and fell back to bulk_v1 regardless of --calibration,
while records were stamped with the requested calibration. The
spawn test below forces a spawn pool and asserts the recorded
preprocessing matches the requested profile.

Offline: all fixtures are synthetic (synth_fits) or in-memory.
"""
import json
import math
import multiprocessing
import sys
import tempfile
import unittest
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from unittest import mock

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import bulk_screen as bs  # noqa: E402
from bulk.oracle_run import rescore_filtered  # noqa: E402
from synth_fits import make_qlp_fits  # noqa: E402

SECTOR = 97
SEED = 7


def _lc(period=2.5, t0=1502.0, duration=0.1, depth=0.01, noise=0.003,
        n=1296, start=1500.0, cad=0.0208333, gap=None, seed=SEED):
    """Synthetic flattened light curve (time, flux) with dips at
    the given ephemeris. gap=(lo, hi) removes cadences in that
    range (an orbit gap)."""
    rng = np.random.default_rng(seed)
    t = start + np.arange(n) * cad
    f = 1.0 + rng.normal(0, noise, n)
    phase = ((t - t0 + 0.5 * period) % period) - 0.5 * period
    f = np.where(np.abs(phase) < duration / 2, f - depth, f)
    if gap is not None:
        keep = ~((t > gap[0]) & (t < gap[1]))
        t, f = t[keep], f[keep]
    return t, f


class TestSegments(unittest.TestCase):
    def test_no_gap_single_segment(self):
        t = 1500.0 + np.arange(100) * 0.0208333
        self.assertEqual(bs.segments_from_times(t), [(0, 100)])

    def test_gap_splits_segments(self):
        t = 1500.0 + np.arange(100) * 0.0208333
        t = np.delete(t, np.arange(40, 60))  # ~0.42 d hole
        segs = bs.segments_from_times(t)
        self.assertEqual(segs, [(0, 40), (40, 80)])

    def test_small_jump_is_not_a_gap(self):
        # A 0.041 d jump (cadence + 0.02 d) is under the 0.05 d
        # threshold.
        t = np.concatenate([1500.0 + np.arange(50) * 0.0208333,
                            1500.0 + 50 * 0.0208333 + 0.02
                            + np.arange(50) * 0.0208333])
        self.assertEqual(bs.segments_from_times(t), [(0, 100)])

    def test_empty(self):
        self.assertEqual(bs.segments_from_times(np.array([])), [])


class TestRescoreFilter(unittest.TestCase):
    def test_edge_truncated_event_dropped(self):
        # 11 events under the old rule; the last event's window
        # extends past the last cadence, so the new rule drops it.
        t, f = _lc()
        old = bs._rescore(t, f, 2.5, 1502.0, 0.1, filter_events=False)
        new = bs._rescore(t, f, 2.5, 1502.0, 0.1)
        self.assertEqual(old["n_events"], 11)
        self.assertEqual(new["n_events"], 10)
        self.assertEqual(new["n_events_dropped"], 1)
        self.assertEqual(len(new["events_kept"]), 10)
        self.assertEqual(len(new["events_dropped"]), 1)

    def test_gap_straddling_event_dropped(self):
        # An event whose window straddles the orbit gap has
        # in-window cadences on one side only: the old rule
        # counts it, the new rule drops it.
        t, f = _lc(period=2.5, t0=1502.0, duration=0.3, gap=(1513.5, 1514.7))
        old = bs._rescore(t, f, 2.5, 1502.0, 0.3, filter_events=False)
        new = bs._rescore(t, f, 2.5, 1502.0, 0.3)
        self.assertGreater(old["n_events"], new["n_events"])
        self.assertGreaterEqual(new["n_events_dropped"], 1)

    def test_low_coverage_event_dropped(self):
        # An event window with < 50% of the expected cadences
        # (most cadences removed inside one window) is dropped.
        t, f = _lc()
        # Remove all but 1 cadence inside the window of the
        # event centred at 1512.0 (window [1511.95, 1512.05]).
        win = (t >= 1511.95) & (t <= 1512.05)
        idx = np.where(win)[0]
        keep = np.ones(len(t), dtype=bool)
        keep[idx[1:]] = False
        t2, f2 = t[keep], f[keep]
        old = bs._rescore(t2, f2, 2.5, 1502.0, 0.1, filter_events=False)
        new = bs._rescore(t2, f2, 2.5, 1502.0, 0.1)
        self.assertGreater(old["n_events"], new["n_events"])

    def test_guard_drops_near_edge_event(self):
        # The first event's window clears the first cadence by
        # 0.05 d: it counts at guard 0 and drops at guard 0.1 d.
        t, f = _lc(t0=1500.1)
        g0 = bs._rescore(t, f, 2.5, 1500.1, 0.1, guard_d=0.0)
        g1 = bs._rescore(t, f, 2.5, 1500.1, 0.1, guard_d=0.1)
        self.assertEqual(g0["n_events"], 11)
        self.assertEqual(g1["n_events"], 10)

    def test_filter_events_false_reproduces_old_rule(self):
        # The measurement seam: filter_events=False gives the
        # pre-P4-2 >= 1-cadence count on every fixture.
        t, f = _lc(gap=(1513.5, 1514.7))
        old = bs._rescore(t, f, 2.5, 1502.0, 0.3, filter_events=False)
        new = bs._rescore(t, f, 2.5, 1502.0, 0.3)
        self.assertGreaterEqual(old["n_events"], new["n_events"])
        # The old rule never drops: its event list is the kept
        # list plus nothing.
        self.assertEqual(old["n_events_dropped"], 0)
        self.assertEqual(old["events_dropped"], [])

    def test_p3_13_pattern_zero_events(self):
        # The P3-13 glitch pattern: a 13.5 d signal with events
        # at sector start, straddling the orbit gap, and at
        # sector end. The old rule counts all three (Tier A
        # territory); the new rule counts none and returns a
        # zero-event dict (not None).
        t, f = _lc(period=13.5, t0=1500.1, duration=0.3, depth=0.01,
                   gap=(1513.5, 1514.7))
        old = bs._rescore(t, f, 13.5, 1500.1, 0.3, filter_events=False)
        new = bs._rescore(t, f, 13.5, 1500.1, 0.3)
        self.assertEqual(old["n_events"], 3)
        self.assertIsNotNone(new)
        self.assertEqual(new["n_events"], 0)
        self.assertEqual(new["n_events_dropped"], 3)
        self.assertEqual(new["mes_pink"], 0.0)
        self.assertEqual(new["n_strong_events"], 0)

    def test_depth_uses_kept_events_only(self):
        # A dropped event's (deep) dip must not contribute to
        # the measured depth: make the edge event's dip 5x
        # deeper than the rest and check the depth does not
        # move between the filtered and unfiltered rescore on
        # the KEPT events. (mes_pink scales with sqrt(N) and
        # the kept depth, so compare mes_pink / sqrt(n_events)
        # — the depth/cdpp ratio — between filter on/off on a
        # fixture where the dropped event is the deep one.)
        t, f = _lc()
        # Deepen the last (edge-truncated) event's dip.
        phase = ((t - 1502.0 + 0.5 * 2.5) % 2.5) - 0.5 * 2.5
        last = (np.abs(phase) < 0.05) & (t > 1526.0)
        f = np.where(last, f - 0.04, f)
        new = bs._rescore(t, f, 2.5, 1502.0, 0.1)
        old = bs._rescore(t, f, 2.5, 1502.0, 0.1, filter_events=False)
        ratio_new = new["mes_pink"] / math.sqrt(new["n_events"])
        ratio_old = old["mes_pink"] / math.sqrt(old["n_events"])
        # The old ratio is inflated by the deep dropped event;
        # the new ratio is not.
        self.assertGreater(ratio_old, ratio_new * 1.1)


class TestRescoreFilteredDelegation(unittest.TestCase):
    def test_delegation_matches_production(self):
        # oracle_run.rescore_filtered delegates to
        # bulk_screen._rescore: the guard curve the driver
        # measures IS the production rule's curve.
        t, f = _lc(gap=(1513.5, 1514.7))
        for guard in (0.0, 0.1, 0.25):
            a = rescore_filtered(t, f, 2.5, 1502.0, 0.3, guard_d=guard)
            b = bs._rescore(t, f, 2.5, 1502.0, 0.3, guard_d=guard)
            self.assertEqual(a["n_events"], b["n_events"])
            self.assertEqual(a["n_events_dropped"], b["n_events_dropped"])
            self.assertEqual(a["mes_pink"], b["mes_pink"])
            self.assertEqual(a["events_kept"], b["events_kept"])


class TestEventGuardProfile(unittest.TestCase):
    def test_profile_defaults(self):
        bs.set_calibration("bulk_v4")
        self.assertEqual(bs.EVENT_GUARD_D, 0.0)
        self.assertEqual(bs.EVENT_GAP_D, 0.05)
        self.assertEqual(bs.EVENT_MIN_COVERAGE, 0.5)
        self.assertEqual(bs.EVENT_MIN_CADENCES, 3)

    def test_set_event_guard(self):
        bs.set_calibration("bulk_v4")
        bs.set_event_guard(0.1)
        self.assertEqual(bs.EVENT_GUARD_D, 0.1)
        with self.assertRaises(ValueError):
            bs.set_event_guard(-0.1)
        bs.set_event_guard(0.0)


class TestVetoSummaryClusters(unittest.TestCase):
    def test_clusters_recorded_with_membership(self):
        # Two 21-star clusters + one loner: the summary carries
        # cluster identity + membership, deterministic.
        recs = []
        for i in range(21):
            recs.append({"tic": str(1000 + i), "period_days": 13.7,
                         "t0_btjd": 1500.0 + i * 0.01, "tier": "B"})
        for i in range(21):
            recs.append({"tic": str(2000 + i), "period_days": 6.85,
                         "t0_btjd": 1501.0 + i * 0.01, "tier": "A"})
        recs.append({"tic": "9999", "period_days": 2.5, "t0_btjd": 1500.5,
                     "tier": "A"})
        kept, summary = bs.apply_epoch_cluster_veto(recs)
        self.assertEqual(summary["n_clusters"], 2)
        self.assertEqual(summary["cluster_sizes"], [21, 21])
        self.assertEqual(len(summary["clusters"]), 2)
        for c in summary["clusters"]:
            self.assertEqual(c["size"], 21)
            self.assertEqual(len(c["members"]), 21)
            self.assertEqual(c["members"], sorted(c["members"]))
        ids = sorted(c["cluster_id"] for c in summary["clusters"])
        self.assertEqual(ids, [0, 1])
        # Membership union == the clustered TICs.
        members = set()
        for c in summary["clusters"]:
            members.update(c["members"])
        self.assertEqual(len(members), 42)
        # Deterministic: a second call gives the same clusters.
        _, summary2 = bs.apply_epoch_cluster_veto(recs)
        self.assertEqual(summary["clusters"], summary2["clusters"])
        # The veto outcome is unchanged by the summary extension.
        self.assertEqual(summary["demoted_tier_b"], 21)
        self.assertEqual(summary["flagged_tier_a"], 21)
        self.assertEqual(len(kept), 22)  # 21 flagged A + 1 loner


class _SpawnPoolExecutor(ProcessPoolExecutor):
    """ProcessPoolExecutor forcing the spawn start method — the
    macOS behaviour — so the initializer test exercises the
    worker re-import path on Linux too (fork would pass
    trivially)."""
    def __init__(self, *args, **kwargs):
        kwargs["mp_context"] = multiprocessing.get_context("spawn")
        super().__init__(*args, **kwargs)


class TestInitializerSpawn(unittest.TestCase):
    def test_worker_screens_under_requested_calibration(self):
        # A small CLI run under bulk_v4 with a spawn pool: the
        # recorded bls_input_hash must match the in-process v4
        # hash, not the v1 default. Without the P4-2 initializer
        # this fails: spawn workers re-import bulk_screen and
        # fall back to bulk_v1.
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            cache = tmp / "cache"
            (cache / f"s{SECTOR:04d}").mkdir(parents=True)
            tic = "7654321"
            # A deep (DEPTH_EB) transit: above the record floor,
            # demoted, so it lands in screen_hits.jsonl without
            # triggering the Zooniverse annotation (survivors
            # only) — the test stays offline.
            make_qlp_fits(cache / f"s{SECTOR:04d}" / f"{tic}.fits",
                          period_d=2.5, t0=1502.0, duration_d=0.1,
                          depth_frac=0.035, seed=SEED)
            stars = tmp / "stars.csv"
            stars.write_text("tic,ra,dec,radius\n7654321,100.0,-65.0,0.5\n")
            star = {"tic": tic, "ra": 100.0, "dec": -65.0,
                    "tmag": None, "radius": 0.5}
            # In-process hashes: v4 vs v1 must differ (the
            # preprocessing differs), and the CLI run must match
            # the v4 one.
            bs.set_calibration("bulk_v4")
            rec_v4 = bs._screen_one(
                (tic, str(cache / f"s{SECTOR:04d}" / f"{tic}.fits"),
                 SECTOR, star))
            bs.set_calibration("bulk_v1")
            rec_v1 = bs._screen_one(
                (tic, str(cache / f"s{SECTOR:04d}" / f"{tic}.fits"),
                 SECTOR, star))
            h_v4 = rec_v4["input_identity"]["bls_input_hash"]
            h_v1 = rec_v1["input_identity"]["bls_input_hash"]
            self.assertNotEqual(h_v4, h_v1)
            out = tmp / "out"
            argv = ["bulk_screen.py", "--sector", str(SECTOR),
                    "--calibration", "bulk_v4",
                    "--stars-file", str(stars),
                    "--cache-dir", str(cache),
                    "--out-dir", str(out),
                    "--skip-filter", "--workers", "2"]
            with mock.patch.object(bs, "ProcessPoolExecutor",
                                   _SpawnPoolExecutor):
                with mock.patch.object(sys, "argv", argv):
                    bs.main()
            hits = [json.loads(l) for l in
                    (out / "screen_hits.jsonl").read_text().splitlines()]
            self.assertEqual(len(hits), 1)
            self.assertEqual(
                hits[0]["input_identity"]["bls_input_hash"], h_v4)
            # The run summary stamps the requested calibration
            # (short form "v4"); the hash above is the per-record
            # proof the workers actually used it.
            summary = json.loads((out / "summary.json").read_text())
            self.assertEqual(
                summary["provenance"]["calibration_version"]["bulk"],
                "v4")
            self.assertEqual(summary["thresholds"]["event_guard_d"], 0.0)


class TestChunkedSummaryCalibration(unittest.TestCase):
    def test_merged_summary_stamps_requested_calibration(self):
        # run_chunked's merge hardcoded {"bulk": "v1"} in the
        # merged summary (P3-21's summary shows it on a v4 run)
        # — the stamp must follow --calibration like the
        # manifest does.
        from tests.test_resume import _build_workdir, _run_driver
        with tempfile.TemporaryDirectory() as td:
            work, recipe = _build_workdir(td)
            stub_log = Path(td) / "stub.log"
            rc, out = _run_driver(work, recipe, stub_log,
                                  extra_args=("--calibration",
                                              "bulk_v4"))
            self.assertEqual(rc, 0, out[-2000:])
            summary = json.loads(
                (work / "run_s0999" / "summary.json").read_text())
            self.assertEqual(
                summary["provenance"]["calibration_version"],
                {"bulk": "v4"})
            manifest = json.loads(
                (work / "run_s0999" / "manifest.json").read_text())
            self.assertEqual(manifest["calibration"]["versions"],
                             {"bulk": "v4"})


if __name__ == "__main__":
    unittest.main()
