# TRICERATOPS golden fixtures (Phase 3, P3-7)

The C-10 runs, committed as fixtures so the offline assertions in
`tests/test_triceratops_golden.py` run in normal CI (TB-12: the
assertions, not the nightly, are the merge gate). The Mac nightly
(P3-8) re-runs the tool on the fixture inputs and checks the
outputs against the bands here; CI only ever reads these files.

## Format

One JSON per target. `tool_output` is the TRICERATOPS output JSON
(schema `triceratops-output-schema.json`) — the adapter input.
`scenario` is the per-scenario probability split from the Mac
report / probabilities CSV (the output schema has no STP/SEB
slots). `seeds` is one entry per seed run (the ≥5-seed band,
TB-4). `expected` is the TB-4 assertion: status + tolerance
bands, NEVER exact floats — TRICERATOPS fetches neighbours and
TRILEGAL remotely, so identical inputs do not guarantee
bitwise-identical output.

## Reconstruction status

The fixtures are RECONSTRUCTED from the recorded C-10 numbers
(Phase 3 BUNDLE.md §1.6 + the merged PR #6 body / lockfile
header) — the full Mac outputs (`vetting_results/
triceratops-verify/VERIFICATION_REPORT.md` + probabilities
CSVs) are not on the VM. Every fixture carries a `provenance`
block stating exactly which fields are measured and which are
placeholders (input hashes, the full per-scenario split, the
artifact paths). The Mac extraction (P3-7, prepared in
`phase3-vote/p3-9-panel-mac-commands.md`) verifies and completes
them; until then the fixtures assert only what the records
measure (dispositions + hard bounds), and the seed-band checks
skip visibly.

## Pending (Mac work)

- **≥5-seed bands** (WASP-29b FPP band, STP-split band): the
  fixtures carry one seed each (20261114). The band checks skip
  until ≥5 seeds are committed. Band width comes from the seed
  spread, never invented.
- **TOI-700 c (TIC 150428135):** NO fixture until a measured run
  exists — measure before asserting (P3-7). The panel (P3-9)
  runs it; the fixture + assertion land from the measured
  result.
- **Fast Mac smoke test (N = 10,000 draws, P-16):** for
  iteration alongside the full N = 1,000,000 run. It lives in
  the nightly (P3-8), not in CI.

| Fixture | Target | Disposition under (A) |
|---|---|---|
| `308851365.json` | Known EB | FAIL / refute (FPP ≥ 0.5) |
| `183537452.json` | WASP-29b (known planet) | INCONCLUSIVE (FPP 0.169, STP-dominated, no contrast curve) |
