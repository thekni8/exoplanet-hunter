"""Big-fish gauntlet — VSX cones only (split from stage 0c after the AIP
timeout killed the combined run before it could save anything).
Target cone 120" + TIC 308851365 positive control. Raw-XML parse.
Output: vetting_results/bf851_vsx.json (written immediately on success).
"""
import json
import re
import xml.etree.ElementTree as ET

import requests
from astropy.coordinates import SkyCoord
from astroquery.mast import Catalogs

RA, DEC = 80.1053299464223, -65.0991806063304
T = SkyCoord(ra=RA, dec=DEC, unit="deg")
res = {}

tab = Catalogs.query_criteria(catalog="TIC", ID=308851365)
crow = tab[0]
C = SkyCoord(ra=float(crow["ra"]), dec=float(crow["dec"]), unit="deg")
res["control_tic_row"] = {"ra": float(crow["ra"]), "dec": float(crow["dec"]),
                          "Tmag": float(crow["Tmag"])}
print("control centre (TIC 308851365):", C.ra.deg, C.dec.deg, flush=True)

FLOAT2 = re.compile(r"(-?\d+\.\d+),(-?\d+\.\d+)")  # comma-anchored: a bare
# \D+ separator eats the minus sign of a negative Dec (bug found 2026-11-07)


def vsx_cone(centre, label):
    coords = f"{centre.ra.deg}+{centre.dec.deg}"
    url = ("https://vsx.aavso.org/index.php?view=query.votable"
           f"&coords={coords}&size=2.0&unit=2&order=9")
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    root = ET.fromstring(resp.content)
    fields = [f.get("name") for f in root.iter("FIELD")]
    entries, nrows = [], 0
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

with open("vetting_results/bf851_vsx.json", "w") as f:
    json.dump(res, f, indent=1, default=str)
print("wrote vetting_results/bf851_vsx.json", flush=True)
