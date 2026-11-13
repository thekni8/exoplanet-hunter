# Responsive (Mobile) Frontend Pass — Build Report

**Date:** 2026-11-05 · **Scope:** `frontend/src` + rebuilt `frontend/dist` only. No engine code (`hunter.py`, `api.py`) touched. Not pushed — left for the parent's pending bundle.

## Problem (verified before)

At 390px the shell kept its desktop shape: a fixed 256px sidebar consumed ~55–66% of the phone screen, the main column crushed to ~134px, Scanner form fields collapsed into tiny clipped boxes, range labels collided, and the History table showed a single column.

## Breakpoint strategy

- **≤768px = mobile**, **≥769px = desktop**, implemented with Tailwind arbitrary variants (`max-[768px]:`, `min-[769px]:`, plus standard `sm:`/`md:` steps inside forms).
- Every change is scoped so that at desktop widths the original classes win — desktop rendering is not merely similar, it is **pixel-identical** (see Desktop gate).
- No text was shrunk to fit; layouts were restructured (stack, wrap, scroll-within-panel) instead.

## Changes per file

### `frontend/src/App.jsx` — mobile shell
- Root: `flex-col` on mobile, `min-[769px]:flex-row` restores the desktop row.
- Sidebar → **top bar** on mobile: full-width, title + a hamburger toggle (`aria-label="Toggle navigation menu"`, Menu/X icons, 41px tap box). On desktop the toggle is `min-[769px]:hidden`.
- Nav + footer wrapped in a collapsible container: `hidden` when closed on mobile, always `flex` at ≥769px with the exact original flex geometry (`flex-1 min-h-0`), so desktop sidebar height distribution is unchanged. Open menu caps the nav at `max-h-[60vh]` with its own internal scroll.
- Nav items close the menu on tap → every view reachable in **≤2 taps**. **Global Settings** (pipeline checkboxes, BLS grid slider, detrend sliders, sector cap/steps) live inside the expanded menu — nothing was deleted.
- `main` gets `min-h-0` on mobile (keeps `h-full` at ≥769px).

### `frontend/src/index.css`
- One mobile-only rule: `@media (max-width: 768px) { input[type="range"] { height: 40px } }` — sliders get a 40px touch height (verified by measurement: 40px). Desktop CSS untouched.

### `frontend/src/views/Scanner.jsx`
- Form grid `grid-cols-2 md:grid-cols-4` → `grid-cols-1 sm:grid-cols-2 md:grid-cols-4`: RA/Dec inputs and both sliders stack full-width on phones; labels and range text fully visible. (Initialize Scan button was already `w-full sm:w-auto`.)

### `frontend/src/views/Sweeper.jsx`
- Same form-grid treatment for its 10 fields.
- Launch row wraps (`flex-wrap gap-3`); Launch Sweep button full-width on mobile.
- Hits table wrapped in `overflow-x-auto` — scrolls **within its panel**, never the page.

### `frontend/src/views/Observatory.jsx`
- Field wrappers `w-44/w-28/w-52` → `w-full min-[500px]:w-…`: inputs stack full-width on phones, original widths return at ≥500px.
- Run Analysis button full-width on mobile (`max-[768px]:w-full ml-0`). Charts already scale to container width (`width:100%` canvases, 1-col grid on mobile) — no change needed.

### `frontend/src/views/HistoryView.jsx`
- Both tables (Past Runs, Discoveries) wrapped in `overflow-x-auto` divs — panel-internal horizontal scroll on mobile; header row wraps.

### `frontend/src/views/QaBenchmarks.jsx`
- Header wraps; Run QA Suite / Run QA check buttons full-width on mobile. Custom-check fields stack full-width (`w-full sm:w-44/w-40`).
- One correction during QA: header alignment is `items-start` only ≤768px and `min-[769px]:items-center` (the original) above — an unconditional `items-start` shifted the desktop button by a few px and failed the desktop gate on the first pass; fixed and re-verified.

### `frontend/src/views/Guide.jsx`
- Page padding `p-6` → `p-4 sm:p-6` (desktop `lg:p-8` unchanged). Content was already single-column fluid; verified readable at 390px.

### `frontend/src/components.jsx`
- `ProgressLog` lines get `whitespace-pre-wrap break-words` — long log lines now wrap inside the panel on narrow screens instead of overflowing (the History expansion rows already wrapped; this closes the same gap for live job logs).

`frontend/index.html` already carried the correct viewport meta — no change.

## Verification method

Test server: `uvicorn api:app` on **port 8001 only** (port 8000 never touched), serving the built `frontend/dist`. Screenshots driven by the Remotion headless Chrome shell over CDP (`/tmp/shot_driver.mjs`): real nav-button clicks per view (the app switches views by React state — no router/hash), mobile runs open the hamburger menu to reach non-home views. Shots in `responsive_shots/`.

## Gates

### Desktop gate (≥1025px must be layout-identical) — **PASS, pixel-perfect**
SHA-256 of BEFORE vs AFTER screenshots at 1440×1000 — **all six views byte-identical**: Scanner, Guide, Observatory, Sweeper, QA Benchmarks, History. Zero pixel differences.

### Mobile gate (390×844) — **PASS**
- `document.documentElement.scrollWidth` = 390 (= clientWidth) on **every** view.
- Element-level audit (all elements inside `main`, excluding sanctioned `overflow-x:auto` panel scrollers and internal scroll containers): **zero offenders** extending past the viewport on any view; `main` width = 390px (was ~134px before).
- Range inputs measure **40px** tall (Scanner ×2, Observatory ×1 sampled programmatically).
- Visual inspection of every view: forms fully stacked and operable, all labels + range text unclipped, Scanner's Initialize Scan full-width, Guide reads at full measure, History tables scroll inside their panels, menu-open state shows all nav items + Global Settings (see `after_menu-open_390x844.png`).
- Audit data: `responsive_shots/after_overflow_audit_390.json`, `before/after_metrics_{390x844,1440x1000}.json`.

## Screenshot index (`responsive_shots/`)

- `before_{scanner,guide,observatory,sweeper,benchmarks,history}_{390x844,1440x1000}.png` — 12 files
- `after_{scanner,guide,observatory,sweeper,benchmarks,history}_{390x844,1440x1000}.png` — 12 files
- `after_menu-open_390x844.png` — mobile menu expanded (nav + Global Settings)
- Metrics/audit JSONs as above. No view was left unscreenshotted.

## Data safety

- `data/hunter.db` md5 before = after: `33b70438b3669f9c313b510488d20d48`
- `discoveries.csv` md5 before = after: `2c8abaae5be0456af6a7effa8a22b6ff`
- Port-8001 test server **stopped** after the run; port 8000 untouched.
