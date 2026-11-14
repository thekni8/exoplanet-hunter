# Phase 1.2 progress

Release A (unblocks Phase 2) — brief v2, `~/workspace/goals/exoplanet-hunter/hidden_files/science-vet/phase1-1-vote/PHASE1_2_AGENT_BRIEF.md`.
Started 2026-11-14 ~12:21 IST on branch `standardize/phase-1` (HEAD `c630327` at start, tree clean).

Note: v1-spec commits `c630327` (runner) and `e1baef2` (contract) to review against the v2 brief — rework in new commits where they diverge. Never amend or rebase.

## Release A

- [x] A-1 Calibration hash enforcement (registry) — `5c7a26d`
- [x] A-2 Provenance layer 2 — `c0364ad` (166-test fast suite green, 585.6 s, before the bare-version map correction; 123-test affected subset green after it)
- [ ] A-3 Resume hash-mismatch refusal
- [ ] A-4 StageResult contract v1 (allowlist + gauntlet_v2)
- [ ] A-5 Stage runner (DAG + cheap-always)
- [ ] A-6 Blend pure function + fixture
- [ ] A-7 Conservation check

## Release B (not this sprint)

- [ ] B-1 Mirror deprecation
- [ ] B-2 MAD clip → bulk_v2

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
| Golden suite green (102 + N new) | `~/workspace/exoplanet-hunter/.venv/bin/python tests/run_golden.py` | `OK, GOLDEN SUITE: PASS` | (fill in) |
