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
    it as one, and no CANDIDATE verdict may stand on it.
  * "inconclusive" means the stage measured but could not decide
    (e.g. an ambiguous trapezoid shape). Also never a pass.
  * "not_applicable" means the stage does not apply to this
    target (e.g. a holdout test on a single-sector candidate).
    It is the ONLY non-pass status that does not block a
    candidate — and only the runner may assign it, when the
    stage's prerequisites say it does not apply.
  * A result carries EVIDENCE, not just a verdict: value,
    uncertainty, threshold, detection limit, transits used,
    metrics, artifacts, tool version, config hash, input
    hashes. A bare "pass" hides whether the test could have
    rejected anything at all (an odd/even test on three
    transits at SNR 8 cannot); the evidence is what makes the
    verdict auditable. The raw result and its interpretation
    stay separate: the interpretation thresholds live in the
    versioned gauntlet calibration profile (the decision
    policy), not in the result.
  * Scientific outcome and execution outcome are separate axes:
    execution_status is completed / not_started / skipped /
    error. A crashed external tool is NOT a scientific failure
    of the candidate — it is an unmeasured stage with an error
    execution status, and the type enforces that (see
    __post_init__).
  * Every result carries provenance (calibration_version,
    pipeline_git_sha, run_id, timestamp_utc) so a verdict can
    always be traced to the code and calibration that produced it.

Adapters map each existing stage's native output onto this type
without changing the stage itself: the shape gate, the
clean-data re-fold gate, the raw-flux fold, the odd/even parity
check, the persistence stamp, and the holdout test.
`aggregate_verdict` turns a set of stage results (+ imaging)
into a final verdict; `gauntlet/verdict.py:build_verdict`
assembles and validates the verdict record.
"""
from dataclasses import dataclass, field

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

# Minimum data for a testable fold verdict — the same bars as the
# clean-data gate (bulk/clean_refold_gate.py MIN_IN / MIN_EVENTS).
MIN_IN_CADENCES = 20
MIN_EVENTS = 2
# Raw-flux pass bar — the hunter._raw_fold_depth bar: a genuine
# dip at >= 3 sigma in unflattened flux.
RAW_FLUX_MIN_SIGNIF = 3.0
# Odd/even disagreement bar: families differing by more than this
# many combined white-noise sigma are an EB.
PARITY_FAIL_SIGMA = 3.0

# Stages every candidate must pass (vetting-manual order). A stage
# that never ran is unmeasured — aggregate_verdict treats a missing
# required stage exactly like an UNMEASURED result.
REQUIRED_STAGES = ("clean_gate", "raw_flux", "shape_gate", "parity",
                   "persistence", "holdout")

# What a FAIL at each stage means for the final verdict.
_FAIL_VERDICT = {
    "clean_gate": "REFUTED",
    "raw_flux": "REFUTED",
    "shape_gate": "EB",
    "parity": "EB",
    "persistence": "REFUTED",
    "holdout": "REFUTED",
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
        d = {"stage": self.stage, "status": self.status,
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

def shape_gate_result(gate, prov=None):
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
            "shape_gate", STATUS_UNMEASURED,
            gate.get("reason") or "shape gate unmeasured",
            _prov(prov), details)
    if gate.get("density_flag"):
        return StageResult(
            "shape_gate", STATUS_FAIL,
            gate.get("density_reason")
            or "density flag: fitted duration impossible for a "
               "planet on this star",
            _prov(prov), details)
    if shape == "V-shaped":
        return StageResult(
            "shape_gate", STATUS_FAIL,
            f"V-shaped transit (T23/T14={gate.get('T23_T14'):.2f})"
            if gate.get("T23_T14") is not None else "V-shaped",
            _prov(prov), details)
    if shape == "U-shaped":
        return StageResult(
            "shape_gate", STATUS_PASS,
            "U-shaped transit, no density flag",
            _prov(prov), details)
    return StageResult(
        "shape_gate", STATUS_INCONCLUSIVE,
        f"ambiguous trapezoid shape "
        f"(T23/T14={gate.get('T23_T14'):.2f})"
        if gate.get("T23_T14") is not None else "ambiguous shape",
        _prov(prov), details)


def clean_gate_result(fold, verdict, prov=None):
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
            "clean_gate", STATUS_FAIL,
            "no dip in clean (quality==0) flux at the filed "
            "ephemeris — signal lives only in flagged cadences",
            _prov(prov), details, **ev)
    if verdict == "PASS":
        return StageResult(
            "clean_gate", STATUS_PASS,
            "dip persists in clean flux", _prov(prov), details,
            **ev)
    return StageResult(
        "clean_gate", STATUS_UNMEASURED,
        "insufficient clean in-transit cadences to test",
        _prov(prov), details, **ev)


def raw_flux_result(fold, prov=None):
    """A raw-flux fold_depth dict -> StageResult.

    Depth > 0 at >= 3 sigma in unflattened flux -> PASS. No dip
    or insignificant -> FAIL (RAW-REFUTED). Too few in-transit
    cadences/events -> UNMEASURED.

    Evidence: value is the fold depth (%), uncertainty its
    1-sigma error from the white significance, threshold the
    3-sigma bar in the same units.
    """
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
          "threshold": (RAW_FLUX_MIN_SIGNIF * unc)
          if unc is not None else None,
          "n_transits": fold.get("n_events")}
    if (fold.get("n_in") or 0) < MIN_IN_CADENCES or \
            (fold.get("n_events") or 0) < MIN_EVENTS:
        return StageResult(
            "raw_flux", STATUS_UNMEASURED,
            "too few in-transit cadences/events for a raw-flux "
            "verdict", _prov(prov), details, **ev)
    if depth is not None and signif is not None \
            and depth > 0 and signif >= RAW_FLUX_MIN_SIGNIF:
        return StageResult(
            "raw_flux", STATUS_PASS,
            f"dip in raw flux: {depth:.3f}% "
            f"({signif:.1f} sigma white)",
            _prov(prov), details, **ev)
    return StageResult(
        "raw_flux", STATUS_FAIL,
        "no significant dip in raw flux at the ephemeris",
        _prov(prov), details, **ev)


def parity_result(odd, even, prov=None):
    """event_parity_depths output -> StageResult.

    Either family unmeasured (None) -> UNMEASURED. Families
    differing by > 3 combined sigma -> FAIL (EB at twice the
    period). Agreeing families -> PASS.
    """
    if odd is None or even is None:
        return StageResult(
            "parity", STATUS_UNMEASURED,
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
    # white-noise sigma, threshold the 3-sigma EB bar in the
    # same units.
    ev = {"value": (diff / sig) if sig > 0 else None,
          "uncertainty": 1.0 if sig > 0 else None,
          "threshold": PARITY_FAIL_SIGMA}
    if sig > 0 and diff > PARITY_FAIL_SIGMA * sig:
        return StageResult(
            "parity", STATUS_FAIL,
            f"odd/even depths differ: {odd['depth_pct']:.2f}% vs "
            f"{even['depth_pct']:.2f}% ({diff / sig:.1f} sigma)",
            _prov(prov), details, **ev)
    return StageResult(
        "parity", STATUS_PASS,
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


# ---------------------------------------------------------------------------
# Aggregation: stage results + imaging -> final verdict
# ---------------------------------------------------------------------------

def aggregate_verdict(results, imaging=None):
    """Decide the final verdict from stage results and imaging.

    Order of decision (first match wins):
      1. Any FAIL -> the kill verdict of the FIRST failing stage
         in vetting-manual order.
      2. Imaging localises the source OFF-target -> BLEND.
      3. Any stage UNMEASURED or INCONCLUSIVE — required or
         newly registered — -> INCONCLUSIVE (not yet vetted —
         never a candidate). A stage that ran and could not
         measure is a gap in the case, whoever registered it;
         the escape hatch is not_applicable, which only the
         runner assigns when the stage does not apply.
      4. Any required stage never run -> INCONCLUSIVE.
      5. All required stages PASS or not_applicable and imaging
         is on-target -> CANDIDATE.
      6. All required stages PASS/not_applicable but imaging is
         missing or unmeasured -> INCONCLUSIVE (a candidate
         needs imaging).

    Returns (final_verdict, note). `imaging` is None or a dict
    with an `on_target` key (True / False / None).
    """
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
        if r.status == STATUS_INCONCLUSIVE:
            return ("INCONCLUSIVE",
                    f"stage {r.stage} inconclusive: {r.reason}")
    for stage in REQUIRED_STAGES:
        if stage not in by_stage:
            return ("INCONCLUSIVE",
                    f"stage {stage} never ran — not yet vetted")
    if imaging is not None and imaging.get("on_target") is True:
        return ("CANDIDATE",
                "all required stages pass; imaging on-target")
    return ("INCONCLUSIVE",
            "all required stages pass but imaging is missing or "
            "unmeasured — a candidate needs on-target imaging")
