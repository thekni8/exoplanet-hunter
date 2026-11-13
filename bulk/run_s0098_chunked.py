"""Resilient chunked runner for the sector-98 full-sector screen.

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
import csv, json, subprocess, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
BULK = ROOT / "bulk"
RUN = BULK / "run_s0098"
CHUNKS = RUN / "chunks"
PY = str(BULK / ".venv-cal" / "bin" / "python")
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
    CHUNKS.mkdir(parents=True, exist_ok=True)
    win = json.loads((BULK / "cache" / "target_lists" /
                      "s0098_window_default.json").read_text())
    tics = win["tics"]
    tic_set = set(tics)
    meta = {}
    with open(BULK / "cache" / "target_lists" / "s0098_tic.csv") as fh:
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
            [PY, str(ROOT / "bulk_screen.py"), "--sector", "98",
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
        "tool": "bulk_screen v1.2 chunked driver (run_s0098_chunked)",
        "sector": 98, "stars_in": 39939,
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
