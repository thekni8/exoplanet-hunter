"""Tests for scripts/score_f4.py (F4 stitched-0.75 fresh validation).

Regression test for the scorer crash of 2026-11-23: validation
copies sampled from `copies` can be p1-carried trials with no
pass-2/pass-3 final row (recovered only via the 5.1 carried row).
The fold loop used to pass their None row to fold_gate and crash
(AttributeError: 'NoneType' object has no attribute 'get').
The fixed scorer skips such trials from the measured set and
logs them (skipped_no_final_row_n / skipped_no_final_row).

All fold work is stubbed: these tests cover the classification
and the skip, not the fold depths (the fold code is exercised
by the F4 re-score on the Mac).
"""
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _load_score_f4():
    spec = importlib.util.spec_from_file_location(
        "score_f4", ROOT / "scripts" / "score_f4.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sf = _load_score_f4()


def _pass1_row():
    return {"period_days": 8.0, "t0_btjd": 3887.5,
            "duration_hours": 3.0, "mes_pink": 9.0,
            "max_event_snr": 7.0, "n_events": 3}


def _pass2_row(**kw):
    row = {"period_days": 8.0, "t0_btjd": 3887.5,
           "duration_hours": 3.0, "depth_percent": 0.5,
           "sde": 10.0, "mes_pink": 9.0, "max_event_snr": 7.0,
           "n_events": 3, "tier": "A", "status": "survivor"}
    row.update(kw)
    return row


def _trial(tic, trial_id, **kw):
    """A stubbed Arm-P trial record (same keys mode_planet reads)."""
    t = {
        "tic": tic, "trial_id": trial_id,
        "period_d": 8.0, "epoch_btjd": 3887.5, "depth_frac": 0.005,
        "final_recovered": True,
        "p1_carried_recovered": False,
        "p2_recovered": False, "p3_recovered": False,
        "pass1": _pass1_row(), "pass2": None, "pass3": None,
    }
    t.update(kw)
    return t


class TestNoneFinalRow(unittest.TestCase):
    def _run_mode_planet(self, trials):
        """Run mode_planet on stubbed host files with stubbed
        folds. Returns (out, planet-dict)."""
        with tempfile.TemporaryDirectory() as tmp:
            host_dir = Path(tmp) / "hosts-p43"
            host_dir.mkdir()
            (host_dir / "100000000.json").write_text(json.dumps({
                "tic": 100000000, "sectors": [95, 96],
                "trials": trials}))
            args = SimpleNamespace(run_p=tmp, cache=tmp)
            out = {"validations": []}
            orig = (sf.build_unmasked_stitch, sf.validate_against,
                    sf.fold_gate)
            sf.build_unmasked_stitch = (
                lambda *a, **k: (None, None, 100))
            sf.validate_against = lambda *a, **k: {"ok": True}
            # Unmasked fold does not confirm: the at-risk trial
            # is a mask rescue with ratio 0.8 (>= 0.75).
            sf.fold_gate = lambda *a, **k: {
                "row_depth_pct": 0.5, "fold_depth_pct": 0.4,
                "confirmed": False}
            try:
                sf.mode_planet(args, out)
            finally:
                (sf.build_unmasked_stitch, sf.validate_against,
                 sf.fold_gate) = orig
            return out, out["planet"]

    def test_p1_carried_validation_copy_skipped_not_crashed(self):
        # Mirrors the real crash trial 41083546:planet02 — a
        # p1-carried recovery whose pass-2 row exists but was
        # never recovered (status 'recorded'), pass-3 None.
        carried = _trial(
            100000000, "planet02", p1_carried_recovered=True,
            pass2=_pass2_row(status="recorded", tier=None,
                             sde=18.7, mes_pink=9.4))
        at_risk = _trial(
            100000000, "planet01", p2_recovered=True,
            pass2=_pass2_row())
        out, planet = self._run_mode_planet([carried, at_risk])
        self.assertEqual(planet["recovered_n"], 2)
        self.assertEqual(planet["at_risk_n"], 1)
        self.assertEqual(planet["copy_n"], 1)
        self.assertEqual(planet["anomaly_n"], 0)
        # The carried trial is skipped (logged, not folded).
        self.assertEqual(planet["skipped_no_final_row_n"], 1)
        self.assertEqual(
            planet["skipped_no_final_row"],
            ["100000000:planet02:validation_copy"])
        # Only the at-risk trial was folded and validated.
        self.assertEqual(len(planet["folds"]), 1)
        self.assertEqual(planet["folds"][0]["trial_id"], "planet01")
        self.assertEqual(planet["folds"][0]["group"], "at_risk")
        self.assertEqual(len(out["validations"]), 1)
        self.assertEqual(planet["mask_rescue_n"], 1)

    def test_all_final_rows_present_nothing_skipped(self):
        a = _trial(100000000, "planet01", p2_recovered=True,
                   pass2=_pass2_row())
        b = _trial(100000000, "planet02", p2_recovered=True,
                   pass2=_pass2_row(carried_from="pass1"))
        out, planet = self._run_mode_planet([a, b])
        self.assertEqual(planet["skipped_no_final_row_n"], 0)
        self.assertEqual(planet["skipped_no_final_row"], [])
        self.assertEqual(planet["at_risk_n"], 1)
        self.assertEqual(planet["copy_n"], 1)
        self.assertEqual(len(planet["folds"]), 2)
        self.assertEqual(len(out["validations"]), 2)


if __name__ == "__main__":
    unittest.main()
