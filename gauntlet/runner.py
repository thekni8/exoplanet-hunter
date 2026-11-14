"""Executable gauntlet stage runner (Phase 1.2, item P0-1).

Phase 1.1 gave the gauntlet typed results and an aggregator — but
that enforces status COMPOSITION, not execution ORDER. Nothing
stopped a fold stage consuming a bulk (unrefined) period, a
variable-star report going out with blend unmeasured, or a stage
running before its prerequisites existed. All three Phase 1.1
reviewers called stage order the weakest closure; this module is
the fix.

The runner is deliberately thin — a dict registry, not a plugin
framework:

  * Every stage is a StageSpec: a name, the artifacts it
    `requires`, the artifacts it `produces`, and a function
    taking a TargetContext and returning a StageResult.
  * The runner executes stages in the caller's order and REFUSES
    to run a stage whose prerequisites are missing or
    unmeasured: the stage gets a SKIPPED/unmeasured result
    naming the missing prerequisite, and the run continues.
    A fold stage requiring "ephemeris.refined" never runs on a
    bulk ephemeris — the ephemeris kind is part of the artifact
    key, so the check is structural, not a comment.
  * In short_circuit mode (the default), a FAIL ends the run:
    remaining stages get NOT_STARTED/unmeasured results. In
    exhaustive mode every stage runs (diagnostics).
  * A stage whose function raises becomes an unmeasured result
    with execution_status "error" — a crashed stage never kills
    the run and never passes.
  * New stages register with register_stage(); the runner treats
    a registered stage exactly like a built-in one, and
    aggregate_verdict blocks candidacy on any unmeasured or
    inconclusive stage, registered or built-in.

TargetContext is the shared state: the target TIC, the
ephemeris (typed: bulk vs refined), the artifacts the caller
has already produced (light curves, native stage outputs), the
provenance header, and the imaging verdict. Stages read from
the context and write their products back into it, so Phase 2
stages share cached light curves and TPFs instead of
re-downloading MAST products per stage.
"""
from dataclasses import dataclass, field

from gauntlet.stage_result import (
    EXEC_ERROR, EXEC_NOT_STARTED, EXEC_SKIPPED, REQUIRED_STAGES,
    STATUS_FAIL, STATUS_NOT_APPLICABLE, STATUS_UNMEASURED,
    StageResult, aggregate_verdict, clean_gate_result,
    holdout_result, parity_result, persistence_result,
    raw_flux_result, shape_gate_result)

# Artifact keys. The ephemeris kind is part of the key on
# purpose: "ephemeris.refined" and "ephemeris.bulk" are different
# artifacts, and a fold stage requiring the refined one can never
# be satisfied by a bulk ephemeris.
EPH_REFINED = "ephemeris.refined"
EPH_BULK = "ephemeris.bulk"


@dataclass(frozen=True)
class Ephemeris:
    """A fold ephemeris with its KIND attached.

    kind is "bulk" (single-sector screen period — NOT a valid
    fold anchor over multi-year baselines) or "refined"
    (phase-scan / period-refined — the only kind a fold stage
    may consume). The kind travels with the numbers so a fold
    stage cannot accidentally consume the wrong one.
    """
    kind: str
    period_d: float
    t0: float
    duration_d: float
    source: str = "filed"

    def __post_init__(self):
        if self.kind not in ("bulk", "refined"):
            raise ValueError(
                f"ephemeris kind must be 'bulk' or 'refined', "
                f"got {self.kind!r}")

    @property
    def artifact_key(self):
        return EPH_REFINED if self.kind == "refined" else EPH_BULK


@dataclass
class TargetContext:
    """Shared state for one gauntlet run.

    artifacts: caller-supplied inputs and stage products, keyed
    by artifact name. Native stage outputs live under
    "<stage>.native" (e.g. "shape_gate.native" is the trapezoid
    gate dict the adapter consumes); the runner adds each
    stage's products as it runs. imaging: the centroid /
    difference-imaging verdict dict (on_target True/False/None),
    or None when imaging has not run.
    """
    tic: str
    ephemeris: Ephemeris | None = None
    artifacts: dict = field(default_factory=dict)
    provenance: dict = field(default_factory=dict)
    imaging: dict | None = None

    def artifact_keys(self):
        keys = set(self.artifacts)
        if self.ephemeris is not None:
            keys.add(self.ephemeris.artifact_key)
        return keys


@dataclass(frozen=True)
class StageSpec:
    """One registered gauntlet stage.

    requires: artifact keys that must exist (and, for keys that
    are another stage's product, whose producing stage must have
    PASSED) before this stage may run. produces: artifact keys
    this stage adds to the context. func: (context) ->
    StageResult. mandatory: whether the stage is required for a
    candidate verdict (REQUIRED_STAGES); non-mandatory stages
    still block candidacy when unmeasured (aggregate_verdict),
    but the runner does not require them in a plan.
    """
    name: str
    requires: tuple = ()
    produces: tuple = ()
    func: object = None
    mandatory: bool = True


# ---------------------------------------------------------------------------
# Built-in stage functions: thin wrappers over the Phase 1.1 adapters.
# Each reads its native output from the context and converts it. The
# runner guarantees the native output exists before calling (it is a
# declared prerequisite), so a missing key here is a runner bug.
# ---------------------------------------------------------------------------

def _clean_gate_fn(ctx):
    fold, verdict = ctx.artifacts["clean_gate.native"]
    return clean_gate_result(fold, verdict, ctx.provenance)


def _raw_flux_fn(ctx):
    return raw_flux_result(ctx.artifacts["raw_flux.native"],
                           ctx.provenance)


def _shape_gate_fn(ctx):
    return shape_gate_result(ctx.artifacts["shape_gate.native"],
                             ctx.provenance)


def _parity_fn(ctx):
    odd, even = ctx.artifacts["parity.native"]
    return parity_result(odd, even, ctx.provenance)


def _persistence_fn(ctx):
    return persistence_result(ctx.artifacts["persistence.native"],
                              ctx.provenance)


def _holdout_fn(ctx):
    return holdout_result(ctx.artifacts["holdout.native"],
                          ctx.provenance)


# The six required stages in vetting-manual order. Every fold
# stage requires the REFINED ephemeris — a bulk ephemeris can
# never satisfy it, so a fold on an unrefined period is refused
# structurally, not by convention.
STAGE_REGISTRY = {}


def register_stage(spec):
    """Register a stage (built-in or Phase 2). Re-registering a
    name replaces it — the registry is a dict, not a framework."""
    STAGE_REGISTRY[spec.name] = spec
    return spec


def get_stage(name):
    return STAGE_REGISTRY.get(name)


for _spec in (
    StageSpec("clean_gate",
              requires=(EPH_REFINED, "clean_gate.native"),
              produces=("clean_gate",), func=_clean_gate_fn),
    StageSpec("raw_flux",
              requires=(EPH_REFINED, "raw_flux.native"),
              produces=("raw_flux",), func=_raw_flux_fn),
    StageSpec("shape_gate",
              requires=(EPH_REFINED, "shape_gate.native"),
              produces=("shape_gate",), func=_shape_gate_fn),
    StageSpec("parity",
              requires=(EPH_REFINED, "parity.native"),
              produces=("parity",), func=_parity_fn),
    StageSpec("persistence",
              requires=(EPH_REFINED, "persistence.native"),
              produces=("persistence",), func=_persistence_fn),
    StageSpec("holdout",
              requires=(EPH_REFINED, "holdout.native"),
              produces=("holdout",), func=_holdout_fn),
):
    register_stage(_spec)


@dataclass
class GauntletRun:
    """The outcome of one run_gauntlet call."""
    results: list
    final_verdict: str
    verdict_note: str
    skipped: list  # (stage, reason) for stages the runner refused


def _check_requires(ctx, spec, available, results_by_stage):
    """Return the list of unsatisfied prerequisites for `spec`,
    each as a human-readable reason. Empty means runnable."""
    missing = []
    for req in spec.requires:
        if req not in available:
            if req == EPH_REFINED and EPH_BULK in available:
                missing.append(
                    "requires a refined ephemeris, but the "
                    "context holds a bulk ephemeris — refine "
                    "the period first")
            else:
                missing.append(f"missing prerequisite {req!r}")
            continue
        # A requirement that is another stage's product is only
        # satisfied when that stage PASSED — a failed or
        # unmeasured prerequisite blocks its dependents.
        producer = results_by_stage.get(req)
        if producer is not None and not producer.is_pass:
            missing.append(
                f"prerequisite stage {req!r} did not pass "
                f"(status {producer.status})")
    return missing


def validate_plan(ctx, stage_names):
    """Check a stage plan WITHOUT running it. Returns the list of
    (stage, [reasons]) for stages whose prerequisites cannot be
    satisfied by the context plus the produces of earlier stages
    in the plan. Raises ValueError for an unknown stage name."""
    available = ctx.artifact_keys()
    problems = []
    for name in stage_names:
        spec = get_stage(name)
        if spec is None:
            raise ValueError(f"unknown gauntlet stage {name!r}")
        missing = [f"missing prerequisite {r!r}" for r in spec.requires
                   if r not in available]
        if missing:
            problems.append((name, missing))
        available |= set(spec.produces)
    return problems


def run_gauntlet(ctx, stages=None, mode="short_circuit"):
    """Run the gauntlet stages over `ctx` in order.

    stages: stage names in execution order (default: the six
    required stages in vetting-manual order). mode:
    "short_circuit" (default) stops at the first FAIL;
    "exhaustive" runs every stage regardless (diagnostics).
    Returns a GauntletRun with the stage results, the aggregated
    final verdict, and the list of stages the runner refused.
    """
    if mode not in ("short_circuit", "exhaustive"):
        raise ValueError(f"unknown runner mode {mode!r}")
    names = list(stages) if stages is not None \
        else list(REQUIRED_STAGES)
    for name in names:
        if get_stage(name) is None:
            raise ValueError(f"unknown gauntlet stage {name!r}")
    available = ctx.artifact_keys()
    results = []
    results_by_stage = {}
    skipped = []
    failed = None
    for name in names:
        spec = get_stage(name)
        if failed is not None and mode == "short_circuit":
            results.append(StageResult(
                name, STATUS_UNMEASURED,
                f"not run: short-circuited after {failed} failed",
                dict(ctx.provenance),
                execution_status=EXEC_NOT_STARTED))
            skipped.append((name, f"short-circuited after {failed}"))
            continue
        missing = _check_requires(ctx, spec, available,
                                  results_by_stage)
        if missing:
            results.append(StageResult(
                name, STATUS_UNMEASURED,
                "refused: " + "; ".join(missing),
                dict(ctx.provenance),
                execution_status=EXEC_SKIPPED))
            skipped.append((name, "; ".join(missing)))
            continue
        try:
            result = spec.func(ctx)
        except Exception as exc:  # noqa: BLE001 — one stage's bug
            # must never kill the run, and never pass either.
            result = StageResult(
                name, STATUS_UNMEASURED,
                f"stage raised {type(exc).__name__}: {exc}",
                dict(ctx.provenance),
                execution_status=EXEC_ERROR)
        results.append(result)
        results_by_stage[name] = result
        available |= set(spec.produces)
        ctx.artifacts[name] = result
        if result.status == STATUS_FAIL and failed is None:
            failed = name
    final_verdict, note = aggregate_verdict(results, ctx.imaging)
    return GauntletRun(results=results, final_verdict=final_verdict,
                       verdict_note=note, skipped=skipped)


def check_report_ready(results):
    """Gate for a variable-star report (VSX filing): the blend
    check must have run and passed. Only the candidate path is
    schema-gated; this is the equivalent gate for the report
    path. Returns (ready, reason)."""
    by_stage = {r.stage: r for r in results}
    blend = by_stage.get("blend")
    if blend is None:
        return (False, "blend stage never ran — no variable-star "
                       "report may go out with blend unmeasured")
    if blend.status == STATUS_UNMEASURED:
        return (False, f"blend unmeasured: {blend.reason}")
    if blend.status == STATUS_FAIL:
        return (False, "blend check failed — the signal is a "
                       "photocopy of a neighbour; no report on "
                       "this target")
    if blend.status == STATUS_NOT_APPLICABLE:
        return (False, "blend not applicable — no blend evidence "
                       "exists for this target")
    if blend.status != "pass":
        return (False, f"blend {blend.status}: {blend.reason}")
    return (True, "blend check passed")
