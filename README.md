# 🔭 Exoplanet Hunter

![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-job--queue%20API-009688?logo=fastapi&logoColor=white)
![React](https://img.shields.io/badge/React-18-61DAFB?logo=react&logoColor=black)
![Data](https://img.shields.io/badge/Data-NASA%20TESS%20%2F%20MAST-0B3D91)
![License](https://img.shields.io/badge/License-GPL--3.0-blue)

**Point it at a patch of sky, press one button, and hunt for planets in real NASA TESS data.**

Exoplanet Hunter is a beginner-friendly exoplanet hunting workstation. It downloads real light curves from NASA's TESS mission, searches them for the tiny, repeating dips in starlight caused by a planet crossing its star, scores every candidate, and saves the strong ones — automatically. It grew out of a real frustration: an earlier one-file version of this idea was fun for a complete beginner (it found real signals, including fakes worth catching) but died after ~15 stars, and its results vanished unless you screenshotted them by hand. This rebuild keeps that simple soul and fixes both flaws.

**There is no simulated data anywhere in this app.** Every chart, score and verdict comes from real observations served by the Mikulski Archive for Space Telescopes (MAST). When a patch of sky is quiet, the app says so — a scan that finds nothing is a real result, reported honestly.

---

## ✨ Features

### 🎯 Deep Space Scanner — *start here*
The home screen, and the whole point of the app. It comes pre-filled with a patch of sky (RA 124.456, Dec −67.568) and needs exactly one click: **Initialize Scan**.

- Screens the catalog for suitable dwarf stars in your patch.
- **Skips stars people have already flagged** — each candidate is checked against Zooniverse (Planet Hunters TESS talk) *before* a single byte is downloaded.
- Runs as a background job that **always finishes the whole list** — 20, 50, 100 stars, no dying halfway.
- Surfaces only strong, new signals as 🎯 hit cards; weaker signals are listed quietly underneath.

### 🔬 Diagnostic Observatory
Deep-dive a single star by its TIC ID. Downloads and stitches its TESS light curves, runs a full BLS (Box Least Squares) period search, and shows four charts drawn from the real result data — the raw light curve, the flattened curve, the BLS periodogram, and the phase-folded transit — plus an engine-rendered diagnostic plate and the recovered period, depth, planet radius and SDE score.

### 🧭 Sky Sweeper
The Scanner's fully manual sibling: your own RA/Dec, cone radius, brightness (Tmag) and star-radius screens, star limit, sector cap and BLS density. Every field shows its valid range above the box, and out-of-range values are refused with a plain message before anything is submitted — no silent clamping, no wasted runs.

### ⚖️ "Is it a fake?" — the odd/even test
The classic impostor in transit hunting is an **eclipsing binary**: two stars whose eclipses mimic a planet. Every hit card carries an **"Is it a fake? →"** button that folds the light curve at twice the candidate's period and compares alternate dips — no retyping, the star and period travel with the click. Equal dips → **planet-like**. Noticeably different dips → **likely a binary star faking a planet**. No measurable dip → inconclusive, and it says so.

### 🧪 QA Benchmarks
One click runs the engine against three known planets — TOI-114, Pi Mensae c and WASP-126 b — and checks the recovered periods against the published values. It's the app's honesty check: if the pipeline drifts, the benchmarks show it.

### 💾 History & Discoveries
Every run is persisted. Anything scoring **SDE ≥ 8.5** is written to the Discoveries table automatically — hits-only, nothing else. Close the tab, rerun a scan, come back next week: your finds are still there. **There is nothing to save by hand.**

In-app, the **Guide** page (next to the Scanner in the nav) explains every value in plain language, with the exact ranges and safe starter values.

---

## ⚙️ How it works

1. **Point** — you give the app a patch of sky (RA / Dec / radius), or a single TIC ID.
2. **Screen** — the TIC catalog is filtered to suitable stars (brightness and size); in Scanner mode, already-discussed stars are skipped via Zooniverse first.
3. **Download** — real TESS light curves are fetched from MAST via `lightkurve`.
4. **Flatten** — slow instrumental and stellar trends are removed (detrending), leaving the fast dips.
5. **Search** — an astropy **BLS** period search tries thousands of candidate periods and measures the best repeating dip.
6. **Score & save** — each candidate gets an **SDE** (Signal Detection Efficiency) score. **SDE ≥ 8.5** is saved to Discoveries; **SDE ≥ 11** is what the Scanner raises a 🎯 alarm for. Everything runs through a one-job-at-a-time queue with live progress, so big scans finish instead of timing out.

---

## 🚀 Quick start — GitHub Codespaces (recommended)

The app is built to run free on GitHub Codespaces (GitHub Free includes ~120 core-hours/month — roughly 60 hours on the 2-core / 8 GB machine — no card required). Full notes live in [CODESPACES.md](CODESPACES.md).

1. Open this repo on GitHub.
2. Green **Code** button → **Codespaces** tab → **Create codespace on main** (or open your existing one).
3. Wait for the browser editor to load — setup is deliberately minimal, nothing installs behind the "Setting up" screen.
4. In the editor's terminal, run:
   ```bash
   bash run.sh
   ```
   First run installs the Python dependencies in the terminal, visibly (a few minutes). Later starts are fast.
5. Open the forwarded **port 8000** link — that's the app. (To share it: Ports panel → right-click port 8000 → Port Visibility → Public.)
6. You're looking at the Scanner. Press **Initialize Scan**.

> **Two gotchas worth knowing**
> - After a `git pull` inside the Codespace, restart the app (`Ctrl+C`, then `bash run.sh` again) **and hard-refresh the app tab** with **Cmd+Shift+R** — browsers love showing you yesterday's cached copy.
> - The app is live **only while a Codespace session is running**. When you're done, stop the codespace (github.com/codespaces → **… → Stop**) to save your free hours; it also auto-stops after ~30 min idle.

**Prefer your own machine, a home server, or a VPS?** That's the full [Installation](#-installation--run-it-on-your-own-system) section below — same app, your hardware.

---

## 📦 Installation — run it on your own system

Codespaces is the zero-install option. Everything below is for running Exoplanet Hunter on **your own machine or any host you control** — a laptop, a home server, a Raspberry-Pi-class box, or a cloud VPS all work the same way.

### Prerequisites

- **Python 3.12** (the version the Dockerfile uses) and **git**.
- **Node.js is NOT required to run the app.** The production frontend is committed to this repo under `frontend/dist/`, and the server serves it as-is.
  - Node 20+ is needed **only if you change the frontend source** (`frontend/src/`). Then rebuild and commit the result, or your changes won't exist at runtime:
    ```bash
    cd frontend && npm install && npm run build   # regenerates frontend/dist/
    ```
- About **10 GB of free disk** (see "Good to know" below) and an internet connection.

### Option 1 — Local install (venv)

```bash
git clone https://github.com/thekni8/exoplanet-hunter.git
cd exoplanet-hunter

python3 -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt

bash run.sh
```

Then open **http://localhost:8000** — you're looking at the Scanner.

What `run.sh` does: it starts the app (`uvicorn api:app`) on `0.0.0.0:8000`, serving the UI and the API together. If the dependencies aren't installed yet, it creates a `.venv` and installs them for you first — in the terminal, visibly, never hidden (on a first run that takes a few minutes). It only builds the frontend if `frontend/dist/` is missing entirely.

### Option 2 — Docker

The image is `python:3.12-slim` and includes the built UI:

```bash
docker build -t exoplanet-hunter .
docker run -p 8000:8000 -v hunter-data:/app/data exoplanet-hunter
```

Then open **http://localhost:8000**. The `-v hunter-data:/app/data` part matters: all runtime state — the SQLite database with your run history and discoveries, stored job results and diagnostic plates — lives in `/app/data`. Mount a volume there (as above) and your discoveries survive container rebuilds; skip it and they vanish with the container.

### Option 3 — Any VPS / cloud VM

Identical to Option 1 on any Linux host: clone, venv, install, `bash run.sh`. Then either open port **8000** in the host firewall, or put a reverse proxy (nginx, Caddy, …) in front and let it own HTTPS. The app itself speaks plain HTTP on 8000 — on Codespaces, GitHub provides the HTTPS layer; on your own host, the proxy does.

### Good to know before your first scan

- **It needs outbound internet.** Light curves are downloaded from **MAST** (NASA's archive) — no MAST access, no data. The Scanner's already-known check talks to **Zooniverse Talk**; that one is *fail-open* — if it's blocked or down, scans simply proceed without the skip.
- **Disk usage grows as you hunt.** Downloaded light curves are cached locally (lightkurve's cache, under `~/.cache/lightkurve`) so re-scanning a star is fast, but the cache accumulates — keep **≥ 10 GB free**, more if you sweep a lot.
- **Your discoveries live in one file:** `data/hunter.db` (SQLite — run history + the hits-only Discoveries table), alongside stored job results in `data/`. **Back up `data/` and you keep your finds**; lose it and the history is gone, though the code never is.
- **Jobs run one at a time, by design.** The queue is built for modest hardware (the reference host is a 2-core / 8 GB Codespace): one careful analysis at a time, always finishing the list, instead of parallel jobs exhausting RAM mid-scan.

---

## ✅ Validation — the numbers are real

The pipeline was verified end-to-end against **WASP-126 b** (TIC 25155310), a known inflated hot Saturn with a published period of **3.2822 days**:

| Check | Result |
|---|---|
| Recovered period | **3.2903 d** — within 0.25% of the catalog value |
| Signal strength (SDE) | **≈ 21.9** — far above the 8.5 discovery bar |
| Odd/even fake-check | Odd dips **0.0852%** vs even dips **0.0813%** deep (ratio 0.955, ~4.5% apart) → verdict **planet-like** ✓, as a real planet should be |

The QA Benchmarks page re-runs this class of check against TOI-114, Pi Mensae c and WASP-126 b on demand. Per-stage build reports with full test evidence are in this repo (`STAGE1_REPORT.md` … `STAGE4_REPORT.md`, `RANGE_LABELS_REPORT.md`).

---

## 🧪 The vetting gauntlet — how a hit earns belief

A sweep hit (SDE ≥ 8.5) is a suspicion, not a candidate. Desk checks run it through the gauntlet in order (the staged runner is `vet_star2.py`); a kill at any stage ends the run:

1. **Reproduce** — re-analyze the star; a hit that doesn't reproduce is a pipeline phantom.
2. **Odd/even + double-period** — alternating eclipse depths, or an ellipsoidal wave at twice the period, mark an eclipsing binary.
3. **Sector persistence** (`persistence.py`) — the filed dip must show sector by sector at a consistent depth. The stamp is graded on raw flux too: a dip that exists only in flattened flux is vetoed to **RAW-REFUTED** (the TIC 294873918 lesson — the transit-masked second pass can manufacture a dip out of broad variability, and the stamp must not re-grade its own artefact).
4. **Holdout prediction** (`holdout_test.py`, added 2026-11-11) — leave-one-sector-out, after the Pavel Rabtsevich / TIC 4206066 (TOI-7930) playbook: fold the star's sectors into groups, refit the ephemeris *without* one group, and require the refined ephemeris to predict that group's dips in **raw** flux at ≥ 3σ in a majority of folds, with no fold showing a significant opposite signal. Stamps: `HOLDOUT-PASS` / `HOLDOUT-FAIL` / `HOLDOUT-INSUFFICIENT-DATA`. A pass proves **predictive periodicity only** — a clean eclipsing binary passes this test (control TIC 308851365 does) — so it complements the raw-flux, shape and imaging gates and never replaces them.
5. **Centroid / difference imaging** — mandatory before any discovery claim or filing; a dip that doesn't come from the target's pixels is a blend, whatever the folds say.

```bash
# Holdout desk check at a filed ephemeris (period d, T0 in BTJD, duration h)
python holdout_test.py TIC PERIOD T0_BTJD DURATION_HOURS --out holdout_TIC.json
```

The full desk-check tooling (raw-flux check + trapezoid shape gate, refined-ephemeris folds, holdout drivers, TESSCut extraction, difference imaging, formal transit fit) lives in [`gauntlet/`](gauntlet/) — see its [README](gauntlet/README.md).

---

## ⚠️ Known limitations — stated plainly

- **Transit depth and planet radius read low.** For WASP-126 b the engine measures a depth of ~0.204% and a planet radius of ~6.4 R⊕ against catalog values of ~0.940% and ~10.7 R⊕. Periods and SDE scores are trustworthy; absolute depths/radii are under-recovered and **under investigation** — treat planet sizes as approximate, lower-bound estimates.
- **The `pipelines` setting is not wired into the engine yet.** The sidebar checkboxes are recorded with each run for provenance, but the engine currently always searches SPOC + TESS-SPOC + QLP with an unfiltered fallback. The UI says this next to the checkboxes, too.
- **Not always-on.** On Codespaces the app exists only while a session runs, and jobs run one at a time — that's the price of free hosting, and the queue is designed around it.
- **The Zooniverse skip is a heuristic.** It searches Planet Hunters talk discussions for the star's TIC number; it can miss known planets, and a quiet patch returning zero hits is a normal, honest outcome.

---

## 🛠 Tech stack

- **Engine** — Python · `lightkurve` (TESS light curves from MAST) · `astropy` BLS · `numpy` / `pandas` / `scipy`
- **API** — FastAPI + a single-worker job queue; SQLite for run history and the hits-only Discoveries table
- **Frontend** — React 18 + Vite + Tailwind CSS (dark zinc workstation theme), canvas charts drawn from real API payloads
- **Hosting** — GitHub Codespaces (2-core / 8 GB), UI + API served together on port 8000

## 📁 Project layout

```
exoplanet-hunter/
├── hunter.py            # the engine: analyze / sweep / odd-even test (real TESS data)
├── persistence.py       # sector-persistence stamp (incl. the RAW-REFUTED raw-flux veto)
├── holdout_test.py      # leave-one-sector-out holdout prediction test (HOLDOUT-* stamps)
├── gauntlet/            # vetting desk-check tools: raw-flux check, imaging, fit (see gauntlet/README.md)
├── api.py               # FastAPI job-queue API + SQLite history & discoveries
├── run.sh               # one-command start (installs deps visibly, serves :8000)
├── requirements.txt
├── Dockerfile
├── CODESPACES.md        # hosting notes, limits and gotchas
├── frontend/
│   ├── src/             # React app: views (Scanner, Observatory, Sweeper, QA, History, Guide)
│   └── dist/            # committed production build — Codespaces has no Node
└── data/                # runtime: SQLite DB + stored job results (created on first run)
```

## 📄 License

GPL-3.0 — see [LICENSE](LICENSE).

---

*Built for a beginner planet hunter, by fixing the two things that killed the first version: scans that died halfway, and discoveries that vanished. Happy hunting. 🔭*
