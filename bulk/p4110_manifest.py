"""4.1-10 deep-sample curve: manifest builder (Phase 4.1, Stage 4).

Builds the pre-manifest (800 curve trials + 1 demo trial) for the
deep-sample sensitivity curve from the FROZEN rescoped census target
list. The design is pinned by FREEZE_413_4110.md section 2 (adopted
as written by the Stage 4 parent) -- this builder is the mechanical
enforcement of that freeze: every pinned number is asserted, and the
build FAILS LOUDLY on any mismatch. No draw, no re-selection, no
host recycling (C41-5).

Frozen design (FREEZE section 2):
- Hosts: the 49 fresh hosts (2-sec 22, 3-sec 10, 4-sec 17) from
  census_4110_targets_rescope.json post-contratio-cut
  (contratio_cut_pass=true, dev-set excluded). Sorted TIC
  ascending -- NUMERIC order (TICs are strings in the census JSON;
  a lexicographic sort silently gives per-stratum 362/163/275
  instead of 362/162/276).
- Depths: 4 -- 0.03% / 0.05% / 0.08% / 0.12%.
- Trials/depth: 200 exactly. TOTAL curve trials 800. Demo +1 = 801.
- Period grid: 5 periods -- 1.0 / 1.7 / 3.5 / 7.0 / 12.0 d (P4-5's
  grid with 0.8 clipped to the 1.0 range floor).
- Allocation rule (rotation, section 2.3): hosts sorted TIC
  ascending, index h = 0..48. Depths j = 0..3. Periods p = 0..4.
  Base: host h at depth j runs all periods EXCEPT p = (h + j)
  mod 5 (4 trials/host/depth, 784 total). Completion: at depth j,
  hosts h = 4j..4j+3 each run their dropped period as a 5th trial
  (+4/depth). Trial order within a depth: host ascending, then
  periods ascending. Trial index = 200j + position within depth.
- Seed map: curve indices 0-799 -> 41010001-41010800 (master
  41010001 + index); demo index 800 -> 41010801; reserve indices
  801-998 -> 41010802-41010999 (198 seeds, partial re-runs only).
- Demo trial (section 2.4): host TIC 234333416 (quietest fresh
  host, stitched CDPP 143.3 ppm), depth 0.046%, period
  3.1827878 d (TOI-7930.02's period). Run blind end-to-end
  through the same harness and gates; reported alongside the
  curve (n=1, a demonstration -- candidate (c) alone doesn't
  count).
- Epoch/duration (freeze pin, mirroring P4-5): epoch per trial
  drawn from the TRIAL seed -- default_rng(trial_seed),
  Uniform(0, P), ONE draw (periods are a fixed grid, so no
  period draw precedes it); epoch_btjd = t_min_orig +
  epoch_offset_d, where t_min_orig is the ORIGINAL sector's
  FITS t_min. Duration law 2.0*P^(1/3) h. Stitched legs inject
  via the ABSOLUTE epoch_btjd.
- Original sector (freeze pin, this builder): the host's
  earliest sector -- min(sectors). Sector numbers increase with
  time, so this is the first observation. Deterministic, no
  outcome tuning. (S98 is never an original sector: every combo
  containing S98 has a lower sector.)
- ">=200 trials/depth" is OVERALL per depth, NOT per stratum
  (section 2.5). Per-stratum counts are reported consequences.

Spans (t_min/t_max per host-sector) come from the cached FITS
(--cache, Mac) or from a pre-measured spans JSON (--spans, for
VM use and tests). The builder asserts every host has FITS (or
a span entry) for every sector in its list.

Output: the pre-manifest JSON (no `recorded` fields -- those
are attached by bulk/p4110_finalise.py after fresh_pass1
establishment). The campaign manifest is the finalised form.

Usage (Mac):
  python bulk/p4110_manifest.py --census <census_4110_targets_rescope.json> \
      --dev-hosts <dev_hosts_union.json> --cache <bulk/cache> \
      --out <p4110_premanifest.json>
"""
import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np

MASTER_SEED = 41010001
BLOCK_START = 41010000
BLOCK_END = 41010999
DEPTHS = [0.0003, 0.0005, 0.0008, 0.0012]
PERIODS = [1.0, 1.7, 3.5, 7.0, 12.0]
N_TRIALS_PER_DEPTH = 200
N_CURVE_TRIALS = 800
DEMO_INDEX = 800
DEMO_TIC = "234333416"
DEMO_DEPTH_FRAC = 0.00046
DEMO_PERIOD_D = 3.1827878
DEMO_CDPP_PPM = 143.3
# Frozen census facts (FREEZE section 2 / section 4 V-2).
EXPECTED_FRESH = 49
EXPECTED_STRATA = {2: 22, 3: 10, 4: 17}
EXPECTED_DEV_EXCLUDED = {
    "150105613", "237917696", "260000998", "279091106",
    "279616549", "350763476", "55367907",
}
EXPECTED_CONTRATIO_REMOVED = "389925522"
EXPECTED_FIRST_SIX_TICS = [
    "31513988", "31531129", "50491833",
    "141621631", "149538480", "166697936",
]
# Verified consequences of the allocation rule (FREEZE section
# 2.3) -- the builder asserts ALL of these.
EXPECTED_PER_PERIOD_PER_DEPTH = {
    0: [40, 40, 40, 40, 40],
    1: [41, 40, 40, 40, 39],
    2: [40, 41, 40, 40, 39],
    3: [40, 40, 41, 40, 39],
}
EXPECTED_PER_HOST = {16: 33, 17: 16}
EXPECTED_PER_STRATUM = {2: 362, 3: 162, 4: 276}
EXPECTED_PER_STRATUM_PER_DEPTH = {
    2: [90, 90, 90, 92],
    3: [40, 41, 41, 40],
    4: [70, 69, 69, 68],
}
EXPECTED_P_LT_5D_AT_0P05 = 121
# Recorded Phase 3/4 seeds (pre-reg section 0.1): no trial seed
# may equal one. They are outside the 41xxxxxx blocks by
# construction; asserted anyway.
RECORDED_PHASE34_SEEDS = {20261114, 20261115, 20261118}


def _duration_d(period_d):
    return (2.0 * period_d ** (1.0 / 3.0)) / 24.0


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def select_fresh_hosts(targets, dev_set):
    """Select the fresh hosts: contratio_cut_pass=true and TIC
    not in the dev-set union. Returns (hosts, excluded, removed)
    with hosts sorted TIC ascending -- NUMERIC order (TICs are
    strings; a lexicographic sort is the documented silent
    failure: per-stratum 362/163/275 instead of 362/162/276).
    Pure (no frozen-fact asserts) so the selection + sort are
    unit-testable on synthetic data."""
    dev = {str(t) for t in dev_set}
    removed = [t for t in targets
               if not t.get("contratio_cut_pass", True)]
    fresh = [t for t in targets
             if t.get("contratio_cut_pass", True)
             and str(t["tic"]) not in dev]
    excluded = {str(t["tic"]) for t in targets
                if t.get("contratio_cut_pass", True)
                and str(t["tic"]) in dev}
    hosts = sorted(fresh, key=lambda t: int(t["tic"]))
    return hosts, excluded, removed


def load_fresh_hosts(census_path, dev_hosts_path):
    """The frozen 49 fresh hosts, NUMERIC TIC ascending.

    Returns (hosts, census_sha, dev_sha). Asserts the frozen
    census facts (FREEZE section 4 V-2).
    """
    census = json.loads(Path(census_path).read_text())
    dev = {str(t) for t in json.loads(
        Path(dev_hosts_path).read_text())["dev_hosts_union_tic"]}
    assert len(dev) == 132, f"dev hosts {len(dev)} != 132"
    hosts, excluded, removed = select_fresh_hosts(
        census["targets"], dev)
    assert [str(t["tic"]) for t in removed] == [
        EXPECTED_CONTRATIO_REMOVED], (
        f"contratio removals {[t['tic'] for t in removed]} != "
        f"[{EXPECTED_CONTRATIO_REMOVED}]")
    assert excluded == EXPECTED_DEV_EXCLUDED, (
        f"dev-set exclusions {sorted(excluded, key=int)} != "
        f"frozen {sorted(EXPECTED_DEV_EXCLUDED, key=int)}")
    assert len(hosts) == EXPECTED_FRESH, (
        f"fresh hosts {len(hosts)} != {EXPECTED_FRESH}")
    strata = Counter(int(t["n_sectors"]) for t in hosts)
    assert dict(strata) == EXPECTED_STRATA, (
        f"fresh strata {dict(strata)} != {EXPECTED_STRATA}")
    assert [str(t["tic"]) for t in hosts[:6]] == \
        EXPECTED_FIRST_SIX_TICS, (
        f"first six TICs {[t['tic'] for t in hosts[:6]]} != "
        f"{EXPECTED_FIRST_SIX_TICS} -- sort order wrong?")
    demo = [t for t in hosts if str(t["tic"]) == DEMO_TIC]
    assert len(demo) == 1, f"demo host {DEMO_TIC} not in fresh list"
    assert abs(float(demo[0]["stitched_cdpp_ppm_2p39h"])
               - DEMO_CDPP_PPM) < 0.05, (
        f"demo host CDPP {demo[0]['stitched_cdpp_ppm_2p39h']} != "
        f"{DEMO_CDPP_PPM}")
    assert all(float(t["stitched_cdpp_ppm_2p39h"]) > 101.0
               for t in hosts), (
        "a fresh host reaches 101 ppm -- contradicts the frozen "
        "census finding (FREEZE section 2.4)")
    return hosts, _sha(census_path), _sha(dev_hosts_path)


def _allocation(hosts):
    """The rotation rule (FREEZE section 2.3).

    Returns the curve trial specs in depth-major order:
    (depth_idx, host_idx, period_idx) triples, 800 total.
    """
    specs = []
    for j in range(len(DEPTHS)):
        for h in range(len(hosts)):
            dropped = (h + j) % len(PERIODS)
            periods = [p for p in range(len(PERIODS))
                       if p != dropped]
            if 4 * j <= h <= 4 * j + 3:
                # Completion hosts run their dropped period too.
                periods = sorted(periods + [dropped])
            for p in periods:
                specs.append((j, h, p))
    return specs


def _expected_n_events(epoch, period_d, t_min, t_max):
    """Transit centres inside [t_min, t_max] (P3-10 convention)."""
    if period_d <= 0:
        return 0
    first = epoch
    while first - period_d >= t_min:
        first -= period_d
    n = 0
    c = first
    while c <= t_max:
        if c >= t_min:
            n += 1
        c += period_d
    return n


def build_trials(hosts, spans):
    """Build the 800 curve trials + 1 demo trial.

    spans: {tic: {sector: (t_min, t_max)}}. Every host must have
    a span for every sector in its list. Returns the trial list
    in trial-index order (depth-major, then demo at index 800).
    """
    for t in hosts:
        tic = str(t["tic"])
        assert tic in spans, f"no spans for TIC {tic}"
        for sec in t["sectors"]:
            assert str(sec) in spans[tic] or sec in spans[tic], (
                f"no span for TIC {tic} sector {sec}")
    trials = []
    specs = _allocation(hosts)
    assert len(specs) == N_CURVE_TRIALS, (
        f"allocation yields {len(specs)} != {N_CURVE_TRIALS}")
    for idx, (j, h, p) in enumerate(specs):
        host = hosts[h]
        tic = str(host["tic"])
        sectors = sorted(int(s) for s in host["sectors"])
        orig = sectors[0]
        period = PERIODS[p]
        depth = DEPTHS[j]
        seed = MASTER_SEED + idx
        rng = np.random.default_rng(seed)
        off = float(rng.uniform(0.0, period))
        host_spans = {int(s): tuple(v)
                      for s, v in spans[tic].items()}
        t_min_o, t_max_o = host_spans[orig]
        epoch = t_min_o + off
        dur = _duration_d(period)
        n_single = _expected_n_events(epoch, period,
                                      t_min_o, t_max_o)
        n_stitch = sum(
            _expected_n_events(epoch, period, *host_spans[s])
            for s in sectors)
        trials.append({
            "tic": tic, "sector": orig,
            "trial_id": f"d{j}p{p}",
            "trial_index": idx,
            "seed": seed,
            "depth_idx": j, "period_idx": p,
            "period_d": period,
            "epoch_offset_d": off,
            "epoch_btjd": epoch,
            "depth_frac": depth,
            "duration_d": dur,
            "n_events_expected": int(n_single),
            "n_events_expected_stitched": int(n_stitch),
            "n_sectors": len(sectors),
            "sectors": sectors,
            "group": "p4110",
            "is_demo": False,
        })
    # Demo trial (index 800, seed 41010801).
    demo_host = next(t for t in hosts
                     if str(t["tic"]) == DEMO_TIC)
    sectors = sorted(int(s) for s in demo_host["sectors"])
    orig = sectors[0]
    seed = MASTER_SEED + DEMO_INDEX
    rng = np.random.default_rng(seed)
    off = float(rng.uniform(0.0, DEMO_PERIOD_D))
    host_spans = {int(s): tuple(v)
                  for s, v in spans[DEMO_TIC].items()}
    t_min_o, t_max_o = host_spans[orig]
    epoch = t_min_o + off
    dur = _duration_d(DEMO_PERIOD_D)
    trials.append({
        "tic": DEMO_TIC, "sector": orig,
        "trial_id": "demo",
        "trial_index": DEMO_INDEX,
        "seed": seed,
        "depth_idx": None, "period_idx": None,
        "period_d": DEMO_PERIOD_D,
        "epoch_offset_d": off,
        "epoch_btjd": epoch,
        "depth_frac": DEMO_DEPTH_FRAC,
        "duration_d": dur,
        "n_events_expected": int(_expected_n_events(
            epoch, DEMO_PERIOD_D, t_min_o, t_max_o)),
        "n_events_expected_stitched": int(sum(
            _expected_n_events(epoch, DEMO_PERIOD_D,
                               *host_spans[s])
            for s in sectors)),
        "n_sectors": len(sectors),
        "sectors": sectors,
        "group": "p4110_demo",
        "is_demo": True,
    })
    return trials


def assert_manifest(manifest):
    """All FREEZE section 2.3 builder assertions. Fails loudly."""
    trials = manifest["trials"]
    hosts = manifest["hosts"]
    assert len(trials) == N_CURVE_TRIALS + 1, (
        f"TOTAL {len(trials)} != 801")
    curve = [t for t in trials if not t["is_demo"]]
    demo = [t for t in trials if t["is_demo"]]
    assert len(curve) == N_CURVE_TRIALS, len(curve)
    assert len(demo) == 1, len(demo)
    # Per-depth 200.
    per_depth = Counter(t["depth_idx"] for t in curve)
    assert dict(per_depth) == {0: 200, 1: 200, 2: 200, 3: 200}, (
        f"per-depth {dict(per_depth)}")
    # Per-period-per-depth table.
    for j in range(4):
        got = [sum(1 for t in curve
                   if t["depth_idx"] == j and t["period_idx"] == p)
               for p in range(5)]
        assert got == EXPECTED_PER_PERIOD_PER_DEPTH[j], (
            f"depth {j} per-period {got} != "
            f"{EXPECTED_PER_PERIOD_PER_DEPTH[j]}")
    # Per-host totals: 16 (33 hosts), 17 (16 hosts, h = 0..15).
    per_host = Counter(t["tic"] for t in curve)
    assert Counter(per_host.values()) == EXPECTED_PER_HOST, (
        f"per-host totals {dict(Counter(per_host.values()))} != "
        f"{EXPECTED_PER_HOST}")
    host_order = [str(h["tic"]) for h in hosts]
    assert all(per_host[tic] == 17 for tic in host_order[:16]), (
        "hosts h = 0..15 must carry 17 trials each")
    assert all(per_host[tic] == 16 for tic in host_order[16:]), (
        "hosts h = 16..48 must carry 16 trials each")
    # Per-stratum totals + per-stratum per-depth.
    nsec = {str(h["tic"]): int(h["n_sectors"]) for h in hosts}
    per_stratum = Counter(nsec[t["tic"]] for t in curve)
    assert dict(per_stratum) == EXPECTED_PER_STRATUM, (
        f"per-stratum {dict(per_stratum)} != {EXPECTED_PER_STRATUM}")
    for s, expected in EXPECTED_PER_STRATUM_PER_DEPTH.items():
        got = [sum(1 for t in curve
                   if nsec[t["tic"]] == s and t["depth_idx"] == j)
               for j in range(4)]
        assert got == expected, (
            f"stratum {s}-sec per-depth {got} != {expected}")
    # P < 5 d trials at 0.05% = 121.
    n_p5 = sum(1 for t in curve
               if t["depth_idx"] == 1 and t["period_d"] < 5.0)
    assert n_p5 == EXPECTED_P_LT_5D_AT_0P05, (
        f"P<5d at 0.05% {n_p5} != {EXPECTED_P_LT_5D_AT_0P05}")
    # Seeds: master + index, within the block, no cross-block
    # seed, no recorded Phase 3/4 seed.
    for t in trials:
        assert t["seed"] == MASTER_SEED + t["trial_index"], (
            f"trial {t['trial_index']} seed {t['seed']} != "
            f"master + index")
        assert BLOCK_START < t["seed"] <= BLOCK_END, (
            f"seed {t['seed']} outside 4101 block")
        assert t["seed"] // 10000 == 4101, (
            f"seed {t['seed']} outside the 4101 block (no "
            f"cross-block seed: 4.1-3 draws only on 4103)")
        assert t["seed"] not in RECORDED_PHASE34_SEEDS, (
            f"seed {t['seed']} is a recorded Phase 3/4 seed")
    assert [t["trial_index"] for t in trials] == list(
        range(N_CURVE_TRIALS + 1)), "trial indices must be 0..800"
    # Demo pin.
    d = demo[0]
    assert (d["tic"], d["depth_frac"], d["period_d"],
            d["trial_index"], d["seed"]) == (
        DEMO_TIC, DEMO_DEPTH_FRAC, DEMO_PERIOD_D, DEMO_INDEX,
        MASTER_SEED + DEMO_INDEX), f"demo trial mismatch: {d}"
    # Trial-index order: depth-major, host ascending, period
    # ascending within a depth.
    for j in range(4):
        depth_trials = [t for t in curve if t["depth_idx"] == j]
        keys = [(int(t["tic"]), t["period_d"]) for t in depth_trials]
        assert keys == sorted(keys), (
            f"depth {j} trials not in (host, period) order")
        assert [t["trial_index"] for t in depth_trials] == list(
            range(200 * j, 200 * j + 200)), (
            f"depth {j} trial indices not contiguous")
    # Epochs: drawn from the trial seed (re-derive one per depth
    # + the demo -- full re-derivation is the builder's job, this
    # asserts the rule, not every draw).
    for t in curve[::199] + demo:
        rng = np.random.default_rng(t["seed"])
        off = float(rng.uniform(0.0, t["period_d"]))
        assert abs(off - t["epoch_offset_d"]) < 1e-12, (
            f"trial {t['trial_index']} epoch offset not drawn "
            f"from its trial seed")
    return True


def load_spans_from_cache(cache_dir, hosts):
    """Per-host per-sector (t_min, t_max) from cached FITS (Mac).

    Returns {tic: {sector: (t_min, t_max)}}. Asserts every host
    has a FITS file for every sector in its list.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from bulk.inject_real_s96 import load_real_fits
    cache = Path(cache_dir)
    spans = {}
    for host in hosts:
        tic = str(host["tic"])
        spans[tic] = {}
        for sec in host["sectors"]:
            p = cache / f"s{int(sec):04d}" / f"{tic}.fits"
            assert p.exists(), f"missing FITS {p}"
            t, _f, _q, _fcol, _meta = load_real_fits(str(p))
            spans[tic][str(sec)] = (float(np.nanmin(t)),
                                    float(np.nanmax(t)))
    return spans


def assemble_manifest(hosts, trials, census_sha, dev_sha,
                      census_name):
    """Assemble the pre-manifest dict from hosts + trials and
    assert it (all FREEZE section 2.3 assertions). Pure -- the
    CLI and the tests share it."""
    host_recs = [{
        "tic": str(h["tic"]),
        "sectors": sorted(int(s) for s in h["sectors"]),
        "n_sectors": int(h["n_sectors"]),
        "combo": h["combo"],
        "original_sector": min(int(s) for s in h["sectors"]),
        "tmag": h["tmag"],
        "stitched_cdpp_ppm_2p39h": h["stitched_cdpp_ppm_2p39h"],
    } for h in hosts]
    manifest = {
        "tool": "bulk/p4110_manifest.py",
        "item": "4.1-10 deep-sample curve (pre-manifest)",
        "freeze_ref": ("FREEZE_413_4110.md section 2 (adopted as "
                       "written by the Stage 4 parent)"),
        "prereg_ref": "PHASE41_PREREG.md section 2.10",
        "calibration": "bulk_v5",
        "master_seed": MASTER_SEED,
        "seed_block": f"{BLOCK_START}-{BLOCK_END}",
        "seed_derivation": ("per-trial seed = master + "
                            "trial_index; epoch_offset_d ~ "
                            "Uniform(0, P) from "
                            "numpy default_rng(trial_seed), one "
                            "draw; epoch_btjd = t_min_orig + "
                            "epoch_offset_d"),
        "seed_map": {
            "curve_0.03pct": [41010001, 41010200],
            "curve_0.05pct": [41010201, 41010400],
            "curve_0.08pct": [41010401, 41010600],
            "curve_0.12pct": [41010601, 41010800],
            "demo": [41010801, 41010801],
            "reserve_partial_rerun_only": [41010802, 41010999],
        },
        "depths_frac": DEPTHS,
        "periods_d": PERIODS,
        "allocation_rule": ("rotation (FREEZE section 2.3): host "
                            "h at depth j runs all periods except "
                            "p = (h + j) mod 5; at depth j, hosts "
                            "h = 4j..4j+3 also run their dropped "
                            "period"),
        "original_sector_rule": "min(sectors) -- the host's earliest sector",
        "duration_law": "2.0 * P**(1/3) hours",
        "census_file": census_name,
        "census_sha256": census_sha,
        "dev_hosts_sha256": dev_sha,
        "n_hosts": len(hosts),
        "n_trials": len(trials),
        "n_curve_trials": N_CURVE_TRIALS,
        "n_demo_trials": 1,
        "hosts": host_recs,
        "sectors_by_host": {
            str(h["tic"]): sorted(int(s) for s in h["sectors"])
            for h in hosts},
        "trials": trials,
    }
    assert_manifest(manifest)
    return manifest


def build_manifest(census_path, dev_hosts_path, spans,
                   expected_census_sha=None):
    """Build + assert the pre-manifest dict (no I/O besides the
    census/dev-hosts reads)."""
    hosts, census_sha, dev_sha = load_fresh_hosts(
        census_path, dev_hosts_path)
    if expected_census_sha is not None:
        assert census_sha == expected_census_sha, (
            f"census sha {census_sha} != expected "
            f"{expected_census_sha} -- the frozen census file "
            f"changed; do NOT rebuild on a changed census")
    trials = build_trials(hosts, spans)
    return assemble_manifest(hosts, trials, census_sha, dev_sha,
                             Path(census_path).name)


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Build the 4.1-10 pre-manifest (800 curve + "
                    "1 demo trials) from the frozen census.")
    ap.add_argument("--census", required=True)
    ap.add_argument("--dev-hosts", required=True)
    ap.add_argument("--cache", default=None,
                    help="bulk/cache dir (Mac): spans read from "
                         "FITS. Exactly one of --cache/--spans.")
    ap.add_argument("--spans", default=None,
                    help="spans JSON {tic: {sector: [t_min, "
                         "t_max]}} (VM use / tests). Exactly one "
                         "of --cache/--spans.")
    ap.add_argument("--expected-census-sha", default=None)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    if bool(args.cache) == bool(args.spans):
        ap.error("exactly one of --cache / --spans is required")
    hosts, _c, _d = load_fresh_hosts(args.census, args.dev_hosts)
    if args.cache:
        spans = load_spans_from_cache(args.cache, hosts)
    else:
        spans = json.loads(Path(args.spans).read_text())
    manifest = build_manifest(args.census, args.dev_hosts, spans,
                              args.expected_census_sha)
    out = Path(args.out)
    out.write_text(json.dumps(manifest, indent=1, sort_keys=True))
    print(f"wrote {out}: {manifest['n_trials']} trials "
          f"({manifest['n_curve_trials']} curve + 1 demo), "
          f"{manifest['n_hosts']} hosts")
    print("sha256:", _sha(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
