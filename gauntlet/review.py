"""Filing review gate (Phase 2, 2E): the human-gated step
between a CANDIDATE verdict and any filing.

A candidate reaches filing review only when the evidence
package passes the gate:

* the verdict is CANDIDATE;
* every required stage is COMPLETED+PASS, or INCONCLUSIVE /
  NOT_APPLICABLE with an F-5 waiver (code + reason) on the
  verdict — a FAIL, an UNMEASURED stage, an unwaived
  inconclusive stage, or a missing required stage blocks;
* persistence, diffimg and blend all PASS (the data part of
  check_report_ready).

The gate deliberately does NOT require the package's
report_ready flag: a waived CANDIDATE reads report_ready
False until a second-eyes review exists — and THIS review
is that second-eyes marker. An approved review's decision
reviewer satisfies check_report_ready's review_2e
requirement (see review_2e_marker).

prepare_filing_review builds the review record for ANY
package (eligible or not) — the record carries the
eligibility verdict and the blockers, so an ineligible
candidate's gap is visible, not a crash. The gate is
enforced at DECISION time: record_review_decision refuses
to approve an ineligible record. Rejecting is always
allowed. A decided record is final — a new review must be
prepared from a (fresh) evidence package.

The review binds to its evidence package by hash (sha256 of
the canonical package JSON), so a decision cannot be
silently re-attached to different evidence.

REVIEWER INDEPENDENCE (P-6, Phase 2 vote): the reviewer must
not be the operator who prepared the run. prepare_filing_review
takes the operator (required, non-empty — the person or agent
who ran the desk gauntlet, usually Pingu); record_review_decision
refuses to approve when the reviewer IS the operator, when the
reviewer claims a known agent identity (a small denylist tripwire
— see AGENT_IDENTITY_DENYLIST), or when the reviewer has not
attested to examining the evidence
(reviewer_examined_evidence must be True to approve). A
rejection needs none of these — rejecting is the fail-safe
direction and is always allowed.

This is a PROCEDURAL control, not authentication: the code can
check that the reviewer string differs from the operator and is
not a known agent identity, but it cannot verify the human
behind the keyboard. The approval call itself is the human
attestation point — the caller asserts, by calling it with a
human reviewer name and the attestation set, that a second pair
of eyes examined the evidence. The denylist is a tripwire
against the lazy failure (the operator approving its own work
under its own name), not a guarantee.

No filing action is ever taken here — the gate prepares the
review, a human decides.
"""

import copy
import hashlib

import provenance as _prov
import validation as _validation
from gauntlet.stage_result import (
    REQUIRED_STAGES, STATUS_INCONCLUSIVE, STATUS_NOT_APPLICABLE,
    STATUS_PASS,
)

REVIEW_SCHEMA_VERSION = "1.0"

_DATA_STAGES = ("persistence", "diffimg", "blend")

# P-6: reviewer identities that are never a human second pair
# of eyes. A tripwire, not authentication — it catches the
# lazy failure (the operator approving its own work under an
# agent name), not a determined impersonation. Compared
# against the reviewer string normalised (stripped +
# casefolded), exact match only — substring matching would
# false-positive on human names. The operator MAY be an agent
# (Pingu runs the desk gauntlet); the REVIEWER may not.
AGENT_IDENTITY_DENYLIST = frozenset({
    "pingu", "muse", "claude", "gemini", "chatgpt", "gpt",
    "copilot", "bot", "agent", "ai", "assistant", "llm",
})


def _normalize_identity(name):
    """Reviewer/operator comparison form: stripped +
    casefolded, so ' Pingu ' and 'pingu' are the same
    identity."""
    return name.strip().casefold()


def _eligibility(package):
    """The filing gate, evaluated on one evidence package.

    Returns (eligible, eligibility-dict). The blockers list
    names every failing condition — empty when eligible.
    """
    verdict = package.get("verdict") or {}
    stages = package.get("stages") or {}
    blockers = []
    verdict_ok = verdict.get("final_verdict") == "CANDIDATE"
    if not verdict_ok:
        blockers.append(
            f"verdict is {verdict.get('final_verdict')}, "
            f"not CANDIDATE")
    all_ok = True
    for stage in REQUIRED_STAGES:
        result = stages.get(stage)
        if result is None:
            blockers.append(f"{stage} never ran")
            all_ok = False
            continue
        status = result.get("status")
        if status == STATUS_PASS:
            continue
        if status in (STATUS_INCONCLUSIVE,
                      STATUS_NOT_APPLICABLE) and \
                result.get("waiver_reason"):
            continue
        all_ok = False
        if status in (STATUS_INCONCLUSIVE,
                      STATUS_NOT_APPLICABLE):
            blockers.append(
                f"{stage} is {status} without a waiver")
        else:
            blockers.append(f"{stage} is {status}")
    data_ok = True
    for stage in _DATA_STAGES:
        result = stages.get(stage)
        if result is None or result.get("status") != STATUS_PASS:
            data_ok = False
            # The missing/failed stage is already a blocker
            # above; do not double-report it.
            break
    # P-7: the review binds to evidence whose bytes were
    # actually hashed. Every source file (verdict_record,
    # desk_natives) must hash non-null, and every artifact
    # the record cites (LATTE PDF, TRICERATOPS CSV) must
    # appear in inputs.tool_artifacts with a non-null hash
    # — a cited artifact whose file is gone, or a package
    # built before P-7 that never hashed its artifacts,
    # blocks approval. The builder never raises for a
    # missing file; THIS gate is where a null hash blocks.
    inputs = package.get("inputs") or {}
    missing_hashes = []
    for key in ("verdict_record", "desk_natives"):
        if (inputs.get(key) or {}).get("sha256") is None:
            missing_hashes.append(f"inputs.{key}")
    hashed = {e.get("path")
              for e in (inputs.get("tool_artifacts") or [])
              if e.get("sha256")}
    for _tool, result in \
            (package.get("external_tools") or {}).items():
        for path in (result or {}).get("artifacts") or []:
            if path not in hashed:
                missing_hashes.append(path)
    source_hashes_present = not missing_hashes
    if missing_hashes:
        blockers.append(
            "source hash missing for: "
            + ", ".join(sorted(set(missing_hashes))))
    return (verdict_ok and all_ok and data_ok
            and source_hashes_present, {
        "verdict_is_candidate": verdict_ok,
        "all_stages_pass_or_waived": all_ok,
        "persistence_diffimg_blend_pass": data_ok,
        "source_hashes_present": source_hashes_present,
        "waivers": list(verdict.get("waivers") or []),
        "blockers": blockers,
    })


def _checklist(package):
    """The human checklist, derived from the package.

    Items a machine cannot close: the LATTE report must be
    READ (it is plots + a PDF, never a machine disposition),
    the TRICERATOPS numbers must be judged against the rest
    of the evidence, waived stages must be consciously
    accepted, and the catalogue census is point-in-time. An
    item with no backing evidence in the package reads
    not_applicable with the reason in its detail — never a
    silently skipped step.
    """
    scores = package.get("scores") or {}
    verdict = package.get("verdict") or {}
    tools = package.get("external_tools") or {}
    items = []
    latte = scores.get("latte")
    if latte is not None:
        items.append({
            "item": "read_latte_report",
            "description": "Read the LATTE diagnostic report "
                           "(plots + PDF) and confirm no check "
                           "contradicts the candidate.",
            "status": "pending",
            "detail": f"report: {latte.get('report_pdf')}",
        })
    else:
        items.append({
            "item": "read_latte_report",
            "description": "Read the LATTE diagnostic report "
                           "(plots + PDF) and confirm no check "
                           "contradicts the candidate.",
            "status": "not_applicable",
            "detail": "no LATTE report in the package",
        })
    tri = scores.get("triceratops")
    if tri is not None and tri.get("fpp") is not None:
        # BP-3 (PIPE50-2, bulk_v6 step 6): the item carries
        # the seed-band summary — headline (the MAX seed),
        # median, band, per-seed values, N. A score that
        # predates BP-3 reads as the single-seed summary it
        # is (n_seeds 1 + PROVISIONAL_TRIAGE).
        fpp = tri.get("fpp")
        n_seeds = tri.get("n_seeds", 1)
        median = tri.get("fpp_median", fpp)
        band = tri.get("fpp_band") or [fpp, fpp]
        detail = (f"headline FPP {fpp} (max of {n_seeds} "
                  f"seed{'s' if n_seeds != 1 else ''}; median "
                  f"{median}, band [{band[0]}, {band[1]}]), "
                  f"NFPP {tri.get('nfpp')}, most likely "
                  f"false positive: "
                  f"{tri.get('most_likely_false_positive')}")
        if n_seeds == 1:
            detail += (" — PROVISIONAL_TRIAGE: a single seed "
                       "is not a validation measurement")
        items.append({
            "item": "confirm_triceratops",
            "description": "Confirm the TRICERATOPS false-"
                           "positive probability supports the "
                           "candidate against the rest of the "
                           "evidence.",
            "status": "pending",
            "detail": detail,
            "fpp_median": median,
            "fpp_band": band,
            "per_seed": tri.get("per_seed") or [],
            "n_seeds": n_seeds,
            "headline": fpp,
        })
    else:
        items.append({
            "item": "confirm_triceratops",
            "description": "Confirm the TRICERATOPS false-"
                           "positive probability supports the "
                           "candidate against the rest of the "
                           "evidence.",
            "status": "not_applicable",
            "detail": ("no TRICERATOPS score in the package"
                       if "triceratops" not in tools else
                       "TRICERATOPS ran but produced no FPP"),
        })
    waivers = verdict.get("waivers") or []
    if waivers:
        stages = ", ".join(sorted(
            w.get("stage", "?") for w in waivers))
        items.append({
            "item": "review_waivers",
            "description": "Consciously accept the waived "
                           "stage(s): the waiver reason must "
                           "cover this target.",
            "status": "pending",
            "detail": f"waived stage(s): {stages}",
        })
    else:
        items.append({
            "item": "review_waivers",
            "description": "Consciously accept the waived "
                           "stage(s): the waiver reason must "
                           "cover this target.",
            "status": "not_applicable",
            "detail": "no waivers on this candidate",
        })
    items.append({
        "item": "confirm_catalogue_current",
        "description": "Confirm no new catalogue entry (TOI / "
                       "VSX / Planet Hunters) has appeared "
                       "since the stage-0 census was taken.",
        "status": "pending",
        "detail": "the census is point-in-time",
    })
    return items


def prepare_filing_review(package, operator,
                          timestamp_utc=None):
    """Prepare the filing review record for one evidence
    package.

    The package is validated against the evidence schema
    first — a malformed package fails loud, never a review
    of unknown evidence. `operator` is the person or agent
    who prepared the run (required, non-empty — usually
    Pingu, who ran the desk gauntlet); it is recorded on
    the review so the decision step can enforce
    reviewer-independence (P-6). The record is returned in
    status awaiting_review with the eligibility verdict,
    the blockers (when ineligible), and the human
    checklist. Preparing a review is never itself a
    decision.
    """
    if not (isinstance(operator, str) and operator.strip()):
        raise ValueError("operator must be a non-empty string")
    _validation.validate_evidence_package(package)
    eligible, eligibility = _eligibility(package)
    package_hash = hashlib.sha256(
        _prov.canonical_json(package).encode("utf-8")
    ).hexdigest()
    record = {
        "record_type": "filing_review",
        "schema_version": REVIEW_SCHEMA_VERSION,
        "tic": package["tic"],
        "run_id": package["run_id"],
        "operator": operator,
        "evidence_package_hash": package_hash,
        "timestamp_utc": (timestamp_utc if timestamp_utc is not None
                          else _prov.utc_now_iso()),
        "status": "awaiting_review",
        "eligible": eligible,
        "eligibility": eligibility,
        "checklist": _checklist(package),
        "decision": None,
    }
    return _validation.validate_filing_review(record)


def record_review_decision(review, reviewer, decision, reason,
                           timestamp_utc=None,
                           reviewer_examined_evidence=False):
    """Record a human's decision on a filing review.

    reviewer: non-empty string (the human deciding — an
    approved review's reviewer is the F-5 second-eyes
    marker). decision: "approved" or "rejected". reason:
    non-empty string (why — an approval without a reason is
    not a review). reviewer_examined_evidence: the
    reviewer's attestation that they examined the evidence
    (the LATTE report, the TRICERATOPS numbers, the waived
    stages) — must be True to approve.

    Raises ValueError when the inputs are invalid, when the
    review was already decided, when approving an
    ineligible record (the blockers are named in the
    error), when the reviewer IS the operator who prepared
    the run (P-6 — a second pair of eyes must be second),
    when the reviewer claims a known agent identity, or
    when approving without the evidence attestation.
    Rejecting is always allowed. Returns a NEW record dict;
    the input is not mutated.
    """
    if not (isinstance(reviewer, str) and reviewer.strip()):
        raise ValueError("reviewer must be a non-empty string")
    if decision not in ("approved", "rejected"):
        raise ValueError(
            f"decision must be 'approved' or 'rejected', "
            f"got {decision!r}")
    if not (isinstance(reason, str) and reason.strip()):
        raise ValueError("reason must be a non-empty string")
    if review.get("status") != "awaiting_review":
        raise ValueError(
            f"review already decided: status is "
            f"{review.get('status')!r} — prepare a fresh "
            f"review from a (fresh) evidence package")
    if decision == "approved" and not review.get("eligible"):
        blockers = (review.get("eligibility") or {}).get(
            "blockers") or []
        raise ValueError(
            "cannot approve an ineligible review: "
            + "; ".join(blockers))
    if decision == "approved":
        # P-6 independence: the reviewer must be a different
        # human from the operator, and must attest to having
        # examined the evidence. The operator check needs an
        # operator on the record — a review prepared before
        # P-6 names none, and cannot be approved (prepare a
        # fresh review instead).
        operator = review.get("operator")
        if not (isinstance(operator, str) and operator.strip()):
            raise ValueError(
                "cannot approve a review that names no "
                "operator — prepare a fresh review from a "
                "(fresh) evidence package")
        if _normalize_identity(reviewer) == \
                _normalize_identity(operator):
            raise ValueError(
                "cannot approve: the reviewer is the operator "
                "who prepared this run — a second pair of "
                "eyes must be second")
        if _normalize_identity(reviewer) in \
                AGENT_IDENTITY_DENYLIST:
            raise ValueError(
                "cannot approve: the reviewer claims an agent "
                "identity — a filing review must be decided "
                "by a human")
        if reviewer_examined_evidence is not True:
            raise ValueError(
                "cannot approve without the reviewer's "
                "attestation that they examined the evidence "
                "(reviewer_examined_evidence=True)")
    decided = copy.deepcopy(review)
    decided["status"] = decision
    decided["decision"] = {
        "reviewer": reviewer,
        "decision": decision,
        "reason": reason,
        "reviewer_examined_evidence": bool(
            reviewer_examined_evidence),
        "timestamp_utc": (timestamp_utc if timestamp_utc is not None
                          else _prov.utc_now_iso()),
    }
    return _validation.validate_filing_review(decided)


def review_2e_marker(review):
    """The F-5 second-eyes marker for an approved review.

    Returns {"reviewer": <approver>} when the review is
    approved, else None. Pass it as review_2e to
    check_report_ready: a waived CANDIDATE reads
    report_ready only with a review marker, and the approved
    review IS that marker.
    """
    if review.get("status") != "approved":
        return None
    decision = review.get("decision") or {}
    reviewer = decision.get("reviewer")
    if not (isinstance(reviewer, str) and reviewer.strip()):
        return None
    return {"reviewer": reviewer}
