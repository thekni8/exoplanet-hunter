"""Resilient chunked runner for a full-sector screen (generalized).

Sector is a CLI argument (--sector N); all paths derive from it.
The sector-98 run used run_s0098_chunked.py, kept as-is for that
closed run at archive/bulk-screens/s0098/run_s0098_chunked.py.
This file is the same logic, parametrized.

Why this exists (2026-11-11): the monolithic run died TWICE in its
serial all-sky VSX-tile filter stage when the VM was replaced
mid-filter — that stage takes longer than the VM's deployment
lifetime and restarts from zero. This driver composes the existing,
proven pieces differently:

- The 39,939-star window is sliced into ~5,000-star CSVs.
- Each slice runs bulk_screen.py with --skip-filter, so a slice is
  just downloads (globally cached on disk) + BLS screen (~40 min),
  and its summary.json is a CHECKPOINT: a killed driver resumes at
  the first unfinished slice, finished slices are never redone.
- Known-source checks move to the survivor stage, the codebase's
  existing survivors-only pattern: TOI by bulk-set join (cheap),
  VSX by the production per-position query hunter.is_known_in_vsx
  (~640 survivors, fail-open), Zooniverse already runs inside
  bulk_screen on each slice's survivors.
- Merged outputs land in bulk/run_s0098/: survivors.jsonl in tier
  order (A first, MES desc), screen_hits.jsonl, summary.json.

Trade-off, stated plainly: known TOI/VSX stars inside a slice consume
download+compute before being removed at the survivor stage (~25%
extra compute), in exchange for the run actually finishing.
"""
import argparse, csv, json, subprocess, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
BULK = ROOT / "bulk"
SECTOR = None  # set in main() from --sector
RUN = None  # set in main() from --sector
N_STARS = 0  # set by build_slices()
CHUNKS = None  # set in main()
def _find_py():
    """Interpreter with the screen deps. VM uses .venv-cal, Mac uses
    .venv-mac (2026-11-12: the S98 Mac driver was hand-patched for
    this — the per-machine patch is exactly the kind of drift that
    bit us with hunter.py, so resolve it at runtime instead)."""
    for name in (".venv-cal", ".venv-mac"):
        p = BULK / name / "bin" / "python"
        if p.exists():
            return str(p)
    return sys.executable


PY = _find_py()
SLICE = 1250  # was 5000 (2026-11-12): S98 light curves are 200-s
# cadence, 24,165 points/star vs 1,281 in S1 — a 5,000-star slice
# needs ~1.5-2 h of screen time, longer than the VM usually lives
# (20-100 min between replacements). 1,250-star slices screen in
# ~20-30 min, so a checkpoint lands inside one VM lifetime.


def log(msg):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(RUN / "chunked.log", "a") as fh:
        fh.write(line + "\n")


def build_slices():
    global N_STARS
    CHUNKS.mkdir(parents=True, exist_ok=True)
    win = json.loads((BULK / "cache" / "target_lists" /
                      f"s{SECTOR:04d}_window_default.json").read_text())
    tics = win["tics"]
    N_STARS = len(tics)
    tic_set = set(tics)
    meta = {}
    with open(BULK / "cache" / "target_lists" / f"s{SECTOR:04d}_tic.csv") as fh:
        for row in csv.DictReader(fh):
            if row["tic"] in tic_set:
                meta[row["tic"]] = row
    slices = []
    for i in range(0, len(tics), SLICE):
        part = tics[i:i + SLICE]
        p = CHUNKS / f"slice_{i // SLICE:02d}.csv"
        if not p.exists():
            with open(p, "w", newline="") as fh:
                w = csv.writer(fh)
                w.writerow(["tic", "ra", "dec", "tmag", "radius"])
                for t in part:
                    m = meta[t]
                    w.writerow([t, m["ra"], m["dec"], m["tmag"],
                                m["radius"]])
        slices.append(p)
    return slices


def chunk_ok(out):
    """A slice counts as done only if its summary exists AND the screen
    did not mostly fail. Lesson 2026-11-11: chunk_00 'completed' with
    screen_counts {'error': 5000} — every star KeyError'd on the S98
    flux column — and bare summary-existence checkpointed that failure
    as success."""
    p = out / "summary.json"
    if not p.exists():
        return False
    try:
        s = json.loads(p.read_text())
    except Exception:
        return False
    searched = s.get("stars_searched", 0)
    errors = s.get("screen_counts", {}).get("error", 0)
    return searched > 0 and errors <= 0.5 * searched


def main():
    global RUN, CHUNKS, SECTOR
    ap = argparse.ArgumentParser()
    ap.add_argument("--sector", type=int, required=True)
    args = ap.parse_args()
    SECTOR = args.sector
    RUN = BULK / f"run_s{SECTOR:04d}"
    CHUNKS = RUN / "chunks"
    RUN.mkdir(parents=True, exist_ok=True)
    slices = build_slices()
    log(f"{len(slices)} slices")
    t_start = time.time()
    for i, sl in enumerate(slices):
        out = RUN / f"chunk_{i:02d}"
        if chunk_ok(out):
            log(f"slice {i}: valid checkpoint exists, skipping")
            continue
        log(f"slice {i}: screening {sl.name} -> {out.name}")
        r = subprocess.run(
            [PY, str(ROOT / "bulk_screen.py"), "--sector", str(SECTOR),
             "--stars-file", str(sl), "--skip-filter",
             "--cache-dir", str(BULK / "cache"),
             "--out-dir", str(out)],
            capture_output=True, text=True)
        if r.returncode != 0:
            log(f"slice {i}: FAILED rc={r.returncode}\n"
                f"{r.stdout[-1500:]}\n{r.stderr[-1500:]}")
            return 1
        if not chunk_ok(out):
            log(f"slice {i}: FAILED — summary written but screen "
                f"mostly errors (see chunk run.log); not checkpointing")
            return 1
        s = json.loads((out / "summary.json").read_text())
        log(f"slice {i}: done — searched {s.get('stars_searched')}, "
            f"survivors {s.get('survivors')}, "
            f"tiers {s.get('survivor_tiers')}")
    # ---- merge ------------------------------------------------------------
    log("all slices done — merging")
    import bulk_screen as bs
    survivors, hits = [], []
    agg = {"stars_searched": 0, "hits_recorded": 0,
           "zooniverse_known": 0, "screen_counts": {}}
    for i in range(len(slices)):
        out = RUN / f"chunk_{i:02d}"
        s = json.loads((out / "summary.json").read_text())
        agg["stars_searched"] += s.get("stars_searched", 0)
        agg["hits_recorded"] += s.get("hits_recorded", 0)
        agg["zooniverse_known"] += len(
            s.get("zooniverse_known_survivors", []))
        for k, v in s.get("screen_counts", {}).items():
            agg["screen_counts"][k] = agg["screen_counts"].get(k, 0) + v
        survivors += [json.loads(l)
                      for l in open(out / "survivors.jsonl")]
        hits += [json.loads(l) for l in open(out / "screen_hits.jsonl")]
    log(f"merged: {len(survivors)} slice survivors, "
        f"{agg['zooniverse_known']} zooniverse-known already removed")
    # TOI join at survivor stage
    toi_ids = bs._toi_ids_with_retry()
    n_toi = 0
    keep = []
    for r in survivors:
        if toi_ids and r["tic"] in toi_ids:
            n_toi += 1
        else:
            keep.append(r)
    survivors = keep
    log(f"TOI survivor-stage join: removed {n_toi}")
    # VSX per-survivor (production query, fail-open)
    import hunter
    n_vsx = 0
    keep = []
    for r in survivors:
        try:
            if hunter.is_known_in_vsx(r["ra"], r["dec"]):
                n_vsx += 1
                continue
        except Exception:
            pass
        keep.append(r)
    survivors = keep
    log(f"VSX survivor-stage check: removed {n_vsx}")
    survivors.sort(key=lambda r: (0 if r.get("tier") == "A" else 1,
                                  -(r.get("mes_pink") or 0)))
    with open(RUN / "survivors.jsonl", "w") as fh:
        for r in survivors:
            fh.write(json.dumps(r) + "\n")
    with open(RUN / "screen_hits.jsonl", "w") as fh:
        for r in hits:
            fh.write(json.dumps(r) + "\n")
    tiers = {"A": sum(1 for r in survivors if r.get("tier") == "A"),
             "B": sum(1 for r in survivors if r.get("tier") == "B")}
    summary = {
        "tool": "bulk_screen v1.2 chunked driver (run_chunked)",
        "sector": SECTOR, "stars_in": N_STARS,
        "known_filter": {"mode": "survivor-stage (chunked resilience)",
                         "toi_removed": n_toi, "vsx_removed": n_vsx,
                         "zooniverse_removed": agg["zooniverse_known"]},
        "stars_searched": agg["stars_searched"],
        "hits_recorded": agg["hits_recorded"],
        "screen_counts": agg["screen_counts"],
        "survivors": len(survivors), "survivor_tiers": tiers,
        "survivor_tics": [r["tic"] for r in survivors],
        "wall_seconds_chunked_driver": round(time.time() - t_start),
    }
    (RUN / "summary.json").write_text(json.dumps(summary, indent=2))
    log(f"DONE: {len(survivors)} survivors {tiers} from "
        f"{agg['stars_searched']} searched")
    return 0


if __name__ == "__main__":
    sys.exit(main())
