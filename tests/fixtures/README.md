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
