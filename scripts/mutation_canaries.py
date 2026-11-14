#!/usr/bin/env python3
"""Mutation canaries (Phase 1.2, item C-6).

Claude's bet, from the Phase 1.1 vote: revert each hard-rule
behaviour and confirm a test goes red — if a reverted rule stays
green, the suite does not actually guard it. Each canary copies
the repo to a THROWAWAY directory (the real tree is never
touched), applies one mutation by string replacement, runs the
test modules that should catch it, and reports RED (caught) or
GREEN (coverage gap).

Exit 0 when every executable canary goes red; exit 1 when any
canary stays green, a mutation does not apply, or a test run
errors/times out.

The 180-arcsecond neighbour rule (F-1) has a code target now:
gauntlet_v2's neighbour_search_radius_arcsec. Its canary
mutates the policy value 180.0 -> 60.0 and re-hashes the
registry in the throwaway copy (so the suite fails on the VALUE
change, not on a hash mismatch), then runs tests.test_census —
the policy-radius test and the S97 host test must go red. (In
Phase 1.2 the rule had NO code target — prose only, code
default 60" — and the canary verified that finding instead.
That check is gone: the rule is implemented now.)

Usage (from the repo root, with the venv python):
  .venv/bin/python scripts/mutation_canaries.py [--canary NAME]
"""
import argparse
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
                "(mad_clip.DEFAULT_FLOOR_FRAC = 0.10, the single "
                "definition since F-11)",
        "mutations": [
            _mut("mad_clip.py",
                 "DEFAULT_FLOOR_FRAC = 0.10",
                 "DEFAULT_FLOOR_FRAC = 0.0"),
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
    {
        # F-1: the neighbour-search radius is a policy value now,
        # so the mutation reverts it to the old 60-arcsecond
        # default. The registry is re-hashed in the throwaway
        # copy after the mutation (see _rehash_registry) so the
        # suite fails on the VALUE change — the policy-radius
        # test and the S97 host test — not on a hash mismatch.
        "name": "neighbour-180arcsec",
        "rule": "neighbour-search radius is the policy value "
                "180 arcseconds (gauntlet_v2)",
        "mutations": [
            _mut("calibration/gauntlet_v2.yaml",
                 "neighbour_search_radius_arcsec: 180.0",
                 "neighbour_search_radius_arcsec: 60.0"),
        ],
        "post": "_rehash_registry",
        "tests": ["tests.test_census"],
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


def _rehash_registry(repo):
    """Re-hash calibration/registry.json in the throwaway copy
    after a mutation changed a profile's bytes. Without this,
    a policy-value mutation would fail at load time on the hash
    mismatch — the canary would go red for the wrong reason.
    Returns an error string or None."""
    import hashlib
    import json
    cal_dir = repo / "calibration"
    reg_path = cal_dir / "registry.json"
    try:
        reg = json.loads(reg_path.read_text())
        for entry in reg["entries"]:
            prof = cal_dir / f"{entry['calibration_id']}.yaml"
            entry["sha256"] = hashlib.sha256(
                prof.read_bytes()).hexdigest()
        reg_path.write_text(json.dumps(reg, indent=2) + "\n")
    except (OSError, ValueError, KeyError) as exc:
        return f"registry re-hash failed: {exc}"
    return None


_POST_STEPS = {"_rehash_registry": _rehash_registry}


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


def run_canary(canary):
    """Run one mutation canary; return (outcome, detail).

    outcome is RED (caught — good), GREEN (not caught —
    coverage gap), or ERROR."""
    repo = _copy_tree()
    try:
        err = _apply_mutations(repo, canary)
        if err is None and canary.get("post"):
            err = _POST_STEPS[canary["post"]](repo)
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
    print()
    if failures:
        print(f"FAIL: {', '.join(failures)} — see above")
        return 1
    print("OK: every executable canary went red")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
