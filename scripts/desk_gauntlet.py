#!/usr/bin/env python
"""Automated desk gauntlet (Phase 2, 2A) — vet one survivor.

Usage:
  desk_gauntlet.py TIC --period P --t0 T0 --duration DUR_H
      --depth DEPTH_PCT [--sde SDE] [--sector SEC]
      [--workdir DIR] [--no-expensive] [--no-bulk]
      [--waive STAGE:REASON ...]

Runs the desk driver (gauntlet/desk.py) in manual order:
catalogue, clean-data re-fold gate, refine, raw flux, shape,
odd/even, persistence, blend, pixel check — then holdout,
difference imaging and the transit fit on cheap-pass survivors
only. Writes verdict_record.json + desk_natives.json (+
stage0_census.json, data/, tesscut/, diffimg/, transit_fit/)
into the workdir and prints the verdict.

The workdir defaults to vetting_results/desk-<TIC> under the
repo root (run data, gitignored). Nothing is filed anywhere:
a CANDIDATE verdict means "ready for human filing review"
(2E), not a discovery.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

from gauntlet.desk import (LiveDataSource, Survivor,  # noqa: E402
                           run_desk_gauntlet)


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Automated desk gauntlet for one survivor.")
    ap.add_argument("tic")
    ap.add_argument("--period", type=float, required=True,
                    help="filed period in days")
    ap.add_argument("--t0", type=float, required=True,
                    help="filed T0 in BTJD")
    ap.add_argument("--duration", type=float, required=True,
                    help="filed transit duration in hours")
    ap.add_argument("--depth", type=float, required=True,
                    help="filed depth in percent")
    ap.add_argument("--sde", type=float, default=None)
    ap.add_argument("--sector", type=int, default=None,
                    help="discovery sector (clean gate + TPF)")
    ap.add_argument("--workdir", default=None)
    ap.add_argument("--no-expensive", action="store_true",
                    help="cheap stages only (no holdout/diffimg/fit)")
    ap.add_argument("--no-bulk", action="store_true",
                    help="not a bulk-screen survivor (the clean gate "
                         "is then not applicable)")
    ap.add_argument("--waive", action="append", default=[],
                    help='"STAGE:reason" (repeatable; F-5 waiver '
                         "policy applies)")
    ap.add_argument("--external-tools", action="store_true",
                    help="run the configured external tools "
                         "(LATTE/TRICERATOPS, from the "
                         "external_tools_v2 policy) as "
                         "post-runner evidence stages "
                         "(Mac-only by configuration: on a "
                         "host without the venvs they read "
                         "UNMEASURED)")
    args = ap.parse_args(argv)

    repo_root = os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))
    workdir = args.workdir or os.path.join(
        repo_root, "vetting_results", f"desk-{args.tic}")
    waivers = {}
    for w in args.waive:
        stage, _, reason = w.partition(":")
        waivers[stage.strip()] = reason.strip() or "operator waiver"
    survivor = Survivor(
        tic=str(args.tic), period_d=args.period, t0_btjd=args.t0,
        duration_h=args.duration, depth_pct=args.depth,
        sde=args.sde, sector=args.sector,
        bulk_survivor=not args.no_bulk)
    source = LiveDataSource(repo_root=repo_root)
    external = None
    if args.external_tools:
        from gauntlet.external_tool import (
            load_external_tool_configs)
        external = load_external_tool_configs(
            repo_root=repo_root)
    result = run_desk_gauntlet(
        survivor, workdir, source=source,
        run_expensive=not args.no_expensive,
        waivers=waivers or None, repo_root=repo_root,
        external_tools=external)
    print(f"TIC {args.tic}: {result.run.final_verdict}",
          flush=True)
    for r in result.run.results:
        print(f"  {r.stage:12s} {r.status:14s} "
              f"[{r.execution_status}] {r.reason}", flush=True)
    for tool, res in sorted(
            (result.extra_evidence.get("external_tools")
             or {}).items()):
        print(f"  {tool:12s} {res['status']:14s} "
              f"[evidence only] {res['reason']}", flush=True)
    if result.cheap_kill:
        print("  (killed at a cheap stage — expensive stages not "
              "run)", flush=True)
    print(f"verdict: {os.path.join(workdir, 'verdict_record.json')}",
          flush=True)
    print(f"natives: {os.path.join(workdir, 'desk_natives.json')}",
          flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
