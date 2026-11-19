"""4.1-3 stacked-floor measurement: host draw + exclusion audit.

Draws the 4.1-3 hosts from the S95-S98 4-sector intersection
(6,820 stars) under the pre-reg section 1 procedure: sort the
eligible pool by TIC ascending (numeric); seeded shuffle with
the item's master seed (numpy Generator, version recorded);
take slices from the ordered list; record the full ordered
list as a build artifact, hashed before generation; assert
disjointness for all used positions.

Frozen facts (413-SEED-20261118 + FREEZE_413_4110.md V-8):
- Host pool = the 4-sector intersection, 6,820 stars -- a
  STATED DEVIATION from the section 2.3 P4-5 window (8,665
  stars; 1,845 excluded by TESS sector geometry, 21.3%).
- The window list is p43c_pool_s95s96s97.json (8,665 TICs);
  the intersection is window ∩ S98 pool. Verified here:
  window ∩ S98 == the full-sky S95∩S96∩S97∩S98 == 6,820
  (the bulk-screen caches ARE the Hunter's search footprint).
- Shuffle seed IS the master seed (41030001) -- the shuffle
  seed is the master seed itself, not a ledger trial seed;
  no trial seed is consumed by any draw (413-9b). 41030001
  numerically equals trial 0's seed (413-A7): separate RNG
  instances, no shared state.

Slices of the ordered list (positions are 1-based):
- 1-46: campaign hosts (first run).
- 47-92: re-run reserve (413-9 -- a re-run uses the NEXT 46
  hosts from the same shuffle).
- 93-339: null hosts (247, paired across all 3 intervals).

POOL EXHAUSTION (measured 2026-11-19, see 413_RUN_DESIGN.md
section 1): after all prior draws, only 339 stars remain in
the 6,820-star intersection. The draw asserts the eligible
count is exactly 339 -- a different count means an exclusion
input changed, and the draw refuses loudly.

The 2-sec null supplement (2,000 hosts) is drawn separately
from the S95∩S96 remaining pool (5,993 after exclusions,
minus the 339 ordered-list hosts = 5,654 eligible), by the
same procedure (fresh Generator(MASTER_SEED), first 2,000).

Exclusions (C41-12 -- fresh hosts AND fresh seeds; the draw
must exclude every previously-used host):
- dev_hosts_union.json (132)
- census_4110_targets_rescope.json (57)
- mes412_hosts.json (20) + mes412_null_hosts.json (480)
- p4110_manifest.json campaign TICs (49)
- p4110_null_manifest.json (8,000 -- the REDRAWN list, sha
  b3935801..., NOT the pre-redraw 900fce31...)
- BRIGHT_STAR_LIST_2026-11-19.json (47)
- p43c_fresh_hosts.json (48)
- bp1_hosts.json (7,664: campaign + null, both designs)
- the 4.1-5 control host TIC 259377017
Union: 16,431 distinct TICs (verified 2026-11-19).

Usage (VM -- all inputs are VM-side files):
  python bulk/p413_draw.py --vote-dir <phase41-vote> \
      --out <413-vote/p413_ordered_hosts.json>
"""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

MASTER_SEED = 41030001
VOTE_REF = "413-SEED-20261118"
EXPECTED_WINDOW = 8665
EXPECTED_INTERSECTION = 6820
EXPECTED_ELIGIBLE = 339
EXPECTED_UNION = 16431
EXPECTED_S95S96_REMAINING = 5993
N_CAMPAIGN = 46
N_RESERVE = 46
N_NULL_PAIRED = 247
N_SUPPLEMENT = 2000
CONTROL_TIC = "259377017"
NULL_MANIFEST_SHA = ("b3935801e8b18840ff9c7b1de672a95a42da67b7"
                     "bd66f2bc4b00e32c8c86abca")


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _load_json(path):
    return json.loads(Path(path).read_text())


def _tics_from_hosts_file(path, key):
    d = _load_json(path)
    return {str(h["tic"]) for h in d[key]}


def _tics_from_trials(path):
    d = _load_json(path)
    return {str(t["tic"]) for t in d["trials"]}


def load_exclusions(vote):
    """The C41-12 exclusion set. Returns (union, per-set dict
    with counts + input shas). Fails loudly on any count
    mismatch with the frozen facts."""
    sets = {}
    shas = {}
    dev_p = vote / "dev_hosts_union.json"
    sets["dev_hosts_union"] = {
        str(t) for t in _load_json(dev_p)["dev_hosts_union_tic"]}
    shas["dev_hosts_union"] = _sha(dev_p)
    assert len(sets["dev_hosts_union"]) == 132
    cen_p = vote / "census_4110_targets_rescope.json"
    sets["census_targets"] = _tics_from_hosts_file(cen_p, "targets")
    shas["census_targets"] = _sha(cen_p)
    assert len(sets["census_targets"]) == 57
    m412c_p = vote / "mes412_hosts.json"
    sets["mes412_campaign"] = _tics_from_hosts_file(m412c_p, "hosts")
    shas["mes412_campaign"] = _sha(m412c_p)
    assert len(sets["mes412_campaign"]) == 20
    m412n_p = vote / "mes412_null_hosts.json"
    sets["mes412_null"] = _tics_from_hosts_file(m412n_p, "hosts")
    shas["mes412_null"] = _sha(m412n_p)
    assert len(sets["mes412_null"]) == 480
    c4110_p = vote / "p4110_manifest.json"
    sets["p4110_campaign"] = _tics_from_trials(c4110_p)
    shas["p4110_campaign"] = _sha(c4110_p)
    assert len(sets["p4110_campaign"]) == 49
    n4110_p = vote / "p4110_null_manifest.json"
    assert _sha(n4110_p) == NULL_MANIFEST_SHA, (
        "p4110_null_manifest.json sha mismatch -- the REDRAWN "
        "list (b3935801...) is the operative one, not the "
        "pre-redraw 900fce31... file")
    sets["p4110_null"] = _tics_from_trials(n4110_p)
    shas["p4110_null"] = _sha(n4110_p)
    assert len(sets["p4110_null"]) == 8000
    bs_p = vote / "BRIGHT_STAR_LIST_2026-11-19.json"
    sets["bright_star_list"] = _tics_from_hosts_file(bs_p, "hosts")
    shas["bright_star_list"] = _sha(bs_p)
    assert len(sets["bright_star_list"]) == 47
    p43c_p = vote / "p43c_fresh_hosts.json"
    sets["p43c_fresh"] = _tics_from_hosts_file(p43c_p, "hosts")
    shas["p43c_fresh"] = _sha(p43c_p)
    assert len(sets["p43c_fresh"]) == 48
    bp1_p = vote / "bp1_hosts.json"
    bp1 = _load_json(bp1_p)
    bp1_tics = set()
    for key in ("design1_hosts", "design2_hosts",
                "null_design1_s95", "null_design1_s96",
                "null_design2"):
        bp1_tics |= {str(h["tic"]) for h in bp1[key]}
    sets["bp1_all_draws"] = bp1_tics
    shas["bp1_all_draws"] = _sha(bp1_p)
    assert len(bp1_tics) == 7664, (
        f"BP-1 drawn TICs {len(bp1_tics)} != 7664")
    sets["control"] = {CONTROL_TIC}
    union = set()
    for v in sets.values():
        union |= v
    assert len(union) == EXPECTED_UNION, (
        f"exclusion union {len(union)} != {EXPECTED_UNION} -- "
        f"an exclusion input changed; do NOT draw on a changed "
        f"exclusion set")
    return union, sets, shas


def shuffle_slices(eligible, master_seed, n_campaign=N_CAMPAIGN,
                   n_reserve=N_RESERVE):
    """The pre-reg section 1 shuffle, pure: sort the eligible
    pool by TIC ascending (numeric), shuffle with a fresh
    Generator(master_seed), return (ordered, campaign,
    reserve, null_paired). No ledger trial seed is consumed
    (the shuffle seed is the master seed itself, not a trial
    seed). Unit-testable on synthetic data; the production
    draw calls it on the real eligible pool."""
    ordered = sorted((str(t) for t in eligible), key=int)
    rng = np.random.default_rng(master_seed)
    order = np.array(ordered, dtype=object)
    rng.shuffle(order)
    ordered = [str(t) for t in order]
    campaign = ordered[:n_campaign]
    reserve = ordered[n_campaign:n_campaign + n_reserve]
    null_paired = ordered[n_campaign + n_reserve:]
    return ordered, campaign, reserve, null_paired


def draw_ordered_hosts(vote):
    """Build the ordered list + slices + supplement. Returns
    the draw artifact dict. Pure except for the input reads."""
    pools_p = vote / "p4110_pools.json"
    pools_doc = _load_json(pools_p)
    pools = {int(s): set(v)
             for s, v in pools_doc["pools"].items()}
    pools_sha = _sha(pools_p)
    win_p = vote / "p43c_pool_s95s96s97.json"
    window = {str(t) for t in _load_json(win_p)}
    window_sha = _sha(win_p)
    assert len(window) == EXPECTED_WINDOW, (
        f"window {len(window)} != {EXPECTED_WINDOW}")
    assert window <= (pools[95] & pools[96] & pools[97]), (
        "window is not a subset of S95∩S96∩S97 -- the window "
        "definition changed")
    inter_window = window & pools[98]
    inter_full = pools[95] & pools[96] & pools[97] & pools[98]
    assert len(inter_window) == EXPECTED_INTERSECTION, (
        f"window ∩ S98 = {len(inter_window)} != "
        f"{EXPECTED_INTERSECTION}")
    assert inter_window == inter_full, (
        "window ∩ S98 != full-sky 4-sector intersection -- "
        "the pool definition changed")
    inter = inter_window
    union, sets, shas = load_exclusions(vote)
    eligible = sorted(inter - union, key=int)
    assert len(eligible) == EXPECTED_ELIGIBLE, (
        f"eligible {len(eligible)} != {EXPECTED_ELIGIBLE} -- "
        f"the pool-exhaustion count changed; do NOT draw")
    # The shuffle (pre-reg section 1): a fresh Generator with
    # the master seed. No ledger trial seed is consumed.
    ordered, campaign, reserve, null_paired = shuffle_slices(
        eligible, MASTER_SEED)
    assert len(set(ordered)) == len(ordered) == EXPECTED_ELIGIBLE
    assert len(null_paired) == N_NULL_PAIRED
    # Disjointness for all used positions (413-9a).
    for name, sl in (("campaign", campaign), ("reserve", reserve),
                     ("null_paired", null_paired)):
        assert not (set(sl) & union), (
            f"{name} slice overlaps the exclusion union")
    assert not (set(campaign) & set(reserve)
                | set(campaign) & set(null_paired)
                | set(reserve) & set(null_paired)), (
        "slices overlap -- the shuffle is broken")
    # 2-sec supplement: S95∩S96 remaining, minus the ordered
    # list (disjoint from campaign/reserve/null by design).
    s95s96 = pools[95] & pools[96]
    s95s96_remaining = sorted((s95s96 - union), key=int)
    assert len(s95s96_remaining) == EXPECTED_S95S96_REMAINING, (
        f"S95∩S96 remaining {len(s95s96_remaining)} != "
        f"{EXPECTED_S95S96_REMAINING}")
    supp_pool = sorted(set(s95s96_remaining) - set(ordered),
                       key=int)
    assert len(supp_pool) == (EXPECTED_S95S96_REMAINING
                              - EXPECTED_ELIGIBLE)
    _o2, supplement, _r2, _n2 = shuffle_slices(
        supp_pool, MASTER_SEED, n_campaign=N_SUPPLEMENT,
        n_reserve=0)
    assert len(set(supplement)) == N_SUPPLEMENT
    assert not (set(supplement) & union)
    assert not (set(supplement) & set(ordered))
    ordered_sha = hashlib.sha256(
        "\n".join(ordered).encode()).hexdigest()
    audit = {}
    for name, s in sets.items():
        audit[name] = {"n": len(s),
                       "in_intersection": len(s & inter),
                       "in_window": len(s & window),
                       "sha256": shas.get(name)}  # control: no
        # file (the frozen §2.5 control TIC, a literal)
    return {
        "tool": "bulk/p413_draw.py",
        "item": "4.1-3 stacked-floor measurement (host draw)",
        "amendment_ref": VOTE_REF,
        "master_seed": MASTER_SEED,
        "shuffle_seed": MASTER_SEED,
        "shuffle_seed_note": (
            "The shuffle seed is the master seed itself, not a "
            "ledger trial seed -- no trial seed is consumed by "
            "any draw (413-9b). 41030001 numerically equals "
            "trial 0's seed (413-A7): separate RNG instances, "
            "no shared state."),
        "numpy_version": np.__version__,
        "pools_sha256": pools_sha,
        "window_sha256": window_sha,
        "pool": {"window_n": len(window),
                 "intersection_n": len(inter),
                 "intersection_frac_of_window": len(inter) / len(window),
                 "excluded_by_geometry_n": len(window - inter),
                 "pool_definition": ("S95-S98 4-sector "
                                     "intersection, 6,820 stars -- "
                                     "STATED DEVIATION from the "
                                     "section 2.3 P4-5 window "
                                     "(8,665)")},
        "exclusion_union_n": len(union),
        "exclusion_audit": audit,
        "eligible_n": len(eligible),
        "ordered_hosts": ordered,
        "ordered_hosts_sha256": ordered_sha,
        "slices": {
            "campaign_positions_1_46": campaign,
            "reserve_positions_47_92": reserve,
            "null_paired_positions_93_339": null_paired,
        },
        "supplement_2sec": {
            "pool_n": len(supp_pool),
            "n_drawn": len(supplement),
            "hosts": supplement,
            "pool_definition": ("S95∩S96 remaining after all "
                                "exclusions, minus the 339 "
                                "ordered-list hosts"),
        },
        "disjointness": {
            "campaign_vs_exclusions": 0,
            "reserve_vs_exclusions": 0,
            "null_paired_vs_exclusions": 0,
            "supplement_vs_exclusions": 0,
            "slices_mutually_disjoint": True,
            "supplement_vs_ordered_list": 0,
        },
    }


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="4.1-3 host draw: shuffle the 339 eligible "
                    "intersection stars + the 2-sec supplement.")
    ap.add_argument("--vote-dir", required=True,
                    help="phase41-vote/ (pools + exclusion files)")
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    artifact = draw_ordered_hosts(Path(args.vote_dir))
    out = Path(args.out)
    out.write_text(json.dumps(artifact, indent=1, sort_keys=True))
    print(f"wrote {out}")
    print(f"eligible: {artifact['eligible_n']} "
          f"(campaign 46 + reserve 46 + null 247)")
    print(f"supplement: "
          f"{artifact['supplement_2sec']['n_drawn']} hosts")
    print("ordered_hosts_sha256:",
          artifact["ordered_hosts_sha256"])
    print("sha256:", _sha(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
