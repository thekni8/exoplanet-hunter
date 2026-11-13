#!/usr/bin/env python
"""Cap-20 persistence only, for a folds-completed star: reads the
ephemeris from vetting_results/{tic}.json, runs the standalone
module, saves the full table sidecar, embeds the summary as
'persistence' in the JSON. Usage: sweep4_persist_only.py TIC RADIUS
"""
import json
import sys
import time
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))

import persistence  # noqa: E402
from sweep4_vet import persistence_summary  # noqa: E402


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


tic, radius = sys.argv[1], float(sys.argv[2])
jp = BASE / "vetting_results" / f"{tic}.json"
d = json.loads(jp.read_text())
a = d["analyze"]
per = persistence.sector_persistence(
    tic, radius, a["period_days"], a["t0_days"], a["duration_hours"],
    sector_cap=20, progress_callback=lambda m: log(f"  e: {m}"))
(BASE / "vetting_results" / f"{tic}_persistence_cap20.json").write_text(
    json.dumps(per, indent=2, default=str))
d["persistence"] = persistence_summary(per)
jp.write_text(json.dumps(d, indent=2, default=str))
log(f"TIC {tic}: persistence -> {per.get('verdict')} "
    f"(usable {per.get('n_usable')}, pos {per.get('n_pos_1p5sigma')}, "
    f"wmean {per.get('weighted_mean_depth_pct')}, "
    f"monsters {[m['sector'] for m in per.get('raw_monster_sectors') or []]})")
