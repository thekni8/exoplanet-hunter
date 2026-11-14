"""Download-backed golden tests: the pipeline end to end on known objects.

These are the tests that prove the SEARCH still works against LIVE
data, not just the plumbing. Each one downloads real TESS light
curves (capped sectors, tens of MB, cached by lightkurve for later
runs) and runs the full pipeline (`hunter._run_pipeline`) on a star
whose answer is known:

* TOI-700 (TIC 150428135) — the multi-planet control. Planet c
  (P 16.05094 d) must come back as the headline signal. Planet b
  (P 9.97706 d) is checked in the BLS spectrum itself, not in the
  top-3 refined list: b ranks 12th–15th in the pipeline's own
  peak extraction (see the comment in hunter._bls_best), so
  top-3 membership is the wrong assertion for it — what matters
  is that the BLS stage still sees b as a significant peak
  (SDE above the pipeline's 6.5 acceptance floor). This is the
  star the 2026-11-13 BLS fix was built against: the old coarse
  grid locked onto the P/2 alias (8.026 d) and missed c entirely.
  If c stops being the headline, the grid or the refinement
  regressed.
* WASP-126 b (TIC 25155310) — the depth TRIPWIRE (not a
  validation). The pipeline has always measured this transit at
  0.631% (vs the 0.7006% TOI catalog value); a drift in the
  recovered depth means the search or the flattening changed.
  Period must match the published 3.286 d.
* TIC 308851365 — a known eclipsing binary (VSX: ECLIPSING BINARY).
  The pipeline must recover its 0.75677 d signal AND the trapezoid
  shape gate must not call the folded transit flat-bottomed
  (T23/T14 < 0.50) with the density flag firing, i.e. an EB
  suspect, not a planet. This guards the shape gate that
  caught the 423498314 grazing transit.

The assertions live in tests/golden_checks.py, shared with the
offline fixture tests (test_golden_fixtures.py) — one definition
of "the pipeline still finds the known answers".

Run with the suite (`python tests/run_golden.py`) or directly:
`python -m unittest tests.test_golden_stars -v`. The `--fast` flag
on the runner skips this module (no downloads); the live tests run
on a schedule instead (.github/workflows/live.yml), so a MAST
outage never turns the PR gate red.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import hunter  # noqa: E402
from gauntlet.rawflux_check import tic_density  # noqa: E402
from tests.golden_checks import check_eb, check_toi700, check_wasp126  # noqa: E402


class TestGoldenStars(unittest.TestCase):
    def test_toi700_c_headline_b_recovered(self):
        # TOI-700 is a 0.42 Rsun M dwarf; SPOC 2-min data. Two sectors
        # give ~3 transits of c — enough for the headline at SDE >> 8.5.
        full = hunter._run_pipeline("150428135", star_radius=0.42,
                                    max_sectors=2)
        check_toi700(self, full)

    def test_wasp126_depth_regression(self):
        # QA benchmark setup: 1 sector, R* = 1.30 Rsun. Depth is the
        # pipeline's own long-standing measurement (0.631%), NOT the
        # catalog value — this test guards the pipeline against
        # itself, so the baseline is what the code has always found.
        full = hunter._run_pipeline("25155310", star_radius=1.30,
                                    max_sectors=1)
        check_wasp126(self, full)

    def test_eb_shape_gate_calls_v_shaped(self):
        # 6%-deep eclipses: one sector is plenty. The period check
        # proves the search found the signal; the shape gate must
        # then refuse to call it a planet.
        full = hunter._run_pipeline("308851365", star_radius=1.0,
                                    max_sectors=1)
        rho_star, _src = tic_density("308851365")
        check_eb(self, full, rho_star)


if __name__ == "__main__":
    unittest.main()
