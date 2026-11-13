"""Big-fish gauntlet stage 0 — TIC 309760851 identification & catalogues.

Read-only:
  * lightkurve product inventory exactly as hunter.py searches it
    (author=[SPOC, TESS-SPOC, QLP]) -> positions, sectors, authors
  * exact TIC row + every TIC source within 150 arcsec (aperture census)
  * Gaia DR3 cone 150 arcsec + vari_classifier_result for the target
  * VSX cone 120 arcsec via query.votable route, PLUS a positive control
    cone on TIC 308851365 (must return its known VSX entry)
Output: vetting_results/bf851_stage0.json
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

TIC = 309760851
CONTROL_TIC = 308851365
OUT = "vetting_results/bf851_stage0.json"
res = {"tic": TIC, "sweep": {"period_d": 0.7083, "sde": 19.2,
                             "depth_pct": 0.12, "persistence": "11/12"}}


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


# ---------------------------------------------------------------- inventory
def inventory(tic):
    # mirror hunter.py exactly: author-filtered first, unfiltered fallback
    sr = lk.search_lightcurve(f"TIC {tic}",
                              author=["SPOC", "TESS-SPOC", "QLP"])
    branch = "author_filtered"
    if len(sr) == 0:
        sr = lk.search_lightcurve(f"TIC {tic}")
        branch = "unfiltered_fallback"
    ent = {"n_products": len(sr), "branch": branch}
    pos = None
    if len(sr):
        t = sr.table
        ras = np.array([float(x) for x in t["s_ra"]], dtype=float)
        decs = np.array([float(x) for x in t["s_dec"]], dtype=float)
        pos = (float(np.median(ras)), float(np.median(decs)))
        ent["authors"] = sorted({str(a) for a in t["author"]})
        ent["sectors"] = sorted({int(s) for s in t["sequence_number"]})
        ent["missions"] = sorted({str(m) for m in t["mission"]})
        by_author = {}
        for a, s in zip(t["author"], t["sequence_number"]):
            by_author.setdefault(str(a), []).append(int(s))
        ent["sectors_by_author"] = {k: sorted(set(v))
                                    for k, v in by_author.items()}
    return ent, pos


ent, pos = inventory(TIC)
res["inventory"] = ent
print(f"TIC {TIC}: products={ent['n_products']} branch={ent['branch']} "
      f"pos={pos}", flush=True)
T = SkyCoord(ra=pos[0], dec=pos[1], unit="deg")
res["position_deg"] = {"ra": pos[0], "dec": pos[1]}

# ---------------------------------------------------------------- TIC rows
def tic_row(tab, want_id):
    for r in tab:
        if int(r["ID"]) == int(want_id):
            return {k: clean(r[k]) for k in
                    ("ID", "ra", "dec", "Tmag", "Vmag", "GAIA", "GAIAmag",
                     "rad", "mass", "Teff", "contratio", "lum", "TWOMASS")
                    if k in tab.colnames}
    return None


tab = Catalogs.query_region(T, radius=6 * u.arcsec, catalog="TIC")
res["tic_row"] = tic_row(tab, TIC)
print(f"TIC row: {res['tic_row']}", flush=True)

tab = Catalogs.query_region(T, radius=150 * u.arcsec, catalog="TIC")
nb = []
for r in tab:
    c = SkyCoord(ra=float(r["ra"]), dec=float(r["dec"]), unit="deg")
    nb.append({"ID": int(r["ID"]), "ra": float(r["ra"]), "dec": float(r["dec"]),
               "Tmag": clean(r["Tmag"]), "GAIA": str(r["GAIA"]),
               "GAIAmag": clean(r["GAIAmag"]), "rad": clean(r["rad"]),
               "Teff": clean(r["Teff"]), "contratio": clean(r["contratio"]),
               "sep_arcsec": round(float(T.separation(c).arcsec), 2)})
nb.sort(key=lambda x: x["sep_arcsec"])
res["tic_within_150arcsec"] = nb
print(f"TIC within 150\": {len(nb)}", flush=True)
for n in nb[:10]:
    print(f"   TIC {n['ID']} sep {n['sep_arcsec']}\" Tmag {n['Tmag']} "
          f"contra {n['contratio']}", flush=True)

# ---------------------------------------------------------------- Gaia cone
try:
    job = Gaia.cone_search_async(T, radius=150 * u.arcsec,
                                 columns=["source_id", "ra", "dec",
                                          "phot_g_mean_mag", "bp_rp",
                                          "teff_gspphot", "radius_gspphot"])
    gt = job.get_results()
    grows = []
    for r in gt:
        c = SkyCoord(ra=float(r["ra"]), dec=float(r["dec"]), unit="deg")
        grows.append({"source_id": int(r["source_id"]),
                      "sep_arcsec": round(float(T.separation(c).arcsec), 2),
                      "G": clean(r["phot_g_mean_mag"]), "bp_rp": clean(r["bp_rp"]),
                      "teff": clean(r["teff_gspphot"]),
                      "radius": clean(r["radius_gspphot"])})
    grows.sort(key=lambda x: x["sep_arcsec"])
    res["gaia_within_150arcsec"] = grows
    print(f"Gaia within 150\": {len(grows)}; target row: {grows[0] if grows else None}",
          flush=True)
except Exception as e:
    res["gaia_within_150arcsec"] = {"error": f"{type(e).__name__}: {str(e)[:200]}"}
    print("Gaia cone FAILED:", e, flush=True)

# Gaia variability for the target's own source_id
gaia_id = None
if res["tic_row"]:
    try:
        gaia_id = int(res["tic_row"]["GAIA"])
    except Exception:
        gaia_id = None
res["target_gaia_id"] = gaia_id
if gaia_id:
    for tbl in ("gaiadr3.vari_classifier_result", "gaiadr3.vari_eclipsing_binary"):
        try:
            q = (f"SELECT * FROM {tbl} WHERE source_id = {gaia_id}")
            job = Gaia.launch_job_async(q)
            t = job.get_results()
            res.setdefault("gaia_vari", {})[tbl] = {
                "n_rows": len(t),
                "rows": [{c: clean(r[c]) for c in t.colnames} for r in t][:3]}
            print(f"{tbl}: {len(t)} rows", flush=True)
        except Exception as e:
            res.setdefault("gaia_vari", {})[tbl] = {
                "error": f"{type(e).__name__}: {str(e)[:160]}"}
            print(f"{tbl} FAILED:", e, flush=True)

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
        e = {"name": clean(r["name"]), "var_type": clean(r["varType"]),
             "ra_deg": cra, "dec_deg": cdec,
             "sep_from_centre_arcsec": round(float(centre.separation(c).arcsec), 2),
             "max_mag": clean(r["maxMag"]), "min_mag": clean(r["minMag"]),
             "period_d": clean(r["period"]), "epoch": clean(r["epoch"])}
        if e["sep_from_centre_arcsec"] <= 120.0:
            entries.append(e)
    entries.sort(key=lambda x: x["sep_from_centre_arcsec"])
    return entries, url


try:
    entries, url = vsx_cone(T)
    res["vsx_target"] = {"query_url": url, "entries": entries}
    print(f"VSX target cone: {len(entries)} entries within 120\"", flush=True)
    for e in entries:
        print(f"   {e['name']} type {e['var_type']} P {e['period_d']} "
              f"sep {e['sep_from_centre_arcsec']}\"", flush=True)
except Exception as e:
    res["vsx_target"] = {"error": f"{type(e).__name__}: {str(e)[:200]}"}
    print("VSX target cone FAILED:", e, flush=True)

# positive control: TIC 308851365 must come back with its known VSX entry
try:
    _, cpos = inventory(CONTROL_TIC)
    C = SkyCoord(ra=cpos[0], dec=cpos[1], unit="deg")
    centries, curl_ = vsx_cone(C)
    res["vsx_positive_control"] = {"centre_tic": CONTROL_TIC,
                                   "position_deg": {"ra": cpos[0], "dec": cpos[1]},
                                   "query_url": curl_, "entries": centries}
    print(f"VSX control cone (TIC {CONTROL_TIC}): {len(centries)} entries",
          flush=True)
    for e in centries:
        print(f"   {e['name']} type {e['var_type']} P {e['period_d']} "
              f"sep {e['sep_from_centre_arcsec']}\"", flush=True)
except Exception as e:
    res["vsx_positive_control"] = {"error": f"{type(e).__name__}: {str(e)[:200]}"}
    print("VSX control FAILED:", e, flush=True)

with open(OUT, "w") as f:
    json.dump(res, f, indent=1, default=str)
print("wrote", OUT, flush=True)
