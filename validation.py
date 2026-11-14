"""Runtime validation of output records against schema/*.json
(Phase 1.1, item 3).

The schemas existed in Phase 1 but nothing enforced them — a writer
could drift a field name, drop a required key, or add a "helpful"
extra key and nothing would notice until a downstream parser broke
silently. Every writer now validates at serialization time and
fails LOUD on the first bad record: a malformed record is a code
bug, and the run must stop, not write a corrupt handoff.

    validate_survivor(record)   # bulk_screen.py write path
    validate_verdict(record)    # gauntlet verdict records

Both raise RecordValidationError listing the offending fields.
The validators are Draft 2020-12. Timestamps are constrained by
a `pattern` in the schema, not `format: date-time` — the format
check needs the optional rfc3339-validator package, and without
it jsonschema silently skips the check (found by the test suite);
a pattern is enforced by the core validator with no extra
dependency. Schemas are loaded once and cached; the schema files
themselves are checked with check_schema at load time so a broken
schema fails at import, not at the first record.
"""
import json
from pathlib import Path

import jsonschema
from jsonschema import Draft202012Validator

SCHEMA_DIR = Path(__file__).resolve().parent / "schema"

_VALIDATORS = {}


class RecordValidationError(ValueError):
    """A record failed schema validation. The message lists the
    offending fields — fix the writer, never the schema, to make
    a bad record pass."""


def _validator(kind):
    if kind not in ("survivor", "verdict"):
        raise ValueError(f"unknown record kind: {kind!r}")
    if kind not in _VALIDATORS:
        path = SCHEMA_DIR / f"{kind}-schema.json"
        schema = json.loads(path.read_text())
        Draft202012Validator.check_schema(schema)
        _VALIDATORS[kind] = Draft202012Validator(schema)
    return _VALIDATORS[kind]


def validate_record(kind, record):
    """Validate `record` against the `kind` schema. Returns the
    record unchanged on success; raises RecordValidationError
    listing every violation on failure."""
    validator = _validator(kind)
    errors = sorted(validator.iter_errors(record),
                    key=lambda e: list(e.absolute_path))
    if not errors:
        return record
    detail = "; ".join(
        f"{'.'.join(str(p) for p in e.absolute_path) or '<root>'}: "
        f"{e.message}" for e in errors[:8])
    if len(errors) > 8:
        detail += f"; … and {len(errors) - 8} more"
    raise RecordValidationError(
        f"{kind} record failed validation ({len(errors)} error(s)): "
        f"{detail}")


def validate_survivor(record):
    """Validate one bulk-screen survivor record."""
    return validate_record("survivor", record)


def validate_verdict(record):
    """Validate one gauntlet verdict record."""
    return validate_record("verdict", record)
