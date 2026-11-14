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
"""
from pathlib import Path

import yaml

CALIBRATION_DIR = Path(__file__).resolve().parent / "calibration"


class CalibrationError(ValueError):
    """Raised when a profile is missing, malformed, or mis-versioned."""


def load_profile(name):
    """Load a calibration profile by version name (e.g. "bulk_v1").
    Returns the profile dict. Raises CalibrationError if the file
    is missing, is not a mapping, or declares a different version
    than its filename."""
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
    return prof


def available_profiles():
    """Sorted names of the profiles on disk (e.g. ['bulk_v1'])."""
    return sorted(p.stem for p in CALIBRATION_DIR.glob("*.yaml"))
