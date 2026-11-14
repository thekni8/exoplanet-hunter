"""Evidence package (Phase 2, 2D): the single reviewable
record for one gauntlet run.

The verdict record carries the stages and the provenance,
but it has no slot for the external-tool evidence (LATTE /
TRICERATOPS — judgment call 6, PHASE_2_PROGRESS.md) and no
completeness checklist. The evidence package bundles all of
it:

* the verdict — final verdict, note, filed/used ephemeris,
  imaging, waivers;
* the stage results — waiver-stamped, copied from the
  verdict record (the authoritative form, not the runner's
  unstamped results);
* the external-tool StageResults (evidence only, never
  promotion inputs);
* a scores summary — FPP/NFPP + most-likely false positive
  for TRICERATOPS, the report path for LATTE;
* provenance — schema 1.2 fields, the calibration map +
  content hash, and the code fingerprint;
* the hashes of the two source files
  (verdict_record.json, desk_natives.json) — a missing file
  hashes to null and is visible, never silently skipped;
* a completeness checklist — per-status counts, required
  stages that never ran, and the check_report_ready filing
  precondition (persistence + diffimg + blend pass; a
  waived candidate needs a second-eyes review marker).

Built by build_evidence_package, validated against
schema/evidence-schema.json before it is returned. The desk
driver writes it as evidence_package.json next to
verdict_record.json and desk_natives.json. 2E consumes it
for the filing review.
"""

import hashlib
from pathlib import Path

import provenance as _prov
import validation as _validation
from gauntlet.runner import check_report_ready
from gauntlet.stage_result import (
    REQUIRED_STAGES, STATUS_FAIL, STATUS_INCONCLUSIVE,
    STATUS_NOT_APPLICABLE, STATUS_PASS, STATUS_UNMEASURED,
    StageResult,
)

EVIDENCE_SCHEMA_VERSION = "1.0"


def _file_sha256(path):
    """sha256 of a file, or None when it cannot be read."""
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return None


def _scores(extra_evidence):
    """The scores summary from the external-tool results.

    TRICERATOPS: FPP/NFPP/planet probability/most-likely FP
    from the StageResult's value + metrics. LATTE: the report
    PDF path (details, falling back to the first artifact).
    A tool that never ran scores null — never a fabricated
    number.
    """
    tools = (extra_evidence or {}).get("external_tools") or {}
    scores = {"triceratops": None, "latte": None}
    tri = tools.get("triceratops")
    if tri:
        metrics = tri.get("metrics") or {}
        scores["triceratops"] = {
            "fpp": tri.get("value"),
            "nfpp": metrics.get("nfpp"),
            "prob_planet": metrics.get("prob_planet"),
            "most_likely_false_positive": metrics.get(
                "most_likely_false_positive"),
            "status": tri.get("status"),
            "tool_version": tri.get("tool_version"),
        }
    lat = tools.get("latte")
    if lat:
        details = lat.get("details") or {}
        artifacts = lat.get("artifacts") or []
        scores["latte"] = {
            "report_pdf": (details.get("report_pdf")
                           or (artifacts[0] if artifacts else None)),
            "status": lat.get("status"),
            "tool_version": lat.get("tool_version"),
        }
    return scores


def build_evidence_package(tic, verdict, extra_evidence, workdir):
    """Build + validate the evidence package for one candidate.

    tic: TIC id (string). verdict: the build_verdict record —
    the source of the final verdict, the header provenance,
    the filed/used ephemeris, imaging, and waivers, and of
    the stage results (waiver-stamped). extra_evidence: the
    desk extra dict — external_tools live here. workdir: the
    run workdir; verdict_record.json and desk_natives.json
    are hashed when present.

    Returns the validated package dict. Raises
    RecordValidationError if the package fails the schema —
    e.g. a verdict record missing its provenance fields.
    """
    stages = dict(verdict.get("stages") or {})
    results = [StageResult.from_dict(d) for d in stages.values()]
    counts = {}
    for result in results:
        counts[result.status] = counts.get(result.status, 0) + 1
    missing = sorted(set(REQUIRED_STAGES) - set(stages))
    ready, ready_reason = check_report_ready(results)
    try:
        code_fingerprint = _prov.fingerprint_result_affecting()
    except Exception:
        code_fingerprint = None
    workdir = Path(workdir)
    package = {
        "record_type": "evidence_package",
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "tic": str(tic),
        "run_id": verdict.get("run_id"),
        "timestamp_utc": verdict.get("timestamp_utc"),
        "verdict": {
            "final_verdict": verdict.get("final_verdict"),
            "verdict_note": verdict.get("verdict_note"),
            "filed": dict(verdict.get("filed") or {}),
            "ephemeris_used": verdict.get("ephemeris_used"),
            "imaging": verdict.get("imaging"),
            "waivers": list(verdict.get("waivers") or []),
            "waivers_hash": verdict.get("waivers_hash"),
        },
        "stages": stages,
        "external_tools": dict(
            (extra_evidence or {}).get("external_tools") or {}),
        "scores": _scores(extra_evidence),
        "provenance": {
            "schema_version": verdict.get("schema_version"),
            "pipeline_git_sha": verdict.get("pipeline_git_sha"),
            "working_tree_clean": verdict.get("working_tree_clean"),
            "calibration_version": dict(
                verdict.get("calibration_version") or {}),
            "calibration_sha256": verdict.get("calibration_sha256"),
            "code_fingerprint": code_fingerprint,
        },
        "inputs": {
            "verdict_record": {
                "path": "verdict_record.json",
                "sha256": _file_sha256(
                    workdir / "verdict_record.json")},
            "desk_natives": {
                "path": "desk_natives.json",
                "sha256": _file_sha256(
                    workdir / "desk_natives.json")},
        },
        "completeness": {
            "n_stages": len(results),
            "n_pass": counts.get(STATUS_PASS, 0),
            "n_fail": counts.get(STATUS_FAIL, 0),
            "n_unmeasured": counts.get(STATUS_UNMEASURED, 0),
            "n_inconclusive": counts.get(STATUS_INCONCLUSIVE, 0),
            "n_not_applicable": counts.get(
                STATUS_NOT_APPLICABLE, 0),
            "missing_required": missing,
            "report_ready": ready,
            "report_ready_reason": ready_reason,
        },
    }
    return _validation.validate_evidence_package(package)
