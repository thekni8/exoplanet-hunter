# History Log Refresh Fix — Report

**Date:** 2026-11-03 · **Scope:** frontend only (`HistoryView.jsx` + rebuilt dist) · **Status:** built and tested locally, NOT pushed (parent pushes after review)

## The bug

The Log expansion added earlier today fetched `getJob(job_id)` exactly once — when the row was first opened — and cached the result in `RunRow` state. The History page's Refresh button refetched the runs/discoveries lists, but nothing ever invalidated a `RunRow`'s cached job. An open log (the canonical case: a still-running sweep) stayed frozen at open-time forever; the only way to see new progress lines was to close and reopen the log — and even that didn't refetch, because the one-shot guard blocked it. The user hit this live while watching his CVZ sweep: Refresh updated the lists but not the open log window.

## The fix (all in `frontend/src/views/HistoryView.jsx`)

1. **`refreshTick` in `HistoryView`.** A new state counter increments at the top of every `load()` call — the mount load and every Refresh click alike — and is passed as a prop to every `RunRow`.
2. **Tick-driven refetch in `RunRow`.** Each row remembers the last tick it saw (`prevTickRef`). A `useEffect` on `[refreshTick, showLog, fetchLog]` compares: if the tick actually changed **while the log is open** and a fetch has already been attempted once, it refetches `getJob(job_id)` and re-renders progress/error/status. Tick changes while the log is closed only move the baseline — no fetch. Because rows mount only after the initial `load()` resolves, each row's baseline starts at the post-initial-load tick, so the first load never causes a spurious refetch.
3. **Self-polling for live jobs.** A second effect starts a 5-second `setInterval(fetchLog)` only while **both** conditions hold: the log is open, and the last fetched job status is `queued` or `running` (`isLive`). Cleanup clears the interval when the log closes, when the component unmounts, and — via `isLive` flipping false — as soon as a poll observes a terminal status (`done`/`failed`). Closed rows and finished jobs never fetch.
4. **Preserved behaviour.** Lazy first fetch on first open (one-shot, now guarded by an `attemptedRef` with the same semantics as the old `log === null && logError === null` guard), the "Loading log…" state, the "Could not load this run's log: …" error message, the full-error + progress-line rendering, and the 'View result' button are all unchanged. One deliberate improvement within spec: if a first fetch errored, a Refresh click while the log is open now retries and clears the error on success (previously an error was permanent for the life of the row). No backend changes.

## Code-review notes (self-review of the diff)

- **Interval hygiene:** exactly one interval can exist per row, and only in the open+live state; every state transition out of that state runs the cleanup. Opening a second row's log doesn't disturb the first row's interval.
- **No fetch storms:** the tick refetch fires at most once per actual tick change per open row; the poll is per open+live row at 5 s. A user with one log open on a running sweep generates one request per 5 s plus one per Refresh click.
- **No duplicate fetch on open:** opening flips `showLog`, which re-runs the tick effect, but `tickChanged` is false at that moment, so no second fetch follows the toggle's initial one.
- **In-flight fetch after close/unmount:** a resolving `fetchLog` only writes component state (a no-op after unmount under React 18); no timers are bound to the fetch itself, so nothing leaks.

## Test evidence

- **Build:** `npm run build` in `frontend/` (the run.sh route) completed with no errors — vite 5.4.21, 1593 modules, built in 2.69 s. New bundle **`index-B0KaLpKw.js`** (234,597 bytes); `frontend/dist/index.html` now references it and the previous bundle `index-D7gdKUoE.js` was removed by the build. CSS asset unchanged (`index-D9VV5TYh.css`, same hash as before).
- **Backend truth the UI now tracks (live API test, scratch port 8001):** started the API, submitted a real 1-target sweep (job `41797ea1ef364bc1`, RA 124.456 / Dec −67.568, first target TIC 307164903), and polled `GET /api/jobs/{id}`:
  - t+3 s — status `running`, **2** progress lines (started; querying catalog)
  - t+18 s — status `running`, **5** progress lines (…screened 1 target; Target 1 of 1: TIC 307164903; querying MAST)
  - t+38 s — status `running`, **8** progress lines (…downloading 2 sectors; running BLS; refining depth…)
  
  Progress grew 2 → 5 → 8 while the job stayed `running` — precisely the updates the old UI froze out and the fixed UI now surfaces via the Refresh tick and the 5 s poll.
- **Cleanup of the test:** test server stopped (no uvicorn processes remain, port 8001 free); the project DB was backed up before the test and restored after — md5 `7c23041c32f8403445c7e836691bfe70` before and after, byte-identical, so the test job left no trace in the real history. Port 8000 was never touched (no server was running there).
- **Honesty note:** UI click-through behaviour was **not** browser-tested. Verification is: production build success, full code review of the diff (above), and the API evidence showing the data the component now re-reads genuinely changes over time.

## Files changed (for the push)

| File | Change |
|---|---|
| `frontend/src/views/HistoryView.jsx` | refreshTick state + prop; RunRow refetch-on-tick effect; 5 s self-poll for open live logs |
| `frontend/dist/index.html` | bundle reference `index-D7gdKUoE.js` → `index-B0KaLpKw.js` |
| `frontend/dist/assets/index-B0KaLpKw.js` | NEW built bundle (replaces `frontend/dist/assets/index-D7gdKUoE.js`, which the build deleted) |
| `HISTORY_LOG_REFRESH_FIX_REPORT.md` | this report |

`frontend/dist/assets/index-D9VV5TYh.css` is byte-identical to the previous build (same content hash) and needs no push. No backend files changed.
