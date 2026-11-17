"""Conservation-check tests (Phase 1.2, item A-7).

The window must be conserved: every star in the window ends up
in exactly one bucket, and every screened survivor ends up
merged or removed with a named reason. Unit tests drive the
pure check_conservation() with fabricated slice summaries;
end-to-end tests drive the chunked driver behind the stub
screen (same harness as test_resume.py) — no downloads, no
network.
"""
import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bulk.run_chunked import check_conservation  # noqa: E402
from tests.test_resume import (  # noqa: E402
    EXPECTED_SURVIVORS, TICS, _build_workdir, _run_driver)


def _slice(stars_in=4, toi=0, vsx=0, no_product=0, errors=0,
           counts=None, zoo=()):
    """A well-formed slice summary. The default conserves:
    4 in, 0 filtered, 4 searched, 1 survivor + 3 recorded."""
    counts = dict(counts) if counts is not None else {
        "survivor": 1, "recorded": 3}
    searched = sum(counts.values())
    return {
        "stars_in": stars_in,
        "skipped_known": {"toi": toi, "vsx": vsx},
        "stars_after_filter": stars_in - toi - vsx,
        "download": {"downloaded": searched, "cached": 0,
                     "no_product": no_product, "errors": errors,
                     "bytes": 0, "seconds": 0},
        "stars_searched": searched,
        "screen_counts": counts,
        "zooniverse_known_survivors": list(zoo),
    }


class TestCheckConservation(unittest.TestCase):
    def test_veto_bucket_balances(self):
        # P3-15: a merge-stage veto demotion is a named removal
        # reason in equation 5 — the run conserves only when
        # the veto count is passed in.
        slices = [_slice(), _slice(counts={"survivor": 2,
                                           "recorded": 1,
                                           "below_floor": 1})]
        # 8 window stars, 3 screened survivors, 1 merged + 1
        # TOI + 1 veto-demoted.
        ok, buckets, problems = check_conservation(
            8, slices, merged_survivors=1, toi_removed=1,
            vsx_removed=0, veto_removed=1)
        self.assertTrue(ok, msg=problems)
        self.assertEqual(buckets["survivors_veto"], 1)
        # Without the veto count the same run fails: the
        # demoted survivor is unaccounted for.
        ok, _b, problems = check_conservation(
            8, slices, merged_survivors=1, toi_removed=1,
            vsx_removed=0)
        self.assertFalse(ok)
        self.assertTrue(any("do not conserve" in p
                            for p in problems))

    def test_balanced_run_passes(self):
        slices = [_slice(), _slice(counts={"survivor": 2,
                                           "recorded": 1,
                                           "below_floor": 1})]
        # Slice 0: 4 in, 1 survivor. Slice 1: 4 in, 2 survivors.
        # 8 window stars, 3 screened survivors, 2 merged + 1
        # removed as a TOI.
        ok, buckets, problems = check_conservation(
            8, slices, merged_survivors=2, toi_removed=1,
            vsx_removed=0)
        self.assertTrue(ok, msg=problems)
        self.assertEqual(buckets["window"], 8)
        self.assertEqual(buckets["slices_in"], 8)
        self.assertEqual(buckets["searched"], 8)
        self.assertEqual(buckets["survivors_screened"], 3)
        self.assertEqual(buckets["screen_counts"],
                         {"survivor": 3, "recorded": 4,
                          "below_floor": 1})

    def test_known_filter_and_download_buckets(self):
        # A slice with a real filter + download failures still
        # conserves: 10 in = 1 TOI + 1 VSX + 8 kept; 8 kept =
        # 6 searched + 1 no-product + 1 error.
        s = _slice(stars_in=10, toi=1, vsx=1, no_product=1,
                   errors=1,
                   counts={"survivor": 1, "recorded": 3,
                           "error": 2})
        ok, buckets, problems = check_conservation(
            10, [s], merged_survivors=1, toi_removed=0,
            vsx_removed=0)
        self.assertTrue(ok, msg=problems)
        self.assertEqual(buckets["known_toi"], 1)
        self.assertEqual(buckets["known_vsx"], 1)
        self.assertEqual(buckets["download_no_product"], 1)
        self.assertEqual(buckets["download_errors"], 1)

    def test_slices_must_cover_the_window(self):
        ok, _b, problems = check_conservation(
            9, [_slice()], merged_survivors=1, toi_removed=0,
            vsx_removed=0)
        self.assertFalse(ok)
        self.assertTrue(any("window" in p for p in problems))

    def test_filter_must_conserve(self):
        s = _slice()
        s["stars_after_filter"] = 3  # 0 + 0 + 3 != 4 in
        ok, _b, problems = check_conservation(
            4, [s], merged_survivors=1, toi_removed=0,
            vsx_removed=0)
        self.assertFalse(ok)
        self.assertTrue(any("filter" in p for p in problems))

    def test_download_must_conserve(self):
        s = _slice()
        s["download"]["no_product"] = 1  # 4 + 1 + 0 != 4 kept
        ok, _b, problems = check_conservation(
            4, [s], merged_survivors=1, toi_removed=0,
            vsx_removed=0)
        self.assertFalse(ok)
        self.assertTrue(any("download" in p for p in problems))

    def test_screen_counts_must_sum_to_searched(self):
        s = _slice()
        s["screen_counts"]["recorded"] = 2  # sum 3 != 4
        ok, _b, problems = check_conservation(
            4, [s], merged_survivors=1, toi_removed=0,
            vsx_removed=0)
        self.assertFalse(ok)
        self.assertTrue(any("screen counts" in p
                            for p in problems))

    def test_unmeasured_status_conserves(self):
        # C-1: a star the per-star watchdog timed out is a final
        # status like any other — it conserves, it is not a
        # dropped star.
        s = _slice(counts={"survivor": 1, "recorded": 2,
                           "unmeasured": 1})
        ok, buckets, problems = check_conservation(
            4, [s], merged_survivors=1, toi_removed=0,
            vsx_removed=0)
        self.assertTrue(ok, msg=problems)
        self.assertEqual(buckets["screen_counts"]["unmeasured"], 1)

    def test_unknown_status_is_a_problem(self):
        # "searched" is the pre-screen placeholder: if it leaks
        # into a summary's counts, a record never got a final
        # status and the partition is broken.
        s = _slice(counts={"survivor": 1, "recorded": 2,
                           "searched": 1})
        ok, _b, problems = check_conservation(
            4, [s], merged_survivors=1, toi_removed=0,
            vsx_removed=0)
        self.assertFalse(ok)
        self.assertTrue(any("searched" in p for p in problems))

    def test_survivors_must_conserve(self):
        # 1 screened survivor, 0 merged, 0 removed: a survivor
        # vanished between the slice and the merge.
        ok, _b, problems = check_conservation(
            4, [_slice()], merged_survivors=0, toi_removed=0,
            vsx_removed=0)
        self.assertFalse(ok)
        self.assertTrue(any("survivors" in p for p in problems))

    def test_missing_bucket_fails_closed(self):
        s = _slice()
        del s["download"]
        ok, _b, problems = check_conservation(
            4, [s], merged_survivors=1, toi_removed=0,
            vsx_removed=0)
        self.assertFalse(ok)
        self.assertTrue(any("download" in p for p in problems))

    def test_zooniverse_removals_count(self):
        # A survivor removed by the Zooniverse annotation is
        # accounted for, not lost.
        s = _slice(zoo=["100000003"])
        ok, buckets, problems = check_conservation(
            4, [s], merged_survivors=0, toi_removed=0,
            vsx_removed=0)
        self.assertTrue(ok, msg=problems)
        self.assertEqual(buckets["survivors_zooniverse"], 1)


class TestConservationEndToEnd(unittest.TestCase):
    def test_stub_run_conserves(self):
        with tempfile.TemporaryDirectory() as td:
            work, recipe = _build_workdir(td)
            stub_log = Path(td) / "invocations.log"
            rc, out = _run_driver(work, recipe, stub_log)
            self.assertEqual(rc, 0, msg=out[-2000:])
            run = work / "run_s0999"
            summary = json.loads(
                (run / "summary.json").read_text())
            cons = summary["conservation"]
            self.assertTrue(cons["ok"], msg=cons["problems"])
            self.assertEqual(cons["buckets"]["window"], len(TICS))
            self.assertEqual(cons["buckets"]["searched"],
                             len(TICS))
            self.assertEqual(
                cons["buckets"]["survivors_screened"],
                len(EXPECTED_SURVIVORS))
            self.assertEqual(cons["buckets"]["survivors_merged"],
                             len(EXPECTED_SURVIVORS))
            self.assertEqual(cons["problems"], [])
            manifest = json.loads(
                (run / "manifest.json").read_text())
            self.assertEqual(manifest["execution"]["status"],
                             "completed")
            self.assertTrue(
                manifest["counts"]["conservation"]["ok"])

    def test_lost_survivor_fails_the_run(self):
        # Delete one survivor line from a slice's survivors.jsonl
        # AND forge the checkpoint entry to match the tampered
        # file (recompute its survivors_sha256). The C-2 output
        # hashes would otherwise heal this: a tampered output
        # with a stale checkpoint hash is re-screened from
        # scratch, and the survivor comes back. Forging the hash
        # models corruption that predates checkpointing (or
        # defeats it) — the case only the conservation check can
        # catch. The merge re-runs, the survivor equation breaks,
        # and the run FAILS with the buckets recorded — exit 1,
        # manifest status "failed".
        with tempfile.TemporaryDirectory() as td:
            work, recipe = _build_workdir(td)
            stub_log = Path(td) / "invocations.log"
            rc, out = _run_driver(work, recipe, stub_log)
            self.assertEqual(rc, 0, msg=out[-2000:])
            run = work / "run_s0999"
            chunk0 = run / "chunk_00" / "survivors.jsonl"
            lines = chunk0.read_text().splitlines()
            self.assertEqual(len(lines), 1)  # TIC 100000002
            chunk0.write_text("")
            # Forge the checkpoint: recompute the entry's output
            # hash over the tampered file, so the slice is
            # trusted as done and the loss reaches the merge.
            cp_path = run / "checkpoint.json"
            cp = json.loads(cp_path.read_text())
            cp["completed"]["0"]["survivors_sha256"] = \
                hashlib.sha256(b"").hexdigest()
            cp_path.write_text(json.dumps(cp))
            rc, out = _run_driver(work, recipe, stub_log)
            self.assertEqual(rc, 1, msg=out[-2000:])
            self.assertIn("CONSERVATION FAILED", out)
            summary = json.loads(
                (run / "summary.json").read_text())
            cons = summary["conservation"]
            self.assertFalse(cons["ok"])
            self.assertTrue(any("survivors" in p
                                for p in cons["problems"]))
            self.assertEqual(cons["buckets"]["survivors_merged"],
                             len(EXPECTED_SURVIVORS) - 1)
            manifest = json.loads(
                (run / "manifest.json").read_text())
            self.assertEqual(manifest["execution"]["status"],
                             "failed")


if __name__ == "__main__":
    unittest.main()
