#!/usr/bin/env python3
"""Deterministic stub for bulk_screen.py — used ONLY by the
resume tests (tests/test_resume.py) via the EXHUNT_SCREEN_CMD
seam. It accepts the driver's slice arguments, reads the slice
CSV, and writes bulk_screen-shaped outputs (survivors.jsonl,
screen_hits.jsonl, summary.json) with DETERMINISTIC outcomes
derived from the TIC id alone — so an uninterrupted run and a
kill-and-resume run must produce byte-identical merged outputs.

Outcome rule: a star is a survivor iff int(tic) % 3 == 0 (tier A
iff int(tic) % 6 == 0, else tier B); every other star is
recorded. Periods, SDEs and MES values are arithmetic on the TIC
— no randomness, no network, no time dependence (the timestamp
is fixed).

Each invocation appends one line to the invocation log
(EXHUNT_STUB_LOG, default <out-dir>/../stub_invocations.log)
recording the slice file — the resume test counts invocations
per slice to prove finished slices are never re-screened.

--sleep SECONDS pauses before writing (widens the kill window
for the SIGKILL test). Summary.json is written LAST, exactly
like the real screen: it is the chunk checkpoint.
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from atomic_io import atomic_write_json, atomic_writer  # noqa: E402

FIXED_TIMESTAMP = "2026-11-14T00:00:00+00:00"


def record_for(tic, ra, dec, tmag, radius, sector, run_id,
               mixed_pipeline=False):
    n = int(tic)
    survivor = (n % 3 == 0)
    rec = {
        "tic": str(tic),
        "sector": sector,
        "product": "QLP",
        "status": "survivor" if survivor else "recorded",
        "period_days": 1.0 + (n % 17) * 0.5,
        "t0_btjd": 1500.0 + (n % 100) * 0.01,
        "duration_hours": 2.0 + (n % 5) * 0.25,
        "depth_percent": 0.5 + (n % 10) * 0.1,
        "sde": 7.0 + (n % 20) * 0.5,
        "mes_pink": 9.0 + (n % 15) if survivor else 5.0,
        "n_events": 3 + (n % 5),
        "n_strong_events": 2 + (n % 3),
        "max_event_snr": 8.0 + (n % 7),
        "near_systematic": False,
        "odd_even_ratio": 0.9 + (n % 10) * 0.01,
        "secondary_depth_percent": 0.0,
        "v_ratio": 1.0,
        "cdpp_pct": 0.3,
        "flags": [],
        "tier": ("A" if n % 6 == 0 else "B") if survivor else None,
        "ra": float(ra),
        "dec": float(dec),
        "tmag": float(tmag),
        "radius_rsun": float(radius),
        "schema_version": "1.1",
        "run_id": run_id,
        "pipeline_git_sha": "stub",
        "calibration_version": "bulk_v1",
        "timestamp_utc": FIXED_TIMESTAMP,
    }
    if mixed_pipeline:
        rec["mixed_pipeline"] = True
    return rec


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--sector", type=int, required=True)
    ap.add_argument("--stars-file", required=True)
    ap.add_argument("--skip-filter", action="store_true")
    ap.add_argument("--cache-dir", default=None)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--run-id", default="stub-run")
    ap.add_argument("--recipe-hash", default=None)
    ap.add_argument("--dl-workers", default=None)
    ap.add_argument("--workers", default=None)
    ap.add_argument("--sleep", type=float, default=0.0)
    ap.add_argument("--mixed-pipeline", action="store_true",
                    help="stamp mixed_pipeline=true on every record "
                         "(A-3 test seam — mirrors bulk_screen.py)")
    args = ap.parse_args(argv)

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    log_path = Path(os.environ.get(
        "EXHUNT_STUB_LOG", out.parent / "stub_invocations.log"))
    with open(log_path, "a") as fh:
        fh.write(f"{Path(args.stars_file).name}\n")
    if args.sleep:
        time.sleep(args.sleep)

    import csv
    stars = []
    with open(args.stars_file, newline="") as fh:
        for row in csv.DictReader(fh):
            stars.append(row)
    records = [record_for(r["tic"], r["ra"], r["dec"], r["tmag"],
                          r["radius"], args.sector, args.run_id,
                          mixed_pipeline=args.mixed_pipeline)
               for r in stars]
    survivors = [r for r in records if r["status"] == "survivor"]
    with atomic_writer(out / "survivors.jsonl") as fh:
        for r in survivors:
            fh.write(json.dumps(r) + "\n")
    with atomic_writer(out / "screen_hits.jsonl") as fh:
        for r in records:
            fh.write(json.dumps(r) + "\n")
    summary = {
        "stars_searched": len(records),
        "hits_recorded": len(records),
        "survivors": len(survivors),
        "survivor_tiers": {
            t: sum(1 for r in survivors if r.get("tier") == t)
            for t in ("A", "B")},
        "survivor_tics": [r["tic"] for r in survivors],
        "screen_counts": {"survivor": len(survivors),
                          "recorded": len(records) - len(survivors),
                          "error": 0},
        "zooniverse_known_survivors": [],
    }
    atomic_write_json(out / "summary.json", summary)
    print(f"stub screen: {len(records)} stars, "
          f"{len(survivors)} survivors -> {out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
