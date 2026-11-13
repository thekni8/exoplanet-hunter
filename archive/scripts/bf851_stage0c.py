"""Big-fish gauntlet stage 0c — TIC 309760851: VSX (raw-XML parse) + Gaia AIP.

Fixes vs 0b: VSX VOTABLE parsed as raw XML text (astropy turned its string
columns into single chars); AIP cone query drops radius_gspphot (absent on
the AIP mirror); positive-control centre from the TIC catalogue row by ID.
Output: vetting_results/bf851_stage0c.json
"""
import io
import json
import re
import xml.etree.ElementTree as ET

import requests
from astropy.coordinates import SkyCoord
from astropy.io.votable import parse_single_table
from astroquery.mast import Catalogs

RA, DEC = 80.1053299464223, -65.0991806063304
T = SkyCoord(ra=RA, dec=DEC, unit="deg")
OUT = "vetting_results/bf851_stage0c.json"
res = {}

# ------------------------------------------------------------ control centre
tab = Catalogs.query_criteria(catalog="TIC", ID=308851365)
crow = tab[0]
C = SkyCoord(ra=float(crow["ra"]), dec=float(crow["dec"]), unit="deg")
res["control_tic_row"] = {"ra": float(crow["ra"]), "dec": float(crow["dec"]),
                          "Tmag": float(crow["Tmag"])}
print("control centre (TIC 308851365):", C.ra.deg, C.dec.deg, flush=True)

# --------------------------------------------------------------------- VSX
FLOAT2 = re.compile(r"(-?\d+\.\d+)\D+(-?\d+\.\d+)")


def vsx_cone(centre, label):
    coords = f"{centre.ra.deg}+{centre.dec.deg}"
    url = ("https://vsx.aavso.org/index.php?view=query.votable"
           f"&coords={coords}&size=2.0&unit=2&order=9")
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    root = ET.fromstring(resp.content)
    fields = [f.get("name") for f in root.iter("FIELD")]
    entries = []
    nrows = 0
    for tr in root.iter("TR"):
        tds = [(td.text or "").strip() for td in tr.iter("TD")]
        if len(tds) != len(fields):
            continue
        nrows += 1
        row = dict(zip(fields, tds))
        m = FLOAT2.search(row.get("Coords(J2000)", ""))
        if not m:
            entries.append({"unparsed": row})
            continue
        cra, cdec = float(m.group(1)), float(m.group(2))
        c = SkyCoord(ra=cra, dec=cdec, unit="deg")
        sep = round(float(centre.separation(c).arcsec), 2)
        if sep <= 120.0:
            entries.append({"name": row.get("Name"),
                            "var_type": row.get("VarType"),
                            "ra_deg": cra, "dec_deg": cdec, "sep_arcsec": sep,
                            "max_mag": row.get("MaxMag"),
                            "min_mag": row.get("MinMag"),
                            "period": row.get("Period"),
                            "epoch": row.get("Epoch")})
    entries.sort(key=lambda x: x.get("sep_arcsec", 1e9))
    print(f"VSX {label}: {nrows} rows total, {len(entries)} entries <=120\"",
          flush=True)
    for e in entries:
        print(f"   {e}", flush=True)
    return {"query_url": url, "n_rows_total": nrows, "entries": entries}


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


q = ("SELECT source_id, ra, dec, phot_g_mean_mag, bp_rp, teff_gspphot "
     "FROM gaiadr3.gaia_source WHERE 1=CONTAINS("
     f"POINT('ICRS', ra, dec), CIRCLE('ICRS', {RA}, {DEC}, {150/3600.0}))")
rows = aip_query(q)
for r in rows:
    c = SkyCoord(ra=r["ra"], dec=r["dec"], unit="deg")
    r["sep_arcsec"] = round(float(T.separation(c).arcsec), 2)
rows.sort(key=lambda x: x["sep_arcsec"])
res["gaia_cone_150"] = rows
print(f"Gaia cone 150\": {len(rows)} sources; nearest 6:", flush=True)
for r in rows[:6]:
    print(f"   {r['source_id']} sep {r['sep_arcsec']}\" "
          f"G {r['phot_g_mean_mag']} bp_rp {r['bp_rp']} teff {r['teff_gspphot']}",
          flush=True)

s0 = json.load(open("vetting_results/bf851_stage0.json"))
suspects = {309760851: "4661020662808439680"}
for n in s0["tic_within_150arcsec"]:
    if n["ID"] in (309760854, 309760840, 309760844, 309760852):
        suspects[n["ID"]] = n["GAIA"]
ids = ",".join(suspects.values())
res["vari"] = {}
for tbl, cols in (
    ("gaiadr3.vari_classifier_result", "source_id, best_class_name, best_class_score"),
    ("gaiadr3.vari_eclipsing_binary", "*"),
):
    try:
        got = aip_query(f"SELECT {cols} FROM {tbl} WHERE source_id IN ({ids})")
        res["vari"][tbl] = got
        print(f"{tbl}: {len(got)} rows", flush=True)
        for g in got:
            print("   ", g, flush=True)
    except Exception as e:
        res["vari"][tbl] = {"error": f"{type(e).__name__}: {str(e)[:140]}"}
        print(f"{tbl} FAILED:", e, flush=True)
res["vari_subjects"] = {str(k): v for k, v in suspects.items()}

with open(OUT, "w") as f:
    json.dump(res, f, indent=1, default=str)
print("wrote", OUT, flush=True)
