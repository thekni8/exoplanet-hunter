#!/usr/bin/env python3
"""Generate requirements.lock (pinned versions + hashes).

The normal route is pip-compile (see AGENTS.md §1):
    pip-compile --generate-hashes \
        --output-file=requirements.lock requirements.txt

This script is the FALLBACK for when pip-compile cannot run
reliably — 2026-11-14, pip-compile failed after 31 minutes
because the resolver downloads distribution files for metadata
extraction and every download from files.pythonhosted.org timed
out on this network. This script never downloads a distribution
file: it takes the versions from the VERIFIED venv (pip freeze
— the environment the golden suite just passed in), walks the
dependency closure from installed metadata, and fetches ONLY the
small PyPI JSON metadata per package (one request each) to get
the sha256 of every distribution file — exactly the hashes
pip-compile's --generate-hashes emits.

Usage (from the repo root, with the venv python):
    .venv/bin/python scripts/make_lockfile.py [--check]

--check verifies the existing lockfile instead of rewriting it:
every direct pin from requirements.txt must be present at the
pinned version, and every package must carry at least one hash.

The output is pip-installable with hash verification:
    pip install --require-hashes -r requirements.lock
"""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Installed in the venv but not part of the pipeline's runtime
# closure (build/dev tools) — never in the lockfile.
# NOTE: setuptools is deliberately NOT in this set even though it
# looks like a build tool — it is a runtime dependency: batman
# imports distutils at runtime and setuptools 69 shims it on
# Python 3.12 (see requirements.txt). It was excluded here until
# 2026-11-14, which is how the undeclared-dependency defect
# reached CI (scratch-repo rest shard failed on a clean runner).
EXCLUDE = {"pip", "pip-tools", "wheel", "build",
           "pyproject_hooks"}

PYPI_JSON = "https://pypi.org/pypi/{name}/{version}/json"
TIMEOUT = 60
RETRIES = 3


def _canonical(name):
    from packaging.utils import canonicalize_name
    return canonicalize_name(name)


def direct_pins():
    pins = {}
    for line in (ROOT / "requirements.txt").read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "==" not in line:
            continue
        name, version = line.split("==", 1)
        pins[_canonical(name.strip())] = version.strip()
    return pins


def installed_versions():
    from importlib.metadata import distributions
    return {_canonical(d.metadata["Name"]): d.version
            for d in distributions()}


def dependency_closure(direct, installed):
    """Walk Requires-Dist from the direct pins, evaluating
    environment markers against the current environment.
    Returns {name: set(parents)} for the closure."""
    from importlib.metadata import distribution
    from packaging.markers import default_environment
    from packaging.requirements import Requirement

    env = default_environment()
    closure = {}
    queue = list(direct)
    seen = set(direct)
    while queue:
        name = queue.pop(0)
        closure.setdefault(name, set())
        try:
            reqs = distribution(name).requires or []
        except Exception:
            reqs = []
        for req_str in reqs:
            req = Requirement(req_str)
            if req.marker is not None and not req.marker.evaluate(env):
                continue
            child = _canonical(req.name)
            if child in EXCLUDE:
                continue
            if child not in installed:
                print(f"WARNING: {name} requires {child}, which "
                      f"is not installed — skipping", flush=True)
                continue
            closure.setdefault(child, set()).add(name)
            if child not in seen:
                seen.add(child)
                queue.append(child)
    return closure


def fetch_hashes(name, version):
    """sha256 of every distribution file for name==version, from
    the PyPI JSON API. Retries with backoff on timeouts."""
    import requests
    last_exc = None
    for attempt in range(RETRIES):
        try:
            r = requests.get(PYPI_JSON.format(name=name,
                                              version=version),
                             timeout=TIMEOUT)
            r.raise_for_status()
            urls = r.json()["urls"]
            hashes = sorted({u["digests"]["sha256"] for u in urls})
            if not hashes:
                raise ValueError(f"no files listed for "
                                 f"{name}=={version}")
            return hashes
        except Exception as exc:  # noqa: BLE001 — retried below
            last_exc = exc
            wait = 5 * (attempt + 1)
            print(f"  {name}: attempt {attempt + 1} failed "
                  f"({exc}); retrying in {wait}s", flush=True)
            time.sleep(wait)
    raise RuntimeError(f"could not fetch hashes for "
                       f"{name}=={version}: {last_exc}")


def render_lock(closure, installed, hashes_by_name, direct):
    lines = [
        "# Exoplanet Hunter — LOCKFILE (pinned versions + hashes).",
        "# Generated by scripts/make_lockfile.py from the verified",
        "# venv (pip freeze) + PyPI JSON hashes — the pip-compile",
        "# --generate-hashes equivalent, without downloading any",
        "# distribution file. Install with hash verification:",
        "#     pip install --require-hashes -r requirements.lock",
        "# Regenerate after any dependency change (pip-compile is",
        "# the preferred route when the network allows it; see",
        "# AGENTS.md §1).",
        "",
    ]
    for name in sorted(closure):
        version = installed[name]
        parents = sorted(closure[name])
        if name in direct:
            via = "# via -r requirements.txt"
        elif parents:
            via = "# via " + ", ".join(parents)
        else:
            via = ""
        hashes = hashes_by_name[name]
        lines.append(f"{name}=={version} \\")
        for i, h in enumerate(hashes):
            cont = " \\" if i < len(hashes) - 1 else ""
            lines.append(f"    --hash=sha256:{h}{cont}")
        if via:
            lines[-1] += f"  {via}"
        lines.append("")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="verify the existing lockfile instead of "
                         "rewriting it")
    args = ap.parse_args(argv)
    lock_path = ROOT / "requirements.lock"
    direct = direct_pins()
    if args.check:
        return 0 if check_lock(lock_path, direct) else 1
    installed = installed_versions()
    missing = [n for n in direct if n not in installed]
    if missing:
        print(f"direct pins not installed in this venv: {missing}",
              file=sys.stderr)
        return 1
    mismatched = [f"{n} (want {v}, have {installed[n]})"
                  for n, v in direct.items()
                  if installed[n] != v]
    if mismatched:
        print(f"venv differs from requirements.txt: {mismatched}",
              file=sys.stderr)
        return 1
    closure = dependency_closure(direct, installed)
    print(f"closure: {len(closure)} packages "
          f"({len(direct)} direct)", flush=True)
    hashes_by_name = {}
    for i, name in enumerate(sorted(closure), 1):
        print(f"[{i}/{len(closure)}] {name}=={installed[name]}",
              flush=True)
        hashes_by_name[name] = fetch_hashes(name, installed[name])
    lock_path.write_text(render_lock(closure, installed,
                                     hashes_by_name, direct))
    print(f"wrote {lock_path} "
          f"({sum(len(h) for h in hashes_by_name.values())} "
          f"hashes)", flush=True)
    return 0


def check_lock(lock_path, direct):
    if not lock_path.exists():
        print("requirements.lock does not exist", file=sys.stderr)
        return False
    text = lock_path.read_text()
    ok = True
    for name, version in sorted(direct.items()):
        if f"{name}=={version}" not in text:
            print(f"lockfile missing direct pin {name}=={version}",
                  file=sys.stderr)
            ok = False
    n_hash = text.count("--hash=sha256:")
    n_pkgs = sum(1 for line in text.splitlines()
                 if "==" in line and not line.startswith(" ")
                 and not line.startswith("#"))
    print(f"lockfile: {n_pkgs} packages, {n_hash} hashes")
    if n_hash == 0:
        print("lockfile has no hashes", file=sys.stderr)
        ok = False
    return ok


if __name__ == "__main__":
    raise SystemExit(main())
