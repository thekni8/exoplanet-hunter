#!/usr/bin/env python
"""Inverted-flux null on S96 (P3-12, 2026-11-15).

Claude's Phase 3 item: run the screen on sign-flipped S96 flux.
Survivors in sign-flipped data show the noise-tail floor, which
makes "reduction" interpretable -- without it, a survivor-count
drop under 3B (P3-11) cannot be distinguished from a noise-floor
shift. The 3B reduction numbers are interpreted against the
floor this run measures.

THE FLIP (median-symmetric reflection)
--------------------------------------
For each cached S96 QLP FITS, the flux is flipped around its own
median: f' = 2*median(f) - f. Dips become bumps of equal depth
and bumps become dips, at the same ephemeris. The flip is an
exact reflection, so the flipped light curve has:

* the same median (median(f') = median(f), exactly),
* the same noise properties (std, MAD, and every even central
  moment are preserved exactly -- a reflection is an isometry),
* the same TIME and QUALITY columns, untouched.

The median is computed over finite values only (np.nanmedian);
NaN flux values stay NaN and are masked by the screen exactly
as they are unflipped. A BLS dip search on flipped flux
therefore measures what the screen finds in data whose transit
signals have been turned into bumps: any survivor is a
noise-tail (or flipped-systematic) detection, not a planet.

METHOD (mirrors bulk/inject_real_s96.py, M-6)
----------------------------------------------
For each cached S96 FITS: load TIME/flux/QUALITY via
inject_real_s96.load_real_fits, flip the flux, write a flipped
FITS to the work dir via inject_real_s96.write_injected_fits
(the minimal QLP-like writer serves flipped flux exactly as it
serves injected flux -- same columns, same flux-column name),
and screen it through the REAL screen (bulk_screen._screen_one)
under bulk_v3. No screen code is duplicated and no calibration
is touched: bulk_v3 is byte-frozen and the null runs under it
unchanged.

DRIVER PATTERN (and where it diverges from rescore_full_driver)
--------------------------------------------------------------
The established full-sector driver
(hidden_files/mac-run-data/rescore-v3-s96/rescore_full_driver.py)
is SEQUENTIAL (9,899 s for 36,075 stars) with NO checkpoint: a
kill restarts from zero. This driver diverges deliberately, on
Dev's parallel-execution order and the VM/Mac flakiness lesson:

* PARALLEL: ProcessPoolExecutor over stars (default 8 workers,
  the Mac M4's sweet spot by the bulk_screen --workers default),
  each worker running _screen_flipped_star (flip + write +
  screen) with the calibration set in the worker initializer.
  Per-star chunking: one star per task, results streamed back
  as they complete (imap-style collection, not batched).
* RESUMABLE: every screened star is checkpointed to
  null_screened.jsonl the moment its record lands (append +
  flush per record); a re-launch skips stars already in the
  checkpoint. Survivors are appended to null_survivors.jsonl
  the same way. A kill loses at most the in-flight stars.
* WATCHDOG + CIRCUIT BREAKER: the collection loop is adapted
  from bulk_screen._collect_screen_results (per-star timeout,
  status "unmeasured" on timeout, 25 consecutive timeouts
  trip the breaker and stop the run without writing a
  summary -- the same contract as the screen's own main()).
  The adaptation is the on_record callback that checkpoints
  each record as it lands; _collect_screen_results returns
  only at the end, which would lose the checkpoint.

Outputs (in --out-dir; run data, NEVER git):
  flipped/<tic>_flipped.fits   the flipped light curves (~3 GB
                               for S96; kept for audit until the
                               P3-11 interpretation is done)
  null_screened.jsonl          one compact record per screened
                               star (the resume checkpoint)
  null_survivors.jsonl         one record per flipped survivor,
                               same shape as the screen emits
                               (emit_survivor_record) plus
                               "inverted_null": true
  summary.json                 counts + the noise-tail floor
                               numbers (the P3-11 deliverable)

The summary's floor numbers are the deliverable: survivors by
tier, floor rates (survivors / stars screened), null survivors
above each candidate SDE bar, and -- with --reference pointing
at the real rescore_v3_s0096.jsonl -- the null/real fraction
per tier.

Usage (Mac):
  python bulk/inverted_null.py --cache bulk/cache --sector 96 \\
      --out-dir bulk/inverted-null-s0096 --workers 8 \\
      --reference <rescore_v3_s0096.jsonl>
"""
import argparse
import json
import os
import sys
import time
import warnings
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "bulk"))

import bulk_screen as bs  # noqa: E402
import provenance as _prov  # noqa: E402
from bulk.inject_real_s96 import (  # noqa: E402
    load_real_fits, write_injected_fits)
from calibration import load_profile as _load_profile  # noqa: E402

PROFILE = "bulk_v3"
DEFAULT_WORKERS = 8
# Per-star watchdog: the screen's own STAR_TIMEOUT_S (netbound).
# A star's BLS takes ~0.3 s; 600 s is a hung-worker tripwire,
# not a performance budget.
DEFAULT_TIMEOUT_S = 600.0
# SDE bars the floor is reported at (P3-11's candidate bars
# are 8.0 / 9.0 / 10.0; 7.0 is the survivor bar itself).
FLOOR_SDE_BARS = (7.0, 8.0, 9.0, 10.0, 15.0, 20.0)

CHECKPOINT_NAME = "null_screened.jsonl"
SURVIVORS_NAME = "null_survivors.jsonl"
SUMMARY_NAME = "summary.json"
FLIPPED_DIRNAME = "flipped"


def _log(msg):
    print(msg, flush=True)


# ---------------------------------------------------------------------------
# The flip
# ---------------------------------------------------------------------------

def flip_flux(f):
    """Median-symmetric reflection: f' = 2*median(f) - f.

    Dips become bumps of equal depth at the same ephemeris and
    vice versa. The median is over finite values only; NaN
    entries stay NaN (the screen masks them either way). An
    all-NaN array has no median and is returned unchanged.
    Returns a new float64 array; the input is not modified.
    """
    f = np.asarray(f, dtype=float)
    finite = np.isfinite(f)
    if not finite.any():
        return f.copy()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        med = float(np.nanmedian(f))
    return 2.0 * med - f


def prepare_flipped(path, workdir):
    """Load a cached QLP FITS, flip its flux, write the flipped
    FITS to `workdir/<tic>_flipped.fits`. Returns
    (flipped_path, meta) where meta is load_real_fits' header
    meta (ra/dec/tmag) for the screen job. TIME and QUALITY are
    carried through untouched by write_injected_fits."""
    t, f, q, fcol, meta = load_real_fits(path)
    f_flip = flip_flux(f)
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    flipped = workdir / f"{Path(path).stem}_flipped.fits"
    write_injected_fits(flipped, t, f_flip, q, fcol)
    return flipped, meta


# ---------------------------------------------------------------------------
# Worker (module-level: pickled to pool workers)
# ---------------------------------------------------------------------------

def _init_worker(root, profile):
    """Pool initializer: path setup + calibration. Fails loudly
    (like rescore_full_driver) if the screen's live mask differs
    from the profile's declared mask -- a worker screening under
    the wrong mask must never silently produce floor numbers."""
    sys.path.insert(0, str(Path(root) / "bulk"))
    sys.path.insert(0, str(root))
    import bulk_screen as _bs
    _bs.set_calibration(profile)
    prof = _load_profile(profile)
    quality_mask = prof.get("quality_mask")
    if quality_mask is not None and _bs.QUALITY_MASK != quality_mask:
        raise SystemExit(
            f"[inverted-null] ABORT: worker QUALITY_MASK "
            f"{_bs.QUALITY_MASK} != profile {profile} "
            f"quality_mask {quality_mask}")


def _screen_flipped_star(job):
    """Worker: flip one star and screen it through the REAL
    screen. job = (tic, path, sector, workdir). Returns the
    screen record (always, with 'status'), plus the null's
    traceability keys (source + flipped filenames). A load/flip
    failure returns a status='error' record -- the parent counts
    it, it never kills the run."""
    tic, path, sector, workdir = job
    rec = {"tic": tic, "sector": int(sector), "product": bs.PRODUCT,
           "status": "error",
           "null_source_file": Path(path).name}
    try:
        flipped, meta = prepare_flipped(path, workdir)
        rec["null_flipped_file"] = flipped.name
        screened = bs._screen_one((tic, str(flipped), int(sector),
                                   meta))
        screened["null_source_file"] = Path(path).name
        screened["null_flipped_file"] = flipped.name
        return screened
    except Exception as e:  # noqa: BLE001 -- worker must not die
        rec["error"] = f"{type(e).__name__}: {e}"
        return rec


# ---------------------------------------------------------------------------
# Collection (adapted from bulk_screen._collect_screen_results)
# ---------------------------------------------------------------------------

def _collect_null_results(ex, jobs, worker, timeout_s, on_record,
                          logf=None, max_consecutive_timeouts=None):
    """Submit every job and collect records, with a per-star
    watchdog and a consecutive-timeout circuit breaker -- the
    same semantics as bulk_screen._collect_screen_results
    (C-1/F-13), plus `on_record(rec)` called for EVERY record
    the moment it lands, so the parent can checkpoint per star
    instead of holding 36k records in memory until the end.

    A star that has not returned within `timeout_s` of
    submission is recorded as status="unmeasured" with a
    watchdog_timeout reason. At `max_consecutive_timeouts`
    (default bulk_screen.MAX_CONSECUTIVE_TIMEOUTS) consecutive
    timeouts the function raises bulk_screen.CircuitBreakerError
    instead of recording another unmeasured star. Returns the
    status counts dict. (Records themselves go to on_record;
    unlike _collect_screen_results this function keeps no list.)
    """
    if max_consecutive_timeouts is None:
        max_consecutive_timeouts = bs.MAX_CONSECUTIVE_TIMEOUTS
    futures = {}
    for job in jobs:
        futures[ex.submit(worker, job)] = (job, time.monotonic())
    counts = {}
    consecutive_timeouts = 0
    pending = set(futures)
    while pending:
        done, pending = wait(pending, timeout=timeout_s,
                             return_when=FIRST_COMPLETED)
        for fut in done:
            rec = fut.result()
            on_record(rec)
            counts[rec["status"]] = counts.get(rec["status"], 0) + 1
            consecutive_timeouts = 0
        now = time.monotonic()
        for fut in list(pending):
            job, t0 = futures[fut]
            if now - t0 > timeout_s:
                pending.discard(fut)
                tic, path, sector, _workdir = job
                rec = {"tic": tic, "sector": int(sector),
                       "product": bs.PRODUCT,
                       "status": "unmeasured",
                       "reason": ("watchdog_timeout: screen "
                                  f"exceeded {timeout_s:g}s"),
                       "null_source_file": Path(path).name}
                on_record(rec)
                counts["unmeasured"] = counts.get("unmeasured", 0) + 1
                consecutive_timeouts += 1
                if consecutive_timeouts >= max_consecutive_timeouts:
                    raise bs.CircuitBreakerError(
                        f"{consecutive_timeouts} consecutive "
                        f"watchdog timeouts (limit "
                        f"{max_consecutive_timeouts}) -- the "
                        f"screen is timing out systematically, "
                        f"not on one pathological star; "
                        f"stopping the null run")
                _log(f"star {tic}: WATCHDOG -- screen exceeded "
                     f"{timeout_s:g}s, recorded unmeasured")
    return counts


# ---------------------------------------------------------------------------
# Records + summary
# ---------------------------------------------------------------------------

_COMPACT_KEYS = ("tic", "status", "tier", "sde", "period_days",
                 "depth_percent", "n_events", "mes_pink",
                 "max_event_snr", "near_systematic",
                 "search_health", "flags", "null_source_file",
                 "null_flipped_file", "error", "reason")


def compact_record(rec):
    """The checkpoint record for one screened star: the fields
    the summary needs (status/tier/SDE/period) plus the null's
    traceability keys. None-valued fields are dropped."""
    return {k: rec.get(k) for k in _COMPACT_KEYS
            if rec.get(k) is not None}


def load_done_tics(checkpoint_path):
    """TICs already checkpointed (resume set). A torn trailing
    line -- a kill mid-write -- is skipped with a warning, and
    that star re-screens; a malformed line never aborts resume."""
    done = set()
    path = Path(checkpoint_path)
    if not path.exists():
        return done
    with open(path) as fh:
        for lineno, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                done.add(str(json.loads(line)["tic"]))
            except (json.JSONDecodeError, KeyError, TypeError):
                _log(f"[inverted-null] WARNING: checkpoint line "
                     f"{lineno} unparseable (torn write?) -- "
                     f"that star will re-screen")
    return done


def _tier_counts(records):
    counts = {"A": 0, "B": 0}
    for r in records:
        if r.get("status") == "survivor" and r.get("tier") in counts:
            counts[r["tier"]] += 1
    return counts


def compute_summary(records, reference_records=None):
    """The noise-tail floor numbers from screened-star records
    (compact checkpoint records or full screen records -- only
    .get() fields are read). Pure function; the run metadata
    (run_id, wall time) is added by run_null.

    Floor rates use stars MEASURED as the denominator (F-13):
    error/unmeasured stars were not screened. `reference_records`
    is the REAL screen's survivor list (e.g. rescore_v3_s0096
    .jsonl); when given, the summary adds the null/real fraction
    per tier -- the number P3-11 interprets the reduction
    against.
    """
    records = list(records)
    status_counts = {}
    for r in records:
        s = r.get("status", "unknown")
        status_counts[s] = status_counts.get(s, 0) + 1
    n_attempted = len(records)
    n_errors = status_counts.get("error", 0)
    n_unmeasured = status_counts.get("unmeasured", 0)
    n_screened = n_attempted - n_errors - n_unmeasured
    survivors = [r for r in records if r.get("status") == "survivor"]
    tiers = _tier_counts(records)
    n_surv = len(survivors)
    sdes = [float(r["sde"]) for r in survivors
            if r.get("sde") is not None]
    above = {f"{bar:g}": int(sum(1 for s in sdes if s >= bar))
             for bar in FLOOR_SDE_BARS}
    out = {
        "n_attempted": n_attempted,
        "n_screened": n_screened,
        "n_errors": n_errors,
        "n_unmeasured": n_unmeasured,
        "status_counts": status_counts,
        "null_survivors_total": n_surv,
        "null_survivors_tier_a": tiers["A"],
        "null_survivors_tier_b": tiers["B"],
        # The floor: null survivors per star screened, overall
        # and per tier. A 3B reduction is interpretable only
        # against these rates.
        "floor_rate_overall": (n_surv / n_screened
                               if n_screened else None),
        "floor_rate_tier_a": (tiers["A"] / n_screened
                              if n_screened else None),
        "floor_rate_tier_b": (tiers["B"] / n_screened
                              if n_screened else None),
        "null_survivors_above_sde": above,
        "null_survivor_sde_max": (max(sdes) if sdes else None),
        "null_survivor_sde_median": (float(np.median(sdes))
                                     if sdes else None),
        "null_survivors_near_systematic": int(sum(
            1 for r in survivors if r.get("near_systematic"))),
    }
    if reference_records is not None:
        ref = list(reference_records)
        ref_surv = [r for r in ref if r.get("status") == "survivor"]
        # A reference jsonl of survivors may carry no status
        # field at all (emit_survivor_record output always has
        # one, but be liberal: a record with a tier is a
        # survivor record).
        if not ref_surv and ref and all(
                r.get("tier") in ("A", "B") for r in ref):
            ref_surv = ref
        ref_tiers = _tier_counts(ref_surv) if ref_surv else {
            "A": sum(1 for r in ref if r.get("tier") == "A"),
            "B": sum(1 for r in ref if r.get("tier") == "B")}
        n_ref = len(ref_surv)
        out["reference"] = {
            "n_survivors": n_ref,
            "n_survivors_tier_a": ref_tiers["A"],
            "n_survivors_tier_b": ref_tiers["B"],
            # Null survivors as a fraction of real survivors:
            # ~0 means the real survivors sit far above the
            # noise floor; ~1 means the reduction is
            # uninterpretable without the floor.
            "floor_fraction_overall": (n_surv / n_ref
                                       if n_ref else None),
            "floor_fraction_tier_a": (tiers["A"] / ref_tiers["A"]
                                      if ref_tiers["A"] else None),
            "floor_fraction_tier_b": (tiers["B"] / ref_tiers["B"]
                                      if ref_tiers["B"] else None),
        }
    return out


def _sort_jsonl_by_tic(path):
    """Rewrite a jsonl sorted by TIC (deterministic final
    artifact). Atomic: write to a temp file, os.replace."""
    rows = []
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    rows.sort(key=lambda r: str(r.get("tic", "")))
    tmp = Path(str(path) + ".tmp")
    with open(tmp, "w") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    os.replace(tmp, path)


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def _check_modules():
    """Fail loudly on module shadowing (rescore_full_driver
    lesson: a stale bulk/bulk_screen.py exists on the Mac)."""
    import bulk.inject_real_s96 as _inj
    if Path(bs.__file__).resolve() != (ROOT / "bulk_screen.py").resolve():
        raise SystemExit(
            f"[inverted-null] ABORT: bulk_screen loaded from "
            f"{bs.__file__}, not {ROOT / 'bulk_screen.py'}")
    if Path(_inj.__file__).resolve() != \
            (ROOT / "bulk" / "inject_real_s96.py").resolve():
        raise SystemExit(
            f"[inverted-null] ABORT: inject_real_s96 loaded from "
            f"{_inj.__file__}, not "
            f"{ROOT / 'bulk' / 'inject_real_s96.py'}")


def run_null(cache, sector, out_dir, workers=DEFAULT_WORKERS,
             profile=PROFILE, timeout_s=DEFAULT_TIMEOUT_S,
             tics=None, limit=None, reference=None, dry_run=False):
    """Run the inverted-flux null over a cached sector. Returns
    the summary dict (also written to out_dir/summary.json on
    completion). Raises bulk_screen.CircuitBreakerError on a
    systematic timeout -- no summary is written then, and the
    checkpoint holds the partial run for a resume."""
    _check_modules()
    bs.set_calibration(profile)
    prof = _load_profile(profile)
    quality_mask = prof.get("quality_mask")
    if quality_mask is not None and bs.QUALITY_MASK != quality_mask:
        raise SystemExit(
            f"[inverted-null] ABORT: screen QUALITY_MASK "
            f"{bs.QUALITY_MASK} != profile {profile} "
            f"quality_mask {quality_mask}")
    _log(f"[inverted-null] profile {profile}, quality_mask "
         f"{quality_mask}, workers {workers}")

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    workdir = out_dir / FLIPPED_DIRNAME
    workdir.mkdir(parents=True, exist_ok=True)
    checkpoint_path = out_dir / CHECKPOINT_NAME
    survivors_path = out_dir / SURVIVORS_NAME

    sector_dir = Path(cache) / f"s{int(sector):04d}"
    if tics is not None:
        files = []
        for tic in tics:
            p = sector_dir / f"{tic}.fits"
            if not p.exists():
                raise SystemExit(
                    f"[inverted-null] ABORT: --tics star {tic} "
                    f"has no cached file {p}")
            files.append(p)
    else:
        files = sorted(sector_dir.glob("*.fits"),
                       key=lambda p: p.stem) if sector_dir.is_dir() \
            else []
    if limit is not None:
        files = files[:limit]
    n_cached = (len(list(sector_dir.glob("*.fits")))
                if sector_dir.is_dir() else 0)
    _log(f"[inverted-null] sector {sector}: {n_cached} cached, "
         f"{len(files)} selected")

    done = load_done_tics(checkpoint_path)
    todo = [p for p in files if p.stem not in done]
    n_skipped = len(files) - len(todo)
    _log(f"[inverted-null] resume: {n_skipped} already "
         f"checkpointed, {len(todo)} to screen")
    if dry_run:
        summary = {"tool": "inverted_null", "sector": int(sector),
                   "calibration_version": profile,
                   "quality_mask": quality_mask,
                   "n_cached": n_cached,
                   "n_selected": len(files),
                   "n_resumed_skipped": n_skipped,
                   "n_to_screen": len(todo),
                   "dry_run": True}
        (out_dir / SUMMARY_NAME).write_text(
            json.dumps(summary, indent=2))
        return summary

    run_id = _prov.new_run_id(f"inverted_null_s{int(sector):04d}")
    started_at = _prov.utc_now_iso()
    prov = _prov.provenance_header(run_id, bs.CALIBRATION_MAP,
                                   timestamp_utc=started_at)
    t_start = time.time()
    counts = {}
    n_done_this_run = [0]

    fh_ckpt = open(checkpoint_path, "a")
    fh_surv = open(survivors_path, "a")

    def on_record(rec):
        fh_ckpt.write(json.dumps(compact_record(rec)) + "\n")
        fh_ckpt.flush()
        if rec.get("status") == "survivor":
            out = bs.emit_survivor_record(rec, prov)
            out["inverted_null"] = True
            fh_surv.write(json.dumps(out) + "\n")
            fh_surv.flush()
        n_done_this_run[0] += 1
        if n_done_this_run[0] % 500 == 0:
            _log(f"[inverted-null] {n_done_this_run[0]}/"
                 f"{len(todo)} screened this run, "
                 f"{counts.get('survivor', 0)} survivors")

    jobs = [(p.stem, str(p), int(sector), str(workdir))
            for p in todo]
    try:
        if workers <= 1:
            # Sequential path: debugging + tests. Same worker,
            # same checkpointing, no pool.
            for job in jobs:
                rec = _screen_flipped_star(job)
                on_record(rec)
                counts[rec["status"]] = \
                    counts.get(rec["status"], 0) + 1
        else:
            with ProcessPoolExecutor(
                    max_workers=workers,
                    initializer=_init_worker,
                    initargs=(str(ROOT), profile)) as ex:
                counts = _collect_null_results(
                    ex, jobs, _screen_flipped_star, timeout_s,
                    on_record)
    finally:
        fh_ckpt.close()
        fh_surv.close()
    # CircuitBreakerError propagates out of the try above (the
    # finally closes the files first): no summary is written,
    # the checkpoint holds the partial run for a resume.

    # Deterministic final artifacts: sort both jsonls by TIC.
    if checkpoint_path.exists():
        _sort_jsonl_by_tic(checkpoint_path)
    if survivors_path.exists():
        _sort_jsonl_by_tic(survivors_path)

    records = []
    if checkpoint_path.exists():
        with open(checkpoint_path) as fh:
            for line in fh:
                line = line.strip()
                if line:
                    records.append(json.loads(line))
    reference_records = None
    if reference is not None:
        reference_records = []
        with open(reference) as fh:
            for line in fh:
                line = line.strip()
                if line:
                    reference_records.append(json.loads(line))
    summary = {"tool": "inverted_null",
               "sector": int(sector),
               "calibration_version": profile,
               "quality_mask": quality_mask,
               "run_id": run_id,
               "provenance": prov,
               "n_cached": n_cached,
               "n_selected": len(files),
               "n_resumed_skipped": n_skipped,
               "n_screened_this_run": len(todo),
               "wall_seconds": time.time() - t_start,
               "dry_run": False}
    summary.update(compute_summary(records, reference_records))
    (out_dir / SUMMARY_NAME).write_text(json.dumps(summary, indent=2))
    _log(f"[inverted-null] done: {summary['n_screened']} screened "
         f"({summary['n_screened_this_run']} this run), "
         f"{summary['null_survivors_total']} null survivors "
         f"({summary['null_survivors_tier_a']} A / "
         f"{summary['null_survivors_tier_b']} B), "
         f"{summary['n_errors']} errors, "
         f"{summary['n_unmeasured']} unmeasured in "
         f"{summary['wall_seconds']:.0f}s")
    return summary


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Inverted-flux null: screen sign-flipped "
                    "S96 flux under bulk_v3; measures the "
                    "noise-tail floor (see module docstring).")
    ap.add_argument("--cache", required=True,
                    help="cache root holding s<NNNN>/<tic>.fits")
    ap.add_argument("--sector", type=int, default=96)
    ap.add_argument("--out-dir", required=True,
                    help="output directory (run data; created "
                         "if needed)")
    ap.add_argument("--profile", default=PROFILE,
                    help="calibration profile (default bulk_v3)")
    ap.add_argument("--workers", type=int, default=DEFAULT_WORKERS,
                    help="pool workers (default 8; 1 = "
                         "sequential, for debugging/tests)")
    ap.add_argument("--timeout", type=float,
                    default=DEFAULT_TIMEOUT_S,
                    help="per-star watchdog seconds (default "
                         "600, the screen's STAR_TIMEOUT_S)")
    ap.add_argument("--tics", default=None,
                    help="comma-separated TICs to screen "
                         "(testing only; overrides the full "
                         "sector list)")
    ap.add_argument("--limit", type=int, default=None,
                    help="screen only the first N stars by TIC "
                         "(smoke testing)")
    ap.add_argument("--reference", default=None,
                    help="real-screen survivor jsonl (e.g. "
                         "rescore_v3_s0096.jsonl) for the "
                         "null/real floor fractions")
    ap.add_argument("--dry-run", action="store_true",
                    help="list stars only, no BLS")
    args = ap.parse_args(argv)
    tics = ([t.strip() for t in args.tics.split(",")]
            if args.tics else None)
    try:
        run_null(args.cache, args.sector, args.out_dir,
                 workers=args.workers, profile=args.profile,
                 timeout_s=args.timeout, tics=tics,
                 limit=args.limit, reference=args.reference,
                 dry_run=args.dry_run)
    except bs.CircuitBreakerError as exc:
        _log(f"[inverted-null] CIRCUIT BREAKER: {exc}")
        _log("[inverted-null] no summary written -- resume with "
             "the same command; the checkpoint holds the "
             "partial run")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
