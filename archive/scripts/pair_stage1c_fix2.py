"""Pair vetting stage 1c: VSX via raw-XML parsing + Gaia via AIP TAP mirror.

Stage 1/1b failures being fixed:
  * VSX query.votable returns FIELDs with no datatype -> astropy reads
    1-char values. Parse the TABLEDATA with ElementTree instead.
  * astroquery Gaia (ESAC TAP) dies with SSL WRONG_VERSION_NUMBER through
    this VM's proxy (all retries). The AIP Gaia mirror TAP
    (gaia.aip.de/tap) speaks the same gaiadr3 schema — try it via plain
    requests sync queries.
Merges into pair_stage1.json. Read-only.
"""
import csv
import io
import json
import urllib.parse
import xml.etree.ElementTree as ET

import requests
from astropy import units as u
from astropy.coordinates import SkyCoord

A_ID, B_ID = 31315594, 31315605
with open("pair_stage1.json") as f:
    res = json.load(f)

A = SkyCoord(ra=res["tic_rows"][str(A_ID)]["ra"],
             dec=res["tic_rows"][str(A_ID)]["dec"], unit="deg")
B = SkyCoord(ra=res["tic_rows"][str(B_ID)]["ra"],
             dec=res["tic_rows"][str(B_ID)]["dec"], unit="deg")
sep = A.separation(B)


def fnum(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------- VSX
def vsx_cone_xml(centre, size_arcmin=2.0):
    coords = f"{centre.ra.deg}+{centre.dec.deg}"
    url = ("https://vsx.aavso.org/index.php?view=query.votable"
           f"&coords={coords}&size={size_arcmin}&unit=2&order=9")
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    root = ET.fromstring(resp.content)
    fields = [f.get("name") for f in root.iter("FIELD")]
    entries = []
    for tr in root.iter("TR"):
        cells = [(td.text or "").strip() if td.text is not None else ""
                 for td in tr.iter("TD")]
        if len(cells) != len(fields):
            continue
        row = dict(zip(fields, cells))
        try:
            cra, cdec = [float(x) for x in row["Coords(J2000)"].split(",")]
        except Exception:
            continue
        c = SkyCoord(ra=cra, dec=cdec, unit="deg")
        e = {
            "auid": row.get("AUID") or None,
            "name": row.get("Name"), "const": row.get("Const"),
            "ra_deg": cra, "dec_deg": cdec,
            "sep_from_centre_arcsec": round(float(centre.separation(c).arcsec), 2),
            "sep_from_A_arcsec": round(float(A.separation(c).arcsec), 2),
            "sep_from_B_arcsec": round(float(B.separation(c).arcsec), 2),
            "var_type": row.get("VarType"),
            "max_mag": fnum(row.get("MaxMag")),
            "max_passband": row.get("MaxMagPass") or None,
            "min_mag": fnum(row.get("MinMag")),
            "min_passband": row.get("MinMagPass") or None,
            "period_d": fnum(row.get("Period")),
            "epoch": fnum(row.get("Epoch")),
            "spec_type": row.get("SpecType") or None,
            "discoverer": row.get("Discoverer") or None,
        }
        if e["sep_from_centre_arcsec"] <= 120.0:
            entries.append(e)
    entries.sort(key=lambda x: x["sep_from_centre_arcsec"])
    return entries, url


res["vsx"] = {}
for label, centre in (("around_A", A), ("around_B", B)):
    try:
        entries, url = vsx_cone_xml(centre)
        res["vsx"][label] = {"query_url": url, "entries": entries,
                             "route": "query.votable + ElementTree parse"}
        print(f"VSX {label}: {len(entries)} entries <=120\"", flush=True)
        for e in entries:
            print(f"   {e['name']} type {e['var_type']} P {e['period_d']} "
                  f"max {e['max_mag']} min {e['min_mag']} "
                  f"sepA {e['sep_from_A_arcsec']} sepB {e['sep_from_B_arcsec']}",
                  flush=True)
    except Exception as e:
        res["vsx"][label] = {"error": f"{type(e).__name__}: {str(e)[:200]}"}
        print(f"VSX {label} FAILED:", e, flush=True)

# ------------------------------------------------------------- Gaia via AIP
AIP = "https://gaia.aip.de/tap/sync"


def aip_query(adql):
    params = {"REQUEST": "doQuery", "LANG": "ADQL", "FORMAT": "csv",
              "QUERY": adql}
    r = requests.get(AIP, params=params, timeout=120)
    r.raise_for_status()
    txt = r.text
    if "VOTABLE" in txt[:200] or txt.strip().startswith("<?xml"):
        raise RuntimeError("AIP returned XML (likely an error document): "
                           + txt[:300].replace("\n", " "))
    rows = list(csv.DictReader(io.StringIO(txt)))
    return rows


mid = SkyCoord(ra=(A.ra.deg + B.ra.deg) / 2, dec=(A.dec.deg + B.dec.deg) / 2,
               unit="deg")
r_cone = (150.0 + sep.arcsec / 2.0 + 5.0) / 3600.0
try:
    q = ("SELECT source_id, ra, dec, phot_g_mean_mag, bp_rp, teff_gspphot "
         "FROM gaiadr3.gaia_source WHERE 1=CONTAINS("
         f"POINT('ICRS', ra, dec), CIRCLE('ICRS', {mid.ra.deg}, {mid.dec.deg}, "
         f"{r_cone}))")
    rows = aip_query(q)
    grows = []
    for r in rows:
        c = SkyCoord(ra=float(r["ra"]), dec=float(r["dec"]), unit="deg")
        grows.append({
            "source_id": int(r["source_id"]),
            "ra": float(r["ra"]), "dec": float(r["dec"]),
            "phot_g_mean_mag": fnum(r["phot_g_mean_mag"]),
            "bp_rp": fnum(r["bp_rp"]), "teff_gspphot": fnum(r["teff_gspphot"]),
            "sep_from_A_arcsec": float(A.separation(c).arcsec),
            "sep_from_B_arcsec": float(B.separation(c).arcsec),
        })
    grows.sort(key=lambda x: min(x["sep_from_A_arcsec"], x["sep_from_B_arcsec"]))
    res["gaia_cone"] = grows
    res["gaia_route"] = "AIP TAP mirror (gaia.aip.de/tap), sync CSV"
    print(f"Gaia cone via AIP: {len(grows)} sources", flush=True)
    for g in grows[:6]:
        print(f"   {g['source_id']} G {g['phot_g_mean_mag']} "
              f"sepA {g['sep_from_A_arcsec']:.2f} sepB {g['sep_from_B_arcsec']:.2f}",
              flush=True)

    cand = {g["source_id"]: g for g in grows
            if g["phot_g_mean_mag"] is not None and g["phot_g_mean_mag"] <= 17.0}
    for star in (A, B):
        best = min(grows, key=lambda g: star.separation(
            SkyCoord(ra=g["ra"], dec=g["dec"], unit="deg")).arcsec)
        cand[best["source_id"]] = best
    ids = ",".join(str(i) for i in sorted(cand))
    vari = {}
    for table, cols in (
            ("gaiadr3.vari_classifier_result",
             "source_id, best_class_name, best_class_score"),
            ("gaiadr3.vari_eclipsing_binary", "*")):
        try:
            out = aip_query(f"SELECT {cols} FROM {table} "
                            f"WHERE source_id IN ({ids})")
            vari[table] = out
            print(f"{table}: {len(out)} rows / {len(cand)} candidates",
                  flush=True)
            for o in out:
                print("   ", o, flush=True)
        except Exception as e:
            vari[table] = {"error": f"{type(e).__name__}: {str(e)[:200]}"}
            print(f"{table} FAILED:", e, flush=True)
    res["gaia_vari"] = {"candidate_ids": sorted(cand), "tables": vari}
except Exception as e:
    res["gaia_cone"] = {"error": f"{type(e).__name__}: {str(e)[:300]}"}
    print("Gaia via AIP FAILED:", e, flush=True)

with open("pair_stage1.json", "w") as f:
    json.dump(res, f, indent=1, default=str)
print("updated pair_stage1.json")
