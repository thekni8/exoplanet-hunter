"""Provenance headers and run manifests (Phase 1.1, item 1).

Every output record the pipeline writes — bulk-screen survivors and
gauntlet verdicts — carries a provenance header so any result can be
traced back to the exact code, calibration, recipe, and run that
produced it:

    schema_version      provenance schema version ("1.1")
    run_id              unique id for the run, e.g.
                        bulk-20261114T063000Z-a1b2
    pipeline_git_sha    short git SHA of the code that ran
                        ("unknown" when git is unavailable — never
                        a crash, but never a silent lie either)
    calibration_version versioned calibration profile, e.g. "bulk_v1"
    timestamp_utc       run start, ISO 8601 UTC (one timestamp per
                        run, so records from one run sort together
                        and the determinism test can fix it)
    recipe_hash         sha256 of the RESOLVED recipe (after CLI
                        overrides), when the run had a recipe —
                        the recipe file alone no longer describes
                        what ran once CLI > recipe applies

The header is stamped at write time, never reconstructed
afterwards: retrofitting provenance onto existing records is
impossible (the vote's unanimous #1 gap — "you'd have to re-run").

A run manifest (manifest.json, one per run directory) carries the
same information at run level, plus the environment (Python version,
requirements hash) and the recipe file hash, so a run directory is
self-describing years later.
"""
import hashlib
import json
import secrets
import subprocess
import sys
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

from atomic_io import atomic_write_json

SCHEMA_VERSION = "1.1"
PIPELINE_NAME = "exoplanet-hunter"


def repo_root():
    return Path(__file__).resolve().parent


@lru_cache(maxsize=1)
def git_sha(short=True):
    """Short git SHA of the working tree, or "unknown".

    Never raises: in a source export without .git (or with git
    missing), "unknown" is the honest answer — a record stamped
    "unknown" says plainly that its code version is untraced.
    """
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short" if short else "HEAD", "HEAD"],
            cwd=repo_root(), capture_output=True, text=True,
            timeout=10)
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    sha = out.stdout.strip()
    return sha if sha and out.returncode == 0 else "unknown"


def utc_now_iso():
    """Current UTC time, ISO 8601 with seconds, e.g.
    2026-11-14T06:30:00+00:00."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_run_id(kind="bulk"):
    """A unique run id: kind + UTC timestamp + 4 random hex chars."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{kind}-{stamp}-{secrets.token_hex(2)}"


def canonical_json(obj):
    """Canonical JSON for hashing: sorted keys, tight separators,
    non-JSON values stringified (so a recipe with a Path still
    hashes deterministically)."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      default=str)


def recipe_hash(resolved_recipe):
    """sha256 of the RESOLVED recipe (after CLI overrides).

    Keys starting with "_" are internal metadata (e.g. "_file",
    the recipe's path on this machine) and are excluded — the hash
    must describe what ran, not where the file lived.
    """
    public = {k: v for k, v in resolved_recipe.items()
              if not k.startswith("_")}
    return hashlib.sha256(
        canonical_json(public).encode("utf-8")).hexdigest()


def file_sha256(path):
    """sha256 of a file's bytes, or None if the file is missing."""
    path = Path(path)
    if not path.exists():
        return None
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def provenance_header(run_id, calibration_version, recipe_hash=None,
                      sha=None, timestamp_utc=None):
    """The header dict stamped onto every output record.

    `sha` and `timestamp_utc` default to the live values; tests pass
    explicit ones for determinism. `recipe_hash` is omitted (not
    null) when the run had no recipe — standalone bulk_screen runs
    and deep-pipeline runs carry no recipe hash.
    """
    header = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "pipeline_git_sha": sha if sha is not None else git_sha(),
        "calibration_version": calibration_version,
        "timestamp_utc": (timestamp_utc if timestamp_utc is not None
                          else utc_now_iso()),
    }
    if recipe_hash is not None:
        header["recipe_hash"] = recipe_hash
    return header


def build_manifest(run_id, calibration_version, sector=None,
                   product=None, recipe=None, recipe_file=None,
                   sha=None, timestamp_utc=None, status="started"):
    """The run-level manifest dict. `recipe` is the resolved recipe
    dict (or None); `recipe_file` its path. Callers add run-specific
    keys (counts, wall time) before writing, or write a second
    manifest with status="completed" at the end of the run."""
    root = repo_root()
    manifest = {
        "run_id": run_id,
        "schema_version": SCHEMA_VERSION,
        "pipeline": {
            "name": PIPELINE_NAME,
            "git_sha": sha if sha is not None else git_sha(),
        },
        "environment": {
            "python": sys.version.split()[0],
            "requirements_sha256": file_sha256(
                root / "requirements.txt"),
            "requirements_lock_sha256": file_sha256(
                root / "requirements-lock.txt"),
        },
        "calibration": {
            "version": calibration_version,
        },
        "execution": {
            "started_at": (timestamp_utc if timestamp_utc is not None
                           else utc_now_iso()),
            "status": status,
        },
    }
    if sector is not None:
        manifest["data"] = {"sector": sector, "product": product}
    if recipe is not None:
        manifest["recipe"] = {
            "file": str(recipe_file) if recipe_file else None,
            "file_sha256": (file_sha256(recipe_file)
                            if recipe_file else None),
            "resolved_hash": recipe_hash(recipe),
            "resolved": {k: v for k, v in recipe.items()
                         if not k.startswith("_")},
        }
    return manifest


def write_manifest(out_dir, manifest):
    """Atomically write manifest.json into `out_dir`. The manifest
    is the run directory's self-description — a partial manifest
    would be worse than none, so this is always an atomic write."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    return atomic_write_json(out_dir / "manifest.json", manifest)
