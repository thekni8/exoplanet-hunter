"""Pair vetting stage 3b: QLP aperture autopsy for sector 35 (+62).

Resolves the fold paradox: A's QLP curve folds 2.5x deeper than C's own,
yet difference imaging puts the variable source on C. Reads the APERTURE
extensions of the cached QLP FITS files for A and C, maps mask pixels to
sky via the TESSCut WCS of the same sector, measures each mask's flux
share per star on the out-of-eclipse image, and re-photometers the
TESSCut pixels through each QLP mask to reproduce the depths.
Output: pair_stage3b.json. Read-only.
"""
import glob
import json
import numpy as np
import lightkurve as lk
from astropy.coordinates import SkyCoord
from astropy.io import fits

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


def win(ph, centre, half):
    return np.abs(((ph - centre + 0.5) % 1.0) - 0.5) <= half


def depths(ph, fl):
    plat = np.concatenate([fl[win(ph, 0.25, 0.06)], fl[win(ph, 0.75, 0.06)]])
    dI = 1 - np.mean(fl[win(ph, 0.0, 0.06)]) / np.mean(plat)
    dII = 1 - np.mean(fl[win(ph, 0.5, 0.06)]) / np.mean(plat)
    return float(100 * dI), float(100 * dII)


def find_qlp(tic, sec):
    pats = [f"/home/hatch/.lightkurve/cache/**/hlsp_qlp_tess_ffi_s{sec:04d}-"
            f"{tic:016d}*.fits", f"/home/hatch/.lightkurve/cache/**/*{tic}*s{sec:04d}*.fits"]
    for p in pats:
        hits = glob.glob(p, recursive=True)
        if hits:
            return hits[0]
    # generic fallback: any file mentioning the tic
    hits = glob.glob("/home/hatch/.lightkurve/cache/**/*.fits", recursive=True)
    hits = [h for h in hits if str(tic) in h and f"s{sec:04d}" in h]
    return hits[0] if hits else None


out = {}
for sec in (35, 62):
    print(f"--- sector {sec}", flush=True)
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
    in_img = np.nanmedian(cube[win(ph, 0.0, 0.05)], axis=0)
    out_img = np.nanmedian(
        cube[win(ph, 0.25, 0.07) | win(ph, 0.75, 0.07)], axis=0)
    diff = out_img - in_img
    wcs = tpf.wcs
    pix = {}
    for name, sc in STARS.items():
        x, y = wcs.world_to_pixel(sc)
        pix[name] = (float(x), float(y))
    entry = {"star_pix": {k: list(v) for k, v in pix.items()}}
    # local depth at each star's brightest pixel
    for name, (x, y) in pix.items():
        xi, yi = int(round(x)), int(round(y))
        o = float(out_img[yi, xi])
        d = float(diff[yi, xi])
        entry[f"local_depth_at_{name}_pct"] = 100 * d / o if o > 0 else None
    # QLP masks
    yy, xx = np.mgrid[0:cube.shape[1], 0:cube.shape[2]]
    for tic, label in ((31315594, "A_31315594"), (31315574, "C_31315574")):
        path = find_qlp(tic, sec)
        if path is None:
            entry[f"qlp_mask_{label}"] = {"error": "file not found in cache"}
            continue
        with fits.open(path) as hdul:
            ext_names = [h.name for h in hdul]
            ap = None
            for h in hdul:
                if h.name.upper() == "APERTURE" and h.data is not None:
                    ap = np.asarray(h.data)
                    break
        if ap is None:
            entry[f"qlp_mask_{label}"] = {"error": "no APERTURE ext",
                                          "extensions": ext_names,
                                          "file": path}
            continue
        # QLP aperture FITS is a small stamp; its WCS differs from TESSCut.
        # Use the file's own WCS if present, else align by shape centre.
        mask = ap > 0
        info = {"file": path.split("/")[-1], "mask_shape": list(mask.shape),
                "n_mask_pix": int(mask.sum())}
        # Photometer TESSCut pixels through a mask of the same shape placed
        # on the star's TESSCut pixel position (stamp assumed centred on
        # the target, as QLP stamps are).
        cx, cy = pix[label]
        mh, mw = mask.shape
        x0 = int(round(cx - (mw - 1) / 2))
        y0 = int(round(cy - (mh - 1) / 2))
        big = np.zeros(cube.shape[1:], dtype=bool)
        ys = slice(max(0, y0), min(big.shape[0], y0 + mh))
        xs = slice(max(0, x0), min(big.shape[1], x0 + mw))
        sub = mask[ys.start - y0:ys.stop - y0, xs.start - x0:xs.stop - x0]
        big[ys, xs] = sub
        if big.sum() > 0:
            fl = np.nansum(cube[:, big], axis=1)
            fl = fl / np.median(fl)
            dI, dII = depths(ph, fl.astype(np.float64))
            info["depth_through_qlp_mask_pct"] = [dI, dII]
            # flux shares: assign each mask pixel to nearest star
            dists = {}
            for name, (sx, sy) in pix.items():
                dists[name] = np.hypot(xx - sx, yy - sy)
            stack = np.stack([dists[k] for k in
                              ("A_31315594", "B_31315605", "C_31315574",
                               "D_31315592")])
            nearest = np.argmin(stack, axis=0)
            names = ["A_31315594", "B_31315605", "C_31315574", "D_31315592"]
            shares = {}
            tot = float(np.nansum(out_img[big]))
            for i, name in enumerate(names):
                sel = big & (nearest == i)
                shares[name] = float(np.nansum(out_img[sel]) / tot) if tot > 0 else None
            info["mask_flux_share_by_nearest_star"] = shares
            # mask centroid offset from the target star
            wgt = np.where(big, np.nan_to_num(out_img), 0.0)
            ccx = float((wgt * xx).sum() / wgt.sum())
            ccy = float((wgt * yy).sum() / wgt.sum())
            csky = SkyCoord.from_pixel(ccx, ccy, wcs)
            info["mask_flux_centroid_offset_arcsec"] = {
                name: float(csky.separation(sc).arcsec)
                for name, sc in STARS.items()}
        entry[f"qlp_mask_{label}"] = info
        print(f"    QLP mask {label}: {info}", flush=True)
    out[str(sec)] = entry
    print(f"    local depths: " +
          ", ".join(f"{n} {entry[f'local_depth_at_{n}_pct']:.1f}%"
                    for n in STARS if entry[f'local_depth_at_{n}_pct'] is not None),
          flush=True)
    del tpf, t, cube, in_img, out_img, diff

with open("pair_stage3b.json", "w") as fh:
    json.dump(out, fh, indent=1)
print("wrote pair_stage3b.json")
