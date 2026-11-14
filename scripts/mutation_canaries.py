#!/usr/bin/env python3
"""Mutation canaries (Phase 1.2, item C-6).

Claude's bet, from the Phase 1.1 vote: revert each hard-rule
behaviour and confirm a test goes red — if a reverted rule stays
green, the suite does not actually guard it. Each canary copies
the repo to a THROWAWAY directory (the real tree is never
touched), applies one mutation by string replacement, runs the
test modules that should catch it, and reports RED (caught) or
GREEN (coverage gap).

Exit 0 when every executable canary goes red and the no-target
verification holds; exit 1 when any canary stays green, a
mutation does not apply, or a test run errors/times out.

The 180-arcsecond neighbour rule has NO executable target: it
exists only as prose in docs/vetting-manual.md, and the code's
neighbour census (gauntlet/diffimg.py tic_cone_census) defaults
to 60 arcseconds — there is no 180 to mutate. That canary
verifies the finding still holds (prose present, no code
target); if someone later implements the rule in code, this
canary reports NEEDS-UPDATE and the mutation must be defined
then. Changing the 60" default to 180" is a science/behaviour
change needing a calibration decision — it is flagged for the
vote, not done here.

Usage (from the repo root, with the venv python):
  .venv/bin/python scripts/mutation_canaries.py [--canary NAME]
"""
import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Directories never copied into the throwaway tree: version
# control, caches, and run data (which the brief forbids touching).
IGNORE = shutil.ignore_patterns(
    ".git", "__pycache__", "*.pyc", ".venv", "bulk/cache",
    "bulk/run_*", "vetting_results", "sweep-output", "results",
    "data", "reports")

TEST_TIMEOUT_S = 600


def _mut(path, old, new):
    """One string-replacement mutation; (relative path, old, new)."""
    return (path, old, new)


CANARIES = [
    {
        "name": "chi2-floor",
        "rule": "persistence stamp 15% systematic floor "
                "(CHI2_SYS_FRAC = 0.15)",
        "mutations": [
            _mut("persistence.py",
                 "CHI2_SYS_FRAC = 0.15", "CHI2_SYS_FRAC = 0.0"),
        ],
        "tests": ["tests.test_stamp", "tests.test_calibration"],
    },
    {
        "name": "mad-clip-floor",
        "rule": "gauntlet MAD-clip 10% depth floor "
                "(MAD_CLIP_FLOOR_FRAC = 0.10, both definitions)",
        "mutations": [
            _mut("gauntlet/rawflux_check.py",
                 "MAD_CLIP_FLOOR_FRAC = 0.10",
                 "MAD_CLIP_FLOOR_FRAC = 0.0"),
            _mut("gauntlet/transit_fit.py",
                 "MAD_CLIP_FLOOR_FRAC = 0.10",
                 "MAD_CLIP_FLOOR_FRAC = 0.0"),
        ],
        "tests": ["tests.test_calibration",
                  "tests.test_false_positives",
                  "tests.test_gauntlet_clip"],
    },
    {
        "name": "clean-refold-gate",
        "rule": "clean-data re-fold gate drops flagged-cadence "
                "artifacts (verdict_for returns FAIL)",
        "mutations": [
            _mut("bulk/clean_refold_gate.py",
                 '        return "FAIL"\n',
                 '        return "PASS"\n'),
        ],
        "tests": ["tests.test_false_positives"],
    },
]


def _copy_tree():
    tmp = Path(tempfile.mkdtemp(prefix="mutation-canary-"))
    shutil.copytree(ROOT, tmp / "repo", ignore=IGNORE)
    return tmp / "repo"


def _apply_mutations(repo, canary):
    """Apply the mutations; return an error string or None."""
    for rel, old, new in canary["mutations"]:
        path = repo / rel
        text = path.read_text()
        if text.count(old) != 1:
            return (f"{rel}: expected exactly 1 occurrence of "
                    f"{old!r}, found {text.count(old)} — the "
                    f"canary no longer applies to this code")
        path.write_text(text.replace(old, new))
    return None


def _run_tests(repo, modules):
    """Run unittest modules in the throwaway copy.

    Returns (went_red, tail): went_red is True when the suite
    fails (the canary was caught), False when it passes (the
    coverage gap this script exists to find)."""
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "unittest"] + modules,
            cwd=repo, capture_output=True, text=True,
            timeout=TEST_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return None, f"TIMEOUT after {TEST_TIMEOUT_S}s"
    tail = "\n".join((proc.stdout + proc.stderr).splitlines()[-5:])
    return proc.returncode != 0, tail


def _check_180arcsec():
    """The 180-arcsecond canary: verify the no-target finding.

    Returns (ok, message): ok is True when the prose rule is
    still in the manual and no code target exists. If either
    changes, the canary needs a human to redefine it."""
    manual = ROOT / "docs" / "vetting-manual.md"
    prose = "180 arcseconds" in manual.read_text()
    code_hits = []
    # A standalone 180 (not 1800, 1180, ...): a real code target
    # for the rule would appear as its own number.
    pat = re.compile(r"\b180\b")
    for rel in ("gauntlet", "bulk"):
        for path in (ROOT / rel).rglob("*.py"):
            for i, line in enumerate(path.read_text().splitlines(),
                                     start=1):
                if pat.search(line.split("#")[0]):
                    code_hits.append(f"{path.relative_to(ROOT)}:{i}")
    for i, line in enumerate(
            (ROOT / "hunter.py").read_text().splitlines(), start=1):
        if pat.search(line.split("#")[0]):
            code_hits.append(f"hunter.py:{i}")
    if not prose:
        return False, ("the 180-arcsecond prose rule is GONE from "
                       "docs/vetting-manual.md — redefine this "
                       "canary")
    if code_hits:
        return False, ("a code target now exists for the "
                       f"180-arcsecond rule: {code_hits} — define "
                       "a real mutation for this canary")
    return True, ("no executable target: the rule exists only as "
                  "prose in docs/vetting-manual.md:148; the "
                  "code's census (gauntlet/diffimg.py "
                  "tic_cone_census) defaults to 60 arcseconds")


def run_canary(canary):
    """Run one mutation canary; return (outcome, detail).

    outcome is RED (caught — good), GREEN (not caught —
    coverage gap), or ERROR."""
    repo = _copy_tree()
    try:
        err = _apply_mutations(repo, canary)
        if err is not None:
            return "ERROR", err
        went_red, tail = _run_tests(repo, canary["tests"])
        if went_red is None:
            return "ERROR", tail
        if went_red:
            return "RED", tail
        return "GREEN", tail
    finally:
        shutil.rmtree(repo.parent, ignore_errors=True)


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Run the mutation canaries (C-6).")
    ap.add_argument("--canary", default=None,
                    help="run only the named canary")
    args = ap.parse_args(argv)
    selected = [c for c in CANARIES
                if args.canary is None or c["name"] == args.canary]
    if args.canary is not None and not selected:
        print(f"unknown canary: {args.canary!r} "
              f"(known: {[c['name'] for c in CANARIES]})")
        return 2
    print("mutation canaries — throwaway copies only, "
          "the real tree is never touched\n")
    failures = []
    for canary in selected:
        print(f"[{canary['name']}] {canary['rule']}")
        outcome, detail = run_canary(canary)
        print(f"  -> {outcome}")
        for line in detail.splitlines():
            print(f"     {line}")
        if outcome != "RED":
            failures.append(canary["name"])
    if args.canary is None:
        print("[neighbour-180arcsec] 180-arcsecond neighbour "
              "search (prose rule, no code target)")
        ok, msg = _check_180arcsec()
        print(f"  -> {'NO-TARGET (verified)' if ok else 'NEEDS-UPDATE'}")
        print(f"     {msg}")
        if not ok:
            failures.append("neighbour-180arcsec")
    print()
    if failures:
        print(f"FAIL: {', '.join(failures)} — see above")
        return 1
    print("OK: every executable canary went red; the 180-arcsecond "
          "no-target finding holds")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
