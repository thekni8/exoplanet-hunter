"""Bright-star injection-recovery curve: manifest builder.

Builds the pre-manifest (800 curve trials, NO demo trial) for the
bright-star sensitivity curve from the cross-checked bright-star
host list (BRIGHT_STAR_LIST_2026-11-19.json + the TOI/VSX
cross-check record). The design is pinned by
BRIGHTSTAR_CURVE_DESIGN.md -- this builder is the mechanical
enforcement of that design: every pinned number is asserted,
and the build FAILS LOUDLY on any mismatch.

Design (BRIGHTSTAR_CURVE_DESIGN.md sections 1-3):
- Hosts: the 41 surviving bright-star hosts (all 4-sector),
  sorted TIC ascending -- NUMERIC order.
- Depths: 4 -- 0.03% / 0.05% / 0.08% / 0.12%.
- Trials/depth: 200 exactly. TOTAL 800. No demo trial.
- Period grid: 5 periods -- 1.0 / 1.7 / 3.5 / 7.0 / 12.0 d.
- Allocation rule (rotation, generalized from 4.1-10 FREEZE
  section 2.3): hosts sorted TIC ascending, index h = 0..40.
  Depths j = 0..3. Periods p = 0..4. Base: host h at depth j
  runs all periods EXCEPT p = (h + j) mod 5 (4 trials/host/
  depth, 164/depth). Completion: C = 200 - 4N = 36 hosts at
  depth j each run their dropped period as a 5th trial
  (+36/depth): the completion hosts are 36 consecutive hosts
  starting at (36j) mod 41, wrapping. Trial order within a
  depth: host ascending, then periods ascending. Trial index
  = 200j + position within depth. (For N = 49 this reduces to
  4.1-10's rule: C = 4, start 4j.)
- Seed map: indices 0-799 -> 41050001-41050800 (master
  41050001 + index); re-run reserve indices 800-1599 ->
  41050801-41051600; spare 41051601-41051999 (399 seeds).
  Block 41050000-41051999 is disjoint from 4101/4102/4103/
  4104/4110 (asserted).
- Epoch/duration (mirroring 4.1-10 / P4-5): epoch per trial
  drawn from the TRIAL seed -- default_rng(trial_seed),
  Uniform(0, P), ONE draw; epoch_btjd = t_min_orig +
  epoch_offset_d, where t_min_orig is the ORIGINAL sector's
  FITS t_min. Duration law 2.0*P^(1/3) h. Stitched legs inject
  via the ABSOLUTE epoch_btjd.
- Original sector: the host's earliest sector -- min(sectors).

Spans (t_min/t_max per host-sector) come from the cached FITS
(--cache, Mac) or from a pre-measured spans JSON (--spans, for
VM use and tests). The builder asserts every host has FITS (or
a span entry) for every sector in its list.

Output: the pre-manifest JSON (no `recorded` fields -- those
are attached by bulk/brightstar_finalise.py after fresh_pass1
establishment). The campaign manifest is the finalised form.

Usage (Mac):
  python bulk/brightstar_manifest.py \
      --bright-list <BRIGHT_STAR_LIST_2026-11-19.json> \
      --crosscheck <brightstar_crosscheck.json> \
      --cache <phase41-brightstar-curve/cache> \
      --out <brightstar_premanifest.json>
"""
import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np

MASTER_SEED = 41050001
BLOCK_START = 41050000
BLOCK_END = 41051999
# Other allocated blocks (pre-reg section 1 + this design note):
# no bright-star seed may fall in any of them.
OTHER_BLOCKS = [
    (41010000, 41011999),  # 4.1-10
    (41020000, 41020999),  # 4.1-2
    (41030000, 41032999),  # 4.1-3
    (41040000, 41040999),  # 4.1-4
    (41100000, 41109999),  # BP-1
]
FIRST_RUN_MAX_INDEX = 799
RE_RUN_MIN_INDEX = 800
RE_RUN_MAX_INDEX = 1599
MAX_INDEX = 1998
DEPTHS = [0.0003, 0.0005, 0.0008, 0.0012]
PERIODS = [1.0, 1.7, 3.5, 7.0, 12.0]
N_TRIALS_PER_DEPTH = 200
N_CURVE_TRIALS = 800
# Pinned host-list facts (BRIGHTSTAR_CURVE_DESIGN.md section 1).
EXPECTED_N_HOSTS = 41
EXPECTED_REMOVED = {
    "150151262", "167303382", "167415965",
    "167719618", "179040880", "277103955",
}
EXPECTED_QUIETEST_TIC = "374862395"
EXPECTED_QUIETEST_CDPP_PPM = 146.52414034156246
EXPECTED_FIRST_SIX_TICS = [
    "30938252", "31311109", "38908399",
    "38908752", "41226271", "41230546",
]
# Verified consequences of the allocation rule (N = 41, C = 36).
EXPECTED_PER_PERIOD_PER_DEPTH = {
    0: [40, 40, 40, 40, 40],
    1: [40, 40, 40, 40, 40],
    2: [40, 40, 40, 40, 40],
    3: [40, 40, 40, 40, 40],
}
EXPECTED_PER_HOST = {19: 20, 20: 21}
EXPECTED_PER_STRATUM = {4: 800}
EXPECTED_P_LT_5D_AT_0P05 = 120
# Recorded Phase 3/4 seeds (pre-reg section 0.1): no trial seed
# may equal one. They are outside the 41xxxxxx blocks by
# construction; asserted anyway.
RECORDED_PHASE34_SEEDS = {20261114, 20261115, 20261118}


def _duration_d(period_d):
    return (2.0 * period_d ** (1.0 / 3.0)) / 24.0


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_surviving_hosts(bright_list_path, crosscheck_path):
    """The 41 surviving hosts, NUMERIC TIC ascending.

    Returns (hosts, bright_sha, crosscheck_sha). Asserts the
    pinned host-list facts (design note section 1).
    """
    bright = json.loads(Path(bright_list_path).read_text())
    cross = json.loads(Path(crosscheck_path).read_text())
    assert set(cross["removed"]) == EXPECTED_REMOVED, (
        f"cross-check removals {sorted(cross['removed'], key=int)} "
        f"!= pinned {sorted(EXPECTED_REMOVED, key=int)}")
    assert cross["n_surviving"] == EXPECTED_N_HOSTS, (
        f"cross-check survivors {cross['n_surviving']} != "
        f"{EXPECTED_N_HOSTS}")
    assert not cross.get("vsx_errors"), (
        f"cross-check has unresolved VSX errors: "
        f"{sorted(cross['vsx_errors'])}")
    surviving = set(cross["surviving_tics"])
    hosts = [h for h in bright["hosts"]
             if str(h["tic"]) in surviving]
    assert len(hosts) == EXPECTED_N_HOSTS, (
        f"surviving hosts {len(hosts)} != {EXPECTED_N_HOSTS}")
    hosts = sorted(hosts, key=lambda h: int(h["tic"]))
    assert all(len(h["sectors"]) == 4 for h in hosts), (
        "not all surviving hosts are 4-sector")
    assert [str(h["tic"]) for h in hosts[:6]] == \
        EXPECTED_FIRST_SIX_TICS, (
        f"first six TICs {[h['tic'] for h in hosts[:6]]} != "
        f"{EXPECTED_FIRST_SIX_TICS} -- sort order wrong?")
    quietest = min(hosts, key=lambda h: float(
        h["stitched_cdpp_ppm_2p39h"]))
    assert str(quietest["tic"]) == EXPECTED_QUIETEST_TIC, (
        f"quietest host {quietest['tic']} != "
        f"{EXPECTED_QUIETEST_TIC}")
    assert abs(float(quietest["stitched_cdpp_ppm_2p39h"])
               - EXPECTED_QUIETEST_CDPP_PPM) < 0.05, (
        f"quietest CDPP "
        f"{quietest['stitched_cdpp_ppm_2p39h']} != "
        f"{EXPECTED_QUIETEST_CDPP_PPM}")
    assert all(float(h["stitched_cdpp_ppm_2p39h"]) > 101.0
               for h in hosts), (
        "a surviving host reaches 101 ppm -- contradicts the "
        "bright-star list finding (0 stars reach 101 ppm)")
    return hosts, _sha(bright_list_path), _sha(crosscheck_path)


def _completion_hosts(n_hosts, n_depths, per_depth):
    """Completion-host sets per depth (generalized rotation).

    C = per_depth - 4 * n_hosts hosts at depth j each run their
    dropped period too: C consecutive hosts starting at
    (C * j) mod N, wrapping. Returns {j: set(h)}.
    """
    comp_n = per_depth - 4 * n_hosts
    assert 0 <= comp_n <= n_hosts, (
        f"completion count {comp_n} outside [0, {n_hosts}] -- "
        f"the rotation rule needs 40 <= N <= 50 for "
        f"200 trials/depth")
    out = {}
    for j in range(n_depths):
        start = (comp_n * j) % n_hosts
        out[j] = {(start + i) % n_hosts for i in range(comp_n)}
    return out


def _allocation(hosts):
    """The rotation rule (design note section 2).

    Returns the curve trial specs in depth-major order:
    (depth_idx, host_idx, period_idx) triples, 800 total.
    """
    n_hosts = len(hosts)
    completion = _completion_hosts(n_hosts, len(DEPTHS),
                                   N_TRIALS_PER_DEPTH)
    specs = []
    for j in range(len(DEPTHS)):
        for h in range(n_hosts):
            dropped = (h + j) % len(PERIODS)
            periods = [p for p in range(len(PERIODS))
                       if p != dropped]
            if h in completion[j]:
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
    """Build the 800 curve trials (no demo trial).

    spans: {tic: {sector: (t_min, t_max)}}. Every host must have
    a span for every sector in its list. Returns the trial list
    in trial-index order (depth-major).
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
            "group": "brightstar",
            "is_demo": False,
        })
    return trials


def assert_manifest(manifest):
    """All design-note section 2 builder assertions. Fails loudly."""
    trials = manifest["trials"]
    hosts = manifest["hosts"]
    assert len(trials) == N_CURVE_TRIALS, (
        f"TOTAL {len(trials)} != 800")
    assert not any(t["is_demo"] for t in trials), (
        "the bright-star run has no demo trial")
    # Per-depth 200.
    per_depth = Counter(t["depth_idx"] for t in trials)
    assert dict(per_depth) == {0: 200, 1: 200, 2: 200, 3: 200}, (
        f"per-depth {dict(per_depth)}")
    # Per-period-per-depth table.
    for j in range(4):
        got = [sum(1 for t in trials
                   if t["depth_idx"] == j and t["period_idx"] == p)
               for p in range(5)]
        assert got == EXPECTED_PER_PERIOD_PER_DEPTH[j], (
            f"depth {j} per-period {got} != "
            f"{EXPECTED_PER_PERIOD_PER_DEPTH[j]}")
    # Per-host totals: 20 (21 hosts, h = 0..20), 19 (20 hosts).
    per_host = Counter(t["tic"] for t in trials)
    assert Counter(per_host.values()) == EXPECTED_PER_HOST, (
        f"per-host totals {dict(Counter(per_host.values()))} != "
        f"{EXPECTED_PER_HOST}")
    host_order = [str(h["tic"]) for h in hosts]
    assert all(per_host[tic] == 20 for tic in host_order[:21]), (
        "hosts h = 0..20 must carry 20 trials each")
    assert all(per_host[tic] == 19 for tic in host_order[21:]), (
        "hosts h = 21..40 must carry 19 trials each")
    # Per-stratum totals: all 4-sector.
    nsec = {str(h["tic"]): int(h["n_sectors"]) for h in hosts}
    per_stratum = Counter(nsec[t["tic"]] for t in trials)
    assert dict(per_stratum) == EXPECTED_PER_STRATUM, (
        f"per-stratum {dict(per_stratum)} != {EXPECTED_PER_STRATUM}")
    # P < 5 d trials at 0.05% = 120.
    n_p5 = sum(1 for t in trials
               if t["depth_idx"] == 1 and t["period_d"] < 5.0)
    assert n_p5 == EXPECTED_P_LT_5D_AT_0P05, (
        f"P<5d at 0.05% {n_p5} != {EXPECTED_P_LT_5D_AT_0P05}")
    # Seeds: master + index, within the 4105 block, disjoint
    # from every other allocated block, no recorded Phase 3/4
    # seed.
    for t in trials:
        assert t["seed"] == MASTER_SEED + t["trial_index"], (
            f"trial {t['trial_index']} seed {t['seed']} != "
            f"master + index")
        assert BLOCK_START < t["seed"] <= BLOCK_END, (
            f"seed {t['seed']} outside 4105 block")
        assert t["seed"] // 10000 == 4105, (
            f"seed {t['seed']} outside the 4105 block (no "
            f"cross-block seed)")
        for lo, hi in OTHER_BLOCKS:
            assert not (lo <= t["seed"] <= hi), (
                f"seed {t['seed']} collides with block "
                f"{lo}-{hi}")
        assert t["seed"] not in RECORDED_PHASE34_SEEDS, (
            f"seed {t['seed']} is a recorded Phase 3/4 seed")
    assert [t["trial_index"] for t in trials] == list(
        range(N_CURVE_TRIALS)), "trial indices must be 0..799"
    # Trial-index order: depth-major, host ascending, period
    # ascending within a depth.
    for j in range(4):
        depth_trials = [t for t in trials if t["depth_idx"] == j]
        keys = [(int(t["tic"]), t["period_d"]) for t in depth_trials]
        assert keys == sorted(keys), (
            f"depth {j} trials not in (host, period) order")
        assert [t["trial_index"] for t in depth_trials] == list(
            range(200 * j, 200 * j + 200)), (
            f"depth {j} trial indices not contiguous")
    # Epochs: drawn from the trial seed (re-derive a sample --
    # full re-derivation is the builder's job, this asserts
    # the rule, not every draw).
    for t in trials[::199]:
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


def _combo_label(sectors):
    return "+".join(f"S{s}" for s in sectors)


def assemble_manifest(hosts, trials, bright_sha, cross_sha,
                      bright_name, cross_name):
    """Assemble the pre-manifest dict from hosts + trials and
    assert it (all design-note section 2 assertions). Pure --
    the CLI and the tests share it."""
    host_recs = [{
        "tic": str(h["tic"]),
        "sectors": sorted(int(s) for s in h["sectors"]),
        "n_sectors": len(h["sectors"]),
        "combo": _combo_label(sorted(int(s) for s in h["sectors"])),
        "original_sector": min(int(s) for s in h["sectors"]),
        "tmag": h["tmag"],
        "stitched_cdpp_ppm_2p39h": h["stitched_cdpp_ppm_2p39h"],
        "rank": h["rank"],
        "sigma_0p05pct_P_lt_5d": h["sigma_0p05pct_P_lt_5d"],
    } for h in hosts]
    manifest = {
        "tool": "bulk/brightstar_manifest.py",
        "item": "bright-star curve (pre-manifest)",
        "design_ref": "BRIGHTSTAR_CURVE_DESIGN.md (2026-11-19)",
        "calibration": "bulk_v5",
        "master_seed": MASTER_SEED,
        "seed_block": f"{BLOCK_START}-{BLOCK_END}",
        "block_bounds": [BLOCK_START, BLOCK_END],
        "trial_index_span": [0, FIRST_RUN_MAX_INDEX],
        "seed_derivation": ("per-trial seed = master + "
                            "trial_index; epoch_offset_d ~ "
                            "Uniform(0, P) from "
                            "numpy default_rng(trial_seed), one "
                            "draw; epoch_btjd = t_min_orig + "
                            "epoch_offset_d"),
        "seed_map": {
            "curve_0.03pct": [41050001, 41050200],
            "curve_0.05pct": [41050201, 41050400],
            "curve_0.08pct": [41050401, 41050600],
            "curve_0.12pct": [41050601, 41050800],
            "re_run_reserve": [41050801, 41051600],
            "spare": [41051601, 41051999],
        },
        "depths_frac": DEPTHS,
        "periods_d": PERIODS,
        "allocation_rule": ("rotation (generalized from 4.1-10 "
                            "FREEZE section 2.3): host h at depth "
                            "j runs all periods except p = (h + "
                            "j) mod 5; at depth j, 36 consecutive "
                            "hosts starting at (36j) mod 41 also "
                            "run their dropped period"),
        "original_sector_rule": "min(sectors) -- the host's earliest sector",
        "duration_law": "2.0 * P**(1/3) hours",
        "bright_list_file": bright_name,
        "bright_list_sha256": bright_sha,
        "crosscheck_file": cross_name,
        "crosscheck_sha256": cross_sha,
        "n_hosts": len(hosts),
        "n_trials": len(trials),
        "n_curve_trials": N_CURVE_TRIALS,
        "n_demo_trials": 0,
        "hosts": host_recs,
        "sectors_by_host": {
            str(h["tic"]): sorted(int(s) for s in h["sectors"])
            for h in hosts},
        "trials": trials,
    }
    assert_manifest(manifest)
    return manifest


def build_manifest(bright_list_path, crosscheck_path, spans):
    """Build + assert the pre-manifest dict (no I/O besides the
    host-list reads)."""
    hosts, bright_sha, cross_sha = load_surviving_hosts(
        bright_list_path, crosscheck_path)
    trials = build_trials(hosts, spans)
    return assemble_manifest(hosts, trials, bright_sha, cross_sha,
                             Path(bright_list_path).name,
                             Path(crosscheck_path).name)


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Build the bright-star pre-manifest (800 "
                    "curve trials, no demo) from the "
                    "cross-checked host list.")
    ap.add_argument("--bright-list", default=None)
    ap.add_argument("--crosscheck", default=None)
    ap.add_argument("--cache", default=None,
                    help="run-dir cache (Mac): spans read from "
                         "FITS. Exactly one of --cache/--spans.")
    ap.add_argument("--spans", default=None,
                    help="spans JSON {tic: {sector: [t_min, "
                         "t_max]}} (VM use / tests). Exactly one "
                         "of --cache/--spans.")
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)
    if not args.bright_list or not args.crosscheck or not args.out:
        ap.error("--bright-list, --crosscheck and --out are "
                 "required")
    if bool(args.cache) == bool(args.spans):
        ap.error("exactly one of --cache / --spans is required")
    hosts, _b, _c = load_surviving_hosts(args.bright_list,
                                         args.crosscheck)
    if args.cache:
        spans = load_spans_from_cache(args.cache, hosts)
    else:
        spans = json.loads(Path(args.spans).read_text())
    manifest = build_manifest(args.bright_list, args.crosscheck,
                              spans)
    out = Path(args.out)
    out.write_text(json.dumps(manifest, indent=1, sort_keys=True))
    print(f"wrote {out}: {manifest['n_trials']} trials "
          f"({manifest['n_curve_trials']} curve, 0 demo), "
          f"{manifest['n_hosts']} hosts")
    print("sha256:", _sha(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
