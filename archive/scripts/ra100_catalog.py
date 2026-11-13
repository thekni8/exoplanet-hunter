#!/usr/bin/env python
"""RA100 sweep vet, stage 0: ID-verified TIC row + neighbour census
for TIC 167367406. Read-only catalog queries; no hunter history."""
import json
import sys
import time
import warnings
from pathlib import Path

import numpy as np

warnings.filterwarnings("ignore")

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
OUTDIR = BASE / "vetting_results"

from astroquery.mast import Catalogs  # noqa: E402
from astropy.coordinates import SkyCoord  # noqa: E402
import astropy.units as u  # noqa: E402

TIC = "167367406"


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def main():
    out = {"tic": TIC, "stage": "catalog_row_and_neighbours"}
    # --- ID-verified row: query BY ID and verify the returned ID ---
    tbl = Catalogs.query_criteria(catalog="TIC", ID=int(TIC))
    log(f"ID query returned {len(tbl)} row(s)")
    rows = []
    for r in tbl:
        rows.append({c: (None if r[c] is None or
                         (hasattr(r[c], 'masked') and r[c].masked)
                         else float(r[c]) if isinstance(r[c], (int, float, np.floating, np.integer))
                         else str(r[c]))
                     for c in tbl.colnames})
    out["id_query_n_rows"] = len(rows)
    out["id_query_rows"] = rows
    match = [r for r in rows if str(r.get("ID")) in (TIC, str(int(TIC)))]
    out["id_verified"] = bool(match)
    if not match:
        out["error"] = "returned ID does not match requested TIC"
        (OUTDIR / f"{TIC}_catalog.json").write_text(json.dumps(out, indent=2, default=str))
        log("ID MISMATCH - abort")
        return
    row = match[0]
    keep = ["ID", "ra", "dec", "Tmag", "rad", "mass", "Teff", "d",
            "contratio", "lum", "logg", "mh", "plx", "GAIAmag", "Vmag",
            "Jmag", "numcont", "wdflag", "ccflag"]
    out["tic_row"] = {k: row.get(k) for k in keep if k in row}
    ra, dec = float(row["ra"]), float(row["dec"])
    out["coords"] = {"ra_deg": ra, "dec_deg": dec}
    log(f"TIC row: ra={ra} dec={dec} Tmag={row.get('Tmag')} rad={row.get('rad')} "
        f"mass={row.get('mass')} Teff={row.get('Teff')} d={row.get('d')} "
        f"contratio={row.get('contratio')}")

    # --- neighbour census within 2 arcmin ---
    coord = SkyCoord(ra=ra * u.deg, dec=dec * u.deg)
    ntbl = Catalogs.query_region(coord, radius=(2.0 / 60.0) * u.deg,
                                 catalog="TIC")
    log(f"cone 2 arcmin returned {len(ntbl)} rows")
    c0 = SkyCoord(ra=ra * u.deg, dec=dec * u.deg)
    neigh = []
    for r in ntbl:
        try:
            c = SkyCoord(ra=float(r["ra"]) * u.deg, dec=float(r["dec"]) * u.deg)
            sep = float(c0.separation(c).arcsec)
        except Exception:
            continue
        neigh.append({"ID": str(r["ID"]), "sep_arcsec": round(sep, 1),
                      "sep_arcmin": round(sep / 60.0, 2),
                      "Tmag": None if r["Tmag"] is None else float(r["Tmag"]),
                      "rad_rsun": None if r["rad"] is None else float(r["rad"]),
                      "Teff": None if r["Teff"] is None else float(r["Teff"]),
                      "contratio": None if r["contratio"] is None else float(r["contratio"])})
    neigh.sort(key=lambda x: x["sep_arcsec"])
    out["neighbours_within_2arcmin"] = neigh
    out["n_neighbours_within_2arcmin_incl_target"] = len(neigh)
    (OUTDIR / f"{TIC}_catalog.json").write_text(json.dumps(out, indent=2, default=str))
    log(f"neighbours (incl target): {len(neigh)}")
    for n in neigh[:12]:
        log(f"  TIC {n['ID']} sep={n['sep_arcsec']}\" Tmag={n['Tmag']} rad={n['rad_rsun']}")


if __name__ == "__main__":
    main()
