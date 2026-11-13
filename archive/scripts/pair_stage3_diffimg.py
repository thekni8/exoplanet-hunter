"""Pair vetting stage 3: TESSCut difference imaging + aperture test.

Cutouts (15x15 px) centred on the A-B midpoint — A (31315594), B (31315605),
C (31315574, the VSX variable) and D (31315592, 12.5" from A, no own light
curve) all fall inside. Sectors 35 + 62 (A's era) and 2 (B's era): the
variable source must sit on the same star in both eras.

Median out-of-eclipse minus in-eclipse (Min I) images; flux-weighted
centroid + peak of the difference, offsets reported to A, B, C and D.
Aperture test: window depths from tight (r<=0.75 px) and standard
(r<=2.0 px) apertures centred on A, B and C in the same pixels.
One sector at a time; float32 cubes freed between sectors.
Output: pair_stage3.json. Read-only.
"""
import json
import numpy as np
import lightkurve as lk
from astropy.coordinates import SkyCoord
import astropy.units as u

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


STARS = {"A_31315594": coord_of(31315594), "B_31315605": coord_of(31315605),
         "C_31315574": coord_of(31315574), "D_31315592": coord_of(31315592)}
MID = SkyCoord(ra=(STARS["A_31315594"].ra.deg + STARS["B_31315605"].ra.deg) / 2,
               dec=(STARS["A_31315594"].dec.deg + STARS["B_31315605"].dec.deg) / 2,
               unit="deg")
SECTORS = [35, 62, 2]


def win(ph, centre, half):
    return np.abs(((ph - centre + 0.5) % 1.0) - 0.5) <= half


def depths(ph, fl):
    plat = np.concatenate([fl[win(ph, 0.25, 0.06)], fl[win(ph, 0.75, 0.06)]])
    dI = 1 - np.mean(fl[win(ph, 0.0, 0.06)]) / np.mean(plat)
    dII = 1 - np.mean(fl[win(ph, 0.5, 0.06)]) / np.mean(plat)
    return float(100 * dI), float(100 * dII)


def centroid_sky(wcs, img):
    w = img - np.median(img)
    w = np.where(w > 0, w, 0.0)
    tot = w.sum()
    if tot <= 0:
        return None, None
    yy, xx = np.mgrid[0:img.shape[0], 0:img.shape[1]]
    cx = float((w * xx).sum() / tot)
    cy = float((w * yy).sum() / tot)
    return SkyCoord.from_pixel(cx, cy, wcs), (cx, cy)


results = {}
for sec in SECTORS:
    print(f"--- sector {sec}", flush=True)
    sr = lk.search_tesscut(MID, sector=sec)
    if len(sr) == 0:
        results[str(sec)] = {"error": "no tesscut"}
        continue
    tpf = sr.download(cutout_size=15)
    t = np.asarray(tpf.time.value, dtype=np.float64)
    cube = np.asarray(tpf.flux.value, dtype=np.float32)
    q = np.asarray(tpf.quality)
    ok = (q == 0) & np.isfinite(t)
    med_ok = np.isfinite(np.nanmedian(cube.reshape(cube.shape[0], -1), axis=1))
    ok = ok & med_ok
    t, cube = t[ok], cube[ok]
    ph = ((t - T0) / P) % 1.0
    in_m = win(ph, 0.0, 0.05)
    out_m = win(ph, 0.25, 0.07) | win(ph, 0.75, 0.07)
    in_img = np.nanmedian(cube[in_m], axis=0)
    out_img = np.nanmedian(cube[out_m], axis=0)
    diff = out_img - in_img
    wcs = tpf.wcs
    pix = {}
    for name, sc in STARS.items():
        x, y = wcs.world_to_pixel(sc)
        pix[name] = (float(x), float(y))
    dsky, dpix = centroid_sky(wcs, diff)
    pk = np.unravel_index(np.nanargmax(diff), diff.shape)
    pk_sky = SkyCoord.from_pixel(float(pk[1]), float(pk[0]), wcs)
    entry = {
        "n_cadences": int(t.size), "n_in": int(in_m.sum()),
        "n_out": int(out_m.sum()),
        "star_pix": {k: list(v) for k, v in pix.items()},
        "diff_centroid_ra_dec": [float(dsky.ra.deg), float(dsky.dec.deg)],
        "diff_peak_value_e_s": float(diff[pk]),
    }
    for name, sc in STARS.items():
        entry[f"diff_centroid_offset_to_{name}_arcsec"] = \
            float(dsky.separation(sc).arcsec)
        entry[f"diff_peak_offset_to_{name}_arcsec"] = \
            float(pk_sky.separation(sc).arcsec)
    # aperture test on the same pixels
    yy, xx = np.mgrid[0:cube.shape[1], 0:cube.shape[2]]
    radii = {name: np.hypot(xx - xy[0], yy - xy[1])
             for name, xy in pix.items()}
    bg_mask = np.ones_like(xx, dtype=bool)
    for name in ("A_31315594", "B_31315605", "C_31315574"):
        bg_mask &= radii[name] > 4.0
    bg = np.nanmedian(cube[:, bg_mask], axis=1)
    for name in ("A_31315594", "B_31315605", "C_31315574"):
        for ap, rmax in (("tight_r0.75", 0.75), ("standard_r2.0", 2.0)):
            mask = radii[name] <= rmax
            fl = np.nansum(cube[:, mask], axis=1) - bg * mask.sum()
            fl = fl / np.median(fl)
            dI, dII = depths(ph, fl.astype(np.float64))
            entry[f"depth_{name}_{ap}_pct"] = [dI, dII]
    results[str(sec)] = entry
    print(f"    centroid offsets: " +
          ", ".join(f"{n} {entry[f'diff_centroid_offset_to_{n}_arcsec']:.1f}\""
                    for n in STARS), flush=True)
    print(f"    peak offsets: " +
          ", ".join(f"{n} {entry[f'diff_peak_offset_to_{n}_arcsec']:.1f}\""
                    for n in STARS), flush=True)
    for name in ("A_31315594", "B_31315605", "C_31315574"):
        print(f"    {name}: tight {entry[f'depth_{name}_tight_r0.75_pct']} "
              f"std {entry[f'depth_{name}_standard_r2.0_pct']}", flush=True)
    del tpf, t, cube, in_img, out_img, diff

with open("pair_stage3.json", "w") as fh:
    json.dump(results, fh, indent=1)
print("wrote pair_stage3.json")
