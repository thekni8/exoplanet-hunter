"""Determinism test (Phase 1.1, item 9).

Same input -> byte-identical survivor records. The screen is
pure arithmetic (BLS + rescore + vetoes — no RNG anywhere in
bulk_screen.py), so screening the same FITS twice and emitting
with a FIXED provenance header must produce identical JSON
bytes. Provenance is fixed because run_id and timestamp_utc
differ per run BY DESIGN — they are the only allowed source of
difference, and this test pins that: with provenance held
constant, everything else must be bit-stable.

Why it matters: the resume test (item 8) proves a killed run
reproduces the same survivors; this test proves the SCREEN
itself is reproducible, which is what makes that promise
meaningful. A future change that introduces order-dependence
(dict iteration, set iteration, unseeded RNG, parallel
nondeterminism) goes red here first.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from bulk_screen import _screen_one, emit_survivor_record  # noqa: E402
from synth_fits import make_qlp_fits, screen_job  # noqa: E402

FIXED_PROV = {
    "schema_version": "1.1",
    "run_id": "determinism-test",
    "pipeline_git_sha": "test",
    "calibration_version": "bulk_v1",
    "timestamp_utc": "2026-11-14T00:00:00+00:00",
}


def _canonical_bytes(record):
    return json.dumps(record, sort_keys=True).encode("utf-8")


class TestDeterminism(unittest.TestCase):
    def test_same_fits_twice_byte_identical(self):
        with tempfile.TemporaryDirectory() as td:
            p = make_qlp_fits(Path(td) / "planet.fits",
                              period_d=2.5, depth_frac=0.01,
                              duration_d=0.1, noise_pct=0.003,
                              seed=42)
            r1 = emit_survivor_record(_screen_one(screen_job(p)),
                                      FIXED_PROV)
            r2 = emit_survivor_record(_screen_one(screen_job(p)),
                                      FIXED_PROV)
            self.assertEqual(_canonical_bytes(r1),
                             _canonical_bytes(r2))
            self.assertEqual(r1["status"], "survivor")

    def test_demoted_and_noise_records_also_deterministic(self):
        # Not just survivors: a demoted EB and pure noise must
        # also reproduce exactly (the veto path and the floor
        # path exercise different code).
        with tempfile.TemporaryDirectory() as td:
            eb = make_qlp_fits(Path(td) / "eb.fits", period_d=3.0,
                               depth_frac=0.02, duration_d=0.1,
                               noise_pct=0.005, odd_even_ratio=0.4,
                               seed=42)
            e1 = emit_survivor_record(_screen_one(screen_job(eb)),
                                      FIXED_PROV)
            e2 = emit_survivor_record(_screen_one(screen_job(eb)),
                                      FIXED_PROV)
            self.assertEqual(_canonical_bytes(e1),
                             _canonical_bytes(e2))
            self.assertEqual(e1["status"], "demoted")
            noise = make_qlp_fits(Path(td) / "n.fits",
                                  period_d=None, noise_pct=0.003,
                                  seed=7)
            n1 = emit_survivor_record(
                _screen_one(screen_job(noise)), FIXED_PROV)
            n2 = emit_survivor_record(
                _screen_one(screen_job(noise)), FIXED_PROV)
            self.assertEqual(_canonical_bytes(n1),
                             _canonical_bytes(n2))

    def test_emit_is_pure(self):
        # emit_survivor_record twice on the same record dict with
        # the same provenance must give identical bytes AND must
        # not mutate its input (a mutating emit would make the
        # second call differ from the first).
        rec = {"tic": "123", "sector": 1, "product": "QLP",
               "status": "survivor", "period_days": 2.5,
               "sde": 15.0, "tier": "A", "mes_pink": 17.3,
               "depth_percent": 1.0, "null_field": None}
        snapshot = dict(rec)
        o1 = emit_survivor_record(rec, FIXED_PROV)
        o2 = emit_survivor_record(rec, FIXED_PROV)
        self.assertEqual(_canonical_bytes(o1), _canonical_bytes(o2))
        self.assertEqual(rec, snapshot)
        self.assertNotIn("null_field", o1)  # Nones are dropped


if __name__ == "__main__":
    unittest.main()
