"""Network-timeout tests (Phase 1.2, item C-1).

Every network call must be bounded: "MAST hung" is a code issue
— the wait was unbounded. These tests prove the bounds, all
offline (no real network): slow callables stand in for hung
MAST calls, a monkeypatched requests.get stands in for the
network, and a file:// URL stands in for a download.

  * run_with_timeout / mast_call — a fast call returns its
    value; a slow call raises NetworkTimeout after the bound;
    an exception inside the call propagates unchanged.
  * http_get — retries connection failures with backoff, returns
    on recovery, raises NetworkTimeout when every attempt times
    out.
  * download_file — streams a file:// URL to disk with a timeout
    and an atomic rename (no .part litter).
  * _with_download_self_heal — a hung step is retried as a
    connection failure and finally raises NetworkTimeout; a fast
    step is unaffected by the default bound.
  * _collect_screen_results — a star whose screen exceeds the
    per-star watchdog is recorded unmeasured with a reason and
    the other stars still screen.
  * repeated timeouts (F-17) — 20 consecutive timed-out calls
    leave no threads behind once their bounded functions
    return: the watchdog does not accumulate.
"""
import sys
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import bulk_screen as bs  # noqa: E402
import hunter  # noqa: E402
import netbound as net  # noqa: E402
import requests  # noqa: E402


class TestRunWithTimeout(unittest.TestCase):
    def test_fast_call_returns_value(self):
        self.assertEqual(
            net.run_with_timeout(lambda: 42, 5.0, "fast"), 42)

    def test_slow_call_raises_network_timeout(self):
        t0 = time.monotonic()
        with self.assertRaises(net.NetworkTimeout):
            net.run_with_timeout(lambda: time.sleep(5), 0.2, "slow")
        self.assertLess(time.monotonic() - t0, 2.0)

    def test_exception_propagates_unchanged(self):
        def _boom():
            raise ValueError("original")
        with self.assertRaisesRegex(ValueError, "original"):
            net.run_with_timeout(_boom, 5.0, "boom")

    def test_mast_call_is_the_same_watchdog(self):
        with self.assertRaises(net.NetworkTimeout):
            net.mast_call(lambda: time.sleep(5), timeout_s=0.2,
                          name="mast")


class TestRepeatedTimeoutStress(unittest.TestCase):
    """F-17: repeated timeouts must not accumulate threads.

    Each timed-out run_with_timeout call leaves its daemon
    thread alive until the underlying fn returns — a Python
    thread cannot be killed. A fn that hung FOREVER would
    leave N threads alive by design; this test uses
    bounded-blocking fns (0.5 s sleeps against a 0.05 s
    timeout), which is the honest form of "no accumulation":
    after the burst, the thread count must drain back to
    baseline. No rewrite, no multiprocessing — the test only
    proves what the watchdog already guarantees.
    """

    def test_twenty_timeouts_leave_no_threads_behind(self):
        baseline = threading.active_count()

        def slow():
            time.sleep(0.5)

        t0 = time.monotonic()
        for _ in range(20):
            with self.assertRaises(net.NetworkTimeout):
                net.run_with_timeout(slow, 0.05, name="stress")
        burst = time.monotonic() - t0
        # The burst is bounded by the TIMEOUT (20 x 0.05 s),
        # not by the fns (20 x 0.5 s).
        self.assertLess(burst, 5.0)
        # The last few daemon threads are still alive (their
        # fns sleep 0.5 s); poll up to 10 s for the count to
        # drain back to baseline.
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            if threading.active_count() <= baseline:
                break
            time.sleep(0.1)
        self.assertLessEqual(threading.active_count(), baseline)
        # The watchdog still works after the burst.
        self.assertEqual(
            net.run_with_timeout(lambda: 42, 1.0, name="after"),
            42)


class TestHttpGet(unittest.TestCase):
    def test_success_first_try(self):
        resp = mock.Mock(status_code=200)
        with mock.patch.object(net.requests, "get",
                               return_value=resp) as get:
            self.assertIs(net.http_get("http://x.invalid/"), resp)
            get.assert_called_once()
            _args, kwargs = get.call_args
            self.assertEqual(kwargs["timeout"],
                             (net.CONNECT_TIMEOUT_S,
                              net.READ_TIMEOUT_S))

    def test_retries_then_recovers(self):
        resp = mock.Mock(status_code=200)
        side = [requests.exceptions.ConnectionError("down"),
                requests.exceptions.ConnectionError("down"),
                resp]
        with mock.patch.object(net.requests, "get",
                               side_effect=side) as get:
            self.assertIs(net.http_get("http://x.invalid/",
                                       retries=3,
                                       backoff=(0.0, 0.0)), resp)
            self.assertEqual(get.call_count, 3)

    def test_all_timeouts_raise_network_timeout(self):
        with mock.patch.object(
                net.requests, "get",
                side_effect=requests.exceptions.ReadTimeout(
                    "slow")) as get:
            with self.assertRaises(net.NetworkTimeout):
                net.http_get("http://x.invalid/", retries=2,
                             backoff=(0.0,))
            self.assertEqual(get.call_count, 2)


class TestDownloadFile(unittest.TestCase):
    def test_file_url_downloads_and_renames(self):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "src.csv"
            src.write_bytes(b"tic,ra,dec\n1,2,3\n")
            dest = Path(td) / "out.csv"
            n = net.download_file(src.as_uri(), dest)
            self.assertEqual(n, len(b"tic,ra,dec\n1,2,3\n"))
            self.assertEqual(dest.read_bytes(), src.read_bytes())
            # No .part litter left behind.
            self.assertEqual(sorted(p.name for p in Path(td).iterdir()),
                             ["out.csv", "src.csv"])


class TestSelfHealTimeout(unittest.TestCase):
    def test_hung_step_retries_then_raises_network_timeout(self):
        calls = []

        def _hang():
            calls.append(1)
            time.sleep(5)

        t0 = time.monotonic()
        with self.assertRaises(net.NetworkTimeout):
            hunter._with_download_self_heal(
                _hang, progress_callback=lambda _m: None,
                connection_max_attempts=2,
                connection_backoff_seconds=(0.01,),
                timeout_s=0.1, timeout_name="test hang")
        # Two attempts (the connection budget), each bounded at
        # 0.1 s — the whole thing returns in well under the
        # 5 s the step would have taken once.
        self.assertEqual(len(calls), 2)
        self.assertLess(time.monotonic() - t0, 4.0)

    def test_fast_step_unaffected_by_default_bound(self):
        self.assertEqual(
            hunter._with_download_self_heal(
                lambda: "ok", progress_callback=lambda _m: None),
            "ok")


def _fake_worker(job):
    tic, _path, _sector, _star = job
    if tic == "slow":
        time.sleep(5)
        return {"tic": tic, "status": "recorded"}
    return {"tic": tic, "status": "recorded"}


class TestCollectScreenResults(unittest.TestCase):
    def test_watchdog_records_unmeasured_and_continues(self):
        jobs = [("fast", "/dev/null", 1, {}),
                ("slow", "/dev/null", 1, {}),
                ("fast2", "/dev/null", 1, {})]
        t0 = time.monotonic()
        with ThreadPoolExecutor(max_workers=3) as ex:
            records, counts = bs._collect_screen_results(
                ex, jobs, _fake_worker, timeout_s=0.3)
        # The slow star was recorded unmeasured (not waited on);
        # the fast stars still screened.
        by_tic = {r["tic"]: r for r in records}
        self.assertEqual(by_tic["slow"]["status"], "unmeasured")
        self.assertIn("watchdog_timeout",
                      by_tic["slow"]["reason"])
        self.assertEqual(by_tic["fast"]["status"], "recorded")
        self.assertEqual(by_tic["fast2"]["status"], "recorded")
        self.assertEqual(counts["unmeasured"], 1)
        self.assertEqual(counts["recorded"], 2)
        # Records are sorted by TIC (deterministic output order).
        self.assertEqual([r["tic"] for r in records],
                         ["fast", "fast2", "slow"])
        # The whole collection took ~the watchdog bound, not the
        # slow star's 5 s (plus executor shutdown joining the
        # daemon-less pool thread — bounded by the sleep).
        self.assertLess(time.monotonic() - t0, 8.0)


if __name__ == "__main__":
    unittest.main()
