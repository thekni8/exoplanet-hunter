"""4.1-10 deep-sample curve: null manifest builder (Phase 4.1, Stage 4).

Null design (BP-1 pattern, BP1_DESIGN.md section 7): 10x DISTINCT
fresh null hosts, each run ONCE through the existing null legs
(p43_run --mode null / k3_run --mode null). The null legs are
deterministic given host + calibration (no RNG called), so null
trials consume NO ledger seeds (pre-reg section 0.5 / FREEZE
section 0 rule 1).

4.1-10 null (8,000 trials = 10x the 800 curve trials; the demo
is outside the 10x basis, as in BP-1 where the null basis was
the campaign trial count):
- Stratified by sector-count AND sector combo, mirroring the
  curve's frozen host mix (49 fresh hosts): each combo's null
  count is 8,000 x combo_hosts/49, largest-remainder rounded.
  A null host's stack uses exactly its combo's sectors, so the
  null measures the false-survivor rate on the same stack
  shapes as the curve (same baselines, same sector counts).
- Pools: per-sector cached-FITS inventories from the Mac
  (subcommand `inventory`); a combo's pool is the intersection
  of its sectors' inventories (hosts with FITS in ALL combo
  sectors -- whether they also have other sectors' data is
  irrelevant, the stack uses only the combo).
- Draw (pre-reg section 1 procedure, BP-1 pattern): sort the
  eligible pool by TIC ascending (numeric); seeded shuffle with
  a FRESH numpy Generator(MASTER_SEED) per combo; take the
  first N. No ledger seed is consumed by a shuffle.
- Exclusions (section 0.1 + section 0.6 burn rule), applied to
  EVERY draw: dev_hosts_union.json (132) + the census target
  list (57, incl. the contratio-demoted TIC 389925522) +
  p43c_fresh_hosts.json (48) + ALL BP-1 drawn TICs (7,664:
  campaign + null, both designs) + the 4.1-5 control host
  (TIC 259377017, conservative -- a control host must not also
  serve as a null host). Each later combo draw additionally
  excludes every TIC drawn earlier, so all 8,000 null TICs
  are distinct.
- DEPENDENCY (recorded, not hidden): the 4.1-2 MES sweep's 48
  hosts are drawn in Stage 4 and did not exist when this null
  manifest was built. The section 0.1 assertion covers
  whichever draws first (FREEZE section 3): the 4.1-2 draw (and
  the 4.1-3 draw) MUST exclude this null list + the 49 curve
  hosts. The campaign spawn re-verifies disjointness against
  the 4.1-2 list when it exists.

Combo counts (frozen -- largest-remainder of 8,000 x n/49):
  S95+S96+S97+S98: 2776 | S96+S97: 2122 | S95+S96+S97: 980
  S95+S96: 816 | S97+S98: 490 | S96+S97+S98: 327
  S95+S96+S98: 163 | S95+S97: 163 | S95+S97+S98: 163
  Strata: 2-sec 3591, 3-sec 1633, 4-sec 2776. Total 8000.

Usage:
  # On the Mac (inventories from the cache):
  python bulk/p4110_null.py inventory --cache <bulk/cache> \
      --out <p4110_pools.json>
  # On the VM (draw from the copied inventories):
  python bulk/p4110_null.py draw --pools <p4110_pools.json> \
      --dev-hosts <dev_hosts_union.json> \
      --census <census_4110_targets_rescope.json> \
      --p43c-hosts <p43c_fresh_hosts.json> \
      --bp1-hosts <bp1_hosts.json> \
      --extra-exclude-tic 259377017 \
      --out <p4110_null_manifest.json>
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np

MASTER_SEED = 41010001
N_NULL_TRIALS = 8000
# (combo sectors, null count) -- frozen, see module docstring.
# Draw order is this listed order (deterministic, recorded).
COMBO_COUNTS = [
    ((95, 96, 97, 98), 2776),
    ((96, 97), 2122),
    ((95, 96, 97), 980),
    ((95, 96), 816),
    ((97, 98), 490),
    ((96, 97, 98), 327),
    ((95, 96, 98), 163),
    ((95, 97), 163),
    ((95, 97, 98), 163),
]
EXPECTED_STRATA = {2: 3591, 3: 1633, 4: 2776}
SECTORS = (95, 96, 97, 98)


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _combo_label(sectors):
    return "+".join(f"S{s}" for s in sectors)


def inventory(cache_dir):
    """Per-sector cached-FITS TIC inventories.

    Returns {sector: sorted TIC list (str)}. Pure directory
    listing -- no FITS reads.
    """
    cache = Path(cache_dir)
    pools = {}
    for sec in SECTORS:
        d = cache / f"s{sec:04d}"
        assert d.is_dir(), f"missing cache dir {d}"
        tics = sorted(
            (p.name[:-5] for p in d.glob("*.fits")
             if p.name[:-5].isdigit()),
            key=int)
        assert tics, f"empty inventory for sector {sec}"
        pools[str(sec)] = tics
        print(f"sector {sec}: {len(tics)} cached FITS")
    return pools


def _load_exclusions(dev_hosts_path, census_path, p43c_path,
                     bp1_path, extra_tics):
    """The section 0.1 exclusion set. Returns (excluded, counts)."""
    dev = {str(t) for t in json.loads(
        Path(dev_hosts_path).read_text())["dev_hosts_union_tic"]}
    assert len(dev) == 132, f"dev hosts {len(dev)} != 132"
    census = {str(t["tic"]) for t in json.loads(
        Path(census_path).read_text())["targets"]}
    assert len(census) == 57, f"census targets {len(census)} != 57"
    p43c = {str(h["tic"]) for h in json.loads(
        Path(p43c_path).read_text())["hosts"]}
    assert len(p43c) == 48, f"p43c hosts {len(p43c)} != 48"
    bp1 = json.loads(Path(bp1_path).read_text())
    bp1_tics = set()
    for key in ("design1_hosts", "design2_hosts",
                "null_design1_s95", "null_design1_s96",
                "null_design2"):
        bp1_tics |= {str(h["tic"]) for h in bp1[key]}
    assert len(bp1_tics) == 7664, (
        f"BP-1 drawn TICs {len(bp1_tics)} != 7664")
    extra = {str(t) for t in extra_tics}
    counts = {"dev_hosts_union": len(dev), "census_targets": len(census),
              "p43c_fresh": len(p43c), "bp1_all_draws": len(bp1_tics),
              "extra": sorted(extra)}
    return dev | census | p43c | bp1_tics | extra, counts


def _draw(pool, excluded, n, label):
    """Sort eligible by TIC ascending (numeric), shuffle with a
    fresh Generator(MASTER_SEED), take the first n. Returns the
    drawn TICs (str) in shuffle order."""
    eligible = sorted((set(pool) - set(excluded)), key=int)
    assert len(eligible) >= n, (
        f"{label}: eligible {len(eligible)} < {n} -- pool too "
        f"small after exclusions")
    rng = np.random.default_rng(MASTER_SEED)
    order = np.array(eligible, dtype=object)
    rng.shuffle(order)
    drawn = [str(t) for t in order[:n]]
    assert len(set(drawn)) == n, f"{label}: duplicate drawn TIC"
    assert not (set(drawn) & set(excluded)), (
        f"{label}: drawn TIC in exclusions")
    print(f"{label}: pool {len(pool)}, eligible {len(eligible)}, "
          f"drew {n}")
    return drawn


def draw_nulls(pools, excluded):
    """Draw the 8,000 null hosts per COMBO_COUNTS. Returns the
    trial list (dummy trials, BP-1 shape) + per-combo record."""
    trials = []
    combo_record = {}
    drawn_all = set()
    for combo, n in COMBO_COUNTS:
        pool = set(pools[str(combo[0])])
        for sec in combo[1:]:
            pool &= set(pools[str(sec)])
        label = _combo_label(combo)
        drawn = _draw(sorted(pool, key=int),
                      excluded | drawn_all, n, label)
        drawn_all |= set(drawn)
        combo_record[label] = {
            "sectors": list(combo), "n_sectors": len(combo),
            "pool_size": len(pool), "n_drawn": len(drawn)}
        for tic in drawn:
            trials.append({
                "tic": tic, "sector": min(combo),
                "trial_id": "null01", "kind": "null_placeholder",
                "n_sectors": len(combo),
                "sectors": list(combo),
                "combo": label,
            })
    assert len(trials) == sum(n for _c, n in COMBO_COUNTS), (
        f"drew {len(trials)} != table total "
        f"{sum(n for _c, n in COMBO_COUNTS)}")
    assert len({t["tic"] for t in trials}) == len(trials)
    from collections import Counter
    strata = Counter(t["n_sectors"] for t in trials)
    assert dict(strata) == EXPECTED_STRATA, (
        f"null strata {dict(strata)} != {EXPECTED_STRATA}")
    trials.sort(key=lambda t: (t["n_sectors"], int(t["tic"])))
    return trials, combo_record


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="4.1-10 null manifest: inventory + draw.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    inv = sub.add_parser("inventory",
                         help="per-sector FITS inventories (Mac)")
    inv.add_argument("--cache", required=True)
    inv.add_argument("--out", required=True)
    dr = sub.add_parser("draw", help="draw the 8,000 null hosts")
    dr.add_argument("--pools", required=True)
    dr.add_argument("--dev-hosts", required=True)
    dr.add_argument("--census", required=True)
    dr.add_argument("--p43c-hosts", required=True)
    dr.add_argument("--bp1-hosts", required=True)
    dr.add_argument("--extra-exclude-tic", nargs="*", default=[])
    dr.add_argument("--out", required=True)
    args = ap.parse_args(argv)

    if args.cmd == "inventory":
        pools = inventory(args.cache)
        out = {"tool": "bulk/p4110_null.py inventory",
               "cache": str(args.cache),
               "sectors": {s: len(v) for s, v in pools.items()},
               "pools": pools}
        Path(args.out).write_text(json.dumps(out))
        print(f"wrote {args.out}")
        print("sha256:", _sha(args.out))
        return 0

    pools_doc = json.loads(Path(args.pools).read_text())
    pools = pools_doc["pools"]
    assert sum(n for _c, n in COMBO_COUNTS) == N_NULL_TRIALS, (
        "combo table total != 8000 -- the frozen table changed")
    excluded, counts = _load_exclusions(
        args.dev_hosts, args.census, args.p43c_hosts,
        args.bp1_hosts, args.extra_exclude_tic)
    print(f"base exclusions: {len(excluded)} unique "
          f"({counts})")
    trials, combo_record = draw_nulls(pools, excluded)
    manifest = {
        "tool": "bulk/p4110_null.py draw",
        "item": "4.1-10 deep-sample curve null (10x)",
        "freeze_ref": "FREEZE_413_4110.md section 2",
        "prereg_ref": ("PHASE41_PREREG.md sections 0.5, 2.10 "
                       "(null >=10x, seed-free)"),
        "calibration": "bulk_v5",
        "master_seed": MASTER_SEED,
        "seed_note": ("Null trials consume NO ledger seeds (the "
                      "null legs are deterministic). The master "
                      "seed is used ONLY as the shuffle seed, "
                      "per the pre-reg section 1 draw procedure."),
        "numpy_version": np.__version__,
        "pools_sha256": _sha(args.pools),
        "exclusions": counts,
        "n_excluded_unique": len(excluded),
        "null_basis": "10x the 800 curve trials (demo outside)",
        "n_null_trials": len(trials),
        "combo_counts": combo_record,
        "strata": EXPECTED_STRATA,
        "dependency_412_413": (
            "The 4.1-2 (48) and 4.1-3 (46) host draws did not "
            "exist when this null manifest was built. Per "
            "pre-reg section 0.1 / FREEZE section 3, those draws "
            "MUST exclude this null list + the 49 curve hosts; "
            "the campaign spawn re-verifies disjointness against "
            "the 4.1-2 list when it exists."),
        "note": ("Null manifests: one dummy trial per null host "
                 "(tic + sector only). The null legs read only "
                 "tic/sector (+ sectors_by_host for the stack). "
                 "These trials carry NO injection parameters and "
                 "MUST NEVER be run in campaign mode."),
        "sectors_by_host": {t["tic"]: t["sectors"] for t in trials},
        "trials": trials,
    }
    Path(args.out).write_text(json.dumps(manifest, indent=1))
    print(f"wrote {args.out}: {len(trials)} null trials")
    print("sha256:", _sha(args.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
