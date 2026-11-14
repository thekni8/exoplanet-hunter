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
- [ ] C-2 Crash-boundary + idempotency
- [ ] C-3 Ledger durability
- [ ] C-4 Fixture-vs-live hash diff
- [ ] C-5 Live CI opens issue on failure
- [ ] C-6 Mutation canaries
- [ ] C-7 Expected-values file
- [ ] C-8 Run fingerprint
- [ ] C-9 Lockfile clean-install test
- [ ] C-10 TRICERATOPS/LATTE design doc

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
| Fast suite green under bulk_v2 | `EXHUNT_BULK_CALIBRATION=bulk_v2 ~/workspace/exoplanet-hunter/.venv/bin/python tests/run_golden.py --fast` | `OK, GOLDEN SUITE: PASS` | `Ran 245 tests in 485.020s — OK (skipped=1, expected failures=1) — GOLDEN SUITE: PASS (245 test(s))`, wall 8m14s, exit 0 (2026-11-14) |
| v1 calibration files byte-identical | `git diff 80832ac HEAD -- calibration/*_v1.yaml` | no diff | IDENTICAL (bulk_v1, deep_v1, gauntlet_v1) |
| Registry check passes | `python scripts/check_registry.py` | `registry check OK` | `registry check OK` (append-only diff skips with a warning: origin/main predates the registry) |
| No run-data writes since Phase 1.1 base | `git diff --name-only 80832ac HEAD`, filtered to run-data dirs | none | none (56 files changed, none under `vetting_results/` / `bulk/cache/` / `bulk/run_*` dirs / `sweep-output/` / `results/` / `data/`; note: the Release A ledger's `bulk/run_*` pathspec also matches the code file `bulk/run_chunked.py`, so the check is done on the file list) |
| Grid green under v2 / strict-xfail under v1 | `python -m unittest tests.test_clip_grid` | OK (expected failures=1) | OK (expected failures=1), 3 tests, 4.1 s |
| --allow-v1 gate tested | `python -m unittest tests.test_calibration.TestV1Gate` | OK | OK, 5 tests |
| Mirror gone, injection tests use the real pipeline | `python -m unittest tests.test_injection` | OK | OK, 3 tests, 275.7 s |
| Rescore tool tested on synthetic data | `python -m unittest tests.test_rescore_v2` | OK | OK, 3 tests — the 3.0%-on-0.3%-noise transit v1 missed (SDE 5.4) is recovered under v2 |

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
