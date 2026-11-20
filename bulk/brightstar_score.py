"""Bright-star curve: scorer.

Scores the campaign + null host files at a PARAMETERISED MES
gate and publishes the stacked sensitivity curve with pre-reg
section 0.3 intervals (Wilson, Clopper-Pearson, host-clustered
bootstrap -- the host-clustered lower bound is PRIMARY).

Modeled on bulk/p4110_score.py; the generic machinery is
IMPORTED from it (rate_row, GateBars, tier_a_at_gate,
leg_recovers, trial_recovers, null_survivor_at_gate,
score_null) so the recovery rule and intervals are identical
to 4.1-10's. The campaign scorer is a local copy because
p4110_score.score_campaign asserts 4.1-10-specific pins:
exactly 1 demo trial and aspirational cell == 121. The
bright-star run has NO demo trial and its aspirational cell
(0.05%, P < 5 d) is 120 trials for N = 41 -- computed from
the manifest, never asserted.

Recovery rule (pinned -- pre-reg section 0.4 + the tier-A
gate): a trial is recovered at gate G iff at pass 2 OR pass 3
of a leg:
  (a) found period within 1% of injected (recovery_tol 0.01);
  (b) |epoch delta| <= ONE transit duration (section 0.4 --
      the p43/k3 runners' epoch_match uses the HALF-duration
      P4-5 rule, so the scorer re-derives from the recorded
      epoch_delta_over_d, and publishes the half-duration rate
      alongside for exact P4-5 comparability);
  (c) the leg would be a tier-A survivor with the MES bar at
      G: sde >= SURVIVOR_SDE (7.0) AND n_events >= 3 AND
      mes_pink >= G AND n_strong_events >= 2 (the frozen
      tier-A bars, read from the calibration profile -- only
      the MES bar is a parameter);
  (d) status != "demoted" (an EB veto is a verdict at any
      gate);
  (e) the leg's alias veto did not fire.
Tier-B survivors (n_events < 3) are NOT counted in the primary
curve; their count is reported as a secondary diagnostic, as
is the runner's final_genuine rate.

Null: scored by p4110_score.score_null (generic). The
bright-star null leg is 41 hosts (all 4-sector) -- a direct
check, not a rate estimate; the primary null reference is
4.1-10's measured 8.75/1,000 (design note section 5).

Run-gate lookup: the runner is bulk/p4110_run.py (reused
as-is), which writes p4110_summary.json in the run dir --
this scorer reads that same file for the default run gate.

Usage:
  python bulk/brightstar_score.py \
      --manifest <brightstar_manifest.json> \
      --null-manifest <brightstar_null_manifest.json> \
      --run-dir <phase41-brightstar-curve/run> \
      --mes-threshold 9.0 --run-gate 9.0 \
      --out <brightstar_curve.json>
"""
import argparse
import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bulk.p4110_score import (  # noqa: E402
    GateBars,
    leg_recovers,
    rate_row,
    score_null,
    trial_recovers,
    trial_recovers_anystage,
)


def _load_host_files(out_dir, subdir, arm=None):
    recs = []
    d = Path(out_dir) / subdir
    if not d.is_dir():
        return recs
    for p in sorted(d.glob("*.json")):
        try:
            rec = json.loads(p.read_text())
        except ValueError:
            continue
        if rec.get("complete") is True:
            if arm is None or rec.get("arm") == arm:
                recs.append(rec)
    return recs


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _period_match(found, injected):
    if found is None or injected is None:
        return False
    return abs(float(found) - float(injected)) / float(injected) \
        < 0.01


def score_campaign(manifest, run_dir, bars, run_gate, partial=False):
    """Score the campaign legs. Returns the curve dict.

    Fails loudly on: a threshold above the run gate; missing
    host files / trials / errors; a nesting violation across
    gates 9/8/7; a re-derived tier-A recovery whose leg status
    is not "survivor" at threshold == run gate.
    partial=True (SMOKE ONLY): score the trials present and
    skip the completeness failures; the output is stamped
    partial and is NEVER a publishable curve. Errors still
    fail loudly -- an error is a broken run, not
    incompleteness.
    """
    if bars.mes_gate > run_gate + 1e-9:
        raise SystemExit(
            f"[brightstar-score] REFUSING: --mes-threshold "
            f"{bars.mes_gate} > run gate {run_gate} -- scoring "
            f"above the run gate needs a re-screen (a "
            f"pass-2-rescued trial never ran pass 3).")
    man_trials = {(t["tic"], int(t["sector"]), t["trial_id"]): t
                  for t in manifest["trials"]}
    nsec = {str(h["tic"]): int(h["n_sectors"])
            for h in manifest["hosts"]}
    strata = sorted(set(nsec.values()))
    out = {"gate": bars.mes_gate, "run_gate": run_gate,
           "partial": bool(partial),
           "calibration": bars.calibration,
           "bars": {"survivor_sde": bars.survivor_sde,
                    "tier_a_min_events": bars.min_events,
                    "tier_a_min_strong": bars.min_strong}}
    for leg, subdir in (("stitched", "hosts-p43"),
                        ("single", "hosts")):
        host_recs = _load_host_files(run_dir, subdir)
        leg_trials = {}
        n_errors = 0
        for rec in host_recs:
            for tr in rec.get("trials", []):
                if "error" in tr:
                    n_errors += 1
                    continue
                leg_trials[(tr["tic"], int(tr["sector"]),
                            tr["trial_id"])] = tr
        missing = [k for k in man_trials if k not in leg_trials]
        if missing and not partial:
            raise SystemExit(
                f"[brightstar-score] {leg} leg: {len(missing)} "
                f"manifest trials have no host record (e.g. "
                f"{missing[0]}); the run is incomplete -- "
                f"re-run or resume before scoring.")
        if n_errors:
            raise SystemExit(
                f"[brightstar-score] {leg} leg: {n_errors} trials "
                f"carry errors; the run is incomplete.")
        rows = []
        tier_b = 0
        runner_genuine = 0
        cross_mismatch = 0
        scored_keys = ([k for k in sorted(man_trials)
                        if k in leg_trials] if partial
                       else sorted(man_trials))
        for key in scored_keys:
            m_tr = man_trials[key]
            rec = leg_trials[key]
            recovers = trial_recovers(rec, m_tr, bars, 1.0)
            recovers_half = trial_recovers(rec, m_tr, bars, 0.5)
            # Any-stage (PIPE50-9b, PRIMARY — same adoption as
            # p4110_score.score_campaign). Degenerates to
            # final-only on runs without a recorded pass-1
            # screen, so old curves re-derive unchanged.
            recovers_any = trial_recovers_anystage(
                rec, m_tr, bars, 1.0)
            recovers_any_half = trial_recovers_anystage(
                rec, m_tr, bars, 0.5)
            if rec.get("final_genuine") is True:
                runner_genuine += 1
            for leg_key in ("pass2", "pass3"):
                sub = rec.get(leg_key)
                if (sub is not None
                        and sub.get("status") == "survivor"
                        and sub.get("tier") == "B"
                        and _period_match(sub.get("period_days"),
                                          m_tr["period_d"])):
                    od = rec.get("epoch_delta_over_d"
                                 if leg_key == "pass2"
                                 else "epoch_delta_over_d_pass3")
                    if od is not None and float(od) <= 1.0:
                        tier_b += 1
                        break
            if recovers and abs(bars.mes_gate - run_gate) < 1e-9:
                # Cross-check: at threshold == run gate, a
                # re-derived tier-A recovery MUST have leg
                # status "survivor" (tier A + no demote ==>
                # survivor). Anything else is a scoring bug.
                ok = False
                for leg_key in ("pass2", "pass3"):
                    sub = rec.get(leg_key)
                    if sub is None:
                        continue
                    vetoed = bool(
                        (rec.get("alias_veto"
                                 if leg_key == "pass2"
                                 else "alias_veto_pass3")
                         or {}).get("vetoed"))
                    od = rec.get(
                        "epoch_delta_over_d"
                        if leg_key == "pass2"
                        else "epoch_delta_over_d_pass3")
                    if (leg_recovers(sub, m_tr, vetoed, od, bars,
                                     1.0)
                            and sub.get("status") == "survivor"):
                        ok = True
                if not ok:
                    cross_mismatch += 1
            rows.append({"key": key, "trial": m_tr,
                         "recovers": recovers,
                         "recovers_half": recovers_half,
                         "recovers_any": recovers_any,
                         "recovers_any_half": recovers_any_half})
        if cross_mismatch:
            raise SystemExit(
                f"[brightstar-score] {leg} leg: {cross_mismatch} "
                f"re-derived tier-A recoveries have leg status "
                f"!= survivor at threshold == run gate -- the "
                f"scorer disagrees with the runner; do NOT "
                f"publish this curve.")
        curve_rows = rows  # no demo trial in this run

        def _row_group(subset):
            by_host = defaultdict(lambda: [0, 0])
            k = 0
            for r in subset:
                by_host[r["trial"]["tic"]][0] += 1
                by_host[r["trial"]["tic"]][1] += int(
                    r["recovers"])
                k += int(r["recovers"])
            kh = 0
            by_host_h = defaultdict(lambda: [0, 0])
            for r in subset:
                by_host_h[r["trial"]["tic"]][0] += 1
                by_host_h[r["trial"]["tic"]][1] += int(
                    r["recovers_half"])
                kh += int(r["recovers_half"])
            ka = 0
            by_host_a = defaultdict(lambda: [0, 0])
            for r in subset:
                by_host_a[r["trial"]["tic"]][0] += 1
                by_host_a[r["trial"]["tic"]][1] += int(
                    r["recovers_any"])
                ka += int(r["recovers_any"])
            kah = 0
            by_host_ah = defaultdict(lambda: [0, 0])
            for r in subset:
                by_host_ah[r["trial"]["tic"]][0] += 1
                by_host_ah[r["trial"]["tic"]][1] += int(
                    r["recovers_any_half"])
                kah += int(r["recovers_any_half"])
            return {
                # Final-only retained for comparability; the
                # anystage rows are PRIMARY (PIPE50-9b).
                "section_0.4_one_duration": rate_row(
                    k, len(subset), list(by_host.values())),
                "half_duration_alongside": rate_row(
                    kh, len(subset), list(by_host_h.values())),
                "anystage_one_duration": rate_row(
                    ka, len(subset), list(by_host_a.values())),
                "anystage_half_duration": rate_row(
                    kah, len(subset), list(by_host_ah.values())),
            }

        by_depth = {}
        for j, depth in enumerate(manifest["depths_frac"]):
            sub = [r for r in curve_rows
                   if r["trial"]["depth_idx"] == j]
            entry = _row_group(sub)
            entry["depth_frac"] = depth
            entry["by_stratum"] = {}
            for s in strata:
                ssub = [r for r in sub
                        if nsec[r["trial"]["tic"]] == s]
                entry["by_stratum"][f"{s}_sector"] = _row_group(
                    ssub)
            by_depth[f"{depth:.4f}"] = entry
        # Aspirational cell: 0.05%, P < 5 d -- 120 trials for
        # N = 41, COMPUTED from the manifest, never asserted.
        asp = [r for r in curve_rows
               if r["trial"]["depth_idx"] == 1
               and r["trial"]["period_d"] < 5.0]
        out[leg] = {
            "n_trials": len(curve_rows),
            "n_hosts": len({r["trial"]["tic"]
                            for r in curve_rows}),
            "by_depth": by_depth,
            "aspirational_0.05pct_P_lt_5d": _row_group(asp),
            "demo": {"note": ("no demo trial in the bright-star "
                              "run (design note section 2)")},
            "tier_b_survivor_recoveries_secondary": tier_b,
            "runner_final_genuine_count": runner_genuine,
            "runner_final_genuine_note": (
                "The runner's final_genuine (half-duration "
                "epoch + any-tier survivor) -- reported for "
                "reference; the curve judges by section 0.4 "
                "(one duration) + tier-A-at-gate."),
        }
    # Nesting across gates 9/8/7 (stitched leg): recovery must
    # be monotone non-decreasing as the gate lowers -- it is
    # monotone BY CONSTRUCTION of the threshold rule, so a
    # violation is a scoring bug.
    nesting = {}
    for g in (9.0, 8.0, 7.0):
        if g > run_gate + 1e-9:
            continue
        b = GateBars(bars.calibration, g)
        host_recs = _load_host_files(run_dir, "hosts-p43")
        leg_trials = {}
        for rec in host_recs:
            for tr in rec.get("trials", []):
                if "error" not in tr:
                    leg_trials[(tr["tic"], int(tr["sector"]),
                                tr["trial_id"])] = tr
        counts = {}
        for j in range(4):
            k = sum(1 for key, m_tr in man_trials.items()
                    if key in leg_trials
                    and not m_tr["is_demo"]
                    and m_tr["depth_idx"] == j
                    and trial_recovers(leg_trials[key], m_tr, b,
                                       1.0))
            counts[f"depth_{j}"] = k
        nesting[f"gate_{g:.0f}"] = counts
    gates_sorted = sorted(nesting, key=lambda s: -float(s[5:]))
    for j in range(4):
        vals = [nesting[g][f"depth_{j}"] for g in gates_sorted]
        if vals != sorted(vals):
            raise SystemExit(
                f"[brightstar-score] NESTING VIOLATION at depth {j}: "
                f"recovery across gates {list(zip(gates_sorted, vals))} "
                f"is not monotone -- the scorer is broken.")
    out["nesting_stitched_9_8_7"] = nesting
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Score the bright-star campaign + null at a "
                    "parameterised MES gate.")
    ap.add_argument("--manifest", required=True,
                    help="finalised brightstar_manifest.json")
    ap.add_argument("--null-manifest", default=None,
                    help="brightstar_null_manifest.json (null "
                         "scored only if given)")
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--mes-threshold", type=float, default=9.0)
    ap.add_argument("--run-gate", type=float, default=None,
                    help="gate the run used (default: read from "
                         "<run-dir>/p4110_summary.json -- the "
                         "runner is bulk/p4110_run.py, reused "
                         "as-is -- else the threshold itself)")
    ap.add_argument("--calibration", default="bulk_v5")
    ap.add_argument("--partial", action="store_true",
                    help="SMOKE ONLY: score the trials/hosts "
                         "present; the output is stamped "
                         "partial and is NEVER publishable.")
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    manifest = json.loads(Path(args.manifest).read_text())
    run_gate = args.run_gate
    if run_gate is None:
        summary_path = Path(args.run_dir) / "p4110_summary.json"
        if summary_path.exists():
            run_gate = float(json.loads(
                summary_path.read_text())["mes_gate"])
        else:
            run_gate = args.mes_threshold
    bars = GateBars(args.calibration, args.mes_threshold)
    curve = score_campaign(manifest, args.run_dir, bars, run_gate,
                           partial=args.partial)
    curve["tool"] = "bulk/brightstar_score.py"
    curve["item"] = "bright-star curve"
    curve["manifest_sha256"] = _sha(args.manifest)
    curve["run_dir"] = str(args.run_dir)
    if args.null_manifest:
        null_man = json.loads(Path(args.null_manifest).read_text())
        curve["null"] = score_null(null_man, args.run_dir, bars,
                                   partial=args.partial)
        curve["null_manifest_sha256"] = _sha(args.null_manifest)
    out = Path(args.out)
    out.write_text(json.dumps(curve, indent=1, sort_keys=True))
    st = curve["stitched"]["by_depth"]
    print(f"[brightstar-score] gate {bars.mes_gate} (run gate "
          f"{run_gate}), stitched recovery by depth:")
    for depth, entry in sorted(st.items()):
        row = entry["section_0.4_one_duration"]
        print(f"  {depth}: {row['k']}/{row['n']} = "
              f"{row['rate']:.1%} "
              f"host-clustered 95% [{row['host_clustered_95'][0]:.1%}, "
              f"{row['host_clustered_95'][1]:.1%}]")
    if "null" in curve and curve["null"]["stitched"].get(
            "n_null_hosts"):
        nl = curve["null"]["stitched"]
        print(f"[brightstar-score] null stitched: "
              f"{nl['n_false_survivors']}/{nl['n_null_hosts']} = "
              f"{nl['rate_per_1000']:.2f}/1,000")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
