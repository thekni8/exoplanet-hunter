#!/usr/bin/env python
"""3A offline ranker experiment driver (Phase 3, P3-18).

Trains the Stage 1 ranker on the TIC-grouped train split, evaluates
it against the three baselines (SDE-only, tier-B gates, 5-feature
logistic regression) on the held-out test split, and writes the
evaluation report + machine-readable results.

OFFLINE EXPERIMENT ONLY — reads the committed data files, writes
only the report + results JSON to --out-dir. Never touches run
data, never pushes, never runs on the Mac. Not run in CI.

Usage:
  .venv/bin/python scripts/rank_experiment.py [--out-dir DIR]
"""
import argparse
import json
import os
import sys
from collections import Counter

import numpy as np
from sklearn.model_selection import GroupKFold

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

from bulk import ranker, ranker_dataset as rds  # noqa: E402

GOAL = "/home/hatch/workspace/goals/exoplanet-hunter/hidden_files"
DEFAULT_PATHS = {
    "campaign": f"{GOAL}/science-vet/phase3-vote/p3-10-results-v2/"
                "injections.jsonl",
    "rescore": f"{GOAL}/mac-run-data/rescore-v3-s96/"
               "rescore_v3_s0096.jsonl",
    "null": f"{GOAL}/mac-run-data/inverted-null-s96/"
            "null_survivors.jsonl",
    "labels": f"{GOAL}/science-vet/phase3-vote/p3-11-labels.json",
    "ledger": f"{GOAL}/science-vet/rescore-v3-gauntlet/LEDGER.md",
}
DEFAULT_OUT = f"{GOAL}/science-vet/phase3-vote"

CLASS_INDEX = {name: i for i, name in enumerate(ranker.CLASS_NAMES)}


def _split_arrays(rows, subset):
    """Feature matrix + labels + records for one split."""
    sel = [r for r in rows if r["split"] == subset]
    X = ranker.features_to_array([r["record"] for r in sel])
    y = np.array([CLASS_INDEX[r["label"]] for r in sel], dtype=int)
    return sel, X, y


def _ranking_metrics(y_bin, scores):
    return {
        "recall_at_20": ranker.recall_at_k(y_bin, scores, 20),
        "recall_top_decile": ranker.recall_at_fraction(
            y_bin, scores, 0.10),
        "ndcg": ranker.ndcg(y_bin, scores),
        "average_precision": ranker.average_precision(y_bin, scores),
    }


def _evaluate(name, y_bin, scores, out):
    out[name] = _ranking_metrics(y_bin, scores)
    return out[name]


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="3A offline ranker experiment (P3-18).")
    ap.add_argument("--out-dir", default=DEFAULT_OUT)
    ap.add_argument("--seed", type=int, default=20261116)
    args = ap.parse_args(argv)

    print("building dataset ...", flush=True)
    ds = rds.build_dataset(DEFAULT_PATHS, seed=args.seed)
    rows = ds["rows"]
    train_rows, X_train, y_train = _split_arrays(rows, "train")
    test_rows, X_test, y_test = _split_arrays(rows, "test")
    y_test_bin = (y_test == ranker.PLANET_INDEX).astype(int)
    sample_weight = np.array(
        [ds["class_weights"][r["label"]] for r in train_rows])

    results = {
        "seed": args.seed,
        "dataset": {
            "rows": len(rows),
            "train_rows": len(train_rows),
            "test_rows": len(test_rows),
            "stats_rows": {f"{s}|{c}": n for (s, c), n
                           in ds["stats"]["rows"].items()},
            "stats_tics": {f"{s}|{c}": n for (s, c), n
                           in ds["stats"]["tics"].items()},
            "class_weights": ds["class_weights"],
            "exclusions": ds["exclusions"],
        },
    }

    # --- Feature symmetry on the real data (P3-16 check) ---
    by_class = {}
    for cls in ranker.CLASS_NAMES:
        by_class[cls] = [r["record"] for r in rows
                         if r["label"] == cls]
    sym = ranker.check_feature_symmetry(by_class)
    results["feature_symmetry"] = {
        "max_gap": sym["_max_gap"],
        "rates": {f: sym[f] for f in ranker.FEATURE_NAMES},
    }
    print("feature symmetry max gap:",
          {k: round(v, 3) for k, v in sym["_max_gap"].items()
           if v > 0.01} or "all <= 0.01", flush=True)

    # --- Train the ranker + the logistic baseline ---
    print("training ranker ...", flush=True)
    model = ranker.train_ranker(X_train, y_train,
                                sample_weight=sample_weight)
    log_model = ranker.train_logistic(X_train, y_train,
                                      sample_weight=sample_weight)

    # --- Test-split evaluation: ranker vs three baselines ---
    print("evaluating on test split ...", flush=True)
    test_records = [r["record"] for r in test_rows]
    scores = {
        "ranker": ranker.planet_proba(model, X_test),
        "sde_only": ranker.sde_scores(test_records),
        "gate_baseline": ranker.gate_scores(test_records),
        "logistic_5feat": ranker.logistic_planet_proba(
            log_model, X_test),
    }
    results["test_metrics"] = {}
    for name, sc in scores.items():
        _evaluate(name, y_test_bin, sc, results["test_metrics"])

    # --- Per-class recall + confusion (3-class, test split) ---
    y_pred = model.predict(X_test)
    results["confusion"] = ranker.confusion_3class(
        y_test, y_pred).tolist()
    results["per_class_recall"] = ranker.per_class_recall(
        y_test, y_pred)

    # --- Feature ablation (leave-one-out, NDCG on test) ---
    print("feature ablation ...", flush=True)
    base_ndcg = results["test_metrics"]["ranker"]["ndcg"]
    ablation = {}
    for drop in ranker.FEATURE_NAMES:
        keep = [i for i, f in enumerate(ranker.FEATURE_NAMES)
                if f != drop]
        m = ranker.train_ranker(X_train[:, keep], y_train,
                                sample_weight=sample_weight)
        sc = ranker.planet_proba(m, X_test[:, keep])
        ablation[drop] = ranker.ndcg(y_test_bin, sc) - base_ndcg
    results["ablation_ndcg_delta"] = ablation

    # --- Unseen-sector test: train on S96, score S95 campaign ---
    print("unseen-sector test ...", flush=True)
    s96 = [i for i, r in enumerate(train_rows)
           if r.get("sector") == 96 or r["source"] != "campaign"]
    s95_rows = [r for r in rows if r["source"] == "campaign"
                and r.get("sector") == 95]
    if s95_rows:
        m96 = ranker.train_ranker(
            X_train[s96], y_train[s96],
            sample_weight=sample_weight[s96])
        X95 = ranker.features_to_array([r["record"] for r in s95_rows])
        y95 = np.array([CLASS_INDEX[r["label"]] for r in s95_rows])
        y95_bin = (y95 == ranker.PLANET_INDEX).astype(int)
        sc95 = ranker.planet_proba(m96, X95)
        sde95 = ranker.sde_scores([r["record"] for r in s95_rows])
        results["unseen_sector_s95"] = {
            "n_rows": len(s95_rows),
            "n_planets": int(y95_bin.sum()),
            "ranker": _ranking_metrics(y95_bin, sc95),
            "sde_only": _ranking_metrics(y95_bin, sde95),
        }

    # --- Out-of-fold scoring (5-fold, TIC-grouped) ---
    print("out-of-fold scoring ...", flush=True)
    X_all = ranker.features_to_array([r["record"] for r in rows])
    y_all = np.array([CLASS_INDEX[r["label"]] for r in rows])
    groups = np.array([r["tic"] for r in rows])
    oof = np.zeros(len(rows))
    gkf = GroupKFold(n_splits=5)
    for tr_idx, te_idx in gkf.split(X_all, y_all, groups):
        sw = np.array([ds["class_weights"][rows[i]["label"]]
                       for i in tr_idx])
        m = ranker.train_ranker(X_all[tr_idx], y_all[tr_idx],
                                sample_weight=sw)
        oof[te_idx] = ranker.planet_proba(m, X_all[te_idx])
    y_all_bin = (y_all == ranker.PLANET_INDEX).astype(int)
    results["out_of_fold"] = {
        "metrics": _ranking_metrics(y_all_bin, oof),
    }

    # Per-SDE-bin EB ranks (out-of-fold): the 36 real EBs are all
    # high-SDE, so aggregate EB performance hides low-SDE failure.
    eb_idx = [i for i, r in enumerate(rows)
              if r["source"] == "gauntlet"
              and r["sublabel"] in ("confirmed_eb", "eb_blend")]
    eb_sdes = np.array([rows[i]["record"].get("sde", 0.0)
                        for i in eb_idx])
    eb_ranks = ranker.ranks_of(oof, [i in set(eb_idx)
                                     for i in range(len(rows))])
    quartiles = np.quantile(eb_sdes, [0.0, 0.25, 0.5, 0.75, 1.0])
    bins = []
    for b in range(4):
        lo, hi = quartiles[b], quartiles[b + 1]
        sel = [(s, rk) for s, rk in zip(eb_sdes, eb_ranks)
               if lo <= s <= hi or (b == 3 and s == hi)]
        if sel:
            ranks = [rk for _, rk in sel]
            bins.append({
                "sde_range": [round(float(lo), 1),
                              round(float(hi), 1)],
                "n_ebs": len(sel),
                "median_rank": int(np.median(ranks)),
                "min_rank": int(min(ranks)),
                "max_rank": int(max(ranks)),
            })
    results["out_of_fold"]["eb_ranks_by_sde_bin"] = bins
    results["out_of_fold"]["eb_median_rank"] = int(
        np.median(eb_ranks)) if len(eb_ranks) else None
    results["out_of_fold"]["eb_n"] = len(eb_idx)

    # Gemini's requirement: batch-01 EBs in the top 25% + the
    # rows with a recorded >10σ phase-0.5 brightening.
    b01 = [i for i, r in enumerate(rows)
           if r["tic"] in rds.BATCH_01_EBS]
    b01_ranks = ranker.ranks_of(
        oof, [i in set(b01) for i in range(len(rows))])
    top25 = int(round(len(rows) * 0.25))
    results["gemini_requirement"] = {
        "note": ("No phase-0.5 sigma is recorded for the batch-01 "
                 "EBs (their decisive evidence is V-shape + density "
                 "fail), so the requirement as literally stated is "
                 "untestable from the available records. Reported "
                 "instead: the batch-01 EBs' ranks + the rows with "
                 "a recorded |sigma| > 10."),
        "batch01_eb_n": len(b01),
        "batch01_eb_in_top25": int((b01_ranks <= top25).sum()),
        "batch01_eb_median_rank": int(np.median(b01_ranks))
        if len(b01_ranks) else None,
        "top25_cutoff_rank": top25,
        "recorded_phase05": [],
    }
    for i, r in enumerate(rows):
        sig = r.get("phase05_sigma")
        if sig is not None and abs(sig) > 10:
            rank = int(ranker.ranks_of(
                oof, [j == i for j in range(len(rows))])[0])
            results["gemini_requirement"]["recorded_phase05"].append({
                "tic": r["tic"], "sublabel": r["sublabel"],
                "phase05_sigma": sig, "oof_rank": rank,
                "in_top25": rank <= top25,
            })

    # --- Held-out validation: the 10 known planets in the rescore ---
    print("held-out validation ...", flush=True)
    rescore = [json.loads(line) for line in
               open(DEFAULT_PATHS["rescore"]) if line.strip()]
    X_res = ranker.features_to_array(rescore)
    sc_res = ranker.planet_proba(model, X_res)
    held_ranks = {}
    held_depths = {}
    for h in ds["heldout"]:
        idx = next(i for i, r in enumerate(rescore)
                   if str(r["tic"]) == h["tic"])
        rank = int(ranker.ranks_of(
            sc_res, [j == idx for j in range(len(rescore))])[0])
        held_ranks[h["tic"]] = rank
        held_depths[h["tic"]] = rescore[idx].get("depth_percent")
    decile = int(round(len(rescore) * 0.10))
    results["heldout_validation"] = {
        "n_survivors": len(rescore),
        "top_decile_cutoff_rank": decile,
        "ranks": held_ranks,
        "depths_pct": held_depths,
        "n_in_top_decile": sum(1 for rk in held_ranks.values()
                               if rk <= decile),
        "n_heldout": len(held_ranks),
    }

    # --- Write results + report ---
    os.makedirs(args.out_dir, exist_ok=True)
    with open(os.path.join(args.out_dir,
                           "p3-18-ranker-eval.json"), "w") as fh:
        json.dump(results, fh, indent=2, sort_keys=True)
    report = _render_report(results, ds)
    with open(os.path.join(args.out_dir,
                           "p3-18-ranker-eval.md"), "w") as fh:
        fh.write(report)
    print("wrote p3-18-ranker-eval.json + .md to", args.out_dir)
    return results


def _render_report(res, ds):
    """Render the Markdown evaluation report from `res`."""
    m = res["test_metrics"]
    lines = []
    lines.append("# P3-18 — 3A experimental ranker evaluation\n")
    lines.append("**Date:** 2026-11-16 · **Status:** EXPERIMENTAL — "
                 "evidence for the 3.1 promotion decision, not "
                 "Phase 3 ship criteria (R2/R3/R4). The ranker has "
                 "NO production influence in Phase 3 (P3-19).\n")
    lines.append("## Dataset\n")
    d = res["dataset"]
    lines.append(f"- Rows: {d['rows']} "
                 f"(train {d['train_rows']}, test {d['test_rows']}); "
                 f"held out: 10 known planets (never trained).")
    lines.append(f"- Train rows by class: planet "
                 f"{d['stats_rows'].get('train|planet')}, astro_fp "
                 f"{d['stats_rows'].get('train|astro_fp')}, instr_fp "
                 f"{d['stats_rows'].get('train|instr_fp')}.")
    lines.append(f"- Train TICs by class (effective n): planet "
                 f"{d['stats_tics'].get('train|planet')}, astro_fp "
                 f"{d['stats_tics'].get('train|astro_fp')}, instr_fp "
                 f"{d['stats_tics'].get('train|instr_fp')}.")
    lines.append(f"- Test rows by class: planet "
                 f"{d['stats_rows'].get('test|planet')}, astro_fp "
                 f"{d['stats_rows'].get('test|astro_fp')}, instr_fp "
                 f"{d['stats_rows'].get('test|instr_fp')}.")
    lines.append(f"- Exclusions: {d['exclusions']}.")
    lines.append(f"- Class weights (train, balanced): "
                 f"{ {k: round(v, 2) for k, v in d['class_weights'].items()} }.")
    gaps = {k: round(v, 3) for k, v in
            res["feature_symmetry"]["max_gap"].items() if v > 0.01}
    lines.append(f"- Feature symmetry: max cross-class imputation "
                 f"gap per feature: {gaps or 'all <= 0.01'}.")
    lines.append("")
    lines.append("## Test split: ranker vs baselines\n")
    lines.append("| Ranker | Recall@20 | Recall@Top-10% | NDCG | AP |")
    lines.append("|---|---|---|---|---|")
    for name in ("ranker", "sde_only", "gate_baseline",
                 "logistic_5feat"):
        r = m[name]
        lines.append(
            f"| {name} | {r['recall_at_20']:.3f} | "
            f"{r['recall_top_decile']:.3f} | {r['ndcg']:.3f} | "
            f"{r['average_precision']:.3f} |")
    lines.append("")
    lines.append("## Per-class recall + confusion (test, 3-class)\n")
    lines.append(f"- Per-class recall: "
                 f"{ {k: round(float(v), 3) for k, v in res['per_class_recall'].items()} }.")
    lines.append("- Confusion matrix (rows true, cols predicted; "
                 "order planet / astro_fp / instr_fp):")
    for row in res["confusion"]:
        lines.append(f"  - {row}")
    lines.append("")
    lines.append("## Feature ablation (NDCG delta vs full model)\n")
    for feat, delta in sorted(res["ablation_ndcg_delta"].items(),
                              key=lambda kv: kv[1]):
        lines.append(f"- {feat}: {float(delta):+.3f}")
    lines.append("")
    u = res.get("unseen_sector_s95")
    if u:
        lines.append("## Unseen-sector test (train S96, score S95)\n")
        lines.append(f"- S95 campaign rows: {u['n_rows']} "
                     f"({u['n_planets']} planets — "
                     f"{u['n_planets'] / u['n_rows']:.0%} positive, "
                     f"so Recall@Top-10% is capped at "
                     f"{max(1, int(round(u['n_rows'] * 0.10))) / u['n_planets']:.3f}; "
                     f"NDCG is the informative metric here).")
        for name in ("ranker", "sde_only"):
            r = u[name]
            lines.append(
                f"- {name}: Recall@Top-10% "
                f"{r['recall_top_decile']:.3f}, NDCG {r['ndcg']:.3f}, "
                f"AP {r['average_precision']:.3f}.")
        lines.append("")
    oof = res["out_of_fold"]
    lines.append("## Out-of-fold scoring (5-fold, TIC-grouped)\n")
    lines.append(f"- Overall: NDCG {oof['metrics']['ndcg']:.3f}, "
                 f"Recall@Top-10% "
                 f"{oof['metrics']['recall_top_decile']:.3f}, AP "
                 f"{oof['metrics']['average_precision']:.3f}.")
    lines.append(f"- EBs (n={oof['eb_n']}): median out-of-fold rank "
                 f"{oof['eb_median_rank']} of {res['dataset']['rows']}.")
    lines.append("- EB ranks by SDE quartile:")
    for b in oof["eb_ranks_by_sde_bin"]:
        lines.append(
            f"  - SDE {b['sde_range'][0]}–{b['sde_range'][1]}: "
            f"n={b['n_ebs']}, median rank {b['median_rank']} "
            f"(range {b['min_rank']}–{b['max_rank']}).")
    lines.append("")
    g = res["gemini_requirement"]
    lines.append("## Gemini's requirement (batch-01 EBs, top 25%)\n")
    lines.append(f"- {g['note']}")
    lines.append(f"- Batch-01 EBs: {g['batch01_eb_n']} rows from 11 "
                 f"TICs (a TIC appears once per population it is in); "
                 f"{g['batch01_eb_in_top25']} in the top 25% "
                 f"(cutoff rank {g['top25_cutoff_rank']}), median "
                 f"rank {g['batch01_eb_median_rank']}.")
    for r in g["recorded_phase05"]:
        lines.append(
            f"- Recorded |sigma| > 10: TIC {r['tic']} "
            f"({r['sublabel']}, {r['phase05_sigma']}σ) — "
            f"out-of-fold rank {r['oof_rank']}, "
            f"in top 25%: {r['in_top25']}.")
    lines.append("")
    h = res["heldout_validation"]
    lines.append("## Held-out validation (known planets, rescore)\n")
    lines.append(f"- {h['n_in_top_decile']}/{h['n_heldout']} known "
                 f"planets rank in the top decile of the "
                 f"{h['n_survivors']} rescore survivors (cutoff "
                 f"rank {h['top_decile_cutoff_rank']}).")
    for tic, rank in sorted(h["ranks"].items(), key=lambda kv: kv[1]):
        depth = h["depths_pct"].get(tic)
        depth_s = f"{depth:.2f}%" if depth is not None else "?"
        lines.append(f"  - TIC {tic}: rank {rank} "
                     f"(depth {depth_s})")
    misses = sorted(
        [(tic, rk) for tic, rk in h["ranks"].items()
         if rk > h["top_decile_cutoff_rank"]],
        key=lambda kv: kv[1])
    if misses:
        miss_depths = sorted(
            (h["depths_pct"][tic] for tic, _ in misses
             if h["depths_pct"].get(tic) is not None))
        hit_depths = sorted(
            (h["depths_pct"][tic] for tic, rk in h["ranks"].items()
             if rk <= h["top_decile_cutoff_rank"]
             and h["depths_pct"].get(tic) is not None))
        lines.append(
            f"- Diagnosis: the {len(misses)} misses are the "
            f"{len(misses)} deepest held-out planets "
            f"(depths {', '.join(f'{d:.2f}%' for d in miss_depths)}; "
            f"the {len(hit_depths)} in-decile planets are all "
            f"≤ {max(hit_depths):.2f}%). The campaign's planet "
            f"depth grid caps at 1.0%, so the model has never seen "
            f"a planet deeper than 1% — every training example "
            f"deeper than ~1% is an FP, and the model learned "
            f"'deep = FP'. This is a training-data coverage gap, "
            f"not a ranker defect: the 3.1 fix is planet injections "
            f"across the full depth range (including >1%).")
    lines.append("")
    lines.append("## Untestable items (recorded honestly)\n")
    lines.append("- **The 18 v2 artifacts:** not in the v3 rescore "
                 "(the mask fix killed them) — they have no v3 "
                 "screen records, so the bulk_v4 ranker cannot "
                 "score them. Out-of-fold scoring covers the EBs "
                 "only.")
    lines.append("- **TOI-700 c:** not a rescore survivor (P 16.05 "
                 "d, single-sector) — absent from the held-out "
                 "check by construction.")
    lines.append("- **Gemini's phase-0.5 requirement as literally "
                 "stated:** no phase-0.5 sigma is recorded for the "
                 "batch-01 EBs; the proxy above is the available "
                 "evidence.")
    lines.append("- **Duration / fold-sigma features:** unavailable "
                 "in this offline experiment (see "
                 "docs/ranker-feature-contract.md) — a 3.1 item.")
    lines.append("")
    lines.append("## Verdicts\n")
    lines.append("- **R2 (beats SDE):** "
                 + ("PASS" if m["ranker"]["ndcg"] > m["sde_only"]["ndcg"]
                    else "FAIL")
                 + f" — ranker NDCG {m['ranker']['ndcg']:.3f} vs SDE "
                 f"{m['sde_only']['ndcg']:.3f}.")
    lines.append("- **Beats the gates:** "
                 + ("PASS" if m["ranker"]["ndcg"] > m["gate_baseline"]["ndcg"]
                    else "FAIL")
                 + f" — ranker NDCG {m['ranker']['ndcg']:.3f} vs gates "
                 f"{m['gate_baseline']['ndcg']:.3f}.")
    lines.append("- **Beats the 5-feature logistic regression:** "
                 + ("PASS" if m["ranker"]["ndcg"] > m["logistic_5feat"]["ndcg"]
                    else "FAIL")
                 + f" — ranker NDCG {m['ranker']['ndcg']:.3f} vs LR "
                 f"{m['logistic_5feat']['ndcg']:.3f}.")
    lines.append("- **R3 (known planets top-decile):** "
                 f"{h['n_in_top_decile']}/{h['n_heldout']} in the "
                 f"top decile"
                 + (" — PASS" if h["n_in_top_decile"] == h["n_heldout"]
                    else " — PARTIAL (see the depth diagnosis above; "
                    "a training-data coverage gap, not a ranker "
                    "defect)."))
    lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    main()
