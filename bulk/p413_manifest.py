"""4.1-3 stacked-floor measurement: manifest builder (Phase 4.1).

Builds the pre-manifest (1,150 trials) for the stacked-floor
measurement on the P4-5 population definition with FRESH hosts.
The design is pinned by pre-reg section 2.3 + amendment
413-SEED-20261118 -- this builder is the mechanical enforcement
of that freeze: every pinned number is asserted, and the build
FAILS LOUDLY on any mismatch.

Frozen design (pre-reg section 2.3 + 413 vote):
- Hosts: the 46 campaign hosts (positions 1-46 of the ordered
  shuffle in p413_ordered_hosts.json), sorted TIC ascending --
  NUMERIC order. Every host has S95+S96+S97+S98 coverage.
- Depths: 5 -- 0.03% / 0.05% / 0.08% / 0.12% / 0.20%.
- Periods: 5 -- 0.8 / 1.7 / 3.5 / 7.0 / 12.0 d (the P4-5 grid).
- Trials: 46 hosts x 5 depths x 5 periods = 1,150. NO demo.
- Trial order: HOST-MAJOR (mirrors p45_manifest.json): host
  TIC-ascending, then depth index 0-4, then period index 0-4.
  trial_index = host_idx * 25 + depth_idx * 5 + period_idx.
- Seed map: first-run indices 0-1149 -> 41030001-41031150
  (master 41030001 + index); re-run reserve 1150-2299 ->
  41031151-41032300; spare 2300-2998 -> 41032301-41032999
  (699 seeds, "spare seeds are not an allowance" -- 413-A12;
  a third full run needs a new section 7 vote, BA-2).
- Epoch/duration (mirroring P4-5): epoch per trial drawn from
  the TRIAL seed -- default_rng(trial_seed), Uniform(0, P),
  ONE draw; epoch_btjd = t_min_orig + epoch_offset_d, where
  t_min_orig is the ORIGINAL sector's (S95) FITS t_min.
  Duration law 2.0*P**(1/3) h. Stitched intervals inject via
  the ABSOLUTE epoch_btjd.
- Original sector: S95 for every host (min(sectors)).
- Intervals (2/3/4 sectors) re-read the SAME trials -- no new
  seeds per interval. The runner (bulk/p413_run.py) applies
  the interval's sector set; this manifest carries the
  canonical 4-sector lists + per-interval event counts.

The builder enforces the amendment guard (413-7, mirroring
413-vote/p413_amendment_guard.py -- the vote-dir file is the
reference; this inline copy follows the p4110 pattern and is
independently verified by 413_amendment_gate.py --post):
requires --amendment-ref 413-SEED-20261118 + --block-end
41032999; asserts master 41030001; blocks trial_index > 1149
without a logged section 0.6 burn entry; blocks > 2998
always; stamps the manifest header.

Spans (t_min/t_max per host-sector) come from the cached FITS
(--cache, Mac) or from a pre-measured spans JSON (--spans, for
VM use and tests). The builder asserts every host has FITS (or
a span entry) for every sector in its list.

Output: the pre-manifest JSON (no `recorded` fields -- those
are attached by bulk/p413_finalise.py after fresh_pass1
establishment). The campaign manifest is the finalised form.

Usage (Mac):
  python bulk/p413_manifest.py --drawn-hosts <p413_ordered_hosts.json> \
      --dev-hosts <dev_hosts_union.json> \
      --prereg <PHASE41_PREREG.md> --amendment-ref 413-SEED-20261118 \
      --block-end 41032999 --cache <bulk/cache> \
      --out <p413_premanifest.json>
"""
import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

import numpy as np

MASTER_SEED = 41030001
BLOCK_START = 41030000
BLOCK_END = 41032999
VOTE_REF = "413-SEED-20261118"
FIRST_RUN_MAX_INDEX = 1149
RE_RUN_MIN_INDEX = 1150
RE_RUN_MAX_INDEX = 2299
MAX_INDEX = 2998
HOST_POOL = "S95-S98_intersection_6820"
DEPTHS = [0.0003, 0.0005, 0.0008, 0.0012, 0.002]
PERIODS = [0.8, 1.7, 3.5, 7.0, 12.0]
SECTORS = [95, 96, 97, 98]
INTERVALS = {2: [95, 96], 3: [95, 96, 97], 4: [95, 96, 97, 98]}
N_HOSTS = 46
N_TRIALS = 1150
EXPECTED_PER_DEPTH = 230
EXPECTED_PER_PERIOD_PER_DEPTH = 46
EXPECTED_PER_HOST = 25
EXPECTED_ASPIRATIONAL = 138  # 0.05%, P < 5 d: 3 periods x 46
# Recorded Phase 3/4 seeds (pre-reg section 0.1): no trial seed
# may equal one. They are outside the 41xxxxxx blocks by
# construction; asserted anyway.
RECORDED_PHASE34_SEEDS = {20261114, 20261115, 20261118}
ROW_RE = re.compile(
    r"\| 4\.1-3 stacked floor \| (\d+) \| (\d+)\u2013(\d+) \|")


def _duration_d(period_d):
    return (2.0 * period_d ** (1.0 / 3.0)) / 24.0


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _sha_text(text):
    return hashlib.sha256(text.encode()).hexdigest()


def parse_prereg(prereg_path):
    """Return (row_dict, row_sha256, log_has_ref) from the
    pre-reg text. row_dict: master, block_lo, block_hi."""
    text = Path(prereg_path).read_text()
    m = ROW_RE.search(text)
    if not m:
        raise AssertionError("section 1 4.1-3 row not found in "
                             "pre-reg")
    row = {"master": int(m.group(1)),
           "block_lo": int(m.group(2)),
           "block_hi": int(m.group(3))}
    row_line = [ln for ln in text.splitlines()
                if ln.startswith("| 4.1-3 stacked floor |")][0]
    row_sha = _sha_text(row_line)
    log_has_ref = "### 413-SEED-20261118" in text
    return row, row_sha, log_has_ref


def assert_amendment(prereg_path, amendment_ref, block_end):
    """Fail closed unless the caller's flags match the amended
    pre-reg. Returns (row, row_sha256)."""
    if amendment_ref != VOTE_REF:
        raise AssertionError(
            f"amendment-ref mismatch: got {amendment_ref!r}, "
            f"need {VOTE_REF!r}")
    if block_end != BLOCK_END:
        raise AssertionError(
            f"block-end mismatch: got {block_end}, "
            f"need {BLOCK_END}")
    row, row_sha, log_has_ref = parse_prereg(prereg_path)
    if row["master"] != MASTER_SEED:
        raise AssertionError(
            f"master mismatch: pre-reg row has {row['master']}, "
            f"need {MASTER_SEED}")
    if (row["block_lo"], row["block_hi"]) != (BLOCK_START,
                                              BLOCK_END):
        raise AssertionError(
            f"block mismatch: pre-reg row has "
            f"{row['block_lo']}-{row['block_hi']}, need "
            f"{BLOCK_START}-{BLOCK_END}")
    if not log_has_ref:
        raise AssertionError(
            f"amendment log entry {VOTE_REF!r} not found in "
            f"pre-reg")
    return row, row_sha


def assert_trial_index(index, burn_logged=False):
    """Refuse out-of-block indices, and refuse any index above
    the first run (1149) without a logged section 0.6 burn
    entry."""
    if not isinstance(index, int) or isinstance(index, bool):
        raise AssertionError(f"trial_index must be int, got "
                             f"{index!r}")
    if index < 0:
        raise AssertionError(f"trial_index {index} < 0")
    if index > MAX_INDEX:
        raise AssertionError(
            f"trial_index {index} > {MAX_INDEX} (block end "
            f"{BLOCK_END}); a third full run needs a new "
            f"section 7 vote (BA-2)")
    if index > FIRST_RUN_MAX_INDEX and not burn_logged:
        raise AssertionError(
            f"trial_index {index} > {FIRST_RUN_MAX_INDEX} "
            f"without a logged section 0.6 burn entry -- spare "
            f"seeds are not an allowance (413-A12)")


def manifest_header(row_sha, trial_index_span, hosts_sha256):
    """Header every 4.1-3 manifest must carry (413-7)."""
    return {
        "amendment_ref": VOTE_REF,
        "master_seed": MASTER_SEED,
        "block_range": [BLOCK_START, BLOCK_END],
        "trial_index_span": list(trial_index_span),
        "host_pool": HOST_POOL,
        "amended_row_sha256": row_sha,
        "hosts_sha256": hosts_sha256,
    }


def load_campaign_hosts(drawn_path, dev_hosts_path):
    """The 46 campaign hosts (shuffle positions 1-46), sorted
    TIC ascending -- NUMERIC order. Returns (hosts, drawn_sha,
    dev_sha). Asserts the frozen draw facts."""
    drawn = json.loads(Path(drawn_path).read_text())
    dev = {str(t) for t in json.loads(
        Path(dev_hosts_path).read_text())["dev_hosts_union_tic"]}
    assert len(dev) == 132, f"dev hosts {len(dev)} != 132"
    assert drawn.get("amendment_ref") == VOTE_REF, (
        f"drawn-hosts amendment_ref "
        f"{drawn.get('amendment_ref')!r} != {VOTE_REF!r}")
    assert drawn.get("master_seed") == MASTER_SEED
    assert drawn.get("eligible_n") == 339, (
        f"drawn eligible_n {drawn.get('eligible_n')} != 339")
    ordered = [str(t) for t in drawn["ordered_hosts"]]
    assert len(ordered) == 339
    assert _sha_text("\n".join(ordered)) == drawn[
        "ordered_hosts_sha256"], (
        "ordered-hosts list hash mismatch -- the draw artifact "
        "changed after hashing")
    campaign = [str(t) for t in drawn["slices"][
        "campaign_positions_1_46"]]
    assert campaign == ordered[:46], (
        "campaign slice != ordered positions 1-46")
    assert len(campaign) == N_HOSTS
    assert not (set(campaign) & dev), (
        "campaign hosts overlap the dev set")
    positions = {tic: i + 1 for i, tic in enumerate(ordered)}
    hosts = sorted(
        ({"tic": tic, "sectors": list(SECTORS),
          "n_sectors": 4, "combo": "S95+S96+S97+S98",
          "original_sector": 95,
          "draw_position": positions[tic]} for tic in campaign),
        key=lambda h: int(h["tic"]))
    return hosts, _sha(drawn_path), _sha(dev_hosts_path)


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
    """Build the 1,150 trials in HOST-MAJOR order: host
    TIC-ascending, then depth 0-4, then period 0-4.
    spans: {tic: {sector: (t_min, t_max)}}. Every host must
    have a span for every sector in its list."""
    for h in hosts:
        tic = str(h["tic"])
        assert tic in spans, f"no spans for TIC {tic}"
        for sec in h["sectors"]:
            assert str(sec) in spans[tic] or sec in spans[tic], (
                f"no span for TIC {tic} sector {sec}")
    trials = []
    for h_idx, host in enumerate(hosts):
        tic = str(host["tic"])
        sectors = sorted(int(s) for s in host["sectors"])
        orig = sectors[0]
        host_spans = {int(s): tuple(v)
                      for s, v in spans[tic].items()}
        t_min_o, t_max_o = host_spans[orig]
        for j, depth in enumerate(DEPTHS):
            for p, period in enumerate(PERIODS):
                idx = h_idx * 25 + j * 5 + p
                assert_trial_index(idx)
                seed = MASTER_SEED + idx
                rng = np.random.default_rng(seed)
                off = float(rng.uniform(0.0, period))
                epoch = t_min_o + off
                dur = _duration_d(period)
                n_single = _expected_n_events(
                    epoch, period, t_min_o, t_max_o)
                n_by_interval = {
                    str(k): int(sum(
                        _expected_n_events(epoch, period,
                                           *host_spans[s])
                        for s in secs))
                    for k, secs in INTERVALS.items()}
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
                    "n_events_expected_by_interval": n_by_interval,
                    "n_events_expected_stitched": int(
                        n_by_interval["4"]),
                    "n_sectors": len(sectors),
                    "sectors": sectors,
                    "group": "p413",
                    "is_demo": False,
                })
    assert len(trials) == N_TRIALS, (
        f"built {len(trials)} != {N_TRIALS}")
    return trials


def assert_manifest(manifest):
    """All section 2.3 builder assertions. Fails loudly."""
    trials = manifest["trials"]
    hosts = manifest["hosts"]
    assert len(trials) == N_TRIALS, (
        f"TOTAL {len(trials)} != {N_TRIALS}")
    assert len(hosts) == N_HOSTS, (
        f"hosts {len(hosts)} != {N_HOSTS}")
    assert all(not t["is_demo"] for t in trials), (
        "4.1-3 has no demo trial")
    # Per-depth 230; per-period-per-depth 46.
    per_depth = Counter(t["depth_idx"] for t in trials)
    assert dict(per_depth) == {j: EXPECTED_PER_DEPTH
                               for j in range(5)}, (
        f"per-depth {dict(per_depth)}")
    for j in range(5):
        for p in range(5):
            n = sum(1 for t in trials
                    if t["depth_idx"] == j
                    and t["period_idx"] == p)
            assert n == EXPECTED_PER_PERIOD_PER_DEPTH, (
                f"depth {j} period {p}: {n} != "
                f"{EXPECTED_PER_PERIOD_PER_DEPTH}")
    # Per-host 25.
    per_host = Counter(t["tic"] for t in trials)
    assert set(per_host.values()) == {EXPECTED_PER_HOST}, (
        f"per-host totals {set(per_host.values())} != "
        f"{{{EXPECTED_PER_HOST}}}")
    # Aspirational cell: 0.05%, P < 5 d = 138.
    n_asp = sum(1 for t in trials
                if t["depth_idx"] == 1 and t["period_d"] < 5.0)
    assert n_asp == EXPECTED_ASPIRATIONAL, (
        f"aspirational cell {n_asp} != {EXPECTED_ASPIRATIONAL}")
    # Host-major trial order: (host TIC, depth, period).
    keys = [(int(t["tic"]), t["depth_idx"], t["period_idx"])
            for t in trials]
    assert keys == sorted(keys), (
        "trials not in host-major (host, depth, period) order")
    assert [t["trial_index"] for t in trials] == list(
        range(N_TRIALS)), "trial indices must be 0..1149"
    # Seeds: master + index, within the block, no cross-block
    # seed, no recorded Phase 3/4 seed.
    for t in trials:
        assert t["seed"] == MASTER_SEED + t["trial_index"], (
            f"trial {t['trial_index']} seed {t['seed']} != "
            f"master + index")
        assert BLOCK_START < t["seed"] <= BLOCK_END, (
            f"seed {t['seed']} outside 4103 block")
        assert t["seed"] // 10000 == 4103, (
            f"seed {t['seed']} outside the 4103 block (no "
            f"cross-block seed: 4.1-3 draws only on 4103)")
        assert t["seed"] not in RECORDED_PHASE34_SEEDS, (
            f"seed {t['seed']} is a recorded Phase 3/4 seed")
    # Every host is 4-sector, original sector 95.
    for h in hosts:
        assert h["sectors"] == SECTORS, (
            f"host {h['tic']} sectors {h['sectors']} != {SECTORS}")
        assert h["original_sector"] == 95
    # Epochs: drawn from the trial seed (re-derive a sample --
    # full re-derivation is the builder's job, this asserts
    # the rule, not every draw).
    for t in trials[::149]:
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


def assemble_manifest(hosts, trials, drawn_sha, dev_sha,
                      drawn_name, row_sha):
    """Assemble the pre-manifest dict from hosts + trials and
    assert it (all section 2.3 assertions). Pure -- the CLI
    and the tests share it."""
    hosts_sha = _sha_text("\n".join(
        str(h["tic"]) for h in hosts))
    header = manifest_header(row_sha, (0, FIRST_RUN_MAX_INDEX),
                             hosts_sha)
    manifest = {
        "tool": "bulk/p413_manifest.py",
        "item": "4.1-3 stacked-floor measurement (pre-manifest)",
        "prereg_ref": "PHASE41_PREREG.md section 2.3",
        "calibration": "bulk_v5",
        "seed_derivation": ("per-trial seed = master + "
                            "trial_index; epoch_offset_d ~ "
                            "Uniform(0, P) from "
                            "numpy default_rng(trial_seed), one "
                            "draw; epoch_btjd = t_min_orig + "
                            "epoch_offset_d"),
        "seed_map": {
            "first_run": [41030001, 41031150],
            "re_run_reserve": [41031151, 41032300],
            "spare": [41032301, 41032999],
        },
        "seed_block": f"{BLOCK_START}-{BLOCK_END}",
        "block_bounds": [BLOCK_START, BLOCK_END],
        "depths_frac": DEPTHS,
        "periods_d": PERIODS,
        "sectors": SECTORS,
        "intervals": {str(k): v for k, v in INTERVALS.items()},
        "allocation_rule": ("host-major (mirrors "
                            "p45_manifest.json): host TIC "
                            "ascending, then depth 0-4, then "
                            "period 0-4; trial_index = "
                            "host_idx*25 + depth_idx*5 + "
                            "period_idx"),
        "trial_order": "host-major",
        "original_sector_rule": "S95 for every host (min(sectors))",
        "duration_law": "2.0 * P**(1/3) hours",
        "drawn_hosts_file": drawn_name,
        "drawn_hosts_sha256": drawn_sha,
        "dev_hosts_sha256": dev_sha,
        "n_hosts": len(hosts),
        "n_trials": len(trials),
        "n_demo_trials": 0,
        "hosts": hosts,
        "sectors_by_host": {
            str(h["tic"]): list(h["sectors"]) for h in hosts},
        "trials": trials,
    }
    manifest.update(header)
    assert_manifest(manifest)
    return manifest


def _selftest(prereg_path):
    results = []

    def case(name, fn, expect_fail=False):
        try:
            fn()
            ok = not expect_fail
            detail = "raised" if expect_fail else "passed"
        except AssertionError as e:
            ok = expect_fail
            detail = f"refused: {str(e)[:80]}"
        results.append((name, ok))
        print(f"[{'PASS' if ok else 'FAIL'}] {name} -- {detail}")

    prereg = Path(prereg_path) if prereg_path else None
    if prereg is not None and prereg.exists():
        case("success: correct ref + block end",
             lambda: assert_amendment(prereg, VOTE_REF, 41032999))
        case("refuse: wrong amendment ref",
             lambda: assert_amendment(prereg, "FAKE-REF", 41032999),
             expect_fail=True)
        case("refuse: wrong block end (frozen bound)",
             lambda: assert_amendment(prereg, VOTE_REF,
                                      BLOCK_END - 2000),
             expect_fail=True)
        case("refuse: block end off by one",
             lambda: assert_amendment(prereg, VOTE_REF, 41033000),
             expect_fail=True)
        case("refuse: missing ref (None)",
             lambda: assert_amendment(prereg, None, 41032999),
             expect_fail=True)
    else:
        print("NOTE: pre-reg not found at "
              f"{prereg_path} -- parse cases skipped; pass "
              "--prereg for the full self-test.")
    case("index 0 ok", lambda: assert_trial_index(0))
    case("index 1149 ok (last first-run)",
         lambda: assert_trial_index(1149))
    case("refuse: index 1150 without burn entry",
         lambda: assert_trial_index(1150), expect_fail=True)
    case("index 1150 ok WITH burn entry",
         lambda: assert_trial_index(1150, burn_logged=True))
    case("index 2998 ok WITH burn entry",
         lambda: assert_trial_index(2998, burn_logged=True))
    case("refuse: index 2999 (beyond block)",
         lambda: assert_trial_index(2999, burn_logged=True),
         expect_fail=True)
    case("refuse: index -1",
         lambda: assert_trial_index(-1), expect_fail=True)

    def header_case():
        h = manifest_header("deadbeef", (0, 1149), "cafef00d")
        assert h["amendment_ref"] == VOTE_REF
        assert h["master_seed"] == MASTER_SEED
        assert h["block_range"] == [41030000, 41032999]
        assert h["trial_index_span"] == [0, 1149]
        assert h["host_pool"] == HOST_POOL
        assert h["amended_row_sha256"] == "deadbeef"
    case("manifest header contents", header_case)

    failed = [n for n, ok in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} passed")
    if failed:
        print("FAILED:", ", ".join(failed))
        raise SystemExit(1)
    print("GUARD SELFTEST: PASS")


def build_manifest(drawn_path, dev_hosts_path, spans, prereg_path,
                   amendment_ref, block_end):
    """Build + assert the pre-manifest dict (no I/O besides the
    input reads)."""
    _row, row_sha = assert_amendment(prereg_path, amendment_ref,
                                     block_end)
    hosts, drawn_sha, dev_sha = load_campaign_hosts(
        drawn_path, dev_hosts_path)
    trials = build_trials(hosts, spans)
    return assemble_manifest(hosts, trials, drawn_sha, dev_sha,
                             Path(drawn_path).name, row_sha)


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Build the 4.1-3 pre-manifest (1,150 trials) "
                    "from the drawn host list.")
    ap.add_argument("--drawn-hosts", default=None)
    ap.add_argument("--dev-hosts", default=None)
    ap.add_argument("--prereg", default=None,
                    help="path to PHASE41_PREREG.md (guard)")
    ap.add_argument("--amendment-ref", default=None)
    ap.add_argument("--block-end", type=int, default=None)
    ap.add_argument("--expected-prereg-sha", default=None,
                    help="fail unless the pre-reg copy matches "
                         "this sha256 (Mac copy check)")
    ap.add_argument("--cache", default=None,
                    help="bulk/cache dir (Mac): spans read from "
                         "FITS. Exactly one of --cache/--spans.")
    ap.add_argument("--spans", default=None,
                    help="spans JSON {tic: {sector: [t_min, "
                         "t_max]}} (VM use / tests). Exactly one "
                         "of --cache/--spans.")
    ap.add_argument("--out", default=None)
    ap.add_argument("--selftest", action="store_true",
                    help="run the amendment-guard self-test "
                         "(413-7) and exit")
    args = ap.parse_args(argv)
    if args.selftest:
        prereg = args.prereg or str(
            Path.home() / "workspace" / "goals"
            / "exoplanet-hunter" / "hidden_files" / "science-vet"
            / "phase41-vote" / "PHASE41_PREREG.md")
        _selftest(prereg)
        return 0
    if (not args.drawn_hosts or not args.dev_hosts
            or not args.prereg or not args.out):
        ap.error("--drawn-hosts, --dev-hosts, --prereg and --out "
                 "are required (unless --selftest)")
    if args.amendment_ref is None or args.block_end is None:
        ap.error("--amendment-ref and --block-end are required "
                 "(413-7: the builder refuses without them)")
    if bool(args.cache) == bool(args.spans):
        ap.error("exactly one of --cache / --spans is required")
    if args.expected_prereg_sha is not None:
        actual = _sha(args.prereg)
        if actual != args.expected_prereg_sha:
            raise SystemExit(
                f"[p413-manifest] REFUSING: pre-reg copy sha "
                f"{actual} != expected {args.expected_prereg_sha} "
                f"-- the Mac copy is not the frozen pre-reg")
    hosts, _d, _v = load_campaign_hosts(args.drawn_hosts,
                                        args.dev_hosts)
    if args.cache:
        spans = load_spans_from_cache(args.cache, hosts)
    else:
        spans = json.loads(Path(args.spans).read_text())
    manifest = build_manifest(args.drawn_hosts, args.dev_hosts,
                              spans, args.prereg,
                              args.amendment_ref, args.block_end)
    out = Path(args.out)
    out.write_text(json.dumps(manifest, indent=1, sort_keys=True))
    print(f"wrote {out}: {manifest['n_trials']} trials, "
          f"{manifest['n_hosts']} hosts")
    print("sha256:", _sha(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
