#!/usr/bin/env python3
"""Headless sweep driver for Exoplanet Hunter — built for GitHub Actions.

Starts the production app exactly as a human would (bash run.sh), launches
one sweep through its real API, watches it to completion, and harvests
everything worth keeping into ./sweep-output/ :

    result.json       full sweep result (every hit, every field)
    discoveries.json  the hits-only table (SDE >= 8.5) after the run
    history.json      recent run history
    hunter.db         the run's SQLite database
    discoveries.csv   hunter.py's CSV, if written
    reports/*.png     diagnostic plots produced during this run
    server.log        the app's own output
    SUMMARY.md        human-readable digest (settings, hits)

Stdlib only — requirements.txt has no `requests`, and this script must run
anywhere the app itself can. Exit codes: 0 = sweep done, 2 = sweep failed,
3 = driver timeout / app never came up.
"""

import argparse
import glob
import json
import os
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "sweep-output"


def http(method, url, payload=None, timeout=60):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode()
        return json.loads(body) if body else {}


def pick(d, *keys):
    for k in keys:
        v = d.get(k)
        if v is not None:
            return v
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ra", type=float, required=True)
    ap.add_argument("--dec", type=float, required=True)
    ap.add_argument("--cone", type=float, default=1.0)
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--min-mag", type=float, default=11.5)
    ap.add_argument("--max-mag", type=float, default=15.0)
    ap.add_argument("--min-rad", type=float, default=0.2)
    ap.add_argument("--max-rad", type=float, default=0.5)
    ap.add_argument("--sector-cap", type=int, default=20)
    ap.add_argument("--bls-points", type=int, default=10000)
    ap.add_argument("--scanner", action="store_true",
                    help="use the app's Deep Space Scanner defaults instead")
    ap.add_argument("--max-minutes", type=int, default=315)
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()

    OUT.mkdir(exist_ok=True)
    base = f"http://127.0.0.1:{args.port}"
    started = time.time()
    started_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    server_log = open(OUT / "server.log", "w")
    proc = subprocess.Popen(["bash", "run.sh"], cwd=ROOT, stdout=server_log,
                            stderr=subprocess.STDOUT, start_new_session=True)
    exit_code = 3
    try:
        # --- wait for the app -------------------------------------------------
        up = False
        for _ in range(75):  # ~5 min: pip-free start is fast, be generous
            if proc.poll() is not None:
                print("server exited during startup — see server.log", flush=True)
                return 3
            try:
                http("GET", f"{base}/api/history?limit=1", timeout=10)
                up = True
                break
            except Exception:
                time.sleep(4)
        if not up:
            print("app never came up", flush=True)
            return 3
        print(f"app up; launching sweep RA {args.ra} Dec {args.dec}", flush=True)

        # --- launch -----------------------------------------------------------
        payload = {
            "ra": args.ra, "dec": args.dec, "cone": args.cone,
            "limit": args.limit, "min_mag": args.min_mag,
            "max_mag": args.max_mag, "min_rad": args.min_rad,
            "max_rad": args.max_rad, "bls_points": args.bls_points,
            "sector_cap": args.sector_cap, "detrend_window": 101,
            "scanner": args.scanner,
        }
        job = http("POST", f"{base}/api/sweep", payload)
        job_id = job["job_id"]
        print(f"job {job_id} queued", flush=True)

        # --- watch ------------------------------------------------------------
        deadline = started + args.max_minutes * 60
        printed = 0
        fails = 0
        status = "running"
        while time.time() < deadline:
            try:
                st = http("GET", f"{base}/api/jobs/{job_id}", timeout=30)
                fails = 0
            except Exception as e:
                fails += 1
                if fails > 5:
                    raise
                print(f"(poll retry {fails}: {e})", flush=True)
                time.sleep(30)
                continue
            status = st["status"]
            progress = st.get("progress") or []
            for line in progress[printed:]:
                print(line, flush=True)
            printed = len(progress)
            if status not in ("queued", "running"):
                break
            time.sleep(45)

        # --- harvest ----------------------------------------------------------
        summary = [f"# Sweep run — {started_iso}",
                   "",
                   f"- RA {args.ra}, Dec {args.dec}, cone {args.cone} deg",
                   f"- Stars requested: {args.limit} | Tmag {args.min_mag}-{args.max_mag}"
                   f" | radius {args.min_rad}-{args.max_rad} Rsun",
                   f"- Sector cap {args.sector_cap} | BLS points {args.bls_points}"
                   f" | scanner mode: {args.scanner}",
                   f"- Job {job_id}: **{status}**",
                   ""]
        if status == "done":
            exit_code = 0
            result = http("GET", f"{base}/api/jobs/{job_id}/result", timeout=60)
            (OUT / "result.json").write_text(json.dumps(result, indent=2))
            try:
                disc = http("GET", f"{base}/api/discoveries", timeout=30)
                (OUT / "discoveries.json").write_text(json.dumps(disc, indent=2))
            except Exception as e:
                print(f"discoveries fetch failed: {e}", flush=True)
            hits = result.get("hits") or []
            summary.append(f"Targets analyzed: {result.get('targets_analyzed')}")
            summary.append(f"**Hits (SDE >= 8.5): {len(hits)}**")
            summary.append("")
            for h in hits:
                tic = pick(h, "tic_id", "tic", "target", "id")
                per = pick(h, "period_days", "period")
                sde = pick(h, "sde")
                dep = pick(h, "depth_percent", "depth_pct", "depth")
                rp = pick(h, "planet_radius_earth", "radius_earth", "rp_earth")
                perst = pick(h, "persistence_label", "persistence")
                bits = [f"- TIC {tic}: P {per} d, SDE {sde}"]
                if dep is not None:
                    bits.append(f"depth {dep}%")
                if rp is not None:
                    bits.append(f"Rp {rp} R_earth")
                if perst is not None:
                    bits.append(f"persistence {perst}")
                summary.append(", ".join(bits))
        else:
            exit_code = 2 if status in ("failed", "error") else 3
            summary.append(f"Sweep did not complete (final status: {status})."
                           " See server.log and result files for detail.")
            try:
                st = http("GET", f"{base}/api/jobs/{job_id}", timeout=30)
                (OUT / "job_final.json").write_text(json.dumps(st, indent=2))
                if st.get("error"):
                    summary.append(f"Error: {st['error']}")
            except Exception:
                pass
        try:
            hist = http("GET", f"{base}/api/history?limit=5", timeout=30)
            (OUT / "history.json").write_text(json.dumps(hist, indent=2))
        except Exception:
            pass
        (OUT / "SUMMARY.md").write_text("\n".join(summary) + "\n")
        print("\n".join(summary), flush=True)

        # --- static harvest ---------------------------------------------------
        rep_out = OUT / "reports"
        rep_out.mkdir(exist_ok=True)
        for png in glob.glob(str(ROOT / "reports" / "*.png")):
            if os.path.getmtime(png) >= started - 5:
                shutil.copy2(png, rep_out)
        for name, src in (("hunter.db", ROOT / "data" / "hunter.db"),
                          ("discoveries.csv", ROOT / "discoveries.csv")):
            if src.exists():
                shutil.copy2(src, OUT / name)
        return exit_code
    finally:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
            proc.wait(timeout=10)
        except Exception:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except Exception:
                pass
        server_log.close()


if __name__ == "__main__":
    sys.exit(main())
