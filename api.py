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
  POST /api/doubleperiod     {tic, period, sector_cap?} — double-period
                              (ellipsoidal / twin-star) check on the RAW
                              light curve; the odd/even blind-spot test
  POST /api/qa               run Dev's 3 QA benchmarks (1-2 sectors, 10k grid);
                              optional {"custom": {tic, expected_period_days,
                              label?}} runs ONE user-supplied target as its
                              own QA job, judged by the same < 0.05 d rule
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
import math
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
from pydantic import BaseModel, Field  # noqa: E402

HIT_SDE = 8.5  # discoveries are hits only: SDE >= 8.5
# TIC contamination ratio at/above which a HIT is flagged as a blend
# risk (flag only — stars are never dropped for contamination). Both
# blend mirages of the first two sweeps sat at 0.136 / 0.186.
CONTAMINATION_FLAG_THRESHOLD = 0.10

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
                type         TEXT NOT NULL,          -- analyze | sweep | qa | oddeven | doubleperiod
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


def _clean_catalog_float(value):
    """Catalog value as a JSON-safe float, or None: NaN, masked and
    unparseable values all become None (the field is still carried)."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


# persistence.py's raw verdict -> the sweep-facing label.
_PERSISTENCE_LABELS = {
    "CONSISTENT": "persistent",
    "CONCENTRATED": "fails-persistence — blend-suspect",
    "MIXED": "patchy",
    "NO USABLE SECTORS": "inconclusive",
}


def _run_hit_persistence(entry, tic_id, star_rad, metrics, sector_cap, cb):
    """Per-hit sector-persistence test, integrated into the sweep.

    Runs persistence.sector_persistence — the exact implementation
    validated against CANDIDATE_374942698_FOLLOWUP.md and used in the
    SWEEP2 vetting — at the hit's own ephemeris (period / T0 / duration
    from the analyze that produced the hit), on the same sector set
    (same sector cap => same first-N products, downloads cached).

    Attaches a compact summary dict to the hit's entry and emits ONE
    progress line. NEVER raises: the discovery is already recorded by
    the time this runs, and a persistence failure must neither kill
    the sweep nor retract the hit — the hit stands, unlabelled.
    """
    try:
        import persistence
        per = persistence.sector_persistence(
            tic_id, star_rad, metrics["best_period_days"],
            metrics["t0_days"], metrics["duration_hours"],
            sector_cap=sector_cap, progress_callback=lambda _msg: None)
    except Exception as e:
        cb(f"persistence check unavailable: {e}")
        return
    raw_verdict = per.get("verdict")
    label = _PERSISTENCE_LABELS.get(raw_verdict, "inconclusive")
    n_usable = per.get("n_usable") or 0
    n_pos = per.get("n_pos_1p5sigma") or 0
    entry["persistence"] = {
        "sectors_usable": per.get("n_usable"),
        "sectors_with_dip": per.get("n_pos_1p5sigma"),
        "frac_ge_1p5sigma": per.get("frac_pos_1p5sigma"),
        "weighted_mean_depth_pct": per.get("weighted_mean_depth_pct"),
        "chi2": per.get("chi2"),
        "chi2_p": per.get("chi2_p"),
        "module_verdict": raw_verdict,
        "verdict": label,
    }
    if not n_usable:
        cb("↳ persistence: no usable sectors — inconclusive")
    elif label == "fails-persistence — blend-suspect":
        cb(f"↳ persistence: {n_pos}/{n_usable} sectors — "
           f"fails persistence — blend-suspect")
    else:
        cb(f"↳ persistence: {n_pos}/{n_usable} sectors, "
           f"mean depth {per.get('weighted_mean_depth_pct'):.2f}% — {label}")


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

    Skip-known build (2026-11-09): p["skip_known"] runs the
    already-known check WITHOUT the scanner screen — the check itself
    is now three-source (hunter.known_skip_source: Zooniverse, then
    VSX within ~30 arcsec of the catalog coords, then the NASA
    Exoplanet Archive TOI table by TIC ID), each source fail-open, and
    the summary counts skips per source (skipped_known_zooniverse /
    _vsx / _toi; skipped_known remains the total). Batch 4's
    Zooniverse-only check skipped 0 of 75 targets, which is why the
    two catalogue sources were added.

    Blend-screening integration (2026-11-04): the two vetting stages
    that killed both blend mirages of the first sweeps (TIC 374942698,
    TIC 231096116 — each passed every fold check first) now run INSIDE
    the sweep, on this shared path, so Sweeper and Scanner inherit
    both:
      * every target's TIC contamination ratio ("contratio", when the
        catalog provides it) is carried into its analyzed entry; a HIT
        at contratio >= CONTAMINATION_FLAG_THRESHOLD additionally
        carries a "high-contamination — blend risk" flag in its entry
        and on its HIT progress line. Flag only — no star is dropped
        or deprioritized because of contamination.
      * every hit then runs the sector-persistence test
        (_run_hit_persistence) at the hit's own ephemeris on the same
        sectors, attaching a compact summary + verdict label to the
        hit entry and emitting one extra progress line. The discovery
        row is written BEFORE the persistence stage runs, exactly as
        before, and the stage can never fail the sweep.
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
    # Skip-known build (2026-11-09): the known check runs when scanner
    # OR skip_known is set; skip_known alone leaves the catalog screen
    # (the request's own filters) exactly as requested.
    skip_known = bool(p.get("skip_known", False))
    check_known = scanner or skip_known
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
    if skip_known and not scanner:
        cb("Known-filter ON: already-known stars skipped via Zooniverse / "
           "VSX / TOI (requested catalog screen unchanged).")
    cb(f"Querying TIC catalog around RA {ra}, Dec {dec} (radius {cone}°)...")
    coord = SkyCoord(ra=ra * u.deg, dec=dec * u.deg)
    # Stage 5c: healed cone query (deep connection budget) — a bare
    # query_region here died outright on a dropped connection and
    # killed a sweep before any star ran (2026-11-03 06:52 IST).
    tic_catalog = hunter._query_tic_cone_healed(coord, cone, cb)
    # TIC contamination ratio rides along when the catalog provides
    # the column; when it doesn't, entries record null (no per-star
    # ExoFOP fetches — screen time stays one catalog call).
    has_contratio = "contratio" in tic_catalog.colnames
    has_radec = ("ra" in tic_catalog.colnames
                 and "dec" in tic_catalog.colnames)
    mask = (
        (tic_catalog["Tmag"] >= min_mag) & (tic_catalog["Tmag"] <= max_mag) &
        (tic_catalog["rad"] >= min_rad) & (tic_catalog["rad"] <= max_rad)
    )
    targets = tic_catalog[mask][:limit]
    total = len(targets)
    cb(f"Screened {total} target(s); starting sweep (no cap beyond requested limit={limit}).")

    analyzed, hits, errors = [], [], []
    skipped_known = 0
    skipped_by = {"zooniverse": 0, "vsx": 0, "toi": 0}
    for i, row in enumerate(targets, start=1):
        tic_id = str(row["ID"])
        star_rad = float(row["rad"])
        contratio = (_clean_catalog_float(row["contratio"])
                     if has_contratio else None)
        if check_known:
            src = hunter.known_skip_source(
                tic_id,
                float(row["ra"]) if has_radec else None,
                float(row["dec"]) if has_radec else None)
            if src:
                skipped_known += 1
                skipped_by[src] += 1
                cb(f"Target {i} of {total}: TIC {tic_id} — already known "
                   f"via {src.upper()}, skipping "
                   f"(skipped {skipped_known} so far).")
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
                     "star_radius_rsun": star_rad, "contratio": contratio,
                     "period_days": m["best_period_days"],
                     "sde": m["sde"], "planet_radius_re": m["planet_radius_earth"],
                     "sectors_analyzed": m["sectors_analyzed"]}
            analyzed.append(entry)
            if m["sde"] >= HIT_SDE:
                hits.append(entry)
                record_discovery(job_id, "sweep", m)
                hit_line = (f"HIT: TIC {tic_id} — "
                            f"P={m['best_period_days']:.4f} d, SDE={m['sde']:.1f}")
                if (contratio is not None
                        and contratio >= CONTAMINATION_FLAG_THRESHOLD):
                    entry["contamination_flag"] = \
                        "high-contamination — blend risk"
                    hit_line += " — high-contamination — blend risk"
                cb(hit_line)
                _run_hit_persistence(entry, tic_id, star_rad, m,
                                     sector_cap, cb)
        except Exception as e:  # recorded, not swallowed — sweep continues
            errors.append({"tic_id": tic_id, "error": str(e)})
            cb(f"Target {i} of {total}: TIC {tic_id} failed: {e}")

    summary = {"ra": ra, "dec": dec, "cone": cone, "targets_total": total,
               "targets_analyzed": len(analyzed), "hits": hits,
               "errors": errors,
               # Stage 4 (additive): scanner provenance + Zooniverse skips.
               # Skip-known build (additive): flag + per-source counters;
               # skipped_known stays the total (their sum).
               "scanner": scanner, "skip_known": skip_known,
               "skipped_known": skipped_known,
               "skipped_known_zooniverse": skipped_by["zooniverse"],
               "skipped_known_vsx": skipped_by["vsx"],
               "skipped_known_toi": skipped_by["toi"]}
    best = max(hits, key=lambda h: h["sde"], default=None)
    update_job(job_id, status="done", finished_at=_now(),
               result_json=json.dumps(summary),
               period=(best["period_days"] if best else None),
               sde=(best["sde"] if best else None))
    done_msg = (f"Sweep complete: {len(hits)} hit(s) with SDE >= {HIT_SDE} "
                f"out of {total} target(s).")
    if skipped_known:
        done_msg += (f" Skipped {skipped_known} already-known star(s) "
                     f"(Zooniverse {skipped_by['zooniverse']}, "
                     f"VSX {skipped_by['vsx']}, TOI {skipped_by['toi']}).")
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


def _run_doubleperiod(job_id, p):
    """Double-period (ellipsoidal) check job: hunter.double_period_test_json
    through the same queue as the odd/even check. The full payload
    (metrics + binned folded curve) is stored like an oddeven result so
    /result returns the chart data; the metrics dict is the job summary.
    No discovery is recorded — this judges an existing candidate.
    """
    result = hunter.double_period_test_json(
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
               period=metrics["period_2p_refined_days"])
    append_progress(job_id, "Done.")


def _qa_custom_entry(custom, cb):
    """One user-supplied QA target, judged by EXACTLY the benchmark
    rule from hunter.run_qa: same 10,000-point BLS grid, PASS iff
    |recovered - expected| < 0.05 d. Sector cap 2 (the top of the
    benchmarks' 1-2 range); host radius 1.0 — radius only scales the
    derived planet size, never the period verdict. Entry shape is
    identical to a benchmark entry (see _run_qa), plus "custom": true.
    """
    tic = custom["tic"]
    expected = float(custom["expected_period_days"])
    name = custom.get("label") or f"TIC {tic}"
    cb(f"\nQA: {name} (TIC {tic}) — expected {expected} d (custom target)")
    entry = {"name": name, "tic_id": tic,
             "expected_period_days": expected,
             "recovered_period_days": None, "diff_days": None,
             "status": "DRIFT", "custom": True}
    try:
        result = hunter.analyze_target(
            tic, star_radius=1.0, bls_points=10000, max_sectors=2,
            progress_callback=cb)
        diff = abs(result["Period"] - expected)
        passed = diff < 0.05
        entry.update(recovered_period_days=result["Period"],
                     diff_days=diff,
                     status=("PASS" if passed else "DRIFT"),
                     sde=result["SDE"],
                     planet_radius_re=result["Radius_Re"])
        cb(f"QA {name}: recovered {result['Period']:.5f} d "
           f"(Δ {diff:.5f} d) — {'PASS' if passed else 'FAIL'}")
    except Exception as e:
        entry["error"] = str(e)
        cb(f"QA {name} (TIC {tic}) error: {e}")
    return entry


def _run_qa(job_id, p):
    def cb(msg):
        append_progress(job_id, msg)

    if p.get("custom"):
        # A custom target is its own QA job: one entry, same shape.
        benchmarks = [_qa_custom_entry(p["custom"], cb)]
        summary = {"benchmarks": benchmarks,
                   "passed": sum(1 for b in benchmarks if b["status"] == "PASS"),
                   "total": len(benchmarks),
                   "custom": True}
        update_job(job_id, status="done", finished_at=_now(),
                   result_json=json.dumps(summary))
        cb("QA complete.")
        return

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
            "oddeven": _run_oddeven, "doubleperiod": _run_doubleperiod}


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
    # Collect their ids BEFORE stamping: afterwards we append a closing
    # progress line to each, so its log in History explains the gap
    # instead of trailing off mid-sentence.
    with _db_lock, db() as conn:
        stale_running = [r["id"] for r in
                         conn.execute("SELECT id FROM jobs WHERE status='running' ORDER BY created_at")]
        conn.execute(
            "UPDATE jobs SET status='failed', error='server restarted',"
            " finished_at=? WHERE status='running'", (_now(),))
        # Jobs left "queued" never started — re-enqueue them.
        queued = [r["id"] for r in
                  conn.execute("SELECT id FROM jobs WHERE status='queued' ORDER BY created_at")]
    for job_id in stale_running:
        append_progress(job_id, "Server restarted while this job was running — it did not finish. Everything above is the complete record up to the stop.")
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
    # Skip-known build (2026-11-09): three-source already-known
    # skipping (Zooniverse + VSX + TOI) WITHOUT the Scanner screen —
    # the request's own filters above apply unchanged.
    skip_known: bool = False


class OddEvenRequest(BaseModel):
    tic: str
    period: float
    sector_cap: Optional[int] = None


class DoublePeriodRequest(BaseModel):
    tic: str
    period: float = Field(gt=0)
    sector_cap: int = Field(default=2, ge=1, le=40)


class QaCustomTarget(BaseModel):
    tic: str
    expected_period_days: float
    label: Optional[str] = None


class QaRequest(BaseModel):
    # No body / no "custom" = QA uses Dev's fixed benchmark settings
    # (1-2 sectors, grid 10000). With "custom", exactly one
    # user-supplied target is QA'd under the same rule.
    custom: Optional[QaCustomTarget] = None


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
    if req is not None and req.custom is not None:
        c = req.custom
        tic = str(c.tic).strip()
        if not tic.isdigit() or int(tic) <= 0:
            raise HTTPException(
                status_code=422,
                detail="custom.tic must be a positive integer TIC ID")
        period = c.expected_period_days
        if period is None or not (0.1 <= period <= 100.0):
            raise HTTPException(
                status_code=422,
                detail="custom.expected_period_days must be between "
                       "0.1 and 100 days")
        params = {"custom": {"tic": tic,
                             "expected_period_days": float(period),
                             "label": (c.label.strip() if c.label else None)}}
        return _submit("qa", params, f"QA custom TIC {tic}")
    return _submit("qa", {}, "QA benchmarks")


@app.post("/api/oddeven")
def post_oddeven(req: OddEvenRequest):
    params = req.dict()
    return _submit("oddeven", params,
                   f"Odd/Even TIC {req.tic} @ {req.period} d")


@app.post("/api/doubleperiod")
def post_doubleperiod(req: DoublePeriodRequest):
    params = req.dict()
    return _submit("doubleperiod", params,
                   f"Double-Period TIC {req.tic} @ {req.period} d")


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
