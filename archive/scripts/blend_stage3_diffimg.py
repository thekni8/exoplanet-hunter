"""Blend check stages 3+4: TESSCut difference imaging + aperture test.

For each chosen sector: cutout centred on TIC 167367406 (13x13 px, both stars
in frame; separation 2.55 px). Build median in-eclipse (Min I window) and
out-of-eclipse (quadrature) images from quality==0 cadences; difference =
out - in; localise the variable source via the difference-image centroid and
peak, converted to sky with the cutout WCS. Also flux-weighted in/out centroid
shift. Aperture test: fold light curves from a tight (r<=0.75 px) and a
standard (r<=2.0 px) aperture around the target and measure window depths.
One sector at a time; float32 cubes freed between sectors.
"""
import json
import numpy as np
import lightkurve as lk
from astropy.coordinates import SkyCoord
import astropy.units as u

P = 0.4346134307164049
T0 = 3095.3776324363
SECTORS = [31, 39, 63, 67, 88, 96]

TARGET = SkyCoord(ra=99.4320261122082, dec=-67.743880749249, unit="deg")
NEIGH = SkyCoord(ra=99.3997399780539, dec=-67.7353198122176, unit="deg")  # TIC 167367400

def win(ph, centre, half):
    return np.abs(((ph - centre + 0.5) % 1.0) - 0.5) <= half

def depths(ph, fl):
    plat = np.concatenate([fl[win(ph, 0.25, 0.06)], fl[win(ph, 0.75, 0.06)]])
    dI = 1 - np.mean(fl[win(ph, 0.0, 0.06)]) / np.mean(plat)
    dII = 1 - np.mean(fl[win(ph, 0.5, 0.06)]) / np.mean(plat)
    return float(100 * dI), float(100 * dII)

def centroid_sky(wcs, img):
    """Flux-weighted centroid of a positive-clipped, baseline-subtracted image."""
    w = img - np.median(img)
    w = np.where(w > 0, w, 0.0)
    tot = w.sum()
    if tot <= 0:
        return None, None
    yy, xx = np.mgrid[0:img.shape[0], 0:img.shape[1]]
    cx = float((w * xx).sum() / tot); cy = float((w * yy).sum() / tot)
    sky = SkyCoord.from_pixel(cx, cy, wcs)
    return sky, (cx, cy)

results = {}
for sec in SECTORS:
    print(f"--- sector {sec}", flush=True)
    sr = lk.search_tesscut(TARGET, sector=sec)
    if len(sr) == 0:
        results[str(sec)] = {"error": "no tesscut"}
        continue
    try:
        tpf = sr.download(cutout_size=13)
    except TypeError:
        tpf = sr.download()
    t = np.asarray(tpf.time.value, dtype=np.float64)
    cube = np.asarray(tpf.flux.value, dtype=np.float32)
    q = np.asarray(tpf.quality)
    ok = (q == 0) & np.isfinite(t)
    # finite per-cadence: require median pixel finite
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
    # pixel positions of the two stars
    tx, ty = wcs.world_to_pixel(TARGET)
    nx, ny = wcs.world_to_pixel(NEIGH)
    dsky, dpix = centroid_sky(wcs, diff)
    isky, _ = centroid_sky(wcs, in_img)
    osky, _ = centroid_sky(wcs, out_img)
    # peak pixel of difference image
    pk = np.unravel_index(np.nanargmax(diff), diff.shape)
    pk_sky = SkyCoord.from_pixel(float(pk[1]), float(pk[0]), wcs)
    entry = {
        "n_cadences": int(t.size), "n_in": int(in_m.sum()), "n_out": int(out_m.sum()),
        "target_pix": [float(tx), float(ty)], "neigh_pix": [float(nx), float(ny)],
        "pix_sep": float(np.hypot(float(tx) - float(nx), float(ty) - float(ny))),
        "diff_centroid_offset_to_target_arcsec": float(dsky.separation(TARGET).arcsec),
        "diff_centroid_offset_to_neighbour_arcsec": float(dsky.separation(NEIGH).arcsec),
        "diff_centroid_ra_dec": [float(dsky.ra.deg), float(dsky.dec.deg)],
        "diff_peak_offset_to_target_arcsec": float(pk_sky.separation(TARGET).arcsec),
        "diff_peak_offset_to_neighbour_arcsec": float(pk_sky.separation(NEIGH).arcsec),
        "diff_peak_value_e_s": float(diff[pk]),
        "in_out_centroid_shift_arcsec": float(isky.separation(osky).arcsec),
        "out_centroid_offset_to_target_arcsec": float(osky.separation(TARGET).arcsec),
        "in_centroid_offset_to_target_arcsec": float(isky.separation(TARGET).arcsec),
    }
    # --- aperture test on the same pixels ---
    yy, xx = np.mgrid[0:cube.shape[1], 0:cube.shape[2]]
    r_t = np.hypot(xx - float(tx), yy - float(ty))
    r_n = np.hypot(xx - float(nx), yy - float(ny))
    bg_mask = (r_t > 5.0) & (r_n > 3.0)
    bg = np.nanmedian(cube[:, bg_mask], axis=1)
    for name, mask in (("tight_r0.75", r_t <= 0.75), ("standard_r2.0", r_t <= 2.0),
                       ("neighbour_r1.5", r_n <= 1.5)):
        fl = np.nansum(cube[:, mask], axis=1) - bg * mask.sum()
        fl = fl / np.median(fl)
        dI, dII = depths(ph, fl.astype(np.float64))
        entry[f"depth_{name}_pct"] = [dI, dII]
    results[str(sec)] = entry
    print(f"    diff centroid: {entry['diff_centroid_offset_to_target_arcsec']:.1f}\" from target, "
          f"{entry['diff_centroid_offset_to_neighbour_arcsec']:.1f}\" from neighbour; "
          f"peak {entry['diff_peak_offset_to_target_arcsec']:.1f}\"/{entry['diff_peak_offset_to_neighbour_arcsec']:.1f}\"; "
          f"tight {entry['depth_tight_r0.75_pct']} std {entry['depth_standard_r2.0_pct']} "
          f"neigh-ap {entry['depth_neighbour_r1.5_pct']}", flush=True)
    del tpf, t, cube, in_img, out_img, diff

with open("blend_check_stage3.json", "w") as fh:
    json.dump(results, fh, indent=1)
print("wrote blend_check_stage3.json")
