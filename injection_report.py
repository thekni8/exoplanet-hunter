#!/usr/bin/env python
"""Build the hunting map (heatmap PNG) + results tables from
injection_results.json. The interpretive readout in the report is
finalized by hand after inspecting these numbers."""
import json
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

PROJECT = os.path.dirname(os.path.abspath(__file__))
DEPTHS = [1.2, 0.8, 0.5, 0.35, 0.25, 0.15]
PERIODS = [1.5, 4.0, 8.0, 13.0]


def main():
    with open(os.path.join(PROJECT, "injection_results.json")) as fh:
        data = json.load(fh)
    trials = data["trials"]
    inj = [r for r in trials if r["kind"] == "inject"]
    ctrl = [r for r in trials if r["kind"] == "control"]

    grid = {}
    for d in DEPTHS:
        for p in PERIODS:
            cell = [r for r in inj if r["injected_depth_pct"] == d
                    and r["injected_period_d"] == p]
            n = len(cell)
            n_clean = sum(r["recovered"] for r in cell)
            n_alias = sum(r["aliased"] for r in cell)
            grid[(d, p)] = {
                "n": n, "clean": n_clean, "alias": n_alias,
                "clean_pct": 100.0 * n_clean / n if n else float("nan"),
                "any_pct": 100.0 * (n_clean + n_alias) / n if n else float("nan"),
                "sdes": [round(r["sde"], 1) for r in cell],
            }

    # Median depth error per depth row (over trials where BLS locked onto
    # the signal: recovered or aliased)
    depth_err = {}
    for d in DEPTHS:
        errs = [r["depth_error_pct"] for r in inj
                if r["injected_depth_pct"] == d and (r["recovered"] or r["aliased"])]
        depth_err[d] = float(np.median(errs)) if errs else None

    # ---- heatmap (clean recovery) ----
    mat = np.array([[grid[(d, p)]["clean_pct"] for p in PERIODS] for d in DEPTHS])
    mat_any = np.array([[grid[(d, p)]["any_pct"] for p in PERIODS] for d in DEPTHS])
    fig, axes = plt.subplots(1, 2, figsize=(11.5, 4.6))
    for ax, m, ttl in [
        (axes[0], mat, "clean recovery (period within 1%)"),
        (axes[1], mat_any, "clean + aliased (P/2 or 2P)"),
    ]:
        im = ax.imshow(m, vmin=0, vmax=100, cmap="RdYlGn", aspect="auto")
        ax.set_xticks(range(len(PERIODS)), [f"{p:g} d" for p in PERIODS])
        ax.set_yticks(range(len(DEPTHS)), [f"{d:g}%" for d in DEPTHS])
        ax.set_xlabel("injected period")
        ax.set_ylabel("injected depth")
        ax.set_title(ttl, fontsize=10)
        for i in range(len(DEPTHS)):
            for j in range(len(PERIODS)):
                c = grid[(DEPTHS[i], PERIODS[j])]
                ax.text(j, i, f"{m[i, j]:.0f}%\n({c['clean']}+{c['alias']}/{c['n']})",
                        ha="center", va="center", fontsize=8,
                        color="black")
        fig.colorbar(im, ax=ax, shrink=0.9, label="recovery %")
    fig.suptitle("Exoplanet Hunter — Scanner recovery rate (2 sectors)",
                 fontweight="bold")
    fig.tight_layout()
    out_png = os.path.join(PROJECT, "injection_heatmap.png")
    fig.savefig(out_png, dpi=150)
    plt.close(fig)
    print(f"heatmap -> {out_png}")

    summary = {"grid": {f"{d}|{p}": grid[(d, p)] for d in DEPTHS for p in PERIODS},
               "depth_err_median_pct": depth_err,
               "controls": [{"tic": r["star_tic"], "sde": r["sde"],
                             "period_d": r["recovered_period_d"],
                             "false_alarm": r["false_alarm"]} for r in ctrl]}
    with open("/tmp/injection_summary.json", "w") as fh:
        json.dump(summary, fh, indent=2)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
