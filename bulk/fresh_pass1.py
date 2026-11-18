"""Pass-1 establishment for fresh injection manifests (Phase 4.1).

A fresh manifest's trials need RECORDED periods before the P4-3
stacking campaign can run on them (the campaign reads
trial["recorded"] -- the frozen pass-1 peak on the injected
curve in the trial's original sector). This driver establishes
them: for each trial in a pre-manifest, inject the planet into
the host's ORIGINAL-sector cached FITS, run unchanged pass 1
(bulk_screen._screen_one), and record the screen + recovery.

Mirrors inject_campaign.run_host's per-trial shape (same screen
record fields, same n_events_found mapping, same
check_recovery) so the downstream group classification
(build_oracle_manifest.py's logic) applies unchanged. Pass 1
only -- no rescore, no oracle pass 2 (unlike oracle_run).

Input: a pre-manifest JSON {"meta": ..., "hosts": [...],
"trials": [...]} -- trials carry tic, sector, trial_id,
period_d, epoch_offset_d, depth_frac, duration_d, seed.
Output: per-host files <out-dir>/hosts/<tic>_s<sector>.json
with the screen record per trial, plus a summary. The manifest
builder (build_p43c_fresh_manifest.py, VM-side) classifies
groups and assembles the p43 manifest from these files.

Calibration is the CLI value (bulk_v5 for Phase 4.1). Offline
on the Mac (cached FITS only). No S98 data is read at any point.
No new dependencies. No push / merge / PR -- the parent does
those.
"""

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))

import bulk_screen as bs  # noqa: E402
from bulk.inject_campaign import check_recovery  # noqa: E402
from bulk.inject_campaign import expected_n_events  # noqa: E402
from bulk.inject_campaign import inject_trial  # noqa: E402
from bulk.inject_real_s96 import load_real_fits  # noqa: E402
from bulk.inject_real_s96 import write_injected_fits  # noqa: E402
from synth_fits import screen_job  # noqa: E402


def _screen_record(r):
    """The P3-10 screen record shape (inject_campaign.run_host):
    the fields build_oracle_manifest.py's group logic reads, plus
    t0/duration for the P4-3c epoch audit. n_events_found is the
    screen's n_events (the P3-10 mapping)."""
    return {
        "sde": r.get("sde"),
        "mes_pink": r.get("mes_pink"),
        "status": r.get("status"),
        "tier": r.get("tier"),
        "period_days": r.get("period_days"),
        "t0_btjd": r.get("t0_btjd"),
        "duration_hours": r.get("duration_hours"),
        "depth_percent": r.get("depth_percent"),
        "flags": r.get("flags", []),
        "odd_even_ratio": r.get("odd_even_ratio"),
        "search_health": r.get("search_health"),
        "n_events_found": r.get("n_events"),
        "n_strong_events": r.get("n_strong_events"),
        "max_event_snr": r.get("max_event_snr"),
        "gate_reason": r.get("gate_reason"),
    }


def run_host_pass1(job):
    """One host: inject each pre-manifest trial into the ORIGINAL
    sector, screen (pass 1), record. Mirrors
    inject_campaign.run_host's per-trial computation (inject via
    inject_trial with the epoch_offset, epoch_btjd + duration
    from the injection, n_events_expected from the sector
    baseline, recovered via check_recovery)."""
    tic = job["tic"]
    sector = int(job["sector"])
    out_dir = Path(job["out_dir"])
    workdir = Path(job["workdir"])
    pre_sha = job["pre_manifest_sha"]
    calibration = job["calibration"]
    keep_fits = job.get("keep_fits", False)
    out_path = out_dir / "hosts" / f"{tic}_s{sector:04d}.json"
    if out_path.exists():
        try:
            prev = json.loads(out_path.read_text())
        except ValueError:
            prev = {}
        if (prev.get("complete") is True
                and prev.get("pre_manifest_sha") == pre_sha
                and prev.get("calibration") == calibration):
            return {"status": "skipped", "tic": tic,
                    "sector": sector}
    t_start = time.time()
    try:
        t, f, q, fcol, meta = load_real_fits(job["path"])
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "tic": tic, "sector": sector,
                "error": f"load_real_fits: {exc}"}
    t_min = float(np.nanmin(t))
    t_max = float(np.nanmax(t))
    results = []
    for tr in job["trials"]:
        r = {"trial_id": tr["trial_id"], "tic": tic,
             "sector": sector,
             "period_d": tr["period_d"],
             "epoch_offset_d": tr["epoch_offset_d"],
             "depth_frac": tr["depth_frac"],
             "seed": tr.get("seed"),
             "trial_index": tr.get("trial_index")}
        t_tr = time.time()
        try:
            spec = {"kind": "planet", "period_d": tr["period_d"],
                    "epoch_offset_d": tr["epoch_offset_d"],
                    "depth_frac": tr["depth_frac"]}
            f_inj, dur_d, epoch = inject_trial(t, f, q, spec, t_min)
            # Sanity: the injection's epoch/duration must match
            # the pre-manifest's (same law, same inputs).
            r["inject_epoch_delta_d"] = float(
                epoch - (t_min + tr["epoch_offset_d"]))
            r["inject_dur_delta_d"] = float(
                dur_d - tr["duration_d"])
            r["epoch_btjd"] = float(epoch)
            r["duration_d"] = float(dur_d)
            r["n_events_expected"] = expected_n_events(
                epoch, tr["period_d"], t_min, t_max)
            inj_path = (workdir /
                        f"{tic}_s{sector:04d}_{tr['trial_id']}.fits")
            write_injected_fits(str(inj_path), t, f_inj, q, fcol)
            p1 = bs._screen_one(screen_job(str(inj_path), tic=tic,
                                           sector=sector,
                                           meta=meta))
            if not keep_fits:
                inj_path.unlink(missing_ok=True)
            r["screen"] = _screen_record(p1)
            r["recovered"] = bool(check_recovery(
                p1, tr["period_d"]))
        except Exception as exc:  # noqa: BLE001
            r["error"] = f"{type(exc).__name__}: {exc}"
        r["seconds"] = round(time.time() - t_tr, 2)
        results.append(r)
    rec = {"tic": tic, "sector": sector, "complete": True,
           "pre_manifest_sha": pre_sha,
           "calibration": calibration,
           "n_trials": len(results),
           "seconds": round(time.time() - t_start, 1),
           "trials": results}
    tmp = out_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(rec))
    tmp.replace(out_path)
    return {"status": "done", "tic": tic, "sector": sector,
            "n_trials": len(results),
            "n_recovered": sum(1 for r in results
                               if r.get("recovered") is True)}


def _init_worker(calibration):
    bs.set_calibration(calibration)


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Pass-1 establishment for a fresh injection "
                    "pre-manifest (Phase 4.1).")
    ap.add_argument("--pre-manifest", required=True,
                    help="pre-manifest JSON (hosts + trials)")
    ap.add_argument("--cache", required=True,
                    help="bulk/cache dir with s0095/s0096/s0097")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--calibration", default="bulk_v5")
    ap.add_argument("--tics", nargs="*", default=None)
    ap.add_argument("--keep-fits", action="store_true")
    args = ap.parse_args(argv)
    out_dir = Path(args.out_dir)
    cache = Path(args.cache)
    pre = json.loads(Path(args.pre_manifest).read_text())
    pre_sha = hashlib.sha256(
        Path(args.pre_manifest).read_bytes()).hexdigest()
    by_host = {}
    for tr in pre["trials"]:
        by_host.setdefault((tr["tic"], int(tr["sector"])),
                           []).append(tr)
    jobs, missing = [], []
    for (tic, sector), trials in sorted(
            by_host.items(), key=lambda kv: (kv[0][1], int(kv[0][0]))):
        if args.tics and tic not in args.tics:
            continue
        p = cache / f"s{sector:04d}" / f"{tic}.fits"
        if not p.exists():
            missing.append((tic, sector))
            continue
        jobs.append({"tic": tic, "sector": sector,
                     "path": str(p), "trials": trials,
                     "out_dir": str(out_dir),
                     "workdir": str(out_dir / "injected"),
                     "calibration": args.calibration,
                     "keep_fits": args.keep_fits,
                     "pre_manifest_sha": pre_sha})
    print(f"[fresh-pass1] {len(jobs)} host jobs, "
          f"{len(missing)} missing FITS", flush=True)
    if missing:
        for tic, sec in missing[:10]:
            print(f"[fresh-pass1] MISSING TIC {tic} s{sec:04d}",
                  flush=True)
    (out_dir / "hosts").mkdir(parents=True, exist_ok=True)
    (out_dir / "injected").mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    if args.workers <= 1:
        bs.set_calibration(args.calibration)
        results = [run_host_pass1(j) for j in jobs]
    else:
        from multiprocessing import Pool
        with Pool(args.workers, initializer=_init_worker,
                  initargs=(args.calibration,)) as pool:
            results = pool.map(run_host_pass1, jobs)
    done = sum(1 for r in results if r["status"] == "done")
    skipped = sum(1 for r in results if r["status"] == "skipped")
    failures = [r for r in results if r["status"] == "error"]
    for r in failures:
        print(f"[fresh-pass1] ERROR TIC {r['tic']} "
              f"s{r['sector']:04d}: {r.get('error')}", flush=True)
    n_trials = sum(r.get("n_trials", 0) for r in results
                   if r["status"] == "done")
    n_rec = sum(r.get("n_recovered", 0) for r in results
                if r["status"] == "done")
    wall = time.time() - t0
    print(f"[fresh-pass1] done: {done} run, {skipped} skipped, "
          f"{len(failures)} failed; {n_trials} trials, "
          f"{n_rec} recovered; {wall:.0f}s wall "
          f"({wall / max(n_trials, 1):.2f} s/trial)", flush=True)
    summary = {"tool": "fresh_pass1",
               "pre_manifest_sha": pre_sha,
               "calibration": args.calibration,
               "n_hosts_run": done, "n_hosts_skipped": skipped,
               "n_hosts_failed": len(failures),
               "n_trials": n_trials, "n_recovered": n_rec,
               "wall_s": round(wall, 1),
               "seconds_per_trial": round(wall / max(n_trials, 1),
                                          3),
               "missing": [[t, s] for t, s in missing]}
    (out_dir / "pass1_summary.json").write_text(
        json.dumps(summary, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
