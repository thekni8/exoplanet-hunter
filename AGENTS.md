# AGENTS.md — runbook for AI agents

You are operating the Exoplanet Hunter: an amateur TESS exoplanet
detection pipeline. It downloads real TESS light curves, searches
them for transits with Box Least Squares, and vets survivors through
a desk-check gauntlet. This file tells you how to run it
end-to-end. If you are a new agent on this repo, start at step 1
and do not skip the validation step.

## What this repo is

- **Detection** — `hunter.py` (single-target deep pipeline),
  `bulk_screen.py` + `bulk/` (sister bulk screen: one sector of QLP
  FFI light curves per star, cheap and wide), `persistence.py`
  (cross-sector stamp), `holdout_test.py` (leave-one-sector-out
  prediction).
- **Vetting** — `gauntlet/` (desk checks: raw-flux fold, trapezoid
  shape gate, refined-ephemeris folds, difference imaging, formal
  transit fit). The desk procedure is `docs/vetting-manual.md`.
- **Outputs** — `survivors.jsonl` (bulk screen → gauntlet handoff,
  `schema/survivor-schema.json`) and one verdict record per vetted
  candidate (`schema/verdict-schema.json`).

Key numbers: a sweep hit needs SDE ≥ 8.5. The bulk screen's
survivor bar and tier thresholds are versioned calibration
constants in `calibration/bulk_v1.yaml` (loaded by
`bulk_screen.py` at import; see `bulk/CALIBRATION_V1_1.md` and
`calibration/README.md`) — they are code, not configuration, and
changing them means a new profile version + the code + the golden
suite, together.

## 1. Set up

Python 3.12. Dependencies are pinned in `requirements.txt` — the
versions are the ones the pipeline was verified against. Do not
unpin without re-running the golden suite.

```bash
git clone https://github.com/thekni8/exoplanet-hunter.git
cd exoplanet-hunter
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## 2. Validate first — never run a sector on a red suite

```bash
.venv/bin/python tests/run_golden.py --fast   # no downloads: recipe loader + stamp unit tests
.venv/bin/python tests/run_golden.py          # full suite: also the pipeline end to end
                                              # on TOI-700, WASP-126 b, TIC 308851365
                                              # (tens of MB of MAST downloads, cached)
```

Exit code 0 means the pipeline on your machine reproduces the
known answers. If a test fails, **do not "fix" it by loosening a
threshold** — find what changed in the search, the stamp, or the
data. A red suite is a real signal. CI runs the same suite on
every push and pull request (`.github/workflows/golden.yml`).

## 3. Run a sector screen

A screen is driven by one YAML recipe in `bulk/recipes/` — the
recipe is the single source of truth for the sector, the target
window (Tmag + radius cuts), and the run shape. Precedence:
CLI flags > recipe file > built-in defaults.

```bash
# 1. Build the target list from the recipe
.venv/bin/python bulk/build_target_list.py --recipe bulk/recipes/sector-96.yaml
# 2. Screen it in slices (checkpoint unit: one slice)
.venv/bin/python bulk/run_chunked.py --recipe bulk/recipes/sector-96.yaml
# 3. Merge slices, recalibrate, and run the clean-data re-fold gate
#    (see bulk/RECALIBRATION_S0097.md for the worked sequence)
```

`run_chunked` verifies the recipe against the window file and
refuses to run on a mismatch — the window that was built is the
window that gets screened. Downloads go to `bulk/cache/`
(gigabytes; gitignored). Survivors land in
`<out-dir>/survivors.jsonl` in gauntlet input shape.

Worked references: `bulk/RECALIBRATION_S0097.md`,
`bulk/RECALIBRATION_S0098.md`, `bulk/CALIBRATION_V1_1.md`,
`bulk/TEARDOWN.md` (why the sister pipeline exists).

## 4. Vet a survivor

Follow `docs/vetting-manual.md` in order: catalogue check →
clean-data re-fold gate → persistence in raw flux (refine the
period FIRST for bulk survivors) → trapezoid shape gate →
odd/even + double period → holdout test → centroid/difference
imaging → formal transit fit. Record every verdict in the
standard verdict record (`schema/verdict-schema.json`).

A kill at any stage ends the run. A survivor that passes every
gate is a **candidate**, not a discovery: confirmation needs
high-resolution imaging or radial velocity, and nothing in this
repo authorises a public claim on its own.

## 5. Single-target deep pipeline

```bash
.venv/bin/python hunter.py --tic 150428135 --radius 0.42 --sectors 2
```

`hunter.analyze_target()` is the programmatic entry point
(`_run_pipeline()` returns the full result dict, including the
top-3 refined signals). Product selection is deterministic:
SPOC > TESS-SPOC > QLP. The persistence stamp
(`persistence.py`) and holdout test (`holdout_test.py`) run on
hits the pipeline already found.

## Hard rules

- **Never claim a planet without centroid/difference imaging.**
  No photometric evidence, however strong, localises the source
  on its own.
- **Never loosen a threshold to make a test pass.** Thresholds
  change deliberately, with the calibration doc and the golden
  suite updated in the same change.
- **Never change a threshold without bumping calibration_version
  and re-running the injection harness.** A threshold change
  without a completeness re-measurement is flying blind — the
  version bump is what keeps old and new records distinguishable.
- **Never use a bulk-screen period as a fold anchor.** Refine it
  first (manual stage 2) or every cross-sector fold reads zero.
- **Never call a transit flat-bottomed from a box-vs-wave test.**
  Fit the trapezoid and read T23/T14 (manual stage 3).
- **Never file a variable-star report before the blend check.**
  Persistence + difference imaging both pass first, and only one
  submission can await review at a time.
- **Keep run data out of git.** `bulk/cache/`, `reports/`,
  `results/`, `discoveries.csv`, `data/` are gitignored. Commit
  code, docs, recipes, and tests — not downloads.
- **Work on a branch; main stays green.** Merge only after the
  golden suite passes and a human has reviewed the change.
