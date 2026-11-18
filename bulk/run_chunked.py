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
from calibration import CalibrationError as _CalibrationError
from calibration import load_profile as _load_profile
from calibration import short_version as _short_version
import provenance as _prov
from validation import validate_survivor as _validate_survivor
BULK = ROOT / "bulk"  # overridable via --work-dir (tests + ports)
SECTOR = None  # set in main() from recipe / --sector
RUN = None  # set in main() from --sector
RECIPE = None  # resolved recipe dict, set in main()
N_STARS = 0  # set by build_slices()
CHUNKS = None  # set in main()
# A-3: fingerprint of the result-affecting files this process runs
# (computed once in main()); MIXED_PIPELINE is True when the run
# resumed across a result-affecting code change under
# --accept-code-change, and is stamped on the checkpoint, the
# manifest, the summary, and (via --mixed-pipeline) every record
# the resumed run writes.
CODE_FINGERPRINT = None
MIXED_PIPELINE = False
# C-8: the run fingerprint block for this process (full + resume
# hashes + components), taken from the manifest in main(). The
# checkpoint stamps both hashes; resume compares the resume
# subset (see the resume check in main()).
RUN_FINGERPRINT = None
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


# The final statuses _screen_one can return (bulk_screen.py): a
# record starts as "searched" and every return path overwrites
# it — "searched" itself must never appear in a summary's
# screen_counts, and neither may any unknown status.
# "unmeasured" (C-1) is a star the per-star watchdog timed out:
# recorded, counted, and conserved like any other outcome — a
# timeout is data, not a dropped star.
SCREEN_STATUSES = frozenset({
    "survivor", "recorded", "demoted", "below_floor",
    "too_few_points", "error", "unmeasured", "search_invalid"})

# Maximum unmeasured fraction of searched stars (F-13): a run
# that timed out on more than 5% of its stars FAILS, like a
# conservation failure. Conservation passes when watchdog
# timeouts land in "unmeasured" — so without this threshold an
# outage looks like "0 survivors" and the run completes green
# on a hollow denominator. 5% is far above the healthy rate
# (a handful of pathological stars per sector) and far below
# any outage.
MAX_UNMEASURED_FRACTION = 0.05


def check_unmeasured_fraction(searched, unmeasured):
    """Pure: (ok, fraction) for the run-level unmeasured
    threshold. A run with no searched stars has fraction 0.0
    (nothing timed out because nothing ran — the conservation
    check, not this one, catches an empty run)."""
    frac = (unmeasured / searched) if searched else 0.0
    return (frac <= MAX_UNMEASURED_FRACTION, frac)


def _measured_of(summary):
    """Stars MEASURED in one slice summary: the recorded
    stars_measured when the screen wrote it (F-13), else
    stars_searched minus unmeasured — so old summaries (and
    the stub's) still yield the honest number."""
    if summary.get("stars_measured") is not None:
        return summary["stars_measured"]
    return (summary.get("stars_searched", 0)
            - summary.get("screen_counts", {}).get("unmeasured", 0))


def check_conservation(window_stars, slice_summaries,
                       merged_survivors, toi_removed, vsx_removed,
                       veto_removed=0):
    """The window must be conserved: every star in the window
    ends up in exactly one bucket, and every screened survivor
    ends up merged or removed with a named reason.

    Pure: slice summaries + merge numbers in, (ok, buckets,
    problems) out. The equations (per slice where the slice is
    the unit, in aggregate for the run):

      1. sum(slice stars_in) == window_stars
         (the slices partition the window)
      2. skipped_known (toi+vsx) + stars_after_filter == stars_in
         (the known filter accounts for every star)
      3. stars_searched + download no_product + download errors
         == stars_after_filter (every kept star was downloaded
         or is named as a download failure)
      4. sum(screen_counts) == stars_searched, and every status
         is a known final status (the screen partitions the
         searched stars; "searched" itself never leaks)
      5. sum(screen_counts["survivor"]) == merged_survivors
         + toi_removed + vsx_removed + sum(zooniverse_known)
         + veto_removed
         (every screened survivor is merged or removed with a
         reason; the veto bucket counts the SECTOR_EPOCH_CLUSTER
         demotions at merge, P3-15 — 0 for pre-v4 profiles,
         whose merge has no veto)

    A missing bucket is a problem, not a skip (fail-closed): a
    summary that cannot be audited is not a summary that
    passed. Returns (ok, buckets, problems); buckets is the
    full partition, recorded on the run summary and manifest.
    """
    problems = []
    buckets = {
        "window": window_stars,
        "slices_in": 0,
        "known_toi": 0, "known_vsx": 0,
        "after_filter": 0,
        "download_no_product": 0, "download_errors": 0,
        "searched": 0,
        "screen_counts": {},
        "survivors_screened": 0,
        "survivors_zooniverse": 0,
        "survivors_toi": toi_removed,
        "survivors_vsx": vsx_removed,
        "survivors_veto": veto_removed,
        "survivors_merged": merged_survivors,
    }

    def _missing(slice_i, key):
        problems.append(
            f"slice {slice_i}: summary lacks {key!r} — cannot "
            f"verify conservation")

    for i, s in enumerate(slice_summaries):
        stars_in = s.get("stars_in")
        if stars_in is None:
            _missing(i, "stars_in")
            continue
        buckets["slices_in"] += stars_in
        skipped = s.get("skipped_known")
        if skipped is None:
            _missing(i, "skipped_known")
            continue
        n_toi = skipped.get("toi", 0)
        n_vsx = skipped.get("vsx", 0)
        buckets["known_toi"] += n_toi
        buckets["known_vsx"] += n_vsx
        after = s.get("stars_after_filter")
        if after is None:
            _missing(i, "stars_after_filter")
            continue
        buckets["after_filter"] += after
        if n_toi + n_vsx + after != stars_in:
            problems.append(
                f"slice {i}: known filter does not conserve: "
                f"{n_toi} TOI + {n_vsx} VSX + {after} kept != "
                f"{stars_in} in")
        dl = s.get("download")
        if dl is None:
            _missing(i, "download")
            continue
        no_prod = dl.get("no_product", 0)
        errors = dl.get("errors", 0)
        buckets["download_no_product"] += no_prod
        buckets["download_errors"] += errors
        searched = s.get("stars_searched")
        if searched is None:
            _missing(i, "stars_searched")
            continue
        buckets["searched"] += searched
        if searched + no_prod + errors != after:
            problems.append(
                f"slice {i}: download does not conserve: "
                f"{searched} searched + {no_prod} no-product + "
                f"{errors} errors != {after} kept")
        counts = s.get("screen_counts")
        if counts is None:
            _missing(i, "screen_counts")
            continue
        for status, n in counts.items():
            if status not in SCREEN_STATUSES:
                problems.append(
                    f"slice {i}: unknown screen status "
                    f"{status!r} ({n} stars) — not a final "
                    f"status")
            buckets["screen_counts"][status] = (
                buckets["screen_counts"].get(status, 0) + n)
        if sum(counts.values()) != searched:
            problems.append(
                f"slice {i}: screen counts do not conserve: "
                f"sum {sum(counts.values())} != {searched} "
                f"searched")
        buckets["survivors_screened"] += counts.get("survivor", 0)
        buckets["survivors_zooniverse"] += len(
            s.get("zooniverse_known_survivors", []))

    if buckets["slices_in"] != window_stars:
        problems.append(
            f"slices do not cover the window: "
            f"{buckets['slices_in']} slice stars != "
            f"{window_stars} window stars")
    accounted = (buckets["survivors_merged"]
                 + buckets["survivors_toi"]
                 + buckets["survivors_vsx"]
                 + buckets["survivors_veto"]
                 + buckets["survivors_zooniverse"])
    if buckets["survivors_screened"] != accounted:
        problems.append(
            f"survivors do not conserve: "
            f"{buckets['survivors_screened']} screened != "
            f"{buckets['survivors_merged']} merged + "
            f"{buckets['survivors_toi']} TOI + "
            f"{buckets['survivors_vsx']} VSX + "
            f"{buckets['survivors_veto']} veto + "
            f"{buckets['survivors_zooniverse']} Zooniverse")
    return (not problems, buckets, problems)


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
    summary file merely exists. Also stamps the code fingerprint
    (A-3): a resume compares it against the current
    result-affecting files and refuses on mismatch unless
    --accept-code-change, which sets mixed_pipeline."""
    global CODE_FINGERPRINT
    if CODE_FINGERPRINT is None:
        CODE_FINGERPRINT = _prov.fingerprint_result_affecting()
    cp = {"run_dir": str(RUN),
          "sector": SECTOR,
          "n_slices": len(completed),
          "code_fingerprint": CODE_FINGERPRINT,
          "mixed_pipeline": MIXED_PIPELINE,
          "completed": {str(k): v for k, v in completed.items()},
          "updated_at": _prov.utc_now_iso()}
    # C-8: the run fingerprint hashes, when this process has them
    # (main() sets RUN_FINGERPRINT from the manifest). A resume
    # compares the resume subset; the full hash is the audit
    # record. Pre-C-8 checkpoints carry neither — the resume
    # check falls back to code_fingerprint for those.
    if RUN_FINGERPRINT is not None:
        cp["run_fingerprint"] = RUN_FINGERPRINT["full"]
        cp["resume_fingerprint"] = RUN_FINGERPRINT["resume"]
    _atomic_write_json(_checkpoint_path(), cp)


def _checkpoint_entry(out, summary):
    """One checkpoint entry: the chunk name, the summary hash,
    AND (C-2) the hashes of the slice's output files. The summary
    hash alone proves the summary; the output hashes prove the
    files the summary describes — a resume must verify the
    outputs before treating a work item as completed, not just
    trust that a summary file exists."""
    return {"chunk": out.name,
            "summary_sha256": _prov.file_sha256(
                out / "summary.json"),
            "survivors_sha256": _prov.file_sha256(
                out / "survivors.jsonl"),
            "hits_sha256": _prov.file_sha256(
                out / "screen_hits.jsonl"),
            "stars_searched": summary.get("stars_searched"),
            "survivors": summary.get("survivors"),
            "completed_at": _prov.utc_now_iso()}


def _checkpoint_entry_status(out, entry):
    """How a checkpoint entry compares with the files on disk.

    Returns one of:
      "ok" — the summary hash matches, and every output hash the
        entry records matches too. The slice is checkpoint-complete.
      "stale" — the summary hash does not match (or the entry
        predates output hashes and the summary disagrees): the
        checkpoint's claim about the slice is outdated. The entry
        is dropped and chunk_ok re-derives the truth from the
        slice's current summary — this is the existing behaviour
        (a stale checkpoint never forces a re-screen on its own).
      "outputs-changed" — the summary hash MATCHES but a recorded
        output hash does not: the slice's outputs were altered
        after the checkpoint was written (tampering or
        corruption), while the summary still describes the old
        outputs. The slice must be re-screened — merging altered
        outputs under an unchanged summary would be silent data
        corruption.

    Entries written before C-2 carry only summary_sha256: with
    no output hashes to check, a matching summary is "ok" (an
    in-flight sector's checkpoints predate this check, and
    re-screening it on upgrade would waste hours of compute for
    a transitional case). New entries always carry all three.
    """
    if _prov.file_sha256(out / "summary.json") != \
            entry.get("summary_sha256"):
        return "stale"
    for key, name in (("survivors_sha256", "survivors.jsonl"),
                      ("hits_sha256", "screen_hits.jsonl")):
        if key in entry and _prov.file_sha256(out / name) != \
                entry[key]:
            return "outputs-changed"
    return "ok"


def _checkpoint_hashes_match(out, entry):
    """True when a checkpoint entry is fully verified ("ok" per
    _checkpoint_entry_status). Kept as the simple predicate for
    callers that only need a boolean."""
    return _checkpoint_entry_status(out, entry) == "ok"


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
    global CODE_FINGERPRINT, MIXED_PIPELINE, RUN_FINGERPRINT
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
    ap.add_argument("--accept-code-change", action="store_true",
                    help="resume across a result-affecting code "
                         "change (A-3): the resumed run is stamped "
                         "mixed_pipeline=true on the checkpoint, "
                         "manifest, summary, and every record it "
                         "writes. Without it, a checkpoint from "
                         "different result-affecting files refuses "
                         "to resume.")
    ap.add_argument("--calibration", default="bulk_v1",
                    help="bulk calibration profile (default: bulk_v1; "
                         "bulk_v2 fixes the MAD-clip defect)")
    ap.add_argument("--allow-v1", action="store_true",
                    help="allow screening a sector outside 96-98 "
                         "under bulk_v1 (known MAD-clip defect — "
                         "prefer --calibration bulk_v2)")
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
    # Validate the calibration name up front (registry-verified
    # load) so a typo fails here, not at slice 0. F-15: the v1
    # sector gate is enforced HERE too, before RUN.mkdir — the
    # B-2 design left it to slice 0, so a refused run still
    # created a run dir, a manifest, and a checkpoint before
    # dying. Each slice still enforces it as well (defence in
    # depth — a slice invoked directly refuses on its own).
    try:
        _load_profile(args.calibration)
    except Exception as exc:
        ap.error(str(exc))
    try:
        # Lazy import: bulk_screen is heavy (lightkurve) and
        # the driver otherwise never imports it.
        from bulk_screen import enforce_v1_gate as _gate
        _gate(args.calibration, SECTOR, args.allow_v1)
    except _CalibrationError as exc:
        ap.error(str(exc))
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
    # A-3: the fingerprint of the result-affecting files THIS
    # process runs. Computed once; the resume check below compares
    # it against the checkpoint's. A docs-only or test-only commit
    # does not move this fingerprint, so a legitimate resume is
    # never refused for one (test_provenance2 proves the property).
    CODE_FINGERPRINT = _prov.fingerprint_result_affecting()
    MANIFEST = _prov.build_manifest(
        RUN_ID, {"bulk": _short_version(args.calibration)},
        sector=SECTOR, product="QLP",
        recipe=RECIPE, recipe_file=RECIPE.get("_file"),
        status="started", code_fingerprint=CODE_FINGERPRINT,
        window_file=_window_path())
    # C-8: the run fingerprint block, for the checkpoint + resume
    # check. The window file may not exist yet (build_slices
    # raises below if it doesn't) — its hash is then None, and
    # the run dies before screening anything.
    RUN_FINGERPRINT = MANIFEST["fingerprint"]
    MIXED_PIPELINE = False
    _prov.write_manifest(RUN, MANIFEST)
    log(f"run_id: {RUN_ID} (recipe hash {R_HASH[:12]}…, "
        f"calibration {args.calibration})")
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
    rescreen = set()  # C-2: slices whose outputs changed after
    # checkpointing (summary matches, output hash does not) —
    # chunk_ok alone must not skip them.
    prev = read_checkpoint()
    if prev and (prev.get("completed") or {}):
        # A-3: refuse to resume work produced by different
        # result-affecting files — a mid-screen code fix would
        # silently mix two pipelines in one sector. The comparison
        # is the fingerprint, NOT the git SHA: a docs-only commit
        # between checkpoint and resume does not refuse. A
        # fingerprint-less checkpoint (pre-A-3) is fail-closed:
        # it cannot prove what code produced it.
        # C-8: compare the resume fingerprint (code + calibration
        # + recipe + window + env + input IDs) when the checkpoint
        # carries one; fall back to the code fingerprint for
        # pre-C-8 checkpoints; fail closed when neither exists
        # (pre-A-3). The comparison excludes the git SHA and the
        # dirty flag (see provenance.resume_fingerprint) — a
        # docs-only commit or a stray untracked file must not
        # refuse a legitimate resume.
        prev_resume = prev.get("resume_fingerprint")
        if prev_resume is not None:
            cur_resume = RUN_FINGERPRINT["resume"]
            if prev_resume != cur_resume:
                reason = ("resume fingerprint mismatch: checkpoint "
                          f"{prev_resume[:12]}… vs current "
                          f"{cur_resume[:12]}… (code, calibration, "
                          f"recipe, window, environment, or inputs "
                          f"changed)")
            else:
                reason = None
        else:
            prev_fp = prev.get("code_fingerprint")
            if prev_fp is None:
                reason = ("checkpoint has no code fingerprint "
                          "(pre-A-3 checkpoint)")
            elif prev_fp != CODE_FINGERPRINT:
                reason = ("code fingerprint mismatch: checkpoint "
                          f"{prev_fp[:12]}… vs current "
                          f"{CODE_FINGERPRINT[:12]}…")
            else:
                reason = None
        if reason is not None:
            if not args.accept_code_change:
                log(f"REFUSING TO RESUME: {reason}. The completed "
                    f"slices were screened under a different run "
                    f"fingerprint; resuming would mix two "
                    f"pipelines in one sector. Re-run from "
                    f"scratch (delete {RUN}) or pass "
                    f"--accept-code-change to resume with "
                    f"mixed_pipeline=true stamped on the run.")
                return 1
            MIXED_PIPELINE = True
            log(f"WARNING: resuming across a code change "
                f"(--accept-code-change): {reason}. This run is "
                f"stamped mixed_pipeline=true.")
        else:
            # Same code — but a previous resume may already have
            # mixed the run; the flag persists.
            MIXED_PIPELINE = bool(prev.get("mixed_pipeline"))
        for k, v in (prev.get("completed") or {}).items():
            i = int(k)
            out = RUN / f"chunk_{i:02d}"
            status = _checkpoint_entry_status(out, v)
            if status == "ok" and chunk_ok(out):
                completed[i] = v
            elif status == "outputs-changed" and chunk_ok(out):
                # The summary still matches but an output file
                # changed after checkpointing — the slice's
                # outputs are untrustworthy and chunk_ok must not
                # skip them. Re-screen from scratch.
                rescreen.add(i)
                log(f"slice {i}: checkpoint entry INVALID — "
                    f"summary matches but an output file changed "
                    f"after checkpointing; re-screening")
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
    # The mixed flag is final now (fresh run: False; clean resume:
    # inherited; accepted code change: True) — stamp the manifest
    # and rewrite it, so even a killed run's manifest is honest.
    MANIFEST["mixed_pipeline"] = MIXED_PIPELINE
    _prov.write_manifest(RUN, MANIFEST)
    t_start = time.time()
    for i, sl in enumerate(slices):
        out = RUN / f"chunk_{i:02d}"
        if chunk_ok(out) and i not in rescreen:
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
               "--calibration", args.calibration,
               "--dl-workers", str(recipe["dl_workers"])]
        if args.allow_v1:
            cmd += ["--allow-v1"]
        if MIXED_PIPELINE:
            # A-3: every record the resumed run writes carries the
            # stamp (bulk_screen --mixed-pipeline).
            cmd += ["--mixed-pipeline"]
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
            f"measured {_measured_of(s)}, "
            f"survivors {s.get('survivors')}, "
            f"tiers {s.get('survivor_tiers')}")
    # ---- merge ------------------------------------------------------------
    log("all slices done — merging")
    import bulk_screen as bs
    survivors, hits = [], []
    slice_summaries = []
    agg = {"stars_searched": 0, "stars_measured": 0,
           "hits_recorded": 0,
           "zooniverse_known": 0, "screen_counts": {}}
    for i in range(len(slices)):
        out = RUN / f"chunk_{i:02d}"
        s = json.loads((out / "summary.json").read_text())
        slice_summaries.append(s)
        agg["stars_searched"] += s.get("stars_searched", 0)
        agg["stars_measured"] += _measured_of(s)
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
    # P3-15 (bulk_v4): SECTOR_EPOCH_CLUSTER veto — merge-only
    # (clusters span slices, so a per-slice veto would
    # under-demote), BEFORE the TOI/VSX joins (the P3-11
    # replay clustered the full survivor set including TOIs).
    # Gated on the run's calibration: the veto runs only when
    # the profile enables it. set_calibration here is
    # merge-local — the slice screens ran as separate processes
    # with --calibration, and the merge only uses bs for the
    # TOI join (calibration-independent) and the veto.
    bs.set_calibration(args.calibration)
    veto_summary = None
    n_veto = 0
    if bs.EPOCH_CLUSTER_VETO_ENABLED:
        survivors, veto_summary = bs.apply_epoch_cluster_veto(
            survivors, hits)
        n_veto = (veto_summary["demoted_tier_b"]
                  + veto_summary.get("demoted_tier_a", 0))
        log(f"epoch-cluster veto: "
            f"{veto_summary['demoted_tier_b']} tier-B demoted, "
            f"{veto_summary.get('demoted_tier_a', 0)} tier-A demoted, "
            f"{veto_summary['flagged_tier_a']} tier-A flagged "
            f"({veto_summary['n_clusters']} clusters, sizes "
            f"{veto_summary['cluster_sizes']})")
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
    # A-7: the window must be conserved. A failure here is a
    # data-integrity failure — stars lost between the window and
    # the merge, or survivors unaccounted for — and the run
    # FAILS (exit 1) with the buckets recorded, so the loss is
    # diagnosable instead of silent. The merged outputs are
    # still written (they exist for diagnosis), but the manifest
    # status is "failed" and no downstream step should consume
    # them as a completed run.
    cons_ok, cons_buckets, cons_problems = check_conservation(
        N_STARS, slice_summaries, len(survivors), n_toi, n_vsx,
        veto_removed=n_veto)
    conservation = {"ok": cons_ok, "buckets": cons_buckets,
                    "problems": cons_problems}
    if not cons_ok:
        for p in cons_problems:
            log(f"CONSERVATION FAILED: {p}")
    # F-13: the unmeasured-fraction threshold — conservation
    # passes when timeouts land in "unmeasured", so a run that
    # timed out on most of its stars would otherwise complete
    # green on a hollow denominator. Like conservation, a
    # failure here fails the run (exit 1) with the numbers
    # recorded on the summary and manifest.
    unmeasured_n = agg["screen_counts"].get("unmeasured", 0)
    unmeasured_ok, unmeasured_frac = check_unmeasured_fraction(
        agg["stars_searched"], unmeasured_n)
    unmeasured = {"ok": unmeasured_ok, "count": unmeasured_n,
                  "fraction": unmeasured_frac,
                  "threshold": MAX_UNMEASURED_FRACTION}
    if not unmeasured_ok:
        log(f"UNMEASURED FRACTION FAILED: {unmeasured_n}/"
            f"{agg['stars_searched']} stars unmeasured "
            f"({unmeasured_frac:.1%} > "
            f"{MAX_UNMEASURED_FRACTION:.0%} threshold) — the run "
            f"timed out systematically, not on a few stars")
    summary = {
        "tool": "bulk_screen v1.2 chunked driver (run_chunked)",
        "sector": SECTOR, "stars_in": N_STARS,
        # P4-2: the merged summary stamps the run's calibration
        # from the manifest — the pre-P4-2 code hardcoded
        # {"bulk": "v1"} here, so every chunked run's summary
        # mis-stamped its calibration (the manifest was right;
        # P3-21's summary shows the v1 stamp on a v4 run).
        "provenance": _prov.provenance_header(
            RUN_ID, MANIFEST["calibration"]["versions"],
            recipe_hash=R_HASH,
            sha=MANIFEST["pipeline"]["git_sha"],
            timestamp_utc=MANIFEST["execution"]["started_at"]),
        "recipe": {"file": RECIPE["_file"],
                   "resolved_hash": R_HASH,
                   "params": {k: v for k, v in RECIPE.items()
                              if not k.startswith("_")}},
        "known_filter": {"mode": "survivor-stage (chunked resilience)",
                         "toi_removed": n_toi, "vsx_removed": n_vsx,
                         "zooniverse_removed": agg["zooniverse_known"]},
        # P3-15: the veto summary (None when the profile has no
        # veto). The demoted rows are NOT deleted — they carry
        # disposition DEMOTED_SECTOR_EPOCH_CLUSTER in the merged
        # screen_hits.jsonl, and the TWO-COMBINED failures carry
        # gate_reason FAILED_TWO_COMBINED there; together they
        # are the manual-review ("unsure") queue.
        "epoch_cluster_veto": veto_summary,
        "stars_searched": agg["stars_searched"],
        "stars_measured": agg["stars_measured"],
        "hits_recorded": agg["hits_recorded"],
        "screen_counts": agg["screen_counts"],
        "conservation": conservation,
        "unmeasured": unmeasured,
        "mixed_pipeline": MIXED_PIPELINE,
        "survivors": len(survivors), "survivor_tiers": tiers,
        "survivor_tics": [r["tic"] for r in survivors],
        "wall_seconds_chunked_driver": round(time.time() - t_start),
    }
    _atomic_write_json(RUN / "summary.json", summary)
    MANIFEST["execution"]["status"] = (
        "completed" if (cons_ok and unmeasured_ok) else "failed")
    MANIFEST["execution"]["wall_seconds"] = round(
        time.time() - t_start)
    MANIFEST["counts"] = {
        "stars_searched": agg["stars_searched"],
        "stars_measured": agg["stars_measured"],
        "hits_recorded": agg["hits_recorded"],
        "survivors": len(survivors),
        "screen_counts": agg["screen_counts"],
        "conservation": conservation,
        "unmeasured": unmeasured,
    }
    _prov.write_manifest(RUN, MANIFEST)
    if not cons_ok:
        log(f"FAILED: conservation check failed "
            f"({len(cons_problems)} problems) — see summary.json")
        return 1
    if not unmeasured_ok:
        log(f"FAILED: unmeasured fraction {unmeasured_frac:.1%} "
            f"exceeds the {MAX_UNMEASURED_FRACTION:.0%} threshold "
            f"— see summary.json")
        return 1
    log(f"DONE: {len(survivors)} survivors {tiers} from "
        f"{agg['stars_measured']} measured "
        f"({agg['stars_searched']} searched)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
