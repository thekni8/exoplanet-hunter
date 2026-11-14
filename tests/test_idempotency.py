"""Crash-boundary + idempotency tests (Phase 1.2, item C-2).

  * work_item_id — deterministic identity of one unit of screen
    work (TIC + sector + code fingerprint + calibration hash +
    recipe hash). NO input hash in the identity: it must be
    computable before any download, so resume can skip finished
    items cheaply; the input hash is verified afterwards.
  * Crash boundaries — the stub screen's --die-at seam kills the
    slice at each write boundary (before/after survivors.jsonl,
    after screen_hits.jsonl); the driver must resume cleanly
    from any of these states with byte-identical merged output.
    A slice completed but never checkpointed (crash between
    slice write and checkpoint update) is re-derived from
    chunk_ok, not re-screened. A corrupt manifest is replaced,
    never trusted.
  * Output-hash verification — a checkpoint entry whose summary
    matches but whose output hash does not (outputs altered
    after checkpointing) forces a re-screen; a merely stale
    entry (summary mismatch) lets chunk_ok decide, as before.
  * Merge idempotency — running the driver twice over a
    completed run reproduces byte-identical merged outputs.
"""
import inspect
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import bulk_screen as bs  # noqa: E402
import provenance as prov  # noqa: E402
from bulk.run_chunked import (  # noqa: E402
    _checkpoint_entry, _checkpoint_entry_status,
    _checkpoint_hashes_match)
from synth_fits import make_qlp_fits  # noqa: E402
from tests.test_resume import (  # noqa: E402
    DRIVER, EXPECTED_SURVIVORS, STUB, TICS, _build_workdir,
    _invocations, _merged_survivors, _run_driver,
    _seed_run_with_checkpoint)

FP = "a" * 64
CAL = "b" * 64
RECIPE = "c" * 64


class TestWorkItemId(unittest.TestCase):
    def test_deterministic(self):
        a = prov.work_item_id("123", 96, FP, CAL, RECIPE)
        b = prov.work_item_id("123", 96, FP, CAL, RECIPE)
        self.assertEqual(a, b)
        self.assertEqual(len(a), 64)
        int(a, 16)  # hex

    def test_sensitive_to_every_component(self):
        base = prov.work_item_id("123", 96, FP, CAL, RECIPE)
        self.assertNotEqual(
            base, prov.work_item_id("124", 96, FP, CAL, RECIPE))
        self.assertNotEqual(
            base, prov.work_item_id("123", 97, FP, CAL, RECIPE))
        self.assertNotEqual(
            base, prov.work_item_id("123", 96, "d" * 64, CAL,
                                    RECIPE))
        self.assertNotEqual(
            base, prov.work_item_id("123", 96, FP, "d" * 64,
                                    RECIPE))
        self.assertNotEqual(
            base, prov.work_item_id("123", 96, FP, CAL,
                                    "d" * 64))

    def test_no_input_hash_in_the_identity(self):
        # The id must be computable BEFORE any download — so it
        # cannot depend on the input. Two runs over different
        # input files (different BLS input hashes) but the same
        # star/code/calibration/recipe share one id; and the
        # signature carries no input parameter at all.
        params = inspect.signature(prov.work_item_id).parameters
        self.assertNotIn("input_hash", params)
        self.assertNotIn("bls_input_hash", params)
        a = prov.work_item_id("123", 96, FP, CAL, RECIPE)
        b = prov.work_item_id("123", 96, FP, CAL, RECIPE)
        self.assertEqual(a, b)


class TestWorkItemIdStamped(unittest.TestCase):
    def setUp(self):
        self._previous = bs.CALIBRATION_VERSION

    def tearDown(self):
        bs.set_calibration(self._previous)

    def test_screen_stamps_work_item_id_on_every_record(self):
        with tempfile.TemporaryDirectory() as td:
            cache = Path(td) / "cache" / "s0096"
            cache.mkdir(parents=True)
            # A transiting star (a hit) and a null (recorded only
            # if above the floor — either way, every emitted
            # record must carry the id).
            make_qlp_fits(cache / "111111111.fits", period_d=2.17,
                          depth_frac=0.01, noise_pct=0.003, seed=7)
            make_qlp_fits(cache / "222222222.fits", period_d=None,
                          noise_pct=0.003, seed=7)
            for f in cache.iterdir():
                # Download-all treats <=1000-byte files as
                # missing and would hit the network.
                self.assertGreater(f.stat().st_size, 1000)
            stars = Path(td) / "stars.csv"
            stars.write_text(
                "tic,ra,dec,tmag,radius\n"
                "111111111,100.0,-65.0,12.0,0.7\n"
                "222222222,100.1,-65.0,12.1,0.7\n")
            out = Path(td) / "out"
            rc = bs.main(["--sector", "96", "--stars-file",
                          str(stars), "--skip-filter",
                          "--cache-dir", str(Path(td) / "cache"),
                          "--out-dir", str(out), "--workers", "1"])
            self.assertEqual(rc, 0)
            fp = prov.fingerprint_result_affecting()
            cal = prov.calibration_content_hash({"bulk": "v1"})
            for name in ("survivors.jsonl", "screen_hits.jsonl"):
                with open(out / name) as fh:
                    recs = [json.loads(line) for line in fh]
                for r in recs:
                    self.assertEqual(
                        r["work_item_id"],
                        prov.work_item_id(r["tic"], 96, fp, cal,
                                          None))


def _run_driver_die(work, recipe, stub_log, die_at, timeout=120):
    """The driver with a stub that dies at `die_at` on every
    invocation. Returns (returncode, stdout)."""
    env = dict(os.environ)
    env["EXHUNT_SCREEN_CMD"] = (
        f"{sys.executable} {STUB} --die-at {die_at}")
    env["EXHUNT_STUB_LOG"] = str(stub_log)
    cmd = [sys.executable, str(DRIVER), "--recipe", str(recipe),
           "--work-dir", str(work), "--skip-known-filter"]
    r = subprocess.run(cmd, capture_output=True, text=True,
                       env=env, timeout=timeout)
    return r.returncode, r.stdout + r.stderr


class TestCrashBoundaries(unittest.TestCase):
    def _control(self, td):
        work_c, recipe_c = _build_workdir(Path(td) / "control")
        rc, out = _run_driver(work_c, recipe_c,
                              Path(td) / "control.log")
        self.assertEqual(rc, 0, msg=out[-2000:])
        return _merged_survivors(work_c / "run_s0999")

    def test_die_before_survivors_resumes_clean(self):
        self._die_point_resumes("before-survivors")

    def test_die_after_survivors_resumes_clean(self):
        self._die_point_resumes("after-survivors")

    def test_die_after_hits_resumes_clean(self):
        self._die_point_resumes("after-hits")

    def _die_point_resumes(self, die_at):
        with tempfile.TemporaryDirectory() as td:
            control = self._control(td)
            work, recipe = _build_workdir(Path(td) / "kill")
            stub_log = Path(td) / "kill.log"
            rc, _out = _run_driver_die(work, recipe, stub_log,
                                       die_at)
            self.assertNotEqual(rc, 0)
            # Slice 0 is incomplete (no summary — the chunk
            # checkpoint); the driver died at slice 0.
            run = work / "run_s0999"
            self.assertFalse(
                (run / "chunk_00" / "summary.json").exists())
            # Re-run with the healthy stub: completes, and the
            # merged output is exactly the control's — no
            # duplicates from the partial slice, no drops.
            rc, out = _run_driver(work, recipe, stub_log)
            self.assertEqual(rc, 0, msg=out[-2000:])
            self.assertEqual(_merged_survivors(run), control)
            inv = _invocations(stub_log)
            self.assertEqual(inv.count("slice_00.csv"), 2)
            self.assertEqual(inv.count("slice_01.csv"), 1)
            self.assertEqual(inv.count("slice_02.csv"), 1)

    def test_complete_slice_without_checkpoint_is_not_rescreened(self):
        # Crash between the slice write and the checkpoint
        # update: the slice is complete, no checkpoint exists.
        # chunk_ok re-derives the truth — the slice is skipped,
        # not re-screened, and the checkpoint is rebuilt.
        with tempfile.TemporaryDirectory() as td:
            control = self._control(td)
            work, recipe, run = _seed_run_with_checkpoint(
                td, prov.fingerprint_result_affecting())
            (run / "checkpoint.json").unlink()
            stub_log = Path(td) / "invocations.log"
            rc, out = _run_driver(work, recipe, stub_log)
            self.assertEqual(rc, 0, msg=out[-2000:])
            inv = _invocations(stub_log)
            self.assertNotIn("slice_00.csv", inv)
            self.assertIn("slice_01.csv", inv)
            self.assertIn("slice_02.csv", inv)
            self.assertEqual(_merged_survivors(run), control)
            cp = json.loads((run / "checkpoint.json").read_text())
            self.assertEqual(sorted(int(k)
                                    for k in cp["completed"]),
                             [0, 1, 2])

    def test_corrupt_manifest_is_replaced_not_trusted(self):
        with tempfile.TemporaryDirectory() as td:
            work, recipe = _build_workdir(td)
            stub_log = Path(td) / "invocations.log"
            rc, out = _run_driver(work, recipe, stub_log)
            self.assertEqual(rc, 0, msg=out[-2000:])
            run = work / "run_s0999"
            (run / "manifest.json").write_text(
                '{"run_id": "truncated')
            rc, out = _run_driver(work, recipe, stub_log)
            self.assertEqual(rc, 0, msg=out[-2000:])
            manifest = json.loads(
                (run / "manifest.json").read_text())
            self.assertEqual(manifest["execution"]["status"],
                             "completed")
            self.assertEqual(
                [r["tic"] for r in _merged_survivors(run)],
                EXPECTED_SURVIVORS)

    def test_merge_is_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            work, recipe = _build_workdir(td)
            stub_log = Path(td) / "invocations.log"
            rc, out = _run_driver(work, recipe, stub_log)
            self.assertEqual(rc, 0, msg=out[-2000:])
            run = work / "run_s0999"
            first_surv = (run / "survivors.jsonl").read_bytes()
            first_hits = (run / "screen_hits.jsonl").read_bytes()
            rc, out = _run_driver(work, recipe, stub_log)
            self.assertEqual(rc, 0, msg=out[-2000:])
            self.assertEqual((run / "survivors.jsonl").read_bytes(),
                             first_surv)
            self.assertEqual((run / "screen_hits.jsonl").read_bytes(),
                             first_hits)
            # The second run screened nothing (all slices
            # skipped via chunk_ok).
            self.assertEqual(_invocations(stub_log).count(
                "slice_00.csv"), 1)


class TestCheckpointOutputHashes(unittest.TestCase):
    def test_outputs_changed_forces_rescreen(self):
        # A checkpoint whose summary hash is CORRECT but whose
        # survivors hash is wrong: the outputs changed after
        # checkpointing. The driver must re-screen the slice —
        # merging altered outputs under an unchanged summary
        # would be silent data corruption.
        with tempfile.TemporaryDirectory() as td:
            work, recipe, run = _seed_run_with_checkpoint(
                td, prov.fingerprint_result_affecting())
            chunk00 = run / "chunk_00"
            entry = _checkpoint_entry(
                chunk00,
                json.loads(
                    (chunk00 / "summary.json").read_text()))
            entry["survivors_sha256"] = "0" * 64  # tampered
            cp = json.loads((run / "checkpoint.json").read_text())
            cp["completed"]["0"] = entry
            (run / "checkpoint.json").write_text(json.dumps(cp))
            stub_log = Path(td) / "invocations.log"
            rc, out = _run_driver(work, recipe, stub_log)
            self.assertEqual(rc, 0, msg=out[-2000:])
            inv = _invocations(stub_log)
            self.assertIn("slice_00.csv", inv)
            self.assertIn("re-screening", out)
            got = [r["tic"] for r in _merged_survivors(run)]
            self.assertEqual(got, EXPECTED_SURVIVORS)

    def test_entry_status_unit(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "chunk_00"
            out.mkdir()
            (out / "summary.json").write_text('{"a": 1}')
            (out / "survivors.jsonl").write_text('{"tic": "1"}\n')
            (out / "screen_hits.jsonl").write_text(
                '{"tic": "1"}\n')
            entry = _checkpoint_entry(out, {"stars_searched": 1,
                                            "survivors": 1})
            self.assertEqual(_checkpoint_entry_status(out, entry),
                             "ok")
            self.assertTrue(_checkpoint_hashes_match(out, entry))
            # Summary tampered -> stale.
            (out / "summary.json").write_text('{"a": 2}')
            self.assertEqual(_checkpoint_entry_status(out, entry),
                             "stale")
            self.assertFalse(_checkpoint_hashes_match(out, entry))
            # Summary restored, survivors tampered ->
            # outputs-changed.
            (out / "summary.json").write_text('{"a": 1}')
            (out / "survivors.jsonl").write_text(
                '{"tic": "2"}\n')
            self.assertEqual(_checkpoint_entry_status(out, entry),
                             "outputs-changed")
            # A pre-C-2 entry (summary hash only) with a matching
            # summary is ok — transitional compatibility.
            old = {"chunk": "chunk_00",
                   "summary_sha256": prov.file_sha256(
                       out / "summary.json")}
            self.assertEqual(_checkpoint_entry_status(out, old),
                             "ok")


if __name__ == "__main__":
    unittest.main()
