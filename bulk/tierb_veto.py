#!/usr/bin/env python3
"""Tier-B single-event veto (S12FIX F8, 5.2 null diagnosis fix #3).

Drops final rows that are tier B with exactly one observed event
(n_events == 1) — SINGLE-SECTOR inputs only. Measured trade-off
(5.2 diagnosis section 8 rank #3; replay_tierb.json): 48 rows on
the single leg at 0/144 final-row planet cost.

SINGLE-LEG ONLY (condition 3a) is load-bearing: the stitched
application is REJECTED by the S12FIX vote — it costs 2/170
planets (220576424:planet03:pass3 and 381977544:planet03:pass2,
both final rows) and kills 220576424:planet03, a mask-rescue
planet the reprieve saves. Enforcement is two-deep: the caller
declares the leg (`leg`, default "single"; any other leg is a
no-op), AND every record is checked against its own content —
a record is vetoed only when it is positively single-sector
(an int `sector` key and no `sectors`/`stitch` keys, the shape
of every one of the 2,720 null_hosts records; stitched records
carry a `sectors` dict). A record that is not positively
single-sector keeps its rows, whatever the caller declared.

R10 CAVEAT (recorded, not hidden): the single-leg 0/144 safety
is weakly tested. Only 1 of the 144 M4 single-leg planets has
ANY tier-B n1 row in its recovery chain (220576424:planet05,
pass-2 row, surviving via its pass-3 tier-A row) — so the veto
was exercised on effectively 1 planet, not 144
(check_3b_exposure.py). A dedicated single-transit safety check
is future work. The veto is demote-not-delete and reversible.

Contract: same discipline as the VSX filter (condition 3c):
post-processing only (never mutates inputs or run dirs), new
dicts, demote-not-delete (a DEMOTED_TIERB_N1 disposition +
audit key with the trigger), fail-closed on leg (ambiguous
records keep their rows). No network, no queries — the rule
reads tier + n_events off the rows themselves.

Enabling by default is gated on the 3d as-adopted-stack replay
(S12FIX F8 condition (iii)): the veto is enabled by default
(`enabled=True`) and BUILD_TIERB.md records the replay verdict.
"""
import argparse
import copy
import json
import sys
from pathlib import Path

import search_health as _search_health
from bulk import pass1_carry as p1c

TIERB_VETO_FLAG = "TIERB_N1"
TIERB_N_EVENTS = 1
TIERB_TIER = "B"

FINAL_PASSES = ("pass2", "pass3", "pass1_carried")


def is_single_sector_record(rec):
    """True iff the record is positively single-sector: an int
    `sector` key and no `sectors` dict / `stitch` key. Stitched
    records carry a `sectors` dict (2,654 of the 2,720 5.2
    null-p43 records also carry `stitch`). Anything else —
    including a record with neither key — is NOT single-sector:
    fail-closed, the veto never touches an ambiguous record."""
    if isinstance(rec.get("sectors"), dict) or "stitch" in rec:
        return False
    sector = rec.get("sector")
    return isinstance(sector, int) and not isinstance(sector, bool)


def is_tierb_n1(row):
    """True iff the row is tier B with exactly one event."""
    return (isinstance(row, dict)
            and row.get("tier") == TIERB_TIER
            and row.get("n_events") == TIERB_N_EVENTS)


def _final_passes(rec):
    """Pass keys with a surviving final row in this record."""
    return [pk for pk in FINAL_PASSES
            if rec.get(f"{pk}_survivor") is True]


def _recompute_final_rows(rec):
    """Recompute final_rows / final_survivor after a demotion
    (the stitched T0-cluster veto's rule: demoting the
    pass-2 partner un-dedupes the carry). Only records that
    already carry the keys are updated."""
    if ("final_rows" not in rec
            and "final_survivor" not in rec):
        return
    carried = rec.get("pass1_carried")
    if not isinstance(carried, dict):
        carried = None
    dur = ((carried or {}).get("duration_hours") or 0) / 24.0
    if carried is not None:
        carried["deduped_with"] = p1c.dedupe_carried(
            carried, rec.get("pass2"), rec.get("pass3"), dur)
    if "final_rows" in rec:
        rec["final_rows"] = p1c.count_final_rows(
            carried, rec.get("pass2"), rec.get("pass3"), dur)
    if "final_survivor" in rec:
        rec["final_survivor"] = bool(
            rec.get("final_rows")
            if "final_rows" in rec
            else _final_passes(rec))


def apply_tierb_veto(records, leg="single", enabled=True):
    """Apply the tier-B single-event veto to host-record dicts.

    `records`: null-leg host records (tic + pass2/pass3/
    pass1_carried rows + *_survivor flags + a `sector` key
    on single-sector records).
    `leg`: the caller's declaration of what the records are.
    Only "single" is vetoed; any other leg is a no-op (the
    stitched application is rejected — 2/170 planet cost).
    `enabled`: False disables the veto (audit-only copies).

    Returns (new_records, summary). Inputs are NOT mutated:
    each record is deep-copied; demoted rows get status
    "demoted", disposition DEMOTED_TIERB_N1, flag TIERB_N1,
    and their survivor flag flipped to False. Every examined
    record carries a `tierb_veto` audit key: the dropped
    passes + the trigger when rows were dropped, an empty
    dropped list when no final row matched, or the reason
    when the record was skipped (disabled, wrong leg, or not
    positively single-sector). Hosts with no final rows are
    not examined and carry no audit key.
    """
    out_records = []
    summary = {"hosts": len(records), "leg": leg,
               "enabled": enabled, "checked": 0,
               "no_final_rows": 0,
               "skipped_not_single_sector": 0,
               "skipped_tics": [],
               "flagged_hosts": 0, "rows_dropped": 0,
               "dropped_pass2": 0, "dropped_pass3": 0,
               "dropped_pass1_carried": 0,
               "dropped_keys": [], "flagged_tics": []}
    if not enabled:
        off_reason = "veto disabled"
    elif leg != "single":
        off_reason = (f"leg is {leg!r}; the tier-B veto "
                      "applies to single-sector inputs only")
    else:
        off_reason = None
    for rec in records:
        new = copy.deepcopy(rec)
        out_records.append(new)
        tic = str(rec.get("tic"))
        final = _final_passes(rec)
        if not final:
            # Nothing to veto; no audit key (the VSX pattern).
            summary["no_final_rows"] += 1
            continue
        if off_reason is not None:
            new["tierb_veto"] = {"applied": False,
                                 "reason": off_reason}
            continue
        if not is_single_sector_record(rec):
            summary["skipped_not_single_sector"] += 1
            summary["skipped_tics"].append(tic)
            new["tierb_veto"] = {
                "applied": False,
                "reason": ("record is not single-sector "
                           "(stitched/multi-sector or "
                           "unconfirmed)")}
            continue
        summary["checked"] += 1
        dropped = []
        for pk in final:
            row = new.get(pk)
            if not is_tierb_n1(row):
                continue
            row["status"] = "demoted"
            row["disposition"] = _search_health.DEMOTED_TIERB_N1
            flags = list(row.get("flags") or [])
            if TIERB_VETO_FLAG not in flags:
                flags.append(TIERB_VETO_FLAG)
            row["flags"] = flags
            new[f"{pk}_survivor"] = False
            dropped.append(pk)
            summary[f"dropped_{pk}"] += 1
            summary["dropped_keys"].append(f"{tic}:{pk}")
        if dropped:
            _recompute_final_rows(new)
            summary["flagged_hosts"] += 1
            summary["rows_dropped"] += len(dropped)
            summary["flagged_tics"].append(tic)
        new["tierb_veto"] = {
            "applied": True,
            "trigger": {"tier": TIERB_TIER,
                        "n_events": TIERB_N_EVENTS},
            "dropped_passes": dropped}
    summary["skipped_tics"] = sorted(summary["skipped_tics"])
    summary["flagged_tics"] = sorted(summary["flagged_tics"])
    summary["dropped_keys"] = sorted(summary["dropped_keys"])
    return out_records, summary


def veto_run_dir(run_dir, subdir, out_dir, leg="single",
                 enabled=True):
    """Read a run dir's host records (run_dir/subdir/*.json),
    apply the veto, and write the vetoed copies + a summary to
    a NEW output dir (out_dir/subdir/*.json +
    out_dir/tierb_veto_summary.json). NEVER writes into the
    run dir: out_dir inside run_dir is refused.
    """
    run_dir = Path(run_dir)
    out_dir = Path(out_dir)
    if out_dir.resolve() == run_dir.resolve() or (
            run_dir.resolve() in out_dir.resolve().parents):
        raise ValueError("out_dir must not be inside run_dir")
    records, paths = [], []
    for p in sorted((run_dir / subdir).glob("*.json")):
        try:
            records.append(json.loads(p.read_text()))
        except ValueError:
            continue
        paths.append(p.name)
    vetoed, summary = apply_tierb_veto(records, leg=leg,
                                       enabled=enabled)
    (out_dir / subdir).mkdir(parents=True, exist_ok=True)
    for name, rec in zip(paths, vetoed):
        (out_dir / subdir / name).write_text(json.dumps(rec))
    summary.update({"run_dir": str(run_dir), "subdir": subdir,
                    "out_dir": str(out_dir)})
    (out_dir / "tierb_veto_summary.json").write_text(
        json.dumps(summary, indent=1))
    return summary


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Tier-B single-event veto (SINGLE-SECTOR "
                    "inputs only): demote final rows that are "
                    "tier B with exactly one event. Writes "
                    "vetoed copies to a NEW output dir; the run "
                    "dir is untouched.")
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--subdir", required=True,
                    help="host-record subdir, e.g. null_hosts")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--leg", default="single",
                    help="declared leg of the records; only "
                         "'single' is vetoed (default: single)")
    ap.add_argument("--disabled", action="store_true",
                    help="veto off: write audit-only copies")
    args = ap.parse_args(argv)
    summary = veto_run_dir(args.run_dir, args.subdir,
                           args.out_dir, leg=args.leg,
                           enabled=not args.disabled)
    print(f"hosts {summary['hosts']} | checked "
          f"{summary['checked']} | flagged "
          f"{summary['flagged_hosts']} | rows dropped "
          f"{summary['rows_dropped']} | skipped "
          f"(not single-sector) "
          f"{summary['skipped_not_single_sector']}")
    print(f"wrote {args.out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
