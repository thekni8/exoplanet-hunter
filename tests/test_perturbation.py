"""Perturbation test for near-tie verdict stability (Phase 1.2
follow-up F-12).

Jitter the golden fixtures' flux by ~1e-6 relative (deterministic
seed) and re-run the pipeline: the verdict class must hold. The
C-4 story was a ~4e-7 trend difference flipping a BLS argmax on
a near-tie — this test proves a 1e-6 input perturbation does not
flip a verdict on rounding noise. The assertions are the SAME
golden checks the unjittered fixtures pass (tests/golden_checks.py,
against tests/expected_values.json) — NOT a re-run baseline, so
no extra pipeline runs are needed.

If a verdict class flips here, that is a FINDING, not a test bug:
the fix (return INCONCLUSIVE rather than flipping) is decided
from the evidence. Bit-identical cross-platform output is NOT
the goal — verdict stability is.

Slow (~2.5 min: three pipeline runs). In the golden shard
(F-10); excluded from smoke.
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import hunter  # noqa: E402
from tests.golden_checks import (  # noqa: E402
    check_eb, check_toi700, check_wasp126)

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "golden"
TICS = ("150428135", "25155310", "308851365")

# Relative flux jitter: 1e-6, far below the ~0.1-1% noise floor.
# Deterministic seed — the same jitter every run, so a failure
# is reproducible, not a flaky draw.
JITTER_SIGMA = 1e-6
JITTER_SEED = 20261114

_TMP = None
_PREV = None


def setUpModule():
    global _TMP, _PREV
    missing = [f"TIC_{t}.npz" for t in TICS
               if not (FIXTURE_DIR / f"TIC_{t}.npz").exists()]
    if missing:
        raise RuntimeError(
            "golden fixtures missing: " + ", ".join(missing) +
            " — regenerate with: "
            ".venv/bin/python tests/make_fixtures.py")
    _TMP = tempfile.TemporaryDirectory(prefix="perturbed-fixtures-")
    rng = np.random.default_rng(JITTER_SEED)
    for tic in TICS:
        z = np.load(FIXTURE_DIR / f"TIC_{tic}.npz")
        t = np.asarray(z["t"], dtype=float)
        f = np.asarray(z["f"], dtype=float)
        # Relative jitter: multiply by (1 + eps), eps ~ N(0, 1e-6).
        f_jit = f * (1.0 + rng.normal(0.0, JITTER_SIGMA, size=f.shape))
        np.savez(Path(_TMP.name) / f"TIC_{tic}.npz",
                 t=t, f=f_jit, meta_json=z["meta_json"])
    _PREV = os.environ.get("EXHUNT_FIXTURE_DIR")
    os.environ["EXHUNT_FIXTURE_DIR"] = _TMP.name


def tearDownModule():
    if _PREV is None:
        os.environ.pop("EXHUNT_FIXTURE_DIR", None)
    else:
        os.environ["EXHUNT_FIXTURE_DIR"] = _PREV
    if _TMP is not None:
        _TMP.cleanup()


def _fixture_meta(tic):
    z = np.load(FIXTURE_DIR / f"TIC_{tic}.npz")
    return json.loads(str(z["meta_json"]))


class TestPerturbation(unittest.TestCase):
    def test_toi700_holds_under_jitter(self):
        full = hunter._run_pipeline("150428135", star_radius=0.42,
                                    max_sectors=2)
        check_toi700(self, full)

    def test_wasp126_holds_under_jitter(self):
        full = hunter._run_pipeline("25155310", star_radius=1.30,
                                    max_sectors=1)
        check_wasp126(self, full)

    def test_eb_holds_under_jitter(self):
        meta = _fixture_meta("308851365")
        full = hunter._run_pipeline("308851365", star_radius=1.0,
                                    max_sectors=1)
        check_eb(self, full, meta["rho_star_solar"])


if __name__ == "__main__":
    unittest.main()
