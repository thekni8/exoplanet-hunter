#!/usr/bin/env python3
"""Golden validation suite — the one command that proves the pipeline
still works.

    python tests/run_golden.py            # full suite (light downloads)
    python tests/run_golden.py --fast     # unit tests only, no downloads
    python tests/run_golden.py --smoke    # smoke tier (<=3 min, PR check)
    python tests/run_golden.py --shard golden|injection|rest
                                          # one CI shard (see below)
    python tests/run_golden.py --only test_blend
                                          # a single module

Tiers (Phase 1.2 follow-up F-10)
--------------------------------
The "fast" suite (888 s) is not fast, so the suite is tiered —
reclassified, never reduced (no scientific test was removed to
achieve speed):

* smoke (<=3 min): the PR check. Runner (test_runner,
  test_runner_e2e), status matrix (test_stage_contract), blend
  (test_blend), conservation (test_conservation), registry
  (test_registry), fingerprint (test_run_fingerprint,
  test_provenance2, test_fingerprint_coverage), idempotency
  stubs (test_idempotency), ingest (test_ingest). No downloads,
  no pipeline runs.
* golden shard: the pipeline-run modules (test_golden_fixtures,
  test_census, test_toi_population, test_perturbation) — each
  runs _run_pipeline on fixtures, ~2 min per module.
* injection shard: test_injection + test_clip_grid (the
  injection-recovery harness + the clip grid, ~5 min).
* rest shard: everything else offline (34 modules) — the
  Phase 2 desk/tool/evidence/review modules live here
  (test_desk, test_desk_external_tools, test_external_tool,
  test_latte, test_triceratops, test_evidence, test_review,
  test_pixel_check, test_concordance, test_holdout): they run fake tools
  and fixtures, no downloads, no pipeline runs, so they
  belong in rest, not smoke (smoke stays the <=3 min PR
  check) and not golden (no _run_pipeline).
* live (DOWNLOAD_TESTS, not in any offline tier):
  test_golden_stars, test_desk_live, test_concordance_live,
  test_deep_mask_live
  — real MAST downloads; weekly + on merge in live.yml,
  non-blocking.

Phase 2 placement (P-14): the desk driver's contract tests
(test_runner, test_runner_e2e, test_stage_contract) are
smoke — the verdict machinery is the PR gate's core. The
labelled-population harness (test_toi_population) is golden
(it runs _run_pipeline on fixtures). Everything else Phase 2
is rest, except the two live modules above.

Parallelism (P-14): the shards already parallelise in CI
(golden.yml runs smoke + golden + injection + rest as four
jobs). Within-shard parallelism via pytest-xdist is BLOCKED:
xdist is not in requirements.lock, and adding a dependency
means a lockfile regeneration (pip-compile + hashes) plus a
full suite re-run — out of scope for this build. The suite
stays unittest + the shard split.

Mac-nightly tools tier (P-16 step, not built here): the
golden tool tests — real LATTE/TRICERATOPS runs on the
labelled population — cannot run in CI (the venvs live on
the Mac, and LATTE needs Rosetta Python 3.8). When the
venvs exist they run as a nightly Mac job, not a CI shard,
and their results are recorded, not gated on.
* rest shard: everything else offline (the medium modules).
* full (--fast): the standard gate — smoke + golden + injection
  + rest, offline, ~15 min. The live tests (test_golden_stars,
  test_desk_live, test_concordance_live, test_deep_mask_live)
  are NOT in any offline tier; they run weekly in live.yml.

CI split: golden.yml runs smoke (the PR check) plus the three
shards in parallel; together the shards cover the full --fast
suite. The lockfile-clean-install job is unchanged.

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
* test_desk_live — the desk driver's clean-data re-fold gate on
  REAL S96 QLP light curves (Phase 2, 2A): the flagged-cadence
  artifacts TIC 355401152 and 382571558 must FAIL, the known
  planet TIC 183537452 (TOI-192.01) must PASS. Also
  download-backed; also live-CI only.
* test_concordance_live — the full 25-lead concordance replay
  (Phase 2 vote follow-up P-12): all 25 hand-vetted rescore-v2
  S96 leads through the automated desk driver on live MAST
  data, asserting agreement with the manual verdicts (TIC
  307433122, harmonic alias, is the expected mismatch —
  recorded, not asserted). ~1-2 h; live-CI only.

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

DOWNLOAD_TESTS = {"test_golden_stars", "test_desk_live",
                  "test_concordance_live", "test_deep_mask_live"}

# Smoke tier (F-10): the <=3 min PR check. Runner, status
# matrix, blend, conservation, registry, fingerprint,
# idempotency stubs, ingest — no downloads, no pipeline runs.
# Timings measured 2026-11-14 (see PHASE_1_2_PROGRESS.md).
SMOKE_MODULES = {
    "test_runner", "test_runner_e2e", "test_stage_contract",
    "test_blend", "test_conservation", "test_registry",
    "test_run_fingerprint", "test_provenance2",
    "test_fingerprint_coverage", "test_idempotency",
    "test_ingest",
}

# Golden shard: the pipeline-run modules (each runs
# _run_pipeline on fixtures, ~2 min per module).
# test_perturbation lands in F-12; naming it here now means it
# is in the golden shard from its first commit.
SHARD_GOLDEN = {
    "test_golden_fixtures", "test_census",
    "test_toi_population", "test_perturbation",
}

# Injection shard: the injection-recovery harness + clip grid.
SHARD_INJECTION = {"test_injection", "test_clip_grid"}


def _module_of(test):
    return test.__class__.__module__.split(".")[-1]


def _modules_in(suite):
    """All module names in a discovered suite (walked once —
    discovery already imported everything)."""
    modules = set()

    def _walk(s):
        for test in s:
            if isinstance(test, unittest.TestSuite):
                _walk(test)
            else:
                modules.add(_module_of(test))

    _walk(suite)
    return modules


def _select(suite, keep):
    """Rebuild a suite keeping only tests whose module is in
    `keep` (a set of module names, or None to keep all)."""
    out = unittest.TestSuite()
    for test in suite:
        if isinstance(test, unittest.TestSuite):
            out.addTests(_select(test, keep))
        elif keep is None or _module_of(test) in keep:
            out.addTest(test)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Golden validation suite (see module docstring).")
    group = ap.add_mutually_exclusive_group()
    group.add_argument("--fast", action="store_true",
                       help="Unit tests only; skip the download tests.")
    group.add_argument("--smoke", action="store_true",
                       help="Smoke tier only (<=3 min PR check).")
    group.add_argument("--shard",
                       choices=("golden", "injection", "rest"),
                       help="One CI shard: golden (pipeline-run "
                            "modules), injection (injection harness "
                            "+ clip grid), or rest (everything else "
                            "offline).")
    group.add_argument("--only", metavar="MODULE",
                       help="Run a single test module "
                            "(e.g. test_blend).")
    ap.add_argument("-v", "--verbose", action="count", default=1,
                    help="Verbosity (default: -v once).")
    args = ap.parse_args(argv)

    loader = unittest.TestLoader()
    suite = loader.discover(str(ROOT / "tests"), pattern="test_*.py")
    label = "full"
    if args.fast:
        suite = _select(
            suite, _modules_in(suite) - DOWNLOAD_TESTS)
        label = "fast — no downloads"
    elif args.smoke:
        suite = _select(suite, SMOKE_MODULES)
        label = "smoke tier (<=3 min PR check)"
    elif args.shard == "golden":
        suite = _select(suite, SHARD_GOLDEN)
        label = "shard golden (pipeline-run modules)"
    elif args.shard == "injection":
        suite = _select(suite, SHARD_INJECTION)
        label = "shard injection (injection harness + clip grid)"
    elif args.shard == "rest":
        rest = (_modules_in(suite) - DOWNLOAD_TESTS
                - SHARD_GOLDEN - SHARD_INJECTION)
        suite = _select(suite, rest)
        label = "shard rest (everything else offline)"
    elif args.only:
        only = args.only.split(".")[-1]
        if only not in _modules_in(suite):
            ap.error(f"no test module {only!r} discovered")
        suite = _select(suite, {only})
        label = f"only {only}"

    print(f"Exoplanet Hunter golden suite ({label})\n", flush=True)
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


if __name__ == "__main__":
    raise SystemExit(main())
