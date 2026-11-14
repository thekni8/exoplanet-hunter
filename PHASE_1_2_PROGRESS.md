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
- [ ] B-2 MAD clip → bulk_v2 (pre-registration `8bdf693`; shared clip `d0012c7`; screen wiring `3203f63`; grid + bulk_v2 + rescore tool pending)

## Release C (not this sprint)

- [ ] C-1 Network timeouts + watchdog
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

## Judgment calls for the vote

- **A-4 waivers "in the policy":** the brief says stages block "unless the decision policy waives them explicitly (per-stage, in the policy, with a reason)". A literal reading (waivers listed in `gauntlet_v2.yaml` per target) is unworkable — the registry forbids editing the policy per target. Implemented as: the policy's `waivers` map is the ALLOWLIST (which stages may be waived + grounds); each run applies waivers with per-target reasons; the verdict record carries them. Allowlist is deliberately small (holdout, clean_refold, pixel_check — structural non-applicability only). UNMEASURED/FAIL never waivable.
- **A-5 raw_flux kept as a required stage:** the brief's DAG table omits it, but it is a load-bearing gate (S97 TIC 344334378 was RAW-REFUTED; hard REFUTED vs shape's INCONCLUSIVE) and the brief never orders its removal; the table's persistence "RAW verdict" is a different per-sector test. Documented in `REQUIRED_STAGES`.
- **A-6 fixture is synthetic:** no real TIC 139526205 light curve is on disk (S97 run data is on the Mac). The fixture is box transits at the real ephemeris with the real depths; the verdict (blend) is the real case's. Documented in `tests/fixtures/blend/README.md` + `case.json`.
