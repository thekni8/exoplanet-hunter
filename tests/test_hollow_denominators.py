"""Hollow-denominator tests (Phase 1.2 follow-up F-13).

Conservation passes when watchdog timeouts land in
"unmeasured", so an outage looks like "0 survivors". Three
fixes, three test groups:

  * the run-level unmeasured-fraction threshold (5%): a run
    that timed out on too many stars FAILS, like a conservation
    failure — tested pure (check_unmeasured_fraction) and at
    the driver (a seeded run whose slice summaries move stars
    recorded -> unmeasured, conservation intact, must fail
    with the unmeasured message);
  * the consecutive-timeout circuit breaker (25): N timeouts
    in a row with no success in between stop the slice with
    CircuitBreakerError — tested with a fake executor (no
    multiprocessing, no hanging workers);
  * "N screened" counts only MEASURED stars: stars_measured
    (searched minus unmeasured) on slice summaries, the run
    summary, the manifest, and the ledger — with a fallback
    for old summaries that lack the field.
"""
import json
import sys
import tempfile
import unittest
from concurrent.futures import Future
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import bulk_screen as bs  # noqa: E402
import provenance as prov  # noqa: E402
from bulk import build_ledger  # noqa: E402
from bulk.run_chunked import (  # noqa: E402
    MAX_UNMEASURED_FRACTION, _measured_of,
    check_unmeasured_fraction)
from tests.test_resume import (  # noqa: E402
    _build_workdir, _invocations, _run_driver)


class TestUnmeasuredFraction(unittest.TestCase):
    def test_below_threshold_passes(self):
        ok, frac = check_unmeasured_fraction(10000, 400)
        self.assertTrue(ok)
        self.assertAlmostEqual(frac, 0.04)

    def test_at_threshold_passes(self):
        ok, frac = check_unmeasured_fraction(10000, 500)
        self.assertTrue(ok)
        self.assertAlmostEqual(frac, 0.05)

    def test_above_threshold_fails(self):
        ok, frac = check_unmeasured_fraction(10000, 501)
        self.assertFalse(ok)
        self.assertAlmostEqual(frac, 0.0501)

    def test_zero_searched_is_zero(self):
        ok, frac = check_unmeasured_fraction(0, 0)
        self.assertTrue(ok)
        self.assertEqual(frac, 0.0)

    def test_threshold_is_five_percent(self):
        self.assertEqual(MAX_UNMEASURED_FRACTION, 0.05)


class _FakeExecutor:
    """An executor whose futures the test controls: jobs in
    `hang` never complete; the rest complete immediately with
    a recorded-status record. The worker is never called."""

    def __init__(self, hang):
        self.hang = set(hang)

    def submit(self, worker, job):
        tic = job[0]
        fut = Future()
        if tic not in self.hang:
            fut.set_result({"tic": tic, "status": "recorded"})
        return fut


def _job(tic):
    return (tic, f"/fake/{tic}.fits", 999,
            {"ra": 100.0, "dec": -65.0, "tmag": 12.0,
             "radius": 0.5})


class TestCircuitBreaker(unittest.TestCase):
    def test_consecutive_timeouts_trip(self):
        # All 5 jobs hang; the breaker trips at 3 (a small
        # limit, passed in for the test — production uses 25).
        jobs = [_job(f"10000000{i}") for i in range(1, 6)]
        ex = _FakeExecutor({j[0] for j in jobs})
        with self.assertRaises(bs.CircuitBreakerError) as ctx:
            bs._collect_screen_results(
                ex, jobs, None, timeout_s=0.05,
                max_consecutive_timeouts=3)
        self.assertIn("consecutive", str(ctx.exception))

    def test_default_limit_trips(self):
        # The production default (25) is wired: 30 hangs trip it.
        jobs = [_job(f"1000000{i:02d}") for i in range(30)]
        ex = _FakeExecutor({j[0] for j in jobs})
        with self.assertRaises(bs.CircuitBreakerError):
            bs._collect_screen_results(ex, jobs, None,
                                       timeout_s=0.05)

    def test_interleaved_successes_do_not_trip(self):
        # 6 jobs, 2 hang (every 3rd): the successes reset the
        # counter, so the run completes with 2 unmeasured and
        # 4 recorded — no trip.
        jobs = [_job(f"10000000{i}") for i in range(1, 7)]
        ex = _FakeExecutor({"100000003", "100000006"})
        records, counts = bs._collect_screen_results(
            ex, jobs, None, timeout_s=0.05,
            max_consecutive_timeouts=3)
        self.assertEqual(counts, {"recorded": 4, "unmeasured": 2})
        self.assertEqual(len(records), 6)
        unmeasured = [r for r in records
                      if r["status"] == "unmeasured"]
        self.assertEqual({r["tic"] for r in unmeasured},
                         {"100000003", "100000006"})
        self.assertTrue(all("watchdog_timeout" in r["reason"]
                            for r in unmeasured))


class TestUnmeasuredFractionDriver(unittest.TestCase):
    def test_high_unmeasured_fails_the_run(self):
        # Seed a completed stub run, then move 1 star
        # recorded -> unmeasured in slice 0 (1/10 = 10% > 5%)
        # and forge the checkpoint's summary hash so the slice
        # is trusted and the edit reaches the merge. The
        # conservation equations still hold (sum == searched,
        # survivors intact) — ONLY the unmeasured threshold
        # fails the run. That is the hole F-13 closes: without
        # the threshold this run would complete green.
        with tempfile.TemporaryDirectory() as td:
            work, recipe = _build_workdir(td)
            stub_log = Path(td) / "invocations.log"
            rc, out = _run_driver(work, recipe, stub_log)
            self.assertEqual(rc, 0, msg=out[-2000:])
            run = work / "run_s0999"
            s_path = run / "chunk_00" / "summary.json"
            s = json.loads(s_path.read_text())
            self.assertEqual(s["screen_counts"]["recorded"], 3)
            s["screen_counts"]["recorded"] -= 1
            s["screen_counts"]["unmeasured"] = 1
            s_path.write_text(json.dumps(s))
            cp_path = run / "checkpoint.json"
            cp = json.loads(cp_path.read_text())
            cp["completed"]["0"]["summary_sha256"] = \
                prov.file_sha256(s_path)
            cp_path.write_text(json.dumps(cp))
            n_before = len(_invocations(stub_log))
            rc, out = _run_driver(work, recipe, stub_log)
            self.assertEqual(rc, 1, msg=out[-2000:])
            self.assertIn("UNMEASURED FRACTION FAILED", out)
            self.assertEqual(len(_invocations(stub_log)), n_before,
                             "no slice was re-screened — the "
                             "edited summaries reached the merge")
            summary = json.loads(
                (run / "summary.json").read_text())
            # Conservation still holds — the failure is the
            # unmeasured threshold alone.
            self.assertTrue(summary["conservation"]["ok"])
            unm = summary["unmeasured"]
            self.assertFalse(unm["ok"])
            self.assertEqual(unm["count"], 1)
            self.assertAlmostEqual(unm["fraction"], 0.1)
            self.assertEqual(unm["threshold"], 0.05)
            self.assertEqual(summary["stars_measured"], 9)
            manifest = json.loads(
                (run / "manifest.json").read_text())
            self.assertEqual(manifest["execution"]["status"],
                             "failed")
            self.assertEqual(
                manifest["counts"]["stars_measured"], 9)
            self.assertFalse(
                manifest["counts"]["unmeasured"]["ok"])

    def test_clean_run_records_measured(self):
        with tempfile.TemporaryDirectory() as td:
            work, recipe = _build_workdir(td)
            stub_log = Path(td) / "invocations.log"
            rc, out = _run_driver(work, recipe, stub_log)
            self.assertEqual(rc, 0, msg=out[-2000:])
            run = work / "run_s0999"
            summary = json.loads(
                (run / "summary.json").read_text())
            self.assertTrue(summary["unmeasured"]["ok"])
            self.assertEqual(summary["unmeasured"]["count"], 0)
            self.assertEqual(summary["stars_searched"], 10)
            self.assertEqual(summary["stars_measured"], 10)
            self.assertIn("10 measured (10 searched)", out)


class TestStarsMeasured(unittest.TestCase):
    def test_measured_of_prefers_recorded_value(self):
        self.assertEqual(
            _measured_of({"stars_searched": 10,
                          "stars_measured": 9,
                          "screen_counts": {"unmeasured": 1}}), 9)

    def test_measured_of_falls_back_for_old_summaries(self):
        # No stars_measured field (old summaries, the stub):
        # searched minus unmeasured.
        self.assertEqual(
            _measured_of({"stars_searched": 10,
                          "screen_counts": {"unmeasured": 3}}), 7)
        self.assertEqual(
            _measured_of({"stars_searched": 10,
                          "screen_counts": {}}), 10)

    def test_ledger_counts_measured(self):
        # From a stub run: measured == searched (0 unmeasured).
        with tempfile.TemporaryDirectory() as td:
            work, recipe = _build_workdir(td)
            rc, out = _run_driver(work, recipe,
                                  Path(td) / "inv.log")
            self.assertEqual(rc, 0, msg=out[-2000:])
            ledger = build_ledger.build_ledger(
                999, work / "run_s0999")
            self.assertEqual(ledger["counts"]["searched"], 10)
            self.assertEqual(ledger["counts"]["measured"], 10)

    def test_ledger_measured_falls_back(self):
        # An old-style summary (no stars_measured, unmeasured
        # in screen_counts): measured == searched - unmeasured.
        with tempfile.TemporaryDirectory() as td:
            run = Path(td) / "run"
            run.mkdir()
            (run / "summary.json").write_text(json.dumps({
                "sector": 96, "stars_in": 5, "stars_searched": 5,
                "hits_recorded": 1, "survivors": 1,
                "survivor_tiers": {"A": 1, "B": 0},
                "screen_counts": {"survivor": 1, "recorded": 2,
                                  "unmeasured": 2},
                "survivor_tics": ["111"],
                "provenance": {
                    "run_id": "legacy", "calibration_version":
                    "bulk_v1", "pipeline_git_sha": "abc",
                    "recipe_hash": "d" * 64}}))
            (run / "survivors.jsonl").write_text(
                '{"tic": "111", "tier": "A"}\n')
            ledger = build_ledger.build_ledger(96, run)
            self.assertEqual(ledger["counts"]["searched"], 5)
            self.assertEqual(ledger["counts"]["measured"], 3)


if __name__ == "__main__":
    unittest.main()
