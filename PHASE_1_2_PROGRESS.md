# Phase 1.2 progress

Release A (unblocks Phase 2) — brief v2, `~/workspace/goals/exoplanet-hunter/hidden_files/science-vet/phase1-1-vote/PHASE1_2_AGENT_BRIEF.md`.
Started 2026-11-14 ~12:21 IST on branch `standardize/phase-1` (HEAD `c630327` at start, tree clean).

Note: v1-spec commits `c630327` (runner) and `e1baef2` (contract) to review against the v2 brief — rework in new commits where they diverge. Never amend or rebase.

## Release A

- [x] A-1 Calibration hash enforcement (registry) — `5c7a26d`
- [x] A-2 Provenance layer 2 — `c0364ad` (166-test fast suite green, 585.6 s, before the bare-version map correction; 123-test affected subset green after it)
- [x] A-3 Resume hash-mismatch refusal — `b86a159`
- [x] A-4 StageResult contract v1 (allowlist + gauntlet_v2) — `acf27d2`
- [x] A-5 Stage runner (DAG + cheap-always) — `0811701`
- [x] A-6 Blend pure function + fixture — `76041cc`
- [x] A-7 Conservation check — `fcf167e`

## Release B

Started 2026-11-14 ~13:50 IST on branch `standardize/phase-1` (HEAD `34bf313` at start, tree clean). NO PUSH per Dev's 2026-11-14 rule: nothing pushes until the work is completely finished and ready to publish — local commits only.

- [x] B-1 Mirror deprecation — `35f2639` (injection smoke tests 3/3 PASS, 275.7 s)
- [x] B-2 MAD clip → bulk_v2 — pre-registration `8bdf693`; shared clip `d0012c7`; screen wiring `3203f63`; grid `c113a42` (300 runs, 135 s; floor_10pct by pre-registered tiebreak); profile `ffa04de`; sensitivity map `0dd9aa0`; CI clip-grid test `994075f`; rescore tool `a936d77`; EB behaviour pin `49d6958`; v1-gate tests `d5a0599`

## Release C

Started 2026-11-14 ~14:47 IST on branch `standardize/phase-1` (HEAD `d8b4be8` at start, tree clean). NO PUSH per Dev's 2026-11-14 rule: nothing pushes until the work is completely finished and ready to publish — local commits only.

- [x] C-1 Network timeouts + watchdog — `netbound.py` (daemon-thread watchdog + http_get + download_file); hunter self-heal per-attempt timeout (cone query 60 s); bulk screen urlretrieve→timeout'd streaming download, astroquery calls watched, per-star watchdog in the screen loop (`unmeasured` status, conserved); gauntlet fetchers watched
- [x] C-2 Crash-boundary + idempotency — `provenance.work_item_id` (TIC + sector + code fingerprint + calibration hash + recipe hash, no input hash); stamped on every screen record (schema: `work_item_id` + `unmeasured` status); checkpoint records + verifies output hashes (summary-match + output-mismatch forces re-screen; stale summary lets chunk_ok decide); stub `--die-at` crash points; merge idempotency tested
- [x] C-3 Ledger durability — `bulk/build_ledger.py --sector N --run-dir DIR --out FILE [--rescore DIR]` (counts + survivor TICs/tiers + calibration + known defects + fingerprint components + conservation; deterministic except generated_at; rescore merge marks superseded_by bulk_v2 + adds new v2 survivors; legacy 1.1 string calibration normalised; sector mismatch / missing summary refused)
- [x] C-4 Fixture-vs-live BLS-input hash diff — root cause FOUND + FIXED: live flux is float32 (FITS) vs fixture float64, and savgol accumulates in the input dtype (~4e-7 trend difference → BLS argmax flips one grid step → pass-2 mask diverges → hash differs). `_run_pipeline` now normalises lc_raw to float64 (exact upcast); `test_eb_fixture_live_bls_inputs_identical` pins hash equality + period agreement + stable shape bounds; `scripts/diff_fixture_live.py` for ad-hoc diffs. C-1 follow-up in the same commit: the last two unwatched MAST calls (`rawflux_check.download_author` row download, `rawflux_check.tic_density` TIC query) are now watched.
- [x] C-5 Live CI opens issue on failure — `.github/workflows/live.yml`: test step gains `id: live`; new step `if: steps.live.outcome == 'failure'` opens a deduped issue via `gh` (permissions `issues: write`); body links the run + commit and points at the fixture-vs-pipeline diagnosis. YAML verified by parsing; live behaviour UNVERIFIED (no push allowed).
- [x] C-6 Mutation canaries — `scripts/mutation_canaries.py` (throwaway-copy only; exit 1 if any canary stays green). All three executable canaries go RED: chi2-floor (3 failures), mad-clip-floor, clean-refold-gate. The 180″ neighbour rule has NO executable target (prose only in `docs/vetting-manual.md:148`; code census defaults to 60″) — the canary verifies that finding and reports NEEDS-UPDATE if a code target ever appears; changing the 60″ default is a science decision flagged for the vote. Gap found + closed: the gauntlet clip floor was guarded only by a constant assertion — `tests/test_gauntlet_clip.py` now pins the behaviour (6% eclipse on a 0.08%-MAD star survives; 50% glitches still clipped; fails with floor 0.0).
- [x] C-7 Expected-values file — `tests/expected_values.json` (golden-star acceptance numbers, pretty-printed for reviewable diffs) + `tests/expected_values.py` loader; `tests/golden_checks.py` reads through it (numbers moved verbatim, rationale stays in the docstrings); `scripts/check_expected_values.py --base <ref>` diffs the file + lists changed `calibration/` files, prints a plain-words summary + `::warning::` annotations, exits 0 (flag, don't block); CI step in `golden.yml` after the registry check. 9/9 fixture + expected-values tests OK.
- [x] C-8 Run fingerprint — `provenance.run_fingerprint_components` / `run_fingerprint` (full: code SHA + dirty flag + calibration hash + recipe hash + window hash + env hash + input IDs) / `resume_fingerprint` (comparable subset excluding git SHA + dirty flag) / `env_hash` (Python + requirements.lock); stamped in manifests (`fingerprint` block: full + resume + components) and checkpoints; resume compares the resume subset with fallback to code_fingerprint for pre-C-8 checkpoints (fail-closed when neither exists); `build_ledger.py` records the full block when the manifest carries it. 9/9 new tests OK (determinism, per-component sensitivity, git-SHA/dirty move full-not-resume, tampered-resume refusal + accept-flag path).
- [x] C-9 Lockfile clean-install test — manifest bug FIXED: `build_manifest` read `requirements-lock.txt` (does not exist), so `requirements_lock_sha256` was always None; now reads `requirements.lock` (test asserts it equals the file hash). New `lockfile-clean-install` job in `golden.yml` (fresh venv, `pip install --require-hashes -r requirements.lock`, no pip cache, smoke: import hunter/bulk_screen/provenance + test_recipe + test_stamp). PROVEN locally: clean install of all 93 packages succeeded with hash verification (pip exit 0, 114 s) + smoke 21/21 OK in the clean venv.
- [x] C-10 TRICERATOPS/LATTE design doc — `docs/triceratops-latte-design.md` (doc only, no code): out-of-process, own venv + lockfile each, JSON in/out through StageResult, seeded Monte Carlo, failure → unmeasured, never on bulk-screen volume (gauntlet finalists only); full input/output JSON contract + StageResult evidence mapping (value=FPP, metrics carry FPP/NFPP + per-scenario probabilities + seed); determinism rules; cost model; acceptance criteria; 5 open questions for the Phase 2 vote; rollout 2B LATTE → 2C TRICERATOPS.

## Phase 1.2 follow-up

Started 2026-11-14 ~16:45 IST on branch `standardize/phase-1` (HEAD `0d2f351` at start, tree clean). The Phase 1.2 vote was unanimous 3/3 GO WITH CHANGES; this build closes the changes (brief: `~/workspace/goals/exoplanet-hunter/hidden_files/science-vet/phase1-2-vote/FOLLOWUP_BRIEF.md`; comparison: `.../phase1-2-vote/COMPARISON.md`). NOT a new phase (ChatGPT: no Phase 1.3) — targeted fixes only. NO PUSH per Dev's rule — local commits only. Out of scope (operator-only): Mac-side ledgers/rescore/run-data copy; git/GitHub steps (scratch-repo workflow runs, branch protection, firing the forced-failure input).

- [x] F-1 180″ neighbour search — policy parameter `neighbour_search_radius_arcsec: 180.0` in gauntlet_v2 (pre-merge correction: gauntlet_v2 never reached main, so the profile AND its registry entry were updated in the same commit — new sha256 + rationale noting the correction — rather than minting a v3; rule documented in `calibration/README.md`); `tic_cone_census` defaults to the policy radius; census logic factored into pure `census_from_rows` (radius filter now enforced in the pure function, so unfiltered rows are still radius-limited); census JSON renamed to `tic_cone_search` + explicit `radius_arcsec` (old `tic_cone_60arcsec` key accepted as a deprecated 60″ fallback with a warning); `check_blend` records `census_radius_arcsec` in every blend verdict; offline S97 census fixture (host at 66.5″ found at 180″, missed at 60″); no-false-kill run on TOI-700 + WASP-126 b (dip-free neighbour leaves the verdict on_target); 180″ canary converted from a no-target check into a real executable canary (mutates the policy value 180→60, re-hashes the registry in the throwaway copy, tests.test_census goes red)
- [x] F-2 Fast suite under bulk_v2 at HEAD — re-run 2026-11-14: **313/313 PASS** in 916.959 s (wall 15m29s) under `EXHUNT_BULK_CALIBRATION=bulk_v2` (skipped=1 — the pre-existing env-override skip in test_calibration.py; expected failures=1 — the v1 xfail). The Release B ledger row (245 tests) predated C; HEAD fast is 313 (300 at C + 13 F-1 census tests). No finding — the suite is green under bulk_v2 at HEAD.
- [x] F-3 live.yml forced-failure input — `workflow_dispatch` input `force_failure` (boolean, default false) added; when true, the live step exits 1 before running the suite, so the issue-opening step (gated on `steps.live.outcome == 'failure'`) can be proven on first push. `permissions: issues: write` unchanged. YAML-parse verified locally; the issue step itself is UNVERIFIED-LIVE until the operator fires it once after the first push and confirms the issue opens (then closes it). Firing it is out of scope for this build (no git/GitHub steps).
- [ ] F-4 Shared float64 ingest
- [ ] F-5 Waiver hardening
- [ ] F-6 Resume fingerprint proof tests
- [ ] F-7 End-to-end runner integration test
- [ ] F-8 Labelled-population TOI run
- [ ] F-9 Fingerprint-coverage test
- [ ] F-10 Tiered suite
- [ ] F-11 transit_fit via the shared clip
- [ ] F-12 Perturbation test for near-tie verdict stability
- [ ] F-13 Hollow denominators
- [ ] F-14 Same-product-selected test
- [ ] F-15 run_chunked v1-gate
- [ ] F-16 TargetContext cache verification
- [ ] F-17 Repeated-timeout stress test

## Claims ledger (Release A)

| Claim | Command | Expected | Actual |
|---|---|---|---|
| Golden suite green (102 + N new) | `~/workspace/exoplanet-hunter/.venv/bin/python tests/run_golden.py` | `OK, GOLDEN SUITE: PASS` | `Ran 223 tests in 662.943s — OK — GOLDEN SUITE: PASS (223 test(s))`, wall 11m14s, exit 0 (2026-11-14) |
| v1 calibration files byte-identical | `git diff 80832ac HEAD -- calibration/*_v1.yaml` | no diff | IDENTICAL (bulk_v1, deep_v1, gauntlet_v1) |
| Registry check passes | `python scripts/check_registry.py` | `registry check OK` | `registry check OK` (append-only diff skips with a warning: origin/main predates the registry) |
| No run-data writes since Phase 1.1 base | `git log 80832ac..HEAD -- vetting_results bulk/run_* bulk/cache sweep-output results data` | empty | empty |
| A-6 fixture verdicts blend | `python -m unittest tests.test_blend` | blend @ ~44x | blend, ratio 45.5x, target 22.1σ, neighbour 634.8σ |
| A-7 lost survivor fails the run | `python -m unittest tests.test_conservation` | exit 1, `CONSERVATION FAILED` | exit 1, manifest status `failed` (12/12 conservation tests pass) |

## Claims ledger (Release B)

| Claim | Command | Expected | Actual |
|---|---|---|---|
| Golden suite green (223 + 30 new) | `~/workspace/exoplanet-hunter/.venv/bin/python tests/run_golden.py` | `OK, GOLDEN SUITE: PASS` | `Ran 253 tests in 675.625s — OK (expected failures=1) — GOLDEN SUITE: PASS (253 test(s))`, wall 11m25s, exit 0 (2026-11-14) |
| Fast suite green under bulk_v2 | `EXHUNT_BULK_CALIBRATION=bulk_v2 ~/workspace/exoplanet-hunter/.venv/bin/python tests/run_golden.py --fast` | `OK, GOLDEN SUITE: PASS` | `Ran 245 tests in 485.020s — OK (skipped=1, expected failures=1) — GOLDEN SUITE: PASS (245 test(s))`, wall 8m14s, exit 0 (2026-11-14, Release B). **Re-run at HEAD (follow-up F-2): `Ran 313 tests in 916.959s — OK (skipped=1, expected failures=1) — GOLDEN SUITE: PASS (313 test(s))`, wall 15m29s, exit 0 (2026-11-14).** The 245 row predated C (HEAD fast was 300 at C, +13 F-1 census tests = 313); the skip is the pre-existing env-override skip in test_calibration.py. |
| v1 calibration files byte-identical | `git diff 80832ac HEAD -- calibration/*_v1.yaml` | no diff | IDENTICAL (bulk_v1, deep_v1, gauntlet_v1) |
| Registry check passes | `python scripts/check_registry.py` | `registry check OK` | `registry check OK` (append-only diff skips with a warning: origin/main predates the registry) |
| No run-data writes since Phase 1.1 base | `git diff --name-only 80832ac HEAD`, filtered to run-data dirs | none | none (56 files changed, none under `vetting_results/` / `bulk/cache/` / `bulk/run_*` dirs / `sweep-output/` / `results/` / `data/`; note: the Release A ledger's `bulk/run_*` pathspec also matches the code file `bulk/run_chunked.py`, so the check is done on the file list) |
| Grid green under v2 / strict-xfail under v1 | `python -m unittest tests.test_clip_grid` | OK (expected failures=1) | OK (expected failures=1), 3 tests, 4.1 s |
| --allow-v1 gate tested | `python -m unittest tests.test_calibration.TestV1Gate` | OK | OK, 5 tests |
| Mirror gone, injection tests use the real pipeline | `python -m unittest tests.test_injection` | OK | OK, 3 tests, 275.7 s |
| Rescore tool tested on synthetic data | `python -m unittest tests.test_rescore_v2` | OK | OK, 3 tests — the 3.0%-on-0.3%-noise transit v1 missed (SDE 5.4) is recovered under v2 |

## Claims ledger (Release C)

| Claim | Command | Expected | Actual |
|---|---|---|---|
| Golden suite green (253 + 51 new) | `~/workspace/exoplanet-hunter/.venv/bin/python tests/run_golden.py` | `OK, GOLDEN SUITE: PASS` | `Ran 304 tests in 911.868s — OK (expected failures=1) — GOLDEN SUITE: PASS (304 test(s))`, wall 15m22s, exit 0 (2026-11-14). New tests: test_net 11, test_idempotency 12, test_build_ledger 8, test_expected_values 6, test_run_fingerprint 10, test_gauntlet_clip 2, C-4 diff test 1, conservation +1 (C-1 unmeasured status) |
| Fast suite green | `~/workspace/exoplanet-hunter/.venv/bin/python tests/run_golden.py --fast` | `OK, GOLDEN SUITE: PASS` | `Ran 300 tests in 888.344s — OK (expected failures=1) — GOLDEN SUITE: PASS (300 test(s))` (ran concurrently with the C-9 pip install, hence slower than usual) |
| v1 calibration files byte-identical | `git diff 80832ac HEAD -- calibration/*_v1.yaml` | no diff | IDENTICAL (bulk_v1, deep_v1, gauntlet_v1) |
| bulk_v2 untouched since Release B | `git diff d8b4be8 HEAD -- calibration/bulk_v2.yaml` | no diff | IDENTICAL |
| Registry check passes | `python scripts/check_registry.py` | `registry check OK` | `registry check OK` (append-only diff skips with a warning: origin/main unresolvable in this clone) |
| No run-data writes since Phase 1.1 base | `git diff --name-only 80832ac HEAD`, filtered to run-data dirs | none | none (31 files changed in Release C, none under `vetting_results/` / `bulk/cache/` / `bulk/run_*` / `sweep-output/` / `results/` / `data/`) |
| C-1 network timeouts | `python -m unittest tests.test_net` | OK | OK, 11 tests, all offline |
| C-2 crash-boundary + idempotency | `python -m unittest tests.test_idempotency` | OK | OK, 12 tests, 21.1 s; stub kill-points verified (die before/after survivors, after hits) |
| C-3 ledger builder | `python -m unittest tests.test_build_ledger` | OK | OK, 8 tests; deterministic except `generated_at`; `--rescore` merge tested on synthetic data |
| C-4 fixture-vs-live BLS-input hash | `python -m unittest tests.test_golden_stars` (live) | OK | OK — live + fixture golden suites 7/7 in 380.059 s; float32/float64 savgol root cause found and fixed (float64 normalisation in `_run_pipeline`) |
| C-5 live-CI issue step | YAML parse of `.github/workflows/live.yml` | parses | parses; **live behaviour UNVERIFIED** (cannot be exercised without pushing) |
| C-6 mutation canaries | `python scripts/mutation_canaries.py` | exit 0, every canary red | exit 0 — chi2-floor, mad-clip-floor, clean-refold-gate all go RED; 180″ rule has NO code target (prose only, code defaults to 60″) — verified on every run |
| C-7 expected-values file + CI flag | `python -m unittest tests.test_expected_values` + temp-edit warning check | OK; warning, exit 0 | 6/6 OK; temp edit 8.5 → 9.9 produced `::warning::expected value changed: stars.150428135.headline_sde_min: 8.5 -> 9.9`, exit 0, reverted clean |
| C-8 run fingerprint | `python -m unittest tests.test_run_fingerprint` | OK | OK, 10 tests (9 fingerprint + 1 C-9 lockfile-hash test); tampered-resume refusal + `--accept-code-change` path verified via the stub driver |
| C-9 lockfile clean install | fresh venv `pip install --require-hashes -r requirements.lock` + smoke | pip exit 0; smoke OK | 93 packages installed with hash verification, pip exit 0, 114 s; smoke (import hunter/bulk_screen/provenance + test_recipe + test_stamp) 21/21 OK in the clean venv; throwaway venv deleted |
| C-10 TRICERATOPS/LATTE design | `docs/triceratops-latte-design.md` exists, doc only | exists | 17,417 B, doc only — no code, no new dependency |

## Claims ledger (Phase 1.2 follow-up)

| Claim | Command | Expected | Actual |
|---|---|---|---|
| F-1 census finds the 66.5″ host at 180″, misses at 60″ | `python -m unittest tests.test_census` | OK | OK, 13 tests, 112.0 s (incl. the no-false-kill run on TOI-700 + WASP-126 b) |
| F-1 180″ canary goes red | `python scripts/mutation_canaries.py --canary neighbour-180arcsec` | RED | RED — 6 failures under the 180→60 policy mutation (registry re-hashed in the throwaway copy, so the failure is the value change, not a hash mismatch) |
| F-1 registry still verifies after the pre-merge gauntlet_v2 edit | `python scripts/check_registry.py` | `registry check OK` | `registry check OK` (append-only diff skips with a warning: origin/main predates the registry) |
| F-2 fast suite green under bulk_v2 at HEAD | `EXHUNT_BULK_CALIBRATION=bulk_v2 ~/workspace/exoplanet-hunter/.venv/bin/python tests/run_golden.py --fast` | `OK, GOLDEN SUITE: PASS` | `Ran 313 tests in 916.959s — OK (skipped=1, expected failures=1) — GOLDEN SUITE: PASS (313 test(s))`, wall 15m29s, exit 0 (2026-11-14). Skip = pre-existing env-override skip in test_calibration.py; expected failure = the v1 xfail. |
| F-3 forced-failure input | YAML parse of `.github/workflows/live.yml` | parses; input present; permissions unchanged | parses; `force_failure` boolean, default false; live step exits 1 when true; `permissions: issues: write` unchanged; issue step still gated on `steps.live.outcome == 'failure'`. **Live behaviour UNVERIFIED** (firing it needs a push — out of scope). |

## Judgment calls for the vote

- **A-4 waivers "in the policy":** the brief says stages block "unless the decision policy waives them explicitly (per-stage, in the policy, with a reason)". A literal reading (waivers listed in `gauntlet_v2.yaml` per target) is unworkable — the registry forbids editing the policy per target. Implemented as: the policy's `waivers` map is the ALLOWLIST (which stages may be waived + grounds); each run applies waivers with per-target reasons; the verdict record carries them. Allowlist is deliberately small (holdout, clean_refold, pixel_check — structural non-applicability only). UNMEASURED/FAIL never waivable.
- **A-5 raw_flux kept as a required stage:** the brief's DAG table omits it, but it is a load-bearing gate (S97 TIC 344334378 was RAW-REFUTED; hard REFUTED vs shape's INCONCLUSIVE) and the brief never orders its removal; the table's persistence "RAW verdict" is a different per-sector test. Documented in `REQUIRED_STAGES`.
- **A-6 fixture is synthetic:** no real TIC 139526205 light curve is on disk (S97 run data is on the Mac). The fixture is box transits at the real ephemeris with the real depths; the verdict (blend) is the real case's. Documented in `tests/fixtures/blend/README.md` + `case.json`.
- **B-1 `fetch_substrate` left alone:** its verbatim copy of the search step inside `hunter._fetch_stitched` duplicates a search, not detrend/BLS scoring — out of B-1's stated scope (the mirror was the duplicate BLS/detrend logic). Grep confirmed the mirror was the only duplicate BLS/detrend logic in the repo.
- **B-2 tiebreak picked `floor_10pct`:** `upward_only`, `isolated_low_only` and `floor_10pct` tied exactly on every pre-registered criterion (16/16 deep-quiet recovery, 0/12 null false alarms, 0 monotonicity violations); the pre-registered tiebreak prefers `floor_10pct` (already in production use in the gauntlet). Its grid numbers are identical to the unclipped reference.
- **B-2 EB period preference:** the clip fix changes which period BLS prefers for deep EBs (true period instead of half-period), so the odd/even veto no longer fires on the 3 d fixture under v2 — pinned as known behaviour (`test_deep_eb_found_at_true_period_under_v2`), veto test moved to a 12 d fixture (true period 24 d, out of range). All three fix options share it — not a selection issue. Documented in `bulk/SENSITIVITY_MAP.md`.
- **B-2 rescore writes survivors only:** the JSONL mirrors `survivors.jsonl` semantics (gauntlet input shape); counts for everything else live in `summary.json`. The ledger merge is C-3's job — the tool never writes into a run directory.
- **B-2 gate lives only in `bulk_screen.main`:** `run_chunked` does not enforce it (its resume tests use fake sector 999 with the stub); a real v1 run on a new sector fails at slice 0 before any screening.
- **B-2 test changes, said in their commits:** `test_bulk_screen_loads_the_profile` is env-aware now (the `EXHUNT_BULK_CALIBRATION` override is a deliberate behaviour change; a new test pins the default to v1); the odd/even EB fixture moved 3 d → 12 d (mechanism in commit `49d6958` + `SENSITIVITY_MAP.md`). No assertion was weakened to get green.
- **C-3 rescore merge lives in build_ledger, not rescore_v2.py:** brief §6 D-2 says "the re-score tool writes superseded_by" — but the B-2 rescore tool's own boundary forbids it writing outside its --out dir, and its docstring explicitly defers the ledger merge to C-3. Implemented as `build_ledger.py --rescore <dir>` (re-scored entries gain superseded_by bulk_v2; new v2-only survivors are added as entries). Same outcome, owned by the tool that owns the ledger.
- **C-4 the fixture/live divergence was real, and it was NOT stale data:** the first run of the new diff test failed (hashes differed). Diagnosis: raw arrays bit-identical; the live flux is float32 (FITS) while the fixture stores float64, and scipy's savgol accumulates in the input dtype — pass-1 trends differed ~4e-7, flipping the BLS argmax one grid step on a near-tie (P 0.758011 vs 0.757982), which diverged the pass-2 mask and the hash. Fixed by normalising lc_raw to float64 in `_run_pipeline` (exact upcast; nothing downstream uses lc_raw beyond time/flux/len/flatten). The T23/T14 instability (0.297 vs 0.474) is the same argmax-noise mechanism, now with its trigger identified. NOT fixed: `_fetch_flattened`/`_fetch_stitched` (gauntlet fetch paths) have no fixture seam, so the same dtype sensitivity is unpinned there — noted, out of scope.
- **C-5 live behaviour is UNVERIFIED:** the issue step cannot be exercised without pushing (forbidden). YAML parses; the `steps.live.outcome` gate is the documented pattern for a `continue-on-error` step. First live failure after the branch lands will prove it.
- **C-6 the 180″ bet was confirmed in the strongest form:** Claude bet the 180″→60″ canary would not go red — there is no 180 to mutate at all (prose only; code defaults to 60″). Changing the default is a science/behaviour change to diffimg (census size, exclusion arithmetic, the `tic_cone_60arcsec` schema name) needing a calibration decision — flagged for the vote, not done here. The canary script re-verifies the no-target finding on every run.
- **C-6 gap found + closed in the same item:** the mad-clip canary first went red only via the constant-equality test — no behavioural test pinned what the gauntlet clip floor does. `tests/test_gauntlet_clip.py` now pins it (deep transit survives, glitches clipped, fails with floor 0.0). The transit_fit use of the same constant is still guarded only by the constant test; a behavioural test there needs a full fit run and is left as follow-up.
- **C-8 resume compares the resume subset, not the full fingerprint:** the full fingerprint includes the git SHA and the dirty flag for audit, but a docs-only commit or a stray untracked file must not refuse a legitimate resume — exactly the A-3 problem the code fingerprint solved. Pre-C-8 checkpoints fall back to code_fingerprint; pre-A-3 (neither) stay fail-closed.
- **C-2 vs A-7 interaction (found during C-8 verification):** the A-7 conservation test's premise — "the checkpoint only hashes summary.json, so a tampered slice is trusted" — is no longer true by design: C-2's output hashes heal the injected corruption by re-screening the slice, so the run exited 0. The test now forges a *consistent* checkpoint (recomputes the entry's survivors_sha256 over the tampered file), modelling corruption that predates checkpointing — the case only conservation can catch. Same assertions (exit 1, CONSERVATION FAILED, buckets, manifest failed); the test is stronger, not weaker.

## Judgment calls (Phase 1.2 follow-up)

- **F-1 pre-merge gauntlet_v2 edit:** the brief permits exactly one calibration edit (F-1) because gauntlet_v2 never reached main and never stamped a run. The profile AND its registry entry changed in the same commit (new sha256 + rationale noting the correction); the exception is documented in `calibration/README.md` as applying only to unmerged profiles. v1 profiles stay byte-frozen; bulk_v2 untouched.
- **F-1 census radius filter in the pure function:** `census_from_rows` enforces the radius itself (the old code relied on the MAST cone query to limit rows). The offline fixture test is therefore faithful: rows outside the radius are excluded by the census logic, not by the network query.
- **F-1 old census JSONs still load:** the deprecated `tic_cone_60arcsec` key is accepted with radius 60.0 and a warning — a saved 60″ census must never be silently upgraded to 180″.
