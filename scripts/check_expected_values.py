#!/usr/bin/env python3
"""Flag changes to the golden-star expected values and to
calibration/ (Phase 1.2, item C-7).

Runs in CI (.github/workflows/golden.yml) after the registry
check. It diffs tests/expected_values.json against the base ref
(default origin/main) and lists any changed files under
calibration/, printing a plain-words summary of WHAT changed and
emitting a GitHub ::warning:: annotation per change.

This flags, it does not block: a changed expected value or a new
calibration version can be legitimate (a pipeline improvement, a
new profile), but it must never slip through unnoticed — the
numbers in expected_values.json are the pipeline's own known
answers, and changing them is changing what "the pipeline still
works" means. Exit 0 unless the CURRENT expected-values file is
unreadable (that breaks the tests anyway, so fail loudly).

Usage:
  python scripts/check_expected_values.py [--base REF]
      [--repo-root PATH]
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

VALUES_REL = "tests/expected_values.json"


def diff_expected_values(old, new):
    """Pure diff of two parsed expected-values dicts.

    Returns a list of plain-words change lines, one per changed
    leaf: added/removed stars, added/removed/changed fields.
    The top-level 'notes' field is prose, not a number — a change
    there is reported but marked as such."""
    lines = []

    def walk(path, a, b):
        if isinstance(a, dict) and isinstance(b, dict):
            for key in sorted(set(a) | set(b)):
                walk(f"{path}.{key}" if path else key,
                     a.get(key, _MISSING), b.get(key, _MISSING))
        elif a is _MISSING:
            lines.append(f"{path}: ADDED = {b!r}")
        elif b is _MISSING:
            lines.append(f"{path}: REMOVED (was {a!r})")
        elif a != b:
            lines.append(f"{path}: {a!r} -> {b!r}")

    class _Missing:
        pass
    _MISSING = _Missing()
    walk("", old, new)
    return lines


def _git(repo_root, *args):
    try:
        out = subprocess.run(["git"] + list(args), cwd=repo_root,
                             capture_output=True, text=True,
                             timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    return out.stdout


def base_values(repo_root, base):
    """The expected values at the base ref, or None if the ref
    cannot be resolved or the file did not exist there."""
    text = _git(repo_root, "show", f"{base}:{VALUES_REL}")
    if text is None:
        return None
    try:
        return json.loads(text)
    except ValueError:
        return None


def changed_calibration_files(repo_root, base):
    """Files under calibration/ changed between base and HEAD,
    or None if the diff cannot be computed."""
    out = _git(repo_root, "diff", "--name-only",
               f"{base}...HEAD", "--", "calibration/")
    if out is None:
        return None
    return sorted(p for p in out.splitlines() if p.strip())


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Flag changes to the expected values and "
                    "calibration/ (see module docstring).")
    ap.add_argument("--base", default="origin/main",
                    help="base ref for the diff "
                         "(default: origin/main)")
    ap.add_argument("--repo-root", default=str(ROOT),
                    help="repo root (default: this checkout)")
    args = ap.parse_args(argv)
    repo_root = Path(args.repo_root)
    values_path = repo_root / VALUES_REL
    try:
        current = json.loads(values_path.read_text())
    except (OSError, ValueError) as exc:
        print(f"EXPECTED-VALUES CHECK FAILED: {values_path} "
              f"unreadable: {exc}", flush=True)
        return 1
    findings = []
    old = base_values(repo_root, args.base)
    if old is None:
        print(f"note: base ref {args.base!r} has no "
              f"{VALUES_REL} (new file, or ref unresolvable) — "
              f"no expected-values diff to report", flush=True)
    else:
        for line in diff_expected_values(old, current):
            findings.append(
                f"expected value changed: {line}")
    cal = changed_calibration_files(repo_root, args.base)
    if cal is None:
        print(f"note: could not diff calibration/ against "
              f"{args.base!r} — skipping calibration list",
              flush=True)
    else:
        for path in cal:
            findings.append(f"calibration file changed: {path}")
    if not findings:
        print("expected-values check OK: no changes vs "
              f"{args.base}", flush=True)
        return 0
    print("EXPECTED-VALUES / CALIBRATION CHANGES vs "
          f"{args.base}:", flush=True)
    for finding in findings:
        print(f"  - {finding}", flush=True)
        print(f"::warning::{finding}", flush=True)
    print("(flag only — this check never blocks the run)",
          flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
