"""Injection-recovery smoke test (Phase 1.1, item 6).

Wires a deterministic slice of the EXISTING injection harness
into the golden suite — it does not rebuild the harness and does
not re-measure the completeness floor (that is the full harness's
job, run manually).

IMPORTANT — why this test uses the REAL pipeline, not the
harness's mirror: the 2026-11-13 injection run
(INJECTION_RECOVERY.md §9) ran the real `hunter._run_pipeline`
(monkey-patched data sources only). The harness's own
`run_pipeline_mirror` uses a LINEAR 10,000-point BLS grid,
which cannot hold phase coherence over this substrate's 2226-d
baseline (report §5) — probed 2026-11-14, the mirror scores a
0.40% @ 2.17 d injection at SDE 4.8 where the real pipeline
scores it at SDE 106. The smoke test therefore injects with the
harness's own `inject_transit`, applies the production outlier
clip (the harness's ordering: clip AFTER injection), writes the
result as a temporary fixture, and runs the real pipeline
through the item-4 fixture seam (EXHUNT_FIXTURE_DIR). Detection
is what is asserted (period within +-1%, SDE >= 8.5); the
gate + stamp stages are covered by test_false_positives.py and
test_stamp.py.

The trials are the STRONG cells from the 2026-11-13 run on this
star (TIC 238620464, a typical Tmag ~12 QLP star, 8 sectors,
35,323 points — committed substrate in
tests/fixtures/injection/): 0.40% @ 2.17 d detected at SDE 106,
0.40% @ 7.31 d at SDE 63, 0.20% @ 2.17 d recovered at SDE 31.
The control trial asserts only that the pipeline completes with
finite metrics — BLS alone false-alarms on 6/7 noise runs
(report §6), so a no-false-alarm assertion at the pipeline level
would be wrong.

Each trial is a full _run_pipeline run (~1 min), so this module
takes ~4 minutes — the slowest part of the --fast suite. That
is the price of a real end-to-end detection check. The
diagnostic-PNG render and discoveries.csv logging are patched to
no-ops for these runs (the 2026-11-13 driver's precedent), so
the smoke test leaves no artifacts behind.
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402

import hunter  # noqa: E402
import injection_harness as ih  # noqa: E402

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "injection"
SUBSTRATE = FIXTURE_DIR / "substrate_238620464.npz"

# (depth_pct, period_d, epoch_offset_d) — the strong cells from the
# 2026-11-13 run on this star. Epoch offsets are fixed (0.3 * P)
# so the trials are deterministic.
TRIALS = [
    (0.40, 2.17, 0.3 * 2.17),
    (0.40, 7.31, 0.3 * 7.31),
    (0.20, 2.17, 0.3 * 2.17),
]

SDE_THRESHOLD = 8.5  # the pipeline's discovery bar
TIC = "238620464"


def _load_substrate():
    if not SUBSTRATE.exists():
        raise RuntimeError(
            "injection substrate missing: tests/fixtures/injection/"
            "substrate_238620464.npz — it is a committed fixture; "
            "check it out from git.")
    d = np.load(SUBSTRATE)
    meta = json.loads(str(d["meta_json"]))
    return (np.asarray(d["t"], dtype=float),
            np.asarray(d["f"], dtype=float),
            np.asarray(d["ferr"], dtype=float), meta)


def _clip_outliers(t, f):
    """Production outlier clip (sigma=5), applied AFTER injection
    — the harness's ordering, mirroring production where the
    (real) signal is already in the data when the clip runs."""
    import lightkurve as lk
    lc = lk.LightCurve(time=t, flux=f).remove_outliers(sigma=5.0)
    return (np.asarray(lc.time.value, dtype=float),
            np.asarray(lc.flux.value, dtype=float))


class TestInjectionSmoke(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.t, cls.f, cls.ferr, cls.meta = _load_substrate()
        # The substrate must be the star the trials were measured
        # on — a swapped file would silently change the test.
        assert cls.meta["tic"] == TIC, cls.meta
        assert cls.meta["n_points"] == len(cls.t) == 35323, cls.meta
        # No artifacts: the 2026-11-13 driver's precedent — patch
        # the PNG render and the discoveries.csv log to no-ops.
        cls._orig_png = hunter._render_diagnostic_png
        cls._orig_log = hunter.log_candidate
        hunter._render_diagnostic_png = lambda *a, **k: None
        hunter.log_candidate = lambda *a, **k: None
        cls._tmp = tempfile.TemporaryDirectory()
        cls._prev_fixture = os.environ.get("EXHUNT_FIXTURE_DIR")
        os.environ["EXHUNT_FIXTURE_DIR"] = cls._tmp.name

    @classmethod
    def tearDownClass(cls):
        hunter._render_diagnostic_png = cls._orig_png
        hunter.log_candidate = cls._orig_log
        if cls._prev_fixture is None:
            os.environ.pop("EXHUNT_FIXTURE_DIR", None)
        else:
            os.environ["EXHUNT_FIXTURE_DIR"] = cls._prev_fixture
        cls._tmp.cleanup()

    def _run_with_injection(self, depth_pct, period_d, epoch_off):
        """Inject, clip, write a temp fixture, run the real
        pipeline through the seam. Returns the _run_pipeline
        result dict."""
        if depth_pct is None:
            f_use = self.f
        else:
            epoch = float(self.t.min()) + epoch_off
            f_use, _dur = ih.inject_transit(
                self.t, self.f, depth_pct / 100.0, period_d, epoch)
        t_c, f_c = _clip_outliers(self.t, f_use)
        meta = {"tic": TIC, "max_sectors": None,
                "n_sectors": int(self.meta["n_sectors"]),
                "n_points": int(len(t_c))}
        path = Path(self._tmp.name) / f"TIC_{TIC}.npz"
        np.savez_compressed(path, t=t_c, f=f_c,
                            meta_json=json.dumps(meta))
        full = hunter._run_pipeline(TIC, star_radius=1.0)
        # Prove the seam fired (no MAST download happened).
        self.assertTrue(
            np.array_equal(np.asarray(full["raw_time"], dtype=float),
                           t_c),
            msg="pipeline raw_time does not match the injected "
                "fixture — the live path ran instead of the seam")
        return full

    def test_strong_injections_recover(self):
        for depth_pct, period_d, epoch_off in TRIALS:
            with self.subTest(depth_pct=depth_pct, period_d=period_d):
                full = self._run_with_injection(depth_pct, period_d,
                                                epoch_off)
                self.assertGreaterEqual(
                    full["SDE"], SDE_THRESHOLD,
                    msg=f"{depth_pct}% @ {period_d} d: SDE "
                        f"{full['SDE']:.1f} below the discovery bar")
                self.assertAlmostEqual(
                    full["Period"], period_d,
                    delta=0.01 * period_d,
                    msg=f"{depth_pct}% @ {period_d} d: recovered "
                        f"P={full['Period']:.4f} d")

    def test_control_completes(self):
        # No injection: the pipeline must complete with finite
        # metrics. No false-alarm assertion — BLS alone
        # false-alarms on most noise runs (see module docstring).
        full = self._run_with_injection(None, None, None)
        self.assertTrue(np.isfinite(full["SDE"]))
        self.assertTrue(np.isfinite(full["Period"]))
        self.assertTrue(np.isfinite(full["Depth"]))


if __name__ == "__main__":
    unittest.main()
