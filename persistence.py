#!/usr/bin/env python
"""Sector-by-sector persistence test — replicates the method of
CANDIDATE_374942698_FOLLOWUP.md exactly:

* Flux = the production pipeline's own stitched two-pass transit-masked
  flattened flux (hunter._run_pipeline internals), split back into
  sectors via the downloaded products' time ranges / SECTOR meta.
* Fixed ephemeris (period, T0, duration) passed in from the analyze stage.
* Per sector: depth = (mean out-of-transit - mean in-transit) x 100 (%),
  in-transit = |phase| <= duration/2. A transit event's window is
  "fully covered" if points x median-cadence >= 80% of the window.
  A sector is usable if it has >= 1 fully-covered event.
* Uncertainty: out-of-transit flux is chunked at the transit-duration
  timescale; chunk_sigma = std of chunk means;
  sigma = chunk_sigma x sqrt(1/n_full_events + 1/n_chunks_out)
  (prices in red noise at the transit timescale).
* Verdict rules (set in advance, same as the follow-up):
  CONSISTENT = >=70% of usable sectors show a dip >= 1.5 sigma AND
  depths compatible with a constant (chi2 p > 0.01, with each
  sector's sigma carrying a 15% fractional systematic floor in
  quadrature — 2026-11-13 injection-recovery fix: per-sector
  systematics scatter depths by ~23-29% while chunk sigmas claim
  ~0.02-0.07%, so without the floor chi2 grows as depth^2 and
  strong real signals are vetoed as MIXED);
  CONCENTRATED = positive (>=1.5 sigma) fraction <= 30%; else MIXED.
"""
import gc
import warnings

import numpy as np
from scipy import stats

warnings.filterwarnings("ignore")

import hunter  # noqa: E402
import lightkurve as lk  # noqa: E402

# Fractional systematic floor for the persistence chi2 test
# (2026-11-13, injection-recovery INJECTION_RECOVERY.md §4).
# Per-sector depths scatter by 23-29% (fractional) on a QLP star
# (TIC 238620464) while the chunk-sigma noise model claims
# ~0.02-0.07% precision, so chi2 grows as depth^2 and STRONGER real
# signals are MORE likely to be vetoed as MIXED/"patchy" and dropped
# without hand-vetting. Each sector's sigma gains the floor in
# quadrature: sigma_eff^2 = sigma^2 + (0.15 * |sector depth|)^2,
# using that sector's own |depth| as the reference — exactly as
# diagnosed in diag_stamp.py §(c), which rescued trial 12
# (chi2 p 0.0014 -> 0.26). The floor applies ONLY to the chi2
# consistency test; the frac clause, the raw-depth clause and the
# reported weighted mean keep the original sigmas.
CHI2_SYS_FRAC = 0.15


def _chi2_consistency(depths, sigmas):
    """Chi2 consistency of per-sector depths against a constant depth,
    with the systematic floor (CHI2_SYS_FRAC) on each sector's sigma.
    The systematic uses each sector's own |depth| as its reference.
    The weighted mean for the chi2 test is recomputed under the
    inflated sigmas (the best-fit constant under the floored noise
    model). Returns a dict with the floored chi2/dof/p plus the
    unfloored values for auditing."""
    d = np.asarray(depths, dtype=float)
    sg = np.asarray(sigmas, dtype=float)
    w = 1.0 / sg ** 2
    wmean = float(np.sum(w * d) / np.sum(w))
    chi2_unfloored = float(np.sum(((d - wmean) / sg) ** 2))
    dof = len(d) - 1
    p_unfloored = (float(stats.chi2.sf(chi2_unfloored, dof))
                   if dof > 0 else None)
    sg_eff = np.sqrt(sg ** 2 + (CHI2_SYS_FRAC * np.abs(d)) ** 2)
    w_eff = 1.0 / sg_eff ** 2
    wmean_eff = float(np.sum(w_eff * d) / np.sum(w_eff))
    chi2 = float(np.sum(((d - wmean_eff) / sg_eff) ** 2))
    p = float(stats.chi2.sf(chi2, dof)) if dof > 0 else None
    return {"chi2": chi2, "dof": dof, "chi2_p": p,
            "wmean_eff": wmean_eff,
            "chi2_unfloored": chi2_unfloored,
            "chi2_p_unfloored": p_unfloored}


def _sector_ranges(tic_id, max_sectors, progress_callback=None):
    """Sector time ranges from the pipeline's OWN product selection.

    (2026-11-13 fix — Gemini review + parent verification.) The old
    code sliced the first ``max_sectors`` ROWS of one multi-author
    search, which (a) could pick different products than the pipeline
    analysed (its ranges then sliced the wrong time windows out of
    the stitched flux), and (b) counted one sector TWICE when both
    20 s and 120 s products exist (TOI-700: 20 ranges covering only
    16 distinct sectors, sectors 27/28/30/31 graded twice). Now the
    ranges come from hunter._select_products — one author per star,
    most sectors wins, SPOC > TESS-SPOC > QLP, one product per sector
    preferring 120 s — so the stamp grades exactly the data the
    pipeline ran on. The post-download dedupe below is a safety net
    for _select_products' unfiltered-fallback path only; it keeps
    the first range per sector.
    """
    tic_id = str(tic_id)

    def _select():
        return hunter._select_products(tic_id, max_sectors,
                                       progress_callback)

    search = hunter._with_download_self_heal(_select, progress_callback)
    coll = hunter._download_products(search, tic_id, progress_callback)
    ranges = []
    seen_sectors = set()
    for lc in coll:
        t = np.asarray(lc.time.value, dtype=float)
        t = t[np.isfinite(t)]
        sector = lc.meta.get("SECTOR")
        sector = int(sector) if sector is not None else None
        if sector is not None:
            if sector in seen_sectors:
                continue
            seen_sectors.add(sector)
        ranges.append({"sector": sector,
                       "tmin": float(t.min()), "tmax": float(t.max())})
    del coll
    gc.collect()
    return ranges


def sector_persistence(tic_id, star_radius, period_days, t0_days,
                       duration_hours, sector_cap=20, progress_callback=None):
    """Run the production pipeline for its fluxes, then measure the
    fixed-ephemeris depth sector by sector. Returns a JSON-able dict."""
    tic_id = str(tic_id)
    full = hunter._run_pipeline(
        tic_id, star_radius=star_radius, bls_points=10000,
        max_sectors=sector_cap, progress_callback=progress_callback)
    ranges = _sector_ranges(tic_id, sector_cap, progress_callback)

    ft = np.asarray(full["flat_time"], dtype=float)
    ff = np.asarray(full["flat_flux"], dtype=float)
    rt = np.asarray(full["raw_time"], dtype=float)
    rf = np.asarray(full["raw_flux"], dtype=float)
    P = float(period_days)
    T0 = float(t0_days)
    DUR = float(duration_hours) / 24.0

    def phase_of(t):
        return ((t - T0 + 0.5 * P) % P) - 0.5 * P

    sectors_out = []
    events_out = []
    for rng in ranges:
        m = (ft >= rng["tmin"]) & (ft <= rng["tmax"])
        t, f = ft[m], ff[m]
        mr = (rt >= rng["tmin"]) & (rt <= rng["tmax"])
        tr, fr = rt[mr], rf[mr]
        if len(t) < 50:
            continue
        med_dt = float(np.median(np.diff(np.sort(t))))
        cadence_min = med_dt * 1440.0
        ph = phase_of(t)
        in_mask = np.abs(ph) <= DUR / 2.0
        out_mask = ~in_mask
        phr = phase_of(tr)
        in_mask_r = np.abs(phr) <= DUR / 2.0

        # transit events whose windows intersect this sector
        k0 = int(np.floor((rng["tmin"] - DUR - T0) / P))
        k1 = int(np.ceil((rng["tmax"] + DUR - T0) / P))
        n_span, n_full, ev_depths = 0, 0, []
        for k in range(k0, k1 + 1):
            tc = T0 + k * P
            w0, w1 = tc - DUR / 2.0, tc + DUR / 2.0
            if w1 < rng["tmin"] or w0 > rng["tmax"]:
                continue
            n_span += 1
            wm = (t >= w0) & (t <= w1)
            coverage = wm.sum() * med_dt / DUR if DUR > 0 else 0.0
            if coverage >= 0.8:
                n_full += 1
                ev_depths.append((tc, wm))

        depth_pct = None
        depth_raw_pct = None
        out_mean = float(np.mean(f[out_mask])) if out_mask.any() else np.nan
        if in_mask.any() and out_mask.any():
            depth_pct = (out_mean - float(np.mean(f[in_mask]))) * 100.0
        if in_mask_r.any() and (~in_mask_r).any() and len(fr):
            depth_raw_pct = (float(np.mean(fr[~in_mask_r]))
                             - float(np.mean(fr[in_mask_r]))) * 100.0

        # chunked red-noise sigma from out-of-transit data
        t_out, f_out = t[out_mask], f[out_mask]
        chunk_means = []
        if len(t_out):
            edges = np.arange(rng["tmin"], rng["tmax"] + DUR, DUR)
            idx = np.clip(np.digitize(t_out, edges) - 1, 0, len(edges) - 2)
            for c in range(len(edges) - 1):
                vals = f_out[idx == c]
                if len(vals):
                    chunk_means.append(float(np.mean(vals)))
        chunk_sigma_pct = (float(np.std(chunk_means, ddof=1)) * 100.0
                           if len(chunk_means) > 1 else None)
        n_chunks = len(chunk_means)

        usable = n_full >= 1
        sigma_pct = None
        signif = None
        if usable and chunk_sigma_pct is not None and depth_pct is not None:
            sigma_pct = chunk_sigma_pct * np.sqrt(1.0 / n_full + 1.0 / n_chunks)
            signif = depth_pct / sigma_pct if sigma_pct > 0 else None

        for tc, wm in ev_depths:
            ev = {"sector": rng["sector"], "center_btjd": round(float(tc), 5)}
            if out_mask.any() and wm.any():
                ev["depth_pct"] = (out_mean - float(np.mean(f[wm]))) * 100.0
            wmr = (tr >= tc - DUR / 2.0) & (tr <= tc + DUR / 2.0)
            if wmr.any() and (~in_mask_r).any() and len(fr):
                ev["depth_raw_pct"] = (float(np.mean(fr[~in_mask_r]))
                                       - float(np.mean(fr[wmr]))) * 100.0
            events_out.append(ev)

        sectors_out.append({
            "sector": rng["sector"], "n_points": int(len(t)),
            "cadence_min": cadence_min,
            "n_in": int(in_mask.sum()), "n_out": int(out_mask.sum()),
            "events_in_span": n_span, "full_events": n_full,
            "depth_pct": depth_pct, "depth_raw_pct": depth_raw_pct,
            "chunk_sigma_pct": chunk_sigma_pct, "n_chunks_out": n_chunks,
            "sigma_pct": sigma_pct, "signif": signif, "usable": bool(usable),
        })

    usable_secs = [s for s in sectors_out
                   if s["usable"] and s["sigma_pct"] and s["depth_pct"] is not None]
    result = {
        "tic": tic_id, "period_days": P, "t0_btjd": T0,
        "duration_hours": float(duration_hours),
        "n_sectors_total": len(sectors_out),
        "n_usable": len(usable_secs),
        "sectors": sectors_out, "events": events_out,
    }
    if usable_secs:
        d = np.array([s["depth_pct"] for s in usable_secs])
        sg = np.array([s["sigma_pct"] for s in usable_secs])
        w = 1.0 / sg ** 2
        wmean = float(np.sum(w * d) / np.sum(w))
        # Chi2 consistency test, with the systematic floor
        # (CHI2_SYS_FRAC — see the constant's comment). The reported
        # wmean / weighted_mean_sigma_pct keep the original sigmas;
        # only the consistency test uses the inflated ones.
        _c2 = _chi2_consistency(d, sg)
        chi2, dof, p = _c2["chi2"], _c2["dof"], _c2["chi2_p"]
        n_pos = int(np.sum([s["signif"] >= 1.5 for s in usable_secs]))
        frac_pos = n_pos / len(usable_secs)
        if frac_pos >= 0.70 and (p is not None and p > 0.01):
            verdict = "CONSISTENT"
        elif frac_pos <= 0.30:
            verdict = "CONCENTRATED"
        else:
            verdict = "MIXED"
        # --- Raw-depth criterion (2026-11-10) -------------------------
        # The depths above are measured on the pipeline's FLATTENED
        # flux, and the pass-2 manufacture (TIC 294873918, raw depth
        # -0.0006% at its own filed ephemeris) proved a flattened-flux
        # dip can be pure detrend artefact — the stamp then "confirms"
        # the same manufactured dip sector by sector. depth_raw_pct,
        # already measured per sector on the RAW flux, is the
        # independent witness; combine it with the same inverse-
        # variance weights (the per-sector sigma prices red noise at
        # the transit timescale on the same data, so it is the right
        # noise scale for the raw means too). A CONSISTENT stamp may
        # not stand when the combined raw depth is <= 0 or
        # insignificant (< 3 sigma, the hunter._raw_fold_depth bar):
        # the verdict becomes RAW-REFUTED and the raw numbers ride
        # along in the record.
        raw_secs = [s for s in usable_secs
                    if s["depth_raw_pct"] is not None]
        raw_wmean = raw_sigma = raw_signif = raw_frac_pos = None
        if raw_secs:
            dr = np.array([s["depth_raw_pct"] for s in raw_secs])
            wr = 1.0 / np.array([s["sigma_pct"] for s in raw_secs]) ** 2
            raw_wmean = float(np.sum(wr * dr) / np.sum(wr))
            raw_sigma = float(1.0 / np.sqrt(np.sum(wr)))
            raw_signif = raw_wmean / raw_sigma if raw_sigma > 0 else None
            raw_frac_pos = float(np.mean(dr > 0))
        raw_refuted = False
        if verdict == "CONSISTENT" and (
                raw_wmean is None or raw_wmean <= 0.0
                or raw_signif is None or raw_signif < 3.0):
            verdict = "RAW-REFUTED"
            raw_refuted = True
        result.update({
            "n_pos_1p5sigma": n_pos, "frac_pos_1p5sigma": frac_pos,
            "weighted_mean_depth_pct": wmean,
            "weighted_mean_sigma_pct": float(1.0 / np.sqrt(np.sum(w))),
            "chi2": chi2, "dof": dof, "chi2_p": p, "verdict": verdict,
            "chi2_sys_frac": CHI2_SYS_FRAC,
            "chi2_unfloored": _c2["chi2_unfloored"],
            "chi2_p_unfloored": _c2["chi2_p_unfloored"],
            "raw_weighted_mean_depth_pct": raw_wmean,
            "raw_combined_sigma_pct": raw_sigma,
            "raw_signif": raw_signif,
            "raw_frac_sectors_positive": raw_frac_pos,
            "raw_refuted": raw_refuted,
        })
        ev_d = [e["depth_pct"] for e in events_out if "depth_pct" in e]
        if ev_d:
            result["event_depth_median_pct"] = float(np.median(ev_d))
            result["event_depth_mean_pct"] = float(np.mean(ev_d))
            result["event_frac_positive"] = float(np.mean(np.array(ev_d) > 0))
            result["n_full_events"] = len(ev_d)
    else:
        result["verdict"] = "NO USABLE SECTORS"
    # blend-monster scan: any sector (usable or not) with a huge raw depth
    monsters = [{"sector": s["sector"], "depth_raw_pct": s["depth_raw_pct"],
                 "depth_pct": s["depth_pct"]}
                for s in sectors_out
                if s["depth_raw_pct"] is not None and abs(s["depth_raw_pct"]) >= 5.0]
    result["raw_monster_sectors"] = monsters
    del full
    gc.collect()
    return result
