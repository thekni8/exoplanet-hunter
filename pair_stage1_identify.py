"""Pair vetting stage 1 — TIC 31315594 (A, deep) vs TIC 31315605 (B, shallow).

Covers task stages 1+2 and the identification half of stage 3:
  * exact TIC rows for both stars + separation / PA / TESS-pixel distance
  * every TIC source within 2.5 arcmin of either star (QLP-aperture census)
  * Gaia DR3 cone (sync TAP) + vari_classifier_result / vari_eclipsing_binary
    rows for both stars and bright neighbours
  * VSX cones at 120 arcsec around BOTH stars (query.votable route)
  * lightkurve product inventory exactly as hunter.py searches it
    (author=[SPOC, TESS-SPOC, QLP], cap 20) -> which sectors/products the
    sweep could have used
Read-only; standalone (no hunter.py import). Output: pair_stage1.json
"""
import io
import json
import time

import numpy as np
import requests
from astropy import units as u
from astropy.coordinates import SkyCoord
from astropy.io.votable import parse_single_table
from astroquery.gaia import Gaia
from astroquery.mast import Catalogs
import lightkurve as lk

A_ID, B_ID = 31315594, 31315605
OUT = "pair_stage1.json"
res = {"pair": {"A_deep": A_ID, "B_shallow": B_ID}}


def clean(v):
    if v is None:
        return None
    try:
        if hasattr(v, "mask") and v.mask:
            return None
    except Exception:
        pass
    if isinstance(v, (np.floating,)):
        v = float(v)
        return None if not np.isfinite(v) else v
    if isinstance(v, (np.integer,)):
        return int(v)
    return v


def tic_row(tab, want_id):
    for r in tab:
        if int(r["ID"]) == int(want_id):
            return {k: clean(r[k]) for k in
                    ("ID", "ra", "dec", "Tmag", "Vmag", "GAIA", "GAIAmag",
                     "rad", "mass", "Teff", "contratio", "lum", "TWOMASS")
                    if k in tab.colnames}
    return None


# ---------------------------------------------------------------- inventory
# (also yields positions: MAST CAOM s_ra / s_dec of each product)
positions = {}
for tic in (A_ID, B_ID):
    ent = {}
    sr = lk.search_lightcurve(f"TIC {tic}",
                              author=["SPOC", "TESS-SPOC", "QLP"])
    ent["n_products_filtered"] = len(sr)
    rows = []
    if len(sr):
        t = sr.table
        ent["search_columns"] = list(t.colnames)
        for r in t:
            rows.append({c: (str(r[c]) if r[c] is not None else None)
                         for c in t.colnames})
        ras = np.array([float(x) for x in t["s_ra"]], dtype=float)
        decs = np.array([float(x) for x in t["s_dec"]], dtype=float)
        positions[tic] = (float(np.median(ras)), float(np.median(decs)))
    ent["products_filtered"] = rows
    ent["sweep_fetch_first20"] = rows[:20]
    sr_all = lk.search_lightcurve(f"TIC {tic}")
    ent["n_products_unfiltered"] = len(sr_all)
    if len(sr_all):
        ent["unfiltered_authors"] = sorted({str(a) for a in sr_all.table["author"]})
    res.setdefault("inventory", {})[str(tic)] = ent
    print(f"TIC {tic}: filtered products={ent['n_products_filtered']} "
          f"unfiltered={ent['n_products_unfiltered']} pos={positions.get(tic)}",
          flush=True)

A = SkyCoord(ra=positions[A_ID][0], dec=positions[A_ID][1], unit="deg")
B = SkyCoord(ra=positions[B_ID][0], dec=positions[B_ID][1], unit="deg")
sep = A.separation(B)
res["pair"]["separation_arcsec"] = float(sep.arcsec)
res["pair"]["separation_tess_pix"] = float(sep.arcsec / 21.0)
res["pair"]["pa_A_to_B_deg"] = float(A.position_angle(B).deg)
print(f"separation A-B: {sep.arcsec:.2f} arcsec = {sep.arcsec / 21.0:.2f} px, "
      f"PA {A.position_angle(B).deg:.1f}", flush=True)

# ---------------------------------------------------------------- TIC rows
for tic, coord in ((A_ID, A), (B_ID, B)):
    tab = Catalogs.query_region(coord, radius=6 * u.arcsec, catalog="TIC")
    row = tic_row(tab, tic)
    res.setdefault("tic_rows", {})[str(tic)] = row
    print(f"TIC {tic} row: {row}", flush=True)

# ------------------------------------------------------- neighbourhood census
nb = {}
for tic, coord in ((A_ID, A), (B_ID, B)):
    tab = Catalogs.query_region(coord, radius=150 * u.arcsec, catalog="TIC")
    for r in tab:
        i = int(r["ID"])
        c = SkyCoord(ra=float(r["ra"]), dec=float(r["dec"]), unit="deg")
        nb[i] = {
            "ID": i, "ra": float(r["ra"]), "dec": float(r["dec"]),
            "Tmag": clean(r["Tmag"]), "GAIA": str(r["GAIA"]),
            "GAIAmag": clean(r["GAIAmag"]), "rad": clean(r["rad"]),
            "Teff": clean(r["Teff"]), "contratio": clean(r["contratio"]),
            "sep_from_A_arcsec": float(A.separation(c).arcsec),
            "sep_from_B_arcsec": float(B.separation(c).arcsec),
        }
nb = sorted(nb.values(), key=lambda x: min(x["sep_from_A_arcsec"],
                                           x["sep_from_B_arcsec"]))
res["tic_within_150arcsec_of_either"] = nb
print(f"TIC within 150\" of either star: {len(nb)}", flush=True)
for r in nb[:12]:
    print(f"   TIC {r['ID']} Tmag {r['Tmag']} sepA {r['sep_from_A_arcsec']:.1f}\" "
          f"sepB {r['sep_from_B_arcsec']:.1f}\"", flush=True)

# ---------------------------------------------------------------- Gaia cone
mid = SkyCoord(ra=(A.ra.deg + B.ra.deg) / 2, dec=(A.dec.deg + B.dec.deg) / 2,
               unit="deg")
r_cone = (150.0 + sep.arcsec / 2.0 + 5.0) / 3600.0
try:
    q = ("SELECT source_id, ra, dec, phot_g_mean_mag, bp_rp, teff_gspphot "
         "FROM gaiadr3.gaia_source WHERE 1=CONTAINS("
         f"POINT('ICRS', ra, dec), CIRCLE('ICRS', {mid.ra.deg}, {mid.dec.deg}, "
         f"{r_cone}))")
    t = Gaia.launch_job(q).get_results()
    grows = []
    for r in t:
        c = SkyCoord(ra=float(r["ra"]), dec=float(r["dec"]), unit="deg")
        grows.append({
            "source_id": int(r["source_id"]),
            "ra": float(r["ra"]), "dec": float(r["dec"]),
            "phot_g_mean_mag": float(r["phot_g_mean_mag"]),
            "bp_rp": clean(r["bp_rp"]), "teff_gspphot": clean(r["teff_gspphot"]),
            "sep_from_A_arcsec": float(A.separation(c).arcsec),
            "sep_from_B_arcsec": float(B.separation(c).arcsec),
        })
    grows.sort(key=lambda x: min(x["sep_from_A_arcsec"], x["sep_from_B_arcsec"]))
    res["gaia_cone"] = grows
    print(f"Gaia cone: {len(grows)} sources", flush=True)
except Exception as e:
    res["gaia_cone"] = {"error": f"{type(e).__name__}: {str(e)[:200]}"}
    print("Gaia cone FAILED:", e, flush=True)

# ------------------------------------------------------- Gaia variable tables
try:
    cand = {}
    for g in res.get("gaia_cone", []):
        if isinstance(g, dict) and g.get("phot_g_mean_mag") is not None \
                and g["phot_g_mean_mag"] <= 17.0:
            cand[g["source_id"]] = g
    # always include the nearest Gaia source to each star regardless of mag
    for key in ("gaia_cone",):
        rows = res.get(key, [])
        if isinstance(rows, list):
            for star in (A, B):
                best = min(rows, key=lambda g: star.separation(
                    SkyCoord(ra=g["ra"], dec=g["dec"], unit="deg")).arcsec)
                cand[best["source_id"]] = best
    ids = ",".join(str(i) for i in sorted(cand))
    vari = {}
    for table, cols in (
            ("gaiadr3.vari_classifier_result",
             "source_id, best_class_name, best_class_score"),
            ("gaiadr3.vari_eclipsing_binary", "*")):
        try:
            qq = f"SELECT {cols} FROM {table} WHERE source_id IN ({ids})"
            tt = Gaia.launch_job(qq).get_results()
            out = []
            for r in tt:
                out.append({c: clean(r[c]) if not isinstance(r[c], str)
                            else r[c] for c in tt.colnames})
            vari[table] = out
            print(f"{table}: {len(out)} rows for {len(cand)} candidates",
                  flush=True)
        except Exception as e:
            vari[table] = {"error": f"{type(e).__name__}: {str(e)[:200]}"}
            print(f"{table} FAILED:", e, flush=True)
    res["gaia_vari"] = {"candidate_ids": sorted(cand), "tables": vari}
except Exception as e:
    res["gaia_vari"] = {"error": f"{type(e).__name__}: {str(e)[:200]}"}
    print("Gaia vari FAILED:", e, flush=True)

# ---------------------------------------------------------------- VSX cones
def vsx_cone(centre, size_arcmin=2.0):
    coords = f"{centre.ra.deg}+{centre.dec.deg}"
    url = ("https://vsx.aavso.org/index.php?view=query.votable"
           f"&coords={coords}&size={size_arcmin}&unit=2&order=9")
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    tab = parse_single_table(io.BytesIO(resp.content)).to_table()
    entries = []
    for r in tab:
        cra, cdec = str(r["radec2000"]).split(",")
        cra, cdec = float(cra), float(cdec)
        c = SkyCoord(ra=cra, dec=cdec, unit="deg")
        e = {
            "auid": clean(r["auid"]) or None,
            "name": clean(r["name"]), "const": clean(r["const"]),
            "ra_deg": cra, "dec_deg": cdec,
            "sep_from_centre_arcsec": round(float(centre.separation(c).arcsec), 2),
            "sep_from_A_arcsec": round(float(A.separation(c).arcsec), 2),
            "sep_from_B_arcsec": round(float(B.separation(c).arcsec), 2),
            "var_type": clean(r["varType"]),
            "max_mag": clean(r["maxMag"]), "max_passband": clean(r["maxPass"]),
            "min_mag": clean(r["minMag"]), "min_passband": clean(r["minPass"]),
            "period_d": clean(r["period"]), "epoch": clean(r["epoch"]),
            "spec_type": clean(r["specType"]) or None,
            "discoverer": clean(r["disc"]) or None,
        }
        if e["sep_from_centre_arcsec"] <= 120.0:
            entries.append(e)
    entries.sort(key=lambda x: x["sep_from_centre_arcsec"])
    return entries, url

res["vsx"] = {}
for label, centre in (("around_A", A), ("around_B", B)):
    try:
        entries, url = vsx_cone(centre)
        res["vsx"][label] = {"query_url": url, "entries": entries}
        print(f"VSX {label}: {len(entries)} entries within 120\"", flush=True)
        for e in entries:
            print(f"   {e['name']} type {e['var_type']} P {e['period_d']} "
                  f"sepA {e['sep_from_A_arcsec']} sepB {e['sep_from_B_arcsec']}",
                  flush=True)
    except Exception as e:
        res["vsx"][label] = {"error": f"{type(e).__name__}: {str(e)[:200]}"}
        print(f"VSX {label} FAILED:", e, flush=True)

with open(OUT, "w") as f:
    json.dump(res, f, indent=1, default=str)
print("wrote", OUT)
