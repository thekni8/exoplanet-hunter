"""Stage 1 addendum: Gaia DR3 cones via sync launch_job (async endpoint SSL-fails
through this VM's proxy; sync worked for the cross-check batch)."""
import json
from astroquery.gaia import Gaia

OUT = "blend_check_stage1.json"

with open(OUT) as f:
    res = json.load(f)


def cone(ra, dec, r_arcsec=6.0):
    q = ("SELECT source_id, ra, dec, phot_g_mean_mag, bp_rp, teff_gspphot "
         "FROM gaiadr3.gaia_source WHERE 1=CONTAINS("
         f"POINT('ICRS', ra, dec), CIRCLE('ICRS', {ra}, {dec}, {r_arcsec / 3600.0}))")
    t = Gaia.launch_job(q).get_results()
    out = []
    for r in t:
        out.append({
            "source_id": int(r["source_id"]),
            "ra": float(r["ra"]), "dec": float(r["dec"]),
            "phot_g_mean_mag": float(r["phot_g_mean_mag"]),
            "bp_rp": float(r["bp_rp"]) if r["bp_rp"] is not None else None,
            "teff_gspphot": float(r["teff_gspphot"]) if r["teff_gspphot"] is not None else None,
        })
    return out


# ASASSN-V position (VSX): 99.39979166666666, -67.73536111111112
res["gaia_cone_6arcsec_around_asassn_pos"] = cone(99.39979166666666, -67.73536111111112)
# TIC 167367400 exact TIC position
res["gaia_cone_6arcsec_around_tic167367400"] = cone(99.3997399780539, -67.7353198122176)
# Target TIC 167367406
res["gaia_cone_6arcsec_around_target"] = cone(99.4320261122082, -67.743880749249)

for k in ("gaia_cone_6arcsec_around_asassn_pos", "gaia_cone_6arcsec_around_tic167367400",
          "gaia_cone_6arcsec_around_target"):
    print(k, res[k])

with open(OUT, "w") as f:
    json.dump(res, f, indent=1, default=str)
print("updated", OUT)
