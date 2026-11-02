# Exoplanet Hunter — Stage 1 Report

**Date:** 2026-11-02 · **Scope:** Stage 1 only — engine reconciliation + capped
real-data test. No FastAPI/API or frontend work was started (a requirements
round with Dev comes first).

## What was built

`hunter.py` (~25 KB, in this working tree, **not pushed to GitHub**) — the
pure-Python CLI engine, with **no Streamlit imports**. `app.py` was used as a
reference only and is byte-for-byte untouched; `requirements.txt` already
listed every dependency the engine uses (lightkurve, astropy, astroquery,
matplotlib, pandas, scipy, numpy), so it needed no change.

### Reconciliation with Dev's original (canonical spec)

Midway through Stage 1, Dev supplied his original local `hunter.py` — the
version that lived only on his machine and was never committed. This build
was **reconciled to that original as the canonical spec**, replacing an
earlier from-`app.py` extraction (different CLI/return shape). Preserved
exactly:

- Signatures & defaults: `analyze_target(tic_id, star_radius=1.0, min_p=0.5,
  max_p=25.0, bls_points=25000, max_sectors=None)`; `sweep_sky(ra, dec,
  radius=0.15, limit=50, min_mag=11.5, max_mag=15.0, min_r=0.5, max_r=1.8,
  bls_points=10000, sector_cap=2)`; `run_qa()`.
- Pipeline: MAST search via lightkurve with `author=["SPOC","TESS-SPOC","QLP"]`
  + unfiltered fallback → `download_all` → stitch/normalize →
  `remove_nans` → `remove_outliers(sigma=5)` → flatten → astropy BLS
  (durations `linspace(0.03, 0.25, 14)`) → SDE = (peak − median)/std →
  radius = √depth × star_radius × 109.1.
- Return: `analyze_target` returns **only** `{"TIC", "Period", "SDE",
  "Radius_Re"}`.
- Side effects: 4-panel 300 DPI PNG to `reports/TIC_<id>_diagnostic.png`
  (phase-fold bins=70); `log_candidate(...)` appends to `discoveries.csv`
  with columns Timestamp, TIC_ID, Period_Days, SDE, Transit_Depth_Pct,
  Planet_Radius_Re, Star_Radius_Rsun, Sectors_Analyzed — called
  **unconditionally** for every analyzed target.
- `purge_corrupt_cache()` deletes `~/.cache/lightkurve/mastDownload` and is
  **manual only** (terminal-menu option 4); the pipeline never calls it, so
  the download cache is reused across runs.
- QA benchmarks: TOI-114 (322307342, R 1.20, expected 3.59 d, 1 sector),
  Pi Mensae c (261136679, R 1.14, 6.27 d, 2 sectors), WASP-126 b (25155310,
  R 1.30, 3.28 d, 1 sector) — all at `bls_points=10000`, PASS if
  |recovered − expected| < 0.05 d.
- CLI flags: `--tic`, `--radius` (1.0), `--sectors` (None = all), `--grid`
  (25000), `--sweep`, `--ra` (83.82), `--dec` (−5.39), `--cone` (0.15),
  `--limit` (50), `--qa`; no args → interactive `terminal_menu()`
  (1 single target, 2 sweep, 3 QA, 4 purge cache, 5 exit).
- Constants: `OUTPUT_DIR="reports"`, `DISCOVERIES_CSV="discoveries.csv"`,
  reports dir created at import.
- Engine defaults stay **exactly as in Dev's original** until he answers
  the requirements round — single-target runs default to all sectors /
  25,000-point BLS grid; the leaner presets live in QA (1–2 sectors,
  10,000 grid) and sweep (cap 2, 10,000 grid).

One honesty note: this file was rebuilt from the exact structural spec of
Dev's original (function-by-function, as relayed when he pasted it), not
from a byte-level copy of his file. **If his literal file differs in any
detail, his file supersedes this build and this version should be
reconciled against it / replaced by it.**

### Bridge additions (the ONLY additions on top of the original)

- **(a) `progress_callback`** — optional parameter on
  `analyze_target` / `sweep_sky` / `run_qa` / `analyze_target_json`.
  Called with one human-readable string per step; default `None` prints,
  exactly as the original did. For a future API layer to stream progress.
- **(b) `detrend_window`** — optional parameter defaulting to **101**, the
  value the original hardcoded in `flatten(window_length=101)`.
- **(c) `analyze_target_json(...)`** — runs the same pipeline and returns a
  JSON-serializable dict for a future FastAPI/frontend layer: `metrics`
  (period, SDE, depth, duration, t0, planet radius, sectors, points) +
  downsampled arrays (each series capped at 4,000 points): raw time/flux +
  trend, flattened time/flux, BLS periods/powers, phase-folded points, and
  binned phase data (mean + SEM, 70 bins). The CLI return/output is
  unchanged; the CLI gained one optional flag, `--json-out PATH`, to write
  this dict to a file.
- Errors propagate with clear messages; sweep per-target errors are printed
  and the sweep continues (original behaviour). No silent `except: pass`.

## Known issues (preserved deliberately — flagged, not silently "fixed")

1. **Sweep logging/rendering cost:** because `analyze_target` logs
   *unconditionally* and renders a full PNG per target, a sweep fills
   `discoveries.csv` with noise-floor targets too and generates a full
   300 DPI PNG for every sweep target. Changing this would change Dev's
   original behaviour, so it is left as-is for his decision.
2. **Depth/radius underestimate in the test below** — see Test outcome.

## Test — real run, this VM, real MAST data

Setup: local venv `.venv/` with requirements minus streamlit (not needed by
`hunter.py`): lightkurve 2.6.0, astropy 8.0.2, numpy 2.5.4 (install took
2m31s). `python3 -m py_compile hunter.py` passes.

Command (Dev's CLI flags; `--grid 8000` = the moderate test grid):

```
.venv/bin/python hunter.py --tic 25155310 --radius 1.30 --sectors 2 \
    --grid 8000 --json-out results/results.json
```

Outcome — **MAST was reachable from this VM and the run succeeded**:

| | |
|---|---|
| Wall time | 23.6 s (cache warm; the first-ever run incl. download took 37.4 s) |
| Search results for TIC 25155310 | 131 |
| Sectors used | 2 (capped) |
| Cadence points (stitched) | 36,535 |
| **Recovered period** | **3.29029 d** |
| Known period (ground truth) | 3.2822 d |
| Difference | **+0.00809 d (+0.25%) — within the QA PASS band (< 0.05 d)** |
| SDE | 21.9 ("Strong Transit") |
| Transit depth | 0.2039 % |
| Duration / t0 | 0.132 d (3.17 h) / 1327.5076 BTJD |
| Estimated planet radius | 6.41 R⊕ |

Artifacts verified on disk: `results/results.json` (729 KB; series
downsampled as designed — raw 3,654 pts, BLS capped at 4,000),
`reports/TIC_25155310_diagnostic.png` (4.1 MB, 300 DPI plate), and one
correct `discoveries.csv` row for the test target.

**Honest caveat:** the period recovery is genuinely good, but the recovered
depth (0.204%) and radius (6.41 R⊕) are well below the catalog values for
WASP-126 b used in the benchmark tables (depth 0.940%, radius 10.7 R⊕).
This run used the first 2 of 131 search results at an 8,000-point grid;
*why* the BLS depth comes out low (cadence/pipeline mix in those first
sectors, grid, flattening interaction) was **not** diagnosed in Stage 1 and
should not be papered over — it is an open question for the next stage /
Dev's requirements round.

## Not tested / not done

- `run_qa()` full suite and `sweep_sky()` were implemented to spec but not
  executed (Stage 1 test plan was the single capped WASP-126 b run).
- Uncapped / 25,000-grid runs were not attempted.
- Nothing was pushed to GitHub and no commits were made; `app.py` and
  `requirements.txt` are unchanged (`git diff` clean). Working tree
  contains, untracked: `hunter.py`, `STAGE1_REPORT.md`, `results/`,
  `reports/`, `discoveries.csv`, `.venv/`.
