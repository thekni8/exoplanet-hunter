"""Pair vetting stage 3c: per-pixel eclipse depth map, sector 35 + 62.

For every pixel in the 15x15 TESSCut cutout: depth = 1 - <in-eclipse> /
<quadrature> at the common ephemeris. Shows WHERE deep pixels live.
Also: best achievable aperture depth on a centre/radius grid around A
and around C, to test whether ANY aperture on these pixels reproduces
the 26% in A's QLP SAP_FLUX. Output: pair_stage3c.json. Read-only.
"""
import json
import numpy as np
import lightkurve as lk
from astropy.coordinates import SkyCoord

with open("pair_stage2a.json") as f:
    ref = json.load(f)
P = ref["common_ephemeris"]["P_common_d"]
T0 = ref["common_ephemeris"]["T0_btjd"]

with open("pair_stage1.json") as f:
    s1 = json.load(f)
census = {r["ID"]: r for r in s1["tic_within_150arcsec_of_either"]}


def coord_of(tic):
    r = census[tic]
    return SkyCoord(ra=r["ra"], dec=r["dec"], unit="deg")


STARS = {"A": coord_of(31315594), "B": coord_of(31315605),
         "C": coord_of(31315574), "D": coord_of(31315592)}
MID = SkyCoord(ra=(STARS["A"].ra.deg + STARS["B"].ra.deg) / 2,
               dec=(STARS["A"].dec.deg + STARS["B"].dec.deg) / 2, unit="deg")


def win(ph, c, h):
    return np.abs(((ph - c + 0.5) % 1.0) - 0.5) <= h


out = {}
for sec in (35, 62):
    sr = lk.search_tesscut(MID, sector=sec)
    tpf = sr.download(cutout_size=15)
    t = np.asarray(tpf.time.value, dtype=np.float64)
    cube = np.asarray(tpf.flux.value, dtype=np.float32)
    q = np.asarray(tpf.quality)
    ok = (q == 0) & np.isfinite(t)
    med_ok = np.isfinite(np.nanmedian(cube.reshape(cube.shape[0], -1), axis=1))
    ok = ok & med_ok
    t, cube = t[ok], cube[ok]
    ph = ((t - T0) / P) % 1.0
    in_img = np.nanmean(cube[win(ph, 0.0, 0.06)], axis=0)
    out_img = np.nanmean(
        cube[win(ph, 0.25, 0.06) | win(ph, 0.75, 0.06)], axis=0)
    with np.errstate(invalid="ignore", divide="ignore"):
        dmap = 1.0 - in_img / out_img
    wcs = tpf.wcs
    pix = {}
    for name, sc in STARS.items():
        x, y = wcs.world_to_pixel(sc)
        pix[name] = (float(x), float(y))
    entry = {"star_pix": {k: list(v) for k, v in pix.items()}}
    # brightest out-of-eclipse pixels and deepest pixels
    flat_o = np.argsort(out_img.ravel())[::-1][:6]
    entry["brightest_pixels"] = [
        {"yx": [int(i // 15), int(i % 15)], "out_flux": float(out_img.ravel()[i]),
         "depth_pct": float(100 * dmap.ravel()[i])} for i in flat_o]
    flat_d = np.argsort(np.where(np.isfinite(dmap), dmap, -9).ravel())[::-1][:6]
    entry["deepest_pixels"] = [
        {"yx": [int(i // 15), int(i % 15)], "out_flux": float(out_img.ravel()[i]),
         "depth_pct": float(100 * dmap.ravel()[i])} for i in flat_d]
    entry["depth_map_pct"] = [[None if not np.isfinite(v) else round(float(100 * v), 1)
                               for v in row] for row in dmap]
    # aperture grid search around A and around C
    yy, xx = np.mgrid[0:15, 0:15]
    for centre_name in ("A", "C"):
        cx, cy = pix[centre_name]
        best = []
        for dx in np.arange(-3.0, 3.01, 0.5):
            for dy in np.arange(-3.0, 3.01, 0.5):
                for r in (0.75, 1.25, 1.75, 2.5, 3.25, 4.0):
                    m = np.hypot(xx - (cx + dx), yy - (cy + dy)) <= r
                    if m.sum() == 0:
                        continue
                    si = np.nansum(in_img[m])
                    so = np.nansum(out_img[m])
                    if so > 0:
                        best.append((float(100 * (1 - si / so)), dx, dy, r,
                                     int(m.sum())))
        best.sort(reverse=True)
        entry[f"best_apertures_near_{centre_name}"] = [
            {"depth_pct": b[0], "dx": b[1], "dy": b[2], "r": b[3], "npix": b[4]}
            for b in best[:5]]
    out[str(sec)] = entry
    print(f"--- sector {sec}")
    print("  star pix:", {k: (round(v[0], 1), round(v[1], 1)) for k, v in pix.items()})
    print("  brightest:", [(b["yx"], round(b["depth_pct"], 1)) for b in entry["brightest_pixels"]])
    print("  deepest:", [(b["yx"], round(b["depth_pct"], 1)) for b in entry["deepest_pixels"]])
    for cn in ("A", "C"):
        print(f"  best near {cn}:", [(round(b["depth_pct"], 1), b["dx"], b["dy"], b["r"]) for b in entry[f"best_apertures_near_{cn}"]])
    del tpf, t, cube, in_img, out_img, dmap

with open("pair_stage3c.json", "w") as fh:
    json.dump(out, fh, indent=1)
print("wrote pair_stage3c.json")
