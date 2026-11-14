"""Versioned calibration profiles (Phase 1.1, item 2).

Thresholds live in code, not in recipes — that decision stands
(Phase 1): per-run thresholds would make screens incomparable. But
thresholds also change over time (the Sector 98 recalibration is
already pending), so every threshold set lives in a versioned
profile file under calibration/:

    calibration/bulk_v1.yaml      bulk-screen thresholds
    calibration/deep_v1.yaml      deep-pipeline thresholds
    calibration/gauntlet_v1.yaml  vetting-gauntlet thresholds

Rules (see calibration/README.md):
  * A profile is IMMUTABLE once used in a run. To change a
    threshold, copy the file to a new version (bulk_v2.yaml),
    bump its `version` field, and update the code + golden suite
    in the same change.
  * The `version` field must match the filename — a copy that
    forgets the bump fails loudly at load time.
  * Every output record stamps its calibration version
    (provenance.py), so records from different calibrations are
    never silently mixed.
  * Immutability is ENFORCED, not just documented (Phase 1.2,
    item A-1): calibration/registry.json records the sha256 of
    every profile version. The loader recomputes the hash and
    rejects a mismatch — a silent edit to a frozen profile fails
    at load time, not at audit time. The registry is append-only:
    new versions add entries; existing entries are never edited
    (CI diffs the registry against the base branch). The expected
    hash lives in the registry, NOT in the profile itself — an
    edit to the profile cannot also rewrite its own expected
    hash. v1 profiles are grandfathered through the registry
    (their status/rationale live there); profiles v2 and later
    must carry `status` and `rationale` fields in the file
    itself.
"""
import hashlib
import json
import re
from pathlib import Path

import yaml

CALIBRATION_DIR = Path(__file__).resolve().parent / "calibration"
REGISTRY_FILENAME = "registry.json"


class CalibrationError(ValueError):
    """Raised when a profile is missing, malformed, or mis-versioned."""


def profile_sha256(name):
    """sha256 of a profile file's bytes — the content hash the
    registry pins. ANY byte change (including a comment edit)
    changes the hash: a frozen profile is frozen."""
    path = CALIBRATION_DIR / f"{name}.yaml"
    if not path.exists():
        raise CalibrationError(
            f"calibration profile not found: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_registry():
    """The registry dict {calibration_id: entry}. Raises
    CalibrationError when the registry file is missing or
    malformed — a checkout without a registry cannot verify
    anything, so it verifies nothing by failing loudly."""
    path = CALIBRATION_DIR / REGISTRY_FILENAME
    if not path.exists():
        raise CalibrationError(
            f"calibration registry not found: {path} — every "
            f"profile version must be registered")
    try:
        reg = json.loads(path.read_text())
        entries = reg["entries"]
    except (ValueError, KeyError) as exc:
        raise CalibrationError(
            f"calibration registry {path} is malformed: {exc}"
        ) from exc
    out = {}
    for entry in entries:
        try:
            out[entry["calibration_id"]] = entry
        except (TypeError, KeyError) as exc:
            raise CalibrationError(
                f"calibration registry {path} has an entry "
                f"without calibration_id: {entry!r}") from exc
    return out


def registry_entry_for(name, status, rationale, supersedes=None):
    """Build the registry entry for a NEW profile version (used
    when registering a profile: write the file, then add the
    entry this returns to calibration/registry.json). The hash
    is computed from the file as it stands — register AFTER the
    file is final, never before."""
    return {
        "calibration_id": name,
        "sha256": profile_sha256(name),
        "status": status,
        "rationale": rationale,
        "supersedes": supersedes,
    }


def version_number(name):
    """The version number of a profile name (bulk_v2 -> 2).
    Returns 1 for names without a _vN suffix."""
    m = re.search(r"_v(\d+)$", name)
    return int(m.group(1)) if m else 1


def _verify_against_registry(name):
    """The A-1 enforcement: the profile's bytes must hash to the
    registry entry. Raises CalibrationError on a missing entry
    or a mismatch — either way the profile is not what the
    registry says it is."""
    registry = load_registry()
    entry = registry.get(name)
    if entry is None:
        raise CalibrationError(
            f"calibration profile {name!r} has no registry entry "
            f"— register it in {REGISTRY_FILENAME} before use")
    actual = profile_sha256(name)
    if entry.get("sha256") != actual:
        raise CalibrationError(
            f"calibration profile {name!r} does not match its "
            f"registry hash — the file was modified after "
            f"registration (registry {entry.get('sha256')}, "
            f"file {actual}). Frozen profiles are immutable: "
            f"copy to a new version instead of editing.")


def profile_name(subsystem, version):
    """The calibration profile name for a (subsystem, version)
    pair: ("bulk", "v1") -> "bulk_v1". The provenance header
    records versions as a per-subsystem map ({"bulk": "v1"} —
    brief §A-2); this resolves the map back to the profile file.
    Strict: the version is the bare version, never a full name —
    passing "bulk_v1" as the version would resolve to the
    nonexistent "bulk_bulk_v1" and fail loudly, as it should."""
    return f"{subsystem}_{version}"


def short_version(name):
    """The bare version of a profile name: "bulk_v1" -> "v1".
    Inverse of profile_name for well-formed names."""
    if "_" not in name:
        raise CalibrationError(
            f"malformed calibration profile name {name!r}: "
            f"expected '<subsystem>_<version>'")
    return name.split("_", 1)[1]


def load_profile(name):
    """Load a calibration profile by version name (e.g. "bulk_v1").
    Returns the profile dict. Raises CalibrationError if the file
    is missing, is not a mapping, declares a different version
    than its filename, lacks the required v2+ fields, or does
    not match its registry hash."""
    path = CALIBRATION_DIR / f"{name}.yaml"
    if not path.exists():
        raise CalibrationError(
            f"calibration profile not found: {path}")
    try:
        prof = yaml.safe_load(path.read_text())
    except yaml.YAMLError as exc:
        raise CalibrationError(
            f"calibration profile {path} is not valid YAML: {exc}"
        ) from exc
    if not isinstance(prof, dict):
        raise CalibrationError(
            f"calibration profile {path} must be a YAML mapping")
    if prof.get("version") != name:
        raise CalibrationError(
            f"calibration profile {path} declares version "
            f"{prof.get('version')!r}, expected {name!r} — bump the "
            f"version field when you copy a profile")
    if version_number(name) >= 2:
        for field in ("status", "rationale"):
            if not isinstance(prof.get(field), str) \
                    or not prof[field].strip():
                raise CalibrationError(
                    f"calibration profile {path} (v2+) must "
                    f"declare a non-empty {field!r} field")
    _verify_against_registry(name)
    return prof


def available_profiles():
    """Sorted names of the profiles on disk (e.g. ['bulk_v1'])."""
    return sorted(p.stem for p in CALIBRATION_DIR.glob("*.yaml"))
