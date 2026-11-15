# TRICERATOPS / LATTE integration — design doc (Phase 1.2, C-10)

**Status: design only. No code, no integration, no new dependency.
The build is Phase 2 items 2B (LATTE) and 2C (TRICERATOPS), in
that order (ChatGPT's Phase 2 sequence: 2A desk automation →
2B LATTE → 2C TRICERATOPS → 2D candidate evidence package → 2E
independent review). This doc fixes the interface contract now
so Phase 2 implements against it instead of inventing it.**

## Why these tools, and what they are not

The gauntlet's desk checks are deterministic rules (shape,
parity, persistence, centroid). TRICERATOPS and LATTE are
probabilistic cross-checks from the professional pipeline:

- **TRICERATOPS** (Giacalone et al.) computes a Bayesian
  false-positive probability (FPP) and nearby false-positive
  probability (NFPP) for a transit signal, marginalising over
  eclipsing-binary scenarios on the target and on neighbouring
  stars. It answers "how likely is this a planet, given the
  data and the local stellar population?" — a number, not a
  verdict.
- **LATTE** (Eisner et al.) runs the standard automated vetting
  diagnostics (odd/even depth, secondary eclipse, centroid
  shift, transit shape, aperture-size dependence) and reports
  per-check dispositions. It answers "does any standard
  diagnostic flag this?" — a checklist, not a verdict.

Neither tool promotes a candidate on its own. A low FPP does
not replace difference imaging (the hard rule stands: never
claim a planet without centroid/difference imaging), and a
clean LATTE run does not replace the gauntlet — both tools
feed evidence INTO the gauntlet, and the gauntlet's decision
policy (gauntlet_v2, StageResult contract v1) decides what
the evidence means.

## Non-negotiable constraints (from the Phase 1.1 vote)

1. **Out-of-process, always.** Each tool runs in its own
   subprocess with its own virtualenv and its own lockfile
   (`requirements-triceratops.lock`,
   `requirements-latte.lock`, same make_lockfile.py pattern as
   requirements.lock). Neither tool's dependency tree may leak
   into the pipeline's environment: TRICERATOPS pins old
   astropy/numpy in places, and a shared environment would
   silently move the pipeline's numerics. The runner spawns the
   tool, the tool writes JSON, the runner reads JSON — no
   in-process imports, ever.
2. **JSON in / JSON out through StageResult.** The tool
   receives one JSON input file (see § Interface contract) and
   writes one JSON output file. The stage adapter translates
   the output into a StageResult — it never parses tool-native
   plots, logs, or pickle files.
3. **Seeded Monte Carlo.** TRICERATOPS marginalises by Monte
   Carlo sampling; the seed is part of the input (fixed default
   in the tool's config, recorded in the output) so a re-run
   reproduces the number. An unseeded run is a bug, not a
   feature — the StageResult records the seed.
4. **Failure is unmeasured, never pass and never fail.** A tool
   crash, a timeout, a missing input, or a malformed output
   produces status UNMEASURED with execution_status ERROR and
   the reason in `reason` — the runner already maps stage
   exceptions to unmeasured + EXEC_ERROR, and these stages use
   the same path. A tool that cannot run must not kill a
   candidate and must not clear one.
5. **Never on the whole bulk screen.** These tools cost
   minutes-to-tens-of-minutes per target. They run downstream
   of candidate selection only — on gauntlet finalists (the
   handful of stars that survive recalibration), never on the
   ~111,000 screened stars and never on bulk survivors
   generally. Cost model in § Cost.
6. **Evidence, not verdicts.** FPP/NFPP and the LATTE
   per-check dispositions are stored as evidence (see §
   StageResult mapping), never reduced to a bare PASS/FAIL.
   Interpretation thresholds (e.g. "FPP < 0.01 validates")
   belong in the versioned decision policy (gauntlet_v3 or a
   tool-specific policy file), NOT in the tool adapter and NOT
   in the tool's config. Changing a threshold is a calibration
   decision with a version bump, per the AGENTS.md hard rules.

## Where the stages sit in the DAG

Both stages run AFTER transit_fit (they need the refined
ephemeris and the fitted transit parameters) and are EXPENSIVE
(short-circuited after a FAIL, like holdout/diffimg/
transit_fit). Registration in gauntlet/runner.py STAGE_REGISTRY:

```python
StageSpec("latte",
          requires=(EPH_REFINED, "shape", "diffimg",
                    "latte.native"),
          produces=("latte",), func=_latte_fn,
          expensive=True),
StageSpec("triceratops",
          requires=(EPH_REFINED, "shape", "diffimg",
                    "triceratops.native"),
          produces=("triceratops",), func=_triceratops_fn,
          expensive=True),
```

`requires` includes shape + diffimg because both tools are
meaningless without a localised, shaped signal: TRICERATOPS
needs the centroid result to weight the neighbour scenarios,
and LATTE's centroid check duplicates diffimg rather than
replacing it. A FAIL at shape or diffimg short-circuits both
(the cheap stages already killed the candidate; the expensive
tools add nothing). `transit_fit` is deliberately NOT a
requirement: a candidate can be worth a probabilistic
cross-check even when the formal fit is inconclusive (e.g. a
grazing geometry the fitter cannot constrain) — the tools take
the BLS/refined ephemeris + depths, not the fitted posterior.

Both stages are REQUIRED_STAGES members once implemented (a
missing stage is unmeasured, and unmeasured blocks promotion
unless waived — the A-4 allowlist governs waivers, and neither
tool is on it by default: a candidate that never ran its
probabilistic cross-check is not promotable without an
explicit, recorded waiver).

## Interface contract

### Input JSON (runner → tool), one file per target

```json
{
  "tool": "triceratops",
  "tool_version": "1.2.0",
  "seed": 20261114,
  "config_hash": "<sha256 of the tool config file>",
  "target": {
    "tic": "423498314",
    "ra_deg": 123.456,
    "dec_deg": -63.789,
    "tmag": 13.45,
    "star_radius_rsun": 0.673,
    "star_mass_msun": 0.61,
    "teff_k": 4400
  },
  "signal": {
    "period_d": 0.8270470,
    "t0_bjd": 2459000.123,
    "duration_h": 1.41,
    "depth_frac": 0.01029,
    "n_transits": 42,
    "ephemeris": "refined"
  },
  "lightcurve": {
    "path": "<absolute path to the stitched npz: time, flux>",
    "input_hash": "<sha256 of the npz bytes>",
    "sectors": [1, 2, 3],
    "cadence_s": 120.0
  },
  "neighbours": {
    "path": "<absolute path to the TIC cone census JSON>",
    "input_hash": "<sha256 of the census bytes>",
    "radius_arcsec": 180.0
  },
  "contrast_curve": {
    "path": "<absolute path, or null when unavailable>",
    "input_hash": "<sha256 or null>"
  },
  "timeout_s": 1800
}
```

Notes:

- `ephemeris` is always `"refined"` — the bulk period is
  never a valid fold anchor (AGENTS.md hard rule), and it is
  never a valid tool input either.
- `neighbours.radius_arcsec` is 180 (the vetting-manual rule)
  — the tool input is where the 180″ rule becomes executable,
  independent of the diffimg census default (60″, see C-6).
- `contrast_curve` is null when no high-resolution imaging
  exists — the tool must handle that (TRICERATOPS degrades
  gracefully: NFPP without a contrast curve is an upper bound,
  and the output must say so in `warnings`).
- `timeout_s` is enforced by the runner (netbound watchdog,
  C-1 pattern), not by the tool: a hung tool process is killed
  and the stage is UNMEASURED.

The LATTE input is the same shape with `"tool": "latte"` and
no `contrast_curve` (LATTE does not use one).

### Output JSON (tool → runner), one file per target

```json
{
  "tool": "triceratops",
  "tool_version": "1.2.0",
  "seed": 20261114,
  "config_hash": "<sha256 of the tool config file>",
  "status": "completed",
  "value": 0.0032,
  "metrics": {
    "fpp": 0.0032,
    "nfpp": 0.0008,
    "prob_planet": 0.9968,
    "prob_eb_target": 0.0021,
    "prob_eb_neighbour": 0.0009,
    "prob_hierarchical_eb": 0.0002,
    "n_samples": 20000,
    "most_likely_false_positive": "EB on TIC 423498315"
  },
  "artifacts": [
    "<absolute path to the FPP corner plot>",
    "<absolute path to the scenario table csv>"
  ],
  "warnings": ["no contrast curve: NFPP is an upper bound"],
  "wall_time_s": 412.5
}
```

The LATTE output replaces `value`/`metrics` with the
per-check dispositions:

```json
{
  "tool": "latte",
  "tool_version": "0.4.1",
  "seed": 20261114,
  "config_hash": "<sha256>",
  "status": "completed",
  "value": null,
  "metrics": {
    "checks": {
      "odd_even": {"disposition": "pass", "depth_ratio": 1.02},
      "secondary_eclipse": {"disposition": "pass",
                            "depth_2p_pct": 0.04},
      "centroid": {"disposition": "pass",
                   "shift_sigma": 0.8},
      "aperture": {"disposition": "flag",
                   "note": "depth grows 12% in the large aperture"}
    },
    "n_checks": 4,
    "n_flags": 1
  },
  "artifacts": ["<path to the LATTE report pdf>"],
  "warnings": [],
  "wall_time_s": 187.0
}
```

`status` is one of `completed` / `failed` / `timeout`
(tool-reported; the runner treats anything but `completed` as
UNMEASURED). The adapter validates the output against a JSON
schema (schema/triceratops-output-schema.json,
schema/latte-output-schema.json — to be written in Phase 2)
before translating it; a schema failure is UNMEASURED with
execution_status ERROR, not a crash.

## StageResult mapping

| StageResult field | TRICERATOPS | LATTE |
|---|---|---|
| `value` | FPP (the headline number) | null (a checklist has no scalar) |
| `uncertainty` | Monte Carlo error on FPP (from the sample spread) | null |
| `threshold` | the policy's FPP bar (from the decision policy, not the tool) | null |
| `detection_limit` | null (the tool measures a probability, not a detection) | null |
| `n_transits` | the signal's n_transits (copied from the input) | same |
| `metrics` | fpp, nfpp, per-scenario probabilities, n_samples, seed, most-likely FP | per-check dispositions + counts |
| `artifacts` | corner plot + scenario table paths | report pdf path |
| `tool_version` | the tool's version string | same |
| `config_hash` | sha256 of the tool config file | same |
| `input_hashes` | lightcurve + neighbours (+ contrast curve) input hashes | lightcurve + neighbours |
| `warnings` | tool warnings verbatim (e.g. no contrast curve) | tool warnings verbatim |
| `status` | PASS / FAIL / INCONCLUSIVE from the POLICY thresholds applied to FPP/NFPP (never from the tool) | PASS when no check flags, INCONCLUSIVE when a check flags but does not refute (LATTE never FAILs a candidate on its own — a flag is a prompt for human review, recorded in `details`) |
| `execution_status` | COMPLETED, or ERROR → UNMEASURED | same |

The `details` dict carries the human-readable story ("FPP
0.32%, dominated by EB-on-target at 0.21%; no contrast curve,
so NFPP is an upper bound") for the verdict record.

## Determinism

- Same input JSON + same seed + same tool version + same
  config hash ⇒ same output JSON, bit-for-bit on the metrics
  (floating-point summation order inside the tool is the
  tool's problem; the adapter compares with a tolerance, not
  bit-equality, when re-running for verification).
- The seed is FIXED per tool config (not per target, not
  random per run): a re-run of the same target reproduces the
  same FPP. The seed is recorded in the StageResult metrics so
  a future re-run with a different seed is distinguishable.
- The input hashes (lightcurve npz, neighbour census) make
  the tool's inputs verifiable: if the light curve changes,
  the input hash changes, and the old FPP is stale — the
  runner refuses to reuse a cached StageResult whose input
  hashes do not match (the A-5 result-caching rule).

## Cost model

Measured costs (to be re-measured in Phase 2 on the Mac, the
render/compute host — these are planning numbers, not
benchmarks):

| Tool | Per-target wall time | Notes |
|---|---|---|
| TRICERATOPS | ~5–15 min | dominated by the Monte Carlo; scales with n_samples and the neighbour count |
| LATTE | ~2–5 min | dominated by the light-curve diagnostics |

At gauntlet-finalist volume (order 1–10 targets per sector),
one sector's cross-checks cost under 3 hours of Mac time —
affordable as part of the gauntlet, never as part of the
screen. At bulk-screen volume (tens of thousands of stars)
the cost would be years: the tools are gated behind candidate
selection by design, and the runner must refuse to run them
on a bulk survivor list (the stage adapter takes a single
TargetContext, not a list).

## Acceptance criteria (Phase 2)

1. Each tool installs from its own lockfile in a clean venv
   (the C-9 pattern: `pip install --require-hashes -r
   requirements-<tool>.lock` + a smoke import).
2. Each tool reproduces a published result on a known object:
   TRICERATOPS recovers a low FPP (< 0.01) on a confirmed
   planet (TOI-700 c or WASP-126 b) and a high FPP (> 0.5) on
   a known EB (TIC 308851365); LATTE passes the planet and
   flags the EB. These become golden tests (offline fixtures
   where the tool allows it; live otherwise, in the live CI
   job — never in the PR gate).
3. A seeded re-run reproduces the FPP within Monte Carlo
   error; a different seed changes it only within error.
4. A tool crash / timeout / malformed output yields
   UNMEASURED + EXEC_ERROR, never a pass or a fail, and the
   run continues (the stage is expensive, so the runner
   short-circuits AFTER it, not before it).
5. The verdict record for a vetted candidate carries the full
   evidence (FPP/NFPP + per-scenario probabilities + seed +
   tool version + config hash + input hashes) — a reader can
   reproduce the number from the record alone.
6. No new dependency in the pipeline environment
   (requirements.txt / requirements.lock untouched by either
   tool).

## Open questions (for the Phase 2 vote)

1. **Tool versions.** Which TRICERATOPS / LATTE releases to
   pin? Pin the latest stable at build time; record the choice
   and the reason in the tool lockfile header. TRICERATOPS has
   known dependency conflicts with modern astropy — the
   lockfile build may need the make_lockfile.py fallback
   (pip-compile was unusable on this network in Phase 1.1).
2. **NFPP without contrast curves.** Most amateur candidates
   have no high-resolution imaging. Is an NFPP upper bound
   useful enough to run, or should TRICERATOPS be skipped
   (NOT_APPLICABLE with a recorded reason) when no contrast
   curve exists? Leaning: run it, record the bound — an upper
   bound still excludes the worst neighbour scenarios.
3. **LATTE's centroid check vs diffimg.** LATTE re-derives a
   centroid shift from the same TPFs diffimg uses. If they
   disagree, diffimg wins (it is the mandatory gate; LATTE's
   is a cross-check). The adapter must say so in `details`
   when they disagree, not silently prefer one.
4. **FPP thresholds.** The policy bar (e.g. FPP < 0.015 to
   validate, FPP > 0.5 to refute) is a calibration decision
   for the Phase 2 vote, informed by the tools' literature
   (Giacalone et al. use FPP < 0.015 + NFPP < 0.001 for
   validation — corrected 2026-11-15, P-10: the paper's bar
   is 0.015, not 0.01 as first written here). This doc
   deliberately does not set them.
5. **Where the tools run.** The Mac is the compute host
   (scheduled jobs only, per Dev's rules). The tools' venvs
   live on the Mac alongside the pipeline; the VM never runs
   them (the VM's RAM pool cannot hold them beside the
   pipeline). The Phase 2 build must include the Mac setup
   steps (venv creation + lockfile install) as Dev-visible
   commands, not silent SSH.

## Rollout plan (Phase 2)

- **2B (LATTE first):** cheaper, fewer dependencies, and its
  checks overlap the gauntlet's — a good shakedown of the
  out-of-process pattern (subprocess + JSON + StageResult)
  before the heavier tool. Deliverable: latte stage + lockfile
  + golden tests (planet passes, EB flags) + policy thresholds.
- **2C (TRICERATOPS second):** the Monte Carlo tool, with the
  seeding + determinism requirements. Deliverable: triceratops
  stage + lockfile + golden tests (FPP recovery on planet +
  EB) + policy thresholds.
- **2D:** the candidate evidence package (verdict record +
  FPP/NFPP + LATTE report) becomes the filing bundle.
- **2E:** independent review (the three-AI vote) before any
  result from either tool is used in a claim.

## References

- Phase 1.1 vote, Claude's verdict (TRICERATOPS/LATTE section):
  out-of-process, own venv + lockfile, seeded, JSON in/out via
  StageResult, failures → unmeasured, FPP/NFPP stored with seed
  + version as evidence.
- Phase 1.1 vote, ChatGPT's verdict: StageResult must preserve
  evidence, never reduce TRICERATOPS (FPP/NFPP) or LATTE to
  bare PASS/FAIL; interpretation thresholds belong in a
  separate versioned policy; Phase 2 order 2A → 2B → 2C → 2D
  → 2E.
- StageResult contract v1: gauntlet/stage_result.py (evidence
  fields: value, uncertainty, threshold, detection_limit,
  n_transits, metrics, artifacts, tool_version, config_hash,
  input_hashes).
- Stage DAG + registration: gauntlet/runner.py
  (STAGE_REGISTRY, StageSpec requires/produces/expensive).
- Vetting manual: docs/vetting-manual.md (stage order;
  180″ neighbour search; centroid/difference imaging mandatory
  before any claim).
