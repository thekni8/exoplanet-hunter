"""Pair vetting stage 1b: fix the failed catalogue routes from stage 1.

  * VSX 120-arcsec cones around both stars — robust radec2000 parsing
    (stage 1 died on a row whose radec2000 did not split on ',').
  * Gaia DR3 cone + vari tables — retried sync launch_job (stage 1 hit a
    transient proxy SSL error).
  * Product inventory for the two flux-relevant third-star candidates
    (TIC 31315592, 12.5" from A; TIC 31315574, Tmag 12.83, 41.6" from A).
  * Flux-ranked shortlist of every TIC source with Tmag <= 15 within
    150" of either star (from pair_stage1.json).
Merges everything into pair_stage1.json. Read-only.
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
import lightkurve as lk

A_ID, B_ID = 31315594, 31315605
with open("pair_stage1.json") as f:
    res = json.load(f)

A = SkyCoord(ra=res["tic_rows"][str(A_ID)]["ra"],
             dec=res["tic_rows"][str(A_ID)]["dec"], unit="deg")
B = SkyCoord(ra=res["tic_rows"][str(B_ID)]["ra"],
             dec=res["tic_rows"][str(B_ID)]["dec"], unit="deg")
sep = A.separation(B)


def clean(v):
    if v is None:
        return None
    try:
        import numpy as _np
        if isinstance(v, _np.floating):
            v = float(v)
            return None if not _np.isfinite(v) else v
        if isinstance(v, _np.integer):
            return int(v)
    except Exception:
        pass
    return v


# --------------------------------------------------------------------- VSX
def parse_radec(s):
    s = str(s).strip()
    for sepch in (",", " "):
        if sepch in s:
            parts = [p for p in s.split(sepch) if p.strip()]
            if len(parts) == 2:
                return float(parts[0]), float(parts[1])
    raise ValueError(f"unparseable radec2000: {s!r}")


def vsx_cone(centre, size_arcmin=2.0):
    coords = f"{centre.ra.deg}+{centre.dec.deg}"
    url = ("https://vsx.aavso.org/index.php?view=query.votable"
           f"&coords={coords}&size={size_arcmin}&unit=2&order=9")
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    tab = parse_single_table(io.BytesIO(resp.content)).to_table()
    entries, bad = [], 0
    for r in tab:
        try:
            cra, cdec = parse_radec(r["radec2000"])
        except Exception:
            bad += 1
            continue
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
    return entries, url, bad


res["vsx"] = {}
for label, centre in (("around_A", A), ("around_B", B)):
    try:
        entries, url, bad = vsx_cone(centre)
        res["vsx"][label] = {"query_url": url, "entries": entries,
                             "unparseable_rows": bad}
        print(f"VSX {label}: {len(entries)} entries <=120\" (bad rows {bad})",
              flush=True)
        for e in entries:
            print(f"   {e['name']} type {e['var_type']} P {e['period_d']} "
                  f"max {e['max_mag']} min {e['min_mag']} "
                  f"sepA {e['sep_from_A_arcsec']} sepB {e['sep_from_B_arcsec']}",
                  flush=True)
    except Exception as e:
        res["vsx"][label] = {"error": f"{type(e).__name__}: {str(e)[:200]}"}
        print(f"VSX {label} FAILED:", e, flush=True)

# -------------------------------------------------------------------- Gaia
mid = SkyCoord(ra=(A.ra.deg + B.ra.deg) / 2, dec=(A.dec.deg + B.dec.deg) / 2,
               unit="deg")
r_cone = (150.0 + sep.arcsec / 2.0 + 5.0) / 3600.0


def gaia_job(q, tries=3):
    last = None
    for i in range(tries):
        try:
            return Gaia.launch_job(q).get_results()
        except Exception as e:
            last = e
            print(f"   gaia attempt {i + 1} failed: {e}", flush=True)
            time.sleep(5)
    raise last


try:
    q = ("SELECT source_id, ra, dec, phot_g_mean_mag, bp_rp, teff_gspphot "
         "FROM gaiadr3.gaia_source WHERE 1=CONTAINS("
         f"POINT('ICRS', ra, dec), CIRCLE('ICRS', {mid.ra.deg}, {mid.dec.deg}, "
         f"{r_cone}))")
    t = gaia_job(q)
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
    for g in grows[:6]:
        print(f"   {g['source_id']} G {g['phot_g_mean_mag']:.2f} "
              f"sepA {g['sep_from_A_arcsec']:.1f} sepB {g['sep_from_B_arcsec']:.1f}",
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
            tt = gaia_job(f"SELECT {cols} FROM {table} "
                          f"WHERE source_id IN ({ids})")
            out = []
            for r in tt:
                out.append({c: (r[c] if isinstance(r[c], str) else clean(r[c]))
                            for c in tt.colnames})
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
    res["gaia_cone"] = {"error": f"{type(e).__name__}: {str(e)[:200]}"}
    print("Gaia cone FAILED after retries:", e, flush=True)

# --------------------------------------------- third-star candidate inventory
for tic in (31315592, 31315574, 31315537):
    try:
        sr = lk.search_lightcurve(f"TIC {tic}",
                                  author=["SPOC", "TESS-SPOC", "QLP"])
        secs = []
        for r in sr.table:
            secs.append({"author": str(r["author"]),
                         "sector": int(r["sequence_number"]),
                         "t_exptime": float(r["t_exptime"])})
        res.setdefault("candidate_inventory", {})[str(tic)] = secs
        print(f"TIC {tic}: {len(secs)} filtered products, sectors "
              f"{sorted({s['sector'] for s in secs})}", flush=True)
    except Exception as e:
        res.setdefault("candidate_inventory", {})[str(tic)] = \
            {"error": f"{type(e).__name__}: {str(e)[:200]}"}
        print(f"TIC {tic} inventory FAILED:", e, flush=True)

# ------------------------------------------------------- flux shortlist
FA = 10 ** (-0.4 * res["tic_rows"][str(A_ID)]["Tmag"])
FB = 10 ** (-0.4 * res["tic_rows"][str(B_ID)]["Tmag"])
short = []
for r in res["tic_within_150arcsec_of_either"]:
    if r["Tmag"] is not None and r["Tmag"] <= 15.0:
        fx = 10 ** (-0.4 * r["Tmag"])
        short.append({**r, "flux_vs_A": fx / FA, "flux_vs_B": fx / FB})
short.sort(key=lambda x: -x["flux_vs_A"])
res["flux_shortlist_Tmag_le15"] = short
print(f"flux shortlist (Tmag<=15): {len(short)}", flush=True)
for r in short:
    print(f"   TIC {r['ID']} Tmag {r['Tmag']:.2f} fluxA x{r['flux_vs_A']:.2f} "
          f"fluxB x{r['flux_vs_B']:.2f} sepA {r['sep_from_A_arcsec']:.1f} "
          f"sepB {r['sep_from_B_arcsec']:.1f}", flush=True)

with open("pair_stage1.json", "w") as f:
    json.dump(res, f, indent=1, default=str)
print("updated pair_stage1.json")
