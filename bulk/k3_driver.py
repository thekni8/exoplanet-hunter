"""4.1-1a: the production K=3 stage for the chunked driver.

After a slice's K=1 screen (bulk_screen.py, unchanged), this stage
looks behind each pass-1 contaminant for a second signal: estimate
the contaminant ephemeris from the pass-1 period, mask it, re-search
(pass 2); if the pass-2 peak is itself an eligible confirmed
contaminant, mask it too and re-search again (pass 3). The K=3 logic
is NOT reimplemented here — the stage calls the campaign's own code:
bulk/k3_run.py's _run_pass2/_run_pass3, bulk/k2_prototype.py's
estimation/mask/veto, bulk/k3_prototype.py's eligibility/cap rules.
Any divergence between the driver and the campaign is therefore a
wiring bug, not a second implementation.

What is new here is only the production plumbing around that logic:
which pass-1 rows enter the stage (k3_entry_candidates), the
per-star job shape (run_k3_star), the emitted queue rows
(k3_emit_rows), and the per-slice stage (run_k3_slice) that the
chunked driver calls after each slice screen.

Production arm: "prototype" ONLY (the P4-1b PRIMARY arm, 25% cap).
The campaign's other arms (combined, cap-aware, no-depth-trigger)
are measurement arms; they never ship in the driver.

Entry rule (production): a pass-1 row enters the stage when it
carries a found period AND its status is "recorded" or "demoted"
— the production analogue of the campaign's wrong-period trials
(a peak was found, but it is not a survivor: a deep EB-like
contaminant or a sub-bar signal that may hide a planet behind
it). Pass-1 SURVIVORS do not enter: they are already queue rows,
and looking behind a survivor is multi-planet search — out of
4.1-1a scope, a Stage 5 decision. Below-floor / error rows have
no usable period and do not enter. The per-star function itself
(run_k3_star) takes any pass-1 record with a period — the entry
filter is a production-screen concern, and the Stage 5 per-trial
parity harness calls run_k3_star directly for all 451 frozen
trials, unfiltered.

Outputs (per slice, written by run_k3_slice; the slice's pass-1
outputs are NEVER modified — DB-5, demote not delete):
  k3_survivors.jsonl   — pass-2/pass-3 survivors (queue rows,
                         schema-validated, k3_pass 2/3 stamped)
  k3_screen_hits.jsonl — pass-2/pass-3 above-floor records
  k3_detail.jsonl      — one audit record per entered star
                         (ephemerides, mask stats, vetoes,
                         eligibility, timing — the campaign's
                         per-trial record shape)
  summary.json "k3" block — the stage's counts (written LAST:
                         the commit point; a slice counts as
                         K=3-done only when the block is present)

K=3 rows carry no work_item_id: that id's contract is
same-work → same-output, and a masked re-search is different
work from the pass-1 screen. K=3 survivors skip the Zooniverse
online check (the pass-1 check runs inside bulk_screen per
slice); the gauntlet's catalogue check still applies. Both are
documented Stage 5 decision points, not oversights.

Status (2026-11-18): SCAFFOLDING. Stage 5 acceptance — (a)
per-trial parity on the frozen sets, (b) S97 queue parity, (c)
A18 ≤ 2.5× — has NOT run. BP-1 FAILED (null side), so per
PHASE41_PREREG §2.1 the driver is NOT production-authorised
even once the scaffolding lands. Stacking is NOT wired here
(4.1-1b, after 4.1-4/4.1-8); the P4-7 pool is untouched.
"""

import csv
import json
import os
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
import sys
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import bulk_screen as bs  # noqa: E402
from atomic_io import atomic_write_json as _atomic_write_json  # noqa: E402
from atomic_io import atomic_writer as _atomic_writer  # noqa: E402
from bulk import k2_prototype as k2  # noqa: E402
from bulk import k3_prototype as k3  # noqa: E402
from bulk import k3_run as k3run  # noqa: E402
from bulk import oracle_run as orc  # noqa: E402
from bulk.inject_real_s96 import load_real_fits  # noqa: E402
from validation import validate_survivor as _validate_survivor  # noqa: E402

# The production arm: the P4-1b PRIMARY arm. Campaign arms never ship.
K3_PRODUCTION_ARM = "prototype"

# Pass-1 statuses that enter the K=3 stage (see module docstring).
K3_ENTRY_STATUSES = ("recorded", "demoted")

# Per-slice K=3 output files (run_k3_slice writes all three, then
# stamps the summary's "k3" block as the commit point).
K3_SURVIVORS_FILE = "k3_survivors.jsonl"
K3_HITS_FILE = "k3_screen_hits.jsonl"
K3_DETAIL_FILE = "k3_detail.jsonl"


def k3_entry_candidates(pass1_hits):
    """Pass-1 rows that enter the K=3 stage: a found period AND a
    non-survivor above-floor status (recorded/demoted). Pure."""
    return [r for r in pass1_hits
            if r.get("period_days") is not None
            and r.get("status") in K3_ENTRY_STATUSES]


def _log_default(msg):
    print(f"[k3-driver] {msg}", flush=True)


def run_k3_star(job):
    """One star: pass 2 (+ pass 3 where eligible) behind the
    pass-1 contaminant. The production analogue of
    k3_run.run_host_null_k3's per-star flow, with pass 1 supplied
    by the caller (the slice screen) instead of re-run.

    job: {tic, sector, path (cached QLP FITS), pass1 (the slice's
    screen_hits row: period_days, depth_percent, ...), meta
    (ra/dec/tmag/radius for the emitted rows), workdir, keep_fits}.
    Calibration is global (set by the caller / Pool initializer).

    Returns a detail dict (the k3_detail.jsonl record shape):
    ephemerides, mask stats, pass-2/pass-3 screen subsets, vetoes,
    eligibility, timing — plus "rows", the emitted queue rows
    (survivors + hits) for this star, already stamped with the
    job's meta and the pass provenance. Per-star failures are
    recorded (error), never raised — a bad star must not kill
    the slice, mirroring _screen_one's per-star error status.
    """
    tic = job["tic"]
    sector = int(job["sector"])
    p1 = job["pass1"]
    meta = job.get("meta") or {}
    workdir = Path(job["workdir"])
    keep_fits = job.get("keep_fits", False)
    prov = job.get("prov") or {}
    t_start = time.time()
    rec = {"tic": tic, "sector": sector,
           "pass1": {"period_days": p1.get("period_days"),
                     "depth_percent": p1.get("depth_percent"),
                     "status": p1.get("status")},
           "rows": {"survivors": [], "hits": []}}
    try:
        t, f, q, fcol, _ = load_real_fits(job["path"])
    except Exception as exc:  # noqa: BLE001
        rec["error"] = f"load_real_fits: {exc}"
        rec["seconds"] = round(time.time() - t_start, 2)
        return rec
    p1_p = p1.get("period_days")
    if p1_p is None:
        rec["error"] = "no-pass1-period"
        rec["seconds"] = round(time.time() - t_start, 2)
        return rec
    try:
        workdir.mkdir(parents=True, exist_ok=True)
        base = workdir / f"{tic}_s{sector:04d}_k3"
        # --- estimation from the RECORDED (pass-1) period + fold
        # only — never a fresh BLS measurement (k2_prototype).
        t_p, f_p = orc.preprocess_arrays(t, f, q)
        ephemeris = k2.estimate_ephemeris(t_p, f_p, p1_p)
        rec["ephemeris"] = ephemeris
        secondary = k2.scan_secondary(
            t_p, f_p, ephemeris["period_ref_d"],
            ephemeris["t0_est_btjd"],
            ephemeris["duration_est_d"])
        rec["secondary_scan"] = {
            "phase": secondary[0], "depth_frac": secondary[1],
            "snr": secondary[2]}
        # --- pass 2 (the campaign's _run_pass2, prototype arm)
        keep2, mstats, p2, _ = k3run._run_pass2(
            t, f, q, fcol, base, tic, sector, ephemeris,
            secondary, p1.get("depth_percent"), K3_PRODUCTION_ARM,
            None, keep_fits)
        rec["k2_mask"] = mstats
        if p2 is None:
            rec["pass2"] = None
            rec["stopped_pass"] = 2
            rec["pass3_eligibility"] = {
                "eligible": False,
                "reason": "stopped-duty-cycle"}
            rec["pass3"] = None
        else:
            rec["stopped_pass"] = None
            rec["pass2"] = orc._subset(p2)
            veto2 = k2.alias_veto(
                p2.get("period_days"), p2.get("t0_btjd"),
                ephemeris["period_ref_d"],
                ephemeris["t0_est_btjd"],
                mstats["mask_half_width_d"],
                comask_phase=mstats["secondary_phase"])
            rec["alias_veto"] = veto2
            # Production has no injected planet, so the "pass 2
            # rescued" short-circuit does not apply (the null-leg
            # rule): a pass-2 survivor is a candidate the K=3
            # search looks behind via the eligibility rule's
            # survivor branch. p2_rescued is always False here.
            elig, reason = k3.pass3_eligible(
                orc._subset(p2), veto2, False)
            rec["pass3_eligibility"] = {"eligible": bool(elig),
                                        "reason": reason,
                                        "veto_pass2": veto2}
            if not elig:
                rec["pass3"] = None
            else:
                _e, rec3 = k3run._run_pass3(
                    t, f, q, fcol, base, tic, sector, keep2, p2,
                    ephemeris, mstats, K3_PRODUCTION_ARM,
                    period_inj=None, epoch_inj=None,
                    duration_inj=None, keep_fits=keep_fits)
                # _run_pass3's null-leg shape: no recovery
                # verdict (no ground truth) — the pass-3 screen
                # record is the result.
                rec["k3_ephemeris"] = rec3.get("k3_ephemeris")
                rec["k3_secondary_scan"] = rec3.get(
                    "k3_secondary_scan")
                rec["k3_mask"] = rec3.get("k3_mask")
                rec["alias_veto_pass3"] = rec3.get(
                    "alias_veto_pass3")
                rec["pass3"] = rec3.get("pass3")
    except Exception as exc:  # noqa: BLE001
        rec["error"] = f"{type(exc).__name__}: {exc}"
        rec["seconds"] = round(time.time() - t_start, 2)
        return rec
    # Emit AFTER the try: a malformed row is a code bug and must
    # fail the stage loudly (bulk_screen main's rule), not hide
    # inside a per-star error record.
    rec["rows"] = k3_emit_rows(rec, p2, prov, meta)
    rec["seconds"] = round(time.time() - t_start, 2)
    return rec


def _stamp_meta(row, meta):
    """Stamp the star's real meta on an emitted row. The campaign
    screens via screen_job's DEFAULT_META (ra/dec/tmag/radius
    placeholders) — the screen never uses them for detection
    (_screen_one only copies them into the record), so stamping
    the slice CSV's real values post-hoc is exact."""
    row["ra"] = meta.get("ra")
    row["dec"] = meta.get("dec")
    row["tmag"] = meta.get("tmag")
    row["radius_rsun"] = meta.get("radius")
    return row


def k3_emit_rows(detail, p2_full, prov, meta):
    """The emitted queue rows for one star's K=3 result.

    detail is run_k3_star's record (pass-2/pass-3 subsets);
    p2_full is the pass-2 FULL _screen_one record (the pass-3
    full record is not retained by k3_run._run_pass3 — its
    subset is what the campaign keeps — so pass-3 rows are
    emitted from the subset + job meta; the asymmetry is
    recorded here, and the full audit lives in k3_detail.jsonl).

    Returns {"survivors": [...], "hits": [...]}: survivors are
    pass-2/pass-3 records with status "survivor"; hits are the
    above-floor pass-2/pass-3 records (bulk_screen main's rule:
    sde present and >= RECORD_FLOOR_SDE). Every row is
    schema-validated before it is returned — a malformed row is
    a code bug and must fail here, not in the merge.
    """
    tic = detail["tic"]
    sector = detail["sector"]
    survivors, hits = [], []

    def _emit(raw, k3_pass, masked_period):
        row = bs.emit_survivor_record(raw, prov)
        row["tic"] = tic
        row["sector"] = sector
        row["product"] = bs.PRODUCT
        _stamp_meta(row, meta)
        row["k3_pass"] = k3_pass
        # The schema type is number (not nullable): omit the key
        # when the masked period is unknown rather than writing
        # a null that fails validation.
        if masked_period is not None:
            row["k3_masked_period_days"] = masked_period
        # No work_item_id: its contract is same-work →
        # same-output, and a masked re-search is different work
        # from the pass-1 screen (see module docstring).
        _validate_survivor(row)
        return row

    p2 = detail.get("pass2")
    if p2 is not None and p2_full is not None:
        masked_p = (detail.get("ephemeris") or {}).get(
            "period_ref_d")
        row = _emit(p2_full, 2, masked_p)
        if p2.get("sde") is not None and p2["sde"] >= bs.RECORD_FLOOR_SDE:
            hits.append(row)
            if p2.get("status") == "survivor":
                survivors.append(row)
    p3 = detail.get("pass3")
    if p3 is not None:
        masked_p = (detail.get("k3_ephemeris") or {}).get(
            "period_ref_d")
        # Subset-based emit: the subset carries every measured
        # field (period/t0/duration/depth/sde/MES/events/flags);
        # tic/sector/product/meta/prov come from the job.
        raw3 = dict(p3)
        raw3["tic"] = tic
        raw3["sector"] = sector
        raw3["product"] = bs.PRODUCT
        row = _emit(raw3, 3, masked_p)
        if p3.get("sde") is not None and p3["sde"] >= bs.RECORD_FLOOR_SDE:
            hits.append(row)
            if p3.get("status") == "survivor":
                survivors.append(row)
    return {"survivors": survivors, "hits": hits}


def slice_k3_done(out_dir):
    """True when a slice's K=3 stage completed: the slice summary
    carries the "k3" block AND the three stage files exist. The
    summary block is written last (the commit point), so a block
    without files means a torn write — not done."""
    out_dir = Path(out_dir)
    p = out_dir / "summary.json"
    if not p.exists():
        return False
    try:
        s = json.loads(p.read_text())
    except Exception:
        return False
    if not (s.get("k3") or {}).get("enabled"):
        return False
    return all((out_dir / f).exists() for f in (
        K3_SURVIVORS_FILE, K3_HITS_FILE, K3_DETAIL_FILE))


def _read_slice_meta(slice_csv):
    """{tic: {ra, dec, tmag, radius}} from the slice CSV (the
    values _screen_one's job tuple carries)."""
    meta = {}
    with open(slice_csv, newline="") as fh:
        for row in csv.DictReader(fh):
            meta[row["tic"]] = {
                "ra": _float_or_none(row.get("ra")),
                "dec": _float_or_none(row.get("dec")),
                "tmag": _float_or_none(row.get("tmag")),
                "radius": _float_or_none(row.get("radius"))}
    return meta


def _float_or_none(v):
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def run_k3_slice(out_dir, *, slice_csv, cache_dir, sector,
                 calibration, prov, workers=1, keep_fits=False,
                 log=None):
    """The per-slice K=3 stage: run run_k3_star over the slice's
    entry candidates and write the slice's K=3 outputs.

    Reads out_dir/screen_hits.jsonl (pass-1 hits) + the slice
    CSV (star meta); loads each candidate's cached FITS from
    cache_dir/s<SSSS>/<tic>.fits. Writes k3_survivors.jsonl,
    k3_screen_hits.jsonl, k3_detail.jsonl (atomic), then stamps
    the summary.json "k3" block (atomic, LAST — the commit
    point). Re-running the stage overwrites its own files: it is
    idempotent, and a kill mid-stage leaves either no "k3" block
    (stage re-runs cleanly) or a complete one.

    workers <= 1 runs serially (calibration set in-process);
    workers > 1 uses a Pool with the campaign's initializer
    (orc._init_worker — spawn-safe, the Mac path). Missing FITS
    files are recorded (n_missing_fits), not fatal — a star
    whose download failed has no pass-1 hit either in the
    normal case, so a missing file here means a cache gap, and
    the stage must not die on it.

    Returns the "k3" counts block (also stamped on the summary).
    Raises only on structural failures (unreadable hits file /
    summary); per-star failures are counted, not raised.
    """
    log = log or _log_default
    t_stage = time.time()
    out_dir = Path(out_dir)
    cache_dir = Path(cache_dir)
    hits_path = out_dir / "screen_hits.jsonl"
    if not hits_path.exists():
        raise SystemExit(
            f"k3 stage: no screen_hits.jsonl in {out_dir} — "
            f"the slice screen must complete first")
    pass1_hits = [json.loads(l) for l in open(hits_path)]
    candidates = k3_entry_candidates(pass1_hits)
    meta_by_tic = _read_slice_meta(slice_csv)
    workdir = out_dir / "k3_work"
    workdir.mkdir(parents=True, exist_ok=True)
    jobs, missing = [], []
    for r in candidates:
        tic = r["tic"]
        path = cache_dir / f"s{int(sector):04d}" / f"{tic}.fits"
        if not path.exists():
            missing.append(tic)
            continue
        jobs.append({"tic": tic, "sector": int(sector),
                     "path": str(path), "pass1": r,
                     "meta": meta_by_tic.get(tic) or {},
                     "workdir": str(workdir),
                     "keep_fits": keep_fits, "prov": prov})
    log(f"k3 stage: {len(candidates)} candidates "
        f"({len(jobs)} with cached FITS, {len(missing)} missing) "
        f"in {out_dir.name}")
    if workers and workers > 1:
        from multiprocessing import Pool
        with Pool(workers, initializer=orc._init_worker,
                  initargs=(calibration,)) as pool:
            results = pool.map(run_k3_star, jobs)
    else:
        bs.set_calibration(calibration)
        results = [run_k3_star(j) for j in jobs]
    survivors, hits, details = [], [], []
    n_p2 = n_p3 = n_stop2 = n_stop3 = n_err = 0
    for res in results:
        # The detail record excludes the emitted rows (they live
        # in their own files); the row counts are in the block.
        det = {k: v for k, v in res.items() if k != "rows"}
        details.append(det)
        if res.get("error"):
            n_err += 1
            continue
        if res.get("pass2") is not None:
            n_p2 += 1
        if res.get("stopped_pass") == 2:
            n_stop2 += 1
        if res.get("pass3") is not None:
            n_p3 += 1
        if (res.get("k3_mask") or {}).get("stopped") is True:
            n_stop3 += 1
        survivors += res.get("rows", {}).get("survivors", [])
        hits += res.get("rows", {}).get("hits", [])
    # Missing-FITS candidates get a detail record too (audit:
    # the stage saw them and skipped them for a named reason).
    for tic in missing:
        details.append({"tic": tic, "sector": int(sector),
                        "error": "missing-fits", "seconds": 0})
    with _atomic_writer(out_dir / K3_SURVIVORS_FILE) as fh:
        for r in survivors:
            fh.write(json.dumps(r) + "\n")
    with _atomic_writer(out_dir / K3_HITS_FILE) as fh:
        for r in hits:
            fh.write(json.dumps(r) + "\n")
    with _atomic_writer(out_dir / K3_DETAIL_FILE) as fh:
        for r in details:
            fh.write(json.dumps(r) + "\n")
    block = {
        "enabled": True,
        "arm": K3_PRODUCTION_ARM,
        "calibration": calibration,
        "n_pass1_hits": len(pass1_hits),
        "n_candidates": len(candidates),
        "n_entered": len(jobs),
        "n_missing_fits": len(missing),
        "n_pass2_screened": n_p2,
        "n_pass3_screened": n_p3,
        "n_pass2_survivors": sum(
            1 for r in survivors if r.get("k3_pass") == 2),
        "n_pass3_survivors": sum(
            1 for r in survivors if r.get("k3_pass") == 3),
        "n_k3_survivors": len(survivors),
        "n_k3_hits": len(hits),
        "n_stopped_pass2": n_stop2,
        "n_stopped_pass3": n_stop3,
        "n_errors": n_err,
        "seconds": round(time.time() - t_stage, 1),
    }
    # Commit point: the summary's "k3" block, written last.
    summary_path = out_dir / "summary.json"
    summary = json.loads(summary_path.read_text())
    summary["k3"] = block
    _atomic_write_json(summary_path, summary)
    log(f"k3 stage done in {out_dir.name}: {len(survivors)} "
        f"survivors ({block['n_pass2_survivors']} pass-2 + "
        f"{block['n_pass3_survivors']} pass-3), {len(hits)} hits, "
        f"{n_stop2 + n_stop3} stopped, {n_err} errors, "
        f"{len(missing)} missing FITS, "
        f"{block['seconds']}s wall")
    return block
