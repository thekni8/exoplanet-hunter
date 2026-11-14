"""Pixel check (Phase 2, 2A) — vetting-manual §7, P >= 8 d only.

The manual's rule: inspect the raw pixel flux at the folded
ephemeris for brightenings where the dip is claimed — a pixel
that brightens where a dip is claimed is contamination. No tool
existed for this in the repo (the manual gauntlet did it by eye
on TESSCut cutouts); this module is the automated version.

Method: fold every tested pixel's flux at the ephemeris (median
in/out depth + white significance, the same fold as
diffimg.fold_depth_simple). Two outcomes:

  * FAIL — some tested pixel brightens at >= BRIGHTEN_BAR sigma
    in transit. The record names the pixel and its significance.
  * PASS — the target pixel shows the dip at >= DIP_BAR sigma
    and no tested pixel brightens significantly.
  * UNMEASURED — too few in-transit cadences, or the target
    pixel shows no dip (the check cannot assess contamination
    on a signal that is not in the pixels; the off-target
    question belongs to difference imaging).

Which pixels are tested: the 3x3 around the target pixel — the
aperture the pipeline flux comes from. A brightening outside the
aperture does not contaminate the aperture flux; the off-target
question belongs to difference imaging. The manual gives no
numeric bar; both bars are 3 sigma — the house raw-flux bar
(gauntlet_v2 raw_flux_min_signif) — and the tested set is kept
to 9 pixels deliberately: a 3-sigma bar over a whole 15x15
cutout (225 pixels) would false-fail roughly 1 in 4 clean
targets on multiple comparisons alone. Depths are medians, so
the significance uses the median's standard error (1.2533 x
sigma / sqrt(n), the same factor as bulk/clean_refold_gate).
The bars and the tested-pixel rule are judgment calls recorded
in PHASE_2_PROGRESS.md for the Phase 2 vote.

The P >= 8 d floor is a RUNNER rule (runner.py assigns
NOT_APPLICABLE below it), not a tool rule — this module works
at any period.
"""
import numpy as np

BRIGHTEN_BAR = 3.0
DIP_BAR = 3.0
MEDIAN_SE_FACTOR = 1.2533
MIN_IN_TRANSIT = 5


def tested_pixels(flux_cube, target_px):
    """Boolean mask of the pixels the check tests: the 3x3 around
    the target pixel (the aperture). Pixels with no finite flux
    are excluded."""
    med = np.nanmedian(flux_cube, axis=0)
    ny, nx = med.shape
    xt, yt = int(round(target_px[0])), int(round(target_px[1]))
    mask = np.zeros((ny, nx), dtype=bool)
    mask[max(0, yt - 1):min(ny, yt + 2),
         max(0, xt - 1):min(nx, xt + 2)] = True
    mask[~np.isfinite(med)] = False
    return mask


def pixel_fold(flux_cube, time, period, t0, duration_d):
    """Per-pixel fold depth (%) + white significance at the
    ephemeris. Returns (depth_pct, signif, n_in) as 2D arrays
    (ny, nx) plus the in-transit cadence count."""
    t = np.asarray(time, dtype=float)
    cube = np.asarray(flux_cube, dtype=float)
    ph = ((t - t0 + 0.5 * period) % period) - 0.5 * period
    in_m = np.abs(ph) <= duration_d / 2
    out_m = np.abs(ph) > duration_d
    n_in = int(in_m.sum())
    ny, nx = cube.shape[1], cube.shape[2]
    depth = np.full((ny, nx), np.nan)
    signif = np.full((ny, nx), np.nan)
    if n_in < MIN_IN_TRANSIT or int(out_m.sum()) < 50:
        return depth, signif, n_in
    fin = cube[in_m]
    fout = cube[out_m]
    with np.errstate(invalid="ignore", divide="ignore"):
        med_in = np.nanmedian(fin, axis=0)
        med_out = np.nanmedian(fout, axis=0)
        sig_out = np.nanstd(fout, axis=0)
        depth = (med_out - med_in) / med_out * 100.0
        # Medians, so the standard error carries the 1.2533 factor
        # (same as bulk/clean_refold_gate).
        se_pct = (MEDIAN_SE_FACTOR * sig_out / med_out
                  / np.sqrt(n_in) * 100.0)
        signif = depth / se_pct
    return depth, signif, n_in


def pixel_check_native(flux_cube, time, period, t0, duration_d,
                       target_px):
    """Build the pixel_check stage native:
    {"verdict", "reason", "details"}."""
    depth, signif, n_in = pixel_fold(flux_cube, time, period, t0,
                                     duration_d)
    ny, nx = depth.shape
    xt, yt = int(round(target_px[0])), int(round(target_px[1]))
    if n_in < MIN_IN_TRANSIT:
        return {"verdict": "unmeasured",
                "reason": f"only {n_in} in-transit cadences",
                "details": {"n_in": n_in}}
    mask = tested_pixels(flux_cube, target_px)
    tested = [(int(y), int(x), float(depth[y, x]),
               float(signif[y, x]))
              for y in range(ny) for x in range(nx)
              if mask[y, x] and np.isfinite(depth[y, x])]
    details = {"n_in": n_in,
               "n_pixels_tested": len(tested),
               "pixels": [{"y": y, "x": x,
                           "depth_pct": round(d, 3),
                           "signif": round(s, 2)}
                          for y, x, d, s in tested]}
    # The most significant brightening (most negative depth).
    bright = min(tested, key=lambda r: r[3]) if tested else None
    if bright is not None and bright[3] <= -BRIGHTEN_BAR:
        y, x, d, s = bright
        return {"verdict": "fail",
                "reason": (f"pixel (x={x}, y={y}) brightens "
                           f"{-d:.3f}% in transit ({-s:.1f} sigma)"),
                "details": {**details, "brightening_pixel": {
                    "y": y, "x": x, "depth_pct": round(d, 3),
                    "signif": round(s, 2)}}}
    if not (0 <= yt < ny and 0 <= xt < nx):
        return {"verdict": "unmeasured",
                "reason": "target pixel outside the cutout",
                "details": details}
    td, ts = float(depth[yt, xt]), float(signif[yt, xt])
    details["target_pixel"] = {"y": yt, "x": xt,
                               "depth_pct": round(td, 3)
                               if np.isfinite(td) else None,
                               "signif": round(ts, 2)
                               if np.isfinite(ts) else None}
    if not np.isfinite(ts) or ts < DIP_BAR:
        return {"verdict": "unmeasured",
                "reason": "no dip at the target pixel "
                          f"({td:.3f}% at {ts:.1f} sigma)"
                          if np.isfinite(td) else
                          "no dip at the target pixel",
                "details": details}
    return {"verdict": "pass",
            "reason": (f"target pixel dips {td:.3f}% "
                       f"({ts:.1f} sigma); no pixel brightens "
                       f"above {BRIGHTEN_BAR} sigma"),
            "details": details}
