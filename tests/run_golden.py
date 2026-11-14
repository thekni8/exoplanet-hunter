#!/usr/bin/env python3
"""Golden validation suite — the one command that proves the pipeline
still works.

    python tests/run_golden.py            # full suite (light downloads)
    python tests/run_golden.py --fast     # unit tests only, no downloads

What it checks
--------------
* test_recipe — the YAML recipe loader (no downloads).
* test_stamp  — the persistence stamp's chi2 systematic floor, the
  2026-11-13 fix that stops real signals being vetoed (no downloads).
* test_provenance, test_calibration, test_schema, test_stage_contract,
  test_false_positives, test_injection, test_resume, test_determinism,
  test_corrupt_data — Phase 1.1 hardening: provenance, calibration
  profiles, schema validation, the gauntlet stage contract,
  false-positive rejection, injection recovery, resume/checkpoint,
  determinism, corrupt-data handling (no downloads).
* test_golden_fixtures — the pipeline end to end on the same three
  known objects as the live tests, against COMMITTED fixtures
  (tests/fixtures/golden/) — no downloads, runs on every PR.
* test_golden_stars — the pipeline end to end on known objects
  against LIVE MAST data (the only download-backed module):
    - TOI-700 (TIC 150428135): must recover planet c at P 16.05094 d
      as the headline signal, with planet b (P 9.97706 d) among the
      refined signals.
    - WASP-126 b (TIC 25155310): regression — the pipeline must
      recover the published period and the depth it has always
      measured (0.631%); a drift here means the search changed.
    - TIC 308851365: a known eclipsing binary — the pipeline must
      recover its 0.75677 d signal AND the trapezoid shape gate must
      not call it flat-bottomed (T23/T14 < 0.50) with the density
      flag firing, i.e. an EB suspect, not a planet (the V-shaped
      label itself is not reproducible on this smeared signal —
      see tests/golden_checks.py).

CI split (Phase 1.1, item 4): the PR gate (golden.yml) runs
--fast only — unit tests + offline fixtures, no network — so a
MAST outage never turns the PR gate red. The live tests run on a
weekly schedule (.github/workflows/live.yml), non-blocking: if
live and offline disagree, the fixture is stale (regenerate with
tests/make_fixtures.py) or MAST changed its data.

Exit code 0 means every test passed. Any failure is a real signal:
do not "fix" it by loosening a threshold — find what changed.
"""
import argparse
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DOWNLOAD_TESTS = {"test_golden_stars"}


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Golden validation suite (see module docstring).")
    ap.add_argument("--fast", action="store_true",
                    help="Unit tests only; skip the download tests.")
    ap.add_argument("-v", "--verbose", action="count", default=1,
                    help="Verbosity (default: -v once).")
    args = ap.parse_args(argv)

    loader = unittest.TestLoader()
    suite = loader.discover(str(ROOT / "tests"), pattern="test_*.py")
    if args.fast:
        suite = _drop_download_tests(suite)

    print(f"Exoplanet Hunter golden suite "
          f"({'fast — no downloads' if args.fast else 'full'})\n",
          flush=True)
    runner = unittest.TextTestRunner(verbosity=args.verbose)
    result = runner.run(suite)
    print()
    if result.wasSuccessful():
        print(f"GOLDEN SUITE: PASS "
              f"({result.testsRun} test(s))", flush=True)
        return 0
    print(f"GOLDEN SUITE: FAIL — "
          f"{len(result.failures)} failure(s), "
          f"{len(result.errors)} error(s) "
          f"of {result.testsRun} test(s)", flush=True)
    return 1


def _drop_download_tests(suite):
    """Rebuild a suite without the download-backed test modules."""
    out = unittest.TestSuite()
    for test in suite:
        if isinstance(test, unittest.TestSuite):
            out.addTests(_drop_download_tests(test))
        elif test.__class__.__module__.split(".")[-1] not in DOWNLOAD_TESTS:
            out.addTest(test)
    return out


if __name__ == "__main__":
    raise SystemExit(main())
