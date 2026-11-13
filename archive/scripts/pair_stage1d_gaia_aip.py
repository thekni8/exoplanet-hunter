"""Pair vetting stage 1d: Gaia DR3 via AIP TAP mirror, VOTABLE parsing.

AIP ignored FORMAT=csv and returned a proper results VOTABLE — parse it
with astropy (AIP votables carry datatypes, unlike VSX's). Cone + vari
tables for both stars' DR3 counterparts and all bright (G<=17) sources
within 150" of either star. Merges into pair_stage1.json. Read-only.
"""
import io
import json

import requests
from astropy.coordinates import SkyCoord
from astropy.io.votable import parse_single_table

A_ID, B_ID = 31315594, 31315605
with open("pair_stage1.json") as f:
    res = json.load(f)

A = SkyCoord(ra=res["tic_rows"][str(A_ID)]["ra"],
             dec=res["tic_rows"][str(A_ID)]["dec"], unit="deg")
B = SkyCoord(ra=res["tic_rows"][str(B_ID)]["ra"],
             dec=res["tic_rows"][str(B_ID)]["dec"], unit="deg")
sep = A.separation(B)
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
        tab.rename_column("datalinkID", "source_id")  # AIP TAP quirk
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


mid = SkyCoord(ra=(A.ra.deg + B.ra.deg) / 2, dec=(A.dec.deg + B.dec.deg) / 2,
               unit="deg")
r_cone = (150.0 + sep.arcsec / 2.0 + 5.0) / 3600.0
q = ("SELECT source_id, ra, dec, phot_g_mean_mag, bp_rp, teff_gspphot "
     "FROM gaiadr3.gaia_source WHERE 1=CONTAINS("
     f"POINT('ICRS', ra, dec), CIRCLE('ICRS', {mid.ra.deg}, {mid.dec.deg}, "
     f"{r_cone}))")
rows = aip_query(q)
grows = []
for r in rows:
    c = SkyCoord(ra=r["ra"], dec=r["dec"], unit="deg")
    grows.append({
        "source_id": int(r["source_id"]), "ra": r["ra"], "dec": r["dec"],
        "phot_g_mean_mag": r["phot_g_mean_mag"], "bp_rp": r["bp_rp"],
        "teff_gspphot": r["teff_gspphot"],
        "sep_from_A_arcsec": float(A.separation(c).arcsec),
        "sep_from_B_arcsec": float(B.separation(c).arcsec),
    })
grows.sort(key=lambda x: min(x["sep_from_A_arcsec"], x["sep_from_B_arcsec"]))
res["gaia_cone"] = grows
res["gaia_route"] = "AIP TAP mirror (gaia.aip.de/tap), sync VOTABLE"
print(f"Gaia cone via AIP: {len(grows)} sources", flush=True)
for g in grows[:8]:
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
        print(f"{table}: {len(out)} rows / {len(cand)} candidates", flush=True)
        for o in out:
            print("   ", o, flush=True)
    except Exception as e:
        vari[table] = {"error": f"{type(e).__name__}: {str(e)[:200]}"}
        print(f"{table} FAILED:", e, flush=True)
res["gaia_vari"] = {"candidate_ids": sorted(cand), "tables": vari}

# DR3 counterparts of the two TIC stars (nearest cone source)
for label, star in (("A", A), ("B", B)):
    best = min(grows, key=lambda g: star.separation(
        SkyCoord(ra=g["ra"], dec=g["dec"], unit="deg")).arcsec)
    res.setdefault("gaia_counterparts", {})[label] = best
    print(f"Gaia DR3 counterpart {label}: {best['source_id']} "
          f"at {min(best['sep_from_A_arcsec'] if label == 'A' else best['sep_from_B_arcsec'], 999):.2f} arcsec, G {best['phot_g_mean_mag']}",
          flush=True)

with open("pair_stage1.json", "w") as f:
    json.dump(res, f, indent=1, default=str)
print("updated pair_stage1.json")
