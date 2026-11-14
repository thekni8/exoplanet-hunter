# Exoplanet Hunter — Stage 2 Report

**Date:** 2026-11-02 · **Scope:** Stage 2 only — FastAPI job-queue API layer
around the Stage 1 engine (`hunter.py`, imported, **not modified**).
No frontend/React work, no deployment, no git commits or pushes.

## What was built

### `api.py` — FastAPI app (uvicorn, port 8000)

| Endpoint | Behaviour |
|---|---|
| `GET /health` | `{"ok": true}` |
| `POST /api/analyze` | `{tic_id, host_radius=1.0, sector_cap=null, bls_points=25000, detrend_window=101, min_period=0.5, max_period=25.0, pipelines?}` → `{job_id, status:"queued"}` |
| `POST /api/sweep` | `{ra, dec, cone=0.15, limit=50, min/max_mag, min/max_rad, bls_points=10000, sector_cap=2, detrend_window=101}` → queued job |
| `POST /api/qa` | Queued job running Dev's 3 benchmarks at his QA settings (1–2 sectors, grid 10000) |
| `GET /api/jobs/{id}` | status (`queued/running/done/failed`), full progress list, error, result summary when done |
| `GET /api/jobs/{id}/result` | Full result JSON (analyze: the `analyze_target_json` payload, read from `data/results/<job_id>.json`); 409 until done |
| `GET /api/jobs/{id}/plate` | The diagnostic PNG (analyze jobs); 404 if none |
| `GET /api/history` | Recent runs newest-first (id, type, target, params, status, period, sde, created/finished, error), `?limit=` |
| `GET /api/discoveries` | Hits-only discoveries table rows |

### Design choices (driven by Dev's requirements answers)

- **Single background worker thread** consuming an in-process queue.
  Jobs run strictly one at a time, in submission order — one user's heavy
  run cannot crash or interleave with another's, and a job is never tied
  to an HTTP request staying open.
- **SQLite persistence** (`data/hunter.db`, stdlib `sqlite3`): every job
  (params, status, progress, error, result summary, result/plate paths)
  and every discovery is stored, so history survives restarts. At
  startup, jobs left `running` are marked `failed: server restarted`;
  jobs left `queued` are re-enqueued.
- **Progress** comes from `hunter.py`'s `progress_callback` bridge:
  each message is appended to the job's progress list in the DB and
  exposed by `GET /api/jobs/{id}`.
- **Discoveries are HITS ONLY (SDE ≥ 8.5)** in the API layer's own
  `discoveries` table. `hunter.py`'s `discoveries.csv` behaviour is
  untouched (CLI path still logs everything, as in Dev's original).
- **Charts are static for v1**: the PNG `hunter.py` renders is copied to
  a per-job path (`data/plates/<job_id>.png`, so re-running the same TIC
  can't overwrite an earlier job's plate) and served by the plate
  endpoint. Full result JSON is stored at `data/results/<job_id>.json`.
- **Sweep** is implemented via the JSON path (not `sweep_sky`): the job
  does the same TIC cone query + Tmag/radius screening as
  `hunter.sweep_sky`, then calls `analyze_target_json` per target
  sequentially with `Target n of N` progress, collects hits at
  SDE ≥ 8.5, records per-target errors in progress and **always finishes
  the full list**. `limit` is respected as requested — no hard cap in
  the API layer.
- **QA** calls `hunter.run_qa` with a progress callback; the job result
  is per-benchmark recovered vs expected period + `PASS`/`DRIFT`
  (PASS = |Δ| < 0.05 d, Dev's band).
- **Cache**: this layer never purges the MAST cache. (`hunter.py` only
  purges on an explicit manual CLI/menu action.)
- **`pipelines` field**: accepted on `POST /api/analyze` and recorded in
  the job params, but **not wired into the engine** — `hunter.py`
  hardcodes its author filter to `["SPOC","TESS-SPOC","QLP"]` with an
  unfiltered fallback (Dev's original spec), and Stage 2's constraint
  was not to change `hunter.py`'s behaviour. Wiring it through needs a
  small `hunter.py` change — flagged for a later stage.

### Packaging

- `requirements.txt`: added `fastapi`, `uvicorn` (installed into the
  existing `.venv`: fastapi 0.162.0, uvicorn 0.54.0).
- `Dockerfile`: `python:3.12-slim` (ARM + x86_64), installs
  requirements, copies `hunter.py api.py app.py`, port 8000,
  `uvicorn api:app`; build/run commands are in the file's comments.
  Host-agnostic by design, so the hosting target can change without a
  rebuild. (Mid-stage, Dev decided hosting = GitHub Codespaces; the
  same `uvicorn api:app --port 8000` command runs there.)
- `.gitignore` / `.dockerignore`: `data/`, `.venv/`, `__pycache__/`,
  `reports/`, `results/`, `discoveries.csv` ignored — verified:
  `git status` shows `api.py`, `Dockerfile`, `.gitignore`,
  `.dockerignore` as new files and **no** `data/` entry.
  (`STAGE1_REPORT.md`, `hunter.py`, `.devcontainer/`, `CODESPACES.md`
  in git status are from Stage 1 / the parent agent, not Stage 2.)

## Test — real run, this VM, real API (with an upstream failure)

Server: `.venv/bin/uvicorn api:app --host 127.0.0.1 --port 8000`.

### What passed

1. **`GET /health`** → `{"ok": true}`, HTTP 200. **All 9 routes**
   registered (verified via `/openapi.json`).
2. **Invalid-TIC job** `a132920cd84a4d09`
   (`tic_id=999999999999, sector_cap=1, bls_points=2000`):
   **failed in ~8 s** with `RuntimeError: No mission data found for
   TIC 999999999999.` — real error in the job record and progress list,
   not a hang.
3. **Queue survival & ordering**: the valid WASP-126 b job
   `66b7ebf5a59048d6` was submitted *immediately after* the invalid job,
   sat queued behind it, and the worker started it the second the
   invalid job finished (started_at = invalid's finished_at,
   02:24:04 UTC). After that job also failed (below), a third job was
   submitted and likewise processed — the worker never wedged.
4. **Error contracts**: `GET /api/jobs/{failed}/result` → **409**
   (`job is failed, no result yet`); `GET /api/jobs/{failed}/plate` →
   **404**; unknown job id → **404**.
5. **History**: `GET /api/history` returns all runs newest-first with
   params, status, and errors — contents verified in the DB
   (`jobs` table: 3 rows; `discoveries` table: 0 rows, see below).
6. **Restart persistence (true restart)**: server process killed,
   port confirmed free, fresh uvicorn started — startup completed and
   `/api/history` returned all 3 prior jobs with correct terminal
   statuses. (Note: a first restart attempt was invalidated when the
   original server turned out to still be alive and the new instance
   failed to bind; the test was redone properly against a confirmed-free
   port. Only the redo is claimed as evidence.)

### What did NOT pass — MAST upstream failure (honest)

7. **Valid analyze job** `66b7ebf5a59048d6`
   (TIC 25155310, host_radius 1.30, sector_cap 2, bls_points 8000 —
   the Stage 1 test parameters): **FAILED after ~274 s** inside the
   very first pipeline step, with:
   `ProxyError: HTTPSConnectionPool(host='mast.stsci.edu', port=443):
   Max retries exceeded with url: /api/v0/invoke (Caused by
   ProxyError('Unable to connect to proxy',
   RemoteDisconnected('Remote end closed connection without response')))`
8. **The one permitted retry** — fresh job `077033cf0ed74f4f`, same
   parameters: **FAILED identically** (~272 s, 02:28:45→02:33:17 UTC),
   same ProxyError at the same step. Per the Stage 2 brief, no further
   retries were attempted.
9. **Diagnosis**: the failure is in this VM's egress path to MAST's
   invoke API, not in the API or engine code. Evidence: plain
   `curl https://mast.stsci.edu/` through the same proxy returns
   HTTP 301 in 0.5–1.2 s (3/3 attempts, after the failures); the
   invalid-TIC job's invoke call succeeded minutes earlier (that's how
   it learned there is no data); and Stage 1 ran the *identical*
   search + download successfully at ~02:01–02:06 UTC today. The
   pattern — invoke POSTs dropping under astroquery's retries while
   simple GETs pass — points to the VM egress proxy resetting those
   requests during that window. Root cause beyond that is not
   determinable from inside this VM.

### Consequences for verification

Because no analyze job reached the download/BLS steps in Stage 2, the
following are **NOT yet verified end-to-end through the API** (they are
implemented and their error paths are verified):

- analyze job reaching `done` with period ≈ 3.29 d / SDE ≈ 21.9
  (the *engine* produced exactly those numbers in Stage 1's verified
  CLI run over the same `_run_pipeline` code path — engine evidence,
  not API evidence);
- the plate endpoint returning a PNG for a done job;
- a discoveries row being inserted (SDE 21.9 ≥ 8.5 would qualify);
  the `discoveries` table is currently **empty, correctly** — the
  hits-only rule's positive case is unverified for the same upstream
  reason, its negative behaviour (no rows from failed/no-hit runs) is
  confirmed by the 0-row table;
- sweep and QA job *executions* (endpoints accept and queue; running
  them during the test would only have queued more calls into the
  same failing upstream);
- the Docker build (docker is not installed on this VM — the
  Dockerfile is written and reviewed, not build-tested).

**To close the verification gap** (no code change needed): when MAST
via this proxy is healthy, submit the same analyze job and poll it —
expect `done` in ~25 s–5 min (Stage 1: 23.6 s warm-cache), period
3.29029 d, SDE 21.9, then check `/result`, `/plate`, `/history`,
`/discoveries`. On the real hosting target (Codespaces), MAST is
reached directly without this VM's proxy, so this specific failure
mode does not apply there.

## State left behind

- Test server **left running** on `127.0.0.1:8000` (uvicorn, logs in
  `/tmp/hunter-api3.log`) with `data/hunter.db` containing the 3 test
  jobs above — real history for the Stage 3 UI to display. Stop it
  with `pkill -f "uvicorn api:app"` if a clean port is needed.
- Working tree (uncommitted, unpushed): new `api.py`, `Dockerfile`,
  `.gitignore`, `.dockerignore`, `STAGE2_REPORT.md`; modified
  `requirements.txt` (+fastapi, +uvicorn). `hunter.py` untouched.
