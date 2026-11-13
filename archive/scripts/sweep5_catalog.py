#!/usr/bin/env python
"""Sweep-5 catalogue pass.

Merges Catalogs.query_object neighbourhood tables for seed stars spread
across the patch (each returns ~34k rows around the seed), then falls
back to a direct query_object for any target still missing (a star's own
neighbourhood always contains the star). Extracts rows for all 20 sweep
targets, TOI TAP counts for the 16 hits, and pairwise separations for
the 13.7215 d trio and the ~24 d sub-cluster. Writes
sweep5_logs/catalog_rows.json; patches catalogue + contamination blocks
into any vetting JSONs that already exist in vetting_results/
(safe to re-run at the end).
"""
import json
import math
import time
import urllib.parse
import urllib.request
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

BASE = Path(__file__).resolve().parent
LOGDIR = BASE / "sweep5_logs"
LOGDIR.mkdir(exist_ok=True)
OUTDIR = BASE / "vetting_results"

CENTRE_RA, CENTRE_DEC = 110.0, -63.0
HITS = ["349370722", "349370477", "349408892", "349477874", "349370417",
        "349370907", "349309779", "349273239", "349268662", "349309664",
        "349268505", "349481800", "349478154", "349519662", "349193749",
        "349193983"]
ALL_TARGETS = ["349370722", "349370477", "349408892", "349477788",
               "349477874", "349370417", "349370907", "349309779",
               "349305195", "349273239", "349272923", "349268662",
               "349309664", "349268505", "349481800", "349478154",
               "349519662", "349193749", "349193983", "349371108"]
SEEDS = ["349370722", "349309779", "349481800", "349193749", "349408892"]
TRIO = ["349309779", "349268662", "349268505"]
CLUSTER24 = ["349408892", "349370907", "349273239"]


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def toi_rows(tic):
    q = f"SELECT tid FROM toi WHERE tid={tic}"
    url = ("https://exoplanetarchive.ipac.caltech.edu/TAP/sync?"
           + urllib.parse.urlencode({"query": q, "format": "csv"}))
    try:
        with urllib.request.urlopen(url, timeout=60) as r:
            txt = r.read().decode()
        lines = [ln for ln in txt.strip().splitlines() if ln.strip()]
        return max(0, len(lines) - 1)
    except Exception as exc:
        return f"error: {exc}"


def sep_deg(ra1, dec1, ra2, dec2):
    p1, p2 = math.radians(dec1), math.radians(dec2)
    dp = math.radians(dec2 - dec1)
    dl = math.radians(ra2 - ra1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return math.degrees(2 * math.asin(min(1.0, math.sqrt(h))))


def row_to_dict(r, colnames):
    def g(c):
        if c not in colnames:
            return None
        v = r[c]
        try:
            if v is None or (isinstance(v, float) and math.isnan(v)):
                return None
        except Exception:
            pass
        return v
    ra, dec = g("ra"), g("dec")
    out = {
        "ra_deg": float(ra) if ra is not None else None,
        "dec_deg": float(dec) if dec is not None else None,
        "tmag": float(g("Tmag")) if g("Tmag") is not None else None,
        "rad_rsun_tic": float(g("rad")) if g("rad") is not None else None,
        "mass_msun": float(g("mass")) if g("mass") is not None else None,
        "teff_k": float(g("Teff")) if g("Teff") is not None else None,
        "dist_pc": float(g("d")) if g("d") is not None else None,
        "gaia_dr3": int(g("GAIA")) if g("GAIA") is not None else None,
        "twomass": str(g("TWOMASS")) if g("TWOMASS") is not None else None,
        "contratio": float(g("contratio")) if g("contratio") is not None else None,
    }
    if out["ra_deg"] is not None:
        out["offset_from_centre_deg"] = round(
            sep_deg(CENTRE_RA, CENTRE_DEC, out["ra_deg"], out["dec_deg"]), 3)
    return out


def pair_block(rows, members, label):
    out = {"label": label, "members": members, "pairs": []}
    for i in range(len(members)):
        for j in range(i + 1, len(members)):
            a, b = rows.get(members[i]), rows.get(members[j])
            if a and b and a.get("ra_deg") is not None and b.get("ra_deg") is not None:
                s = sep_deg(a["ra_deg"], a["dec_deg"], b["ra_deg"], b["dec_deg"])
                out["pairs"].append({
                    "a": members[i], "b": members[j],
                    "separation_deg": s, "separation_arcmin": s * 60.0})
                log(f"{label} pair {members[i]}-{members[j]}: {s:.4f} deg "
                    f"= {s * 60:.2f} arcmin")
    return out


def main():
    from astroquery.mast import Catalogs

    found = {}
    wanted = set(ALL_TARGETS)

    def harvest(seed):
        log(f"query_object TIC {seed} ...")
        tab = Catalogs.query_object(f"TIC {seed}", catalog="TIC")
        log(f"  neighbourhood rows: {len(tab)}")
        ids = {str(r["ID"]): r for r in tab}
        for tic in list(wanted):
            if tic in ids:
                found[tic] = row_to_dict(ids[tic], tab.colnames)
                wanted.discard(tic)
        log(f"  targets found so far: {len(found)}/20; missing: {sorted(wanted)}")

    for seed in SEEDS:
        if not wanted:
            break
        try:
            harvest(seed)
        except Exception as exc:
            log(f"  seed {seed} failed: {type(exc).__name__}: {str(exc)[:160]}")
    for tic in list(wanted):
        try:
            harvest(tic)
        except Exception as exc:
            log(f"  direct {tic} failed: {type(exc).__name__}: {str(exc)[:160]}")
            found[tic] = {"error": f"catalog lookup failed: {exc}"}
            wanted.discard(tic)

    rows = {tic: found.get(tic, {"error": "not found"}) for tic in ALL_TARGETS}
    out = {"centre": {"ra": CENTRE_RA, "dec": CENTRE_DEC}, "rows": rows,
           "trio": pair_block(rows, TRIO, "13.7215-trio"),
           "cluster24": pair_block(rows, CLUSTER24, "24d-cluster")}
    (LOGDIR / "catalog_rows.json").write_text(json.dumps(out, indent=2, default=str))
    log("wrote sweep5_logs/catalog_rows.json")

    for tic in HITS:
        n = toi_rows(tic)
        rows[tic]["archive_toi_rows"] = n
        log(f"TIC {tic}: TOI rows = {n}")
        jp = OUTDIR / f"{tic}.json"
        if jp.exists():
            d = json.loads(jp.read_text())
            row = rows[tic]
            contra = row.get("contratio")
            d["catalogue"] = {
                "ra_deg": row.get("ra_deg"), "dec_deg": row.get("dec_deg"),
                "offset_from_centre_deg": row.get("offset_from_centre_deg"),
                "tmag": row.get("tmag"), "rad_rsun_tic": row.get("rad_rsun_tic"),
                "mass_msun": row.get("mass_msun"), "teff_k": row.get("teff_k"),
                "dist_pc": row.get("dist_pc"), "gaia_dr3": row.get("gaia_dr3"),
                "twomass": row.get("twomass"), "archive_toi_rows": n,
            }
            d["contamination"] = {
                "tic_contratio": contra,
                "source": "TIC catalog via MAST (the value ExoFOP displays)",
                "flag_line": 0.1,
                "flagged": bool(contra is not None and contra >= 0.1),
            }
            jp.write_text(json.dumps(d, indent=2, default=str))
            log(f"TIC {tic}: patched catalogue+contamination into JSON")
    (LOGDIR / "catalog_rows.json").write_text(json.dumps(out, indent=2, default=str))
    log("done")


if __name__ == "__main__":
    main()
