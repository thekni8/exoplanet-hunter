#!/usr/bin/env python3
"""Check the calibration registry (Phase 1.2, item A-1).

Two guards, both run in CI (.github/workflows/golden.yml):

  1. Hash verification — every registry entry's sha256 must match
     the profile file on disk, and every profile file on disk must
     have a registry entry. A silent edit to a frozen profile, or
     an unregistered new profile, fails here.
  2. Append-only diff — the registry at HEAD must not MODIFY or
     REMOVE any entry that exists at the base ref (default
     origin/main). New entries are fine; changing an existing
     entry's hash/status/rationale is rewriting history, and the
     registry exists precisely so history cannot be rewritten.

Usage:
  python scripts/check_registry.py [--base REF] [--no-diff]
      [--repo-root PATH]

--no-diff skips guard 2 (local runs without the base ref
available). When the base ref cannot be resolved, guard 2 is
skipped with a warning — the hash guard still runs.
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

GUARDED_FIELDS = ("sha256", "status", "rationale", "supersedes")


def _load_registry_text(text):
    return {e["calibration_id"]: e
            for e in json.loads(text)["entries"]}


def load_registry_file(path):
    return _load_registry_text(Path(path).read_text())


def verify_hashes(repo_root):
    """Guard 1. Returns a list of problem strings (empty = pass)."""
    problems = []
    cal_dir = Path(repo_root) / "calibration"
    reg_path = cal_dir / "registry.json"
    if not reg_path.exists():
        return [f"registry missing: {reg_path}"]
    try:
        registry = load_registry_file(reg_path)
    except (ValueError, KeyError) as exc:
        return [f"registry {reg_path} malformed: {exc}"]
    import hashlib
    for name, entry in sorted(registry.items()):
        prof = cal_dir / f"{name}.yaml"
        if not prof.exists():
            problems.append(
                f"registry entry {name}: profile file missing")
            continue
        actual = hashlib.sha256(prof.read_bytes()).hexdigest()
        if entry.get("sha256") != actual:
            problems.append(
                f"registry entry {name}: hash mismatch — file "
                f"was modified after registration (registry "
                f"{entry.get('sha256')}, file {actual})")
    for prof in sorted(cal_dir.glob("*.yaml")):
        if prof.stem not in registry:
            problems.append(
                f"profile {prof.name} has no registry entry — "
                f"register it before use")
    return problems


def registry_diff(old, new):
    """Guard 2 as a pure function. Returns a list of violations:
    modified or removed entries. Added entries are fine."""
    violations = []
    for name, old_entry in sorted(old.items()):
        if name not in new:
            violations.append(
                f"registry entry {name} was REMOVED — the "
                f"registry is append-only")
            continue
        for field in GUARDED_FIELDS:
            if old_entry.get(field) != new[name].get(field):
                violations.append(
                    f"registry entry {name}: field {field!r} "
                    f"changed ({old_entry.get(field)!r} -> "
                    f"{new[name].get(field)!r}) — existing "
                    f"entries are immutable")
    return violations


def base_registry(repo_root, base):
    """The registry at the base ref, or None if the ref cannot
    be resolved (caller decides: warn and skip the diff)."""
    try:
        out = subprocess.run(
            ["git", "show", f"{base}:calibration/registry.json"],
            cwd=repo_root, capture_output=True, text=True,
            timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    try:
        return _load_registry_text(out.stdout)
    except (ValueError, KeyError):
        return None


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Check the calibration registry (see module "
                    "docstring).")
    ap.add_argument("--base", default="origin/main",
                    help="base ref for the append-only diff "
                         "(default: origin/main)")
    ap.add_argument("--no-diff", action="store_true",
                    help="skip the base-branch diff (hash check "
                         "only)")
    ap.add_argument("--repo-root", default=str(ROOT),
                    help="repo root (default: this checkout)")
    args = ap.parse_args(argv)
    repo_root = Path(args.repo_root)
    problems = verify_hashes(repo_root)
    if not args.no_diff:
        old = base_registry(repo_root, args.base)
        if old is None:
            print(f"WARNING: base ref {args.base!r} unresolvable "
                  f"or has no registry — skipping append-only "
                  f"diff", flush=True)
        else:
            try:
                new = load_registry_file(
                    repo_root / "calibration" / "registry.json")
            except (ValueError, KeyError, OSError) as exc:
                problems.append(f"registry unreadable: {exc}")
                new = {}
            problems.extend(registry_diff(old, new))
    if problems:
        print("REGISTRY CHECK FAILED:", flush=True)
        for p in problems:
            print(f"  - {p}", flush=True)
        return 1
    print("registry check OK", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
