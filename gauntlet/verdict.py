"""Verdict-record builder (Phase 1.1, item 7).

The enforcement point for the unmeasured-status contract: the
ONLY way to produce a verdict record is build_verdict(), which
derives the final verdict from typed stage results
(gauntlet/stage_result.py) + imaging, stamps provenance, and
validates the record against schema/verdict-schema.json before
returning it. A record that fails validation is never written —
fix the vetting, never the schema, to make a bad record pass.

The schema enforces the candidate rule: final_verdict CANDIDATE
requires imaging populated with on_target == true, and every
listed stage at status "pass". build_verdict enforces the rest
in code via aggregate_verdict: any FAIL kills, any UNMEASURED /
INCONCLUSIVE / never-run required stage means INCONCLUSIVE, and
a candidate needs on-target imaging.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import provenance as _prov  # noqa: E402
from validation import validate_verdict  # noqa: E402

try:
    from gauntlet.stage_result import aggregate_verdict  # noqa: E402
except ImportError:  # run as a plain script from the gauntlet dir
    from stage_result import aggregate_verdict  # noqa: E402

CALIBRATION_VERSION = "gauntlet_v1"
# Provenance map (A-2): per-subsystem bare versions. A-4 moves
# the decision policy to gauntlet_v2 and this becomes {"gauntlet": "v2"}.
CALIBRATION_MAP = {"gauntlet": "v1"}


def build_verdict(tic, filed, stage_results, imaging=None,
                  ephemeris_used=None, verdict_note=None,
                  run_id=None, extra=None):
    """Assemble + validate one verdict record.

    tic: TIC id (string). filed: the filed ephemeris dict
    (period_days required; depth_pct, sde optional). stage_results:
    list of StageResult (gauntlet/stage_result.py). imaging: None
    or a dict with on_target / offset_px / offset_arcsec /
    blend_host_tic. ephemeris_used: the ephemeris the vetting
    folded on (period_d, t0, duration_d, source). verdict_note:
    one-paragraph human justification. run_id: explicit run id
    (a fresh one is generated when omitted). extra: legacy
    per-stage fields (rawflux_verdict, shape_gate,
    holdout_verdict) carried verbatim for backward compatibility
    with existing verdict readers.

    Returns the validated record dict. Raises
    RecordValidationError if the record fails the schema — e.g.
    a CANDIDATE verdict without on-target imaging.
    """
    final_verdict, note = aggregate_verdict(stage_results, imaging)
    if verdict_note is None:
        verdict_note = note
    header = _prov.provenance_header(
        run_id if run_id is not None else _prov.new_run_id("gauntlet"),
        CALIBRATION_MAP)
    record = {
        "tic": str(tic),
        "filed": dict(filed),
        "final_verdict": final_verdict,
        "verdict_note": verdict_note,
        "stages": {r.stage: r.to_dict() for r in stage_results},
    }
    # Optional keys are OMITTED when absent, not nulled:
    # ephemeris_used is type object in the schema (not nullable).
    if ephemeris_used is not None:
        record["ephemeris_used"] = dict(ephemeris_used)
    if imaging is not None:
        record["imaging"] = dict(imaging)
    record.update(header)
    if extra:
        record.update({k: v for k, v in extra.items()
                       if v is not None})
    return validate_verdict(record)
