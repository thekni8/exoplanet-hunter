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
listed stage at status "pass", "not_applicable" or "inconclusive"
(the schema cannot cross-reference the waivers list, so the
waiver rule itself — an inconclusive/not_applicable stage needs
a policy waiver with a reason — is enforced in code by
aggregate_verdict). build_verdict enforces the rest in code via
aggregate_verdict: any FAIL kills, any UNMEASURED / unwaived
INCONCLUSIVE or NOT_APPLICABLE / never-run required stage means
INCONCLUSIVE, and a candidate needs on-target imaging.
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
    from gauntlet.stage_result import (  # noqa: E402
        apply_waivers as _apply_waivers)
    from gauntlet.stage_result import (  # noqa: E402
        normalize_waivers as _norm_waivers)
except ImportError:  # run as a plain script from the gauntlet dir
    from stage_result import aggregate_verdict  # noqa: E402
    from stage_result import apply_waivers as _apply_waivers  # noqa: E402
    from stage_result import normalize_waivers as _norm_waivers  # noqa: E402

CALIBRATION_VERSION = "gauntlet_v2"
# Provenance map (A-2): per-subsystem bare versions. A-4 moved
# the decision policy to gauntlet_v2.
CALIBRATION_MAP = {"gauntlet": "v2"}


def build_verdict(tic, filed, stage_results, imaging=None,
                  ephemeris_used=None, verdict_note=None,
                  run_id=None, extra=None, waivers=None,
                  policy=None):
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
    with existing verdict readers. waivers: {stage: reason} (or
    a list of {"stage", "reason"}) — INCONCLUSIVE or
    NOT_APPLICABLE stages the decision policy waives for this
    target; validated against the policy by aggregate_verdict
    and recorded on the verdict. policy: the decision-policy
    dict (default: gauntlet_v2).

    Returns the validated record dict. Raises
    RecordValidationError if the record fails the schema — e.g.
    a CANDIDATE verdict without on-target imaging — and
    ValueError if a waiver is invalid.
    """
    final_verdict, note = aggregate_verdict(stage_results, imaging,
                                            waivers=waivers,
                                            policy=policy)
    if verdict_note is None:
        verdict_note = note
    # F-5: stamp the waiver reasons onto the results, so the
    # record's stages carry the full waiver story (code +
    # reason) — and record the waiver code + the waivers hash
    # on the verdict itself.
    stamped = _apply_waivers(stage_results, waivers, policy)
    by_stage = {r.stage: r for r in stamped}
    header = _prov.provenance_header(
        run_id if run_id is not None else _prov.new_run_id("gauntlet"),
        CALIBRATION_MAP)
    record = {
        "tic": str(tic),
        "filed": dict(filed),
        "final_verdict": final_verdict,
        "verdict_note": verdict_note,
        "stages": {r.stage: r.to_dict() for r in stamped},
    }
    # Optional keys are OMITTED when absent, not nulled:
    # ephemeris_used is type object in the schema (not nullable).
    if ephemeris_used is not None:
        record["ephemeris_used"] = dict(ephemeris_used)
    if imaging is not None:
        record["imaging"] = dict(imaging)
    if waivers:
        norm = _norm_waivers(waivers)
        record["waivers"] = [
            {"stage": s, "reason": r,
             **({"code": by_stage[s].waiver_code}
                if by_stage[s].waiver_code else {})}
            for s, r in sorted(norm.items())]
        record["waivers_hash"] = _prov.waivers_hash(norm)
    record.update(header)
    if extra:
        record.update({k: v for k, v in extra.items()
                       if v is not None})
    return validate_verdict(record)
