"""Stage runner (Phase 1.2, item A-5) — the vetting DAG, executed.

The runner turns the vetting-manual stage order (docs/vetting-manual.md
§0–§9) into an executable plan with prerequisite gating. It does NOT
re-implement the stages: each stage's native output is handed to the
runner as an artifact, and the runner's job is ORDER, GATING, and
CACHING — run each stage only when its inputs exist and its
prerequisites passed, short-circuit only where it saves real work,
and never re-run a stage whose inputs have not changed.

The DAG (stage -> requires -> produces -> cost):

    catalogue      TIC, period            catalogue        cheap
    clean_refold   bulk ephemeris         clean_refold     cheap
    refine         bulk ephemeris         refined ephemeris cheap
    raw_flux       refined ephemeris      raw_flux         cheap
    persistence    refined ephemeris      persistence      cheap
    shape          refined ephemeris      shape            cheap
    odd_even       refined ephemeris      odd_even         cheap
    holdout        refined ephemeris      holdout          EXPENSIVE
    diffimg        refined ephemeris      diffimg          EXPENSIVE
    blend          refined ephemeris      blend            cheap
    pixel_check    refined ephemeris      pixel_check      cheap
    transit_fit    shape+holdout+diffimg  transit_fit      EXPENSIVE

(raw_flux is not in the brief's DAG table but stays a required
stage — see REQUIRED_STAGES in stage_result.py.)

Rules:

* KIND. A fold stage consumes a REFINED ephemeris only. The
  entry context carries the BULK (filed) ephemeris; the refine
  stage upgrades it. A caller holding only a refined ephemeris
  may pass it as the entry ephemeris — the fold stages run, but
  refine is SKIPPED (its input, the bulk ephemeris, is absent)
  and the run cannot reach CANDIDATE until refine actually runs:
  the runner never treats a refined entry as a completed
  refinement, because the refine stage's native output is the
  evidence.
* CHEAP ALWAYS. The v1 runner short-circuited EVERYTHING after
  the first FAIL. That is wrong: a cheap stage costs nothing and
  its result is diagnostic (the S96 gauntlet ran every cheap
  stage for every target). In short_circuit mode (the default)
  cheap stages ALWAYS run; only EXPENSIVE stages are skipped
  after a FAIL. `mode="exhaustive"` runs everything.
* FROZEN CONTEXT. TargetContext is immutable: artifacts are a
  read-only mapping, updates return a new context (with_*).
  A stage cannot silently rewrite its own inputs mid-run.
* WAIVED PREREQUISITES. A stage requiring another stage's
  product runs when the producer PASSED — or when the producer
  is inconclusive/not_applicable AND waived (the transit_fit
  rule: a waived holdout does not block the fit). A failed or
  unmeasured prerequisite still refuses the stage.
* CACHING. With a work_dir, results are cached under
  work_dir/"gauntlet-cache"/<context-hash>.json and re-used
  when the input context is unchanged. The cache key covers
  the target, the ephemeris, the native artifacts and the
  imaging — NOT the run provenance (run_id/timestamp), which
  would defeat the cache. A cached result's stage provenance
  is the ORIGINAL run's: the measurements were made then.
* REFINE. After the refine stage passes, the context's
  ephemeris is replaced with the refined one, so later stages
  (e.g. pixel_check's P >= 8 d rule) see the refined period.
"""

import json
import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from types import MappingProxyType

import numpy as np

try:
    from gauntlet.stage_result import (  # type: ignore
        EXEC_COMPLETED, EXEC_ERROR, EXEC_NOT_STARTED, EXEC_SKIPPED,
        STATUS_FAIL, STATUS_INCONCLUSIVE, STATUS_NOT_APPLICABLE,
        STATUS_PASS, STATUS_UNMEASURED, StageResult,
        aggregate_verdict, apply_waivers, blend_result,
        catalogue_result, clean_refold_result,
        diffimg_result, holdout_result, normalize_waivers,
        odd_even_result, persistence_result, pixel_check_result,
        raw_flux_result, refine_result, shape_result,
        transit_fit_result)
except ImportError:  # pragma: no cover - direct-file fallback
    from stage_result import (  # type: ignore  # noqa: E402
        EXEC_COMPLETED, EXEC_ERROR, EXEC_NOT_STARTED, EXEC_SKIPPED,
        STATUS_FAIL, STATUS_INCONCLUSIVE, STATUS_NOT_APPLICABLE,
        STATUS_PASS, STATUS_UNMEASURED, StageResult,
        aggregate_verdict, apply_waivers, blend_result,
        catalogue_result, clean_refold_result,
        diffimg_result, holdout_result, normalize_waivers,
        odd_even_result, persistence_result, pixel_check_result,
        raw_flux_result, refine_result, shape_result,
        transit_fit_result)

EPH_BULK = "ephemeris.bulk"
EPH_REFINED = "ephemeris.refined"

# Stages whose execution costs real time or downloads (full-sector
# light-curve pulls, difference imaging, a formal fit). These are
# the ONLY stages short-circuited after a FAIL.
EXPENSIVE_STAGES = frozenset({"holdout", "diffimg", "transit_fit"})


@dataclass(frozen=True)
class Ephemeris:
    """An ephemeris with its kind. kind is "bulk" (filed, from a
    screen) or "refined" (phase-scan / period refinement). The
    two are different artifacts — a fold stage that accepts
    either is a bug."""

    kind: str
    period_d: float
    t0: float
    duration_d: float
    source: str = ""

    def __post_init__(self):
        if self.kind not in ("bulk", "refined"):
            raise ValueError(
                f"ephemeris kind must be 'bulk' or 'refined', "
                f"got {self.kind!r}")

    @property
    def artifact_key(self):
        return EPH_BULK if self.kind == "bulk" else EPH_REFINED


def _canonical(value):
    """A JSON-canonical form of a context value for hashing.
    StageResults hash via to_dict; numpy arrays hash by their
    bytes (a repr of a 20k-point light curve would be
    megabytes); anything else falls back to repr (so numpy
    scalars and tuples still hash)."""
    if isinstance(value, StageResult):
        return _canonical(value.to_dict())
    if isinstance(value, np.ndarray):
        return {"__ndarray__": hashlib.sha256(
                    np.ascontiguousarray(value).tobytes()
                    ).hexdigest(),
                "shape": list(value.shape),
                "dtype": str(value.dtype)}
    if isinstance(value, Mapping):
        return {str(k): _canonical(v) for k, v in
                sorted(value.items(), key=lambda kv: str(kv[0]))}
    if isinstance(value, (list, tuple)):
        return [_canonical(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)


@dataclass(frozen=True)
class TargetContext:
    """Everything a gauntlet run needs, frozen.

    artifacts maps "<stage>.native" -> the stage's native output
    (whatever the existing tool produced) plus, as the run
    progresses, "<stage>" -> that stage's StageResult. The
    mapping is read-only: use with_artifact / with_ephemeris
    to derive a new context. provenance is the run's provenance
    header (run_id, git sha, calibration map); imaging is the
    imaging evidence dict or None. bulk_survivor says whether
    the target came from a bulk screen (the clean_refold gate
    only applies to bulk survivors).
    """

    tic: str
    ephemeris: Ephemeris | None = None
    artifacts: dict = field(default_factory=dict)
    provenance: dict = field(default_factory=dict)
    imaging: dict | None = None
    bulk_survivor: bool = True

    def __post_init__(self):
        # Freeze the mappings (object.__setattr__ because the
        # dataclass is frozen). The freeze is shallow: a native
        # output dict is still mutable, but the context's shape
        # — which artifacts exist — cannot change in place.
        object.__setattr__(self, "artifacts",
                           MappingProxyType(dict(self.artifacts)))
        object.__setattr__(self, "provenance",
                           MappingProxyType(dict(self.provenance)))
        if self.imaging is not None:
            object.__setattr__(self, "imaging",
                               MappingProxyType(dict(self.imaging)))

    def with_artifact(self, key, value):
        """A new context with one artifact added/replaced."""
        artifacts = dict(self.artifacts)
        artifacts[key] = value
        return replace(self, artifacts=artifacts)

    def with_ephemeris(self, ephemeris):
        """A new context with the ephemeris replaced (refine)."""
        return replace(self, ephemeris=ephemeris)

    def artifact_keys(self):
        keys = set(self.artifacts)
        if self.ephemeris is not None:
            keys.add(self.ephemeris.artifact_key)
        return keys

    def context_hash(self):
        """Stable identity of the run's INPUTS.

        Covers the target, the ephemeris (kind + values), the
        native artifacts and the imaging — NOT the provenance
        (run_id/timestamp change every run and would defeat the
        cache) and NOT the stage products (they do not exist
        when the hash is taken, at run entry).
        """
        payload = {
            "tic": self.tic,
            "bulk_survivor": self.bulk_survivor,
            "ephemeris": (None if self.ephemeris is None else
                          {"kind": self.ephemeris.kind,
                           "period_d": self.ephemeris.period_d,
                           "t0": self.ephemeris.t0,
                           "duration_d": self.ephemeris.duration_d,
                           "source": self.ephemeris.source}),
            "imaging": (None if self.imaging is None
                        else dict(self.imaging)),
            "artifacts": {k: _canonical(v) for k, v in
                          sorted(self.artifacts.items())},
        }
        blob = json.dumps(payload, sort_keys=True,
                          default=repr).encode()
        return hashlib.sha256(blob).hexdigest()


@dataclass(frozen=True)
class StageSpec:
    """A stage's contract with the runner.

    requires: artifact keys (or producing stage names) that must
    exist AND, for a stage product, have PASSED (or been waived)
    before this stage may run. produces: artifact keys this stage
    adds when it runs. expensive: True when the stage costs real
    time/downloads — only expensive stages are short-circuited
    after a FAIL. mandatory: a required stage (in REQUIRED_STAGES)
    blocks the candidate verdict when it never runs.
    """

    name: str
    requires: tuple = ()
    produces: tuple = ()
    func: object = None
    expensive: bool = False
    mandatory: bool = True


# ---------------------------------------------------------------------------
# Stage functions: context -> StageResult (via the adapters)
# ---------------------------------------------------------------------------

def _prov(ctx):
    return dict(ctx.provenance)


def _catalogue_fn(ctx):
    if ctx.ephemeris is None:
        return StageResult("catalogue", STATUS_UNMEASURED,
                           "no period to match against the "
                           "catalogues", _prov(ctx))
    return catalogue_result(ctx.artifacts.get("catalogue.native"),
                            ctx.provenance)


def _clean_refold_fn(ctx):
    if not ctx.bulk_survivor:
        return StageResult(
            "clean_refold", STATUS_NOT_APPLICABLE,
            "target is not a bulk survivor: no clean-data gate "
            "applies", _prov(ctx),
            waiver_code="not_bulk_survivor")
    native = ctx.artifacts.get("clean_refold.native")
    if native is None:
        return StageResult(
            "clean_refold", STATUS_UNMEASURED,
            "no clean-gate output supplied", _prov(ctx))
    fold, verdict = native
    return clean_refold_result(fold, verdict, ctx.provenance)


def _refine_fn(ctx):
    return refine_result(ctx.artifacts.get("refine.native"),
                         ctx.provenance)


def _refined_ephemeris(ctx):
    """The refined ephemeris after a PASSing refine stage: the
    refined period from the native output, with t0/duration
    falling back to the entry (bulk) ephemeris."""
    native = ctx.artifacts.get("refine.native") or {}
    bulk = ctx.ephemeris
    return Ephemeris(
        "refined", native["period_d"],
        native.get("t0", bulk.t0 if bulk is not None else 0.0),
        native.get("duration_d",
                   bulk.duration_d if bulk is not None else 0.0),
        source="refine")


def _raw_flux_fn(ctx):
    return raw_flux_result(ctx.artifacts["raw_flux.native"],
                           ctx.provenance)


def _persistence_fn(ctx):
    return persistence_result(
        ctx.artifacts["persistence.native"], ctx.provenance)


def _shape_fn(ctx):
    return shape_result(ctx.artifacts["shape.native"],
                        ctx.provenance)


def _odd_even_fn(ctx):
    odd, even = ctx.artifacts["odd_even.native"]
    return odd_even_result(odd, even, ctx.provenance)


def _holdout_fn(ctx):
    return holdout_result(ctx.artifacts["holdout.native"],
                          ctx.provenance)


def _diffimg_fn(ctx):
    return diffimg_result(ctx.artifacts["diffimg.native"],
                          ctx.provenance)


def _blend_fn(ctx):
    return blend_result(ctx.artifacts["blend.native"],
                        ctx.provenance)


def _pixel_check_fn(ctx):
    eph = ctx.ephemeris
    if eph is not None and eph.period_d < 8.0:
        return StageResult(
            "pixel_check", STATUS_NOT_APPLICABLE,
            f"period {eph.period_d:.2f} d < 8 d: the TPF pixel "
            f"check does not apply", _prov(ctx),
            waiver_code="period_lt_8d")
    native = ctx.artifacts.get("pixel_check.native")
    if native is None:
        return StageResult(
            "pixel_check", STATUS_UNMEASURED,
            "no pixel-check output supplied", _prov(ctx))
    return pixel_check_result(native, ctx.provenance)


def _transit_fit_fn(ctx):
    return transit_fit_result(ctx.artifacts["transit_fit.native"],
                              ctx.provenance)


# The DAG, in vetting-manual order. A stage's `requires` names
# artifact keys or producing stages; transit_fit's stage-product
# requirements mean it runs only when shape, holdout and diffimg
# PASSED (or were waived — see _check_requires).
STAGE_REGISTRY = {}


def register_stage(spec):
    STAGE_REGISTRY[spec.name] = spec


for _spec in (
    StageSpec("catalogue", requires=("catalogue.native",),
              produces=("catalogue",), func=_catalogue_fn),
    StageSpec("clean_refold", requires=(EPH_BULK,),
              produces=("clean_refold",), func=_clean_refold_fn),
    StageSpec("refine", requires=(EPH_BULK, "refine.native"),
              produces=("refine", EPH_REFINED), func=_refine_fn),
    StageSpec("raw_flux", requires=(EPH_REFINED,
                                    "raw_flux.native"),
              produces=("raw_flux",), func=_raw_flux_fn),
    StageSpec("persistence", requires=(EPH_REFINED,
                                       "persistence.native"),
              produces=("persistence",), func=_persistence_fn),
    StageSpec("shape", requires=(EPH_REFINED, "shape.native"),
              produces=("shape",), func=_shape_fn),
    StageSpec("odd_even", requires=(EPH_REFINED,
                                    "odd_even.native"),
              produces=("odd_even",), func=_odd_even_fn),
    StageSpec("holdout", requires=(EPH_REFINED, "holdout.native"),
              produces=("holdout",), func=_holdout_fn,
              expensive=True),
    StageSpec("diffimg", requires=(EPH_REFINED, "diffimg.native"),
              produces=("diffimg",), func=_diffimg_fn,
              expensive=True),
    StageSpec("blend", requires=(EPH_REFINED, "blend.native"),
              produces=("blend",), func=_blend_fn),
    StageSpec("pixel_check", requires=(EPH_REFINED,),
              produces=("pixel_check",), func=_pixel_check_fn),
    StageSpec("transit_fit",
              requires=(EPH_REFINED, "shape", "holdout",
                        "diffimg", "transit_fit.native"),
              produces=("transit_fit",), func=_transit_fit_fn,
              expensive=True),
):
    register_stage(_spec)


def get_stage(name):
    try:
        return STAGE_REGISTRY[name]
    except KeyError:
        raise ValueError(f"unknown stage {name!r}") from None


def _check_requires(ctx, spec, available, results_by_stage,
                    waived=None):
    """Missing prerequisites for one stage.

    A plain artifact key is satisfied by presence. A stage
    product is satisfied by a PASSED producer — or by a producer
    whose inconclusive/not_applicable status is WAIVED (a waived
    prerequisite counts as satisfied; a failed or unmeasured one
    still refuses the stage).
    """
    waived = waived or {}
    missing = []
    for req in spec.requires:
        producer = results_by_stage.get(req)
        if producer is not None:
            if producer.status == STATUS_PASS:
                continue
            if (producer.status in (STATUS_INCONCLUSIVE,
                                    STATUS_NOT_APPLICABLE)
                    and req in waived):
                continue
            missing.append(
                f"{req} {producer.status}: {producer.reason}")
        elif req in available:
            continue
        else:
            missing.append(f"missing {req}")
    return missing


def validate_plan(ctx, stages):
    """Static plan check: for each stage in order, which
    prerequisites are unmet? Returns [(stage, [reasons])].
    A plan is sound only when this returns []."""
    available = ctx.artifact_keys()
    results_by_stage = {}
    problems = []
    for name in stages:
        spec = get_stage(name)
        missing = _check_requires(ctx, spec, available,
                                  results_by_stage)
        if missing:
            problems.append((name, missing))
        available |= set(spec.produces)
    return problems


@dataclass
class GauntletRun:
    results: list
    final_verdict: str
    verdict_note: str
    skipped: list
    cached: bool = False
    context_hash: str = ""


def _cache_path(work_dir, context_hash):
    return (Path(work_dir) / "gauntlet-cache"
            / f"{context_hash}.json")


def _load_cached(work_dir, context_hash):
    path = _cache_path(work_dir, context_hash)
    if not path.exists():
        return None
    try:
        record = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    if record.get("context_hash") != context_hash:
        return None
    try:
        results = [StageResult.from_dict(d)
                   for d in record["results"]]
    except (KeyError, TypeError, ValueError):
        return None
    return GauntletRun(
        results=results,
        final_verdict=record["final_verdict"],
        verdict_note=record.get("verdict_note", ""),
        skipped=[tuple(s) for s in record.get("skipped", [])],
        cached=True, context_hash=context_hash)


def _save_cached(work_dir, run):
    path = _cache_path(work_dir, run.context_hash)
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "context_hash": run.context_hash,
        "results": [r.to_dict() for r in run.results],
        "final_verdict": run.final_verdict,
        "verdict_note": run.verdict_note,
        "skipped": [list(s) for s in run.skipped],
    }
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(record, sort_keys=True))
    tmp.replace(path)


def run_gauntlet(ctx, stages=None, mode="short_circuit",
                 waivers=None, policy=None, work_dir=None):
    """Run the gauntlet over a target context.

    mode "short_circuit" (default): cheap stages always run;
    only EXPENSIVE stages are skipped after a FAIL.
    mode "exhaustive": run every stage regardless of FAILs.
    waivers: passed to aggregate_verdict (and used to satisfy
    waived prerequisites). work_dir: when given, results are
    cached under work_dir/"gauntlet-cache"/<context-hash>.json
    and re-used for an unchanged input context.
    """
    if mode not in ("short_circuit", "exhaustive"):
        raise ValueError(
            f"mode must be 'short_circuit' or 'exhaustive', "
            f"got {mode!r}")
    names = (list(STAGE_REGISTRY) if stages is None
             else list(stages))
    specs = [get_stage(n) for n in names]
    waived = normalize_waivers(waivers)
    context_hash = ctx.context_hash()

    if work_dir is not None:
        cached = _load_cached(work_dir, context_hash)
        if cached is not None:
            return cached

    available = ctx.artifact_keys()
    results_by_stage = {}
    results = []
    skipped = []
    failed = None
    for spec in specs:
        if (failed is not None and mode == "short_circuit"
                and spec.expensive):
            results.append(StageResult(
                spec.name, STATUS_UNMEASURED,
                f"not started: {failed} failed and {spec.name} "
                f"is an expensive stage", _prov(ctx),
                execution_status=EXEC_NOT_STARTED))
            skipped.append((spec.name, f"skipped after "
                            f"{failed} failed"))
            continue
        missing = _check_requires(ctx, spec, available,
                                  results_by_stage, waived)
        if missing:
            results.append(StageResult(
                spec.name, STATUS_UNMEASURED,
                "skipped: " + "; ".join(missing), _prov(ctx),
                execution_status=EXEC_SKIPPED))
            skipped.append((spec.name, "; ".join(missing)))
            continue
        try:
            result = spec.func(ctx)
        except Exception as exc:  # noqa: BLE001
            # A stage that crashes is unmeasured with an error
            # execution status — never a pass, never a run kill.
            result = StageResult(
                spec.name, STATUS_UNMEASURED,
                f"stage raised {type(exc).__name__}: {exc}",
                _prov(ctx), execution_status=EXEC_ERROR)
            skipped.append((spec.name, result.reason))
        results.append(result)
        results_by_stage[spec.name] = result
        available |= set(spec.produces)
        ctx = ctx.with_artifact(spec.name, result)
        if spec.name == "refine" and result.status == STATUS_PASS:
            # The refined ephemeris replaces the bulk one from
            # here on — later stages fold on it.
            ctx = ctx.with_ephemeris(_refined_ephemeris(ctx))
        if result.status == STATUS_FAIL and failed is None:
            failed = spec.name

    # F-5: stamp the waiver reasons onto the results before
    # aggregating, so the returned (and cached) run carries the
    # full waiver story on its stages — the filing gate detects
    # waivers from the results alone.
    results = apply_waivers(results, waivers, policy)
    verdict, note = aggregate_verdict(
        results, ctx.imaging, waivers=waivers, policy=policy)
    run = GauntletRun(results=results, final_verdict=verdict,
                      verdict_note=note, skipped=skipped,
                      cached=False, context_hash=context_hash)
    if work_dir is not None:
        _save_cached(work_dir, run)
    return run


def check_report_ready(results, review_2e=None):
    """The filing gate's data precondition (manual §9): a
    candidate is report-ready only when persistence, diffimg
    AND blend all PASS. This is a data check only — the human
    gate (filing_gate) is enforced separately by
    check_report_ready's caller and is never runnable here.

    F-5: a waived candidate additionally needs a second-eyes
    review marker — `review_2e` must be a dict with a non-empty
    "reviewer". Waivers are detected from the results
    themselves (any waiver_reason set), so a record that
    carries waivers cannot reach the filing gate unreviewed
    just because the caller forgot to pass the waivers list."""
    by_stage = {r.stage: r for r in results}
    for stage in ("persistence", "diffimg", "blend"):
        r = by_stage.get(stage)
        if r is None:
            return (False, f"{stage} stage never ran — a "
                    f"report needs {stage} to pass")
        if r.status != STATUS_PASS:
            return (False, f"{stage} {r.status}: {r.reason}")
    waived = [r.stage for r in results if r.waiver_reason]
    if waived:
        reviewer = (review_2e or {}).get("reviewer") \
            if isinstance(review_2e, dict) else None
        if not (isinstance(reviewer, str) and reviewer.strip()):
            return (False,
                    f"waived stage(s) {', '.join(sorted(waived))}"
                    f" — a waived candidate needs a second-eyes "
                    f"review (review_2e with a reviewer) before "
                    f"filing")
    return (True, "persistence, diffimg and blend all pass")
