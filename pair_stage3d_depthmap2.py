"""Pair vetting stage 3d: robust (median-based) depth forensics.

(a) Sector 35, 25x25 cutout: median in/out images -> difference image
    centroid + peak offsets to A/B/C/D on the wider field (closes the
    'deeper variable just outside the 15x15 frame' loophole), and the
    maximum per-pixel depth with its location.
(b) Sectors 35 + 62, 15x15: aperture grid search (centres around A and
    around C, radii 0.75-4 px) with depths measured as window MEDIANS of
    the folded aperture light curve (robust to jitter/outliers, unlike
    stage 3c's mean images). Question: can ANY aperture on the real
    pixels reproduce the 26% in A's QLP SAP_FLUX?
Output: pair_stage3d.json. Read-only.
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


STARS = {"A_31315594": coord_of(31315594), "B_31315605": coord_of(31315605),
         "C_31315574": coord_of(31315574), "D_31315592": coord_of(31315592)}
MID = SkyCoord(
    ra=(STARS["A_31315594"].ra.deg + STARS["B_31315605"].ra.deg) / 2,
    dec=(STARS["A_31315594"].dec.deg + STARS["B_31315605"].dec.deg) / 2,
    unit="deg")


def win(ph, c, h):
    return np.abs(((ph - c + 0.5) % 1.0) - 0.5) <= h


def load_cube(sec, size):
    sr = lk.search_tesscut(MID, sector=sec)
    tpf = sr.download(cutout_size=size)
    t = np.asarray(tpf.time.value, dtype=np.float64)
    cube = np.asarray(tpf.flux.value, dtype=np.float32)
    q = np.asarray(tpf.quality)
    ok = (q == 0) & np.isfinite(t)
    med_ok = np.isfinite(np.nanmedian(cube.reshape(cube.shape[0], -1), axis=1))
    ok = ok & med_ok
    return t[ok], cube[ok], tpf.wcs


def centroid_sky(wcs, img):
    w = img - np.median(img)
    w = np.where(w > 0, w, 0.0)
    tot = w.sum()
    if tot <= 0:
        return None
    yy, xx = np.mgrid[0:img.shape[0], 0:img.shape[1]]
    return SkyCoord.from_pixel(float((w * xx).sum() / tot),
                               float((w * yy).sum() / tot), wcs)


out = {}

# ---- (a) wide cutout, sector 35 ----
t, cube, wcs = load_cube(35, 25)
ph = ((t - T0) / P) % 1.0
in_img = np.nanmedian(cube[win(ph, 0.0, 0.05)], axis=0)
out_img = np.nanmedian(cube[win(ph, 0.25, 0.07) | win(ph, 0.75, 0.07)], axis=0)
diff = out_img - in_img
cs = centroid_sky(wcs, diff)
pk = np.unravel_index(np.nanargmax(diff), diff.shape)
pk_sky = SkyCoord.from_pixel(float(pk[1]), float(pk[0]), wcs)
with np.errstate(invalid="ignore", divide="ignore"):
    dmap = 1.0 - in_img / out_img
dmax = np.nanargmax(np.where(out_img > 0.05 * np.nanmax(out_img), dmap, -9))
ent = {"centroid_offsets_arcsec": {n: float(cs.separation(s).arcsec)
                                   for n, s in STARS.items()},
       "peak_offsets_arcsec": {n: float(pk_sky.separation(s).arcsec)
                               for n, s in STARS.items()},
       "max_pixel_depth_pct": float(100 * dmap.ravel()[dmax]),
       "max_pixel_depth_yx": [int(dmax // 25), int(dmax % 25)],
       "star_pix": {}}
for n, s in STARS.items():
    x, y = wcs.world_to_pixel(s)
    ent["star_pix"][n] = [float(x), float(y)]
out["wide25_sector35"] = ent
print("wide25 s35 centroid:", ent["centroid_offsets_arcsec"], flush=True)
print("wide25 s35 peak:", ent["peak_offsets_arcsec"],
      "max pixel depth:", ent["max_pixel_depth_pct"], "at", ent["max_pixel_depth_yx"],
      "star pix:", {k: (round(v[0], 1), round(v[1], 1)) for k, v in ent["star_pix"].items()},
      flush=True)
del t, cube, in_img, out_img, diff, dmap

# ---- (b) robust aperture grid, sectors 35 + 62 ----
for sec in (35, 62):
    t, cube, wcs = load_cube(sec, 15)
    ph = ((t - T0) / P) % 1.0
    mI = win(ph, 0.0, 0.06)
    mP = win(ph, 0.25, 0.06) | win(ph, 0.75, 0.06)
    yy, xx = np.mgrid[0:15, 0:15]
    pix = {}
    for n, s in STARS.items():
        x, y = wcs.world_to_pixel(s)
        pix[n] = (float(x), float(y))
    ent = {}
    for centre_name in ("A_31315594", "C_31315574"):
        cx, cy = pix[centre_name]
        best = []
        for dx in np.arange(-3.0, 3.01, 0.5):
            for dy in np.arange(-3.0, 3.01, 0.5):
                for r in (0.75, 1.25, 1.75, 2.5, 3.25, 4.0):
                    m = np.hypot(xx - (cx + dx), yy - (cy + dy)) <= r
                    if m.sum() == 0:
                        continue
                    fl = np.nansum(cube[:, m], axis=1)
                    d = 1 - np.nanmedian(fl[mI]) / np.nanmedian(fl[mP])
                    best.append((float(100 * d), float(dx), float(dy),
                                 float(r), int(m.sum())))
        best.sort(reverse=True)
        ent[f"best_near_{centre_name}"] = [
            {"depth_pct": b[0], "dx": b[1], "dy": b[2], "r": b[3], "npix": b[4]}
            for b in best[:5]]
    out[f"grid_sector{sec}"] = ent
    for cn in ("A_31315594", "C_31315574"):
        print(f"s{sec} best near {cn}:",
              [(round(b["depth_pct"], 1), b["dx"], b["dy"], b["r"])
               for b in ent[f"best_near_{cn}"]], flush=True)
    del t, cube

with open("pair_stage3d.json", "w") as fh:
    json.dump(out, fh, indent=1)
print("wrote pair_stage3d.json")
