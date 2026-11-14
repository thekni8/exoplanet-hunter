"""Loader for the golden-star expected values (Phase 1.2, C-7).

The acceptance numbers live in tests/expected_values.json so a
change to them is a visible, reviewable diff — scripts/
check_expected_values.py flags any change against the base
branch in CI. tests/golden_checks.py reads through here; the
rationale for each number stays in that module's docstrings.
"""
import json
from pathlib import Path

_VALUES_PATH = Path(__file__).resolve().parent / "expected_values.json"

_CACHE = None


def load_expected_values():
    """The parsed expected-values file (cached per process)."""
    global _CACHE
    if _CACHE is None:
        _CACHE = json.loads(_VALUES_PATH.read_text())
    return _CACHE


def star_values(tic):
    """The expected-values entry for one golden star (by TIC)."""
    return load_expected_values()["stars"][str(tic)]
