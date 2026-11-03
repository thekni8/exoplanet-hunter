# History Log Fix — dead jobs get a viewable, self-explaining log

**Date:** 2026-11-03 · **Status:** built + tested on Pingu's server, NOT pushed
(parent pushes after review).

## The gap

Every job's progress lines were already persisted (`jobs.progress_json`)
and served by `GET /api/jobs/{id}`, but the History page offered no way to
open them: a failed run showed only the first 160 characters of its error.
Worse, a job killed by a server restart (Codespace stop, crash) trailed off
mid-log with no explanation of why it stopped — the exact failure Dev hit
when his CVZ sweep's record read "failed / server restarted" with no log
to inspect.

## What changed

### 1. `api.py` — `_startup()` appends a closing line to restart-killed jobs

The startup hook already stamps stale `running` jobs as
`failed` / `error='server restarted'`. It now collects those job ids
**before** stamping, and after the existing UPDATE calls `append_progress`
once per stamped job with exactly this line:

> Server restarted while this job was running — it did not finish. Everything above is the complete record up to the stop.

The error string `'server restarted'` is unchanged. No other backend
behaviour changed.

### 2. `frontend/src/views/HistoryView.jsx` — per-run "Log" toggle

- New `RunRow` component (the runs table now renders rows through it),
  following the existing `DiscoveryRow` expansion pattern in the same file.
- Every run row — any type, any status — gets a **Log** button
  (FileText icon, same zinc button styling as "View result").
- Clicking it opens a full-width expansion row under the run that lazily
  fetches `getJob(r.job_id)` **once** and renders:
  - the job's **full** error, if any (red, mono, pre-wrap), then
  - **all progress lines in order** (mono, `text-[11px]`, zinc-400).
  - "Loading log…" while the fetch is in flight; a plain
    "Could not load this run's log: …" message if it fails; a
    "No progress lines recorded for this run." note if the log is empty.
- The existing "View result" button for done analyze jobs is unchanged
  (same handler, same styling, now sitting beside Log).

### 3. Frontend dist rebuilt

`npm run build` in `frontend/` (the same command run.sh runs; node_modules
was already present). Build succeeded with no errors.

- New bundle: **`index-D7gdKUoE.js`** (234,219 bytes)
- CSS: `index-D9VV5TYh.css` — hash unchanged (no style changes)
- `frontend/dist/index.html` updated to reference the new bundle
- Old bundle `index-OYu1Pmn1.js` removed by the build

## Test evidence (this server, port 8000)

**Seed test.** Backed up `data/hunter.db`, started the server, submitted a
real sweep job via `POST /api/sweep` (job `99e31d22a3594059`), stopped the
server, then set that row directly in sqlite to the frozen-mid-run state:

```json
{"job_id":"99e31d22a3594059","status":"running","error":null,
 "progress":["Job 99e31d22a3594059 started (sweep).",
             "Querying TIC catalog around RA 10.0, Dec -80.0 (radius 0.01 deg)...",
             "Screened 1 target(s); starting sweep..."]}
```

Restarted the server. `GET /api/jobs/99e31d22a3594059` then returned:

```json
{"job_id": "99e31d22a3594059", "type": "sweep",
 "target": "Sweep RA 10.0 Dec -80.0",
 "status": "failed", "error": "server restarted",
 "progress": ["Job 99e31d22a3594059 started (sweep).",
              "Querying TIC catalog around RA 10.0, Dec -80.0 (radius 0.01 deg)...",
              "Screened 1 target(s); starting sweep...",
              "Server restarted while this job was running — it did not finish. Everything above is the complete record up to the stop."]}
```

✅ status stamped `failed`, error string unchanged, original progress
preserved, closing line appended as the final entry. The run also appeared
in `GET /api/history` as `failed / server restarted`.

**Regression.** On the test DB and again on the restored DB:
`GET /api/history` → HTTP 200 (42 runs on the restored DB),
`GET /api/discoveries` → HTTP 200.

**DB backup/restore.** Backup taken before any test writes
(`/tmp/hunter.db.bak-historylog`); restored afterwards and verified
byte-identical (md5 `7c23041c32f8403445c7e836691bfe70` both sides). The
seed job exists only in the discarded test state. Test servers were
stopped; port 8000 is free.

## Files changed (for the push)

- `api.py`
- `frontend/src/views/HistoryView.jsx`
- `frontend/dist/index.html`
- `frontend/dist/assets/index-D7gdKUoE.js` (new; `index-OYu1Pmn1.js` deleted)
- `HISTORY_LOG_FIX_REPORT.md` (this file)
