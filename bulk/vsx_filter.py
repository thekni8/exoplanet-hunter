#!/usr/bin/env python3
"""Nearby-eclipsing VSX filter (5.2 null diagnosis fix #2).

Drops final rows whose host has a VSX variable of type E
(eclipsing binary) at separation 2-30 arcsec — a nearby blend,
NOT the target itself (self-hits, sep < 2", are excluded: a
blanket VSX filter costs 16/170 planets, DIAGNOSIS_5_2_NULL.md
section 5). Measured trade-off (5.2 diagnosis): 5 + 5 rows
removed at 0/170 + 0/144 planet cost.

The blend link is solid for only 1 of the 3 triggering hosts
(31109583: BLS P is the half-harmonic of the VSX E period;
the other two hosts' BLS periods do not match their VSX E
periods) — recorded here and in the build record, not hidden.

Contract: same VSX query.votable route and raw-text parsing as
hunter.py:is_known_in_vsx (astropy's votable parser mangles
VSX string columns — proven 2026-11-09), with hit details
(name, vartype, period, separation) recorded instead of a
bare boolean, as in the 5.2 diagnosis probe
(vsx_query_5_2.py). Separations are recomputed locally
(haversine) — the cone response is NOT distance-sorted.

FAIL OPEN: any network error, timeout, or non-200 keeps the
rows and records the failure — a row is never removed on
ambiguous evidence. Hosts with no coordinates, or no final
rows, are not queried and keep their rows.

Post-processing only: apply_vsx_filter takes host-record
dicts and returns NEW dicts — it never mutates its inputs
and never touches a run dir. filter_run_dir writes the
filtered copies + a summary to a NEW output dir. Demotion
is demote-not-delete (status "demoted", disposition
DEMOTED_VSX_NEARBY_E, flag VSX_NEARBY_E, survivor flags
flipped, final_rows/final_survivor recomputed exactly as
the stitched T0-cluster veto recomputes them), so scorers
reading the filtered records see the filter and the audit
trail (the triggering VSX entry) stays in the record.

Coordinates come from the caller ({tic: {"ra", "dec"}} —
the MAST TIC catalog, as the diagnosis did); this module
does no MAST lookup.

F3 logging conditions (S12FIX, ratified 2026-11-23): the
per-run summary reports hosts queried / flagged / failed; a
failed query is re-queried once before the failure stands
("if failed > 0, re-query before scoring"); every queried
host's VSX result is persisted in the summary's
`query_results` (hits or error, with a UTC timestamp) so
runs re-score offline; and the audit key logs BLS P / VSX P
per dropped pass (logging only — it never changes a
verdict).

Campaign leg (S12FIX F2 runner wiring): apply_vsx_filter_campaign
is the same rule for campaign-leg host records (trials
lists, p43/k3 drivers). The filter acts per host — a
flagged host loses every final trial in every record that
carries it — with each tic queried once across the record
list. The per-pass recovery flags differ by driver
(p2/p3 on the stitched leg, k2/k3 on the single leg); the
adapter reads both stem sets.
"""
import argparse
import copy
import json
import math
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

import search_health as _search_health
from bulk import pass1_carry as p1c

# Same route as hunter.VSX_QUERY_URL — the two must stay in
# sync (the probe's copy is vsx_query_5_2.py VSX_URL).
VSX_QUERY_URL = (
    "https://vsx.aavso.org/index.php?view=query.votable"
    "&coords={ra}+{dec}&size=0.5&unit=2&order=9"
)
_VSX_TR_SPLIT_RE = re.compile(r"<TR\b", re.IGNORECASE)
_VSX_TD_RE = re.compile(r"<TD[^>]*>(.*?)</TD>",
                        re.IGNORECASE | re.DOTALL)
_VSX_TAG_RE = re.compile(r"<[^>]+>")
_VSX_COORD_RE = re.compile(r"(-?\d+\.\d+)\s*,\s*(-?\d+\.\d+)")

# Nearby = a blend, not the target itself. Self-hits
# (sep < 2") are the target's own variability and are NOT
# filtered (blanket VSX costs 16/170 planets).
VSX_NEARBY_MIN_ARCSEC = 2.0
VSX_NEARBY_MAX_ARCSEC = 30.0
# Vartype match is EXACT ("E"): the 5.2 sample's nearby
# eclipsing hits are all vartype "E"; EA/EB/EW subtypes did
# not appear and are NOT included — the measured rule, not
# an extended one.
VSX_ECLIPSING_VARTYPE = "E"
VSX_FILTER_FLAG = "VSX_NEARBY_E"
VSX_QUERY_TIMEOUT_S = 20

FINAL_PASSES = ("pass2", "pass3", "pass1_carried")


def _sep_arcsec(ra1, dec1, ra2, dec2):
    """Great-circle separation in arcseconds (haversine)."""
    p1, p2 = math.radians(dec1), math.radians(dec2)
    dp = p2 - p1
    dl = math.radians(ra2 - ra1)
    a = (math.sin(dp / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2)
    return math.degrees(2 * math.asin(min(1.0, math.sqrt(a)))) * 3600.0


def parse_vsx_hits(text, ra, dec):
    """Parse a VSX query.votable response (raw text) into hit
    dicts {name, vartype, period_days, sep_arcsec}, keeping
    only hits within VSX_NEARBY_MAX_ARCSEC of (ra, dec).

    Cell layout (validated by the 5.2 diagnosis probe):
    cells[1] = name, cells[3] = "ra, dec", cells[4] =
    vartype, cells[11] = period (days, raw string or None).
    Rows with fewer than 12 cells or no parseable coordinate
    cell are skipped.
    """
    hits = []
    for tr in _VSX_TR_SPLIT_RE.split(text)[1:]:
        cells = [_VSX_TAG_RE.sub("", c).strip()
                 for c in _VSX_TD_RE.findall(tr)]
        if len(cells) < 12:
            continue
        m = _VSX_COORD_RE.search(cells[3])
        if not m:
            continue
        sep = _sep_arcsec(float(ra), float(dec),
                          float(m.group(1)), float(m.group(2)))
        if sep <= VSX_NEARBY_MAX_ARCSEC:
            hits.append({"name": cells[1],
                         "vartype": cells[4],
                         "period_days": cells[11] or None,
                         "sep_arcsec": round(sep, 2)})
    return hits


def query_vsx_hits(ra, dec, timeout=VSX_QUERY_TIMEOUT_S,
                   http_get=None):
    """One VSX cone query at (ra, dec). Returns
    {"hits": [...]} on success or {"error": str} on any
    failure (network error, timeout, non-200) — fail-open,
    as hunter.is_known_in_vsx. `http_get` is the seam for
    tests (a fake requests.get); production passes None.
    """
    get = http_get if http_get is not None else requests.get
    try:
        r = get(VSX_QUERY_URL.format(ra=float(ra),
                                     dec=float(dec)),
                timeout=timeout)
        if r.status_code != 200:
            return {"error": f"HTTP {r.status_code}"}
        return {"hits": parse_vsx_hits(r.text, ra, dec)}
    except Exception as exc:  # noqa: BLE001 - fail-open
        return {"error": repr(exc)}


def find_nearby_eclipsing(hits):
    """The nearest VSX hit of vartype E at separation 2-30
    arcsec, or None. Nearest wins when several match (the
    5.2 host 276788366 has three E hits; the 4.9" one is the
    recorded trigger)."""
    best = None
    for h in hits or []:
        if h.get("vartype") != VSX_ECLIPSING_VARTYPE:
            continue
        sep = h.get("sep_arcsec")
        if sep is None:
            continue
        if not (VSX_NEARBY_MIN_ARCSEC <= sep
                <= VSX_NEARBY_MAX_ARCSEC):
            continue
        if best is None or sep < best["sep_arcsec"]:
            best = h
    return best


def _now_iso():
    """UTC timestamp for the query log (F3 persistence)."""
    return datetime.now(timezone.utc).isoformat()


def _query_with_retry(query, ra, dec):
    """One VSX query with the F3 (1c) retry: a failed query is
    re-queried once before the failure stands. Returns
    (result, attempts)."""
    res = query(ra, dec)
    if res.get("error") is not None:
        res = query(ra, dec)
        return res, 2
    return res, 1


def _period_ratio(bls_period_days, vsx_period_days):
    """BLS P / VSX P for the audit key (F3, logging only).
    None when either period is missing, unparseable,
    non-finite, or the VSX period is zero."""
    try:
        bls = float(bls_period_days)
        vsx = float(vsx_period_days)
    except (TypeError, ValueError):
        return None
    if vsx == 0 or not (math.isfinite(bls)
                        and math.isfinite(vsx)):
        return None
    return bls / vsx


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


def apply_vsx_filter(records, coords, query_fn=None):
    """Apply the nearby-E VSX filter to host-record dicts.

    `records`: null-leg host records (tic + pass2/pass3/
    pass1_carried rows + *_survivor flags).
    `coords`: {tic: {"ra": float, "dec": float}} (MAST TIC
    catalog). `query_fn`: (ra, dec) -> {"hits": [...]} or
    {"error": str}; defaults to query_vsx_hits.

    Returns (new_records, summary). Inputs are NOT mutated:
    each record is deep-copied; demoted rows get status
    "demoted", disposition DEMOTED_VSX_NEARBY_E, flag
    VSX_NEARBY_E, and their survivor flag flipped to False.
    Every queried record carries a `vsx_filter` audit key:
    the triggering VSX entry (name, vartype, period,
    separation) when rows were dropped, None when the query
    came back clean, or the failure reason when the query
    failed (rows kept — fail open); the audit key also
    carries the query timestamp (`queried_at`) and, for
    dropped rows, BLS P / VSX P per dropped pass
    (`period_ratios`, logging only). Hosts with no final
    rows are not queried (nothing to filter) and carry no
    audit key. The summary's `query_results` persists every
    queried host's VSX result (hits or error) with its
    timestamp, so a run re-scores offline; a failed query is
    re-queried once before the failure stands (F3 1c), and
    `query_retries` counts the retries.
    """
    query = query_fn if query_fn is not None else query_vsx_hits
    out_records = []
    summary = {"hosts": len(records), "queried": 0,
               "no_coords": 0, "query_failed": 0,
               "query_retries": 0,
               "clean": 0, "flagged_hosts": 0,
               "rows_dropped": 0,
               "dropped_pass2": 0, "dropped_pass3": 0,
               "dropped_pass1_carried": 0,
               "flagged_tics": [], "failed_tics": [],
               "query_results": {}}
    for rec in records:
        new = copy.deepcopy(rec)
        out_records.append(new)
        tic = str(rec.get("tic"))
        final = _final_passes(rec)
        if not final:
            continue  # nothing to filter; no query, no audit
        c = (coords or {}).get(tic)
        if c is None or c.get("ra") is None \
                or c.get("dec") is None:
            summary["no_coords"] += 1
            new["vsx_filter"] = {"applied": False,
                                 "reason": "no coordinates"}
            continue
        res, attempts = _query_with_retry(query, c["ra"], c["dec"])
        if attempts == 2:
            summary["query_retries"] += 1
        summary["queried"] += 1
        queried_at = _now_iso()
        if res.get("error") is not None:
            summary["query_failed"] += 1
            summary["failed_tics"].append(tic)
            summary["query_results"][tic] = {
                "queried_at": queried_at, "attempts": attempts,
                "error": res["error"]}
            new["vsx_filter"] = {"applied": False,
                                 "reason": ("VSX query failed: "
                                            f"{res['error']}"),
                                 "queried_at": queried_at}
            continue
        summary["query_results"][tic] = {
            "queried_at": queried_at, "attempts": attempts,
            "hits": res.get("hits")}
        trigger = find_nearby_eclipsing(res.get("hits"))
        if trigger is None:
            summary["clean"] += 1
            new["vsx_filter"] = {"applied": True,
                                 "trigger": None,
                                 "dropped_passes": [],
                                 "queried_at": queried_at}
            continue
        dropped = []
        for pk in final:
            row = new.get(pk)
            if not isinstance(row, dict):
                continue
            row["status"] = "demoted"
            row["disposition"] = (
                _search_health.DEMOTED_VSX_NEARBY_E)
            flags = list(row.get("flags") or [])
            if VSX_FILTER_FLAG not in flags:
                flags.append(VSX_FILTER_FLAG)
            row["flags"] = flags
            new[f"{pk}_survivor"] = False
            dropped.append(pk)
            summary[f"dropped_{pk}"] += 1
        _recompute_final_rows(new)
        summary["flagged_hosts"] += 1
        summary["rows_dropped"] += len(dropped)
        summary["flagged_tics"].append(tic)
        new["vsx_filter"] = {
            "applied": True,
            "trigger": dict(trigger),
            "dropped_passes": dropped,
            "queried_at": queried_at,
            "period_ratios": {
                pk: _period_ratio(
                    new[pk].get("period_days"),
                    trigger.get("period_days"))
                for pk in dropped}}
    summary["flagged_tics"] = sorted(summary["flagged_tics"])
    summary["failed_tics"] = sorted(summary["failed_tics"])
    return out_records, summary


# Campaign-leg (p43/k3) trial recovery flags. The stitched
# leg (p43 driver) records p2/p3_recovered; the single leg
# (k3 driver) records k2/k3_recovered for the same passes
# (k2 = pass 2, k3 = pass 3); both record
# p1_carried_recovered. A pass counts as recovered when any
# of its stems is True.
_CAMPAIGN_PASS_STEMS = (
    ("pass2", ("p2", "k2")),
    ("pass3", ("p3", "k3")),
    ("pass1_carried", ("p1_carried",)),
)


def trial_is_final(tr):
    """A campaign trial counts as final (has final rows the
    filter can remove) when its final verdict is True or any
    per-pass recovery flag is True (both driver stem sets).
    The final-verdict clause covers records whose per-pass
    flags are absent (pre-5.1 M4 records have no
    p1_carried_recovered); the per-pass clause covers
    inconsistent records where the final verdict was never
    recomputed."""
    if not isinstance(tr, dict):
        return False
    if tr.get("final_recovered") is True:
        return True
    return any(tr.get(f"{s}_recovered") is True
               for _, stems in _CAMPAIGN_PASS_STEMS
               for s in stems)


def _trial_recovered_flags(tr):
    """{pass: bool} recovered flags for one campaign trial,
    across both driver stem sets."""
    return {pk: any(tr.get(f"{s}_recovered") is True
                    for s in stems)
            for pk, stems in _CAMPAIGN_PASS_STEMS}


def apply_vsx_filter_campaign(records, coords, query_fn=None):
    """The nearby-E VSX filter for CAMPAIGN-leg host records
    (trials lists, p43/k3 drivers) — the campaign half of the
    S12FIX F2 runner wiring. Same rule as apply_vsx_filter
    (exact vartype "E", 2-30", nearest wins), same fail-open
    contract, same F3 logging (retry once, persist every
    queried host's result with a timestamp, BLS P / VSX P
    per dropped pass).

    The filter acts per HOST: a flagged host loses every
    final trial in every record that carries it (a host
    appears in both legs' files, so each tic is queried
    ONCE across the whole record list). A lost trial has
    its recovered pass rows demoted (status "demoted",
    disposition DEMOTED_VSX_NEARBY_E, flag VSX_NEARBY_E),
    its recovery + genuine flags cleared (all stems), and
    final_recovered/final_genuine recomputed as the OR of
    what remains (False — the trial is lost). Non-final
    trials are untouched: the filter removes final rows,
    not signals.

    Returns (new_records, summary). Inputs are NOT mutated.
    Each record that had a final trial carries a `vsx_filter`
    audit key: {"applied": bool, "hosts": {tic: {"trigger":
    ...|None, "dropped": [{"trial_id", "pass"}],
    "lost_trials": [trial_id], "queried_at": ...,
    "period_ratios": {"trial_id:pass": ratio}}}} (or an
    error entry when the query failed — rows kept, fail
    open). Records with no final trial carry no audit key.

    Summary units (the null leg's coincide, the campaign
    leg's do not — one tic spans two legs' files): "hosts"
    counts records; "queried" / "no_coords" / "query_failed"
    / "clean" / "flagged_hosts" count TICS (deduped);
    "rows_dropped" / "dropped_pass*" count rows;
    "trials_lost" counts trials whose final_recovered
    flipped True -> False.
    """
    query = query_fn if query_fn is not None else query_vsx_hits
    summary = {"hosts": len(records), "queried": 0,
               "no_coords": 0, "query_failed": 0,
               "query_retries": 0,
               "clean": 0, "flagged_hosts": 0,
               "rows_dropped": 0, "trials_lost": 0,
               "dropped_pass2": 0, "dropped_pass3": 0,
               "dropped_pass1_carried": 0,
               "flagged_tics": [], "failed_tics": [],
               "query_results": {}}
    # First pass: tics with a final trial anywhere. Query
    # each tic once (deduped across records and legs).
    results = {}  # tic -> (res, attempts, queried_at, trigger)
    for rec in records:
        for tr in rec.get("trials") or []:
            if not isinstance(tr, dict):
                continue
            tic = str(tr.get("tic")
                      if tr.get("tic") is not None
                      else rec.get("tic"))
            if tic in results:
                continue
            if not trial_is_final(tr):
                continue
            c = (coords or {}).get(tic)
            if c is None or c.get("ra") is None \
                    or c.get("dec") is None:
                summary["no_coords"] += 1
                results[tic] = (None, 0, None, None)
                continue
            res, attempts = _query_with_retry(query, c["ra"],
                                              c["dec"])
            if attempts == 2:
                summary["query_retries"] += 1
            summary["queried"] += 1
            queried_at = _now_iso()
            if res.get("error") is not None:
                summary["query_failed"] += 1
                summary["failed_tics"].append(tic)
                summary["query_results"][tic] = {
                    "queried_at": queried_at,
                    "attempts": attempts, "error": res["error"]}
                results[tic] = (res, attempts, queried_at, None)
                continue
            summary["query_results"][tic] = {
                "queried_at": queried_at, "attempts": attempts,
                "hits": res.get("hits")}
            trigger = find_nearby_eclipsing(res.get("hits"))
            if trigger is None:
                summary["clean"] += 1
            else:
                summary["flagged_hosts"] += 1
                summary["flagged_tics"].append(tic)
            results[tic] = (res, attempts, queried_at, trigger)
    # Second pass: apply the demotions.
    out_records = []
    for rec in records:
        new = copy.deepcopy(rec)
        out_records.append(new)
        tics = sorted(
            {str(tr.get("tic")
                 if tr.get("tic") is not None
                 else rec.get("tic"))
             for tr in rec.get("trials") or []
             if isinstance(tr, dict) and trial_is_final(tr)})
        if not tics:
            continue  # nothing to filter; no audit key
        audit_hosts = {}
        for tic in tics:
            res, _attempts, queried_at, trigger = results[tic]
            if res is None:
                audit_hosts[tic] = {
                    "applied": False,
                    "reason": "no coordinates"}
                continue
            if res.get("error") is not None:
                audit_hosts[tic] = {
                    "applied": False,
                    "reason": ("VSX query failed: "
                               f"{res['error']}"),
                    "queried_at": queried_at}
                continue
            if trigger is None:
                audit_hosts[tic] = {
                    "applied": True, "trigger": None,
                    "dropped": [], "lost_trials": [],
                    "queried_at": queried_at}
                continue
            dropped, lost, ratios = [], [], {}
            for tr in new.get("trials") or []:
                ttic = str(tr.get("tic")
                           if tr.get("tic") is not None
                           else new.get("tic"))
                if ttic != tic:
                    continue
                if not trial_is_final(tr):
                    continue
                was_final = tr.get("final_recovered") is True
                rec_flags = _trial_recovered_flags(tr)
                for pk, stems in _CAMPAIGN_PASS_STEMS:
                    if not rec_flags[pk]:
                        continue
                    row = tr.get(pk)
                    if isinstance(row, dict):
                        row["status"] = "demoted"
                        row["disposition"] = (
                            _search_health.DEMOTED_VSX_NEARBY_E)
                        flags = list(row.get("flags") or [])
                        if VSX_FILTER_FLAG not in flags:
                            flags.append(VSX_FILTER_FLAG)
                        row["flags"] = flags
                        dropped.append(
                            {"trial_id": tr.get("trial_id"),
                             "pass": pk})
                        ratios[f"{tr.get('trial_id')}:{pk}"] = (
                            _period_ratio(
                                row.get("period_days"),
                                trigger.get("period_days")))
                        summary[f"dropped_{pk}"] += 1
                    for s in stems:
                        if f"{s}_recovered" in tr:
                            tr[f"{s}_recovered"] = False
                        if f"{s}_genuine" in tr:
                            tr[f"{s}_genuine"] = False
                tr["final_recovered"] = bool(any(
                    tr.get(f"{s}_recovered") is True
                    for _, stems in _CAMPAIGN_PASS_STEMS
                    for s in stems))
                tr["final_genuine"] = bool(any(
                    tr.get(f"{s}_genuine") is True
                    for _, stems in _CAMPAIGN_PASS_STEMS
                    for s in stems))
                if was_final and not tr["final_recovered"]:
                    lost.append(tr.get("trial_id"))
                    summary["trials_lost"] += 1
            summary["rows_dropped"] += len(dropped)
            audit_hosts[tic] = {
                "applied": True, "trigger": dict(trigger),
                "dropped": dropped, "lost_trials": lost,
                "queried_at": queried_at,
                "period_ratios": ratios}
        new["vsx_filter"] = {"applied": True,
                             "hosts": audit_hosts}
    summary["flagged_tics"] = sorted(summary["flagged_tics"])
    summary["failed_tics"] = sorted(summary["failed_tics"])
    return out_records, summary


def filter_run_dir(run_dir, subdir, coords, out_dir,
                   query_fn=None):
    """Read a run dir's host records (run_dir/subdir/*.json),
    apply the filter, and write the filtered copies + a
    summary to a NEW output dir (out_dir/subdir/*.json +
    out_dir/vsx_filter_summary.json). NEVER writes into the
    run dir: out_dir inside run_dir is refused.
    """
    run_dir = Path(run_dir)
    out_dir = Path(out_dir)
    if out_dir.resolve() == run_dir.resolve() or (
            run_dir.resolve() in out_dir.resolve().parents):
        raise ValueError("out_dir must not be inside run_dir")
    coords = {str(k): v for k, v in (coords or {}).items()}
    records, paths = [], []
    for p in sorted((run_dir / subdir).glob("*.json")):
        try:
            records.append(json.loads(p.read_text()))
        except ValueError:
            continue
        paths.append(p.name)
    filtered, summary = apply_vsx_filter(records, coords,
                                         query_fn=query_fn)
    (out_dir / subdir).mkdir(parents=True, exist_ok=True)
    for name, rec in zip(paths, filtered):
        (out_dir / subdir / name).write_text(json.dumps(rec))
    summary.update({"run_dir": str(run_dir), "subdir": subdir,
                    "out_dir": str(out_dir)})
    (out_dir / "vsx_filter_summary.json").write_text(
        json.dumps(summary, indent=1))
    return summary


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Nearby-eclipsing VSX filter: drop final "
                    "rows whose host has a VSX type-E variable "
                    "at 2-30 arcsec. Writes filtered copies to "
                    "a NEW output dir; the run dir is untouched.")
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--subdir", required=True,
                    help="host-record subdir, e.g. null-p43")
    ap.add_argument("--coords", required=True,
                    help="JSON {tic: {ra, dec}} (MAST TIC "
                         "catalog)")
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args(argv)
    coords = json.loads(Path(args.coords).read_text())
    summary = filter_run_dir(args.run_dir, args.subdir, coords,
                             args.out_dir)
    print(f"hosts {summary['hosts']} | queried "
          f"{summary['queried']} | flagged "
          f"{summary['flagged_hosts']} | rows dropped "
          f"{summary['rows_dropped']} | query failures "
          f"{summary['query_failed']} (retries "
          f"{summary['query_retries']}) | no coords "
          f"{summary['no_coords']}")
    print(f"wrote {args.out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
