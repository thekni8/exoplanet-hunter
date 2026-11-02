# README + In-App Guide — Report

**Date:** 2026-11-02 · **Scope:** two documentation/teaching deliverables —
a professional `README.md` at the repo root, and a new in-app **Guide**
page — plus a follow-up addition (same day): a full **Installation**
section in the README for running the app on your own system/host.
Every fact and number comes from the verified stage reports
(`STAGE4_REPORT.md`, `RANGE_LABELS_REPORT.md`, `CODESPACES.md`) and the
project files themselves. Nothing was invented: no fake badges, no
screenshots, no unbuilt features. Nothing committed or pushed — left
for the parent agent.

## Deliverable 1 — `README.md` (new, repo root)

Sections: title + shields (Python 3.12, FastAPI, React 18, NASA TESS
data, GPL-3.0 — the repo's actual license file) · one-line pitch · "what
this is" (beginner workstation, real TESS data only, born from v1's two
fatal flaws) · feature tour (Scanner, Observatory with its four real
charts + diagnostic plate, Sweeper, the odd/even "Is it a fake?" test,
QA Benchmarks, History & Discoveries) · "How it works" in 6 steps
(point → screen → download → flatten → BLS search → score & save) ·
Codespaces quick start (incl. both gotchas: restart + Cmd+Shift+R
hard-refresh after `git pull`; stop the codespace to save hours) ·
**Installation** (below) · Validation with the real WASP-126 b numbers
(period 3.2903 d vs 3.2822 known, SDE ≈ 21.9, odd/even 0.0852% vs
0.0813% → planet-like) · honest Known limitations (depth/radius
under-recovery with the measured-vs-catalog figures; `pipelines`
parameter not yet wired into the engine; Codespaces-only-while-open;
Zooniverse check is a heuristic) · tech stack · project layout tree.

### Installation section (follow-up addition, Dev's ask)

Written from the actual files (`run.sh`, `requirements.txt`,
`Dockerfile`, `api.py`) so other users can self-host:

- **Prerequisites:** Python 3.12 (matches the Dockerfile) + git.
  Node **not** required to run — `frontend/dist` is committed; Node 20+
  only for rebuilding the frontend, with the rebuild commands and the
  warning that dist must be rebuilt + recommitted after source changes.
- **Local install, step by step:** `git clone
  https://github.com/thekni8/exoplanet-hunter.git` → venv
  (`python3 -m venv .venv && source .venv/bin/activate`) →
  `pip install -r requirements.txt` → `bash run.sh` (explained: starts
  `uvicorn api:app` on 0.0.0.0:8000, installs deps into `.venv` first
  if missing, visibly; builds the frontend only if dist is absent) →
  http://localhost:8000.
- **Docker route:** `docker build -t exoplanet-hunter .` +
  `docker run -p 8000:8000 -v hunter-data:/app/data exoplanet-hunter`,
  with the volume explained from api.py's storage layout
  (`data/hunter.db`, `data/results`, `data/plates` under `/app/data`).
- **Run-it-anywhere notes:** any VPS/VM works the same; open port 8000
  or put a reverse proxy in front for HTTPS; outbound internet required
  to **MAST** (downloads) and **Zooniverse Talk** (known-star check,
  fail-open if blocked); first scans cache light curves locally
  (`~/.cache/lightkurve`) so disk grows — ≥ 10 GB free suggested;
  discoveries live in `data/hunter.db` — back up `data/` to keep them;
  jobs run one at a time by design (8 GB RAM-class machines).

**One real fix made while documenting:** the Dockerfile copied only
`hunter.py` + `api.py`, but `api.py` serves the UI from
`frontend/dist` *when it exists* — a Docker build would have been
API-only at `/`. Added one line, `COPY frontend/dist ./frontend/dist`
(`.dockerignore` does not exclude `frontend/`). Verified by inspection;
**Docker is not installed on this VM, so the image build itself was not
test-run here** — the parent agent may want a `docker build` check on a
Docker-capable machine before advertising the route loudly.

## Deliverable 2 — Guide page (`frontend/src/views/Guide.jsx`, new)

- **Nav:** "Beginner's Guide" (BookOpen icon) sits in "Start here"
  directly under the Deep Space Scanner — not under Advanced tools.
  Scanner remains the default home view. (`frontend/src/App.jsx`:
  import + one nav button + one render line; nothing else touched.)
- **"Start here"** — what the app does in plain words, then the normal
  hunt as 6 numbered steps: Scanner → Initialize Scan → read the
  summary → 🎯 hit card → "Is it a fake? →" → "Open in Observatory",
  with hits already saved in History & Discoveries.
- **"What every value means"** — 15 small cards in the app's card
  style, each with a one-sentence plain explanation, the **exact range
  from `RANGE_LABELS_REPORT.md`** (RA 0–360, Dec −90–+90, Scanner
  radius 0.01–1.00°, Sweeper cone 0.01–2°, stars 5–100 / 1–1,000,
  Tmag 0–20, star radius 0.1–10 R☉, sector cap 1–20 or All, BLS
  1,000–100,000 / sidebar 5,000–50,000, detrend 31–201 odd, period
  0.1–100 d, TIC positive whole number) and a "Beginner pick". Covers
  all required concepts: RA, Dec, radius/cone, stars to scan, Tmag,
  star/host radius, sector cap (with a plain "what a sector is"), BLS
  grid points ("how hard the app thinks"), detrend window, period,
  SDE (8.5 saved / 8.5–11 weaker / ≥11 🎯, WASP-126 b ≈ 21.9 for
  scale), transit depth %, planet radius (R⊕), and the odd/even
  verdict meanings (≤25% dip difference = planet-like; >25% = likely
  eclipsing binary; no measurable dip = inconclusive). Depth/radius
  cards carry the honest under-recovery warning with the real
  WASP-126 b figures (≈6.4 vs ≈10.7 R⊕).
- **"Your first advanced run, step by step"** — Walkthrough A:
  Observatory on WASP-126 b (TIC 25155310, host radius 1.30, periods
  0.5–25, sector cap 2, sidebar defaults) with the expected verified
  outcome (period ≈ 3.29 d, SDE ≈ 21.9). Walkthrough B: Sweeper with
  its built-in starter values (RA 83.82, Dec −5.39, cone 0.15, Tmag
  11.5–15, radius 0.5–1.8, max stars 8, sector cap 2, BLS 10,000),
  including the OOB-refusal behaviour and the honest note that the
  Zooniverse known-skip is Scanner-only.
- **"Reading your results"** — promising-candidate vs likely-fake
  cards, plus where finds live (auto-saved at SDE ≥ 8.5, nothing to
  save by hand, reruns never wipe finds) and the honesty note that
  "planet-like" means *candidate*, not confirmed planet.
- Style reuses `Panel` and the existing zinc card classes; no new
  dependencies; the page makes no API calls.

## Build & smoke test

- `cd frontend && npm run build` **succeeded** (Vite, 1,591 modules):
  JS **`index-DMaBEKc7.js` — 220.54 kB (gzip 66.99 kB)**,
  CSS `index-BfjZAewy.css` — 20.88 kB. (Guide added ~19.6 kB over the
  range-labels build.)
- Bundle greps confirm the Guide shipped: "Beginner's Guide",
  "What every value means", "Beginner pick", "Your first advanced run".
- Simulator grep (`generateAstrophysicsData`, `INITIAL_SWEEP`,
  `pseudoRandom`, `Math.random`): **clean in `frontend/src/` (0 hits)**.
  The bundle contains exactly 2 `Math.random` hits, both inside React
  DOM's own library code (`_reactListening…`, `__reactFiber$…` key
  generation — standard React internals, not app code).
- Server restarted via `bash run.sh` (old PID 4628 stopped; new server
  left running on :8000): `GET /health` → `{"ok": true}`; `GET /`
  serves the new bundle `index-DMaBEKc7.js`; invalid-TIC analyze job
  `b748d48bfb774b23` (TIC 999999999999) **failed cleanly** in ~6 s with
  the real engine error `RuntimeError: No mission data found for
  TIC 999999999999.` — queue behaviour unchanged.

## Files changed

| File | Change |
|---|---|
| `README.md` | **New** — full repo README incl. Installation section |
| `Dockerfile` | +2 lines (comment + `COPY frontend/dist ./frontend/dist`) so the documented Docker route serves the UI |
| `frontend/src/views/Guide.jsx` | **New** — the Guide view |
| `frontend/src/App.jsx` | Guide import, nav button under Scanner, render branch |
| `frontend/dist/` | Rebuilt (`index-DMaBEKc7.js`, `index-BfjZAewy.css`) |
| `GUIDE_README_REPORT.md` | This report |

No git commit/push performed — left for the parent agent. Note for the
Codespace ritual: after pulling this change, restart the app and
hard-refresh (Cmd+Shift+R), per CODESPACES.md.
