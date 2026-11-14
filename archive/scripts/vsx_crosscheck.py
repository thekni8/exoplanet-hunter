#!/usr/bin/env python
"""VSX cross-check batch 2026-11-06 — READ-ONLY. No hunter.py import,
no DB access. Per star: (A) ID-verified TIC row via MAST Catalogs;
(B) VSX cone search — VizieR B/vsx attempted first, VSX website
query.votable service as the working route (VizieR unreachable from
this VM 2026-11-06); (C) Gaia DR3 secondary (gaia_source cone +
vari_classifier_result + vari_eclipsing_binary) only when VSX shows
no same-star entry. Saves JSON after every star."""
import json
import time
import warnings
from pathlib import Path
from urllib.parse import quote

import numpy as np
import requests

warnings.filterwarnings("ignore")

BASE = Path(__file__).resolve().parent
OUT = BASE / "vsx_crosscheck_2026-11-06.json"

from astroquery.mast import Catalogs  # noqa: E402
from astroquery.gaia import Gaia  # noqa: E402
from astropy.coordinates import SkyCoord  # noqa: E402
import astropy.units as u  # noqa: E402
from astropy.io.votable import parse_single_table  # noqa: E402
import io  # noqa: E402

TARGETS = [
    # tic, our_type, our_period_d, period_note
    ("167367406", "EW (contact binary)", 0.43461,
     "orbital period, twin-eclipse reading; photometric cycle 0.21731 d"),
    ("231124169", "EB (twin eclipsing binary)", 2.91396,
     "double-period fold; ellipsoidal +0.871% @ 92 sigma"),
    ("149975388", "EB", 28.38,
     "double-period fold 2P (BLS half-period 14.0768 d); wave +0.53% @ 17 sigma"),
    ("149914431", "EB", 27.45,
     "double-period fold 2P (BLS half-period 13.7264 d); wave +0.58% @ 23 sigma"),
    ("294671352", "EB", 26.25450,
     "odd/even fold at 26.25450 d; sweep 13.1286 d is half-period alias"),
    ("294782870", "EB", 49.04,
     "present/absent alternation at 49.04 d fold (2 x 24.52220 d); fold-depth caveat on record"),
    ("276791802", "LIKELY BINARY", 27.4587,
     "wave +0.211% @ 10.0 sigma at 27.4587 d"),
]

EB_TOKENS = {"E", "EA", "EB", "EW", "ELL"}


def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def clean(v):
    if v is None:
        return None
    if hasattr(v, "masked") and v.masked:
        return None
    if isinstance(v, (np.floating, np.integer)):
        f = float(v)
        return None if np.isnan(f) else f
    return str(v)


def tic_row(tic):
    tbl = Catalogs.query_criteria(catalog="TIC", ID=int(tic))
    for r in tbl:
        if str(r["ID"]) == tic or int(r["ID"]) == int(tic):
            return {k: clean(r[k]) for k in
                    ("ID", "ra", "dec", "Tmag", "GAIA", "GAIAmag", "Vmag",
                     "rad", "mass", "Teff", "contratio") if k in tbl.colnames}
    return None


def vsx_cone(ra, dec):
    """VSX website query.votable cone search, size 0.5 unit=2.
    Route validated 2026-11-06 on the TIC 308851365 control entry
    (returned exactly its ROT entry, P 0.75629). Separations are
    recomputed locally; entries <=30 arcsec are kept."""
    coords = f"{ra}+{dec}"
    url = ("https://vsx.aavso.org/index.php?view=query.votable"
           f"&coords={coords}&size=0.5&unit=2&order=9")
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    tab = parse_single_table(io.BytesIO(resp.content)).to_table()
    centre = SkyCoord(ra=ra, dec=dec, unit="deg")
    entries = []
    for r in tab:
        cra, cdec = str(r["radec2000"]).split(",")
        cra, cdec = float(cra), float(cdec)
        sep = centre.separation(SkyCoord(ra=cra, dec=cdec, unit="deg")).arcsec
        if sep > 30.0:
            continue
        maxm, minm = clean(r["maxMag"]), clean(r["minMag"])
        entries.append({
            "auid": clean(r["auid"]) or None,
            "name": clean(r["name"]),
            "const": clean(r["const"]),
            "ra_deg": cra, "dec_deg": cdec,
            "sep_arcsec": round(float(sep), 2),
            "var_type": clean(r["varType"]),
            "max_mag": maxm, "max_passband": clean(r["maxPass"]),
            "min_mag": minm, "min_passband": clean(r["minPass"]),
            "mag_range": (f"{maxm}-{minm} {clean(r['maxPass']) or ''}".strip()
                          if maxm is not None else None),
            "period_d": clean(r["period"]),
            "epoch": clean(r["epoch"]),
            "spec_type": clean(r["specType"]) or None,
            "discoverer": clean(r["disc"]) or None,
        })
    entries.sort(key=lambda e: e["sep_arcsec"])
    return entries, url


def gaia_secondary(ra, dec):
    """Gaia DR3: nearest gaia_source within 10 arcsec, then its
    vari_classifier_result and vari_eclipsing_binary rows."""
    out = {"catalogue": "Gaia DR3 (archive TAP)"}
    r_deg = 10.0 / 3600.0
    q1 = ("SELECT source_id, ra, dec, phot_g_mean_mag FROM gaiadr3.gaia_source "
          f"WHERE CONTAINS(POINT('ICRS', ra, dec), CIRCLE('ICRS', {ra}, {dec}, {r_deg})) = 1")
    job = Gaia.launch_job(q1)
    res = job.get_results()
    if len(res) == 0:
        out["gaia_source_within_10arcsec"] = []
        out["present_as_variable"] = False
        out["note"] = "no Gaia DR3 source within 10 arcsec (unexpected)"
        return out
    centre = SkyCoord(ra=ra, dec=dec, unit="deg")
    cands = []
    for r in res:
        sep = centre.separation(
            SkyCoord(ra=float(r["ra"]), dec=float(r["dec"]), unit="deg")).arcsec
        cands.append({"source_id": int(r["source_id"]),
                      "sep_arcsec": round(float(sep), 2),
                      "phot_g_mean_mag": float(r["phot_g_mean_mag"])})
    cands.sort(key=lambda c: c["sep_arcsec"])
    out["gaia_source_within_10arcsec"] = cands
    sid = cands[0]["source_id"]
    out["dr3_counterpart_source_id"] = sid
    out["dr3_counterpart_sep_arcsec"] = cands[0]["sep_arcsec"]
    q2 = ("SELECT best_class_name, best_class_score "
          f"FROM gaiadr3.vari_classifier_result WHERE source_id = {sid}")
    cls = Gaia.launch_job(q2).get_results()
    if len(cls):
        out["vari_classifier_result"] = {
            "best_class_name": str(cls["best_class_name"][0]),
            "best_class_score": float(cls["best_class_score"][0])}
    else:
        out["vari_classifier_result"] = None
    try:
        q3 = f"SELECT * FROM gaiadr3.vari_eclipsing_binary WHERE source_id = {sid}"
        eb = Gaia.launch_job(q3).get_results()
        if len(eb):
            row = {c: clean(eb[c][0]) for c in eb.colnames}
            out["vari_eclipsing_binary"] = row
        else:
            out["vari_eclipsing_binary"] = None
    except Exception as e:  # sub-check only; classifier result stands
        out["vari_eclipsing_binary"] = f"query failed: {type(e).__name__}"
    out["present_as_variable"] = bool(out.get("vari_classifier_result")) or \
        isinstance(out.get("vari_eclipsing_binary"), dict)
    return out


def type_is_eb_family(vartype):
    if not vartype:
        return False
    toks = [t.strip().upper().rstrip(":").split("/")[0]
            for t in str(vartype).replace("|", "+").split("+")]
    return any(t in EB_TOKENS for t in toks if t)


def period_relation(filed, ours):
    if filed is None or filed == 0:
        return "no period filed"
    rel = abs(filed - ours) / ours
    if rel <= 0.01:
        return "agree (<=1%)"
    if abs(filed - ours / 2) / (ours / 2) <= 0.01:
        return "filed is HALF our period"
    if abs(filed - 2 * ours) / (2 * ours) <= 0.01:
        return "filed is DOUBLE our period"
    return f"differ (rel. diff {rel:.1%})"


def main():
    results = {"batch": "VSX cross-check 2026-11-06",
               "vsx_route_primary": "VizieR B/vsx — FAILED from this VM (proxy drop, 2026-11-06)",
               "vsx_route_used": "VSX website query.votable cone service (vsx.aavso.org), validated on TIC 308851365 control entry",
               "stars": []}
    if OUT.exists():
        results = json.loads(OUT.read_text())
    done = {s["tic"] for s in results["stars"]}
    for tic, our_type, our_p, pnote in TARGETS:
        if tic in done:
            log(f"TIC {tic}: already done, skipping")
            continue
        log(f"=== TIC {tic} ===")
        star = {"tic": tic, "our_type": our_type, "our_period_d": our_p,
                "our_period_note": pnote}
        # A. identity
        try:
            row = tic_row(tic)
            star["tic_row"] = row
            star["id_verified"] = bool(row)
            if not row:
                star["classification"] = "CHECK FAILED"
                star["fail_reason"] = "TIC ID query returned no matching row"
                results["stars"].append(star)
                OUT.write_text(json.dumps(results, indent=2, default=str))
                continue
            ra, dec = float(row["ra"]), float(row["dec"])
            log(f"  TIC row: ra={ra:.6f} dec={dec:.6f} Tmag={row.get('Tmag')} "
                f"GAIA(DR2)={row.get('GAIA')}")
        except Exception as e:
            star["classification"] = "CHECK FAILED"
            star["fail_reason"] = f"TIC query: {type(e).__name__}: {str(e)[:200]}"
            results["stars"].append(star)
            OUT.write_text(json.dumps(results, indent=2, default=str))
            continue
        # B. VSX
        try:
            entries, url = vsx_cone(ra, dec)
            star["vsx_route"] = "VSX website query.votable"
            star["vsx_query_url"] = url
            star["vsx_entries_within_30arcsec"] = entries
            same = [e for e in entries if e["sep_arcsec"] <= 5.0]
            star["vsx_same_star_entries"] = same
            log(f"  VSX: {len(entries)} entr(ies) within 30 arcsec, "
                f"{len(same)} same-star (<=5 arcsec)")
            for e in same:
                log(f"    MATCH {e['name']} type={e['var_type']} P={e['period_d']}")
        except Exception as e:
            star["classification"] = "CHECK FAILED"
            star["fail_reason"] = f"VSX query: {type(e).__name__}: {str(e)[:200]}"
            results["stars"].append(star)
            OUT.write_text(json.dumps(results, indent=2, default=str))
            continue
        # classify / secondary
        if same:
            e = same[0]
            star["filed_vs_ours"] = {
                "type_eb_family": type_is_eb_family(e["var_type"]),
                "period_relation": period_relation(
                    float(e["period_d"]) if e["period_d"] not in (None, "") else None,
                    our_p)}
            if star["filed_vs_ours"]["type_eb_family"] and \
                    star["filed_vs_ours"]["period_relation"].startswith("agree"):
                star["classification"] = "IN VSX, TYPE+PERIOD AGREE"
            else:
                star["classification"] = "IN VSX, DISAGREES"
        else:
            # C. secondary
            try:
                sec = gaia_secondary(ra, dec)
                star["secondary"] = sec
                log(f"  Gaia DR3 secondary: present_as_variable="
                    f"{sec.get('present_as_variable')}")
            except Exception as ex:
                star["secondary"] = {"catalogue": "Gaia DR3 (archive TAP)",
                                     "error": f"{type(ex).__name__}: {str(ex)[:200]}"}
                log(f"  Gaia secondary FAILED: {ex}")
            if isinstance(star.get("secondary"), dict) and \
                    star["secondary"].get("present_as_variable"):
                star["classification"] = \
                    "ABSENT IN VSX (present in Gaia DR3) — new-filing candidate, known variable elsewhere"
            elif isinstance(star.get("secondary"), dict) and \
                    "error" not in star["secondary"]:
                star["classification"] = "ABSENT EVERYWHERE CHECKED"
            else:
                star["classification"] = \
                    "ABSENT IN VSX (secondary check failed) — new-filing candidate, secondary unresolved"
        results["stars"].append(star)
        OUT.write_text(json.dumps(results, indent=2, default=str))
        log(f"  -> {star['classification']}")
    log("BATCH COMPLETE")


if __name__ == "__main__":
    main()
