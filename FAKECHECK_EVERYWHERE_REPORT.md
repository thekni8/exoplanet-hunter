# Fake-Check Everywhere — Report

**Date:** 2026-11-03 · **Scope:** frontend only (`api.py` untouched — `POST /api/oddeven` already existed and is proven). The "Is it a fake? →" odd/even check, previously reachable only from Scanner hit cards, is now offered on every star the app shows: Observatory results, Sweeper hits, and History & Discoveries rows. QA Benchmarks deliberately untouched (known reference targets).

## Shared component — `frontend/src/fakecheck.jsx` (new)

Extracted verbatim from Scanner's Stage-4 flow; three exports:

- **`FakeCheckToggleButton({ open, busy, onToggle })`** — the amber button with the ShieldAlert icon and label `Is it a fake? →`, pixel-identical classes to Scanner's original. One addition: `disabled:opacity-50`, visible only while disabled (see busy rule below).
- **`FakeCheck({ tic, period, onBusyChange })`** — the job body, moved unchanged in behaviour: on mount it posts `{ tic: String(tic), period: Number(period), sector_cap: 2 }` to `/api/oddeven`, polls via `useJobPolling`, fetches the full payload from `/api/jobs/{id}/result`, and renders — queued/running line with spinner → verdict box in Scanner's exact presentation (plain-language sentence per verdict, odd/even depth %s, % difference, fitted period, sector count, `OddEvenChart` on `result.folded`). Verdict wording comes from the component's plain-sentence map, falling back to the API's `verdict_text`.
- **`FakeCheckButton({ tic, period })`** — the one-piece widget (own open/busy state; toggle + panel expanding inline beneath it) for block layouts.

Two deliberate, documented deltas vs. the old Scanner-only code, both spec'd in the task brief:

1. **Busy disabling** — `FakeCheck` reports busy (no result/error/failure yet) via `onBusyChange`; the owning toggle is disabled while its check is queued/running, so one instance can never start a second job. Unmount resets busy.
2. **Failed jobs surface their error** — if the polled job ends `failed`, the panel shows `Fake-check failed: {job.error}` in the same red mono style as a failed submit. (The old code spun forever in that case; the success path is byte-for-bit the same rendering.)

## Per-view wiring

| View | Where | Data used | Composition |
|---|---|---|---|
| **Scanner** (`views/Scanner.jsx`) | Hit cards (strong + weaker rows), unchanged layout | `hit.tic_id`, `hit.period_days` | Refactored onto the shared module: `FakeCheckToggleButton` in the card's button row + `FakeCheck` panel in its original slot below. Local `FakeCheck`/`VERDICT_PLAIN` copies deleted; unused imports (`ShieldAlert`, `getJobResult`, `OddEvenChart`) removed. No appearance/behaviour change on the working path. |
| **Observatory** (`views/Observatory.jsx`) | Directly under the metrics grid + classification line of a completed analysis | `metrics.tic_id`, `metrics.best_period_days` | One-piece `FakeCheckButton` widget; panel expands inline in place. |
| **Sweeper** (`views/Sweeper.jsx`) | Each hit row's actions cell, beside "Open in Observatory" | `h.tic_id`, `h.period_days` | New `HitRow` component (own open/busy state): toggle in the row; when open, a full-width expansion `<tr>` (`colSpan=9`, `bg-zinc-950/40`) carries `FakeCheck`. |
| **History & Discoveries** (`views/HistoryView.jsx`) | Each discovery row (new trailing actions column) | `d.tic_id`, `d.period_days` | New `DiscoveryRow` component, same pattern; expansion `<tr>` with `colSpan=9`. Field names verified against the live view payload (`tic_id`, `period_days` — the same fields the table already renders; `GET /api/discoveries` returns `{discoveries: [...]}`). |

## Build

- `npm run build` ✅ — JS **`index-vtTY13EG.js` 225.83 kB (gzip 67.97 kB)**, CSS `index-BL3vLpjt.css` 22.32 kB. Previous bundle was 224.25 kB JS → +1.6 kB for three new placements (the flow itself was already shipped via Scanner).
- Bundle grep: `Is it a fake?`, `The two dips match`, `Running the odd/even test on real TESS data`, `Fake-check failed` all present in `index-vtTY13EG.js`.
- Component usage (source grep): all four views import from `../fakecheck.jsx` — Scanner (toggle + panel), Observatory (widget), Sweeper (toggle + panel in `HitRow`), HistoryView (toggle + panel in `DiscoveryRow`).

## Smoke + live API verification

- Server restarted via `bash run.sh`; `GET /health` → `{"ok":true}`; `GET /` serves the new bundle hash `index-vtTY13EG.js`.
- **Real end-to-end check through the component's exact call:** `POST /api/oddeven {"tic":"308851365","period":0.75873,"sector_cap":2}` → job `bdcb982908c14d2e` → **done**. `GET /api/jobs/{id}/result` shape matches everything the component renders:
  - `metrics.verdict` = **"planet-like"** ✓
  - `metrics.verdict_text` present ("The two dips match — odd transits dip 0.756% and even transits dip 0.886%, within 15% of each other…")
  - `metrics.depth_odd_percent` 0.756 · `metrics.depth_even_percent` 0.886 · `depth_rel_diff` 0.147 · `period_fit_days` 0.75668 · `sectors_analyzed` 2
  - `folded` = `{ points.time_days (1,900 pts), binned.flux (60), range_days, center_odd_days −0.37834, center_even_days +0.37834 }` — exactly the fields `OddEvenChart` consumes.
- **Depth discrepancy, explained with evidence:** the earlier reference run for this star (job `f69acf9f8ab34898`, same server DB) reported 1.312% / 1.260%. Its stored result shows `sectors_analyzed: 12` (12,578 points) — it ran uncapped over all surviving sectors. The UI flow has always capped the fake-check at 2 sectors (Scanner's original payload), so depths measured on the 2-sector subset differ (0.756% / 0.886%) while the fitted period (0.75668 vs 0.75638 d) and the **planet-like verdict agree**. Depths are subset-dependent; the verdict is stable.

## Files changed

- `frontend/src/fakecheck.jsx` (new)
- `frontend/src/views/Scanner.jsx` (refactor onto shared module)
- `frontend/src/views/Observatory.jsx` (+ widget on completed analysis)
- `frontend/src/views/Sweeper.jsx` (+ `HitRow` with toggle + expansion row)
- `frontend/src/views/HistoryView.jsx` (+ `DiscoveryRow`, actions column)
- `frontend/dist/` (rebuilt: `index.html`, `assets/index-vtTY13EG.js`, `assets/index-BL3vLpjt.css`)

Nothing committed or pushed — parent agent handles GitHub. Dev's ritual after the push is unchanged: `git pull` → restart → Cmd+Shift+R hard refresh.
