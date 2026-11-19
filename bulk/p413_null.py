"""4.1-3 stacked-floor measurement: null manifest builder.

Null design (413_RUN_DESIGN.md section 6): the section 0.5
10x bar (11,500 null trials) is INFEASIBLE with fresh hosts --
the 3/4-sector fresh pool is exhausted (339 stars; 92 needed
for campaign + reserve). This builder assembles the adopted
null manifest from the ALREADY-DRAWN hosts in
p413_ordered_hosts.json (the draw + exclusion audit live in
bulk/p413_draw.py; this builder re-verifies disjointness, it
does not re-draw):

- 247 PAIRED null hosts (shuffle positions 93-339), each run
  at ALL 3 intervals (2/3/4 sectors) = 741 null trials.
- 2,000 2-SEC SUPPLEMENT hosts (S95∩S96 remaining pool),
  run at the 2-sec interval only = 2,000 null trials.
- Total NEW null trials: 2,741. The primary null reference
  per interval is 4.1-10's measured per-combo rates at the
  exact stacks (S95+S96 n=816, S95+S96+S97 n=980,
  S95+S96+S97+S98 n=2,776) -- see the design note.

Null trials consume NO ledger seeds (the null legs are
deterministic given host + calibration -- pre-reg section
0.5). The null manifest carries one dummy trial per null
host (tic + sector + intervals); the runner's --interval
flag selects the eligible hosts + overrides the sector set.

Usage (VM):
  python bulk/p413_null.py --drawn-hosts <p413_ordered_hosts.json> \
      --vote-dir <phase41-vote> --out <p413_null_manifest.json>
"""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

MASTER_SEED = 41030001
VOTE_REF = "413-SEED-20261118"
N_PAIRED = 247
N_SUPPLEMENT = 2000
CONTROL_TIC = "259377017"


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _tics_from_hosts_file(path, key):
    d = json.loads(Path(path).read_text())
    return {str(h["tic"]) for h in d[key]}


def _tics_from_trials(path):
    d = json.loads(Path(path).read_text())
    return {str(t["tic"]) for t in d["trials"]}


def load_exclusions(vote):
    """Re-verify the C41-12 exclusion union (same sets as the
    draw). Returns the union. Fails loudly on any count
    mismatch."""
    union = set()
    dev = {str(t) for t in json.loads(
        (vote / "dev_hosts_union.json").read_text())
        ["dev_hosts_union_tic"]}
    assert len(dev) == 132
    union |= dev
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
    assert len(union) == 16431, (
        f"exclusion union {len(union)} != 16431")
    return union


def build_null_manifest(drawn_path, vote_dir):
    """Assemble the null manifest from the draw artifact.
    Re-verifies every disjointness assertion."""
    drawn = json.loads(Path(drawn_path).read_text())
    assert drawn.get("amendment_ref") == VOTE_REF
    assert drawn.get("master_seed") == MASTER_SEED
    ordered = [str(t) for t in drawn["ordered_hosts"]]
    assert _sha_text("\n".join(ordered)) == drawn[
        "ordered_hosts_sha256"], (
        "ordered-hosts list hash mismatch -- the draw artifact "
        "changed after hashing")
    campaign = set(str(t) for t in drawn["slices"][
        "campaign_positions_1_46"])
    reserve = set(str(t) for t in drawn["slices"][
        "reserve_positions_47_92"])
    paired = [str(t) for t in drawn["slices"][
        "null_paired_positions_93_339"]]
    supplement = [str(t) for t in drawn["supplement_2sec"]["hosts"]]
    assert len(paired) == N_PAIRED, (
        f"paired null hosts {len(paired)} != {N_PAIRED}")
    assert len(supplement) == N_SUPPLEMENT, (
        f"supplement hosts {len(supplement)} != {N_SUPPLEMENT}")
    assert paired == ordered[92:], (
        "paired null slice != ordered positions 93-339")
    assert not (set(paired) & campaign), "paired overlaps campaign"
    assert not (set(paired) & reserve), "paired overlaps reserve"
    assert not (set(supplement) & set(ordered)), (
        "supplement overlaps the ordered list")
    union = load_exclusions(Path(vote_dir))
    for name, hosts in (("paired", paired),
                        ("supplement", supplement)):
        assert not (set(hosts) & union), (
            f"{name} null hosts overlap the exclusion union")
    assert not (set(paired) & set(supplement)), (
        "paired and supplement null hosts overlap")
    trials = []
    for tic in sorted(paired, key=int):
        trials.append({
            "tic": tic, "sector": 95,
            "trial_id": "null01", "kind": "null_placeholder",
            "n_sectors": 4, "sectors": [95, 96, 97, 98],
            "combo": "S95+S96+S97+S98",
            "intervals": [2, 3, 4],
            "null_source": "ordered_positions_93_339",
        })
    for tic in sorted(supplement, key=int):
        trials.append({
            "tic": tic, "sector": 95,
            "trial_id": "null01", "kind": "null_placeholder",
            "n_sectors": 2, "sectors": [95, 96],
            "combo": "S95+S96",
            "intervals": [2],
            "null_source": "s95s96_supplement",
        })
    manifest = {
        "tool": "bulk/p413_null.py",
        "item": "4.1-3 stacked-floor measurement null",
        "prereg_ref": ("PHASE41_PREREG.md sections 0.5, 2.3 "
                       "(null >=10x -- see the shortfall note)"),
        "design_ref": "413_RUN_DESIGN.md section 6",
        "amendment_ref": VOTE_REF,
        "calibration": "bulk_v5",
        "master_seed": MASTER_SEED,
        "seed_note": ("Null trials consume NO ledger seeds "
                      "(the null legs are deterministic). The "
                      "master seed is used ONLY as the shuffle "
                      "seed, per the pre-reg section 1 draw "
                      "procedure."),
        "numpy_version": np.__version__,
        "drawn_hosts_sha256": _sha(drawn_path),
        "n_excluded_unique": len(union),
        "null_basis": ("10x the 1,150 campaign trials = "
                       "11,500 -- INFEASIBLE with fresh hosts "
                       "(pool exhaustion: 339 fresh 3/4-sector "
                       "stars remain; see 413_RUN_DESIGN.md "
                       "section 6). This manifest carries 2,741 "
                       "NEW null trials (741 paired + 2,000 "
                       "supplement); the primary null reference "
                       "per interval is 4.1-10's measured "
                       "per-combo rates at the exact stacks "
                       "(n=4,572)."),
        "n_null_hosts": len(trials),
        "n_null_trials": N_PAIRED * 3 + N_SUPPLEMENT,
        "counts": {
            "paired_3_intervals": N_PAIRED,
            "supplement_2sec_only": N_SUPPLEMENT,
            "per_interval": {"2": N_PAIRED + N_SUPPLEMENT,
                             "3": N_PAIRED, "4": N_PAIRED},
        },
        "note": ("Null manifests: one dummy trial per null host "
                 "(tic + sector + intervals). The null legs read "
                 "only tic/sector (+ sectors_by_host for the "
                 "stack). These trials carry NO injection "
                 "parameters and MUST NEVER be run in campaign "
                 "mode."),
        "sectors_by_host": {t["tic"]: t["sectors"]
                            for t in trials},
        "trials": trials,
    }
    return manifest


def _sha_text(text):
    return hashlib.sha256(text.encode()).hexdigest()


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="4.1-3 null manifest: assemble from the "
                    "drawn hosts (247 paired + 2,000 "
                    "supplement).")
    ap.add_argument("--drawn-hosts", required=True)
    ap.add_argument("--vote-dir", required=True,
                    help="phase41-vote/ (exclusion files)")
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    manifest = build_null_manifest(args.drawn_hosts,
                                   args.vote_dir)
    out = Path(args.out)
    out.write_text(json.dumps(manifest, indent=1, sort_keys=True))
    print(f"wrote {out}: {manifest['n_null_hosts']} null hosts, "
          f"{manifest['n_null_trials']} null trials "
          f"(741 paired + 2,000 supplement)")
    print("sha256:", _sha(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
