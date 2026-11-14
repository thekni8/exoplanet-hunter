# Calibration profiles

Thresholds live in code, not in recipes (Phase 1 decision: per-run
thresholds would make screens incomparable). These files are the
versioned record of those thresholds — one profile per pipeline,
immutable once used in a run.

## Files

| Profile | Pipeline | Loaded by |
|---|---|---|
| `bulk_v1.yaml` | bulk screen | `bulk_screen.py` reads it at import; the module constants (`RECORD_FLOOR_SDE`, …) are derived from it |
| `bulk_v2.yaml` | bulk screen | same loader, selected with `--calibration bulk_v2` (or `EXHUNT_BULK_CALIBRATION=bulk_v2`); clip option `floor_10pct` + per-sector systematic windows (see `bulk/SENSITIVITY_MAP.md`) |
| `deep_v1.yaml` | deep pipeline (`hunter.py`) | drift-tested: `tests/test_calibration.py` asserts the profile matches `hunter.py`'s named constants |
| `gauntlet_v1.yaml` | vetting gauntlet | drift-tested against `gauntlet/` + `persistence.py` constants |

## Rules

1. **A profile is immutable once used in a run.** Never edit a
   profile version that has stamped records — those records' meaning
   would silently change.
2. **To change a threshold:** copy the file to the next version
   (`bulk_v2.yaml`), bump its `version` field (it must match the
   filename — the loader refuses a mismatch), update the code to
   load the new version, and update the golden suite in the same
   change. Then re-run the injection harness: a threshold change
   without a completeness re-measurement is flying blind.
3. **Every output record stamps its calibration version**
   (`provenance.py`). Records from different calibrations are never
   silently mixed — a Sector 98 screen before recalibration and
   after recalibration are distinguishable in the data.
4. **The bulk profile is the source of truth for the bulk screen.**
   The deep/gauntlet profiles are drift-tested snapshots: the code
   keeps its named constants, and the suite fails if code and
   profile disagree. Either way, a threshold change is a deliberate,
   reviewed change — never a quiet edit.
