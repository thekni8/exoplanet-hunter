"""P4-3: multi-sector stitching.

Phase 4, item 4-3 (build brief P4-3; PB-3; PB-6 A9/A10/A2/A18).
P4-1b PASSED its gate (K=3, 69/451) and the parent adopted K=3 (Arm A
prototype) with the depth trigger DROPPED, the 25% cap settled, and
NO combined mask. This module adds the multi-sector stitch:

  per sector: fresh pass 1 -> estimate contaminant ephemeris ->
  pre-mask if a confirmed contaminant -> stitch (inverse-variance
  weighted) -> K=3 on the stitched curve.

Design (pre-registered in P43_PREREG.md, written BEFORE any P4-3
measurement — do not tune on outcomes):

- Per-sector preprocessing is the identical front end to
  _screen_one (orc.preprocess_arrays): quality mask -> normalise
  (per-sector median) -> MAD clip -> SavGol flatten.
- Inverse-variance weighting: per sector s, sigma_s = 1.4826 * MAD
  of the preprocessed flux. The stitched flux scales each sector's
  deviations: f'_s = 1 + (f_s - 1) * (sigma_ref / sigma_s), with
  sigma_ref = min_s sigma_s (quietest sector unscaled). This makes
  the stitched series homoscedastic at sigma_ref, so the frozen BLS
  (which takes no per-cadence weights) sees an optimally weighted
  series. Measured on the Mac 2026-11-18 (34 TICs): sigma ratios
  (max/min) median 1.092, p90 1.190, max 1.338.
- CROWDSAP tracking: the QLP FITS headers carry NO
  CROWDSAP/CONTAM/DILU keyword (verified on the Mac 2026-11-18) --
  recorded as None with this reason. The injected depth is the
  APPARENT depth in every sector (same as the single-sector
  campaign). Per-sector fcol is SYS_RM_FLUX for all files; recorded.
- Stitch: concatenate the (t, f', q) triples, time-sort
  (k3.stitch_sectors). The stitched curve is screened by the
  UNCHANGED _screen_one (frozen grid: 12,000 points).
- Per-orbit guard bands: the P4-2 event filter (_rescore, guard
  0.0 d) splits the stitched curve into contiguous valid segments
  at gaps > 0.05 d -- sector boundaries ARE such gaps, so events
  spanning a sector boundary are excluded by the existing rule.
- Sector-dropout diagnostics: for a found ephemeris, per-sector
  in-transit cadence counts and folded depths (the check that the
  signal is present in all sectors vs one).

Offline and pure: no downloads, no BLS search. Depends on
bulk_screen for _fold_depth, on bulk/oracle_run for
preprocess_arrays, and on bulk/k3_prototype for stitch_sectors.
"""

import numpy as np

import bulk_screen as bs

from bulk import detrend as _detrend
from bulk import k3_prototype as k3
from bulk import oracle_run as orc


def sector_sigma(t_p, f_p):
    """Robust sigma of a preprocessed sector curve: 1.4826 * MAD."""
    f_p = np.asarray(f_p, dtype=float)
    f_p = f_p[np.isfinite(f_p)]
    if len(f_p) == 0:
        return None
    med = float(np.median(f_p))
    return float(1.4826 * np.median(np.abs(f_p - med)))


def read_crowdsap(path):
    """CROWDSAP from a QLP FITS header, or None.

    The cached QLP HLSP files carry no CROWDSAP/CONTAM/DILU keyword
    (verified on the Mac 2026-11-18) -- the caller records None with
    the reason "not in QLP header". This helper exists so the
    tracking is explicit rather than silently absent.
    """
    from astropy.io import fits
    with fits.open(path, memmap=True) as hdul:
        hdr = hdul[0].header
        for key in ("CROWDSAP", "CONTAM", "DILU"):
            if key in hdr:
                try:
                    return float(hdr.get(key))
                except (TypeError, ValueError):
                    return None
    return None


def stitch_weighted(masked_sectors, sigmas):
    """Inverse-variance-weighted stitch of per-sector masked curves.

    masked_sectors is a list of dicts, one per sector, each with:
      sector (int), t, f, q (raw arrays AFTER the per-sector
      pre-mask has dropped cadences), fcol (str), crowdsap (float
      or None).
    sigmas maps sector -> robust sigma of the preprocessed curve
    (from sector_sigma; None values are treated as the reference).

    Returns (t_s, f_s, q_s, tracking): the stitched time-sorted
    arrays and a tracking dict with per-sector sigma, weight
    (sigma_ref/sigma_s), scale applied, cadence counts, fcol and
    crowdsap, plus sigma_ref and the sector list. The flux scaling
    is f'_s = 1 + (f_s - 1) * (sigma_ref/sigma_s): deviations from
    1 are scaled, so the median stays ~1 and the transit depth in
    the stitched curve is the noise-weighted mean depth. A sector
    with sigma None (or <= 0) is stitched unscaled (scale 1.0) and
    flagged in the tracking.
    """
    usable = [s for s in masked_sectors
              if sigmas.get(s["sector"]) is not None
              and sigmas[s["sector"]] > 0]
    if usable:
        sigma_ref = min(sigmas[s["sector"]] for s in usable)
    else:
        sigma_ref = None
    parts_t, parts_f, parts_q = [], [], []
    tracking = {"sigma_ref": sigma_ref, "sectors": {},
                "n_sectors": len(masked_sectors)}
    for s in masked_sectors:
        sec = s["sector"]
        t = np.asarray(s["t"], dtype=float)
        f = np.asarray(s["f"], dtype=float)
        q = np.asarray(s["q"])
        sig = sigmas.get(sec)
        if sig is not None and sig > 0 and sigma_ref is not None:
            scale = float(sigma_ref / sig)
        else:
            scale = 1.0
        f_w = 1.0 + (f - 1.0) * scale
        parts_t.append(t)
        parts_f.append(f_w)
        parts_q.append(q)
        tracking["sectors"][sec] = {
            "sigma": sig, "weight": (1.0 / sig ** 2
                                     if sig else None),
            "scale": scale, "n_cadences": int(len(t)),
            "fcol": s.get("fcol"), "crowdsap": s.get("crowdsap"),
            # unscaled iff the scale is 1.0 for a reason other than
            # being the reference sector (missing/non-positive sigma).
            "unscaled": bool(sig is None or sig <= 0
                             or sigma_ref is None),
        }
    if not parts_t:
        return (np.array([], dtype=float), np.array([], dtype=float),
                np.array([], dtype=int), tracking)
    t_s, f_s, q_s = k3.stitch_sectors(
        list(zip(parts_t, parts_f, parts_q)))
    tracking["n_cadences_total"] = int(len(t_s))
    tracking["t_min"] = float(np.nanmin(t_s)) if len(t_s) else None
    tracking["t_max"] = float(np.nanmax(t_s)) if len(t_s) else None
    return t_s, f_s, q_s, tracking


def sector_consistency(t_s, f_s, q_s, bounds, period, t0, duration):
    """Per-sector transit-consistency record at a found ephemeris.

    bounds is a list of (sector, t_min, t_max) covering the stitched
    curve's sectors (from the per-sector arrays before stitching).
    Returns {sector: {n_in_transit, depth_frac, n_cadences}}: the
    folded depth at the found ephemeris computed on that sector's
    cadences alone (bs._fold_depth on the stitched arrays restricted
    to the sector's time span). A real planet shows a consistent
    depth in every sector; a single-sector systematic shows ~0
    elsewhere. t_s/f_s/q_s are the STITCHED arrays (already
    preprocessed by the screen's front end is NOT assumed -- the
    caller passes the arrays the fold should run on, normally the
    preprocessed stitched curve).
    """
    out = {}
    for sec, lo, hi in bounds:
        m = (np.asarray(t_s) >= lo) & (np.asarray(t_s) <= hi)
        n = int(m.sum())
        if n < 10:
            out[sec] = {"n_cadences": n, "n_in_transit": 0,
                        "depth_frac": None}
            continue
        depth, n_in, _noise = bs._fold_depth(
            np.asarray(t_s)[m], np.asarray(f_s)[m], period, t0,
            duration)
        out[sec] = {"n_cadences": n,
                    "n_in_transit": int(n_in),
                    "depth_frac": (float(depth)
                                   if depth is not None
                                   and np.isfinite(depth) else None)}
    return out


def preprocess_sector(t, f, q, detrend="v6"):
    """Preprocess one sector's (raw, injected) curve + its sigma.

    Returns (t_p, f_p, sigma): the arrays as they enter BLS
    (orc.preprocess_arrays) and the robust sigma of the flattened
    flux. The sigma is the inverse-variance weight input.

    5.7 (R3): under detrend "v7" the returned arrays are
    PRE-SavGol (no flatten — _screen_one flattens the stitched
    curve at 1.0 d) and the sigma is computed from a TEMPORARY
    1.0 d flattened copy of the pre-SavGol arrays. The flattened
    copy is used ONLY for the sigma, never stitched.
    """
    t_p, f_p = orc.preprocess_arrays(t, f, q, detrend=detrend)
    if detrend == _detrend.DETREND_V7:
        trend = _detrend.savgol_trend(t_p, f_p,
                                      _detrend.WINDOW_V7_D)
        f_flat = f_p / trend
        f_flat = f_flat - np.median(f_flat) + 1.0
        return t_p, f_p, sector_sigma(t_p, f_flat)
    return t_p, f_p, sector_sigma(t_p, f_p)
