"""Big-fish gauntlet stage 0b — TIC 309760851: VSX (robust) + Gaia via AIP.

Fix-ups for stage 0's two failed routes:
  * VSX query.votable with a tolerant radec2000 parser (never silently
    drops a row: unparseable rows are reported raw), target cone 120"
    plus the TIC 308851365 positive control.
  * Gaia DR3 via the AIP TAP mirror (ESA TAP hit an SSL failure):
    cone 150", plus vari_classifier_result / vari_eclipsing_binary rows
    for the target and the two prime neighbour suspects.
Output: vetting_results/bf851_stage0b.json
"""
import io
import json
import re

import requests
from astropy.coordinates import SkyCoord
from astropy.io.votable import parse_single_table

RA, DEC = 80.1053299464223, -65.0991806063304
T = SkyCoord(ra=RA, dec=DEC, unit="deg")
CONTROL_RA, CONTROL_DEC = 100.917, -67.7336  # placeholder, replaced below
OUT = "vetting_results/bf851_stage0b.json"
res = {}

# control position comes from stage 0's saved positive-control attempt:
# TIC 308851365 lightkurve median position is fetched fresh here instead.
import lightkurve as lk
import numpy as np
sr = lk.search_lightcurve("TIC 308851365")
t = sr.table
cpos = (float(np.median([float(x) for x in t["s_ra"]])),
        float(np.median([float(x) for x in t["s_dec"]])))
C = SkyCoord(ra=cpos[0], dec=cpos[1], unit="deg")
print("control centre:", cpos, flush=True)

FLOAT2 = re.compile(r"(-?\d+\.\d+)\D+(-?\d+\.\d+)")


def vsx_cone(centre, label):
    coords = f"{centre.ra.deg}+{centre.dec.deg}"
    url = ("https://vsx.aavso.org/index.php?view=query.votable"
           f"&coords={coords}&size=2.0&unit=2&order=9")
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    tab = parse_single_table(io.BytesIO(resp.content)).to_table()
    entries, bad = [], []
    for r in tab:
        raw = str(r["radec2000"])
        m = FLOAT2.search(raw)
        if not m:
            bad.append({"name": str(r["name"]), "radec2000_raw": raw,
                        "varType": str(r["varType"]), "period": str(r["period"])})
            continue
        cra, cdec = float(m.group(1)), float(m.group(2))
        c = SkyCoord(ra=cra, dec=cdec, unit="deg")
        sep = round(float(centre.separation(c).arcsec), 2)
        e = {"name": str(r["name"]), "var_type": str(r["varType"]),
             "ra_deg": cra, "dec_deg": cdec, "sep_arcsec": sep,
             "max_mag": str(r["maxMag"]), "min_mag": str(r["minMag"]),
             "period": str(r["period"]), "epoch": str(r["epoch"])}
        if sep <= 120.0:
            entries.append(e)
    entries.sort(key=lambda x: x["sep_arcsec"])
    print(f"VSX {label}: {len(entries)} entries <=120\", "
          f"{len(bad)} unparseable rows", flush=True)
    for e in entries:
        print(f"   {e['name']} type {e['var_type']} P {e['period']} "
              f"sep {e['sep_arcsec']}\"", flush=True)
    for b in bad:
        print(f"   UNPARSED ROW: {b}", flush=True)
    return {"query_url": url, "entries": entries, "unparseable": bad}


res["vsx_target"] = vsx_cone(T, "target TIC 309760851")
res["vsx_positive_control"] = vsx_cone(C, "control TIC 308851365")

# ---------------------------------------------------------------- Gaia AIP
AIP = "https://gaia.aip.de/tap/sync"


def fnum(v):
    try:
        x = float(v)
        return None if x != x else x
    except (TypeError, ValueError):
        return None


def aip_query(adql):
    params = {"REQUEST": "doQuery", "LANG": "ADQL", "FORMAT": "votable",
              "QUERY": adql}
    r = requests.get(AIP, params=params, timeout=180)
    r.raise_for_status()
    tab = parse_single_table(io.BytesIO(r.content)).to_table()
    if "datalinkID" in tab.colnames and "source_id" not in tab.colnames:
        tab.rename_column("datalinkID", "source_id")
    out = []
    for row in tab:
        d = {}
        for c in tab.colnames:
            v = row[c]
            if hasattr(v, "decode"):
                v = v.decode()
            d[c] = v if isinstance(v, str) else fnum(v)
        out.append(d)
    return out


q = ("SELECT source_id, ra, dec, phot_g_mean_mag, bp_rp, teff_gspphot, "
     "radius_gspphot FROM gaiadr3.gaia_source WHERE 1=CONTAINS("
     f"POINT('ICRS', ra, dec), CIRCLE('ICRS', {RA}, {DEC}, {150/3600.0}))")
rows = aip_query(q)
for r in rows:
    c = SkyCoord(ra=r["ra"], dec=r["dec"], unit="deg")
    r["sep_arcsec"] = round(float(T.separation(c).arcsec), 2)
rows.sort(key=lambda x: x["sep_arcsec"])
res["gaia_cone_150"] = rows
print(f"Gaia cone 150\": {len(rows)} sources; nearest:", flush=True)
for r in rows[:6]:
    print(f"   {r['source_id']} sep {r['sep_arcsec']}\" G {r['phot_g_mean_mag']} "
          f"bp_rp {r['bp_rp']} R {r.get('radius_gspphot')}", flush=True)

# variability rows: target + prime suspects (from stage 0 census)
s0 = json.load(open("vetting_results/bf851_stage0.json"))
suspects = {309760851: "4661020662808439680"}
for n in s0["tic_within_150arcsec"]:
    if n["ID"] in (309760854, 309760840, 309760844, 309760852):
        suspects[n["ID"]] = n["GAIA"]
res["vari"] = {}
for tic, gid in suspects.items():
    entry = {}
    for tbl, cols in (
        ("gaiadr3.vari_classifier_result",
         "best_class_name, best_class_score"),
        ("gaiadr3.vari_eclipsing_binary",
         "global_ranking, period, period_error"),
    ):
        try:
            got = aip_query(f"SELECT {cols} FROM {tbl} "
                            f"WHERE source_id = {gid}")
            entry[tbl] = got
        except Exception as e:
            entry[tbl] = {"error": f"{type(e).__name__}: {str(e)[:140]}"}
    res["vari"][str(tic)] = entry
    print(f"TIC {tic} (Gaia {gid}): {entry}", flush=True)

with open(OUT, "w") as f:
    json.dump(res, f, indent=1, default=str)
print("wrote", OUT, flush=True)
