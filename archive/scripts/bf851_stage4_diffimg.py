"""Big-fish gauntlet stage 4 — TIC 309760851 difference imaging (TESSCut).

Adapted from blend_stage3_diffimg.py (the TIC 167367406 blend check).
Question: does the 0.7083 d varying flux sit on the target
(TIC 309760851, Tmag 14.23) or on the catalogued RR Lyrae 23.6" away
(TIC 733257403, Tmag 18.54, VSX RRAB P 0.70817 d)?

Usage: bf851_stage4_diffimg.py P T0 [sector ...]   (default sectors 2 8 12)
Median out-of-dip minus in-dip images at the sweep ephemeris; difference
centroid + peak offsets to both stars; aperture folds: tight/standard on
target, r<=1.5 px on the RR Lyrae, incl. full phase-binned amplitude of
the RR-Lyrae aperture (an RRab sawtooth there settles the photocopy).
One sector at a time; float32 cubes freed between sectors.
Output: vetting_results/bf851_stage4.json
"""
import json
import sys

import numpy as np
import lightkurve as lk
from astropy.coordinates import SkyCoord

P = float(sys.argv[1])
T0 = float(sys.argv[2])
SECTORS = [int(s) for s in sys.argv[3:]] or [2, 8, 12]

TARGET = SkyCoord(ra=80.1053299464223, dec=-65.0991806063304, unit="deg")
NEIGH = SkyCoord(ra=80.0902757506244, dec=-65.1008447352653, unit="deg")


def win(ph, centre, half):
    return np.abs(((ph - centre + 0.5) % 1.0) - 0.5) <= half


def depths(ph, fl):
    plat = np.concatenate([fl[win(ph, 0.25, 0.06)], fl[win(ph, 0.75, 0.06)]])
    dI = 1 - np.mean(fl[win(ph, 0.0, 0.06)]) / np.mean(plat)
    dII = 1 - np.mean(fl[win(ph, 0.5, 0.06)]) / np.mean(plat)
    return float(100 * dI), float(100 * dII)


def phase_amplitude(ph, fl, nbins=20):
    """(max-min)/median of the phase-binned curve, in percent."""
    bins = np.linspace(0, 1, nbins + 1)
    idx = np.digitize(ph, bins) - 1
    prof = np.array([np.median(fl[idx == i]) if np.any(idx == i) else np.nan
                     for i in range(nbins)])
    return float(100 * (np.nanmax(prof) - np.nanmin(prof)) / np.nanmedian(prof))


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


results = {"P": P, "T0": T0, "sectors": {}}
for sec in SECTORS:
    print(f"--- sector {sec}", flush=True)
    sr = lk.search_tesscut(TARGET, sector=sec)
    if len(sr) == 0:
        results["sectors"][str(sec)] = {"error": "no tesscut"}
        continue
    try:
        tpf = sr.download(cutout_size=13)
    except TypeError:
        tpf = sr.download()
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
    tx, ty = wcs.world_to_pixel(TARGET)
    nx, ny = wcs.world_to_pixel(NEIGH)
    dsky, dpix = centroid_sky(wcs, diff)
    pk = np.unravel_index(np.nanargmax(diff), diff.shape)
    pk_sky = SkyCoord.from_pixel(float(pk[1]), float(pk[0]), wcs)
    entry = {
        "n_cadences": int(t.size), "n_in": int(in_m.sum()),
        "n_out": int(out_m.sum()),
        "target_pix": [float(tx), float(ty)],
        "neigh_pix": [float(nx), float(ny)],
        "pix_sep": float(np.hypot(float(tx) - float(nx),
                                  float(ty) - float(ny))),
        "diff_centroid_offset_to_target_arcsec":
            float(dsky.separation(TARGET).arcsec),
        "diff_centroid_offset_to_rrlab_arcsec":
            float(dsky.separation(NEIGH).arcsec),
        "diff_peak_offset_to_target_arcsec":
            float(pk_sky.separation(TARGET).arcsec),
        "diff_peak_offset_to_rrlab_arcsec":
            float(pk_sky.separation(NEIGH).arcsec),
        "diff_peak_value_e_s": float(diff[pk]),
    }
    yy, xx = np.mgrid[0:cube.shape[1], 0:cube.shape[2]]
    r_t = np.hypot(xx - float(tx), yy - float(ty))
    r_n = np.hypot(xx - float(nx), yy - float(ny))
    bg_mask = (r_t > 5.0) & (r_n > 3.0)
    bg = np.nanmedian(cube[:, bg_mask], axis=1)
    for name, mask in (("tight_r0.75", r_t <= 0.75),
                       ("standard_r2.0", r_t <= 2.0),
                       ("rrlab_r1.5", r_n <= 1.5)):
        fl = np.nansum(cube[:, mask], axis=1) - bg * mask.sum()
        fl = fl / np.median(fl)
        dI, dII = depths(ph, fl.astype(np.float64))
        entry[f"depth_{name}_pct"] = [dI, dII]
        entry[f"phase_amp_{name}_pct"] = phase_amplitude(
            ph, fl.astype(np.float64))
    results["sectors"][str(sec)] = entry
    print(f"    diff centroid: {entry['diff_centroid_offset_to_target_arcsec']:.1f}\" "
          f"from target, {entry['diff_centroid_offset_to_rrlab_arcsec']:.1f}\" from RR Lyrae; "
          f"peak {entry['diff_peak_offset_to_target_arcsec']:.1f}\"/"
          f"{entry['diff_peak_offset_to_rrlab_arcsec']:.1f}\"", flush=True)
    print(f"    depths tight {entry['depth_tight_r0.75_pct']} "
          f"std {entry['depth_standard_r2.0_pct']} "
          f"rrlab-ap {entry['depth_rrlab_r1.5_pct']}; "
          f"phase amps tight {entry['phase_amp_tight_r0.75_pct']:.2f}% "
          f"rrlab {entry['phase_amp_rrlab_r1.5_pct']:.2f}%", flush=True)
    del tpf, t, cube, in_img, out_img, diff

with open("vetting_results/bf851_stage4.json", "w") as fh:
    json.dump(results, fh, indent=1)
print("wrote vetting_results/bf851_stage4.json")
