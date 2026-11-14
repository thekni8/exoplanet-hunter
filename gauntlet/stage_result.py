"""Typed gauntlet stage results (Phase 1.1, item 7; contract v1 in
Phase 1.2).

Every gauntlet stage returns a StageResult — a typed record with
(status, reason, provenance) — instead of a bare string, a dict
with a different shape per stage, or (worst) nothing at all when
a stage could not measure. The contract:

  * status is one of pass / fail / unmeasured / inconclusive /
    not_applicable.
  * "unmeasured" means NOT YET VETTED — the stage had too little
    data to judge. It is NEVER a pass: no aggregation may treat
    it as one, and no CANDIDATE verdict may stand on it. It is
    NEVER waivable.
  * "inconclusive" means the stage measured but could not decide
    (e.g. an ambiguous trapezoid shape). Also never a pass. It
    blocks candidacy unless the decision policy waives that
    stage explicitly (per-stage, in the policy, with a reason —
    see aggregate_verdict).
  * "not_applicable" means the stage does not apply to this
    target (e.g. a holdout test on a single-sector candidate).
    It BLOCKS candidacy unless the decision policy waives that
    stage explicitly — a stage that does not apply is a gap in
    the case until the policy says the gap is structural and the
    run records the waiver with its reason. (v1 let it pass
    silently; v2 reverses that.)
  * Promotion is an ALLOWLIST: only COMPLETED + PASS passes. A
    FAIL kills, an UNMEASURED blocks, an INCONCLUSIVE or
    NOT_APPLICABLE blocks unless waived — and the waiver must
    name the stage and carry a reason, and the stage must be in
    the policy's waiver allowlist.
  * A result carries EVIDENCE, not just a verdict: value,
    uncertainty, threshold, detection limit, transits used,
    metrics, artifacts, tool version, config hash, input
    hashes. A bare "pass" hides whether the test could have
    rejected anything at all (an odd/even test on three
    transits at SNR 8 cannot); the evidence is what makes the
    verdict auditable. The raw result and its interpretation
    stay separate: the interpretation thresholds live in the
    versioned gauntlet calibration profile (the decision
    policy, gauntlet_v2), not in the result.
  * Scientific outcome and execution outcome are separate axes:
    execution_status is completed / not_started / skipped /
    error. A crashed external tool is NOT a scientific failure
    of the candidate — it is an unmeasured stage with an error
    execution status, and the type enforces that (see
    __post_init__).
  * Every result carries provenance (calibration_version,
    pipeline_git_sha, run_id, timestamp_utc) so a verdict can
    always be traced to the code and calibration that produced it.
  * Every result carries a record_type discriminator
    ("stage_result") alongside schema_version, so a standalone
    stage-result record is self-describing (schema/
    stage_result-schema.json).

Adapters map each existing stage's native output onto this type
without changing the stage itself: the catalogue check, the
clean-data re-fold gate, the period refinement, the raw-flux
fold, the odd/even check, the persistence stamp, the holdout
test, the difference imaging, the pixel check, and the formal
transit fit. (The blend verdict itself is a pure function in
gauntlet/blend.py — check_blend — and blend_result here is only
its adapter.)
`aggregate_verdict` turns a set of stage results (+ imaging)
into a final verdict; `gauntlet/verdict.py:build_verdict`
assembles and validates the verdict record.
"""
from dataclasses import dataclass, field
from functools import lru_cache

import provenance as _provenance

STATUS_PASS = "pass"
STATUS_FAIL = "fail"
STATUS_UNMEASURED = "unmeasured"
STATUS_INCONCLUSIVE = "inconclusive"
STATUS_NOT_APPLICABLE = "not_applicable"
STATUSES = (STATUS_PASS, STATUS_FAIL, STATUS_UNMEASURED,
            STATUS_INCONCLUSIVE, STATUS_NOT_APPLICABLE)

# Execution outcome — separate from the scientific outcome. A stage
# that crashed did not fail scientifically; a stage that never ran
# did not measure anything. (ChatGPT/Claude, Phase 1.1 vote.)
EXEC_COMPLETED = "completed"
EXEC_NOT_STARTED = "not_started"
EXEC_SKIPPED = "skipped"
EXEC_ERROR = "error"
EXEC_STATUSES = (EXEC_COMPLETED, EXEC_NOT_STARTED, EXEC_SKIPPED,
                 EXEC_ERROR)

# Decision policy (Phase 1.2, item A-4): the interpretation
# thresholds live in the versioned gauntlet calibration profile
# (gauntlet_v2), NOT in code. A threshold change is a calibration
# change — version bump + registry entry. The adapters take an
# explicit `policy` dict (tests pass one); when omitted they load
# the default policy, cached (the profile never changes mid-run).
DEFAULT_POLICY_VERSION = "gauntlet_v2"
RECORD_TYPE = "stage_result"


@lru_cache(maxsize=4)
def load_decision_policy(version=DEFAULT_POLICY_VERSION):
    """The decision-policy dict for a gauntlet calibration
    version (default gauntlet_v2). Cached; call
    load_decision_policy.cache_clear() after changing the
    calibration dir in tests."""
    from calibration import load_profile
    return load_profile(version)


def _policy_value(policy, key, version=DEFAULT_POLICY_VERSION):
    """One threshold from an explicit policy dict, or the
    default policy when none is passed."""
    if policy is None:
        policy = load_decision_policy(version)
    return policy[key]

# Stages every candidate must pass (vetting-manual order — the
# A-5 DAG). A stage that never ran is unmeasured —
# aggregate_verdict treats a missing required stage exactly like
# an UNMEASURED result. `raw_flux` is NOT in the brief's DAG
# table, but it stays a required stage: the S97 344334378
# refutation rests on the standalone raw-flux dip test (a hard
# REFUTED, where the shape gate would only say unmeasured), the
# table's persistence RAW verdict is a different (per-sector)
# test, and the brief never orders raw_flux's removal. The vote
# may order it dropped; until then it runs.
REQUIRED_STAGES = ("catalogue", "clean_refold", "refine",
                   "raw_flux", "persistence", "shape", "odd_even",
                   "holdout", "diffimg", "blend", "pixel_check",
                   "transit_fit")

# What a FAIL at each stage means for the final verdict.
_FAIL_VERDICT = {
    "catalogue": "REFUTED",
    "clean_refold": "REFUTED",
    "raw_flux": "REFUTED",
    "shape": "EB",
    "odd_even": "EB",
    "persistence": "REFUTED",
    "holdout": "REFUTED",
    "diffimg": "BLEND",
    "blend": "BLEND",
    "pixel_check": "REFUTED",
    "transit_fit": "EB",
}


@dataclass(frozen=True)
class StageResult:
    """One gauntlet stage's typed result (contract v1).

    `details` carries the measurements behind the verdict
    (depths, significances, ratios) — JSON-able, for the record.
    The evidence fields carry the same story in a fixed shape
    so a consumer never has to guess where the number lives:
    `value` is the measured quantity, `uncertainty` its 1-sigma
    error in the same units, `threshold` the pass bar in the
    same units (None when the stage is a classification, not a
    thresholded measurement), `detection_limit` the faintest
    signal this stage could have seen, `n_transits` the
    transits the verdict rests on. `metrics` holds the
    stage-specific numbers that do not fit the fixed fields
    (e.g. TRICERATOPS FPP/NFPP — preserved, never reduced to a
    bare PASS/FAIL), `artifacts` the paths/ids of evidence
    files, `tool_version` / `config_hash` / `input_hashes` the
    reproducibility of the measurement itself.
    """
    stage: str
    status: str
    reason: str
    provenance: dict = field(default_factory=dict)
    details: dict = field(default_factory=dict)
    # --- evidence (contract v1) ---
    value: float | None = None
    uncertainty: float | None = None
    threshold: float | None = None
    detection_limit: float | None = None
    n_transits: int | None = None
    metrics: dict = field(default_factory=dict)
    artifacts: list = field(default_factory=list)
    tool_version: str | None = None
    config_hash: str | None = None
    input_hashes: dict = field(default_factory=dict)
    warnings: list = field(default_factory=list)
    execution_status: str = EXEC_COMPLETED

    def __post_init__(self):
        if self.status not in STATUSES:
            raise ValueError(
                f"invalid stage status {self.status!r} for stage "
                f"{self.stage!r}: must be one of {STATUSES}")
        if self.execution_status not in EXEC_STATUSES:
            raise ValueError(
                f"invalid execution status "
                f"{self.execution_status!r} for stage "
                f"{self.stage!r}: must be one of {EXEC_STATUSES}")
        # Execution and science must agree: a stage that errored
        # or never started cannot claim a scientific outcome — it
        # is unmeasured, not failed and not passed. A skipped
        # stage is unmeasured, unless the runner skipped it
        # because it does not apply (not_applicable).
        if self.execution_status in (EXEC_ERROR, EXEC_NOT_STARTED) \
                and self.status != STATUS_UNMEASURED:
            raise ValueError(
                f"stage {self.stage!r} with execution "
                f"{self.execution_status!r} must have status "
                f"'unmeasured', not {self.status!r}")
        if self.execution_status == EXEC_SKIPPED and self.status \
                not in (STATUS_UNMEASURED, STATUS_NOT_APPLICABLE):
            raise ValueError(
                f"stage {self.stage!r} with execution 'skipped' "
                f"must have status 'unmeasured' or "
                f"'not_applicable', not {self.status!r}")

    @property
    def is_pass(self):
        """Only an explicit pass counts. Unmeasured and
        inconclusive are NEVER a pass — this is the property the
        whole contract hangs on."""
        return self.status == STATUS_PASS

    @property
    def is_measured(self):
        return self.status not in (STATUS_UNMEASURED,
                                   STATUS_NOT_APPLICABLE)

    def to_dict(self):
        d = {"record_type": RECORD_TYPE,
             "schema_version": _provenance.SCHEMA_VERSION,
             "stage": self.stage, "status": self.status,
             "reason": self.reason,
             "execution_status": self.execution_status,
             "provenance": dict(self.provenance),
             "details": dict(self.details),
             "metrics": dict(self.metrics),
             "artifacts": list(self.artifacts),
             "input_hashes": dict(self.input_hashes),
             "warnings": list(self.warnings)}
        for k in ("value", "uncertainty", "threshold",
                  "detection_limit", "n_transits", "tool_version",
                  "config_hash"):
            v = getattr(self, k)
            if v is not None:
                d[k] = v
        return d

    @classmethod
    def from_dict(cls, d):
        # Old dicts (pre-v1, no evidence fields) still load: every
        # new field has a default, so a Phase 1.1 record is a valid
        # v1 record with empty evidence.
        return cls(stage=d["stage"], status=d["status"],
                   reason=d["reason"],
                   provenance=dict(d.get("provenance") or {}),
                   details=dict(d.get("details") or {}),
                   value=d.get("value"),
                   uncertainty=d.get("uncertainty"),
                   threshold=d.get("threshold"),
                   detection_limit=d.get("detection_limit"),
                   n_transits=d.get("n_transits"),
                   metrics=dict(d.get("metrics") or {}),
                   artifacts=list(d.get("artifacts") or []),
                   tool_version=d.get("tool_version"),
                   config_hash=d.get("config_hash"),
                   input_hashes=dict(d.get("input_hashes") or {}),
                   warnings=list(d.get("warnings") or []),
                   execution_status=d.get("execution_status",
                                          EXEC_COMPLETED))


def _prov(prov):
    """Normalise the provenance argument: adapters accept the
    provenance.header() dict or None (tests pass explicit dicts)."""
    return dict(prov) if prov else {}


# ---------------------------------------------------------------------------
# Adapters: native stage output -> StageResult
# ---------------------------------------------------------------------------

def shape_result(gate, prov=None):
    """trapezoid_shape_gate output -> StageResult.

    V-shaped or density-flagged -> FAIL (EB suspect). U-shaped
    with no density flag -> PASS. Ambiguous -> INCONCLUSIVE (the
    shape was measured but does not decide). Unmeasured (too few
    bins, no dip) -> UNMEASURED.
    """
    shape = gate.get("shape_verdict")
    details = {k: gate.get(k) for k in
               ("T23_T14", "T14_h", "density_flag", "depth_frac")
               if gate.get(k) is not None}
    if gate.get("verdict") == "unmeasured" or shape == "unmeasured":
        return StageResult(
            "shape", STATUS_UNMEASURED,
            gate.get("reason") or "shape gate unmeasured",
            _prov(prov), details)
    if gate.get("density_flag"):
        return StageResult(
            "shape", STATUS_FAIL,
            gate.get("density_reason")
            or "density flag: fitted duration impossible for a "
               "planet on this star",
            _prov(prov), details)
    if shape == "V-shaped":
        return StageResult(
            "shape", STATUS_FAIL,
            f"V-shaped transit (T23/T14={gate.get('T23_T14'):.2f})"
            if gate.get("T23_T14") is not None else "V-shaped",
            _prov(prov), details)
    if shape == "U-shaped":
        return StageResult(
            "shape", STATUS_PASS,
            "U-shaped transit, no density flag",
            _prov(prov), details)
    return StageResult(
        "shape", STATUS_INCONCLUSIVE,
        f"ambiguous trapezoid shape "
        f"(T23/T14={gate.get('T23_T14'):.2f})"
        if gate.get("T23_T14") is not None else "ambiguous shape",
        _prov(prov), details)


def clean_refold_result(fold, verdict, prov=None):
    """clean_refold_gate verdict_for output -> StageResult.

    FAIL -> FAIL (signal lives only in flagged cadences).
    PASS -> PASS. INSUFFICIENT -> UNMEASURED (too few clean
    in-transit cadences to test — not yet vetted).

    Evidence: value is the clean-fold depth (%), uncertainty
    its 1-sigma error from the fold SNR, threshold the 3-sigma
    bar in the same units.
    """
    details = {k: fold.get(k) for k in
               ("n_in", "n_events", "depth_percent", "snr")
               if fold.get(k) is not None}
    depth = fold.get("depth_percent")
    snr = fold.get("snr")
    unc = (abs(depth) / snr) if (depth is not None
                                and snr is not None and snr > 0) \
        else None
    ev = {"value": depth, "uncertainty": unc,
          "threshold": (3.0 * unc) if unc is not None else None,
          "n_transits": fold.get("n_events")}
    if verdict == "FAIL":
        return StageResult(
            "clean_refold", STATUS_FAIL,
            "no dip in clean (quality==0) flux at the filed "
            "ephemeris — signal lives only in flagged cadences",
            _prov(prov), details, **ev)
    if verdict == "PASS":
        return StageResult(
            "clean_refold", STATUS_PASS,
            "dip persists in clean flux", _prov(prov), details,
            **ev)
    return StageResult(
        "clean_refold", STATUS_UNMEASURED,
        "insufficient clean in-transit cadences to test",
        _prov(prov), details, **ev)


def raw_flux_result(fold, prov=None, policy=None):
    """A raw-flux fold_depth dict -> StageResult.

    Depth > 0 at >= the policy's raw_flux_min_signif sigma in
    unflattened flux -> PASS. No dip or insignificant -> FAIL
    (RAW-REFUTED). Too few in-transit cadences/events (policy
    min_in_cadences / min_events) -> UNMEASURED.

    Evidence: value is the fold depth (%), uncertainty its
    1-sigma error from the white significance, threshold the
    policy's sigma bar in the same units.
    """
    min_signif = _policy_value(policy, "raw_flux_min_signif")
    min_in = _policy_value(policy, "min_in_cadences")
    min_events = _policy_value(policy, "min_events")
    details = {k: fold.get(k) for k in
               ("depth_pct", "signif_white", "signif_red",
                "n_in", "n_events")
               if fold.get(k) is not None}
    depth = fold.get("depth_pct")
    signif = fold.get("signif_white")
    unc = (depth / signif) if (depth is not None
                               and signif is not None
                               and signif > 0 and depth > 0) \
        else None
    ev = {"value": depth, "uncertainty": unc,
          "threshold": (min_signif * unc)
          if unc is not None else None,
          "n_transits": fold.get("n_events")}
    if (fold.get("n_in") or 0) < min_in or \
            (fold.get("n_events") or 0) < min_events:
        return StageResult(
            "raw_flux", STATUS_UNMEASURED,
            "too few in-transit cadences/events for a raw-flux "
            "verdict", _prov(prov), details, **ev)
    if depth is not None and signif is not None \
            and depth > 0 and signif >= min_signif:
        return StageResult(
            "raw_flux", STATUS_PASS,
            f"dip in raw flux: {depth:.3f}% "
            f"({signif:.1f} sigma white)",
            _prov(prov), details, **ev)
    return StageResult(
        "raw_flux", STATUS_FAIL,
        "no significant dip in raw flux at the ephemeris",
        _prov(prov), details, **ev)


def odd_even_result(odd, even, prov=None, policy=None):
    """event_parity_depths output -> StageResult.

    Either family unmeasured (None) -> UNMEASURED. Families
    differing by more than the policy's parity_fail_sigma
    combined sigma -> FAIL (EB at twice the period). Agreeing
    families -> PASS.
    """
    fail_sigma = _policy_value(policy, "parity_fail_sigma")
    if odd is None or even is None:
        return StageResult(
            "odd_even", STATUS_UNMEASURED,
            "odd/even families not both measurable",
            _prov(prov), {})
    import math
    diff = abs(odd["depth_pct"] - even["depth_pct"])
    sig = math.sqrt(odd["sig_white_pct"] ** 2
                    + even["sig_white_pct"] ** 2)
    details = {"odd_depth_pct": odd["depth_pct"],
               "even_depth_pct": even["depth_pct"],
               "diff_sigma": diff / sig if sig > 0 else None}
    # Evidence: value is the odd/even disagreement in combined
    # white-noise sigma, threshold the policy's EB bar in the
    # same units.
    ev = {"value": (diff / sig) if sig > 0 else None,
          "uncertainty": 1.0 if sig > 0 else None,
          "threshold": fail_sigma}
    if sig > 0 and diff > fail_sigma * sig:
        return StageResult(
            "odd_even", STATUS_FAIL,
            f"odd/even depths differ: {odd['depth_pct']:.2f}% vs "
            f"{even['depth_pct']:.2f}% ({diff / sig:.1f} sigma)",
            _prov(prov), details, **ev)
    return StageResult(
        "odd_even", STATUS_PASS,
        "odd/even depths agree", _prov(prov), details, **ev)


def persistence_result(stamp, prov=None):
    """persistence.sector_persistence output -> StageResult.

    CONSISTENT -> PASS. MIXED / CONCENTRATED / RAW-REFUTED ->
    FAIL. No verdict key (no usable sectors) -> UNMEASURED.
    """
    verdict = stamp.get("verdict") if stamp else None
    details = {k: stamp.get(k) for k in
               ("n_usable", "frac_pos_1p5sigma", "chi2_p",
                "raw_signif")
               if stamp.get(k) is not None} if stamp else {}
    if verdict is None:
        return StageResult(
            "persistence", STATUS_UNMEASURED,
            "no usable sectors for a persistence stamp",
            _prov(prov), details)
    if verdict == "CONSISTENT":
        return StageResult(
            "persistence", STATUS_PASS,
            "signal persists across sectors", _prov(prov), details)
    return StageResult(
        "persistence", STATUS_FAIL,
        f"persistence stamp {verdict}", _prov(prov), details)


def holdout_result(verdict, prov=None):
    """holdout test verdict string -> StageResult.

    HOLDOUT-PASS -> PASS (predictive periodicity only — a clean
    EB passes too, which is why holdout is one stage among many).
    HOLDOUT-FAIL -> FAIL. HOLDOUT-INSUFFICIENT-DATA or None ->
    UNMEASURED.
    """
    if verdict == "HOLDOUT-PASS":
        return StageResult(
            "holdout", STATUS_PASS,
            "held-out sector predicted by the ephemeris",
            _prov(prov), {})
    if verdict == "HOLDOUT-FAIL":
        return StageResult(
            "holdout", STATUS_FAIL,
            "held-out sector does not show the transit",
            _prov(prov), {})
    return StageResult(
        "holdout", STATUS_UNMEASURED,
        "insufficient data for a holdout test", _prov(prov), {})


def catalogue_result(native, prov=None):
    """Catalogue check (manual §0) -> StageResult.

    Native shape: {"known": bool, "source": "VSX"/"TOI"/"PHT"
    or None, "var_type": str or None, "period_match": bool}.
    Not known -> PASS. Known with a matching period -> FAIL
    (the signal is already catalogued — a known variable at
    this period is a blend until imaging proves otherwise, and
    a catalogue hit ends the gauntlet). Known at a DIFFERENT
    period -> PASS with a warning (it does not explain this
    signal). No native output -> UNMEASURED.
    """
    if not native:
        return StageResult(
            "catalogue", STATUS_UNMEASURED,
            "no catalogue check was run", _prov(prov), {})
    details = {k: native.get(k) for k in
               ("source", "var_type", "period_match")
               if native.get(k) is not None}
    if not native.get("known"):
        return StageResult(
            "catalogue", STATUS_PASS,
            "not catalogued in VSX/TOI/PHT", _prov(prov), details)
    if native.get("period_match"):
        return StageResult(
            "catalogue", STATUS_FAIL,
            f"catalogued as {native.get('var_type') or 'variable'} "
            f"in {native.get('source') or 'a catalogue'} at a "
            f"matching period",
            _prov(prov), details)
    return StageResult(
        "catalogue", STATUS_PASS,
        "catalogued at a different period — does not explain "
        "this signal", _prov(prov), details,
        warnings=["known variable at a different period"])


def refine_result(native, prov=None):
    """Period refinement (manual §2) -> StageResult.

    Native shape: {"period_d", "t0", "duration_d",
    "converged": bool, "rms_resid_d": float or None,
    "n_eras": int}. Converged -> PASS (the refined ephemeris is
    the fold anchor from here on). A period that did not
    converge -> INCONCLUSIVE (the phase scan measured but did
    not settle). No period at all -> UNMEASURED. Evidence:
    value is the RMS residual in days — the ephemeris is only
    as good as its residuals.
    """
    if not native or native.get("period_d") is None:
        return StageResult(
            "refine", STATUS_UNMEASURED,
            "no refined period was produced", _prov(prov), {})
    details = {k: native.get(k) for k in
               ("period_d", "t0", "duration_d", "rms_resid_d",
                "n_eras") if native.get(k) is not None}
    ev = {"value": native.get("rms_resid_d"),
          "n_transits": native.get("n_eras")}
    if native.get("converged"):
        return StageResult(
            "refine", STATUS_PASS,
            f"refined period {native['period_d']:.7f} d",
            _prov(prov), details, **ev)
    return StageResult(
        "refine", STATUS_INCONCLUSIVE,
        "phase scan did not converge on a refined period",
        _prov(prov), details, **ev)


def diffimg_result(native, prov=None):
    """Difference imaging / host localisation (manual §6) ->
    StageResult.

    Native shape: {"on_target": bool or None, "offset_px",
    "offset_arcsec", "blend_host_tic", "n_sectors"}. On-target
    -> PASS. Off-target -> FAIL (BLEND — the source is a
    neighbour). No localisation -> UNMEASURED. Evidence: value
    is the centroid offset in pixels.
    """
    if not native or native.get("on_target") is None:
        return StageResult(
            "diffimg", STATUS_UNMEASURED,
            "no difference-imaging localisation", _prov(prov), {})
    details = {k: native.get(k) for k in
               ("offset_px", "offset_arcsec", "blend_host_tic",
                "n_sectors") if native.get(k) is not None}
    ev = {"value": native.get("offset_px")}
    if native.get("on_target"):
        return StageResult(
            "diffimg", STATUS_PASS,
            "source localises on-target", _prov(prov), details,
            **ev)
    host = native.get("blend_host_tic")
    return StageResult(
        "diffimg", STATUS_FAIL,
        "source localises off-target"
        + (f" (blend host TIC {host})" if host else ""),
        _prov(prov), details, **ev)


def pixel_check_result(native, prov=None):
    """Pixel check (manual §7, P >= 8 d only) -> StageResult.

    Native shape: {"verdict": "pass"/"fail"/"unmeasured",
    "reason": str, "details": {...}}. Maps directly; the P < 8 d
    NOT_APPLICABLE is assigned by the runner, not this adapter.
    A FAIL means the pixels brighten where a dip is claimed —
    the transit is not on this target.
    """
    if not native:
        return StageResult(
            "pixel_check", STATUS_UNMEASURED,
            "no pixel check was run", _prov(prov), {})
    verdict = native.get("verdict")
    reason = native.get("reason") or f"pixel check {verdict}"
    details = dict(native.get("details") or {})
    if verdict == "pass":
        return StageResult(
            "pixel_check", STATUS_PASS, reason, _prov(prov),
            details)
    if verdict == "fail":
        return StageResult(
            "pixel_check", STATUS_FAIL, reason, _prov(prov),
            details)
    return StageResult(
        "pixel_check", STATUS_UNMEASURED, reason, _prov(prov),
        details)


def transit_fit_result(native, prov=None):
    """Formal transit fit (manual §8) -> StageResult.

    Native shape: {"b": float or None, "rp_re": float or None,
    "t14_h": float or None, "density_flag": bool,
    "converged": bool}. The shape gate screens; the fit decides:
    a converged physical fit (b < 1, no density flag) -> PASS.
    Grazing (b >= 1) or density-flagged -> FAIL (EB suspect).
    Not converged or no fit at all -> UNMEASURED. A converged
    fit with an unconstrained impact parameter -> INCONCLUSIVE.
    Evidence: value is the impact parameter, threshold 1.0.
    """
    if not native or not native.get("converged"):
        return StageResult(
            "transit_fit", STATUS_UNMEASURED,
            "no converged transit fit", _prov(prov), {})
    details = {k: native.get(k) for k in
               ("b", "rp_re", "t14_h", "density_flag")
               if native.get(k) is not None}
    ev = {"value": native.get("b"), "threshold": 1.0,
          "metrics": {k: native[k] for k in ("rp_re", "t14_h")
                      if native.get(k) is not None}}
    if native.get("b") is None:
        return StageResult(
            "transit_fit", STATUS_INCONCLUSIVE,
            "fit converged but the impact parameter is "
            "unconstrained", _prov(prov), details, **ev)
    if native.get("density_flag"):
        return StageResult(
            "transit_fit", STATUS_FAIL,
            "density flag: fitted duration impossible for a "
            "planet on this star", _prov(prov), details, **ev)
    if native["b"] >= 1.0:
        return StageResult(
            "transit_fit", STATUS_FAIL,
            f"grazing fit (b={native['b']:.2f}) — EB suspect",
            _prov(prov), details, **ev)
    return StageResult(
        "transit_fit", STATUS_PASS,
        f"physical transit fit (b={native['b']:.2f})",
        _prov(prov), details, **ev)


def blend_result(native, prov=None, policy=None):
    """Blend test (gauntlet/blend.py:check_blend) -> StageResult.

    Native shape: {"target_t", "target_f", "neighbour_t",
    "neighbour_f", "period_d", "t0", "duration_d",
    "neighbour_tic", "separation_arcsec"}. The pure function
    folds both light curves and decides; this adapter only maps
    its verdict onto a status. Evidence: value is the depth
    ratio (neighbour/target), threshold is the policy's
    blend_min_depth_ratio.
    """
    if not native:
        return StageResult(
            "blend", STATUS_UNMEASURED,
            "no blend-test input supplied", _prov(prov))
    try:
        from gauntlet.blend import check_blend  # type: ignore
    except ImportError:  # run as a plain script from gauntlet/
        from blend import check_blend  # type: ignore
    res = check_blend(
        native["target_t"], native["target_f"],
        native["neighbour_t"], native["neighbour_f"],
        native["period_d"], native["t0"],
        native["duration_d"],
        neighbour_tic=native.get("neighbour_tic"),
        separation_arcsec=native.get("separation_arcsec"),
        policy=policy)
    verdict = res["verdict"]
    status = {"blend": STATUS_FAIL, "on_target": STATUS_PASS,
              "inconclusive": STATUS_INCONCLUSIVE,
              "unmeasured": STATUS_UNMEASURED}[verdict]
    details = {k: res.get(k) for k in
               ("neighbour_tic", "separation_arcsec", "period_d")
               if res.get(k) is not None}
    metrics = {}
    for key, fold in (("target", res.get("target_fold")),
                      ("neighbour", res.get("neighbour_fold"))):
        if fold:
            metrics[f"{key}_depth_pct"] = fold["depth_pct"]
            metrics[f"{key}_n_in"] = fold["n_in"]
    if res.get("target_signif") is not None:
        metrics["target_signif"] = res["target_signif"]
    if res.get("neighbour_signif") is not None:
        metrics["neighbour_signif"] = res["neighbour_signif"]
    return StageResult(
        "blend", status, res["reason"], _prov(prov), details,
        value=res.get("depth_ratio"),
        threshold=res.get("min_depth_ratio"), metrics=metrics)


# ---------------------------------------------------------------------------
# Aggregation: stage results + imaging -> final verdict
# ---------------------------------------------------------------------------

def normalize_waivers(waivers):
    """Waivers as {stage: reason}. Accepts a dict or a list of
    {"stage", "reason"} dicts (the verdict record's shape).
    Raises ValueError on a malformed entry — a waiver with no
    reason is not a waiver."""
    if not waivers:
        return {}
    if isinstance(waivers, dict):
        items = waivers.items()
    else:
        items = [(w["stage"], w["reason"]) for w in waivers]
    out = {}
    for stage, reason in items:
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError(
                f"waiver for stage {stage!r} has no reason — a "
                f"waiver must name the stage and carry a reason")
        out[stage] = reason
    return out


def validate_waivers(results, waivers, policy=None):
    """Check applied waivers against the decision policy. A waiver
    is valid only when ALL of these hold:
      * the stage ran (it is in `results`);
      * the stage's status is inconclusive or not_applicable
        (a PASS needs no waiver; a FAIL or UNMEASURED can never
        be waived);
      * the stage is in the policy's waiver allowlist
        (policy["waivers"] — the policy gates WHAT may be
        waived; the run supplies the per-target reason).
    Returns the normalized {stage: reason} dict. Raises
    ValueError on the first invalid waiver — an invalid waiver
    is a caller bug, and failing loud beats promoting a
    candidate on a waiver nobody authorized."""
    waived = normalize_waivers(waivers)
    if not waived:
        return {}
    if policy is None:
        policy = load_decision_policy()
    allowlist = policy.get("waivers") or {}
    by_stage = {r.stage: r for r in results}
    for stage, reason in sorted(waived.items()):
        result = by_stage.get(stage)
        if result is None:
            raise ValueError(
                f"waiver for stage {stage!r}, but that stage "
                f"never ran — a waiver names a stage that "
                f"measured inconclusive or not-applicable")
        if result.status not in (STATUS_INCONCLUSIVE,
                                 STATUS_NOT_APPLICABLE):
            raise ValueError(
                f"stage {stage!r} has status "
                f"{result.status!r} — only inconclusive or "
                f"not_applicable may be waived (a pass needs no "
                f"waiver; a fail or unmeasured can never be "
                f"waived)")
        if stage not in allowlist:
            raise ValueError(
                f"stage {stage!r} is not in the decision "
                f"policy's waiver allowlist — the policy waives "
                f"stages explicitly, per-stage, and {stage!r} "
                f"is not among them")
    return waived


def aggregate_verdict(results, imaging=None, waivers=None,
                      policy=None):
    """Decide the final verdict from stage results and imaging.

    Promotion is an ALLOWLIST: only COMPLETED + PASS passes.
    Order of decision (first match wins):
      0. Waivers are validated against the decision policy
         (validate_waivers) — an invalid waiver raises
         ValueError before any verdict is decided.
      1. Any FAIL -> the kill verdict of the FIRST failing stage
         in vetting-manual order.
      2. Imaging localises the source OFF-target -> BLEND.
      3. Any stage UNMEASURED — required or newly registered —
         -> INCONCLUSIVE (not yet vetted — never a candidate,
         never waivable).
      4. Any stage INCONCLUSIVE or NOT_APPLICABLE that is not
         waived -> INCONCLUSIVE. A waived stage is a gap the
         policy calls structural, recorded with its reason.
      5. Any required stage never run -> INCONCLUSIVE.
      6. All required stages PASS (or waived) and imaging is
         on-target -> CANDIDATE.
      7. All required stages PASS (or waived) but imaging is
         missing or unmeasured -> INCONCLUSIVE (a candidate
         needs imaging).

    Returns (final_verdict, note). `imaging` is None or a dict
    with an `on_target` key (True / False / None). `waivers` is
    a {stage: reason} dict or a list of {"stage", "reason"}
    dicts; `policy` is the decision-policy dict (default:
    gauntlet_v2).
    """
    waived = validate_waivers(results, waivers, policy)
    by_stage = {r.stage: r for r in results}
    fails = [r for r in results if r.status == STATUS_FAIL]
    if fails:
        # First fail in manual order decides.
        order = {s: i for i, s in enumerate(REQUIRED_STAGES)}
        fails.sort(key=lambda r: order.get(r.stage, len(order)))
        first = fails[0]
        return (_FAIL_VERDICT.get(first.stage, "REFUTED"),
                f"{first.stage} failed: {first.reason}")
    if imaging is not None and imaging.get("on_target") is False:
        host = imaging.get("blend_host_tic")
        return ("BLEND",
                "imaging localises the source off-target"
                + (f" (blend host TIC {host})" if host else ""))
    for r in results:
        if r.status == STATUS_UNMEASURED:
            return ("INCONCLUSIVE",
                    f"stage {r.stage} unmeasured: {r.reason}")
        if r.status in (STATUS_INCONCLUSIVE,
                        STATUS_NOT_APPLICABLE) \
                and r.stage not in waived:
            return ("INCONCLUSIVE",
                    f"stage {r.stage} {r.status}: {r.reason} "
                    f"(not waived)")
    for stage in REQUIRED_STAGES:
        if stage not in by_stage:
            return ("INCONCLUSIVE",
                    f"stage {stage} never ran — not yet vetted")
    if imaging is not None and imaging.get("on_target") is True:
        note = "all required stages pass"
        if waived:
            names = ", ".join(f"{s} ({waived[s]})"
                              for s in sorted(waived))
            note += f" (waived: {names})"
        note += "; imaging on-target"
        return ("CANDIDATE", note)
    return ("INCONCLUSIVE",
            "all required stages pass but imaging is missing or "
            "unmeasured — a candidate needs on-target imaging")
