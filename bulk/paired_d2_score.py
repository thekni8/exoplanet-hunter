#!/usr/bin/env python3
"""Paired-D2 guardrail scorer for the Phase 5 5.2 null campaign
(BP3_TEMPLATE.md §2.3, §5).

Adapted from the FROZEN ELIGFIX E6 scorer
(`science-vet/bulkv6/eligfix-vote/paired_d2_score.py`) — the
frozen file is NOT edited; this module is the adapted copy the
template's §2.3 specifies. It compares an M2 baseline run dir
against a paired run dir (E6's `run_d2_eligfix` for the
backward-compatibility dry-run; the 5.2 run dir at campaign
time) and scores the paired gates (template §5, P1–P5) plus
the D2st tripwire.

Adaptations vs the frozen scorer (BP3_TEMPLATE §2.3, items
1–7; each marked "5.2" below):
  1. `final_rows()` iterates ("pass2", "pass3",
     "pass1_carried") — the 5.1 carried row counts as its own
     per-pass row. Without this the scorer UNDERCOUNTS the
     null side on 5.1 records (BUILD_5_1).
  2. No dedupe in this unit: a carried row counts even when
     it dedupes against a pass-2/3 row (same signal) — the
     guardrail unit is per-pass, the same rule under which
     pass-2 and pass-3 rows from one host already count
     separately. Applying dedupe here would break
     comparability with the 66/74/45 baselines.
  3. The driver's `final_rows` (distinct-row count, dedupe
     applied — written into each 5.1 host record by the null
     legs) is reported alongside the per-pass count as a
     cross-check (`driver_final_rows`).
  4. `true_f2()` iterates the same three passes. A carried
     row takes the copy branch (`carried_from == "pass1"`):
     outcome-changing iff the pass-1 baseline was a
     survivor — True by construction for a carried row, but
     the check is stated and run, not assumed.
  5. `arm_totals()` adds a `pass1_carried_survivors` count.
  6. `row_detail()` works unchanged for the carried row.
  7. Diagnosis-style residual: carried rows' T0s enter the
     epoch clustering exactly as pass-2/3 rows' do (automatic
     — the residual is computed from `final_rows()`).

Further 5.2 adaptations (template §5):
  8. Gate 2 (P2) compares pass-2/3 survivor flags ONLY, not
     `final_survivor`: on 5.1 records `final_survivor`
     includes the carried row, so including it would flag
     every carried row as a discordance. Final-survivor
     discordances are reported separately
     (`final_survivor_discordances`) — expected on 5.1
     records wherever a carried row exists. On pre-5.1
     records `final_survivor` is determined by pass-2/3, so
     this change is a no-op for the E6 dry-run.
  9. Gate 6 adds the D2st tripwire vs the 45-row veto-replay
     baseline (template §5): delta_vs_replay + tripwire band
     (proceed | investigate | back-to-dev).
 10. Gate 6 adds a `carried_rows` block (P4): every carried
     row in the paired finals, with full row_detail — 0
     silent carried rows.

Run-time interpretation notes (not code changes):
  - Gate 3 ("untouched identical") will show diffs on 5.2
    records by design: the 5.1 code adds keys
    (`pass1_carried`, `pass1_carried_survivor`,
    `final_rows`, `alias_veto_carried`) and changes
    `final_survivor` wherever a carried row exists. The
    run-time review attributes every gate-3 diff path to
    the 5.1 additions; any other differing path is an
    unintended change and is investigated. (Same for
    gate 2's `other_diffs`.)
  - Gate 5's `pass` field (true F-2 <= 2) is computed for
    dry-run reproduction only. At 5.2 the F-2 count is a
    diagnostic (P5 / S9), never the judged bar.

Backward-compatibility gate (template §2.3, pre-registered):
the adapted scorer is frozen BEFORE the campaign runs and
dry-run on the E6 paired records (BASE vs PAIRED defaults
below): on pre-5.1 records it must reproduce
`paired_d2_score.json` EXACTLY (74 rows, true F-2 = 3,
diagnosis residual 29 rows). Any deviation is a scorer bug.
"""
import argparse
import json
import glob
import os
import sys
from collections import Counter

# E6 defaults (the dry-run comparison). The 5.2 run passes
# --paired <new run dir> explicitly.
BASE = "/Volumes/NVME/pingu-jobs/bulkv6-m2/run_d2"
PAIRED = "/Volumes/NVME/pingu-jobs/bulkv6-m2/run_d2_eligfix"
OUT = "/Volumes/NVME/pingu-jobs/bulkv6-m2/paired_d2_score.json"
REPLAY_BASELINE_ROWS = 45  # veto-replay baseline (template §5)

# 5.2 (item 1): the guardrail unit's passes, carried row included.
FINAL_PASSES = ("pass2", "pass3", "pass1_carried")

RATIOS = (1.0 / 3.0, 0.5, 2.0 / 3.0, 1.0, 1.5, 2.0, 3.0)
# Keys added by the fix / runtime metadata: ignored in the
# "identical in every field" comparison (documented modulo).
IGNORED_KEYS = {"eligible_via", "seconds"}


def is_eb_flag(f):
    return f.endswith("_EB") or "HARMONIC" in f


def flagged_periods(records):
    out = []
    for rec in records:
        if not rec:
            continue
        p = rec.get("period_days")
        if p is None:
            continue
        flags = [f for f in (rec.get("flags") or []) if is_eb_flag(f)]
        if flags:
            out.append((p, flags))
    return out


def carried_eb_flags(period, flagged, tol=0.01):
    if period is None:
        return []
    matched = set()
    for fp, flags in flagged:
        if not fp:
            continue
        ratio = period / fp
        for h in RATIOS:
            if abs(ratio - h) / h <= tol:
                matched.update(flags)
                break
    return sorted(matched)


def load(d, sub):
    recs = {}
    for f in sorted(glob.glob(os.path.join(d, sub, "*.json"))):
        r = json.load(open(f))
        recs[str(r["tic"])] = r
    return recs


def sector_pass1s(rec):
    return [s.get("pass1") for s in (rec.get("sectors") or {}).values()]


def eq_modulo(a, b, path="", diffs=None):
    """Deep equality ignoring IGNORED_KEYS anywhere. Collects
    differing leaf paths into diffs (list)."""
    if isinstance(a, dict) and isinstance(b, dict):
        keys = (set(a) | set(b)) - IGNORED_KEYS
        ok = True
        for k in sorted(keys):
            if k not in a or k not in b:
                ok = False
                if diffs is not None:
                    diffs.append(f"{path}.{k}: missing one side")
                continue
            if not eq_modulo(a[k], b[k], f"{path}.{k}", diffs):
                ok = False
        return ok
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            if diffs is not None:
                diffs.append(f"{path}: len {len(a)} vs {len(b)}")
            return False
        ok = True
        for i, (x, y) in enumerate(zip(a, b)):
            if not eq_modulo(x, y, f"{path}[{i}]", diffs):
                ok = False
        return ok
    if a != b:
        if diffs is not None:
            diffs.append(f"{path}: {a!r} vs {b!r}")
        return False
    return True


def epoch_clusters(t0s, tol_d=0.125, min_size=1):
    t0s = sorted(t for t in t0s if t is not None)
    clusters = []
    cur = [t0s[0]] if t0s else []
    for t in t0s[1:]:
        if t - cur[-1] <= tol_d:
            cur.append(t)
        else:
            if len(cur) >= min_size:
                clusters.append((cur[0], cur[-1], len(cur)))
            cur = [t]
    if cur and len(cur) >= min_size:
        clusters.append((cur[0], cur[-1], len(cur)))
    return clusters


def final_rows(recs):
    """(tic, pass) -> row dict, per-pass rows (m2_score def).

    5.2 (items 1–2): passes are pass-2, pass-3, and
    pass-1-carried. A carried row counts as its own
    (tic, "pass1_carried") row whenever
    `pass1_carried_survivor` is True — even when it dedupes
    against a pass-2/3 row (same signal). No dedupe in this
    unit: the guardrail unit is per-pass.
    """
    rows = {}
    for tic, r in recs.items():
        for pk in FINAL_PASSES:
            if r.get(f"{pk}_survivor") is True:
                rows[(tic, pk)] = r.get(pk) or {}
    return rows


def driver_final_rows(recs):
    """5.2 (item 3): the driver's distinct-row count as a
    cross-check — the sum of the `final_rows` field the 5.1
    null legs write into each host record (dedupe applied).
    Pre-5.1 records carry no such key: total is None when no
    record has it (not 0 — 0 would be a wrong claim).
    """
    vals = [r["final_rows"] for r in recs.values()
            if r.get("final_rows") is not None]
    return {"total": (sum(vals) if vals else None),
            "n_present": len(vals),
            "n_records": len(recs)}


def true_f2(recs):
    """Scorer-definition count (carried + tier A) and the
    zero-compute TRUE outcome-changing count, per trial.

    Copy (carried_from='pass1'): true iff the stitched pass-1
    baseline was a survivor (the carry is the only demotion).
    Re-screen: true iff the stored flags are entirely carried
    (measured-only == []), i.e. no measured demoting flag.
    Returns (scorer_trials, true_trials, details list).

    5.2 (item 4): the carried row is iterated with the same
    tuple. It takes the copy branch (`carried_from` is
    "pass1" by construction — build_carried_row sets it):
    outcome-changing iff the pass-1 baseline was a survivor.
    That is True by construction for a carried row (the carry
    exists only if pass-1 status is "survivor"), but the
    check is stated and run, not assumed.
    """
    scorer_trials = set()
    true_trials = set()
    details = []
    for tic, r in recs.items():
        flagged = flagged_periods(sector_pass1s(r))
        for pk in FINAL_PASSES:
            prec = r.get(pk) or {}
            if not prec.get("flags_carried_from"):
                continue
            if prec.get("tier") != "A":
                continue
            scorer_trials.add(tic)
            if prec.get("carried_from") == "pass1":
                kind = "copy"
                is_true = r.get("pass1_survivor") is True
                why = ("survivor baseline" if is_true
                       else "baseline already demoted")
            else:
                kind = "rescreen"
                carried = carried_eb_flags(
                    prec.get("period_days"), flagged)
                measured_only = [f for f in (prec.get("flags") or [])
                                 if f not in carried]
                is_true = (measured_only == [])
                why = (f"measured-only={measured_only} "
                       f"carried={carried}")
            if is_true:
                true_trials.add(tic)
            details.append({"tic": tic, "pass": pk, "kind": kind,
                            "true": bool(is_true), "why": why,
                            "period": prec.get("period_days"),
                            "flags": list(prec.get("flags") or [])})
    return scorer_trials, true_trials, details


def arm_totals(recs):
    """5.2 (item 5): per-leg survivor counts, carried included."""
    return {"n": len(recs),
            "pass1_survivors": sum(1 for r in recs.values()
                                   if r.get("pass1_survivor") is True),
            "pass2_survivors": sum(1 for r in recs.values()
                                   if r.get("pass2_survivor") is True),
            "pass3_survivors": sum(1 for r in recs.values()
                                   if r.get("pass3_survivor") is True),
            "pass1_carried_survivors": sum(
                1 for r in recs.values()
                if r.get("pass1_carried_survivor") is True)}


def row_detail(recs, key, affected=None):
    """5.2 (item 6): works unchanged for the carried row (it
    reads r.get(pk)); the masked/stopped sector fields are
    the same host's sectors. Lifted to module level (the
    frozen script nests it in main) so tests can call it."""
    tic, pk = key
    r = recs[tic]
    prec = r.get(pk) or {}
    flagged = flagged_periods(sector_pass1s(r))
    carried = carried_eb_flags(prec.get("period_days"), flagged)
    masked = [s for s, sec in (r.get("sectors") or {}).items()
              if (sec.get("k2_mask") or {}).get("stopped") is False
              and sec.get("k2_mask") is not None]
    stopped = [s for s, sec in (r.get("sectors") or {}).items()
               if (sec.get("k2_mask") or {}).get("stopped")]
    return {"tic": tic, "pass": pk,
            "period_days": prec.get("period_days"),
            "t0_btjd": prec.get("t0_btjd"),
            "depth_percent": prec.get("depth_percent"),
            "sde": prec.get("sde"),
            "n_events": prec.get("n_events"),
            "tier": prec.get("tier"),
            "status": prec.get("status"),
            "flags": list(prec.get("flags") or []),
            "carried_from": prec.get("carried_from"),
            "flags_carried_from": prec.get("flags_carried_from"),
            "in_890_affected": (tic in affected
                                if affected is not None else None),
            "masked_sectors_live": masked,
            "masked_sectors_stopped": stopped,
            "period_matches_flagged_eb": bool(carried),
            "matched_carried_flags": carried}


def tripwire_band(delta):
    """5.2 (item 9): the layered D2st tripwire (template §5)."""
    if abs(delta) <= 3:
        return "proceed"
    if abs(delta) <= 5:
        return "investigate"
    return "back-to-dev"


def main(base_dir=None, paired_dir=None, out_path=None,
         replay_baseline=REPLAY_BASELINE_ROWS):
    base_dir = base_dir or BASE
    paired_dir = paired_dir or PAIRED
    out_path = out_path or OUT
    base_st = load(base_dir, "null-p43")
    pair_st = load(paired_dir, "null-p43")
    base_sg = load(base_dir, "null_hosts")
    pair_sg = load(paired_dir, "null_hosts")
    rep = {"base_dir": base_dir, "paired_dir": paired_dir,
           "replay_baseline_rows": replay_baseline,
           "n_base_stitched": len(base_st),
           "n_paired_stitched": len(pair_st),
           "n_base_single": len(base_sg),
           "n_paired_single": len(pair_sg),
           "tic_sets_equal": (set(base_st) == set(pair_st)
                              and set(base_sg) == set(pair_sg))}

    # --- baseline reproduction (zero-compute R1) ---
    n_flagged = n_flag_inelig = n_flag_elig = 0
    n_flag_elig_masked = 0
    affected = set()
    for tic, r in base_st.items():
        for s, sec in (r.get("sectors") or {}).items():
            p1 = sec.get("pass1") or {}
            if not any(is_eb_flag(f) for f in (p1.get("flags") or [])):
                continue
            n_flagged += 1
            if sec.get("eligible"):
                n_flag_elig += 1
                km = sec.get("k2_mask")
                if km is not None and not km.get("stopped"):
                    n_flag_elig_masked += 1
            else:
                n_flag_inelig += 1
                affected.add(tic)
    rep["baseline_reproduction"] = {
        "flagged_sector_records": n_flagged,
        "flagged_ineligible": n_flag_inelig,
        "flagged_eligible": n_flag_elig,
        "flagged_eligible_live_masked": n_flag_elig_masked,
        "affected_trials_890": len(affected),
        "untouched_trials": len(base_st) - len(affected)}
    rep["affected_tics"] = sorted(affected)

    # --- Gate 1: pass-1 identical (P1) ---
    g1_diffs = []
    g1_epi_diffs = []
    for tic in sorted(base_st):
        b, p = base_st[tic], pair_st[tic]
        if b.get("pass1") != p.get("pass1"):
            g1_diffs.append({"tic": tic, "level": "stitched",
                             "base": b.get("pass1"),
                             "paired": p.get("pass1")})
        for s in (b.get("sectors") or {}):
            bp = (b["sectors"][s] or {}).get("pass1")
            pp = (p.get("sectors") or {}).get(s, {}).get("pass1")
            if bp != pp:
                g1_diffs.append({"tic": tic, "level": f"sector-{s}",
                                 "base": bp, "paired": pp})
            for k in ("ephemeris", "secondary_scan"):
                if (b["sectors"][s] or {}).get(k) != \
                        (p.get("sectors") or {}).get(s, {}).get(k):
                    g1_epi_diffs.append({"tic": tic, "sector": s,
                                         "field": k})
    rep["gate1_pass1_identical"] = {
        "n_compared_hosts": len(base_st),
        "n_pass1_diffs": len(g1_diffs),
        "n_ephemeris_diffs": len(g1_epi_diffs),
        "diffs": g1_diffs[:10], "ephemeris_diffs": g1_epi_diffs[:10],
        "pass": len(g1_diffs) == 0 and len(g1_epi_diffs) == 0}

    # --- Gate 2: D2s pass-2/3 identical (P2) ---
    # 5.2 (item 8): the outcome tuple is pass-2/3 ONLY.
    # final_survivor discordances are reported separately:
    # on 5.1 records they are expected wherever a carried row
    # exists (the carry is additive). On pre-5.1 records
    # final_survivor is determined by pass-2/3, so the
    # separate list equals the outcome list there.
    g2_disc = []
    g2_final_disc = []
    g2_other_diffs = []
    g2_other_paths = Counter()
    for tic in sorted(base_sg):
        b, p = base_sg[tic], pair_sg[tic]
        bo = (b.get("pass2_survivor"), b.get("pass3_survivor"))
        po = (p.get("pass2_survivor"), p.get("pass3_survivor"))
        if bo != po:
            g2_disc.append({"tic": tic, "base": bo, "paired": po})
        if b.get("final_survivor") != p.get("final_survivor"):
            g2_final_disc.append({
                "tic": tic,
                "base": b.get("final_survivor"),
                "paired": p.get("final_survivor"),
                "paired_pass1_carried_survivor":
                    p.get("pass1_carried_survivor")})
        diffs = []
        if not eq_modulo(b, p, "", diffs):
            g2_other_diffs.append({"tic": tic, "diffs": diffs[:5]})
            for d in diffs:
                g2_other_paths[d.split(":")[0]] += 1
    rep["gate2_d2s_identical"] = {
        "n_compared_hosts": len(base_sg),
        "n_outcome_discordances": len(g2_disc),
        "discordances": g2_disc,
        "n_final_survivor_discordances": len(g2_final_disc),
        "final_survivor_discordances": g2_final_disc,
        "n_records_differing_modulo": len(g2_other_diffs),
        "differing_path_counts": dict(g2_other_paths),
        "other_diffs_sample": g2_other_diffs[:5],
        "pass": len(g2_disc) == 0}

    # --- Gate 3: 1,830 untouched trials identical in every field ---
    untouched = [t for t in sorted(base_st) if t not in affected]
    g3_diffs = []
    g3_strict_diff = 0
    for tic in untouched:
        if base_st[tic] != pair_st[tic]:
            g3_strict_diff += 1
        diffs = []
        if not eq_modulo(base_st[tic], pair_st[tic], "", diffs):
            g3_diffs.append({"tic": tic, "diffs": diffs[:8]})
    rep["gate3_untouched_identical"] = {
        "n_untouched": len(untouched),
        "n_differing_strict": g3_strict_diff,
        "n_differing_modulo_eligible_via_seconds": len(g3_diffs),
        "diffs": g3_diffs[:10],
        "pass": len(g3_diffs) == 0}

    # --- Gate 4: >=90% masked or stop reason (paired run) ---
    elig_flagged = []
    for tic, r in pair_st.items():
        for s, sec in (r.get("sectors") or {}).items():
            p1 = sec.get("pass1") or {}
            if not any(is_eb_flag(f) for f in (p1.get("flags") or [])):
                continue
            if not sec.get("eligible"):
                elig_flagged.append({"tic": tic, "sector": s,
                                     "state": "INELIGIBLE?!",
                                     "eligible_via": sec.get("eligible_via"),
                                     "reason": sec.get("reason")})
                continue
            km = sec.get("k2_mask")
            if km is None:
                state = "no-mask-no-reason"
                stop = sec.get("reason")
            elif km.get("stopped"):
                state = "stopped"
                stop = km.get("stop_reason")
            else:
                state = "live-masked"
                stop = None
            elig_flagged.append({"tic": tic, "sector": s,
                                 "state": state, "stop_reason": stop,
                                 "eligible_via": sec.get("eligible_via"),
                                 "reason": sec.get("reason")})
    cnt = Counter(e["state"] for e in elig_flagged)
    via = Counter(e.get("eligible_via") for e in elig_flagged)
    no_reason = [e for e in elig_flagged
                 if e["state"] == "no-mask-no-reason"]
    live = cnt.get("live-masked", 0)
    tot = len(elig_flagged)
    rep["gate4_masked_or_stop"] = {
        "n_eligible_flagged_records": tot,
        "counts": dict(cnt),
        "eligible_via_values": {str(k): v for k, v in via.items()},
        "live_masked_fraction": (live / tot if tot else None),
        "no_mask_no_reason": no_reason[:10],
        "stopped_stop_reasons": dict(Counter(
            e.get("stop_reason") for e in elig_flagged
            if e["state"] == "stopped")),
        "pass": (tot > 0 and live / tot >= 0.90
                 and len(no_reason) == 0)}

    # --- Gate 5: true F-2 (P5 diagnostic at 5.2) ---
    for label, recs in (("base", base_st), ("paired", pair_st)):
        scorer, true, details = true_f2(recs)
        rep[f"gate5_true_f2_{label}"] = {
            "scorer_carried_tierA_trials": len(scorer),
            "true_outcome_changing_trials": len(true),
            "true_tics": sorted(true),
            "true_details": [d for d in details if d["true"]]}
    rep["gate5_true_f2_pass"] = (
        len(rep["gate5_true_f2_paired"]["true_tics"]) <= 2)

    # --- Gate 6: D2st delta (measurement + tripwire) ---
    brows = final_rows(base_st)
    prows = final_rows(pair_st)
    gained = sorted(set(prows) - set(brows))
    lost = sorted(set(brows) - set(prows))
    delta_replay = len(prows) - replay_baseline
    rep["gate6_d2st_delta"] = {
        "base_final_rows": len(brows),
        "paired_final_rows": len(prows),
        "delta": len(prows) - len(brows),
        "base_final_hosts_or": len({t for t, _ in brows}),
        "paired_final_hosts_or": len({t for t, _ in prows}),
        "gained_keys": [[t, p] for t, p in gained],
        "lost_keys": [[t, p] for t, p in lost],
        "delta_vs_replay_baseline": delta_replay,
        "tripwire": tripwire_band(delta_replay)}
    rep["gate6_d2st_delta"]["gained_rows"] = [
        row_detail(pair_st, k, affected) for k in gained]
    rep["gate6_d2st_delta"]["lost_rows"] = [
        row_detail(base_st, k, affected) for k in lost]
    # 5.2 (item 10, P4): every carried row in the paired
    # finals, attributed. 0 on pre-5.1 records.
    carried_keys = sorted(k for k in prows if k[1] == "pass1_carried")
    rep["gate6_d2st_delta"]["carried_rows"] = {
        "n_paired_carried": len(carried_keys),
        "keys": [[t, p] for t, p in carried_keys],
        "details": [row_detail(pair_st, k, affected)
                    for k in carried_keys]}
    # 5.2 (item 3): driver's distinct-row count, cross-check.
    rep["driver_final_rows"] = {
        "base_stitched": driver_final_rows(base_st),
        "paired_stitched": driver_final_rows(pair_st),
        "base_single": driver_final_rows(base_sg),
        "paired_single": driver_final_rows(pair_sg)}
    # Diagnosis-style residual on the finals (context).
    # 5.2 (item 7): carried rows' T0s enter the clustering
    # via final_rows() — no separate handling.
    for label, rows in (("base", brows), ("paired", prows)):
        t0s = [v.get("t0_btjd") for v in rows.values()]
        cl = epoch_clusters(t0s, min_size=3)
        dem = sum(c for _a, _b, c in cl)
        rep[f"diagnosis_residual_{label}"] = {
            "n_clusters_ge3": len(cl), "cluster_sizes":
            [c for _a, _b, c in cl], "residual_rows": len(rows) - dem,
            "residual_per_1000": 1000.0 * (len(rows) - dem) / 2720}

    # Paired arm totals for the record.
    rep["arm_totals_base_stitched"] = arm_totals(base_st)
    rep["arm_totals_paired_stitched"] = arm_totals(pair_st)
    rep["arm_totals_base_single"] = arm_totals(base_sg)
    rep["arm_totals_paired_single"] = arm_totals(pair_sg)

    json.dump(rep, open(out_path, "w"), indent=1)
    print("WROTE", out_path)
    print("gate1 pass:", rep["gate1_pass1_identical"]["pass"],
          "diffs:", rep["gate1_pass1_identical"]["n_pass1_diffs"],
          "epi:", rep["gate1_pass1_identical"]["n_ephemeris_diffs"])
    print("gate2 pass:", rep["gate2_d2s_identical"]["pass"],
          "discord:", rep["gate2_d2s_identical"]["n_outcome_discordances"],
          "final-surv-disc:",
          rep["gate2_d2s_identical"]["n_final_survivor_discordances"],
          "recs-diff-modulo:",
          rep["gate2_d2s_identical"]["n_records_differing_modulo"])
    print("gate3 pass:", rep["gate3_untouched_identical"]["pass"],
          "untouched:", rep["gate3_untouched_identical"]["n_untouched"],
          "diff-modulo:",
          rep["gate3_untouched_identical"]["n_differing_modulo_eligible_via_seconds"],
          "diff-strict:",
          rep["gate3_untouched_identical"]["n_differing_strict"])
    print("gate4:", rep["gate4_masked_or_stop"]["counts"],
          "live-frac:",
          rep["gate4_masked_or_stop"]["live_masked_fraction"],
          "pass:", rep["gate4_masked_or_stop"]["pass"])
    print("gate5 base true F-2:",
          rep["gate5_true_f2_base"]["true_outcome_changing_trials"],
          "scorer:", rep["gate5_true_f2_base"]["scorer_carried_tierA_trials"],
          "| paired true F-2:",
          rep["gate5_true_f2_paired"]["true_outcome_changing_trials"],
          "scorer:",
          rep["gate5_true_f2_paired"]["scorer_carried_tierA_trials"],
          "pass:", rep["gate5_true_f2_pass"])
    print("gate6 delta:", rep["gate6_d2st_delta"]["delta"],
          "base:", rep["gate6_d2st_delta"]["base_final_rows"],
          "paired:", rep["gate6_d2st_delta"]["paired_final_rows"],
          "gained:", len(gained), "lost:", len(lost),
          "delta-vs-replay:",
          rep["gate6_d2st_delta"]["delta_vs_replay_baseline"],
          "tripwire:", rep["gate6_d2st_delta"]["tripwire"])
    print("carried rows (paired finals):",
          rep["gate6_d2st_delta"]["carried_rows"]["n_paired_carried"])
    print("driver final_rows:",
          {k: v["total"]
           for k, v in rep["driver_final_rows"].items()})
    print("baseline repro:", rep["baseline_reproduction"])
    return rep


if __name__ == "__main__":
    ap = argparse.ArgumentParser(
        description="Paired-D2 guardrail scorer (5.2). Defaults "
                    "are the E6 dry-run dirs.")
    ap.add_argument("--base", default=BASE,
                    help="Baseline run dir (default: M2 run_d2)")
    ap.add_argument("--paired", default=PAIRED,
                    help="Paired run dir (default: E6 run_d2_eligfix)")
    ap.add_argument("--out", default=OUT,
                    help="Output JSON path")
    ap.add_argument("--replay-baseline", type=int,
                    default=REPLAY_BASELINE_ROWS,
                    help="Veto-replay baseline rows for the "
                         "tripwire (default 45)")
    args = ap.parse_args()
    main(args.base, args.paired, args.out, args.replay_baseline)
