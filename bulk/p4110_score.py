"""4.1-10 deep-sample curve: scorer (Phase 4.1, Stage 4).

Scores the campaign + null host files at a PARAMETERISED MES
gate and publishes the stacked sensitivity curve with pre-reg
section 0.3 intervals (Wilson, Clopper-Pearson, host-clustered
bootstrap -- the host-clustered lower bound is PRIMARY).

The gate hookup (the POST-SWEEP gate):
- The campaign RUNS at the settled gate (bulk/p4110_run.py
  --mes-gate, recorded per host file + in the run summary).
  The runner-side override makes tiers, pass-3 eligibility,
  and recovery exact at the settled gate.
- This scorer RE-DERIVES recovery at --mes-threshold from the
  recorded screen fields (sde, mes_pink, n_events,
  n_strong_events, status, period, t0) + the recorded epoch
  deltas. At threshold == run gate it must agree with the
  runner's tier assignment (asserted: every re-derived tier-A
  recovery has leg status "survivor"); at a LOWER threshold it
  re-scores exactly for pass 2 and conservatively for pass 3
  (a pass-2 peak with mes in [threshold, run gate) earns no
  pass 3 at run time -- the measured rate at a lower threshold
  is a LOWER bound on the true at-threshold rate).
- FAILS LOUDLY if --mes-threshold > --run-gate: scoring above
  the run gate would need a re-screen (a pass-2-rescued trial
  never ran pass 3, so its pass-3 outcome at a higher gate is
  unmeasured).

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
curve (the MES gate is a tier-A concept); their count is
reported as a secondary diagnostic, as is the runner's
final_genuine rate (half-duration epoch + any-tier survivor).

Null: a null host counts as a false survivor at gate G iff its
pass-2 OR pass-3 stitched (or single) screen record is tier-A
at G per (c)+(d) -- no period/epoch match (nothing injected).
Null rate = false survivors / null hosts, reported per 1,000
(overall + per stratum).

Intervals (section 0.3): Wilson, Clopper-Pearson, and
host-clustered bootstrap (10,000 resamples of HOSTS with
replacement, percentile 95% CI, seed 20261117 -- the P4-5
convention). Every rate reports n_hosts alongside n_trials
(section 0.2: the host is the independent unit).

Usage:
  python bulk/p4110_score.py --manifest <p4110_manifest.json> \
      --run-dir <phase41-4110/run> --mes-threshold 9.0 \
      --run-gate 9.0 --out <p4110_curve.json>
"""
import argparse
import hashlib
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import bulk_screen as bs  # noqa: E402

BOOTSTRAP_REPS = 10000
BOOTSTRAP_SEED = 20261117
RECOVERY_TOL = 0.01
Z_95 = 1.959964


# ---------------------------------------------------------------------------
# Intervals (pre-reg section 0.3)
# ---------------------------------------------------------------------------

def wilson(k, n):
    """Wilson 95% interval on k/n. Returns (lo, hi)."""
    if n == 0:
        return (None, None)
    p = k / n
    z2 = Z_95 * Z_95
    denom = 1.0 + z2 / n
    centre = (p + z2 / (2.0 * n)) / denom
    half = (Z_95 * math.sqrt(p * (1.0 - p) / n
                             + z2 / (4.0 * n * n))) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def clopper_pearson(k, n):
    """Clopper-Pearson (exact) 95% interval on k/n."""
    if n == 0:
        return (None, None)
    from scipy.stats import beta as beta_dist
    lo = (0.0 if k == 0 else float(
        beta_dist.ppf(0.025, k, n - k + 1)))
    hi = (1.0 if k == n else float(
        beta_dist.ppf(0.975, k + 1, n - k)))
    return (lo, hi)


def host_clustered_bootstrap(host_counts, n_rep=BOOTSTRAP_REPS,
                             seed=BOOTSTRAP_SEED):
    """Host-clustered bootstrap 95% CI on a RATE.

    host_counts: list of (n_trials, n_recovered) per host.
    Resamples HOSTS with replacement; each replicate's rate is
    sum(recovered)/sum(trials) over the resampled hosts (the
    denominator varies because hosts carry unequal trial
    counts). Percentile interval. Returns (lo, hi).
    """
    n_hosts = len(host_counts)
    if n_hosts == 0:
        return (None, None)
    rng = np.random.default_rng(seed)
    tot = np.array([h[0] for h in host_counts], dtype=float)
    rec = np.array([h[1] for h in host_counts], dtype=float)
    rates = np.empty(n_rep)
    for i in range(n_rep):
        idx = rng.integers(0, n_hosts, n_hosts)
        denom = tot[idx].sum()
        rates[i] = rec[idx].sum() / denom if denom else 0.0
    return (float(np.percentile(rates, 2.5)),
            float(np.percentile(rates, 97.5)))


def rate_row(k, n, host_counts):
    """One rate with all three section 0.3 intervals."""
    w_lo, w_hi = wilson(k, n)
    cp_lo, cp_hi = clopper_pearson(k, n)
    hc_lo, hc_hi = host_clustered_bootstrap(host_counts)
    return {
        "n": n, "k": k,
        "rate": (k / n if n else None),
        "n_hosts": len(host_counts),
        "wilson_95": [w_lo, w_hi],
        "clopper_pearson_95": [cp_lo, cp_hi],
        "host_clustered_95": [hc_lo, hc_hi],
        "host_clustered_lb_primary": hc_lo,
    }


# ---------------------------------------------------------------------------
# Gate-parameterised recovery
# ---------------------------------------------------------------------------

class GateBars:
    """The frozen tier-A bars (from the calibration profile) +
    the parameterised MES gate. Only mes_gate is a parameter."""

    def __init__(self, calibration="bulk_v5", mes_gate=9.0):
        bs.set_calibration(calibration)
        self.calibration = calibration
        self.survivor_sde = float(bs.SURVIVOR_SDE)
        self.min_events = int(bs.TIER_A_MIN_EVENTS)
        self.min_strong = int(bs.TIER_A_MIN_STRONG)
        self.mes_gate = float(mes_gate)


def tier_a_at_gate(leg, bars):
    """Would this screen-record subset be a tier-A survivor with
    the MES bar at bars.mes_gate? Every input is recorded in the
    host file, so this is an exact re-derivation, not an
    approximation. Returns False on any missing field."""
    if leg is None:
        return False
    if leg.get("status") == "demoted":
        return False  # an EB veto is a verdict at any gate
    sde = leg.get("sde")
    mes = leg.get("mes_pink")
    nev = leg.get("n_events")
    nst = leg.get("n_strong_events")
    if sde is None or mes is None or nev is None or nst is None:
        return False
    return (float(sde) >= bars.survivor_sde
            and int(nev) >= bars.min_events
            and float(mes) >= bars.mes_gate
            and int(nst) >= bars.min_strong)


def _period_match(found, injected):
    if found is None or injected is None:
        return False
    return abs(float(found) - float(injected)) / float(injected) \
        < RECOVERY_TOL


def leg_recovers(leg, trial, vetoed, epoch_over_d, bars,
                 epoch_tol_dur=1.0):
    """One leg (pass-2 or pass-3 subset) recovers the trial at
    gate bars.mes_gate under the pinned rule (section 0.4 +
    tier-A-at-gate). epoch_over_d is the recorded
    |epoch delta| / duration (None when unmeasured)."""
    if leg is None or vetoed:
        return False
    if not _period_match(leg.get("period_days"),
                         trial["period_d"]):
        return False
    if epoch_over_d is None:
        return False
    if float(epoch_over_d) > epoch_tol_dur:
        return False
    return tier_a_at_gate(leg, bars)


def trial_recovers(trial_rec, trial, bars, epoch_tol_dur=1.0):
    """A campaign trial record (stitched or single leg shape)
    recovers iff pass 2 OR pass 3 recovers."""
    p2 = leg_recovers(
        trial_rec.get("pass2"), trial,
        bool((trial_rec.get("alias_veto") or {}).get("vetoed")),
        trial_rec.get("epoch_delta_over_d"), bars,
        epoch_tol_dur)
    p3 = leg_recovers(
        trial_rec.get("pass3"), trial,
        bool((trial_rec.get("alias_veto_pass3") or {}).get(
            "vetoed")),
        trial_rec.get("epoch_delta_over_d_pass3"), bars,
        epoch_tol_dur)
    return bool(p2 or p3)


def null_survivor_at_gate(null_rec, bars):
    """A null host record (stitched or single shape) is a false
    survivor at the gate iff its pass-2 OR pass-3 screen record
    is tier-A at the gate. (No period/epoch match -- nothing
    was injected.)"""
    return bool(tier_a_at_gate(null_rec.get("pass2"), bars)
                or tier_a_at_gate(null_rec.get("pass3"), bars))


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def score_campaign(manifest, run_dir, bars, run_gate):
    """Score the campaign legs. Returns the curve dict.

    Fails loudly on: a threshold above the run gate; missing
    host files / trials / errors; a nesting violation across
    gates 9/8/7; a re-derived tier-A recovery whose leg status
    is not "survivor" at threshold == run gate.
    """
    if bars.mes_gate > run_gate + 1e-9:
        raise SystemExit(
            f"[p4110-score] REFUSING: --mes-threshold "
            f"{bars.mes_gate} > run gate {run_gate} -- scoring "
            f"above the run gate needs a re-screen (a "
            f"pass-2-rescued trial never ran pass 3).")
    man_trials = {(t["tic"], int(t["sector"]), t["trial_id"]): t
                  for t in manifest["trials"]}
    nsec = {str(h["tic"]): int(h["n_sectors"])
            for h in manifest["hosts"]}
    out = {"gate": bars.mes_gate, "run_gate": run_gate,
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
        if missing:
            raise SystemExit(
                f"[p4110-score] {leg} leg: {len(missing)} "
                f"manifest trials have no host record (e.g. "
                f"{missing[0]}); the run is incomplete -- "
                f"re-run or resume before scoring.")
        if n_errors:
            raise SystemExit(
                f"[p4110-score] {leg} leg: {n_errors} trials "
                f"carry errors; the run is incomplete.")
        # Per-trial recovery at the scored gate (+ the
        # half-duration epoch rule alongside).
        rows = []
        tier_b = 0
        runner_genuine = 0
        cross_mismatch = 0
        for key, m_tr in sorted(man_trials.items()):
            rec = leg_trials[key]
            recovers = trial_recovers(rec, m_tr, bars, 1.0)
            recovers_half = trial_recovers(rec, m_tr, bars, 0.5)
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
                         "recovers_half": recovers_half})
        if cross_mismatch:
            raise SystemExit(
                f"[p4110-score] {leg} leg: {cross_mismatch} "
                f"re-derived tier-A recoveries have leg status "
                f"!= survivor at threshold == run gate -- the "
                f"scorer disagrees with the runner; do NOT "
                f"publish this curve.")
        curve_rows = [r for r in rows
                      if not r["trial"]["is_demo"]]
        demo_rows = [r for r in rows if r["trial"]["is_demo"]]
        assert len(demo_rows) == 1, (
            f"{leg} leg: {len(demo_rows)} demo trials (want 1)")

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
            return {
                "section_0.4_one_duration": rate_row(
                    k, len(subset), list(by_host.values())),
                "half_duration_alongside": rate_row(
                    kh, len(subset), list(by_host_h.values())),
            }

        by_depth = {}
        for j, depth in enumerate(manifest["depths_frac"]):
            sub = [r for r in curve_rows
                   if r["trial"]["depth_idx"] == j]
            entry = _row_group(sub)
            entry["depth_frac"] = depth
            entry["by_stratum"] = {}
            for s in (2, 3, 4):
                ssub = [r for r in sub
                        if nsec[r["trial"]["tic"]] == s]
                entry["by_stratum"][f"{s}_sector"] = _row_group(
                    ssub)
            by_depth[f"{depth:.4f}"] = entry
        # Aspirational cell: 0.05%, P < 5 d (121 trials).
        asp = [r for r in curve_rows
               if r["trial"]["depth_idx"] == 1
               and r["trial"]["period_d"] < 5.0]
        assert len(asp) == 121, (
            f"aspirational cell has {len(asp)} trials, want 121")
        demo = demo_rows[0]
        d_rec = leg_trials[demo["key"]]
        demo_entry = {
            "tic": demo["trial"]["tic"],
            "depth_frac": demo["trial"]["depth_frac"],
            "period_d": demo["trial"]["period_d"],
            "stitched_cdpp_ppm_2p39h": next(
                h["stitched_cdpp_ppm_2p39h"]
                for h in manifest["hosts"]
                if h["tic"] == demo["trial"]["tic"]),
            "recovered_at_gate": bool(demo["recovers"]),
            "note": ("n=1 DEMONSTRATION reported alongside the "
                     "curve (pre-reg section 2.10) -- candidate "
                     "(c) alone doesn't count."),
            "pass2": d_rec.get("pass2"),
            "pass3": d_rec.get("pass3"),
        }
        out[leg] = {
            "n_trials": len(curve_rows),
            "n_hosts": len({r["trial"]["tic"]
                            for r in curve_rows}),
            "by_depth": by_depth,
            "aspirational_0.05pct_P_lt_5d": _row_group(asp),
            "demo": demo_entry,
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
                    if not m_tr["is_demo"]
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
                f"[p4110-score] NESTING VIOLATION at depth {j}: "
                f"recovery across gates {list(zip(gates_sorted, vals))} "
                f"is not monotone -- the scorer is broken.")
    out["nesting_stitched_9_8_7"] = nesting
    return out


def score_null(manifest_null, run_dir, bars):
    """Score the null legs (stitched primary, single secondary).
    Returns per-leg null rates per 1,000 (overall + stratum)."""
    nsec = {t["tic"]: int(t["n_sectors"])
            for t in manifest_null["trials"]}
    out = {"gate": bars.mes_gate, "calibration": bars.calibration}
    for leg, subdir in (("stitched", "null-p43"),
                        ("single", "null_hosts")):
        recs = _load_host_files(run_dir, subdir)
        if not recs:
            out[leg] = {"n_null_hosts": 0,
                        "note": "no null host files in this run dir"}
            continue
        n_err = sum(1 for r in recs if "error" in r)
        if n_err:
            raise SystemExit(
                f"[p4110-score] {leg} null: {n_err} host files "
                f"carry errors; the null run is incomplete.")
        missing = [t for t in manifest_null["trials"]
                   if t["tic"] not in {r["tic"] for r in recs}]
        if missing:
            raise SystemExit(
                f"[p4110-score] {leg} null: "
                f"{len(missing)} manifest null hosts have no "
                f"host record; the null run is incomplete.")
        by_host = {}
        for r in recs:
            by_host[r["tic"]] = null_survivor_at_gate(r, bars)
        k = sum(by_host.values())
        n = len(by_host)
        entry = {"n_null_hosts": n, "n_false_survivors": k,
                 "rate_per_1000": (1000.0 * k / n if n else None),
                 "by_stratum": {}}
        for s in (2, 3, 4):
            hosts_s = [t for t in by_host if nsec.get(t) == s]
            ks = sum(by_host[t] for t in hosts_s)
            entry["by_stratum"][f"{s}_sector"] = {
                "n": len(hosts_s), "k": ks,
                "rate_per_1000": (1000.0 * ks / len(hosts_s)
                                  if hosts_s else None)}
        out[leg] = entry
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Score the 4.1-10 campaign + null at a "
                    "parameterised MES gate.")
    ap.add_argument("--manifest", required=True,
                    help="finalised p4110_manifest.json")
    ap.add_argument("--null-manifest", default=None,
                    help="p4110_null_manifest.json (null scored "
                         "only if given)")
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--mes-threshold", type=float, default=9.0)
    ap.add_argument("--run-gate", type=float, default=None,
                    help="gate the run used (default: read from "
                         "<run-dir>/p4110_summary.json, else the "
                         "threshold itself)")
    ap.add_argument("--calibration", default="bulk_v5")
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
    curve = score_campaign(manifest, args.run_dir, bars, run_gate)
    curve["tool"] = "bulk/p4110_score.py"
    curve["item"] = "4.1-10 deep-sample curve"
    curve["manifest_sha256"] = _sha(args.manifest)
    curve["run_dir"] = str(args.run_dir)
    if args.null_manifest:
        null_man = json.loads(Path(args.null_manifest).read_text())
        curve["null"] = score_null(null_man, args.run_dir, bars)
        curve["null_manifest_sha256"] = _sha(args.null_manifest)
    out = Path(args.out)
    out.write_text(json.dumps(curve, indent=1, sort_keys=True))
    st = curve["stitched"]["by_depth"]
    print(f"[p4110-score] gate {bars.mes_gate} (run gate "
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
        print(f"[p4110-score] null stitched: "
              f"{nl['n_false_survivors']}/{nl['n_null_hosts']} = "
              f"{nl['rate_per_1000']:.2f}/1,000")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
