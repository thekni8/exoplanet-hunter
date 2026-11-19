"""4.1-3 stacked-floor measurement: scorer (Phase 4.1).

Scores ONE interval's campaign + null host files at a
PARAMETERISED MES gate and publishes the stacked sensitivity
curve for that interval with pre-reg section 0.3 intervals
(Wilson, Clopper-Pearson, host-clustered bootstrap -- the
host-clustered lower bound is PRIMARY).

SCORING RULE (PIPE50-9, ratified 2026-11-19 14:00 IST):
pre-reg section 0.4 is STAGE-AGNOSTIC (period within 1% +
epoch within one transit duration -- no pass qualifier), so
the PRIMARY rule is ANY-STAGE: a trial is recovered iff ANY
pass (1, 2, or 3) finds it under period-within-1% +
epoch-within-one-duration + tier-A-at-gate. The final-only
rule (pass 2 OR 3) is ALSO reported at every depth and
interval, for comparability with the 4.1-10 / bright-star
curves. The stitched pass-1 screen is recorded per trial by
the campaign leg (bulk/p43_run.py, record_pass1_stitched)
-- this scorer FAILS LOUDLY if a trial record lacks it
(a run without pass-1 recording cannot be scored
any-stage).

DUAL EPOCH RULE (413-6, pre-declared): the frozen section
0.4 rule (epoch within ONE transit duration) is the
HEADLINE; the P4-5 half-duration rule (|dT0| <= 0.5*D_inj)
is the like-for-like comparator for 9.1% at 0.05% and 53.5%
at 0.20%. Both are published at every depth and interval,
under BOTH the any-stage and final-only rules.

NULL: a null host is a false survivor at gate G iff its
pass-1 OR pass-2 OR pass-3 stitched screen record is tier-A
at G (any-stage, symmetric with the campaign -- if the
recovery rate counts pass-1 detections, the null rate must
count pass-1 false alarms). The final-only null rate (pass
2/3) is ALSO reported, for comparability with 4.1-10's
8.75/1,000 (final-only). The null leg already records its
stitched pass-1 screen (r["pass1"]), so no harness change
is needed for nulls.

The gate hookup (the POST-SWEEP gate): the campaign RUNS at
the settled gate (bulk/p413_run.py --mes-gate, recorded per
host file + in the run summary). This scorer RE-DERIVES
recovery at --mes-threshold from the recorded screen fields
+ the recorded epoch deltas. At threshold == run gate it
must agree with the runner's tier assignment (asserted:
every re-derived tier-A recovery has leg status
"survivor"). FAILS LOUDLY if --mes-threshold > --run-gate.

Usage:
  python bulk/p413_score.py --manifest <p413_manifest.json> \
      --null-manifest <p413_null_manifest.json> \
      --run-dir <phase41-413/run/interval4> --interval 4 \
      --mes-threshold 9.0 --run-gate 9.0 \
      --out <p413_curve_interval4.json>
"""
import argparse
import hashlib
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bulk.p4110_score import GateBars  # noqa: E402
from bulk.p4110_score import leg_recovers  # noqa: E402
from bulk.p4110_score import rate_row  # noqa: E402
from bulk.p4110_score import tier_a_at_gate  # noqa: E402
from bulk.p4110_score import trial_recovers  # noqa: E402

INTERVAL_SECTORS = {2: [95, 96], 3: [95, 96, 97],
                    4: [95, 96, 97, 98]}
RECOVERY_TOL = 0.01


def _period_match(found, injected):
    if found is None or injected is None:
        return False
    return abs(float(found) - float(injected)) / float(injected) \
        < RECOVERY_TOL


def _load_host_files(out_dir, subdir):
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
            recs.append(rec)
    return recs


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def pass1_recovers(rec, trial, bars, epoch_tol_dur=1.0):
    """The stitched pass-1 (unmasked) screen recovers the
    trial at gate bars.mes_gate. No alias veto is recorded
    for pass 1, so none is applied (the PIPE50 section 7.3
    precedent -- the official scorer applies the veto only
    to pass 2/3; vetoed trials are few)."""
    return leg_recovers(
        rec.get("pass1"), trial, False,
        rec.get("epoch_delta_over_d_pass1"), bars, epoch_tol_dur)


def trial_recovers_anystage(rec, trial, bars, epoch_tol_dur=1.0):
    """A campaign trial record recovers iff ANY pass (1, 2,
    or 3) recovers it (PIPE50-9b, the section 0.4 rule)."""
    return bool(
        pass1_recovers(rec, trial, bars, epoch_tol_dur)
        or trial_recovers(rec, trial, bars, epoch_tol_dur))


def null_survivor_anystage(null_rec, bars):
    """A null host record is a false survivor at the gate iff
    its pass-1 OR pass-2 OR pass-3 screen record is tier-A at
    the gate. (No period/epoch match -- nothing injected.)"""
    return bool(tier_a_at_gate(null_rec.get("pass1"), bars)
                or tier_a_at_gate(null_rec.get("pass2"), bars)
                or tier_a_at_gate(null_rec.get("pass3"), bars))


def null_survivor_finalonly(null_rec, bars):
    """A null host record is a false survivor (final-only)
    iff its pass-2 OR pass-3 screen record is tier-A at the
    gate -- the 4.1-10 comparability definition."""
    return bool(tier_a_at_gate(null_rec.get("pass2"), bars)
                or tier_a_at_gate(null_rec.get("pass3"), bars))


def _floor_estimate(by_depth, rule_key, epoch_key):
    """The depth where the curve crosses 50% recovery, by
    linear interpolation on log10(depth) between adjacent
    measured depths. Returns {"floor_frac": x, ...} or
    {"floor_frac": None, "reason": ...} when the curve never
    crosses 50% in the measured range. An interpolation, not
    a measurement -- the record states it as such."""
    depths = sorted((float(d), e[rule_key][epoch_key]["rate"])
                    for d, e in by_depth.items())
    depths = [(d, r) for d, r in depths if r is not None]
    if not depths:
        return {"floor_frac": None, "reason": "no rates"}
    if all(r < 0.5 for _d, r in depths):
        return {"floor_frac": None,
                "reason": "curve below 50% at all depths "
                          "(floor above the measured range)"}
    if all(r >= 0.5 for _d, r in depths):
        return {"floor_frac": None,
                "reason": "curve above 50% at all depths "
                          "(floor below the measured range)"}
    for (d0, r0), (d1, r1) in zip(depths, depths[1:]):
        if (r0 - 0.5) * (r1 - 0.5) <= 0 and r1 != r0:
            w = (0.5 - r0) / (r1 - r0)
            logf = (math.log10(d0)
                    + w * (math.log10(d1) - math.log10(d0)))
            return {"floor_frac": float(10 ** logf),
                    "floor_pct": float(100 * 10 ** logf),
                    "bracket": [d0, d1],
                    "method": ("linear interpolation on "
                               "log10(depth) between adjacent "
                               "measured depths")}
    return {"floor_frac": None, "reason": "no crossing found"}


def score_campaign(manifest, run_dir, bars, run_gate, interval,
                   partial=False):
    """Score one interval's campaign leg. Returns the curve
    dict for that interval.

    Fails loudly on: a threshold above the run gate; missing
    host files / trials / errors; a trial record without a
    pass-1 screen (the run did not record pass-1); a nesting
    violation across gates 9/8/7; a re-derived tier-A
    recovery whose leg status is not "survivor" at threshold
    == run gate.
    partial=True (SMOKE ONLY): score the trials present and
    skip the completeness failures; the output is stamped
    partial and is NEVER a publishable curve. Errors still
    fail loudly.
    """
    if bars.mes_gate > run_gate + 1e-9:
        raise SystemExit(
            f"[p413-score] REFUSING: --mes-threshold "
            f"{bars.mes_gate} > run gate {run_gate} -- scoring "
            f"above the run gate needs a re-screen.")
    man_trials = {(t["tic"], int(t["sector"]), t["trial_id"]): t
                  for t in manifest["trials"]}
    host_recs = _load_host_files(run_dir, "hosts-p43")
    leg_trials = {}
    n_errors = 0
    n_no_pass1 = 0
    for rec in host_recs:
        for tr in rec.get("trials", []):
            if "error" in tr:
                n_errors += 1
                continue
            if "pass1" not in tr:
                n_no_pass1 += 1
            leg_trials[(tr["tic"], int(tr["sector"]),
                        tr["trial_id"])] = tr
    missing = [k for k in man_trials if k not in leg_trials]
    if missing and not partial:
        raise SystemExit(
            f"[p413-score] interval {interval}: {len(missing)} "
            f"manifest trials have no host record (e.g. "
            f"{missing[0]}); the run is incomplete -- re-run "
            f"or resume before scoring.")
    if n_errors:
        raise SystemExit(
            f"[p413-score] interval {interval}: {n_errors} "
            f"trials carry errors; the run is incomplete.")
    if n_no_pass1:
        raise SystemExit(
            f"[p413-score] interval {interval}: {n_no_pass1} "
            f"trial records lack a pass-1 screen -- this run "
            f"did not record the stitched pass-1 screen "
            f"(PIPE50-9c); any-stage scoring is impossible. "
            f"Re-run with --record-pass1-stitched.")
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
        any_10 = trial_recovers_anystage(rec, m_tr, bars, 1.0)
        any_05 = trial_recovers_anystage(rec, m_tr, bars, 0.5)
        fin_10 = trial_recovers(rec, m_tr, bars, 1.0)
        fin_05 = trial_recovers(rec, m_tr, bars, 0.5)
        p1 = pass1_recovers(rec, m_tr, bars, 1.0)
        veto2 = bool((rec.get("alias_veto") or {}).get("vetoed"))
        veto3 = bool((rec.get("alias_veto_pass3") or {}).get(
            "vetoed"))
        p2 = leg_recovers(rec.get("pass2"), m_tr, veto2,
                          rec.get("epoch_delta_over_d"), bars,
                          1.0)
        p3 = leg_recovers(rec.get("pass3"), m_tr, veto3,
                          rec.get("epoch_delta_over_d_pass3"),
                          bars, 1.0)
        if rec.get("final_genuine") is True:
            runner_genuine += 1
        for leg_key, od_key in (("pass2", "epoch_delta_over_d"),
                                ("pass3",
                                 "epoch_delta_over_d_pass3")):
            sub = rec.get(leg_key)
            if (sub is not None
                    and sub.get("status") == "survivor"
                    and sub.get("tier") == "B"
                    and _period_match(sub.get("period_days"),
                                      m_tr["period_d"])):
                od = rec.get(od_key)
                if od is not None and float(od) <= 1.0:
                    tier_b += 1
                    break
        if abs(bars.mes_gate - run_gate) < 1e-9:
            # Cross-check: at threshold == run gate, a
            # re-derived tier-A recovery MUST have leg status
            # "survivor". Checked for every pass that recovers.
            for leg_key, recovers in (("pass1", p1),
                                      ("pass2", p2),
                                      ("pass3", p3)):
                if not recovers:
                    continue
                sub = rec.get(leg_key)
                if sub is None or sub.get("status") != "survivor":
                    cross_mismatch += 1
        rows.append({"key": key, "trial": m_tr,
                     "any_1.0": any_10, "any_0.5": any_05,
                     "fin_1.0": fin_10, "fin_0.5": fin_05,
                     "p1": p1, "p2": p2, "p3": p3})
    if cross_mismatch:
        raise SystemExit(
            f"[p413-score] interval {interval}: "
            f"{cross_mismatch} re-derived tier-A recoveries "
            f"have leg status != survivor at threshold == run "
            f"gate -- the scorer disagrees with the runner; do "
            f"NOT publish this curve.")

    def _row_group(subset, field):
        by_host = defaultdict(lambda: [0, 0])
        k = 0
        for r in subset:
            by_host[r["trial"]["tic"]][0] += 1
            by_host[r["trial"]["tic"]][1] += int(r[field])
            k += int(r[field])
        return rate_row(k, len(subset), list(by_host.values()))

    def _entry(subset):
        by_pass = {
            "pass1": sum(1 for r in subset if r["p1"]),
            "pass2": sum(1 for r in subset if r["p2"]),
            "pass3": sum(1 for r in subset if r["p3"]),
            "pass1_only": sum(1 for r in subset
                              if r["p1"] and not r["fin_1.0"]),
            "final_only_count": sum(1 for r in subset
                                    if r["fin_1.0"]
                                    and not r["p1"]),
            "both_pass1_and_final": sum(1 for r in subset
                                        if r["p1"]
                                        and r["fin_1.0"]),
            "neither": sum(1 for r in subset
                           if not r["any_1.0"]),
        }
        return {
            "any_stage": {
                "section_0.4_one_duration": _row_group(
                    subset, "any_1.0"),
                "half_duration_alongside": _row_group(
                    subset, "any_0.5"),
            },
            "final_only": {
                "section_0.4_one_duration": _row_group(
                    subset, "fin_1.0"),
                "half_duration_alongside": _row_group(
                    subset, "fin_0.5"),
            },
            "by_pass_one_duration": by_pass,
        }

    by_depth = {}
    for j, depth in enumerate(manifest["depths_frac"]):
        sub = [r for r in rows if r["trial"]["depth_idx"] == j]
        entry = _entry(sub)
        entry["depth_frac"] = depth
        by_depth[f"{depth:.4f}"] = entry
    asp = [r for r in rows
           if r["trial"]["depth_idx"] == 1
           and r["trial"]["period_d"] < 5.0]
    if not partial:
        assert len(asp) == 138, (
            f"aspirational cell has {len(asp)} trials, want 138")
    out = {
        "interval": interval,
        "sectors": INTERVAL_SECTORS[interval],
        "gate": bars.mes_gate, "run_gate": run_gate,
        "partial": bool(partial),
        "calibration": bars.calibration,
        "bars": {"survivor_sde": bars.survivor_sde,
                 "tier_a_min_events": bars.min_events,
                 "tier_a_min_strong": bars.min_strong},
        "n_trials": len(rows),
        "n_hosts": len({r["trial"]["tic"] for r in rows}),
        "by_depth": by_depth,
        "aspirational_0.05pct_P_lt_5d": _entry(asp),
        "floor_estimate": {
            "any_stage_one_duration": _floor_estimate(
                by_depth, "any_stage",
                "section_0.4_one_duration"),
            "any_stage_half_duration": _floor_estimate(
                by_depth, "any_stage",
                "half_duration_alongside"),
            "final_only_one_duration": _floor_estimate(
                by_depth, "final_only",
                "section_0.4_one_duration"),
            "final_only_half_duration": _floor_estimate(
                by_depth, "final_only",
                "half_duration_alongside"),
        },
        "tier_b_survivor_recoveries_secondary": tier_b,
        "runner_final_genuine_count": runner_genuine,
        "runner_final_genuine_note": (
            "The runner's final_genuine (half-duration epoch + "
            "any-tier survivor) -- reported for reference; the "
            "curve judges by section 0.4 (one duration) + "
            "tier-A-at-gate."),
    }
    # Nesting across gates 9/8/7: recovery must be monotone
    # non-decreasing as the gate lowers -- monotone BY
    # CONSTRUCTION of the threshold rule, so a violation is a
    # scoring bug. Checked for BOTH rules (any-stage primary).
    for rule_name, fn in (
            ("any_stage", trial_recovers_anystage),
            ("final_only", trial_recovers)):
        nesting = {}
        for g in (9.0, 8.0, 7.0):
            if g > run_gate + 1e-9:
                continue
            b = GateBars(bars.calibration, g)
            counts = {}
            for j in range(5):
                k = sum(1 for key, m_tr in man_trials.items()
                        if key in leg_trials
                        and m_tr["depth_idx"] == j
                        and fn(leg_trials[key], m_tr, b, 1.0))
                counts[f"depth_{j}"] = k
            nesting[f"gate_{g:.0f}"] = counts
        gates_sorted = sorted(nesting,
                              key=lambda s: -float(s[5:]))
        for j in range(5):
            vals = [nesting[g][f"depth_{j}"]
                    for g in gates_sorted]
            if vals != sorted(vals):
                raise SystemExit(
                    f"[p413-score] NESTING VIOLATION "
                    f"({rule_name}) at depth {j}: recovery "
                    f"across gates "
                    f"{list(zip(gates_sorted, vals))} is not "
                    f"monotone -- the scorer is broken.")
        out[f"nesting_{rule_name}_9_8_7"] = nesting
    return out


def score_null(manifest_null, run_dir, bars, interval,
               partial=False):
    """Score one interval's null leg (stitched only).
    Returns the null rates per 1,000 (any-stage PRIMARY +
    final-only alongside). partial=True (SMOKE ONLY): score
    the null hosts present; the output is stamped partial."""
    eligible = {t["tic"] for t in manifest_null["trials"]
                if interval in t.get("intervals", [])}
    recs = _load_host_files(run_dir, "null-p43")
    if not recs:
        return {"interval": interval, "n_null_hosts": 0,
                "note": "no null host files in this run dir"}
    n_err = sum(1 for r in recs if "error" in r)
    if n_err:
        raise SystemExit(
            f"[p413-score] interval {interval} null: {n_err} "
            f"host files carry errors; the null run is "
            f"incomplete.")
    have = {r["tic"] for r in recs}
    missing = [t for t in eligible if t not in have]
    if missing and not partial:
        raise SystemExit(
            f"[p413-score] interval {interval} null: "
            f"{len(missing)} eligible null hosts have no host "
            f"record; the null run is incomplete.")
    by_host_any = {}
    by_host_fin = {}
    for r in recs:
        if r["tic"] not in eligible:
            continue  # a host from another interval's run dir
        by_host_any[r["tic"]] = null_survivor_anystage(r, bars)
        by_host_fin[r["tic"]] = null_survivor_finalonly(r, bars)
    n = len(by_host_any)
    k_any = sum(by_host_any.values())
    k_fin = sum(by_host_fin.values())
    return {
        "interval": interval,
        "sectors": INTERVAL_SECTORS[interval],
        "gate": bars.mes_gate,
        "calibration": bars.calibration,
        "partial": bool(partial),
        "n_null_hosts": n,
        "any_stage": {
            "n_false_survivors": k_any,
            "rate_per_1000": (1000.0 * k_any / n if n else None),
        },
        "final_only": {
            "n_false_survivors": k_fin,
            "rate_per_1000": (1000.0 * k_fin / n if n else None),
        },
    }


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Score one 4.1-3 interval's campaign + null "
                    "at a parameterised MES gate.")
    ap.add_argument("--manifest", required=True,
                    help="finalised p413_manifest.json")
    ap.add_argument("--null-manifest", default=None,
                    help="p413_null_manifest.json (null scored "
                         "only if given)")
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--interval", type=int, required=True,
                    choices=(2, 3, 4))
    ap.add_argument("--mes-threshold", type=float, default=9.0)
    ap.add_argument("--run-gate", type=float, default=None,
                    help="gate the run used (default: read from "
                         "<run-dir>/p413_summary.json, else the "
                         "threshold itself)")
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
        summary_path = Path(args.run_dir) / "p413_summary.json"
        if summary_path.exists():
            run_gate = float(json.loads(
                summary_path.read_text())["mes_gate"])
        else:
            run_gate = args.mes_threshold
    bars = GateBars(args.calibration, args.mes_threshold)
    curve = score_campaign(manifest, args.run_dir, bars, run_gate,
                           args.interval, partial=args.partial)
    curve["tool"] = "bulk/p413_score.py"
    curve["item"] = "4.1-3 stacked-floor measurement"
    curve["manifest_sha256"] = _sha(args.manifest)
    curve["run_dir"] = str(args.run_dir)
    if args.null_manifest:
        null_man = json.loads(Path(args.null_manifest).read_text())
        curve["null"] = score_null(null_man, args.run_dir, bars,
                                   args.interval,
                                   partial=args.partial)
        curve["null_manifest_sha256"] = _sha(args.null_manifest)
    out = Path(args.out)
    out.write_text(json.dumps(curve, indent=1, sort_keys=True))
    print(f"[p413-score] interval {args.interval} gate "
          f"{bars.mes_gate} (run gate {run_gate}), stitched "
          f"recovery by depth (any-stage PRIMARY / final-only):")
    for depth, entry in sorted(curve["by_depth"].items()):
        a = entry["any_stage"]["section_0.4_one_duration"]
        f = entry["final_only"]["section_0.4_one_duration"]
        print(f"  {depth}: any {a['k']}/{a['n']} = "
              f"{a['rate']:.1%} | fin {f['k']}/{f['n']} = "
              f"{f['rate']:.1%}")
    if "null" in curve and curve["null"].get("n_null_hosts"):
        nl = curve["null"]
        print(f"[p413-score] null interval {args.interval}: any "
              f"{nl['any_stage']['n_false_survivors']}/"
              f"{nl['n_null_hosts']} = "
              f"{nl['any_stage']['rate_per_1000']:.2f}/1,000 | "
              f"fin {nl['final_only']['n_false_survivors']}/"
              f"{nl['n_null_hosts']} = "
              f"{nl['final_only']['rate_per_1000']:.2f}/1,000")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
