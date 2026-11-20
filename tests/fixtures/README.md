# Test fixtures (committed, offline)

These fixtures let the golden suite run with no network. They are
small, versioned data — a fixture diff means the pipeline's view
of a known star changed, and regenerating one is a deliberate,
reviewable change.

## golden/ — golden-star light curves (Phase 1.1, item 4)

One npz per golden star, as produced by `tests/make_fixtures.py`
from the LIVE pipeline: the stitched, cleaned arrays
(`raw_time` / `raw_flux`) exactly as `hunter._run_pipeline`
sees them after stitch + remove_nans + remove_outliers, plus a
`meta_json` (TIC, sector cap, live period/SDE, TIC density for
the EB, generation time, pipeline git SHA).

| Fixture | Star | Sectors | Used by |
|---|---|---|---|
| `TIC_150428135.npz` | TOI-700 | 2 | `test_golden_fixtures.py` |
| `TIC_25155310.npz` | WASP-126 b | 1 | `test_golden_fixtures.py` |
| `TIC_308851365.npz` | known EB | 1 | `test_golden_fixtures.py` |

The offline tests load these through the fixture seam
(`hunter._fixture_lightcurve`, enabled by `EXHUNT_FIXTURE_DIR`)
and assert the SAME things the live tests assert. Regenerate
when the live and offline suites disagree, or after a pipeline
change to the fetch/clean path:

    .venv/bin/python tests/make_fixtures.py

## golden/s97_f1_queue.jsonl — S97 F-1 golden fixture (bulk_v6)

A COMPACT DERIVED fixture for the F-1 T0-cluster veto golden
test (`tests/test_bulk_v6.py`, TestS97F1GoldenFixture): the
749-row S97 re-screened queue (Stage 5 (b), bulk_v5 order,
filter-off) reduced to the fields F-1 reads (tic, t0_btjd,
n_events, k3_pass) plus tier. The raw 1.23 MB run output stays
out of git (repo AGENTS.md: keep run data out of git); this
65 KB derivation is test data, not a run dump.

Source: `stage5-run/bulk/run_s0097/survivors.jsonl`, sha256
`2b2bc1745dff5bf036769b621f862ca84044660044ab8654b802535075c0ef4a`.
Derived by `/tmp/extract_s97_fixture.py` (one-off; the script
is not committed — the derivation is: keep tic/t0_btjd/
n_events/k3_pass/tier, drop nulls, one JSON object per line,
keys sorted). The source file is the v5-order run (K=3 joined
before the veto), so its K=3 population is smaller than the v6
F-1 input — the pinned counts below are a regression guard on
this fixed input, not the v6 production count.

Pinned expectations (measured 2026-11-20 with the implemented
veto; a change means F-1's behaviour on real data moved):
25 demoted (23 pass-1 + 2 K=3), 1 cluster of 25 (T0 span
3946.6134–3946.7616, the 3946.5–3947.0 artifact epoch from
NULL_DIAGNOSIS §2), 724 kept, 0 known-planet TICs demoted.
All 25 demoted rows are tier B (24 single-event, 1 two-event).
The file carries no known_toi/known_vsx flags (the re-screen
ran --skip-known-filter), so the full 0-TOIs-lost check stays
a frozen-replay validation item (Mac), not a fixture assertion.

## injection/ — injection-recovery substrate (Phase 1.1, item 6)

`substrate_238620464.npz` — the stitched light curve of the
typical Tmag ~12 QLP star from the 2026-11-13 injection-recovery
study (8 sectors, 35,323 points, 2226-d baseline). The smoke test
(`tests/test_injection.py`) injects trapezoid transits into it
with the repo's own `injection_harness.py` functions and asserts
recovery. Copied from the study's substrate store, not
regenerated per run: the smoke test must be deterministic.

## triceratops/ — TRICERATOPS golden fixtures (Phase 3, P3-7)

The C-10 runs (EB TIC 308851365, WASP-29b TIC 183537452),
committed as JSON fixtures so the offline assertions in
`tests/test_triceratops_golden.py` run in normal CI (TB-12:
the assertions, not the nightly, are the merge gate). See
`triceratops/README.md` for the format, the reconstruction
status (the fixtures are rebuilt from the recorded C-10
numbers; the full Mac outputs are pending extraction), and
the pending items (≥5-seed bands, TOI-700 c).
