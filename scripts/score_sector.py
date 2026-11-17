#!/usr/bin/env python
"""Score one sector's survivors with the frozen 3A ranker (Phase 3, P3-21).

The frozen ranker is the model trained by scripts/rank_experiment.py
at the Phase 3 freeze (commit bc60dad): HistGB 3-class, Stage 1 ten
1D features, TIC-grouped train split, seed 20261116, balanced class
weights. This script reproduces that model EXACTLY by re-running the
same training procedure — it imports rank_experiment.py's paths,
split and class index, so it cannot drift from the frozen procedure
— and scores one sector's survivors file with it, once.

This script changes NO ranker code: it only applies the frozen model
(bulk/ranker.py + bulk/ranker_dataset.py, untouched since the freeze).
The S97 validation pass (P3-21) runs it exactly once, on the
bulk_v4 S97 rescore survivors, after they are copied back to the VM.

S98 LOCK (TB-8): the script refuses to score any file whose name or
records name sector 98. S98 stays locked for the final blind
evaluation — do not score it, do not peek at it in Phase 3.

Outputs (in --out-dir):
  ranked_survivors.jsonl — the input rows in ranker order (a
    PERMUTATION of the input — same rows, same count), each a copy
    with ranker_rank (1-based), planet_proba and sde_rank added.
    The input file is never modified.
  score_report.json — machine-readable report: config hashes
    (git SHA, bulk_v4 registry sha256), dataset counts, top-decile
    cutoff, TOI ranks (when --toi-csv is given), the permutation
    check, and whether --limit was used.
  score_report.md — the same, human-readable.

Usage (VM, after the S97 rescore outputs are copied back):
  .venv/bin/python scripts/score_sector.py \
    --survivors <rescore_v4_s0097.jsonl> \
    --out-dir <p3-21-results> --toi-csv <toi_tics.csv>

--limit N scores only the first N rows (smoke testing only — a
limited run is recorded as limited in the report and is NOT the
validation pass).
"""
import argparse
import importlib.util
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

from bulk import ranker, ranker_dataset as rds  # noqa: E402


def _load_rank_experiment():
    """Import scripts/rank_experiment.py as a module (it has a
    __main__ guard, so importing it runs nothing). Reusing its
    DEFAULT_PATHS / CLASS_INDEX / _split_arrays is what makes
    the reproduced model the FROZEN model — same data, same
    split, same seed, same class weights."""
    here = Path(__file__).resolve().parent
    spec = importlib.util.spec_from_file_location(
        "rank_experiment", here / "rank_experiment.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def train_frozen_model(seed=20261116):
    """Reproduce the frozen ranker: the exact P3-18 training
    invocation (dataset build + TIC-grouped train split +
    balanced class weights + train_ranker default random_state).
    Returns (model, dataset). Deterministic on the same code +
    data + seed."""
    rx = _load_rank_experiment()
    ds = rds.build_dataset(rx.DEFAULT_PATHS, seed=seed)
    rows = ds["rows"]
    train_rows, X_train, y_train = rx._split_arrays(rows, "train")
    sample_weight = np.array(
        [ds["class_weights"][r["label"]] for r in train_rows])
    model = ranker.train_ranker(X_train, y_train,
                                sample_weight=sample_weight)
    return model, ds


def guard_sector(path, records):
    """Enforce the S98 lock (TB-8) + the one-sector rule.

    Raises SystemExit when the survivors file names sector 98
    (by filename or by any record's sector field), or when the
    records span more than one sector (the validation is
    per-sector). Returns the sector int otherwise."""
    name = Path(path).name.lower()
    if "s0098" in name or "sector-98" in name or "sector_98" in name:
        raise SystemExit(
            "[score_sector] ABORT: S98 is LOCKED for the final blind "
            "evaluation (TB-8) — refusing to score a sector-98 file.")
    sectors = {r.get("sector") for r in records}
    if 98 in sectors:
        raise SystemExit(
            "[score_sector] ABORT: a record names sector 98 — S98 is "
            "LOCKED (TB-8). Refusing to score.")
    if len(sectors) != 1:
        raise SystemExit(
            "[score_sector] ABORT: records span sectors "
            f"{sorted(s for s in sectors if s is not None)} — the "
            "validation scores one sector at a time.")
    return sectors.pop()


def score_records(records, model):
    """Score `records` with `model`. Returns a list of COPIES of
    the input rows in ranker order (a permutation — same rows,
    same count), each with ranker_rank (1-based), planet_proba
    and sde_rank added. Input rows are not mutated."""
    if not records:
        return []
    X = ranker.features_to_array(records)
    scores = ranker.planet_proba(model, X)
    sde = ranker.sde_scores(records)
    ranks = ranker.ranks_of(scores, [True] * len(records))
    sde_ranks = ranker.ranks_of(sde, [True] * len(records))
    order = np.argsort(-np.asarray(scores), kind="stable")
    out = []
    for i in order:
        row = dict(records[int(i)])
        row["ranker_rank"] = int(ranks[int(i)])
        row["planet_proba"] = float(scores[int(i)])
        row["sde_rank"] = int(sde_ranks[int(i)])
        out.append(row)
    return out


def _load_toi_csv(path):
    """TOI TIC ids from a CSV (first column; tolerates a header
    row and trailing '.0'). Returns a set of TIC strings."""
    tics = set()
    with open(path) as fh:
        for line in fh:
            v = line.split(",")[0].strip().strip('"')
            if v.endswith(".0"):
                v = v[:-2]
            if v and v.lower() not in ("tid", "tic"):
                tics.add(v)
    return tics


def _git_sha():
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(__file__).resolve().parent.parent,
            text=True, timeout=30).strip()
    except Exception:
        return "unknown"


def _bulk_v4_sha():
    """The bulk_v4 sha256 from the calibration registry (the
    profile hash the loader enforces)."""
    root = Path(__file__).resolve().parent.parent
    try:
        reg = json.loads((root / "calibration" / "registry.json")
                         .read_text())
        for entry in reg.get("entries", []):
            if entry.get("calibration_id") == "bulk_v4":
                return entry.get("sha256", "unknown")
    except Exception:
        pass
    return "unknown"


def build_report(scored, records, sector, seed, git_sha, bulk_v4_sha,
                 dataset, toi_tics=None, limited=False, limit=None):
    """The machine-readable validation report for one scored
    sector. `scored` is score_records' output; `records` the
    input rows (for the permutation check)."""
    n = len(scored)
    decile = max(1, int(round(n * 0.10))) if n else 0
    rank_by_tic = {str(r["tic"]): r["ranker_rank"] for r in scored}
    report = {
        "tool": "scripts/score_sector.py (P3-21 frozen-ranker scoring)",
        "sector": sector,
        "scored_at_utc": datetime.now(timezone.utc).isoformat(),
        "seed": seed,
        "git_sha": git_sha,
        "bulk_v4_registry_sha256": bulk_v4_sha,
        "dataset": {
            "rows": len(dataset["rows"]),
            "train_rows": sum(1 for r in dataset["rows"]
                              if r["split"] == "train"),
            "test_rows": sum(1 for r in dataset["rows"]
                             if r["split"] == "test"),
            "class_weights": dataset["class_weights"],
        },
        "n_survivors": n,
        "top_decile_cutoff_rank": decile,
        "limited": limited,
        "limit": limit,
        "permutation_check": (
            sorted(str(r["tic"]) for r in records)
            == sorted(str(r["tic"]) for r in scored)
            and len(records) == len(scored)),
        "ranker_top10_tics": [str(r["tic"]) for r in scored[:10]],
        "sde_top10_tics": [str(r["tic"]) for r in
                           sorted(scored, key=lambda r: r["sde_rank"])
                           [:10]],
    }
    # Ranker-vs-SDE top-decile overlap: how much the ranker moves
    # the queue relative to the SDE order the desk already uses.
    ranker_decile = {str(r["tic"]) for r in scored[:decile]}
    sde_decile = {str(r["tic"]) for r in
                  sorted(scored, key=lambda r: r["sde_rank"])[:decile]}
    report["top_decile_overlap_ranker_vs_sde"] = len(
        ranker_decile & sde_decile)
    if toi_tics is not None:
        present = {t: rank_by_tic[t] for t in toi_tics
                   if t in rank_by_tic}
        report["toi"] = {
            "n_in_toi_list": len(toi_tics),
            "n_in_scored_set": len(present),
            "ranks": present,
            "n_in_top_decile": sum(1 for rk in present.values()
                                   if rk <= decile),
        }
    return report


def _render_report_md(report):
    lines = ["# P3-21 — Frozen-ranker scoring report\n"]
    lines.append(f"- **Sector:** {report['sector']} · "
                 f"**scored:** {report['scored_at_utc']}")
    lines.append(f"- **Survivors scored:** {report['n_survivors']} "
                 f"(top-decile cutoff: rank ≤ "
                 f"{report['top_decile_cutoff_rank']})")
    lines.append(f"- **Frozen model:** seed {report['seed']} · "
                 f"git {report['git_sha'][:12]} · bulk_v4 registry "
                 f"sha256 {report['bulk_v4_registry_sha256'][:12]}…")
    lines.append(f"- **Dataset:** {report['dataset']['rows']} rows "
                 f"(train {report['dataset']['train_rows']}, test "
                 f"{report['dataset']['test_rows']})")
    lines.append(f"- **Permutation check:** "
                 f"{'PASS' if report['permutation_check'] else 'FAIL'} "
                 f"(output is a permutation of the input)")
    if report["limited"]:
        lines.append(f"- **LIMITED RUN:** only the first "
                     f"{report['limit']} rows scored — NOT the "
                     f"validation pass.")
    lines.append(f"- **Ranker top 10:** "
                 f"{', '.join(report['ranker_top10_tics'])}")
    lines.append(f"- **SDE top 10:** "
                 f"{', '.join(report['sde_top10_tics'])}")
    lines.append(f"- **Top-decile overlap (ranker vs SDE):** "
                 f"{report['top_decile_overlap_ranker_vs_sde']} / "
                 f"{report['top_decile_cutoff_rank']}")
    if "toi" in report:
        t = report["toi"]
        lines.append(f"- **TOIs in the scored set:** "
                     f"{t['n_in_scored_set']} of "
                     f"{t['n_in_toi_list']} in the TOI list; "
                     f"{t['n_in_top_decile']} in the top decile")
        for tic, rk in sorted(t["ranks"].items(), key=lambda kv: kv[1]):
            lines.append(f"  - TIC {tic}: rank {rk} "
                         f"({'top decile' if rk <= report['top_decile_cutoff_rank'] else 'outside top decile'})")
    return "\n".join(lines) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Score one sector's survivors with the frozen "
                    "3A ranker (P3-21). S98 is refused (TB-8).")
    ap.add_argument("--survivors", required=True,
                    help="survivors JSONL to score (one sector)")
    ap.add_argument("--out-dir", required=True,
                    help="output directory (created if needed)")
    ap.add_argument("--seed", type=int, default=20261116,
                    help="dataset seed (default 20261116 — the "
                         "frozen seed; do not change for P3-21)")
    ap.add_argument("--toi-csv", default=None,
                    help="optional CSV of TOI TICs (first column) "
                         "for the top-decile check")
    ap.add_argument("--limit", type=int, default=None,
                    help="score only the first N rows (SMOKE ONLY — "
                         "a limited run is not the validation pass)")
    args = ap.parse_args(argv)

    with open(args.survivors) as fh:
        records = [json.loads(line) for line in fh if line.strip()]
    if not records:
        raise SystemExit("[score_sector] ABORT: no records in "
                         f"{args.survivors}")
    sector = guard_sector(args.survivors, records)
    print(f"scoring sector {sector}: {len(records)} survivors",
          flush=True)
    if args.limit is not None:
        records = records[:args.limit]
        print(f"--limit {args.limit}: scoring {len(records)} rows "
              f"(SMOKE ONLY)", flush=True)

    print("rebuilding the frozen model (dataset + train split, "
          f"seed {args.seed}) ...", flush=True)
    model, ds = train_frozen_model(seed=args.seed)
    print(f"dataset: {len(ds['rows'])} rows", flush=True)

    scored = score_records(records, model)
    toi_tics = (_load_toi_csv(args.toi_csv)
                if args.toi_csv else None)
    report = build_report(
        scored, records, sector, args.seed, _git_sha(),
        _bulk_v4_sha(), ds, toi_tics=toi_tics,
        limited=args.limit is not None, limit=args.limit)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "ranked_survivors.jsonl", "w") as fh:
        for row in scored:
            fh.write(json.dumps(row) + "\n")
    with open(out_dir / "score_report.json", "w") as fh:
        json.dump(report, fh, indent=2, sort_keys=True)
    with open(out_dir / "score_report.md", "w") as fh:
        fh.write(_render_report_md(report))
    print(f"wrote ranked_survivors.jsonl ({len(scored)} rows) + "
          f"score_report.json/.md to {out_dir}")
    if "toi" in report:
        t = report["toi"]
        print(f"TOIs in scored set: {t['n_in_scored_set']}, "
              f"in top decile: {t['n_in_top_decile']}")
    return report


if __name__ == "__main__":
    main()
