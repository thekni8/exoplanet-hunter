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

Recipes: the run is driven by a YAML recipe (bulk/recipes/*.yaml)
— sector, target window, tag, slice size, workers. See
bulk/recipe.py for the schema. CLI flags override the recipe;
--sector may come from either. The recipe's window is verified
against the target-list window file before any slice runs.
"""
import argparse, csv, json, os, shlex, subprocess, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from atomic_io import atomic_write_json as _atomic_write_json
from atomic_io import atomic_write_text as _atomic_write_text
from atomic_io import atomic_writer as _atomic_writer
from bulk.recipe import (RecipeError, apply_overrides, default_recipe_path,
                         load_recipe)
import provenance as _prov
from validation import validate_survivor as _validate_survivor
BULK = ROOT / "bulk"  # overridable via --work-dir (tests + ports)
SECTOR = None  # set in main() from recipe / --sector
RUN = None  # set in main() from --sector
RECIPE = None  # resolved recipe dict, set in main()
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
# Default slice size (stars per checkpoint). Overridden by the recipe's
# slice_size (2026-11-12: S98 light curves are 200-s cadence, 24,165
# points/star vs 1,281 in S1 — a 5,000-star slice needs ~1.5-2 h of
# screen time, longer than the VM usually lives (20-100 min between
# replacements). 1,250-star slices screen in ~20-30 min, so a
# checkpoint lands inside one VM lifetime).
SLICE = 1250


def _window_path():
    tag = RECIPE["tag"] if RECIPE else "window_default"
    return (BULK / "cache" / "target_lists" /
            f"s{SECTOR:04d}_{tag}.json")


def log(msg):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(RUN / "chunked.log", "a") as fh:
        fh.write(line + "\n")


def build_slices():
    global N_STARS
    CHUNKS.mkdir(parents=True, exist_ok=True)
    wpath = _window_path()
    if not wpath.exists():
        raise SystemExit(
            f"target-list window file not found: {wpath}\n"
            f"Build it first with the same recipe:\n"
            f"  python bulk/build_target_list.py "
            f"--recipe {RECIPE.get('_file', '')} "
            f"--sector {SECTOR}")
    win = json.loads(wpath.read_text())
    _verify_window(win)
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
            # Atomic (Phase 1.1, item 8): a kill mid-write used to
            # leave a truncated slice CSV that "exists" and was
            # never rewritten — those stars were silently dropped.
            lines = ["tic,ra,dec,tmag,radius"]
            for t in part:
                m = meta[t]
                lines.append(",".join([t, m["ra"], m["dec"],
                                       m["tmag"], m["radius"]]))
            _atomic_write_text(p, "\n".join(lines) + "\n")
        slices.append(p)
    return slices


def _verify_window(win):
    """The window file records the params it was built with
    (stats.window). They must match the recipe — otherwise we'd screen
    a different star set than the recipe says. Legacy window files
    without stats.window get a warning, not a refusal."""
    recorded = (win.get("stats") or {}).get("window")
    if not recorded:
        log("WARNING: window file has no recorded build params; "
            "cannot verify it matches the recipe")
        return
    want = RECIPE["window"]
    mismatches = [f"{k}: recipe={want[k]!r} window-file={recorded.get(k)!r}"
                  for k in ("min_mag", "max_mag", "min_rad", "max_rad",
                            "require_radius", "limit_ids")
                  if recorded.get(k) != want[k]]
    if mismatches:
        raise SystemExit(
            "recipe/window mismatch — refusing to screen the wrong "
            "star set:\n  " + "\n  ".join(mismatches) + "\n"
            "Rebuild the target list with the same recipe:\n"
            f"  python bulk/build_target_list.py "
            f"--recipe {RECIPE.get('_file', '')} --sector {SECTOR}")


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


def _checkpoint_path():
    return RUN / "checkpoint.json"


def read_checkpoint():
    """The run-level progress record, or None when no slice has
    completed yet (or the file is corrupt — a corrupt checkpoint
    is ignored, never trusted: chunk_ok re-derives the truth
    from the slice summaries)."""
    p = _checkpoint_path()
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


def write_checkpoint(completed):
    """Atomically record which slices are done. `completed` maps
    slice index -> {chunk, summary_sha256, stars_searched,
    survivors, completed_at}. Written after EVERY slice, so a
    kill costs at most the in-flight slice — and the summary hash
    lets a resume VERIFY a checkpoint instead of trusting that a
    summary file merely exists."""
    cp = {"run_dir": str(RUN),
          "sector": SECTOR,
          "n_slices": len(completed),
          "completed": {str(k): v for k, v in completed.items()},
          "updated_at": _prov.utc_now_iso()}
    _atomic_write_json(_checkpoint_path(), cp)


def _checkpoint_entry(out, summary):
    return {"chunk": out.name,
            "summary_sha256": _prov.file_sha256(
                out / "summary.json"),
            "stars_searched": summary.get("stars_searched"),
            "survivors": summary.get("survivors"),
            "completed_at": _prov.utc_now_iso()}


def _screen_cmd():
    """The screen invocation. EXHUNT_SCREEN_CMD overrides the
    production bulk_screen.py call (test seam, same pattern as
    EXHUNT_FIXTURE_DIR): the value is shell-split and the driver's
    slice arguments are appended. Production runs never set it."""
    override = os.environ.get("EXHUNT_SCREEN_CMD")
    if override:
        return shlex.split(override)
    return [PY, str(ROOT / "bulk_screen.py")]


def main():
    global RUN, CHUNKS, SECTOR, RECIPE, SLICE, BULK
    ap = argparse.ArgumentParser()
    ap.add_argument("--recipe", default=str(default_recipe_path()),
                    help="YAML recipe file (default: bulk/recipes/default.yaml)")
    ap.add_argument("--sector", type=int, default=None,
                    help="TESS sector (overrides the recipe)")
    ap.add_argument("--work-dir", default=None,
                    help="bulk working directory (default: <repo>/bulk); "
                         "overrides where the window files, chunks and "
                         "run output live — tests point it at a temp dir")
    ap.add_argument("--skip-known-filter", action="store_true",
                    help="skip the merge-stage TOI/VSX known-source "
                         "checks (offline re-merge; the checks are "
                         "fail-open, so skipping them explicitly is "
                         "the same as MAST being down)")
    ap.add_argument("--min-mag", type=float, default=None)
    ap.add_argument("--max-mag", type=float, default=None)
    ap.add_argument("--min-rad", type=float, default=None)
    ap.add_argument("--max-rad", type=float, default=None)
    ap.add_argument("--require-radius",
                    action=argparse.BooleanOptionalAction, default=None)
    ap.add_argument("--limit-ids", type=int, default=None)
    ap.add_argument("--tag", default=None)
    ap.add_argument("--slice-size", type=int, default=None)
    ap.add_argument("--dl-workers", type=int, default=None)
    ap.add_argument("--workers", type=int, default=None)
    args = ap.parse_args()
    try:
        recipe = load_recipe(args.recipe)
        recipe = apply_overrides(recipe, {
            "sector": args.sector, "min_mag": args.min_mag,
            "max_mag": args.max_mag, "min_rad": args.min_rad,
            "max_rad": args.max_rad,
            "require_radius": args.require_radius,
            "limit_ids": args.limit_ids, "tag": args.tag,
            "slice_size": args.slice_size,
            "dl_workers": args.dl_workers, "workers": args.workers,
        })
    except RecipeError as exc:
        ap.error(str(exc))
    SECTOR = recipe["sector"]
    if SECTOR is None:
        ap.error("--sector is required (or set sector: in the recipe)")
    RECIPE = recipe
    SLICE = recipe["slice_size"]
    if args.work_dir:
        BULK = Path(args.work_dir)
    RUN = BULK / f"run_s{SECTOR:04d}"
    CHUNKS = RUN / "chunks"
    RUN.mkdir(parents=True, exist_ok=True)
    # Provenance for the whole run (Phase 1.1, item 1): one run id
    # and one resolved-recipe hash, passed to every slice so all
    # records from this run carry the same header. The run manifest
    # makes the run directory self-describing.
    RUN_ID = _prov.new_run_id("bulk")
    R_HASH = _prov.recipe_hash(RECIPE)
    MANIFEST = _prov.build_manifest(
        RUN_ID, "bulk_v1", sector=SECTOR, product="QLP",
        recipe=RECIPE, recipe_file=RECIPE.get("_file"),
        status="started")
    _prov.write_manifest(RUN, MANIFEST)
    log(f"run_id: {RUN_ID} (recipe hash {R_HASH[:12]}…, "
        f"calibration bulk_v1)")
    log(f"recipe: {recipe['_file']} (sector {SECTOR}, "
        f"window Tmag {recipe['window']['min_mag']}-"
        f"{recipe['window']['max_mag']}, R "
        f"{recipe['window']['min_rad']}-"
        f"{recipe['window']['max_rad']}, tag {recipe['tag']}, "
        f"slice {SLICE}, dl-workers {recipe['dl_workers']}, "
        f"workers {recipe['workers'] or 'default'})")
    slices = build_slices()
    log(f"{len(slices)} slices")
    # Resume state (Phase 1.1, item 8): the checkpoint records
    # completed slices + their summary hashes. chunk_ok is still
    # the authority — a checkpoint entry whose slice no longer
    # validates is dropped and the slice re-runs.
    completed = {}
    prev = read_checkpoint()
    if prev:
        for k, v in (prev.get("completed") or {}).items():
            i = int(k)
            out = RUN / f"chunk_{i:02d}"
            if chunk_ok(out) and _prov.file_sha256(
                    out / "summary.json") == v.get("summary_sha256"):
                completed[i] = v
            else:
                # The checkpoint ENTRY is dropped — the slice loop
                # below still decides from chunk_ok alone, so a
                # slice with a valid summary is skipped, not
                # re-screened; only the entry's hash is distrusted.
                log(f"slice {i}: checkpoint entry invalid or "
                    f"stale, dropping it (chunk_ok decides)")
        if completed:
            log(f"resuming: {len(completed)}/{len(slices)} slices "
                f"already complete")
    t_start = time.time()
    for i, sl in enumerate(slices):
        out = RUN / f"chunk_{i:02d}"
        if chunk_ok(out):
            log(f"slice {i}: valid checkpoint exists, skipping")
            if i not in completed:
                s = json.loads((out / "summary.json").read_text())
                completed[i] = _checkpoint_entry(out, s)
                write_checkpoint(completed)
            continue
        log(f"slice {i}: screening {sl.name} -> {out.name}")
        cmd = _screen_cmd() + ["--sector", str(SECTOR),
               "--stars-file", str(sl), "--skip-filter",
               "--cache-dir", str(BULK / "cache"),
               "--out-dir", str(out),
               "--run-id", RUN_ID, "--recipe-hash", R_HASH,
               "--dl-workers", str(recipe["dl_workers"])]
        if recipe["workers"] is not None:
            cmd += ["--workers", str(recipe["workers"])]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            log(f"slice {i}: FAILED rc={r.returncode}\n"
                f"{r.stdout[-1500:]}\n{r.stderr[-1500:]}")
            return 1
        if not chunk_ok(out):
            log(f"slice {i}: FAILED — summary written but screen "
                f"mostly errors (see chunk run.log); not checkpointing")
            return 1
        s = json.loads((out / "summary.json").read_text())
        completed[i] = _checkpoint_entry(out, s)
        write_checkpoint(completed)
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
    n_toi = n_vsx = 0
    if args.skip_known_filter:
        log("known-source checks skipped (--skip-known-filter)")
    else:
        # TOI join at survivor stage
        toi_ids = bs._toi_ids_with_retry()
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
    # Atomic merge outputs (Phase 1.1, item 8): a kill mid-merge
    # used to leave truncated merged files. The merge itself is
    # idempotent — it recomputes from the slice outputs — so a
    # re-run after a kill reproduces the same files exactly.
    with _atomic_writer(RUN / "survivors.jsonl") as fh:
        for r in survivors:
            # Slice records were validated at write time; re-validating
            # at merge catches a slice file corrupted or hand-edited
            # since (Phase 1.1, item 3).
            _validate_survivor(r)
            fh.write(json.dumps(r) + "\n")
    with _atomic_writer(RUN / "screen_hits.jsonl") as fh:
        for r in hits:
            fh.write(json.dumps(r) + "\n")
    tiers = {"A": sum(1 for r in survivors if r.get("tier") == "A"),
             "B": sum(1 for r in survivors if r.get("tier") == "B")}
    summary = {
        "tool": "bulk_screen v1.2 chunked driver (run_chunked)",
        "sector": SECTOR, "stars_in": N_STARS,
        "provenance": _prov.provenance_header(
            RUN_ID, "bulk_v1", recipe_hash=R_HASH,
            sha=MANIFEST["pipeline"]["git_sha"],
            timestamp_utc=MANIFEST["execution"]["started_at"]),
        "recipe": {"file": RECIPE["_file"],
                   "resolved_hash": R_HASH,
                   "params": {k: v for k, v in RECIPE.items()
                              if not k.startswith("_")}},
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
    _atomic_write_json(RUN / "summary.json", summary)
    MANIFEST["execution"]["status"] = "completed"
    MANIFEST["execution"]["wall_seconds"] = round(
        time.time() - t_start)
    MANIFEST["counts"] = {
        "stars_searched": agg["stars_searched"],
        "hits_recorded": agg["hits_recorded"],
        "survivors": len(survivors),
        "screen_counts": agg["screen_counts"],
    }
    _prov.write_manifest(RUN, MANIFEST)
    log(f"DONE: {len(survivors)} survivors {tiers} from "
        f"{agg['stars_searched']} searched")
    return 0


if __name__ == "__main__":
    sys.exit(main())
