# Phase 2 progress — desk automation + TRICERATOPS/LATTE

Base: `standardize/phase-1` at `4acbc16` (389 tests: 385 offline
+ 4 live). Branch: `standardize/phase-2`. Worktree:
`~/workspace/exoplanet-hunter-phase2`. No push, no merge — Dev
runs the AI votes when he wakes (2026-11-15 00:07 IST).

Order: 2A desk → 2B LATTE → 2C TRICERATOPS → 2D evidence
package → 2E review. Commit per item.

## 2A — Desk automation (COMPLETE)

| Item | Commit | What |
|---|---|---|
| 2A-1 | `ca5ce0e` | Promote the BLS refine primitive to `gauntlet/refine.py` (verbatim from `holdout_test._refine_ephemeris`; alias kept). 4 tests. |
| 2A-2 | `f3a1f83` | Stage-0 census in-repo (`gauntlet/census.py`, fail-closed) + PHT adapter branch (INCONCLUSIVE). 10 tests. |
| 2A-3 | `26db546` | Pixel check (manual §7) as a new tool (`gauntlet/pixel_check.py`). 5 tests. |
| 2A-4 | `ff8d374` | Desk driver (`gauntlet/desk.py`, two-pass) + CLI (`scripts/desk_gauntlet.py`) + `rawflux_check` explicit-args refactor. 18 tests. |
| 2A-5 | — | Live clean-gate regression (`tests/test_desk_live.py`, DOWNLOAD_TESTS) + `docs/desk-automation.md`. 1 live test. |

Test tally after 2A: 389 at base + 4 (refine) + 10 (census) +
5 (pixel) + 18 (desk) + 1 (live) = **427** (422 offline + 5
live). Smoke tier green (194/194). Full suite to be run once
at the end.

### Claims ledger (2A)

- The automated clean gate FAILs both real S96
  flagged-cadence artifacts (TIC 355401152, 382571558) and
  PASSes the real planet TIC 183537452 on live MAST data
  (`test_desk_live`, verified 2026-11-15).
- The driver reproduces the manual gauntlet's verdict logic
  on synthetic data: 12 end-to-end scenarios (CANDIDATE,
  flagged-cadence kill, TOI kill, EB shape kill, blend kill,
  single-sector waivers, pixel-check pass/kill, no-data,
  persistence kill, diffimg kill, grazing-fit kill).
- A cheap-stage FAIL ends the run before any expensive stage
  is called (asserted via the fake data source's call log).
- `rho_star` is in SOLAR units throughout the driver (the
  shape gate's expectation). A g/cm³ slip during development
  false-flagged the density check on the synthetic planet —
  caught by the tests, fixed, and pinned by
  `test_rho_star_from_census`.

### Judgment calls (2A — for the Phase 2 vote)

1. **Clean gate is the three-way flagcheck.** The bulk gate
   CLI keeps `verdict_for` as validated; the driver adds the
   flagged-only FAIL (flagged cadences alone carrying a ≥3σ
   dip, measured against the clean out-of-transit baseline).
   The 18 rescore artifacts have ZERO clean in-transit
   cadences — a bare clean_fold reads them INSUFFICIENT.
2. **Gauntlet catalogue is fail-closed; the sweep is
   fail-open.** A census whose TOI/VSX/PHT sub-check errored
   produces no catalogue native (UNMEASURED). A Gaia failure
   does not block (advisory only).
3. **VSX kill radius 30″** (the `hunter.is_known_in_vsx`
   bar); a matching variable 30–180″ out is blend evidence.
4. **PHT hit → INCONCLUSIVE** (a Talk thread carries no
   period; a human must read the discussion). New adapter
   branch, additive.
5. **Diffimg on-target bar: 1 px** (21″). The manual gives no
   number; the 423498314 on-target case was 0.06 px.
6. **Pixel-check bars: 3σ, 3×3 aperture.** The manual gives
   no numbers. The 3×3 (not the whole cutout) is deliberate:
   a 3σ bar over 225 pixels false-fails ~1 in 4 clean
   targets on multiple comparisons alone, and a brightening
   outside the aperture does not contaminate the aperture
   flux. Depths are medians, so the significance carries the
   1.2533 median standard-error factor.
7. **Waivers are filtered, never blindly forwarded.** Pass 1
   runs without waivers; pass 2 and the verdict get only
   waivers that apply. Drops are recorded in
   `desk_natives.json`.
8. **F-8 copies left untouched.** `persistence_native` and
   `dip_free_neighbour` are generalised into `gauntlet/desk.py`;
   the `scripts/toi_population.py` copies stay frozen so the
   F-8 baseline remains untouched evidence.

### Open questions carried forward (2A)

- Holdout re-runs the pipeline instead of reusing the
  driver's arrays (array-based holdout is a follow-up).
- P/2 alias kill threshold: the P/2 fold and the phase-0.5
  secondary fold are evidence, not stage criteria.
- Transit fit is QLP-only + LS-only (no TESSCut sectors, no
  MCMC).
- The F-8 TOI-700 c shape false-kill stands (T23/T14 0.2925
  vs the 0.30 bar) — a shape-gate review is a vote item, not
  a 2A change (threshold = calibration).

## 2B — LATTE (COMPLETE)

| Item | Commit | What |
|---|---|---|
| 2B-1 | `39dc271` | Shared external-tool plumbing (`gauntlet/external_tool.py`): subprocess runner with timeout + RLIMIT_AS memory cap, C-10 input builder, missing-venv as a status. 14 tests. |
| 2B-2 | `c0ccc7a` | LATTE adapter (`latte_result` in `stage_result.py`, report-only → INCONCLUSIVE) + output schema + `gauntlet/tools/run_latte.py` wrapper (targetlist CSV, stable indir via `_config.txt`, PDF check, nested timeout). 14 tests (adapter + wrapper against a fake LATTE package). |
| 2B-3 | (this commit) | Policy `calibration/external_tools_v1.yaml` (shared seed/timeout/memory + per-tool Mac venv paths + PROVISIONAL TRICERATOPS FPP bars) + registry entry + desk-driver wiring (post-runner evidence stages, expensive-gated) + `--external-tools` CLI flag + `docs/external-tools-mac-setup.md`. 10 tests. |

Test tally after 2B-3: 427 + 14 + 14 + 10 = **465** (460
offline + 5 live). Smoke tier green (194/194, after 2B-2).

### Tool research (2026-11-15 — read from the tools' own source, not the design doc's assumptions)

- **TRICERATOPS 1.1.0** (stevengiacalone/triceratops):
  `target(ID, sectors, ...)` queries TIC + a pixel cutout in
  `__init__` (network); `calc_depths(tdepth)` then
  `calc_probs(time, flux_0, flux_err_0, P_orb, ...)` where
  `time` is the PHASE-FOLDED light curve (days from transit
  midpoint) and flux is dilution-corrected. Results are
  attributes, not a return value: `FPP`, `NFPP`,
  `probs` (per-scenario DataFrame), `FPP_degenerate`.
  Seeding is via `np.random.seed()` — there is no seed
  parameter; the MC draws from the global generator. Pins
  numpy<2 / scipy<1.14 (Python < 3.13) against the
  pipeline's numpy==2.5.4 / scipy==1.18.1: the separate
  venv is mandatory, not precautionary. Validation bars in
  the literature: FPP < 0.015 + NFPP < 0.001 (Giacalone et
  al. 2021) — the C-10 doc's "FPP < 0.01" is a slight
  misremembering; the provisional policy uses 0.015 and says
  so.
- **LATTE 1.0.21** (noraeisner/LATTE, Eisner et al. 2020):
  GUI-first (`python3 -m LATTE`, tkinter), but batchable via
  `--targetlist=csv` with `TICID, period, t0, sectors, BLS,
  model, FFI` columns — with period+t0 it computes up to 4
  transit times itself and forces `--noshow --auto`.
  **It produces NO machine-readable per-check dispositions:
  output is plots + a PDF report**
  (`{indir}/{tic}/DV_report_{tic}.pdf`). The C-10 design
  doc's "per-check dispositions" assumption is wrong —
  confirmed from the source (the only CSV is an optional
  pyaneti model-parameters file). LATTE re-downloads its own
  data from MAST; it does NOT consume our stitched npz.
  Pins matplotlib==3.2.0 against the pipeline's 3.11.2.
  First run needs `_config.txt` (output path, in the package
  dir — an interactive prompt if missing) + a ~325 MB
  one-time MAST text-file download. It swallows per-target
  failures and exits 0 with no report — the wrapper must
  check for the PDF, never trust the exit code.

### Judgment calls (2B/2C — for the Phase 2 vote)

1. **Memory/IPC: BOTH subprocess isolation AND Mac-only by
   configuration.** The runner enforces a timeout (1800 s)
   and an RLIMIT_AS memory cap (2048 MB) on every tool
   invocation, and the tool venv paths in the policy point
   at the Mac. On a host without the venv (the VM) the run
   returns "missing_venv" and the stage reads UNMEASURED
   with a clear reason — never a crash. This answers
   Gemini's Phase 1.2 vote point and the design doc's open
   question 5 together.
2. **LATTE is report-only evidence, and can never PASS or
   FAIL.** With no machine-readable dispositions, a
   completed LATTE run reads INCONCLUSIVE ("report
   generated; a human must read it") and does NOT
   participate in promotion aggregation — including it
   would block every promotion, since it can never PASS.
   Its StageResult lives in the verdict record's extra
   evidence and the 2D evidence package. This deviates from
   C-10's LATTE mapping, because C-10's premise (per-check
   dispositions) does not exist in the tool.
3. **TRICERATOPS is evidence-only in this build; gating is
   the vote's call.** The adapter computes the policy-mapped
   status (PASS/FAIL/INCONCLUSIVE) from the provisional
   policy bars, so the evidence record shows what the policy
   WOULD say — but a provisional threshold must not kill a
   candidate, so the result does not gate promotion until
   the vote ratifies the thresholds. The vote also decides
   REQUIRED_STAGES membership.
4. **Neither tool joins REQUIRED_STAGES or the default
   STAGE_REGISTRY in this build.** Registering them would
   turn every existing e2e CANDIDATE into INCONCLUSIVE
   (unmeasured stages block promotion) and make LATTE a
   permanent promotion-blocker. The desk driver runs them
   as opt-in post-runner evidence stages when tool configs
   are supplied.
5. **LATTE needs Python 3.8 on the Mac — the main setup
   risk.** tessLATTE 1.0.21 still pins matplotlib==3.2.0
   and astropy<=4.0 (verified on PyPI 2026-11-15), which
   have no wheels past CPython 3.8. On the Apple Silicon
   Mac that means the Intel python.org 3.8 installer under
   Rosetta 2, or a pyenv 3.8 build. If 3.8 cannot be
   installed, the fallbacks are (a) relax the pins and
   verify LATTE still produces its report, or (b) drop
   LATTE — the in-repo checks already cover its
   diagnostics. TRICERATOPS 1.1.0 is safer (Python 3.11;
   numpy<2/scipy<1.14 have wheels through 3.12, pytransit /
   celerite are the unverified part). Both are documented
   in `docs/external-tools-mac-setup.md`, unverified until
   a Mac run.
6. **Tool results do NOT go in the verdict record.** The
   verdict schema has no slot for them (`extra` only
   carries the legacy per-stage fields), and the `stages`
   map is exactly the aggregated results — adding LATTE
   there would feed it to aggregate_verdict, which
   judgment call 2 forbids. Tool evidence lives in
   `desk_natives.json` (`extra_evidence.external_tools`)
   and the 2D evidence package. C-10's acceptance
   criterion 5 ("the verdict record carries the full
   evidence") is therefore satisfied by the evidence
   package + desk_natives.json, not by the verdict record
   itself; extending the verdict schema with an
   `external_tools` section is a vote item.

## 2C — TRICERATOPS (COMPLETE)

| Item | Commit | What |
|---|---|---|
| 2C-1 | (this commit) | TRICERATOPS adapter (`triceratops_result`, policy-mapped PASS/FAIL/INCONCLUSIVE, degenerate → UNMEASURED) + output schema + `gauntlet/tools/run_triceratops.py` wrapper (phase fold, `np.random.seed`, `target`/`calc_depths`/`calc_probs`, name-based scenario aggregation, probs CSV artifact). 17 tests (adapter + wrapper against a fake triceratops package, incl. seeded determinism). |
| 2C-2 | (this commit) | Driver wiring (`_TOOL_ADAPTERS` + `dilution_corrected` from the light-curve product: SPOC/TESS-SPOC PDCSAP true, QLP KSPSAP false). 1 driver test (both tools on a clean planet, policy-mapped under the real default policy). |

Test tally after 2C: 465 + 17 + 1 = **483** (478 offline +
5 live).

### Judgment calls (2C — for the Phase 2 vote)

1. **Degenerate FPP=1.0 is UNMEASURED, never FAIL.** The
   tool itself warns that a degenerate computation (all
   scenario log-evidences −inf) reports FPP=1.0 for a
   failed computation, not a confident false positive. The
   wrapper reports the run completed with
   `fpp_degenerate=true` (evidence preserved) and the
   adapter maps it to UNMEASURED + EXEC_ERROR.
2. **NFPP alone never refutes in v1.** A low FPP blocked
   by a high NFPP reads INCONCLUSIVE (grey zone): without
   a contrast curve NFPP is an upper bound, so failing on
   it would be aggressive. Whether NFPP > 0.1 should refute
   (the literature's "likely false positive" bar) is a vote
   item.
3. **Uncertainty is None in v1.** A single seeded run
   carries no Monte Carlo error bar (papers run 20× and
   report mean ± std). The seed makes a re-run
   reproducible; a repeat-run harness is future work.
4. **N=1,000,000 (the tool default).** No policy override
   in v1; the published cost (~5–15 min/target) stands.
5. **No nested timeout in the TRICERATOPS wrapper.**
   calc_probs is a blocking in-process call, so the
   runner's 1800 s timeout is the enforcement (unlike
   LATTE, which the wrapper kills itself 60 s early).

## 2D — Evidence package (COMPLETE)

| Item | Commit | What |
|---|---|---|
| 2D-1 | (this commit) | `gauntlet/evidence.py:build_evidence_package` + `schema/evidence-schema.json` (stage-result shape inlined from the standalone schema, the verdict schema's pattern) + `validate_evidence_package`. The driver writes `evidence_package.json` last (it hashes verdict_record.json + desk_natives.json) and carries the package on DeskResult. 7 builder tests + driver assertions in test_desk_external_tools.py. |

Test tally after 2D: 483 + 7 = **490** (485 offline +
5 live).

### Judgment calls (2D — for the Phase 2 vote)

1. **Stages come from the verdict record, not the runner.**
   build_verdict stamps the waiver reasons onto the results;
   the runner's objects are unstamped. The package copies
   the verdict's stages and reconstructs StageResult objects
   (from_dict) only to run check_report_ready.
2. **report_ready is the NARROW F-5 precondition.**
   check_report_ready only checks persistence + diffimg +
   blend and the second-eyes rule — an EB verdict with
   those three passing IS report_ready. The 2E gate refuses
   non-CANDIDATE verdicts on its own check; report_ready
   alone never files anything. (Two test expectations were
   corrected on this point during 2D — the code was right,
   the tests misread the contract.)
3. **Missing source files hash to null, visibly.** A
   package built without verdict_record.json /
   desk_natives.json on disk records sha256 null rather
   than raising — the gap is in the record, not hidden.
4. **The code fingerprint is computed live** at package
   build (provenance.fingerprint_result_affecting), not
   copied from anywhere — the verdict record carries no
   fingerprint field.

## 2E — Review gate (COMPLETE)

| Item | Commit | What |
|---|---|---|
| 2E-1 | (this commit) | `gauntlet/review.py` (prepare_filing_review + record_review_decision + review_2e_marker) + `schema/review-schema.json` + `validate_filing_review`. 14 tests, incl. the integration proof that an approved review unblocks check_report_ready for a waived candidate. |

Test tally after 2E: 490 + 14 = **504** (499 offline +
5 live).

### Judgment calls (2E — for the Phase 2 vote)

1. **The gate is enforced at DECISION time, not
   preparation.** prepare_filing_review builds a record
   for ANY package (eligible or not) with the blockers
   visible; record_review_decision refuses to APPROVE an
   ineligible record. Rejecting an ineligible record is
   allowed. A decided record is final.
2. **The review IS the F-5 second-eyes marker.** The gate
   checks the DATA part of check_report_ready
   (persistence/diffimg/blend pass) and does NOT require
   the package's report_ready flag — a waived CANDIDATE
   reads report_ready False until a review exists, and
   this review is what supplies it. review_2e_marker
   returns {"reviewer": approver} for an approved review.
3. **Checklist items are advisory.** The human's approve
   decision IS the attestation; per-item completion is
   not tracked (future work). Items with no backing
   evidence read not_applicable with the reason in their
   detail, never silently skipped.
4. **The review binds to its package by hash** (sha256 of
   the canonical package JSON) — a decision cannot be
   silently re-attached to different evidence.

## Deferred deliberately (not forgotten)

- **Tool lockfiles** (`requirements-latte.lock`,
  `requirements-triceratops.lock`): NOT built on the VM.
  Lockfiles with per-wheel hashes are platform-specific
  (macOS arm64 wheels differ from Linux x86_64), and
  LATTE's pins (matplotlib==3.2.0, astropy<=4.0) cannot
  even resolve under the VM's Python 3.12. They must be
  built on the Mac where the venvs live — the Mac setup
  doc (`docs/external-tools-mac-setup.md`) already
  instructs that step. C-10's "installs from its own
  lockfile in a clean venv" acceptance criterion is
  therefore a Mac-side check, not a VM one.

## Final verification (2026-11-15, after 2E)

- Full offline suite (`tests/run_golden.py --fast`): **499
  tests, PASS, expected failures=1** (the v1 xfail), 988.9 s.
  Total suite: **504** (499 offline + 5 live; the live
  modules run in live CI, not the PR gate).
- Tally correction: the per-release lines above originally
  read "N offline + 4 live" — the 2A live test
  (test_desk_live) makes it 5 live, so every offline count
  was one high. Totals were always right; the split is now
  corrected.
- Frozen v1 calibration files byte-identical to the
  baseline below (md5 verified 2026-11-15 after the final
  commit).
- Branch: `standardize/phase-2`, 12 commits on top of
  `standardize/phase-1` at 4acbc16. No push, no merge.
  Tree clean.

## Vote follow-up (P-items) — 2026-11-15

Branch rebased onto merged main f438a70 (mask-fix PR #2) with
one conflict (`calibration/registry.json` — kept BOTH the
bulk_v3 entry from main and the external_tools_v1 entry from
2B-3). Smoke green on the rebased tip before the build
(194/194). The vote was unanimous 3/3 GO WITH CHANGES; this
section closes the changes (brief:
`hidden_files/science-vet/phase2-vote/FOLLOWUP_BRIEF.md`).
Tie-breaks honored, not relitigated: NO external_tools
section in the verdict schema; F-8 uncertainty-aware, 0.30
bar pinned; LATTE REPORT_ONLY.

### P-1 — Pixel-check: population settled, null-star calibrated

- **Code reading (from `gauntlet/pixel_check.py`):** the 3σ
  brightening bar applies to the 3×3 aperture — **9 pixels**,
  never the whole 15×15 cutout. Claude's "~1 in 4 clean
  targets" is the correct arithmetic for 225 pixels
  (one-sided 3σ over 225: 26.2% family-wise) and does not
  apply to this code. For the 9-pixel population the nominal
  one-sided 3σ false-fail rate is 1.2%, and the Šidák 1%
  family-wise bar for 9 pixels is 3.06σ — the 3.0σ bar
  already in place. No bar change was needed.
- **Measured** (`tests/test_pixel_check.py::TestNullCalibration`,
  fixed seeds, 300 nulls each): 5/300 (1.7%) false-fails on
  clean targets with a real dip, 0/300 on pure-noise cubes —
  both consistent with the nominal 1.2%. The tests bound the
  rate at <5%: widening the tested set to the whole cutout
  would read ~26% and fail loudly.
- **Follow-up (not this build):** the synthetic rate assumes
  white noise; a null-star run on REAL TESS cutouts is still
  owed (real pixels share systematics).

### P-2 — Verdict invariance under pathological tool outcomes

- **Test** (`tests/test_desk_external_tools.py::
  TestVerdictInvariance`): the same clean-planet desk run,
  once with no tools (baseline) and once per TRICERATOPS
  mode — NaN FPP, FPP 1.5 (a tool FAIL), hang past the
  timeout, malformed output, crash. Final verdict AND the
  verdict record's stages (provenance stripped — run_id /
  timestamp differ by design) are identical in all six
  runs; `triceratops` never appears in the verdict's
  stages. The per-mode tool statuses are asserted too, so
  the test proves the modes exercised distinct adapter
  paths: NaN → inconclusive (grey zone — NaN fails both
  policy comparisons), FPP 1.5 → fail (refute bar), the
  three process failures → unmeasured + EXEC_ERROR.

### P-3 — RLIMIT_AS Linux-only, process-group kill, cap recorded

- **Guard:** `_memory_cap_preexec` now installs RLIMIT_AS
  only on Linux. macOS/XNU counts the whole virtual
  address space against it, so the 2048 MB cap would kill
  a healthy tool on the Mac (where the tools actually
  run). On macOS the cap is not applied and the run
  records `memory_cap_applied=False`; the timeout is the
  only guard there until an RSS watchdog exists (the
  vote's preferred direction — future work, a P-16 step
  when the Mac venvs exist to test it against).
- **Kill:** `run_external_tool` moved from `subprocess.run`
  to Popen + `start_new_session=True` + `os.killpg` on
  timeout — the wrapper's children die with it (LATTE
  shells out, TRICERATOPS forks workers). Tested with a
  spawner fake whose grandchild must be dead after the
  timeout, not orphaned.
- **Record:** `ToolRunResult.memory_cap_applied` (default
  False) says whether the cap was actually installed —
  False on macOS, with `memory_mb=0`, and when no process
  was spawned at all.

### P-4 — Raw evidence vs dispositions (TRICERATOPS)

- **Pure mapping:** `triceratops_disposition(fpp, nfpp,
  degenerate, policy)` in `gauntlet/stage_result.py` is
  the single source of truth for the status — no I/O, no
  global state. The adapter calls it; a policy-only edit
  re-derives the disposition from a stored raw record
  without re-running the tool. Tested: FPP 0.01 passes
  under the default bars (0.015) and is inconclusive
  under a stricter policy (0.005); NaN → inconclusive
  (grey zone); degenerate → unmeasured.
- **Policy version:** `StageResult.policy_version`
  (new field, in both the stage-result and verdict
  schemas) records which policy produced the
  disposition — "external_tools_v1" under the default
  profile. LATTE carries none: it has no disposition to
  version (report-only).
- **Limitation, recorded honestly:** TRICERATOPS fetches
  neighbour-star data and TRILEGAL simulations from
  remote catalogs inside the tool, so the wrapper cannot
  hash them — `input_hashes` cover only the files the
  pipeline handed the tool. Seed + tool_version +
  policy_version make the run reproducible in principle;
  a remote catalog change could move the number.

### P-5 — LATTE status REPORT_ONLY, not INCONCLUSIVE

- **New status:** `STATUS_REPORT_ONLY = "report_only"`
  joins the contract vocabulary (module docstring,
  `STATUSES`, and the status enum in all three schemas
  that inline the stage shape: stage-result, verdict,
  evidence — the evidence schema's `stages` and
  `external_tools` sections both). A completed LATTE run
  reads `report_only`: inconclusive means the stage
  measured and could not decide; here there was nothing
  to decide. It is never a pass, never a fail, never
  waivable (pinned by a test), and AGGREGATION-NEUTRAL —
  no `aggregate_verdict` branch matches it, so it could
  neither promote nor block if one ever entered
  aggregation (it never does; tool results live in extra
  evidence).
- **Test changes, stated:** the LATTE assertions in
  test_latte / test_desk_external_tools / test_evidence
  moved from "inconclusive" to "report_only" (the
  deliberate status change, not a weakening); the
  status×execution matrix gained
  `("report_only", EXEC_COMPLETED) → CANDIDATE`
  (10 legal combinations now, test renamed) and a
  report-only-cannot-be-waived pin.
- **Schema note:** the P-4 `policy_version` field also
  had to be added to the evidence schema's two inlined
  stage shapes — the first P-5 test run caught it
  (evidence-package validation rejected the field).

### P-6 — Review independence: reviewer ≠ preparer

- **Operator recorded:** `prepare_filing_review` takes
  `operator` (required, non-empty — usually Pingu, who
  ran the desk gauntlet); the record carries it, and the
  review schema requires it. A pre-P-6 record naming no
  operator cannot be approved (prepare a fresh review).
- **Approval refusals** (all `ValueError`, all approval-
  only — rejecting is the fail-safe direction and needs
  none of them): reviewer == operator (compared
  stripped + casefolded, so " Pingu " is Pingu); reviewer
  claims a known agent identity (denylist tripwire:
  pingu, muse, claude, gemini, chatgpt, gpt, copilot,
  bot, agent, ai, assistant, llm — exact match only, so
  no human name false-positives); approval without
  `reviewer_examined_evidence=True`.
- **Attestation recorded:** the decision carries
  `reviewer_examined_evidence` (schema-required boolean),
  so the record says whether the reviewer attested to
  examining the LATTE report, the TRICERATOPS numbers,
  and the waived stages.
- **Procedural, not authentication:** documented in the
  module docstring — the code checks the reviewer string,
  it cannot verify the human behind the keyboard. The
  approval call itself is the human attestation point;
  the denylist is a tripwire against the lazy failure,
  not a guarantee.

### P-7 — Evidence provenance: hash the actual artifacts

- **Package hashes the files** (`inputs.tool_artifacts`,
  new in the evidence schema): every path in the tool
  StageResults' `artifacts` lists — the LATTE report
  PDF, the TRICERATOPS probabilities CSV — hashed from
  the file bytes, sorted by (tool, path). A file that
  cannot be read hashes to null; the builder NEVER
  raises for a missing file (that stays the rule).
- **Null-hash block at the review gate:** `_eligibility`
  gains `source_hashes_present` (new in the review
  schema): both source files must hash non-null, AND
  every artifact the record cites must appear in
  `tool_artifacts` with a non-null hash — the coverage
  check also catches a pre-P-7 package that never hashed
  its artifacts. A null hash is a blocker, so
  `record_review_decision` refuses approval
  automatically (rejection still allowed). The driver
  already writes verdict_record.json + desk_natives.json
  before building the package, so real runs hash
  present.
- **Test fixtures now use real files:** the review
  tests' tool artifacts live in a module temp dir (the
  per-test tempdirs are deleted before the review is
  prepared), and `_tool_extra` takes override paths so
  the missing-artifact case is drivable.

### P-8 — Shape gate uncertainty-aware (F-8, vote tie-break)

- **Rule** (`shape_result`): a V-shaped point estimate
  FAILs ONLY when all four legs hold — V-shaped, `frac_err`
  known, 1σ upper bound `frac + frac_err < 0.30`, and
  `depth0_signif ≥ 5`. Any missing leg reads INCONCLUSIVE
  with the gap named in the reason. The 0.30 bar itself
  is UNCHANGED (the vote pinned it; do not nudge to
  0.29). The density flag is a separate physical argument
  and still FAILs unconditionally. The result now carries
  evidence: value = T23/T14, uncertainty = frac_err,
  threshold = the 0.30 V-shape (fail) bar.
- **T23 documented:** T23 is not fitted separately — the
  trapezoid fit's `frac` parameter IS T23/T14 (the model
  sets t23 = t14 * frac), so T23_d = t14 * frac is
  derived and frac_err is the fit's 1σ error on the
  fraction (None on a parameter bound, where the
  covariance is degenerate). Recorded in the gate's
  header comment + docstring and the adapter docstring.
- **Bar mirror:** the adapter carries
  `SHAPE_V_MAX_T23_T14 = 0.30` (it cannot import the
  gate's constant — rawflux_check imports lightkurve at
  module scope), pinned equal by a test; the gate
  constant is itself drift-tested against
  gauntlet_v1.yaml.
- **Measured on the labelled population** (harness re-run
  2026-11-15): TOI-700 c reads INCONCLUSIVE, not FAIL —
  frac 0.2925 ± 0.107, upper bound 0.40 above the bar,
  at 18.6σ dip significance (the SNR leg holds; the
  upper-bound leg does not). The EB still shape-FAILs —
  via the DENSITY flag (rho_circ/rho_star < 0.80), not
  the V-shape test, so P-8 leaves it untouched.
- **DELIBERATE baseline update** (stated in the commit):
  `tests/fixtures/toi_population/baseline.json` —
  planets any_fail 1 → 0, TOI-700 c shape fail →
  inconclusive; all_measured_pass stays 1 (inconclusive
  is not a pass). The meaning test in
  test_toi_population.py is updated to match.

### P-9 — diffimg offset with a sigma (F-9, vote item)

- **Rule** (`diffimg_native_for`): on-target when ALL of —
  offset/sigma < 3, offset < 1 px absolute cap, and the
  centroid sits closer to the target than to the
  neighbour. Sigma is the split-half centroid scatter
  from diffimg.py (radial, hypot(x_std, y_std)), floored
  at 0.1 px, with NO sqrt(n) reduction (conservative —
  the stack centroid's error would be smaller by
  ~sqrt(n), but we do not claim it). Scatter is usable
  only with n ≥ 2 halves and finite stds; otherwise the
  test falls back to the flat 1-px bar, flagged as
  sigma_source "flat_1px_fallback" — never a silent
  sigma. The native now carries offset_sigma_px,
  offset_over_sigma and sigma_source; the adapter
  records them as evidence (uncertainty = the scatter,
  threshold = the 1-px cap) and names the sigma in the
  reason.
- **The 0.06 px TIC 423498314 case still passes** under
  any scatter (0.06/0.1 = 0.6 sigma at the floor). The
  new kill a flat bar would miss: a 0.5 px offset on
  tight scatter (5 sigma) now reads off-target.
- **DEFERRED with reason:** the empirical calibration
  across the F-8 population + known BEBs needs live
  diffimg runs — a Mac/live-CI job, not a VM one
  (diffimg needs TESSCut TPUs from MAST + the WCS
  stack). The 3-sigma bar and the 0.1 px floor stay
  judgment calls until then.

### P-10 — Giacalone+2021 cited (vote item)

- The full citation is now in
  `calibration/external_tools_v1.yaml` as a
  machine-readable `citation` field under `triceratops:`
  plus a comment spelling out the paper's three
  criteria: Giacalone, S., Dressing, C. D., Jensen,
  E. L. N., et al. 2021, AJ, 161, 24, "Vetting of 384
  TESS Objects of Interest with TRICERATOPS and
  Statistical Validation of 12 Planet Candidates",
  doi:10.3847/1538-3881/abc6af, arXiv:2002.00691 —
  verified against the published abstract 2026-11-15.
  Validated: FPP < 0.015 and NFPP < 1e-3; likely
  planets: FPP < 0.5 and NFPP < 1e-3; likely nearby
  FPs: NFPP > 1e-1. The registry entry's sha256 +
  rationale were updated in the same commit (pre-merge
  correction under the F-1 exception; no threshold
  changed). The C-10 design doc's "FPP < 0.01" line was
  the same misremembering — corrected in the same
  commit, marked as such.

### P-11 — C-10 shipped as evidence plumbing, zero executions

- Stated plainly, so no reader mistakes the plumbing for
  a live integration: Phase 2's C-10 (TRICERATOPS /
  LATTE) shipped as **evidence plumbing with ZERO tool
  executions**. No TRICERATOPS run and no LATTE run has
  ever executed under this pipeline — on any host. The
  venvs do not exist yet (they must be built on the Mac
  per docs/external-tools-mac-setup.md), no golden tool
  test exists (a hard Phase 3 entry gate), and every
  tool stage in every run so far has read UNMEASURED
  (missing_venv). What C-10 built is the subprocess
  plumbing, the adapters, the policy, the evidence
  package fields, and the review-gate wiring — the
  machinery that will carry a tool result the day a
  venv exists. Until then the tools contribute nothing
  to any verdict, by design and by test (P-2 verdict
  invariance).

### P-12 — Real-data concordance test (vote item)

- **Harness:** scripts/concordance_replay.py replays the
  25 hand-vetted rescore-v2 S96 leads through the
  automated desk driver on live MAST data and compares
  each automated outcome to the manual verdict in
  tests/fixtures/concordance/manual_verdicts.json
  (transcribed from the 2026-11-14 gauntlet LEDGER:
  18 flagged-cadence artifacts, 4 single-event/weak
  dips, 1 catalogued planet, 1 era-confined V-shaped
  lead, 1 harmonic alias). Concordance = the driver
  kills the lead at one of the expected stages (the
  manual kill ground expressed as driver stages). The
  4 weak-dip leads accept a clean_refold, persistence
  or raw_flux kill — all three say "the clean-data
  signal is too weak / not persistent".
- **Expected mismatch:** TIC 307433122 (harmonic alias)
  is recorded, not asserted — no stage covers
  harmonic-alias grounds. In the subset run the driver
  killed it anyway (persistence + shape + odd_even),
  on different grounds than the manual verdict.
- **Live subset run in-session (2026-11-15, 5 leads,
  one per class, ~8 min): 4/5 agree, 0 disagree, 1
  mismatch-recorded.** 183537452 killed at catalogue
  (+ shape, odd_even); 355401152 at clean_refold (+
  persistence, odd_even); 101945781 at persistence +
  shape (+ odd_even); 41361938 at raw_flux +
  persistence (validating the weak-dip expected set).
- **Full 25-lead replay is a Mac/live-CI job** (~1-2 h
  of MAST downloads + BLS refines — not a VM job):
  tests/test_concordance_live.py runs it in live.yml
  (weekly + on merge, non-blocking), added to
  DOWNLOAD_TESTS. The offline fixture test
  (test_concordance.py, rest tier) pins the fixture
  itself — the 25 leads, the LEDGER tally, the
  ephemerides, the single expected mismatch — plus the
  compare rule, unit-tested. The deep-candidate leg is
  the existing F-8 population harness
  (scripts/toi_population.py, P-8).

### P-13 — Fault injection on the subprocess plumbing

- The fault matrix is now tested end to end
  (TestFaultInjection in test_external_tool.py) and
  documented as a table in run_external_tool's
  docstring: child crash → failed, hang → timeout
  (whole process group SIGKILLed, P-3), memory-cap
  breach → failed (MemoryError), OOM/signal kill →
  failed (returncode -9, proven with a self-SIGKILL
  fake — no real OOM is induced on the 1.5 GB VM),
  malformed output JSON → failed, exit 0 with no
  output → failed, non-object output JSON → failed,
  missing venv → missing_venv, missing wrapper →
  failed, spawn failure (venv broken mid-run — the
  python path exists but is not executable) → failed
  ("could not spawn"). Every mode is a status, never a
  raise and never a silent PASS. Stdout is never
  parsed: garbage on stdout with a valid output.json
  still completes, and garbage on stdout does not mask
  a malformed output.json. The crash / timeout /
  memory-cap / missing-venv / missing-wrapper /
  malformed-output modes were already covered in
  TestRunExternalTool; P-13 adds the signal kill, the
  two stdout modes, the spawn failure, and the
  non-object output (24 tests in the module, was 19).

### P-14 — Suite tiering documented (vote item)

- No code change to the tiers themselves: the F-10 tiers
  (smoke / golden / injection / rest / live) already
  exist and already cover the Phase 2 modules. P-14
  documents the placement in tests/run_golden.py's
  docstring: the verdict machinery (test_runner,
  test_runner_e2e, test_stage_contract) is smoke; the
  labelled-population harness (test_toi_population) is
  golden; the desk/tool/evidence/review modules
  (test_desk, test_desk_external_tools,
  test_external_tool, test_latte, test_triceratops,
  test_evidence, test_review, test_pixel_check,
  test_concordance) are rest; test_desk_live and
  test_concordance_live are live (DOWNLOAD_TESTS).
- **pytest-xdist is BLOCKED, recorded as such:** xdist is
  not in requirements.lock, and adding a dependency
  means a lockfile regeneration (pip-compile + hashes)
  plus a full suite re-run — out of scope for this
  build. The shards already parallelise in CI
  (golden.yml runs four jobs); the suite stays unittest
  + the shard split. The full suite (--fast) stays the
  required merge check for this branch.
- **Mac-nightly tools tier** (a P-16 step, not built
  here): the golden tool tests — real LATTE /
  TRICERATOPS runs on the labelled population — cannot
  run in CI (the venvs live on the Mac; LATTE needs
  Rosetta Python 3.8). When the venvs exist they run as
  a nightly Mac job, not a CI shard, and their results
  are recorded, not gated on.

### P-15 — TRICERATOPS phase-binning (vote item)

- The wrapper passed the FULL phase-folded curve (every
  cadence — tens of thousands of points) to calc_probs.
  It now bins the fold to ~200 bins (per-bin median
  flux, median phase as the bin centre) within a ±3-
  duration window around mid-transit; empty bins are
  dropped, so the count is approximate. flux_err stays
  the UNBINNED out-of-transit MAD scatter — conservative
  (binned fluxes have smaller errors, so the unbinned
  scalar overstates the noise and can only make the
  tool's fits more cautious, never more confident).
- metrics.n_fold_points records the number of input
  cadences inside the window (635 of 3888 in the test
  fixture); the schema gained the field (integer/null,
  required) and the adapter passes it through to the
  StageResult metrics. Failure records carry the count
  when the run reached binning, else null.
- TEST CHANGE, STATED: test_success_planet's fold
  assertions described the unbinned behaviour (span
  [-P/2, P/2], >1000 points) and are replaced by the
  binned ones (span ±3 durations, ≤200 points). The
  canned TRICERATOPS metrics in test_triceratops /
  test_desk_external_tools / test_evidence / test_review
  gained n_fold_points (1234 completed, null failed)
  for the new required schema field.

### P-16 — Mac-side venvs / lockfiles / golden tool tests

- **Mac-only step, recorded as blocked/unverified-live —
  nothing built.** Neither venv exists (LATTE Python 3.8
  under Rosetta, TRICERATOPS Python 3.11), no lockfile
  exists, no golden tool test exists, and zero tool
  executions have ever run (P-11). The status table is
  recorded in docs/external-tools-mac-setup.md (§Status),
  with the gates:
  - **LATTE venv: do NOT build until a candidate
    reaches review.** The Rosetta 3.8 setup is the main
    risk (3.8 may not install on current macOS at all)
    and there is no candidate to vet yet; the vote's
    fallback is to drop LATTE if setup proves
    impractical.
  - TRICERATOPS venv: build when a candidate reaches
    review (the lower-risk venv; build it first).
  - Lockfiles: built on the Mac AFTER a verified
    install (platform-specific hashes — the VM cannot
    build them).
  - Golden tool tests: a hard Phase 3 entry gate; when
    the venvs exist they run as a nightly Mac job
    (P-14), not in CI.
- The vote ratified the tools as evidence-only, but
  ratification is not a build order — the venvs are
  built when a candidate needs them, not before. The
  verification targets are fixed (WASP-29b + TIC
  308851365).

### P-17 — Phase 3 design-doc rule (vote item)

- **Rule for every Phase 3 design doc (and any later
  one): every external fact carries a citation, and
  every external dependency gets a spike before the
  design is accepted.** An external fact is any claim
  about something outside this repo — a paper's result
  or threshold, a tool's behaviour or output format, a
  catalog's contents. Its citation is the paper (journal
  + DOI/arXiv) or the source (package + version +
  date read). A spike is a small verification run
  against the real thing — install the tool, read its
  source, run the minimal example — that proves the
  premise the design rests on, recorded with its
  outcome. A design whose premises are unspiked is a
  draft, not a decision.
- **Motivation — the two C-10 failures:** (a) LATTE was
  designed as a per-check disposition source; the
  premise was wrong — LATTE emits plots + a PDF, no
  machine-readable dispositions (verified against the
  1.0.21 source during the build, after the design was
  written). A spike (read the source / run it once)
  would have caught it before the design existed.
  (b) The Giacalone validation bar was misremembered as
  FPP < 0.01; the paper says 0.015 (P-10). A citation
  checked against the abstract would have caught it.
  Both failures cost build time and one shipped a wrong
  premise into a design doc — the rule exists so Phase 3
  does not repeat them.

### P-18 — desk-natives schema (vote item)

- **`schema/desk-natives-schema.json` is the formal
  contract for `desk_natives.json`, the Phase 3 feature
  list.** Phase 3 reads features from the natives, so
  their shapes are pinned here. Self-contained (no
  cross-file $refs — `validation.py` loads schemas
  singly). Every native key is optional (a stage that
  never ran writes no native); every value shape is
  pinned. Arrays appear as `_jsonable` summaries
  (`{__array__, shape, dtype, sha256}`), never embedded
  data.
- **The driver validates before writing either record.**
  `run_desk_gauntlet` builds the payload, serialises it
  through `_jsonable` (so validation sees exactly the
  record as written — `run.skipped` holds (stage,
  reason) tuples until then), and `validate_desk_natives`
  raises on failure. A malformed record is a code bug,
  not a data failure, so no malformed record is ever
  written.
- **Two real shapes the excavation got wrong, caught by
  the desk tests:** (a) `run.skipped` is a list of
  [stage, reason] pairs, not strings. (b) `flagged_fold`
  has NO `quality_mask` — `_flagged_fold` returns the
  clean_fold shape minus the mask, despite its docstring
  claiming the clean_fold shape; the schema pins a
  separate `flaggedFold` def, and a test pins the
  omission (if the code ever adds the mask, the schema
  must change with it). The `external_tools` StageResult
  values pin only stage + status — the full shape is
  `stage_result-schema.json`, enforced at the adapter.
- **Shape native:** only `method` is required — early
  exits return a subset, and the density fields are
  null/absent without a TIC density. Persistence's
  verdict is absent when `n_usable` is 0. Holdout is a
  string sentinel or the `holdout_test` dict.
- Tests: 7 new in `tests/test_schema.py`
  (TestDeskNativesValidation); the 31 desk driver tests
  prove real payloads validate (14 → 4 → 0 errors as
  the schema was corrected against them).

## Frozen v1 calibration (verify at the end)

Baseline md5 (2026-11-15, before any Phase 2 commit):

- `calibration/bulk_v1.yaml`: d1778465edab35e509dd27ea1e14dd63
- `calibration/deep_v1.yaml`: ac2e385726ccd10c1fca6122fa05a6a8
- `calibration/gauntlet_v1.yaml`: 348f98b347c2f08042d0bfb54f16d04b
