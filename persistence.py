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
  depths compatible with a constant (chi2 p > 0.01);
  CONCENTRATED = positive (>=1.5 sigma) fraction <= 30%; else MIXED.
"""
import gc
import warnings

import numpy as np
from scipy import stats

warnings.filterwarnings("ignore")

import hunter  # noqa: E402
import lightkurve as lk  # noqa: E402


def _sector_ranges(tic_id, max_sectors, progress_callback=None):
    """Mirror _run_pipeline's search/download; return per-product
    {sector, tmin, tmax} in collection order (downloads are cached)."""
    tic_id = str(tic_id)

    def _search():
        s = lk.search_lightcurve(f"TIC {tic_id}",
                                 author=["SPOC", "TESS-SPOC", "QLP"])
        if len(s) == 0:
            s = lk.search_lightcurve(f"TIC {tic_id}")
        if len(s) == 0:
            raise RuntimeError(f"No mission data found for TIC {tic_id}.")
        return s

    search = hunter._with_download_self_heal(_search, progress_callback)
    sub = search if max_sectors is None else search[:max_sectors]
    coll = hunter._download_products(sub, tic_id, progress_callback)
    ranges = []
    for lc in coll:
        t = np.asarray(lc.time.value, dtype=float)
        t = t[np.isfinite(t)]
        sector = lc.meta.get("SECTOR")
        ranges.append({"sector": int(sector) if sector is not None else None,
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
        chi2 = float(np.sum(((d - wmean) / sg) ** 2))
        dof = len(usable_secs) - 1
        p = float(stats.chi2.sf(chi2, dof)) if dof > 0 else None
        n_pos = int(np.sum([s["signif"] >= 1.5 for s in usable_secs]))
        frac_pos = n_pos / len(usable_secs)
        if frac_pos >= 0.70 and (p is not None and p > 0.01):
            verdict = "CONSISTENT"
        elif frac_pos <= 0.30:
            verdict = "CONCENTRATED"
        else:
            verdict = "MIXED"
        result.update({
            "n_pos_1p5sigma": n_pos, "frac_pos_1p5sigma": frac_pos,
            "weighted_mean_depth_pct": wmean,
            "weighted_mean_sigma_pct": float(1.0 / np.sqrt(np.sum(w))),
            "chi2": chi2, "dof": dof, "chi2_p": p, "verdict": verdict,
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
