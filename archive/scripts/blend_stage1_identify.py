"""Blend check stage 1: identify the ASASSN-V star + full 60" neighbourhood.

Cone-search TIC around the VSX position of ASASSN-V J063735.95-674407.3,
Gaia DR3 cone for cross-ID, and a TIC cone around TIC 167367406 with
separations AND position angles so the ASASSN-V star can be matched to a
specific TIC neighbour. Read-only; standalone (no hunter.py).
"""
import json
import numpy as np
from astropy import units as u
from astropy.coordinates import SkyCoord
from astroquery.mast import Catalogs
from astroquery.gaia import Gaia

OUT = "blend_check_stage1.json"

TARGET = SkyCoord(ra=99.4320261122082, dec=-67.743880749249, unit="deg")
# VSX position of ASASSN-V J063735.95-674407.3: RA 06 37 35.95, Dec -67 44 07.3
ASASSN = SkyCoord("06h37m35.95s", "-67d44m07.3s")

print("ASASSN-V position deg:", ASASSN.ra.deg, ASASSN.dec.deg)
print("Separation target<->ASASSN-V position (arcsec):",
      TARGET.separation(ASASSN).arcsec)
print("PA of ASASSN-V from target (deg, E of N):",
      TARGET.position_angle(ASASSN).deg)

res = {}

# --- TIC cone 10" around ASASSN-V position ---
tab = Catalogs.query_region(ASASSN, radius=10 * u.arcsec, catalog="TIC")
rows = []
for r in tab:
    c = SkyCoord(ra=float(r["ra"]), dec=float(r["dec"]), unit="deg")
    rows.append({
        "ID": str(r["ID"]), "ra": float(r["ra"]), "dec": float(r["dec"]),
        "sep_from_asassn_pos_arcsec": float(ASASSN.separation(c).arcsec),
        "sep_from_target_arcsec": float(TARGET.separation(c).arcsec),
        "Tmag": float(r["Tmag"]), "Vmag": float(r["Vmag"]),
        "GAIA": str(r["GAIA"]), "Teff": float(r["Teff"]),
        "rad": float(r["rad"]), "GAIAmag": float(r["GAIAmag"]),
        "TWOMASS": str(r["TWOMASS"]),
    })
res["tic_cone_10arcsec_around_asassn_pos"] = rows
print(f"TIC within 10\" of ASASSN-V position: {len(rows)}")
for r in rows:
    print("  ", r)

# --- TIC cone 65" around target, with PA, to match neighbours ---
tab2 = Catalogs.query_region(TARGET, radius=65 * u.arcsec, catalog="TIC")
nb = []
for r in tab2:
    c = SkyCoord(ra=float(r["ra"]), dec=float(r["dec"]), unit="deg")
    nb.append({
        "ID": str(r["ID"]), "ra": float(r["ra"]), "dec": float(r["dec"]),
        "sep_arcsec": float(TARGET.separation(c).arcsec),
        "pa_deg": float(TARGET.position_angle(c).deg),
        "sep_from_asassn_pos_arcsec": float(ASASSN.separation(c).arcsec),
        "Tmag": float(r["Tmag"]), "Vmag": float(r["Vmag"]),
        "GAIA": str(r["GAIA"]), "Teff": float(r["Teff"]),
        "rad": float(r["rad"]), "GAIAmag": float(r["GAIAmag"]),
        "contratio": float(r["contratio"]),
    })
nb.sort(key=lambda x: x["sep_arcsec"])
res["tic_neighbours_within_65arcsec_of_target"] = nb
print(f"TIC within 65\" of target: {len(nb)}")
for r in nb:
    print(f"   TIC {r['ID']} sep {r['sep_arcsec']:.1f}\" PA {r['pa_deg']:.0f} "
          f"Tmag {r['Tmag']} V {r['Vmag']} sepFromASASSNpos {r['sep_from_asassn_pos_arcsec']:.1f}\"")

# Gaia cones handled by blend_stage1_gaia_fix.py (async endpoint SSL-fails here).
with open(OUT, "w") as f:
    json.dump(res, f, indent=1, default=str)
print("wrote", OUT)
