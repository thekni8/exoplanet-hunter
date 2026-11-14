"""Provenance headers and run manifests (Phase 1.1, item 1;
layer 2 in Phase 1.2, item A-2).

Every output record the pipeline writes — bulk-screen survivors and
gauntlet verdicts — carries a provenance header so any result can be
traced back to the exact code, calibration, recipe, and run that
produced it:

    schema_version      provenance schema version ("1.2")
    run_id              unique id for the run, e.g.
                        bulk-20261114T063000Z-a1b2
    pipeline_git_sha    short git SHA of the code that ran
                        ("unknown" when git is unavailable — never
                        a crash, but never a silent lie either)
    working_tree_clean  whether the working tree was clean at run
                        start (None when git is unavailable). A git
                        SHA with no dirty flag misleads whenever
                        uncommitted code runs.
    calibration_version per-subsystem map of versioned calibration
                        profiles, e.g. {"bulk": "v1"} (1.2;
                        a plain string is a legacy 1.1 record and
                        still validates)
    calibration_sha256  sha256 over the calibration CONTENT hashes
                        (not just the labels) — the profiles' bytes
                        are part of the computation's identity
    timestamp_utc       run start, ISO 8601 UTC (one timestamp per
                        run, so records from one run sort together
                        and the determinism test can fix it)
    recipe_hash         sha256 of the RESOLVED recipe (after CLI
                        overrides), when the run had a recipe —
                        the recipe file alone no longer describes
                        what ran once CLI > recipe applies

Layer 2 (A-2) also identifies the INPUTS, not just the code:
input_identity records the MAST product IDs, sectors, author,
cadence, input file hash, selected-product manifest hash, and a
hash of the arrays entering BLS — so a result can be traced to
the exact data it was computed from. The fingerprint helper
(fingerprint_result_affecting) hashes the result-affecting files
(pipeline code + calibration + schemas) for resume checks (A-3)
and work-item identity (C-2).

The header is stamped at write time, never reconstructed
afterwards: retrofitting provenance onto existing records is
impossible (the vote's unanimous #1 gap — "you'd have to re-run").

A run manifest (manifest.json, one per run directory) carries the
same information at run level, plus the environment (Python version,
requirements hash) and the recipe file hash, so a run directory is
self-describing years later.
"""
import hashlib
import json
import secrets
import subprocess
import sys
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

from atomic_io import atomic_write_json

SCHEMA_VERSION = "1.2"
PIPELINE_NAME = "exoplanet-hunter"


def repo_root():
    return Path(__file__).resolve().parent


@lru_cache(maxsize=1)
def git_sha(short=True):
    """Short git SHA of the working tree, or "unknown".

    Never raises: in a source export without .git (or with git
    missing), "unknown" is the honest answer — a record stamped
    "unknown" says plainly that its code version is untraced.
    """
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short" if short else "HEAD", "HEAD"],
            cwd=repo_root(), capture_output=True, text=True,
            timeout=10)
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    sha = out.stdout.strip()
    return sha if sha and out.returncode == 0 else "unknown"


@lru_cache(maxsize=8)
def working_tree_clean(root=None):
    """True when `git status --porcelain` reports a clean tree,
    False when there are uncommitted changes, None when git is
    unavailable (source export, git missing). Never raises.
    Cached: the tree does not change mid-run. `root` defaults to
    this repo; tests pass a temp repo."""
    root = Path(root) if root is not None else repo_root()
    try:
        out = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=root, capture_output=True, text=True,
            timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    return out.stdout.strip() == ""


def git_dirty(root=None):
    """The complement of working_tree_clean: True when the tree
    has uncommitted changes, False when clean, None when git is
    unavailable. (Claude, Phase 1.1 vote: a git SHA with no dirty
    flag misleads whenever an agent runs uncommitted code.)"""
    clean = working_tree_clean(root)
    return None if clean is None else not clean


def utc_now_iso():
    """Current UTC time, ISO 8601 with seconds, e.g.
    2026-11-14T06:30:00+00:00."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_run_id(kind="bulk"):
    """A unique run id: kind + UTC timestamp + 4 random hex chars."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{kind}-{stamp}-{secrets.token_hex(2)}"


def canonical_json(obj):
    """Canonical JSON for hashing: sorted keys, tight separators,
    non-JSON values stringified (so a recipe with a Path still
    hashes deterministically)."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      default=str)


def recipe_hash(resolved_recipe):
    """sha256 of the RESOLVED recipe (after CLI overrides).

    Keys starting with "_" are internal metadata (e.g. "_file",
    the recipe's path on this machine) and are excluded — the hash
    must describe what ran, not where the file lived.
    """
    public = {k: v for k, v in resolved_recipe.items()
              if not k.startswith("_")}
    return hashlib.sha256(
        canonical_json(public).encode("utf-8")).hexdigest()


def file_sha256(path):
    """sha256 of a file's bytes, or None if the file is missing."""
    path = Path(path)
    if not path.exists():
        return None
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# Result-affecting files (Phase 1.2, item A-2): the files whose
# bytes can change a run's output. Pipeline code (root + gauntlet/
# + bulk/ .py), calibration profiles, and schemas. NOT included:
# tests (they check results, they don't make them), docs, recipes
# (run config — hashed separately as recipe_hash), scripts (dev
# tools), archive/ (old code, never imported), run data, CI
# config. A docs-only commit must NOT change this fingerprint —
# that is the property the resume check (A-3) depends on.
_RESULT_AFFECTING_GLOBS = ("*.py", "gauntlet/*.py", "bulk/*.py",
                           "calibration/*.yaml", "schema/*.json")


def fingerprint_result_affecting(root=None):
    """sha256 over the result-affecting files: the canonical JSON
    of {relative path: file sha256}, sorted. Two checkouts with
    equal fingerprints run identical pipeline code on identical
    calibration and schemas. `root` defaults to this repo; tests
    pass a temp tree."""
    root = Path(root) if root is not None else repo_root()
    files = {}
    for pattern in _RESULT_AFFECTING_GLOBS:
        for path in sorted(root.glob(pattern)):
            if path.is_file():
                files[path.relative_to(root).as_posix()] = \
                    file_sha256(path)
    return hashlib.sha256(
        canonical_json(files).encode("utf-8")).hexdigest()


def work_item_id(tic, sector, code_fingerprint, calibration_hash,
                 recipe_hash=None):
    """Deterministic identity of one unit of screen work (C-2):
    sha256 over {tic, sector, code fingerprint, calibration hash,
    recipe hash}. Two runs with equal work-item ids screened the
    same star with the same code, calibration and recipe — their
    outputs must be identical, so a resume can skip the item and
    a re-run can verify it without re-screening.

    Deliberately NO input_hash in the identity: the id must be
    computable BEFORE any download, so resume can skip finished
    items cheaply. The input hash is verified afterwards — the
    record's input_identity carries it (bls_input_hash,
    input_file_sha256) and the checkpoint verifies the output
    hashes (run_chunked._checkpoint_hashes_match). An id that
    needed the input would force a download just to learn what
    work was already done.
    """
    return hashlib.sha256(
        canonical_json({
            "tic": str(tic),
            "sector": int(sector),
            "code_fingerprint": code_fingerprint,
            "calibration_hash": calibration_hash,
            "recipe_hash": recipe_hash,
        }).encode("utf-8")).hexdigest()


def calibration_content_hash(calibration_versions):
    """sha256 over the calibration CONTENT: the canonical JSON of
    {subsystem: profile-file sha256} for the given versions map
    (e.g. {"bulk": "v1"} — bare versions; the profile name is
    resolved as "<subsystem>_<version>"). A label alone ("v1")
    does not identify the bytes; this hash does. Raises
    CalibrationError when a profile file is missing — a run that
    cannot read its calibration is broken, not unhashable."""
    import calibration as _cal
    hashes = {sub: _cal.profile_sha256(
                  _cal.profile_name(sub, ver))
              for sub, ver in sorted(calibration_versions.items())}
    return hashlib.sha256(
        canonical_json(hashes).encode("utf-8")).hexdigest()


# Run fingerprint (Phase 1.2, item C-8): one hash identifying a
# run's full computation — code SHA + dirty flag + calibration
# hash + resolved recipe + window-file hash + env hash + input
# IDs. Two runs with equal FULL fingerprints ran identical code
# on identical inputs in identical environments; two runs with
# equal RESUME fingerprints produced comparable results. The
# resume fingerprint EXCLUDES the git SHA (a docs-only commit
# changes the SHA but not results — the A-3 problem) and the
# dirty flag (a stray untracked file would refuse a legitimate
# resume). The checkpoint stores both; resume compares the resume
# subset, falling back to code_fingerprint for pre-C-8
# checkpoints.
RESUME_FINGERPRINT_KEYS = ("code_fingerprint", "calibration_hash",
                           "recipe_hash", "window_sha256",
                           "env_hash", "input_ids")


def env_hash(root=None):
    """sha256 over the execution environment: the Python version
    + the requirements.lock hash. The lock (not requirements.txt)
    pins the transitive set — two runs with equal env hashes ran
    the same interpreter on the same installed packages."""
    root = Path(root) if root is not None else repo_root()
    return hashlib.sha256(
        canonical_json({
            "python": sys.version.split()[0],
            "requirements_lock_sha256": file_sha256(
                root / "requirements.lock"),
        }).encode("utf-8")).hexdigest()


def run_fingerprint_components(root=None, calibration_versions=None,
                               recipe=None, recipe_hash_value=None,
                               window_file=None, input_ids=None,
                               code_fingerprint=None,
                               git_sha_value=None):
    """Collect the run-fingerprint components dict. Callers pass
    what they know; the rest is measured here (code fingerprint,
    git SHA, dirty flag, env hash). `recipe` is the resolved
    recipe dict (hashed here); `recipe_hash_value` overrides it
    when the caller already computed the hash (run_chunked).
    Missing pieces are None — a null component is explicit, not a
    silent omission, and two runs with the same nulls are
    comparable."""
    root = Path(root) if root is not None else repo_root()
    if code_fingerprint is None:
        code_fingerprint = fingerprint_result_affecting(root)
    if recipe_hash_value is None and recipe is not None:
        recipe_hash_value = recipe_hash(recipe)
    cal_hash = None
    if calibration_versions is not None:
        try:
            cal_hash = calibration_content_hash(calibration_versions)
        except Exception:
            cal_hash = None
    return {
        "code_fingerprint": code_fingerprint,
        "calibration_hash": cal_hash,
        "recipe_hash": recipe_hash_value,
        "window_sha256": (file_sha256(window_file)
                          if window_file is not None else None),
        "env_hash": env_hash(root),
        "input_ids": (sorted(str(i) for i in input_ids)
                      if input_ids is not None else None),
        "git_sha": (git_sha_value if git_sha_value is not None
                    else git_sha()),
        "working_tree_clean": working_tree_clean(root),
    }


def run_fingerprint(components):
    """The full run fingerprint: sha256 over the canonical JSON
    of ALL components (code SHA + dirty flag included)."""
    return hashlib.sha256(
        canonical_json(components).encode("utf-8")).hexdigest()


def resume_fingerprint(components):
    """The comparable subset: everything that affects results,
    excluding the git SHA and the dirty flag. A docs-only commit
    or a stray untracked file must not refuse a legitimate
    resume — those change the full fingerprint but not this one."""
    subset = {k: components.get(k) for k in RESUME_FINGERPRINT_KEYS}
    return hashlib.sha256(
        canonical_json(subset).encode("utf-8")).hexdigest()


def fingerprint_block(**kwargs):
    """The manifest/checkpoint fingerprint block: the full +
    resume hashes + the components, so a reader can verify either
    hash without re-running anything. Keyword arguments are
    run_fingerprint_components'."""
    components = run_fingerprint_components(**kwargs)
    return {
        "full": run_fingerprint(components),
        "resume": resume_fingerprint(components),
        "components": components,
    }


def calibration_hashes(calibration_versions):
    """The per-subsystem {subsystem: profile-file sha256} map
    behind calibration_content_hash — for the manifest, where
    the breakdown is as useful as the combined hash."""
    import calibration as _cal
    return {sub: _cal.profile_sha256(_cal.profile_name(sub, ver))
            for sub, ver in sorted(calibration_versions.items())}


def bls_input_hash(t, f):
    """sha256 of the arrays entering BLS: the exact data the
    search saw, after quality masking, clipping and flattening.
    Two runs with equal BLS input hashes searched identical
    arrays — the fixture-vs-live question (C-4) is answered by
    comparing this hash, not by trusting that the paths match.
    Shapes are hashed with the bytes so a reshape cannot alias."""
    import numpy as np
    t = np.asarray(t, dtype=np.float64)
    f = np.asarray(f, dtype=np.float64)
    h = hashlib.sha256()
    h.update(str(t.shape).encode("utf-8"))
    h.update(t.tobytes())
    h.update(str(f.shape).encode("utf-8"))
    h.update(f.tobytes())
    return h.hexdigest()


def input_identity(product_ids=None, sectors=None, author=None,
                   cadence_s=None, input_file_sha256=None,
                   input_manifest_sha256=None, bls_input_hash=None,
                   fixture=False):
    """The input-identity dict for a record or manifest: which
    MAST products, which sectors, which author, which cadence,
    the input file's hash, the selected-product manifest's hash,
    and the hash of the arrays entering BLS. None-valued fields
    are omitted; `fixture` is included only when True (offline
    test data, not MAST products)."""
    ident = {}
    if product_ids is not None:
        ident["product_ids"] = list(product_ids)
    if sectors is not None:
        ident["sectors"] = list(sectors)
    if author is not None:
        ident["author"] = author
    if cadence_s is not None:
        ident["cadence_s"] = cadence_s
    if input_file_sha256 is not None:
        ident["input_file_sha256"] = input_file_sha256
    if input_manifest_sha256 is not None:
        ident["input_manifest_sha256"] = input_manifest_sha256
    if bls_input_hash is not None:
        ident["bls_input_hash"] = bls_input_hash
    if fixture:
        ident["fixture"] = True
    return ident


def provenance_header(run_id, calibration_versions, recipe_hash=None,
                      sha=None, timestamp_utc=None,
                      mixed_pipeline=False):
    """The header dict stamped onto every output record.

    `calibration_versions` is a per-subsystem map, e.g.
    {"bulk": "v1"} (1.2; a plain string is a legacy 1.1
    record and still validates, but new code stamps the map).
    `sha` and `timestamp_utc` default to the live values; tests
    pass explicit ones for determinism. `recipe_hash` is omitted
    (not null) when the run had no recipe — standalone
    bulk_screen runs and deep-pipeline runs carry no recipe
    hash. `working_tree_clean` and `calibration_sha256` are
    stamped whenever they can be computed; a missing profile
    file omits the calibration hash rather than crashing the
    writer (the run already failed at profile load if its
    calibration is unreadable). `mixed_pipeline` is stamped
    only when True (A-3): the run resumed across a
    result-affecting code change under --accept-code-change,
    so its records come from two pipelines.
    """
    header = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "pipeline_git_sha": sha if sha is not None else git_sha(),
        "working_tree_clean": working_tree_clean(),
        "calibration_version": dict(calibration_versions),
        "timestamp_utc": (timestamp_utc if timestamp_utc is not None
                          else utc_now_iso()),
    }
    try:
        header["calibration_sha256"] = calibration_content_hash(
            calibration_versions)
    except Exception:
        pass
    if recipe_hash is not None:
        header["recipe_hash"] = recipe_hash
    if mixed_pipeline:
        header["mixed_pipeline"] = True
    return header


def build_manifest(run_id, calibration_versions, sector=None,
                   product=None, recipe=None, recipe_file=None,
                   sha=None, timestamp_utc=None, status="started",
                   input_identity=None, code_fingerprint=None,
                   window_file=None, input_ids=None):
    """The run-level manifest dict. `recipe` is the resolved recipe
    dict (or None); `recipe_file` its path. Callers add run-specific
    keys (counts, wall time) before writing, or write a second
    manifest with status="completed" at the end of the run.

    `calibration_versions` is the per-subsystem map (1.2); the
    manifest records it three ways — the labels (`versions`), the
    per-subsystem content hashes (`hashes`), and the combined
    content hash (`sha256`) — so a manifest can be checked
    against a registry without re-running anything. `execution`
    records `working_tree_clean` (a git SHA with no dirty flag
    misleads whenever uncommitted code runs), and `data` records
    `input_identity` when the caller can supply it.

    `fingerprint` (C-8) is the run fingerprint block: the full +
    resume hashes + the components (code fingerprint, calibration
    hash, recipe hash, window-file hash, env hash, input IDs,
    git SHA, dirty flag). `code_fingerprint` / `window_file` /
    `input_ids` are caller-supplied when the caller knows them;
    the rest is measured here.
    """
    root = repo_root()
    try:
        cal_hashes = calibration_hashes(calibration_versions)
        cal_sha = calibration_content_hash(calibration_versions)
    except Exception:
        cal_hashes, cal_sha = {}, None
    manifest = {
        "run_id": run_id,
        "schema_version": SCHEMA_VERSION,
        "pipeline": {
            "name": PIPELINE_NAME,
            "git_sha": sha if sha is not None else git_sha(),
        },
        "environment": {
            "python": sys.version.split()[0],
            "requirements_sha256": file_sha256(
                root / "requirements.txt"),
            # C-9: this used to read requirements-lock.txt,
            # which does not exist — the hash was always None.
            # The lockfile is requirements.lock.
            "requirements_lock_sha256": file_sha256(
                root / "requirements.lock"),
        },
        "calibration": {
            "versions": dict(calibration_versions),
            "hashes": cal_hashes,
            "sha256": cal_sha,
        },
        "execution": {
            "started_at": (timestamp_utc if timestamp_utc is not None
                           else utc_now_iso()),
            "status": status,
            "working_tree_clean": working_tree_clean(),
        },
    }
    if sector is not None:
        manifest["data"] = {"sector": sector, "product": product}
        if input_identity is not None:
            manifest["data"]["input_identity"] = input_identity
    if recipe is not None:
        manifest["recipe"] = {
            "file": str(recipe_file) if recipe_file else None,
            "file_sha256": (file_sha256(recipe_file)
                            if recipe_file else None),
            "resolved_hash": recipe_hash(recipe),
            "resolved": {k: v for k, v in recipe.items()
                         if not k.startswith("_")},
        }
    # C-8: the run fingerprint — full + resume hashes + the
    # components, so the run's identity is verifiable from the
    # manifest alone. The git SHA here is the manifest's own
    # (caller-supplied or measured above), so the fingerprint and
    # the pipeline block never disagree about it.
    manifest["fingerprint"] = fingerprint_block(
        root=root, calibration_versions=calibration_versions,
        recipe=recipe, window_file=window_file,
        input_ids=input_ids, code_fingerprint=code_fingerprint,
        git_sha_value=manifest["pipeline"]["git_sha"])
    return manifest


def write_manifest(out_dir, manifest):
    """Atomically write manifest.json into `out_dir`. The manifest
    is the run directory's self-description — a partial manifest
    would be worse than none, so this is always an atomic write."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    return atomic_write_json(out_dir / "manifest.json", manifest)
