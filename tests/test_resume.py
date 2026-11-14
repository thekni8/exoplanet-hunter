"""Resumable-jobs tests (Phase 1.1, item 8).

The chunked driver screens a sector in slices; a VM replacement
kills the driver mid-slice, and the re-run must resume WITHOUT
duplicating or dropping stars. These tests prove that with a
deterministic stub screen (tests/stub_screen.py) behind the
EXHUNT_SCREEN_CMD seam, in a temp work dir (--work-dir) — no
downloads, no network (the merge's TOI/VSX stages are skipped
with --skip-known-filter):

  * test_uninterrupted_run — the control: 10 fake stars in 3
    slices run to completion; the merged survivors are exactly
    the deterministic set, each slice screened once.
  * test_kill_mid_slice_then_resume — the VM-kill test: the
    driver is SIGKILLed mid-slice-1 (the stub sleeps so the
    kill window is wide), then re-run to completion. The merged
    survivors must match the control EXACTLY (same TICs, same
    tiers, same MES — run_id/timestamp excluded, they differ
    per run by design), slice_00 must NOT be re-screened, and
    slice_01 must be re-screened from scratch.
  * test_partial_slice_not_checkpointed — a hand-seeded run dir
    with a complete slice_00, a PARTIAL slice_01 (truncated
    survivors, corrupt summary) and a checkpoint claiming both
    complete: the driver must distrust the checkpoint (hash
    mismatch) and re-screen slice_01.
  * TestAtomicWrites — the primitives: a failed atomic write
    leaves no partial target behind.
"""
import csv
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import provenance as prov  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
STUB = ROOT / "tests" / "stub_screen.py"
DRIVER = ROOT / "bulk" / "run_chunked.py"

TICS = [f"10000000{i}" for i in range(1, 10)] + ["100000010"]
# Deterministic stub rule: survivor iff int(tic) % 3 == 0.
EXPECTED_SURVIVORS = sorted(t for t in TICS if int(t) % 3 == 0)

RECIPE_YAML = """\
sector: 999
window:
  min_mag: 10.0
  max_mag: 13.5
  min_rad: 0.2
  max_rad: 0.8
  require_radius: true
  limit_ids: null
tag: window_resume
slice_size: 4
dl_workers: 1
workers: null
"""

WINDOW = {"tics": TICS,
          "stats": {"window": {"min_mag": 10.0, "max_mag": 13.5,
                               "min_rad": 0.2, "max_rad": 0.8,
                               "require_radius": True,
                               "limit_ids": None}}}


def _build_workdir(base):
    """A temp bulk/ work dir: window file + TIC csv + recipe."""
    work = Path(base) / "bulk"
    tl = work / "cache" / "target_lists"
    tl.mkdir(parents=True)
    (tl / "s0999_window_resume.json").write_text(
        json.dumps(WINDOW))
    with open(tl / "s0999_tic.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["tic", "ra", "dec", "tmag", "radius"])
        for i, t in enumerate(TICS):
            w.writerow([t, 100.0 + i, -65.0 + i * 0.1,
                        12.0 + i * 0.1, 0.5])
    recipe = Path(base) / "recipe.yaml"
    recipe.write_text(RECIPE_YAML)
    return work, recipe


def _run_driver(work, recipe, stub_log, sleep=0.0, timeout=120,
                extra_args=(), allow_v1=True):
    """Run the driver to completion in a subprocess. Returns
    (returncode, stdout). Sector 999 is outside the v1 sectors
    (96-98), so the F-15 driver gate requires --allow-v1 — it
    is passed by default; pass allow_v1=False to exercise the
    refusal."""
    env = dict(os.environ)
    env["EXHUNT_SCREEN_CMD"] = (
        f"{sys.executable} {STUB} --sleep {sleep}")
    env["EXHUNT_STUB_LOG"] = str(stub_log)
    cmd = [sys.executable, str(DRIVER), "--recipe", str(recipe),
           "--work-dir", str(work), "--skip-known-filter",
           *extra_args]
    if allow_v1:
        cmd += ["--allow-v1"]
    r = subprocess.run(cmd, capture_output=True, text=True,
                       env=env, timeout=timeout)
    return r.returncode, r.stdout + r.stderr


def _seed_run_with_checkpoint(td, fingerprint):
    """A run dir with slice_00 complete (stub-built) + a checkpoint
    claiming it, stamped with `fingerprint` (a hex string, or None
    to omit the key — a pre-A-3 checkpoint). The slice-00 entry's
    summary hash is CORRECT here (unlike the partial-slice test's
    hand-wrong one): the resume trusts the entry, so slice 00 is
    never re-screened. Returns (work, recipe, run)."""
    work, recipe = _build_workdir(td)
    run = work / "run_s0999"
    chunks = run / "chunks"
    chunks.mkdir(parents=True)
    slices = [TICS[i:i + 4] for i in range(0, len(TICS), 4)]
    for i, part in enumerate(slices):
        with open(chunks / f"slice_{i:02d}.csv", "w",
                  newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["tic", "ra", "dec", "tmag", "radius"])
            for t in part:
                gi = TICS.index(t)
                w.writerow([t, 100.0 + gi, -65.0 + gi * 0.1,
                            12.0 + gi * 0.1, 0.5])
    env = dict(os.environ)
    env["EXHUNT_STUB_LOG"] = str(Path(td) / "seed.log")
    subprocess.run(
        [sys.executable, str(STUB), "--sector", "999",
         "--stars-file", str(chunks / "slice_00.csv"),
         "--out-dir", str(run / "chunk_00"),
         "--run-id", "seed-run"],
        check=True, capture_output=True, env=env)
    cp = {"run_dir": str(run), "sector": 999, "n_slices": 1,
          "completed": {"0": {"chunk": "chunk_00",
                              "summary_sha256": prov.file_sha256(
                                  run / "chunk_00" / "summary.json"),
                              "stars_searched": 4, "survivors": 1}},
          "updated_at": "2026-11-14T00:00:00+00:00"}
    if fingerprint is not None:
        cp["code_fingerprint"] = fingerprint
    (run / "checkpoint.json").write_text(json.dumps(cp))
    return work, recipe, run


def _merged_survivors(run_dir):
    recs = [json.loads(l)
            for l in open(run_dir / "survivors.jsonl")]
    # run_id / timestamp differ per run by design; everything
    # else must be identical between runs.
    return sorted(
        ({k: v for k, v in r.items()
          if k not in ("run_id", "timestamp_utc")} for r in recs),
        key=lambda r: r["tic"])


def _invocations(stub_log):
    if not stub_log.exists():
        return []
    return stub_log.read_text().splitlines()


class TestResume(unittest.TestCase):
    def test_uninterrupted_run(self):
        with tempfile.TemporaryDirectory() as td:
            work, recipe = _build_workdir(td)
            stub_log = Path(td) / "invocations.log"
            rc, out = _run_driver(work, recipe, stub_log)
            self.assertEqual(rc, 0, msg=out[-2000:])
            run = work / "run_s0999"
            got = [r["tic"] for r in _merged_survivors(run)]
            self.assertEqual(got, EXPECTED_SURVIVORS)
            self.assertEqual(len(got), len(set(got)))  # no dupes
            hits = [json.loads(l)
                    for l in open(run / "screen_hits.jsonl")]
            self.assertEqual(sorted(r["tic"] for r in hits),
                             sorted(TICS))  # no drops
            cp = json.loads((run / "checkpoint.json").read_text())
            self.assertEqual(sorted(int(k) for k in cp["completed"]),
                             [0, 1, 2])
            # A-3: the checkpoint stamps the live code fingerprint
            # and the clean run is explicitly not mixed.
            self.assertEqual(cp["code_fingerprint"],
                             prov.fingerprint_result_affecting())
            self.assertFalse(cp["mixed_pipeline"])
            summary = json.loads(
                (run / "summary.json").read_text())
            self.assertFalse(summary["mixed_pipeline"])
            manifest = json.loads(
                (run / "manifest.json").read_text())
            self.assertFalse(manifest["mixed_pipeline"])
            inv = _invocations(stub_log)
            self.assertEqual(sorted(inv),
                             ["slice_00.csv", "slice_01.csv",
                              "slice_02.csv"])

    def test_kill_mid_slice_then_resume(self):
        with tempfile.TemporaryDirectory() as td:
            # Control run first (separate work dir, same inputs).
            work_c, recipe_c = _build_workdir(Path(td) / "control")
            rc, out = _run_driver(work_c, recipe_c,
                                  Path(td) / "control.log")
            self.assertEqual(rc, 0, msg=out[-2000:])
            control = _merged_survivors(work_c / "run_s0999")

            # Kill run: SIGKILL the driver mid-slice-1.
            work, recipe = _build_workdir(Path(td) / "kill")
            stub_log = Path(td) / "kill.log"
            env = dict(os.environ)
            env["EXHUNT_SCREEN_CMD"] = (
                f"{sys.executable} {STUB} --sleep 3.0")
            env["EXHUNT_STUB_LOG"] = str(stub_log)
            cmd = [sys.executable, str(DRIVER), "--recipe",
                   str(recipe), "--work-dir", str(work),
                   "--skip-known-filter", "--allow-v1"]
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True, env=env,
                start_new_session=True)
            run = work / "run_s0999"
            # Wait for slice 0 done + slice 1 started, then kill.
            deadline = time.time() + 60
            while time.time() < deadline:
                if ((run / "chunk_00" / "summary.json").exists()
                        and (run / "chunk_01").exists()):
                    break
                if proc.poll() is not None:
                    break
                time.sleep(0.02)
            self.assertIsNone(proc.poll(),
                              msg="driver finished before the kill "
                                  "window — widen the stub sleep")
            self.assertFalse(
                (run / "chunk_01" / "summary.json").exists(),
                msg="slice 1 already finished — the kill landed "
                    "too late")
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait(timeout=30)
            # The kill must not have checkpointed slice 1.
            self.assertFalse(
                (run / "chunk_01" / "summary.json").exists())
            chunk00_hash_before = json.loads(
                (run / "chunk_00" / "summary.json").read_text())

            # Re-run to completion.
            rc, out = _run_driver(work, recipe, stub_log)
            self.assertEqual(rc, 0, msg=out[-2000:])
            resumed = _merged_survivors(run)
            self.assertEqual(resumed, control)
            # Slice 0 was NOT re-screened; slice 1 was (killed +
            # re-run); slice 2 ran once.
            inv = _invocations(stub_log)
            self.assertEqual(inv.count("slice_00.csv"), 1)
            self.assertEqual(inv.count("slice_01.csv"), 2)
            self.assertEqual(inv.count("slice_02.csv"), 1)
            # Slice 0's outputs are untouched by the re-run.
            self.assertEqual(
                json.loads((run / "chunk_00"
                            / "summary.json").read_text()),
                chunk00_hash_before)
            cp = json.loads((run / "checkpoint.json").read_text())
            self.assertEqual(sorted(int(k) for k in cp["completed"]),
                             [0, 1, 2])

    def test_partial_slice_not_checkpointed(self):
        with tempfile.TemporaryDirectory() as td:
            work, recipe = _build_workdir(td)
            run = work / "run_s0999"
            chunks = run / "chunks"
            chunks.mkdir(parents=True)
            # Seed slice CSVs the way the driver builds them.
            import csv as _csv
            slices = [TICS[i:i + 4] for i in range(0, len(TICS), 4)]
            for i, part in enumerate(slices):
                with open(chunks / f"slice_{i:02d}.csv", "w",
                          newline="") as fh:
                    w = _csv.writer(fh)
                    w.writerow(["tic", "ra", "dec", "tmag",
                                "radius"])
                    for j, t in enumerate(part):
                        gi = TICS.index(t)
                        w.writerow([t, 100.0 + gi,
                                    -65.0 + gi * 0.1,
                                    12.0 + gi * 0.1, 0.5])
            # chunk_00: complete (built by the stub itself).
            env = dict(os.environ)
            env["EXHUNT_STUB_LOG"] = str(Path(td) / "seed.log")
            subprocess.run(
                [sys.executable, str(STUB), "--sector", "999",
                 "--stars-file", str(chunks / "slice_00.csv"),
                 "--out-dir", str(run / "chunk_00"),
                 "--run-id", "seed-run"],
                check=True, capture_output=True, env=env)
            # chunk_01: PARTIAL — truncated survivors, corrupt
            # summary (what a kill mid-slice used to leave).
            (run / "chunk_01").mkdir()
            (run / "chunk_01" / "survivors.jsonl").write_text(
                '{"tic": "100000005", "status": "survivor", '
                '"truncated": ')
            (run / "chunk_01" / "summary.json").write_text(
                '{"stars_searched": 4, "survivo')
            # A checkpoint claiming BOTH slices complete, with a
            # WRONG hash for slice 1 — the driver must distrust it.
            # The checkpoint itself carries the LIVE code
            # fingerprint (A-3): the seed simulates a checkpoint
            # from the same code — a docs-only change between
            # checkpoint and resume leaves the fingerprint equal
            # and must NOT refuse (the fingerprint property is
            # proven in test_provenance2; this test proves an
            # equal fingerprint resumes).
            (run / "checkpoint.json").write_text(json.dumps({
                "run_dir": str(run), "sector": 999, "n_slices": 2,
                "code_fingerprint":
                    prov.fingerprint_result_affecting(),
                "completed": {
                    "0": {"chunk": "chunk_00",
                          "summary_sha256": "seeded-by-hand",
                          "stars_searched": 4, "survivors": 1},
                    "1": {"chunk": "chunk_01",
                          "summary_sha256": "deadbeef",
                          "stars_searched": 4, "survivors": 2},
                },
                "updated_at": "2026-11-14T00:00:00+00:00"}))
            stub_log = Path(td) / "invocations.log"
            rc, out = _run_driver(work, recipe, stub_log)
            self.assertEqual(rc, 0, msg=out[-2000:])
            inv = _invocations(stub_log)
            # Slice 0 skipped (valid checkpoint); slice 1 + 2
            # screened (slice 1's partial state was discarded).
            self.assertNotIn("slice_00.csv", inv)
            self.assertIn("slice_01.csv", inv)
            self.assertIn("slice_02.csv", inv)
            got = [r["tic"] for r in _merged_survivors(run)]
            self.assertEqual(got, EXPECTED_SURVIVORS)


class TestResumeCodeChange(unittest.TestCase):
    """A-3: a mid-screen code fix must not silently mix two
    pipelines in one sector. The resume compares the fingerprint
    of RESULT-AFFECTING files (not the git SHA) and refuses on
    mismatch unless --accept-code-change, which stamps
    mixed_pipeline=true."""

    def test_resume_refuses_code_change(self):
        with tempfile.TemporaryDirectory() as td:
            work, recipe, run = _seed_run_with_checkpoint(
                td, "0" * 64)
            stub_log = Path(td) / "invocations.log"
            rc, out = _run_driver(work, recipe, stub_log)
            self.assertNotEqual(rc, 0)
            self.assertIn("REFUSING TO RESUME", out)
            self.assertIn("fingerprint", out)
            self.assertIn("--accept-code-change", out)
            # The refusal lands before the slice loop: nothing
            # was screened.
            self.assertEqual(_invocations(stub_log), [])

    def test_accept_code_change_resumes_and_stamps_mixed(self):
        with tempfile.TemporaryDirectory() as td:
            work, recipe, run = _seed_run_with_checkpoint(
                td, "0" * 64)
            stub_log = Path(td) / "invocations.log"
            rc, out = _run_driver(
                work, recipe, stub_log,
                extra_args=["--accept-code-change"])
            self.assertEqual(rc, 0, msg=out[-2000:])
            got = [r["tic"] for r in _merged_survivors(run)]
            self.assertEqual(got, EXPECTED_SURVIVORS)
            # Slice 0 was NOT re-screened (valid checkpoint entry).
            inv = _invocations(stub_log)
            self.assertNotIn("slice_00.csv", inv)
            self.assertIn("slice_01.csv", inv)
            self.assertIn("slice_02.csv", inv)
            # Run-level stamps: summary, manifest, checkpoint.
            summary = json.loads(
                (run / "summary.json").read_text())
            self.assertTrue(summary["mixed_pipeline"])
            manifest = json.loads(
                (run / "manifest.json").read_text())
            self.assertTrue(manifest["mixed_pipeline"])
            cp = json.loads((run / "checkpoint.json").read_text())
            self.assertTrue(cp["mixed_pipeline"])
            # Record-level stamps: slices screened AFTER the
            # accepted resume carry the flag; slice 0's record
            # (written by the original run) keeps its original
            # provenance — the run-level flag covers the run.
            # Survivors: 100000002 (slice 0), 100000005 and
            # 100000008 (slice 1); slice 2 has no survivors.
            recs = {r["tic"]: r for r in _merged_survivors(run)}
            self.assertNotIn("mixed_pipeline", recs["100000002"])
            self.assertTrue(recs["100000005"]["mixed_pipeline"])
            self.assertTrue(recs["100000008"]["mixed_pipeline"])

    def test_fingerprintless_checkpoint_refused(self):
        # A pre-A-3 checkpoint cannot prove what code produced
        # it — fail closed, unless explicitly accepted.
        with tempfile.TemporaryDirectory() as td:
            work, recipe, run = _seed_run_with_checkpoint(td, None)
            stub_log = Path(td) / "invocations.log"
            rc, out = _run_driver(work, recipe, stub_log)
            self.assertNotEqual(rc, 0)
            self.assertIn("REFUSING TO RESUME", out)
            self.assertIn("no code fingerprint", out)
            self.assertEqual(_invocations(stub_log), [])
            rc, out = _run_driver(
                work, recipe, stub_log,
                extra_args=["--accept-code-change"])
            self.assertEqual(rc, 0, msg=out[-2000:])
            summary = json.loads(
                (run / "summary.json").read_text())
            self.assertTrue(summary["mixed_pipeline"])
            got = [r["tic"] for r in _merged_survivors(run)]
            self.assertEqual(got, EXPECTED_SURVIVORS)


class TestAtomicWrites(unittest.TestCase):
    def test_failed_write_leaves_no_target(self):
        from atomic_io import atomic_write_json, atomic_writer
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "out.json"
            with self.assertRaises(RuntimeError):
                with atomic_writer(target) as fh:
                    fh.write('{"partial": ')
                    raise RuntimeError("simulated kill")
            self.assertFalse(target.exists())
            # No tmp litter left behind on failure either.
            self.assertEqual(list(Path(td).iterdir()), [])
            # A pre-existing target survives a failed overwrite.
            atomic_write_json(target, {"v": 1})
            with self.assertRaises(RuntimeError):
                with atomic_writer(target) as fh:
                    fh.write('{"partial": ')
                    raise RuntimeError("simulated kill")
            self.assertEqual(json.loads(target.read_text()),
                             {"v": 1})

    def test_atomic_write_json_round_trip(self):
        from atomic_io import atomic_write_json
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "s.json"
            atomic_write_json(target, {"b": 2, "a": 1})
            self.assertEqual(json.loads(target.read_text()),
                             {"a": 1, "b": 2})
            # Sorted keys: identical objects, identical bytes.
            target2 = Path(td) / "s2.json"
            atomic_write_json(target2, {"a": 1, "b": 2})
            self.assertEqual(target.read_bytes(),
                             target2.read_bytes())


class TestV1Gate(unittest.TestCase):
    """F-15: the driver enforces the v1 sector gate itself,
    before creating the run dir — a refused run leaves no run
    dir, no manifest, no checkpoint behind."""

    def test_refuses_without_allow_v1(self):
        with tempfile.TemporaryDirectory() as td:
            work, recipe = _build_workdir(td)
            rc, out = _run_driver(work, recipe,
                                  Path(td) / "inv.log",
                                  allow_v1=False)
            self.assertEqual(rc, 2, msg=out[-2000:])
            self.assertIn("bulk_v1", out)
            self.assertFalse((work / "run_s0999").exists(),
                             "the refused run must not create "
                             "a run dir")

    def test_proceeds_with_allow_v1(self):
        with tempfile.TemporaryDirectory() as td:
            work, recipe = _build_workdir(td)
            rc, out = _run_driver(work, recipe,
                                  Path(td) / "inv.log")
            self.assertEqual(rc, 0, msg=out[-2000:])
            self.assertTrue((work / "run_s0999").exists())


if __name__ == "__main__":
    unittest.main()
