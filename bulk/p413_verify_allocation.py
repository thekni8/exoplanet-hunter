"""4.1-3 stacked-floor measurement: allocation verifier.

Standalone, seed-free verification of the 4.1-3 manifests.
Does NOT import the manifest builder -- it re-derives every
frozen number from the manifest + draw artifact + exclusion
files independently. Assigns NO seeds.

Checks (all must PASS):
- manifest: 1,150 trials, 46 hosts, no demo trial
- trial order host-major (host TIC asc, depth asc, period
  asc); indices 0-1149 contiguous
- seeds == 41030001 + index; unique; in block 41030000-
  41032999; // 10000 == 4103; no recorded Phase 3/4 seed
- per-depth 230; per-period-per-depth 46; per-host 25
- aspirational cell (0.05%, P < 5 d) == 138
- epoch offsets re-derived from the trial seeds (ALL trials)
- duration law 2.0*P^(1/3) h (ALL trials)
- event-count consistency (interval counts non-decreasing,
  4-sec == stitched)
- hosts == the draw's campaign slice (positions 1-46),
  sorted TIC asc; draw positions match the ordered list;
  the ordered list's hash matches the draw artifact
- hosts disjoint from the dev set + every exclusion set
  (union re-derived from the vote-dir files)
- null manifest: 2,247 hosts (247 paired + 2,000
  supplement), intervals correct, disjoint from the
  exclusions + campaign + reserve
- seed map endpoints; manifest header fields

Usage (VM):
  python bulk/p413_verify_allocation.py \
      --manifest <p413_manifest.json> \
      --null-manifest <p413_null_manifest.json> \
      --drawn-hosts <p413_ordered_hosts.json> \
      --vote-dir <phase41-vote>
"""
import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

import numpy as np

MASTER = 41030001
BLOCK = (41030000, 41032999)
DEPTHS = [0.0003, 0.0005, 0.0008, 0.0012, 0.002]
PERIODS = [0.8, 1.7, 3.5, 7.0, 12.0]
P34_SEEDS = {20261114, 20261115, 20261118}
CONTROL_TIC = "259377017"

PASS = []
FAIL = []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}"
          + (f" -- {detail}" if detail else ""))
    return ok


def _sha_text(text):
    return hashlib.sha256(text.encode()).hexdigest()


def _tics_from_hosts_file(path, key):
    d = json.loads(Path(path).read_text())
    return {str(h["tic"]) for h in d[key]}


def _tics_from_trials(path):
    d = json.loads(Path(path).read_text())
    return {str(t["tic"]) for t in d["trials"]}


def load_exclusion_union(vote):
    union = set()
    union |= {str(t) for t in json.loads(
        (vote / "dev_hosts_union.json").read_text())
        ["dev_hosts_union_tic"]}
    union |= _tics_from_hosts_file(
        vote / "census_4110_targets_rescope.json", "targets")
    union |= _tics_from_hosts_file(vote / "mes412_hosts.json",
                                   "hosts")
    union |= _tics_from_hosts_file(
        vote / "mes412_null_hosts.json", "hosts")
    union |= _tics_from_trials(vote / "p4110_manifest.json")
    union |= _tics_from_trials(vote / "p4110_null_manifest.json")
    union |= _tics_from_hosts_file(
        vote / "BRIGHT_STAR_LIST_2026-11-19.json", "hosts")
    union |= _tics_from_hosts_file(
        vote / "p43c_fresh_hosts.json", "hosts")
    bp1 = json.loads((vote / "bp1_hosts.json").read_text())
    for key in ("design1_hosts", "design2_hosts",
                "null_design1_s95", "null_design1_s96",
                "null_design2"):
        union |= {str(h["tic"]) for h in bp1[key]}
    union |= {CONTROL_TIC}
    return union


def verify(manifest_path, null_manifest_path, drawn_path,
           vote_dir):
    man = json.loads(Path(manifest_path).read_text())
    trials = man["trials"]
    hosts = man["hosts"]
    drawn = json.loads(Path(drawn_path).read_text())
    vote = Path(vote_dir)

    check("manifest: 1,150 trials", len(trials) == 1150,
          f"got {len(trials)}")
    check("manifest: 46 hosts", len(hosts) == 46,
          f"got {len(hosts)}")
    check("manifest: no demo trial",
          all(not t["is_demo"] for t in trials))
    check("manifest: amendment_ref",
          man.get("amendment_ref") == "413-SEED-20261118",
          f"got {man.get('amendment_ref')!r}")
    check("manifest: block_bounds",
          man.get("block_bounds") == [BLOCK[0], BLOCK[1]],
          f"got {man.get('block_bounds')}")
    check("manifest: trial_index_span",
          man.get("trial_index_span") == [0, 1149])
    check("manifest: host_pool",
          man.get("host_pool") == "S95-S98_intersection_6820",
          f"got {man.get('host_pool')!r}")
    check("manifest: seed_map endpoints",
          man.get("seed_map", {}).get("first_run")
          == [41030001, 41031150]
          and man.get("seed_map", {}).get("re_run_reserve")
          == [41031151, 41032300]
          and man.get("seed_map", {}).get("spare")
          == [41032301, 41032999],
          f"got {man.get('seed_map')}")
    # Trial order + indices + seeds.
    keys = [(int(t["tic"]), t["depth_idx"], t["period_idx"])
            for t in trials]
    check("trials: host-major order (host, depth, period)",
          keys == sorted(keys))
    check("trials: indices 0-1149 contiguous",
          [t["trial_index"] for t in trials]
          == list(range(1150)))
    seeds = [t["seed"] for t in trials]
    check("trials: seeds == master + index",
          seeds == [MASTER + t["trial_index"] for t in trials])
    check("trials: seeds unique",
          len(set(seeds)) == len(seeds))
    check("trials: seeds in block 41030000-41032999",
          all(BLOCK[0] < s <= BLOCK[1] for s in seeds))
    check("trials: seeds in the 4103 block only",
          all(s // 10000 == 4103 for s in seeds))
    check("trials: no recorded Phase 3/4 seed",
          not (set(seeds) & P34_SEEDS))
    # Grid counts.
    per_depth = Counter(t["depth_idx"] for t in trials)
    check("grid: per-depth 230",
          dict(per_depth) == {j: 230 for j in range(5)},
          f"got {dict(per_depth)}")
    per_cell_ok = all(
        sum(1 for t in trials
            if t["depth_idx"] == j and t["period_idx"] == p)
        == 46 for j in range(5) for p in range(5))
    check("grid: per-(depth, period) cell 46", per_cell_ok)
    per_host = Counter(t["tic"] for t in trials)
    check("grid: per-host 25",
          set(per_host.values()) == {25},
          f"got {set(per_host.values())}")
    n_asp = sum(1 for t in trials
                if t["depth_idx"] == 1 and t["period_d"] < 5.0)
    check("grid: aspirational cell (0.05%, P<5d) == 138",
          n_asp == 138, f"got {n_asp}")
    check("grid: depths",
          man.get("depths_frac") == DEPTHS,
          f"got {man.get('depths_frac')}")
    check("grid: periods",
          man.get("periods_d") == PERIODS,
          f"got {man.get('periods_d')}")
    # Epochs + durations re-derived (ALL trials).
    epoch_ok = True
    dur_ok = True
    for t in trials:
        rng = np.random.default_rng(t["seed"])
        off = float(rng.uniform(0.0, t["period_d"]))
        if abs(off - t["epoch_offset_d"]) >= 1e-12:
            epoch_ok = False
            break
    for t in trials:
        want = (2.0 * t["period_d"] ** (1.0 / 3.0)) / 24.0
        if abs(want - t["duration_d"]) >= 1e-12:
            dur_ok = False
            break
    check("epochs: all 1,150 offsets re-derived from seeds",
          epoch_ok)
    check("durations: all follow 2.0*P^(1/3) h", dur_ok)
    # Event-count consistency.
    ev_ok = all(
        t["n_events_expected_by_interval"]["2"]
        <= t["n_events_expected_by_interval"]["3"]
        <= t["n_events_expected_by_interval"]["4"]
        == t["n_events_expected_stitched"]
        for t in trials)
    check("event counts: 2<=3<=4==stitched (all trials)", ev_ok)
    # Hosts vs the draw.
    ordered = [str(t) for t in drawn["ordered_hosts"]]
    check("draw: ordered list hash matches the artifact",
          _sha_text("\n".join(ordered))
          == drawn["ordered_hosts_sha256"])
    campaign = [str(t) for t in drawn["slices"][
        "campaign_positions_1_46"]]
    check("draw: campaign slice == ordered positions 1-46",
          campaign == ordered[:46])
    man_tics = [str(h["tic"]) for h in hosts]
    check("hosts: manifest hosts == campaign slice (sorted)",
          man_tics == sorted(campaign, key=int))
    pos = {tic: i + 1 for i, tic in enumerate(ordered)}
    check("hosts: draw_position matches the ordered list",
          all(h["draw_position"] == pos[str(h["tic"])]
              for h in hosts))
    check("hosts: all 4-sector, original sector 95",
          all(h["sectors"] == [95, 96, 97, 98]
              and h["original_sector"] == 95 for h in hosts))
    # Exclusion audit (union re-derived from the files).
    union = load_exclusion_union(vote)
    check("exclusions: union is 16,431",
          len(union) == 16431, f"got {len(union)}")
    check("exclusions: campaign hosts disjoint (zero overlap)",
          not (set(man_tics) & union),
          f"overlap={len(set(man_tics) & union)}")
    reserve = [str(t) for t in drawn["slices"][
        "reserve_positions_47_92"]]
    check("exclusions: reserve hosts disjoint",
          not (set(reserve) & union))
    # Null manifest.
    null_man = json.loads(Path(null_manifest_path).read_text())
    n_trials = null_man["trials"]
    paired = [t for t in n_trials
              if t["null_source"] == "ordered_positions_93_339"]
    supp = [t for t in n_trials
            if t["null_source"] == "s95s96_supplement"]
    check("null: 2,247 hosts", len(n_trials) == 2247,
          f"got {len(n_trials)}")
    check("null: 247 paired hosts", len(paired) == 247,
          f"got {len(paired)}")
    check("null: 2,000 supplement hosts", len(supp) == 2000,
          f"got {len(supp)}")
    check("null: paired == ordered positions 93-339",
          sorted((t["tic"] for t in paired), key=int)
          == sorted(ordered[92:], key=int))
    check("null: paired intervals [2,3,4]",
          all(t["intervals"] == [2, 3, 4] for t in paired))
    check("null: supplement intervals [2]",
          all(t["intervals"] == [2] for t in supp))
    check("null: supplement sectors [95,96]",
          all(t["sectors"] == [95, 96] for t in supp))
    null_tics = {t["tic"] for t in n_trials}
    check("null: hosts disjoint from exclusions",
          not (null_tics & union),
          f"overlap={len(null_tics & union)}")
    check("null: hosts disjoint from campaign + reserve",
          not (null_tics & set(campaign))
          and not (null_tics & set(reserve)))
    check("null: n_null_trials == 2,741",
          null_man.get("n_null_trials") == 2741,
          f"got {null_man.get('n_null_trials')}")
    check("null: all trials are null_placeholder",
          all(t.get("kind") == "null_placeholder"
              for t in n_trials))
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED:", ", ".join(FAIL))
        raise SystemExit(1)
    print("ALLOCATION VERIFY: PASS")


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Verify the 4.1-3 manifests independently "
                    "(no builder import, no seeds assigned).")
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--null-manifest", required=True)
    ap.add_argument("--drawn-hosts", required=True)
    ap.add_argument("--vote-dir", required=True)
    args = ap.parse_args(argv)
    verify(args.manifest, args.null_manifest, args.drawn_hosts,
           args.vote_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
