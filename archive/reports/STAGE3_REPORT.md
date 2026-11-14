# Exoplanet Hunter — Stage 3 Report

**Date:** 2026-11-02 · **Scope:** Stage 3 only — a real Vite + React UI wired
to the Stage 2 FastAPI API, served by the same process on port 8000.
**No simulated/fake data path exists anywhere in the frontend** — every
number shown comes from the API, or is a clearly labelled known-benchmark
reference value (the QA cards). `hunter.py` was not touched. No git
commits, pushes, or deployments.

## What was built

### Frontend (`frontend/`, Vite 5 + React 18 + Tailwind v4 + lucide-react)

Visual identity kept from Gemini's pasted UI (which was a simulator —
its data layer was discarded entirely): dark zinc-950 terminal, left
sidebar with global settings, three modes + History, 4-chart diagnostic
layout, monospace numbers. Dark but flat/professional — no gradients or
flashy effects.

| File | Role |
|---|---|
| `src/App.jsx` | Shell: sidebar nav (Observatory / Sweeper / QA Benchmarks / History & Discoveries), global settings — pipeline checkboxes (SPOC/TESS-SPOC/QLP), BLS grid slider 5,000–50,000 (default 25,000), detrend window slider 31–201 step 10 (default 101) — plus the cross-view "open target / open run" seed plumbing |
| `src/api.js` | Fetch wrappers for the Stage 2 endpoints; nothing else produces data |
| `src/useJob.js` | Polls `GET /api/jobs/{id}` every 2 s while queued/running |
| `src/components.jsx` | Panels, fields, metric tiles, status badges, and the live progress log (the engine's real progress messages, numbered, with the real error text on failure) |
| `src/charts.jsx` | Four draw-once canvas charts from the real result arrays (raw + trend, flattened, BLS with peak marker, phase-folded points + binned ±SEM). Static per Dev's answer 12B — no hover/zoom |
| `src/views/Observatory.jsx` | TIC / host radius / min-max period inputs; **sector slider 1–20 + "All sectors" toggle** (toggle sends `sector_cap: null`); Run → `POST /api/analyze` (with sidebar pipelines/BLS/detrend) → live progress → metrics tiles (period, SDE, depth %, duration, planet radius, points·sectors) → engine classification → the 300 DPI **diagnostic plate image** (`GET /api/jobs/{id}/plate`, with a download link) → the four charts from `GET /api/jobs/{id}/result` |
| `src/views/Sweeper.jsx` | RA / Dec / cone / Tmag range / radius range / max stars (+ per-star sector cap & BLS grid) → `POST /api/sweep` → progress incl. "Target n of N" → hits-only results table (SDE ≥ 8.5, from the job summary) with an **"Open in Observatory" button that actually works**: it sets the Observatory's TIC + host radius and switches the view |
| `src/views/QaBenchmarks.jsx` | The 3 benchmark cards with their labelled known periods (TOI-114 3.5941 d, Pi Mensae c 6.2679 d, WASP-126 b 3.2822 d) → "Run QA Suite" → `POST /api/qa` → per-benchmark recovered vs expected, Δ, SDE, PASS/DRIFT from the job result; "Load in Observatory" per card |
| `src/views/HistoryView.jsx` | `GET /api/history` (newest first: time, type, target, status, period, SDE; failed runs show their error); clicking a finished analyze run loads its real result + plate in the Observatory. Discoveries section from `GET /api/discoveries` (hits only) |

**Pipelines honesty note (in the UI itself):** the sidebar states, next
to the checkboxes, that the selection is sent with each run and recorded
in its history, but the engine currently always searches
SPOC + TESS-SPOC + QLP with an unfiltered fallback — unticking a box
does not yet change the engine's search (the known Stage 2 API gap;
wiring it needs a `hunter.py` change, out of Stage 3 scope).

### Serving (Codespaces-ready, one command)

- `api.py` — the ONLY change is at the end of the file: if
  `frontend/dist/` exists, it is mounted as static files at `/`
  (mounted after all `/api` routes and `/health`, so API priority and
  behaviour are unchanged; with no dist present the API behaves exactly
  as in Stage 2).
- `run.sh` (project root, executable): builds the frontend **only if**
  `frontend/dist/index.html` is missing (installs deps if needed), then
  execs `uvicorn api:app` on `0.0.0.0:8000` (prefers `.venv`). One
  command serves UI + API.
- `CODESPACES.md` step 4 now says `./run.sh`.
- `.gitignore` now also covers `frontend/node_modules/` and
  `frontend/dist/` (dist is built in the Codespace by `run.sh`, not
  committed).

## Build evidence

- `npm install` clean (36 s). `npm run build` **succeeded** (Vite 5.4.21,
  1,589 modules, 2.6 s): `dist/index.html` 0.42 kB,
  `dist/assets/index-*.js` **182.8 kB (gzip 56.1 kB)**,
  `dist/assets/index-*.css` 15.8 kB.
- Bundle sanity: the built JS contains all view labels
  ("Diagnostic Observatory", "Sky Sweeper", "QA Benchmarks",
  "Run Analysis", "Discoveries"); grep for the simulator's identifiers
  (`generateAstrophysicsData`, `INITIAL_SWEEP`, `pseudoRandom`) across
  `src/` and the bundle returns **nothing** — no fake-data code shipped.

## HTTP test evidence (real, this VM, server started via `./run.sh`)

Server first restarted the Stage 2 way (port confirmed free), then
started with `./run.sh` — which correctly skipped the rebuild (dist
existed) and served on `0.0.0.0:8000`.

1. **`GET /`** → the app HTML: `<title>Exoplanet Hunter — Terminal
   Workstation</title>` and `<div id="root">` present, referencing the
   built assets.
2. **Assets** → JS `200 text/javascript, 182,903 B`; CSS
   `200 text/css, 15,767 B`.
3. **`GET /api/history`** via the same origin → the real run history
   (Stage 2 jobs + the known-good run `57cc226b466441e8`).
4. **End-to-end analyze through the served origin** — job
   `5955893878694ac2`, WASP-126 b exactly as the UI submits it
   (`tic_id 25155310, host_radius 1.30, sector_cap 2, bls_points 8000,
   detrend 101, pipelines [SPOC, TESS-SPOC, QLP]`): queued → running →
   **done in ~25 s** (02:39:40 → 02:40:05 UTC). Progress log streamed
   the real engine steps (MAST query → "Downloading 2 of 131 sector(s)"
   → "Running BLS (8,000 grid points)" → plate written → Done).
   **Recovered period 3.290286285785723 d** (expected ≈ 3.2903 d,
   known 3.2822 d), **SDE 21.859**, depth 0.2039 %, radius 6.41 R⊕,
   36,535 points over 2 sectors — identical to the Stage 1 / Stage 2
   verified values, as it must be over the same pipeline.
5. **`GET /api/jobs/{id}/result`** → full payload with all array
   sections the charts consume (raw 3,654 pts, BLS 4,000 pts,
   phase-folded 3,423 pts + 70 bins).
6. **`GET /api/jobs/{id}/plate`** → `200 image/png`, 4,252,182 B
   (the real 300 DPI plate).
7. **History + discoveries after the run** → history lists job
   `5955893878694ac2` first, done, period 3.290286 / SDE 21.859;
   discoveries now contains its hits-only row (SDE 21.86 ≥ 8.5).

## Honest gaps

- **Visual check is UNVERIFIED.** No headless browser is available on
  this VM (no Chromium/Firefox/Playwright/Selenium), and per the brief
  no browser stack was installed to force one. The HTML/JS/CSS all
  serve correctly and the bundle contains the full app, but nobody has
  *seen* the rendered page yet — **Dev's first Codespace launch is the
  visual test.** (React mount, chart drawing on real data in-browser,
  and layout are therefore compile-and-serve verified only.)
- Sweep and QA job *executions* were not re-run in Stage 3 (their UI
  wiring uses the same polling/result plumbing proven end-to-end by the
  analyze run; their endpoints and result shapes were verified in
  Stage 2 as far as the then-broken MAST proxy allowed — a sweep run
  through the UI is still worth doing once in the Codespace).
- The depth/radius underestimate for WASP-126 b (0.204 % / 6.41 R⊕ vs
  catalog 0.940 % / 10.7 R⊕) is an engine-level open question from
  Stage 1 — the UI faithfully displays the engine's real numbers.
- `pipelines` remains pass-through/recorded only (see note above).

## State left behind

- Server **left running** via `./run.sh` on `0.0.0.0:8000`
  (log `/tmp/hunter-stage3.log`), with the Stage 3 test job in history.
- Working tree (uncommitted, unpushed): new `frontend/` (source;
  `node_modules/` + `dist/` gitignored), `run.sh`, `STAGE3_REPORT.md`;
  modified `api.py` (static mount only), `CODESPACES.md` (step 4),
  `.gitignore` (frontend artifacts). `hunter.py` untouched.
