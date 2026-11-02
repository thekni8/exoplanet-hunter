#!/usr/bin/env python3
"""
Exoplanet Hunter — Stage 2 API layer (FastAPI).

Wraps the Stage 1 engine (hunter.py) in a job-queue API:

  * Jobs are BACKGROUND jobs. POST returns immediately with a job_id;
    a single worker thread runs jobs one at a time, in submission order,
    so one user's heavy run can never crash or interleave with another's.
  * A job is never tied to an HTTP request staying open. Clients poll
    GET /api/jobs/{id} for status + progress (progress strings come from
    hunter.py's progress_callback bridge).
  * Every run is persisted in SQLite at data/hunter.db, so history
    survives restarts. Jobs left "running" when the server died are
    marked "failed: server restarted" at startup; jobs left "queued"
    are re-enqueued.
  * DISCOVERIES ARE HITS ONLY: a row is written to the discoveries
    table only when SDE >= 8.5. (hunter.py's own discoveries.csv
    behaviour is untouched — it still logs everything on the CLI path,
    exactly as Dev's original does.)
  * The MAST download cache is never purged by this layer. hunter.py
    only purges on an explicit manual CLI/menu action.
  * Charts are static for v1: the 300 DPI diagnostic PNG hunter.py
    renders is the chart deliverable, served by GET /api/jobs/{id}/plate.

Endpoints:
  POST /api/analyze          {tic_id, host_radius, sector_cap, bls_points,
                              detrend_window, min_period, max_period,
                              pipelines?}
  POST /api/sweep            {ra, dec, cone, limit, mag/rad filters,
                              bls_points, sector_cap, scanner?}
  POST /api/oddeven          {tic, period, sector_cap?} — Stage 4: v1's
                              odd/even eclipsing-binary fake-check
  POST /api/qa               run Dev's 3 QA benchmarks (1-2 sectors, 10k grid)
  GET  /api/jobs/{id}        status / progress / error / result summary
  GET  /api/jobs/{id}/result full result JSON
  GET  /api/jobs/{id}/plate  diagnostic PNG (analyze jobs)
  GET  /api/history          recent runs, newest first (?limit=)
  GET  /api/discoveries      hits-only table
  GET  /health               {ok: true}

Note on `pipelines`: hunter.py's engine hardcodes its author filter to
["SPOC", "TESS-SPOC", "QLP"] with an unfiltered fallback (Dev's original
spec, not changed in Stage 2). The analyze request accepts and records a
`pipelines` field for forward compatibility, but the engine's filter is
what actually runs; see STAGE2_REPORT.md.
"""

import json
import os
import queue
import shutil
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

BASE_DIR = Path(__file__).resolve().parent
# hunter.py uses CWD-relative paths ("reports/", "discoveries.csv") —
# anchor them to the project root no matter where uvicorn is launched.
os.chdir(BASE_DIR)

DATA_DIR = BASE_DIR / "data"
RESULTS_DIR = DATA_DIR / "results"
PLATES_DIR = DATA_DIR / "plates"
DB_PATH = DATA_DIR / "hunter.db"
for _d in (DATA_DIR, RESULTS_DIR, PLATES_DIR):
    _d.mkdir(parents=True, exist_ok=True)

import hunter  # noqa: E402  (after chdir: hunter creates reports/ at import)

from fastapi import FastAPI, HTTPException  # noqa: E402
from fastapi.responses import FileResponse, JSONResponse  # noqa: E402
from pydantic import BaseModel  # noqa: E402

HIT_SDE = 8.5  # discoveries are hits only: SDE >= 8.5

# ---------------------------------------------------------------------------
# Storage (stdlib sqlite3; one short-lived connection per operation,
# writes serialized with a lock — the worker is single-threaded anyway)
# ---------------------------------------------------------------------------

_db_lock = threading.Lock()


@contextmanager
def db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with _db_lock, db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                id           TEXT PRIMARY KEY,
                type         TEXT NOT NULL,          -- analyze | sweep | qa | oddeven
                params_json  TEXT NOT NULL,
                target       TEXT,                   -- human summary for history
                status       TEXT NOT NULL,          -- queued|running|done|failed
                progress_json TEXT NOT NULL DEFAULT '[]',
                error        TEXT,
                result_json  TEXT,                   -- result summary (metrics / hits / benchmarks)
                result_path  TEXT,                   -- full result JSON on disk (analyze)
                plate_path   TEXT,                   -- diagnostic PNG (analyze)
                period       REAL,
                sde          REAL,
                created_at   TEXT NOT NULL,
                started_at   TEXT,
                finished_at  TEXT
            );
            CREATE TABLE IF NOT EXISTS discoveries (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id            TEXT,
                source            TEXT,              -- analyze | sweep
                tic_id            TEXT,
                period_days       REAL,
                sde               REAL,
                depth_percent     REAL,
                planet_radius_re  REAL,
                star_radius_rsun  REAL,
                sectors           INTEGER,
                created_at        TEXT NOT NULL
            );
            """
        )


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def create_job(job_type, params, target):
    job_id = uuid.uuid4().hex[:16]
    with _db_lock, db() as conn:
        conn.execute(
            "INSERT INTO jobs (id, type, params_json, target, status, created_at)"
            " VALUES (?, ?, ?, ?, 'queued', ?)",
            (job_id, job_type, json.dumps(params), target, _now()),
        )
    return job_id


def update_job(job_id, **fields):
    if not fields:
        return
    cols = ", ".join(f"{k} = ?" for k in fields)
    with _db_lock, db() as conn:
        conn.execute(f"UPDATE jobs SET {cols} WHERE id = ?",
                     (*fields.values(), job_id))


def get_job(job_id):
    with db() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return dict(row) if row else None


def append_progress(job_id, message):
    with _db_lock, db() as conn:
        row = conn.execute("SELECT progress_json FROM jobs WHERE id = ?",
                           (job_id,)).fetchone()
        if row is None:
            return
        progress = json.loads(row["progress_json"])
        progress.append(str(message))
        conn.execute("UPDATE jobs SET progress_json = ? WHERE id = ?",
                     (json.dumps(progress), job_id))


def record_discovery(job_id, source, metrics):
    """Hits only: the caller checks SDE, this just writes the row."""
    with _db_lock, db() as conn:
        conn.execute(
            "INSERT INTO discoveries (job_id, source, tic_id, period_days, sde,"
            " depth_percent, planet_radius_re, star_radius_rsun, sectors, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (job_id, source, metrics.get("tic_id"), metrics.get("best_period_days"),
             metrics.get("sde"), metrics.get("depth_percent"),
             metrics.get("planet_radius_earth"), metrics.get("host_radius_solar"),
             metrics.get("sectors_analyzed"), _now()),
        )


# ---------------------------------------------------------------------------
# Job execution (single background worker)
# ---------------------------------------------------------------------------

_job_queue: "queue.Queue[str]" = queue.Queue()
_worker_started = False


def _run_analyze(job_id, p):
    result = hunter.analyze_target_json(
        p["tic_id"],
        star_radius=p.get("host_radius", 1.0),
        min_p=p.get("min_period", 0.5),
        max_p=p.get("max_period", 25.0),
        bls_points=p.get("bls_points", 25000),
        max_sectors=p.get("sector_cap"),
        detrend_window=p.get("detrend_window", 101),
        progress_callback=lambda msg: append_progress(job_id, msg),
    )
    metrics = result["metrics"]

    result_path = RESULTS_DIR / f"{job_id}.json"
    result_path.write_text(json.dumps(result))

    # hunter.py renders the plate to reports/TIC_<id>_diagnostic.png —
    # copy it to a per-job path so later runs of the same TIC can't
    # overwrite this job's plate.
    plate_path = None
    src_png = BASE_DIR / "reports" / f"TIC_{metrics['tic_id']}_diagnostic.png"
    if src_png.exists():
        dst_png = PLATES_DIR / f"{job_id}.png"
        shutil.copyfile(src_png, dst_png)
        plate_path = str(dst_png)

    if metrics["sde"] >= HIT_SDE:
        record_discovery(job_id, "analyze", metrics)

    update_job(job_id, status="done", finished_at=_now(),
               result_json=json.dumps(metrics), result_path=str(result_path),
               plate_path=plate_path, period=metrics["best_period_days"],
               sde=metrics["sde"])
    append_progress(job_id, "Done.")


def _run_sweep(job_id, p):
    """Sweep job: TIC cone query + screening (same as hunter.sweep_sky),
    then analyze_target_json per target, sequentially, ALWAYS finishing
    the full target list. Per-target errors are recorded in progress and
    the sweep continues (hunter's original behaviour).

    Stage 4 — scanner mode (p["scanner"] true) applies Gemini v1's
    recipe on top of the same machinery: the catalog screen is forced
    to v1's faint-dwarf filter (Tmag 13.5-15.4, radius 0.2-1.5 R_sun,
    ignoring the request's filter values), and every candidate is run
    through hunter.is_already_known_online (Zooniverse) BEFORE any
    download; known stars are skipped and counted in the summary's
    "skipped_known". Discoveries logging is unchanged (hits only,
    SDE >= 8.5) — the SDE >= 11 "unflagged signal" bar is presentation
    only, applied by the Scanner UI.
    """
    import astropy.units as u
    from astropy.coordinates import SkyCoord
    from astroquery.mast import Catalogs

    ra, dec = p["ra"], p["dec"]
    cone = p.get("cone", 0.15)
    limit = p.get("limit", 50)
    bls_points = p.get("bls_points", 10000)
    sector_cap = p.get("sector_cap", 2)
    detrend_window = p.get("detrend_window", 101)
    scanner = bool(p.get("scanner", False))
    if scanner:
        min_mag, max_mag = 13.5, 15.4      # v1 scanner screen
        min_rad, max_rad = 0.2, 1.5
    else:
        min_mag, max_mag = p.get("min_mag", 11.5), p.get("max_mag", 15.0)
        min_rad, max_rad = p.get("min_rad", 0.5), p.get("max_rad", 1.8)

    def cb(msg):
        append_progress(job_id, msg)

    if scanner:
        cb("Scanner mode: hunting NEW, unflagged signals (v1 recipe — "
           "faint-dwarf screen, already-known stars skipped via Zooniverse).")
    cb(f"Querying TIC catalog around RA {ra}, Dec {dec} (radius {cone}°)...")
    coord = SkyCoord(ra=ra * u.deg, dec=dec * u.deg)
    tic_catalog = Catalogs.query_region(coord, radius=cone * u.deg, catalog="TIC")
    mask = (
        (tic_catalog["Tmag"] >= min_mag) & (tic_catalog["Tmag"] <= max_mag) &
        (tic_catalog["rad"] >= min_rad) & (tic_catalog["rad"] <= max_rad)
    )
    targets = tic_catalog[mask][:limit]
    total = len(targets)
    cb(f"Screened {total} target(s); starting sweep (no cap beyond requested limit={limit}).")

    analyzed, hits, errors = [], [], []
    skipped_known = 0
    for i, row in enumerate(targets, start=1):
        tic_id = str(row["ID"])
        star_rad = float(row["rad"])
        if scanner and hunter.is_already_known_online(tic_id):
            skipped_known += 1
            cb(f"Target {i} of {total}: TIC {tic_id} — already known on "
               f"Zooniverse, skipping (skipped {skipped_known} so far).")
            continue
        cb(f"Target {i} of {total}: TIC {tic_id} (R* = {star_rad:.2f} R_sun, Tmag = {float(row['Tmag']):.1f})")
        try:
            result = hunter.analyze_target_json(
                tic_id, star_radius=star_rad, bls_points=bls_points,
                max_sectors=sector_cap, detrend_window=detrend_window,
                progress_callback=cb,
            )
            m = result["metrics"]
            entry = {"tic_id": tic_id, "tmag": float(row["Tmag"]),
                     "star_radius_rsun": star_rad, "period_days": m["best_period_days"],
                     "sde": m["sde"], "planet_radius_re": m["planet_radius_earth"],
                     "sectors_analyzed": m["sectors_analyzed"]}
            analyzed.append(entry)
            if m["sde"] >= HIT_SDE:
                hits.append(entry)
                record_discovery(job_id, "sweep", m)
                cb(f"HIT: TIC {tic_id} — P={m['best_period_days']:.4f} d, SDE={m['sde']:.1f}")
        except Exception as e:  # recorded, not swallowed — sweep continues
            errors.append({"tic_id": tic_id, "error": str(e)})
            cb(f"Target {i} of {total}: TIC {tic_id} failed: {e}")

    summary = {"ra": ra, "dec": dec, "cone": cone, "targets_total": total,
               "targets_analyzed": len(analyzed), "hits": hits,
               "errors": errors,
               # Stage 4 (additive): scanner provenance + Zooniverse skips.
               "scanner": scanner, "skipped_known": skipped_known}
    best = max(hits, key=lambda h: h["sde"], default=None)
    update_job(job_id, status="done", finished_at=_now(),
               result_json=json.dumps(summary),
               period=(best["period_days"] if best else None),
               sde=(best["sde"] if best else None))
    done_msg = (f"Sweep complete: {len(hits)} hit(s) with SDE >= {HIT_SDE} "
                f"out of {total} target(s).")
    if scanner:
        done_msg += f" Skipped {skipped_known} already-known star(s)."
    cb(done_msg)


def _run_oddeven(job_id, p):
    """Odd/Even fake-check job (Stage 4): hunter.odd_even_test_json
    through the same queue. The full payload (metrics + folded arrays)
    is stored like an analyze result so /result returns the chart data;
    the metrics dict is the job summary. No discovery is recorded — this
    judges an existing candidate, it doesn't discover one.
    """
    result = hunter.odd_even_test_json(
        p["tic"],
        p["period"],
        sector_cap=p.get("sector_cap"),
        progress_callback=lambda msg: append_progress(job_id, msg),
    )
    metrics = result["metrics"]

    result_path = RESULTS_DIR / f"{job_id}.json"
    result_path.write_text(json.dumps(result))

    update_job(job_id, status="done", finished_at=_now(),
               result_json=json.dumps(metrics), result_path=str(result_path),
               period=metrics["period_fit_days"])
    append_progress(job_id, "Done.")


def _run_qa(job_id, p):
    def cb(msg):
        append_progress(job_id, msg)

    results = hunter.run_qa(progress_callback=cb)
    benchmarks = []
    for r in results:
        entry = {
            "name": r["name"], "tic_id": r["tic_id"],
            "expected_period_days": r["expected"],
            "recovered_period_days": r["recovered"],
            "diff_days": r["diff"],
            "status": ("PASS" if r["pass"] else "DRIFT"),
        }
        if r.get("result"):
            entry["sde"] = r["result"]["SDE"]
            entry["planet_radius_re"] = r["result"]["Radius_Re"]
        if r.get("error"):
            entry["error"] = r["error"]
        benchmarks.append(entry)
    summary = {"benchmarks": benchmarks,
               "passed": sum(1 for b in benchmarks if b["status"] == "PASS"),
               "total": len(benchmarks)}
    update_job(job_id, status="done", finished_at=_now(),
               result_json=json.dumps(summary))
    cb("QA complete.")


_RUNNERS = {"analyze": _run_analyze, "sweep": _run_sweep, "qa": _run_qa,
            "oddeven": _run_oddeven}


def _worker_loop():
    while True:
        job_id = _job_queue.get()
        try:
            job = get_job(job_id)
            if job is None or job["status"] not in ("queued",):
                continue
            update_job(job_id, status="running", started_at=_now())
            append_progress(job_id, f"Job {job_id} started ({job['type']}).")
            try:
                params = json.loads(job["params_json"])
                _RUNNERS[job["type"]](job_id, params)
            except Exception as e:
                update_job(job_id, status="failed", finished_at=_now(),
                           error=f"{type(e).__name__}: {e}")
                append_progress(job_id, f"FAILED: {type(e).__name__}: {e}")
        finally:
            _job_queue.task_done()


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(title="Exoplanet Hunter API", version="2.0-stage2")


@app.on_event("startup")
def _startup():
    global _worker_started
    init_db()
    # Jobs left "running" when the server died are dead — mark them failed.
    with _db_lock, db() as conn:
        conn.execute(
            "UPDATE jobs SET status='failed', error='server restarted',"
            " finished_at=? WHERE status='running'", (_now(),))
        # Jobs left "queued" never started — re-enqueue them.
        queued = [r["id"] for r in
                  conn.execute("SELECT id FROM jobs WHERE status='queued' ORDER BY created_at")]
    for job_id in queued:
        _job_queue.put(job_id)
    if not _worker_started:
        threading.Thread(target=_worker_loop, daemon=True, name="hunter-worker").start()
        _worker_started = True


class AnalyzeRequest(BaseModel):
    tic_id: str
    host_radius: float = 1.0
    sector_cap: Optional[int] = None
    bls_points: int = 25000
    detrend_window: int = 101
    min_period: float = 0.5
    max_period: float = 25.0
    pipelines: Optional[List[str]] = None


class SweepRequest(BaseModel):
    ra: float
    dec: float
    cone: float = 0.15
    limit: int = 50  # respected as requested — no hard cap in the API layer
    min_mag: float = 11.5
    max_mag: float = 15.0
    min_rad: float = 0.5
    max_rad: float = 1.8
    bls_points: int = 10000
    sector_cap: Optional[int] = 2
    detrend_window: int = 101
    # Stage 4: v1 Scanner recipe (faint-dwarf screen + Zooniverse
    # already-known skipping). Filters above are ignored when true.
    scanner: bool = False


class OddEvenRequest(BaseModel):
    tic: str
    period: float
    sector_cap: Optional[int] = None


class QaRequest(BaseModel):
    pass  # QA uses Dev's fixed benchmark settings (1-2 sectors, grid 10000)


def _submit(job_type, params, target):
    job_id = create_job(job_type, params, target)
    _job_queue.put(job_id)
    return {"job_id": job_id, "status": "queued"}


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/api/analyze")
def post_analyze(req: AnalyzeRequest):
    params = req.dict()
    return _submit("analyze", params, f"TIC {req.tic_id}")


@app.post("/api/sweep")
def post_sweep(req: SweepRequest):
    params = req.dict()
    return _submit("sweep", params, f"Sweep RA {req.ra} Dec {req.dec}")


@app.post("/api/qa")
def post_qa(req: Optional[QaRequest] = None):
    return _submit("qa", {}, "QA benchmarks")


@app.post("/api/oddeven")
def post_oddeven(req: OddEvenRequest):
    params = req.dict()
    return _submit("oddeven", params,
                   f"Odd/Even TIC {req.tic} @ {req.period} d")


@app.get("/api/jobs/{job_id}")
def get_job_status(job_id: str):
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    out = {
        "job_id": job["id"],
        "type": job["type"],
        "target": job["target"],
        "status": job["status"],
        "progress": json.loads(job["progress_json"]),
        "error": job["error"],
        "created_at": job["created_at"],
        "started_at": job["started_at"],
        "finished_at": job["finished_at"],
        "result": None,
    }
    if job["status"] == "done" and job["result_json"]:
        out["result"] = json.loads(job["result_json"])
    return out


@app.get("/api/jobs/{job_id}/result")
def get_job_result(job_id: str):
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    if job["status"] != "done":
        raise HTTPException(status_code=409,
                            detail=f"job is {job['status']}, no result yet")
    if job["result_path"] and Path(job["result_path"]).exists():
        return JSONResponse(json.loads(Path(job["result_path"]).read_text()))
    if job["result_json"]:
        return JSONResponse(json.loads(job["result_json"]))
    raise HTTPException(status_code=404, detail="no result stored for this job")


@app.get("/api/jobs/{job_id}/plate")
def get_job_plate(job_id: str):
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    if not job["plate_path"] or not Path(job["plate_path"]).exists():
        raise HTTPException(status_code=404, detail="no diagnostic plate for this job")
    return FileResponse(job["plate_path"], media_type="image/png",
                        filename=f"{job_id}_diagnostic.png")


@app.get("/api/history")
def get_history(limit: int = 50):
    with db() as conn:
        rows = conn.execute(
            "SELECT id, type, target, params_json, status, period, sde,"
            " created_at, finished_at, error FROM jobs"
            " ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    return {"runs": [
        {"job_id": r["id"], "type": r["type"], "target": r["target"],
         "params": json.loads(r["params_json"]), "status": r["status"],
         "period": r["period"], "sde": r["sde"],
         "created_at": r["created_at"], "finished_at": r["finished_at"],
         "error": r["error"]}
        for r in rows
    ]}


@app.get("/api/discoveries")
def get_discoveries(limit: int = 100):
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM discoveries ORDER BY id DESC LIMIT ?",
            (limit,)).fetchall()
    return {"discoveries": [dict(r) for r in rows]}


# ---------------------------------------------------------------------------
# Stage 3: serve the built React UI (frontend/dist) at / when it exists.
# Mounted LAST, after every /api route and /health above, so API routes
# keep priority and behaviour is unchanged when dist/ is absent.
# ---------------------------------------------------------------------------

_FRONTEND_DIST = BASE_DIR / "frontend" / "dist"
if _FRONTEND_DIST.is_dir():
    from fastapi.staticfiles import StaticFiles

    app.mount("/", StaticFiles(directory=str(_FRONTEND_DIST), html=True),
              name="frontend")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
