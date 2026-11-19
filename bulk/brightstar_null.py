"""Bright-star curve: null manifest builder.

Builds the 41-trial null manifest: one null trial per campaign
host, on the host's own 4-sector combo. This is a DIRECT CHECK
that the campaign hosts themselves carry no pipeline-triggering
artifact -- NOT a rate estimate. The primary null reference is
4.1-10's measured rate (stitched 70/8,000 = 8.75/1,000;
4-sector stratum 43/2,776 = 15.49/1,000), per
BRIGHTSTAR_CURVE_DESIGN.md section 5:

- The null rate is a pipeline+data property dominated by
  sector-wide common-mode artifacts (PROVEN by the BP-1 null
  diagnosis), not host brightness.
- The bright population is too small (79 in-box TICs) for an
  independent 8,000-host draw.
- Re-running the identical frozen 4.1-10 null manifest would
  reproduce identical files (deterministic legs, no new
  information).

The null legs are deterministic given host + calibration (no
RNG called), so null trials consume NO ledger seeds (pre-reg
section 0.5). No draw, no shuffle, no exclusions: the null
hosts ARE the campaign hosts by design.

Null trial shape (BP-1 / 4.1-10 pattern): dummy trials with
tic, sector=min(combo), trial_id "null01", kind
"null_placeholder", n_sectors, sectors, combo, null_source.
These trials carry NO injection parameters and MUST NEVER be
run in campaign mode (bulk/p4110_run.py refuses them there).

Usage:
  python bulk/brightstar_null.py \
      --manifest <brightstar_manifest.json> \
      --out <brightstar_null_manifest.json>
"""
import argparse
import hashlib
import json
from pathlib import Path

N_NULL_TRIALS = 41


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _combo_label(sectors):
    return "+".join(f"S{s}" for s in sectors)


def build_null_manifest(campaign_manifest):
    """One null trial per campaign host. Returns the null
    manifest dict. Fails loudly on any mismatch."""
    hosts = campaign_manifest["hosts"]
    assert len(hosts) == N_NULL_TRIALS, (
        f"campaign hosts {len(hosts)} != {N_NULL_TRIALS}")
    trials = []
    for h in hosts:
        sectors = sorted(int(s) for s in h["sectors"])
        assert len(sectors) == 4, (
            f"TIC {h['tic']} has {len(sectors)} sectors != 4")
        trials.append({
            "tic": str(h["tic"]), "sector": sectors[0],
            "trial_id": "null01", "kind": "null_placeholder",
            "n_sectors": 4,
            "sectors": sectors,
            "combo": _combo_label(sectors),
            "null_source": "campaign_host",
        })
    trials.sort(key=lambda t: int(t["tic"]))
    assert len({t["tic"] for t in trials}) == len(trials), (
        "duplicate null TIC")
    manifest = {
        "tool": "bulk/brightstar_null.py",
        "item": "bright-star curve null (direct check, 41 hosts)",
        "design_ref": "BRIGHTSTAR_CURVE_DESIGN.md section 5",
        "calibration": "bulk_v5",
        "seed_note": ("Null trials consume NO ledger seeds (the "
                      "null legs are deterministic). No draw was "
                      "made: the null hosts ARE the campaign "
                      "hosts by design."),
        "primary_null_reference": (
            "4.1-10 measured rate: stitched 70/8,000 = "
            "8.75/1,000; 4-sector stratum 43/2,776 = "
            "15.49/1,000 (the relevant comparator -- all "
            "bright-star hosts are 4-sector)."),
        "null_basis": ("1 null trial per campaign host (41) -- "
                       "a direct check, not a rate estimate. "
                       "Expected survivors at the 4.1-10 rate "
                       "approx 0.36; 0/41 is consistent "
                       "(P(0) approx 70%); >=2 survivors is a "
                       "red flag to investigate before trusting "
                       "the curve."),
        "n_null_trials": len(trials),
        "strata": {4: len(trials)},
        "note": ("Null manifests: one dummy trial per null host "
                 "(tic + sector only). The null legs read only "
                 "tic/sector (+ sectors_by_host for the stack). "
                 "These trials carry NO injection parameters and "
                 "MUST NEVER be run in campaign mode."),
        "sectors_by_host": {t["tic"]: t["sectors"] for t in trials},
        "trials": trials,
    }
    return manifest


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Build the bright-star null manifest (one "
                    "null trial per campaign host).")
    ap.add_argument("--manifest", required=True,
                    help="finalised brightstar_manifest.json "
                         "(or the pre-manifest -- only the host "
                         "list is read)")
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    campaign = json.loads(Path(args.manifest).read_text())
    manifest = build_null_manifest(campaign)
    manifest["campaign_manifest_sha256"] = _sha(args.manifest)
    out = Path(args.out)
    out.write_text(json.dumps(manifest, indent=1, sort_keys=True))
    print(f"wrote {out}: {len(manifest['trials'])} null trials")
    print("sha256:", _sha(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
