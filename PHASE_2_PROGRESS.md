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

## Frozen v1 calibration (verify at the end)

Baseline md5 (2026-11-15, before any Phase 2 commit):

- `calibration/bulk_v1.yaml`: d1778465edab35e509dd27ea1e14dd63
- `calibration/deep_v1.yaml`: ac2e385726ccd10c1fca6122fa05a6a8
- `calibration/gauntlet_v1.yaml`: 348f98b347c2f08042d0bfb54f16d04b
