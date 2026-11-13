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
* test_golden_stars — the pipeline end to end on known objects, with
  capped sectors so the downloads stay in the tens of MB and are
  cached by lightkurve for later runs:
    - TOI-700 (TIC 150428135): must recover planet c at P 16.05094 d
      as the headline signal, with planet b (P 9.97706 d) among the
      refined signals.
    - WASP-126 b (TIC 25155310): regression — the pipeline must
      recover the published period and the depth it has always
      measured (0.631%); a drift here means the search changed.
    - TIC 308851365: a known eclipsing binary — the pipeline must
      recover its 0.75677 d signal AND the trapezoid shape gate must
      call it V-shaped, i.e. an EB suspect, not a planet.

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
