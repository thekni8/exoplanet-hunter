# Range Labels + Out-of-Bounds Guard — Report

**Date:** 2026-11-02 · **Ask (Dev):** show the valid range above every text
box so a value can't go out of bounds (OOB) — for all sliders and text
boxes, including the Advanced section.

**Backend fact that shaped the ranges:** `api.py`'s Pydantic models
(`AnalyzeRequest`, `SweepRequest`, `OddEvenRequest`) declare **no**
numeric constraints at all — every field is accepted as-is. So no range
below comes from an API constraint; each is the UI-implied range (an
existing slider's min/max), an astronomical identity (RA/Dec), or an
operational bound consistent with how `hunter.py` uses the value.

## Audit table — every numeric input in the app

| View | Field | Valid range | Source of range |
|---|---|---|---|
| Sidebar (App) | BLS Grid Density (slider) | 5,000 – 50,000 | UI-implied (slider min/max; engine default 25,000) |
| Sidebar (App) | Detrend Window (slider) | 31 – 201 (odd) | UI-implied (slider min/max; flatten window must be odd) |
| Scanner | RA (deg) | 0 – 360 | Astronomical |
| Scanner | Dec (deg) | −90 – +90 | Astronomical |
| Scanner | Search radius (slider) | 0.01 – 1.00° | UI-implied (slider min/max) |
| Scanner | Stars to scan (slider) | 5 – 100 | UI-implied (slider min/max) |
| Observatory | Target TIC ID | positive whole number | Catalog identifier (typed as text) |
| Observatory | Host Radius (R☉) | 0.1 – 10 | Operational (dwarf-star family the catalog screens use) |
| Observatory | Min Period (d) | 0.1 – 100 | Operational (BLS grid `np.linspace(min_p, max_p)`; engine defaults 0.5–25) |
| Observatory | Max Period (d) | 0.1 – 100, and > Min Period | Operational (as above) |
| Observatory | Sector Cap (slider + All) | 1 – 20, or All | UI-implied (slider min/max) |
| Sweeper | RA (deg) | 0 – 360 | Astronomical |
| Sweeper | Dec (deg) | −90 – +90 | Astronomical |
| Sweeper | Cone Radius (deg) | 0.01 – 2 | Operational (TIC cone-query size; default 0.15) |
| Sweeper | Max Stars | 1 – 1,000 (whole) | Operational (API applies no cap; each star is a real download + BLS) |
| Sweeper | Min / Max Tmag | 0 – 20, Min ≤ Max | Operational (TIC catalog magnitudes; app screens use 11.5–15.4) |
| Sweeper | Min / Max Star Radius (R☉) | 0.1 – 10, Min ≤ Max | Operational (catalog `rad` screen family) |
| Sweeper | Sector Cap (per star) | 1 – 20 (whole) | UI-implied (matches Observatory slider) |
| Sweeper | BLS Grid Points | 1,000 – 100,000 (whole) | Operational (sidebar slider caps at 50,000; sweeps default 10,000) |
| QA Benchmarks | — | — | No numeric inputs (fixed benchmarks, one Run button) |
| History & Discoveries | — | — | No numeric inputs |
| Scanner "Is it a fake?" | — | — | No inputs (runs with the hit's TIC + period) |

## What changed (minimal, additive — no behavior/default changes)

- **`frontend/src/components.jsx`**
  - `Field` gained an optional `range` prop: renders a quiet
    `Range: …` line (10px, zinc-500, mono) between the label and the
    input — i.e. above the text box, as asked.
  - New `SliderEnds` component: min/max labels at both ends of a slider.
  - New `rangeError(name, value, min, max, int?)` helper: returns a
    plain message (`"Dec must be between −90 and 90"`) or `null`.
- **`frontend/src/App.jsx`** — `SliderEnds` under both sidebar sliders
  (BLS Grid Density 5,000/50,000; Detrend Window 31/201).
- **`frontend/src/views/Scanner.jsx`** — range hints on all four inputs,
  slider end labels on both sliders, `min`/`max` attributes on RA/Dec,
  and a pre-submit check of RA/Dec in `run()` (sliders are bounded by
  the DOM). One-button flow unchanged; the message appears in the
  existing submit-message line.
- **`frontend/src/views/Observatory.jsx`** — range hints on all five
  inputs, slider ends on Sector Cap, `min`/`max` attributes, and a
  pre-submit check in `run()`: TIC positive whole number, Host Radius,
  Min/Max Period ranges, plus Min Period < Max Period.
- **`frontend/src/views/Sweeper.jsx`** — range hints + `min`/`max`
  attributes on all ten inputs, and a pre-submit check in `run()`
  covering every field, whole-number checks for Max Stars / Sector Cap
  / BLS Grid Points, and the two min ≤ max pairs.
- **`QaBenchmarks.jsx`, `HistoryView.jsx`** — untouched (no inputs).

**Protection behavior:** an out-of-range value is never submitted and
never silently clamped — the view shows one inline message naming the
field and its range (e.g. "Dec must be between −90 and 90",
"Max Stars must be a whole number between 1 and 1000") in the same
place API submit errors already appear.

## Build

`cd frontend && npm run build` — **succeeded** (Vite, 1,590 modules):
JS **`index-R9F8dC4b.js` — 200.94 kB (gzip 60.96 kB)**,
CSS `index-CZVBNGAr.css` — 19.56 kB. (Was 198.8 kB JS in Stage 4.)
Bundle greps confirm the new strings shipped (`Range:`, `−90 – +90`,
the `must be …` validation messages). Simulator grep (Stage 3/4 rule —
`generateAstrophysicsData`, `INITIAL_SWEEP`, `pseudoRandom`,
`Math.random`) over `src/` and the built bundle: **clean**.

## Smoke test (server restarted via `bash run.sh`, left running on :8000)

- `GET /health` → `{"ok": true}`
- `GET /` → serves HTML referencing the **new** bundle
  `/assets/index-R9F8dC4b.js` (asset fetch: 200, 201,147 B).
- `POST /api/analyze` with an invalid TIC → job accepted, then **failed
  cleanly** with the real engine error
  (`RuntimeError: No mission data found for TIC not-a-real-tic-xyz.`) —
  queue behaviour unchanged.

No git commit/push performed — left for the parent agent.
