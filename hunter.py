#!/usr/bin/env python3
"""
Exoplanet Hunter — local CLI engine (Dev's original, reconciled).

This is Dev's local ``hunter.py`` — the version that lived only on his own
machine and was never committed to GitHub — rebuilt to his exact spec:
same function signatures, defaults, CLI flags, QA benchmarks, and
discoveries.csv / PNG behaviour. See STAGE1_REPORT.md for the reconciliation
notes.

Behaviour preserved from the original:
  * ``analyze_target`` searches MAST via lightkurve with
    author=["SPOC", "TESS-SPOC", "QLP"] (unfiltered fallback), downloads
    the requested sectors, stitches/normalizes, removes NaNs and outliers
    (sigma=5), flattens, runs astropy Box Least Squares, renders a 4-panel
    300 DPI PNG to ``reports/TIC_<id>_diagnostic.png``, logs the target to
    ``discoveries.csv`` UNCONDITIONALLY, and returns only the scalar dict
    ``{"TIC", "Period", "SDE", "Radius_Re"}``.
  * ``purge_corrupt_cache`` is MANUAL ONLY (terminal menu option 4). It is
    never called automatically by the pipeline — unlike the old
    Streamlit app (removed 2026-11-02), which purged on every run.
  * ``sweep_sky`` calls ``analyze_target`` per star (so sweep targets are
    also logged to discoveries.csv and get a full PNG each — a known issue
    in the original design, preserved deliberately; see STAGE1_REPORT.md).
  * ``run_qa`` benchmarks TOI-114 / Pi Mensae c / WASP-126 b at
    bls_points=10000 with 1–2 sectors; PASS if |recovered - expected| < 0.05 d.
  * No CLI arguments -> interactive ``terminal_menu()``.

Bridge additions (Pingu, Stage 1 — the ONLY additions on top of the
original; they do not change any of the behaviour above):
  (a) ``progress_callback``: optional parameter on the pipeline functions.
      Called with a single human-readable string per progress step.
      Default None -> progress is printed, exactly as the original did.
      A future FastAPI/WebSocket layer can pass its own callback instead.
  (b) ``detrend_window``: optional parameter on ``analyze_target``,
      defaulting to 101 — the value the original hardcoded in ``flatten``.
  (c) ``analyze_target_json(...)``: runs the same pipeline and returns a
      JSON-serializable dict (scalar metrics + downsampled arrays) for a
      future API/frontend layer. The CLI path / ``analyze_target`` return
      value is unchanged. The CLI also accepts one extra optional flag,
      ``--json-out PATH``, which writes that JSON dict to a file; without
      it, CLI output is identical to the original.

Stage 4 additions (Pingu — ports of Gemini's v1 app features; see
GEMINI_V1_ANALYSIS.md). They do not change any behaviour above:
  (d) ``is_already_known_online(tic_id)``: v1's Zooniverse (Planet
      Hunters TESS) already-discussed check. FAIL-OPEN: any error,
      timeout or unexpected response returns False (treat as unknown).
  (e) ``sweep_sky`` gains ``check_known=False``. When True, each
      screened star is checked with (d) BEFORE any download; known
      stars are skipped and counted via progress messages. Default
      False = original behaviour, unchanged.
  (f) ``odd_even_test(...)`` / ``odd_even_test_json(...)``: v1's QA
      Validation Lab odd/even eclipsing-binary check. Folds the light
      curve at 2x the candidate period and compares the depths of the
      two dips (equal depths -> planet-like; unequal -> likely an
      eclipsing binary at twice the period). Renders NO PNG and logs
      NOTHING to discoveries.csv — it is a check, not a discovery.

CLI (original flags):
    python hunter.py --tic 25155310 --radius 1.30 --sectors 2 --grid 8000
    python hunter.py --sweep --ra 83.82 --dec -5.39 --cone 0.15 --limit 50
    python hunter.py --qa
    python hunter.py            # interactive terminal menu
"""

import argparse
import csv
import gc
import json
import math
import os
import shutil
import sys
import time
from datetime import datetime

import astropy.units as u
import lightkurve as lk
import matplotlib
import requests

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd  # noqa: F401  (original import; kept for parity / ad-hoc use)
from astropy.coordinates import SkyCoord
from astropy.timeseries import BoxLeastSquares
from astroquery.mast import Catalogs

OUTPUT_DIR = "reports"
DISCOVERIES_CSV = "discoveries.csv"

os.makedirs(OUTPUT_DIR, exist_ok=True)

# Bridge addition (c): cap for each downsampled series in the JSON payload.
DEFAULT_MAX_POINTS = 4000


# ---------------------------------------------------------------------------
# Progress (bridge addition (a): optional callback, default = print)
# ---------------------------------------------------------------------------

def _emit(progress_callback, message):
    if progress_callback is None:
        print(message, flush=True)
    else:
        progress_callback(str(message))


# ---------------------------------------------------------------------------
# Cache (manual only — terminal menu option 4)
# ---------------------------------------------------------------------------

def purge_corrupt_cache():
    """Delete the lightkurve MAST download cache.

    MANUAL ONLY: called from the terminal menu (option 4), never
    automatically by analyze_target.
    """
    cache_dir = os.path.expanduser("~/.cache/lightkurve/mastDownload")
    if os.path.exists(cache_dir):
        shutil.rmtree(cache_dir, ignore_errors=True)
        print(f"Purged download cache: {cache_dir}")
    else:
        print("No download cache found — nothing to purge.")


# ---------------------------------------------------------------------------
# Discovery log
# ---------------------------------------------------------------------------

def log_candidate(tic_id, period, sde, depth, planet_re, sectors, star_rad):
    """Append one row to discoveries.csv (called for EVERY analyzed target)."""
    file_exists = os.path.exists(DISCOVERIES_CSV)
    with open(DISCOVERIES_CSV, "a", newline="") as fh:
        writer = csv.writer(fh)
        if not file_exists:
            writer.writerow([
                "Timestamp", "TIC_ID", "Period_Days", "SDE",
                "Transit_Depth_Pct", "Planet_Radius_Re",
                "Star_Radius_Rsun", "Sectors_Analyzed",
            ])
        writer.writerow([
            datetime.now().isoformat(timespec="seconds"),
            tic_id,
            f"{period:.5f}",
            f"{sde:.2f}",
            f"{depth * 100:.4f}",
            f"{planet_re:.2f}",
            f"{star_rad:.2f}",
            sectors,
        ])


# ---------------------------------------------------------------------------
# Core pipeline (internal: returns scalars + arrays)
# ---------------------------------------------------------------------------

def _run_pipeline(tic_id, star_radius=1.0, min_p=0.5, max_p=25.0,
                  bls_points=25000, max_sectors=None, progress_callback=None,
                  detrend_window=101):
    """Dev's analyze_target pipeline, returning scalars AND plot arrays.

    ``analyze_target`` (below) discards the arrays and returns only the
    original scalar dict; ``analyze_target_json`` serializes them.
    PNG rendering and discoveries.csv logging happen here, exactly once
    per call — i.e. for every analyzed target, as in the original.
    """
    tic_id = str(tic_id).strip()
    _emit(progress_callback, f"Querying MAST for TIC {tic_id}...")

    search = lk.search_lightcurve(f"TIC {tic_id}", author=["SPOC", "TESS-SPOC", "QLP"])
    if len(search) == 0:
        search = lk.search_lightcurve(f"TIC {tic_id}")
    if len(search) == 0:
        raise RuntimeError(f"No mission data found for TIC {tic_id}.")

    sectors_to_fetch = search if max_sectors is None else search[:max_sectors]
    _emit(progress_callback,
          f"Downloading {len(sectors_to_fetch)} of {len(search)} sector(s) for TIC {tic_id}...")

    lc_collection = sectors_to_fetch.download_all()
    if not lc_collection or len(lc_collection) == 0:
        raise RuntimeError(f"Failed to download light curve data products for TIC {tic_id}.")
    n_sectors = len(lc_collection)

    lc_raw = (lc_collection.stitch(corrector_func=lambda x: x.normalize())
              .remove_nans().remove_outliers(sigma=5.0))

    # detrend_window defaults to 101 — the value the original hardcoded here.
    lc_flat, trend = lc_raw.flatten(window_length=detrend_window, return_trend=True)
    t = lc_flat.time.value
    f = lc_flat.flux.value

    _emit(progress_callback, f"Running BLS ({bls_points:,} grid points) for TIC {tic_id}...")
    periods = np.linspace(min_p, max_p, bls_points) * u.day
    durations = np.linspace(0.03, 0.25, 14) * u.day
    bls = BoxLeastSquares(t * u.day, f)
    res = bls.power(periods, durations)

    best_idx = int(np.argmax(res.power))
    best_period = float(res.period[best_idx].value)
    best_depth = float(res.depth[best_idx])
    best_duration = float(res.duration[best_idx].value)
    t0 = float(res.transit_time[best_idx].value)
    sde = float((res.power[best_idx] - np.median(res.power)) / (np.std(res.power) + 1e-12))
    planet_radius_re = float(np.sqrt(max(0.0, best_depth)) * star_radius * 109.1)

    # Phase fold (bins=70, as in the original PNG rendering)
    phase = ((t - t0 + 0.5 * best_period) % best_period) - 0.5 * best_period
    phase_hours = phase * 24.0
    zoom_hr = max(6.0, (best_duration * 24.0) * 3.5)
    in_window = (phase_hours >= -zoom_hr) & (phase_hours <= zoom_hr)
    folded_hours = phase_hours[in_window]
    folded_flux = f[in_window]

    edges = np.linspace(-zoom_hr, zoom_hr, 70 + 1)
    bin_idx = np.clip(np.digitize(folded_hours, edges) - 1, 0, 69)
    binned_hours, binned_mean, binned_sem = [], [], []
    for b in range(70):
        mask = bin_idx == b
        vals = folded_flux[mask]
        if len(vals) == 0:
            continue
        binned_hours.append(float(np.mean(folded_hours[mask])))
        binned_mean.append(float(np.mean(vals)))
        binned_sem.append(
            float(np.std(vals, ddof=1) / math.sqrt(len(vals))) if len(vals) > 1 else 0.0
        )

    full = {
        "TIC": tic_id,
        "Period": best_period,
        "SDE": sde,
        "Radius_Re": planet_radius_re,
        # extra scalars (JSON layer / PNG titles)
        "Depth": best_depth,
        "Duration_Days": best_duration,
        "T0": t0,
        "Star_Radius_Rsun": float(star_radius),
        "Sectors_Analyzed": int(n_sectors),
        "Total_Points": int(len(lc_raw)),
        # arrays
        "raw_time": np.asarray(lc_raw.time.value, dtype=float),
        "raw_flux": np.asarray(lc_raw.flux.value, dtype=float),
        "trend_time": np.asarray(trend.time.value, dtype=float),
        "trend_flux": np.asarray(trend.flux.value, dtype=float),
        "flat_time": np.asarray(t, dtype=float),
        "flat_flux": np.asarray(f, dtype=float),
        "bls_periods": np.asarray(res.period.value, dtype=float),
        "bls_powers": np.asarray(res.power, dtype=float),
        "folded_phase_hours": np.asarray(folded_hours, dtype=float),
        "folded_flux": np.asarray(folded_flux, dtype=float),
        "binned_phase_hours": np.asarray(binned_hours, dtype=float),
        "binned_flux_mean": np.asarray(binned_mean, dtype=float),
        "binned_flux_sem": np.asarray(binned_sem, dtype=float),
        "zoom_hours": float(zoom_hr),
    }

    png_path = os.path.join(OUTPUT_DIR, f"TIC_{tic_id}_diagnostic.png")
    _render_diagnostic_png(full, png_path)
    _emit(progress_callback, f"Diagnostic PNG written to {png_path}")

    # Unconditional in the original — every analyzed target is logged,
    # candidate or noise floor alike.
    log_candidate(tic_id, best_period, sde, best_depth, planet_radius_re,
                  n_sectors, star_radius)

    del lc_collection, lc_raw, lc_flat, trend, bls, res
    gc.collect()
    return full


def _render_diagnostic_png(full, out_path):
    """4-panel, 300 DPI diagnostic plate (original rendering)."""
    fig, axes = plt.subplots(4, 1, figsize=(14, 15), constrained_layout=True)

    axes[0].scatter(full["raw_time"], full["raw_flux"], s=0.5, color="#6c757d", alpha=0.3)
    axes[0].plot(full["trend_time"], full["trend_flux"], color="#e63946", lw=1.2)
    axes[0].set_title(
        f"TIC {full['TIC']} — Raw Baseline ({full['Sectors_Analyzed']} Sectors)",
        fontweight="bold")
    axes[0].grid(alpha=0.2)

    axes[1].scatter(full["flat_time"], full["flat_flux"], s=0.5, color="#1d3557", alpha=0.35)
    axes[1].axhline(1.0, color="#e63946", linestyle="--", lw=0.9)
    axes[1].set_title("Flattened Residuals", fontweight="bold")
    axes[1].grid(alpha=0.2)

    axes[2].plot(full["bls_periods"], full["bls_powers"], color="#2a9d8f", lw=0.9)
    axes[2].axvline(full["Period"], color="#e63946", linestyle="--", lw=1.2)
    axes[2].set_title(
        f"BLS Power Spectrum (P: {full['Period']:.5f} d | SDE: {full['SDE']:.1f})",
        fontweight="bold")
    axes[2].grid(alpha=0.2)

    axes[3].scatter(full["folded_phase_hours"], full["folded_flux"],
                    s=2.0, color="#8d99ae", alpha=0.3)
    if len(full["binned_phase_hours"]):
        axes[3].errorbar(full["binned_phase_hours"], full["binned_flux_mean"],
                         yerr=full["binned_flux_sem"], fmt="o", color="#e63946",
                         markersize=4, capsize=2)
    axes[3].set_xlim(-full["zoom_hours"], full["zoom_hours"])
    axes[3].set_title(f"Transit Phase Fold (Rp: {full['Radius_Re']:.2f} R⊕)", fontweight="bold")
    axes[3].grid(alpha=0.2)

    fig.savefig(out_path, format="png", dpi=300)
    plt.close(fig)
    return out_path


# ---------------------------------------------------------------------------
# Public API — original signatures preserved
# ---------------------------------------------------------------------------

def analyze_target(tic_id, star_radius=1.0, min_p=0.5, max_p=25.0,
                   bls_points=25000, max_sectors=None, progress_callback=None,
                   detrend_window=101):
    """Analyze one TIC target. Returns ONLY the original scalar dict:
    {"TIC", "Period", "SDE", "Radius_Re"}.

    (progress_callback and detrend_window are bridge additions, appended
    after the original parameters; detrend_window defaults to the
    original's hardcoded 101.)
    """
    full = _run_pipeline(tic_id, star_radius=star_radius, min_p=min_p, max_p=max_p,
                         bls_points=bls_points, max_sectors=max_sectors,
                         progress_callback=progress_callback,
                         detrend_window=detrend_window)
    return {
        "TIC": full["TIC"],
        "Period": full["Period"],
        "SDE": full["SDE"],
        "Radius_Re": full["Radius_Re"],
    }


def _downsample_pair(x, y, max_points):
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    if len(x) > max_points:
        stride = int(math.ceil(len(x) / max_points))
        x, y = x[::stride], y[::stride]
    return [float(v) for v in x], [float(v) for v in y]


def full_result_to_json_dict(full, max_points=DEFAULT_MAX_POINTS):
    """Serialize a _run_pipeline result to a JSON-safe dict (downsampled)."""
    raw_t, raw_f = _downsample_pair(full["raw_time"], full["raw_flux"], max_points)
    trend_t, trend_f = _downsample_pair(full["trend_time"], full["trend_flux"], max_points)
    flat_t, flat_f = _downsample_pair(full["flat_time"], full["flat_flux"], max_points)
    bls_p, bls_pw = _downsample_pair(full["bls_periods"], full["bls_powers"], max_points)
    fold_h, fold_f = _downsample_pair(full["folded_phase_hours"], full["folded_flux"], max_points)
    return {
        "metrics": {
            "tic_id": full["TIC"],
            "best_period_days": full["Period"],
            "sde": full["SDE"],
            "classification": "Strong Transit" if full["SDE"] >= 8.5 else "Marginal / Noise",
            "depth": full["Depth"],
            "depth_percent": full["Depth"] * 100.0,
            "duration_days": full["Duration_Days"],
            "duration_hours": full["Duration_Days"] * 24.0,
            "t0_days": full["T0"],
            "planet_radius_earth": full["Radius_Re"],
            "host_radius_solar": full["Star_Radius_Rsun"],
            "sectors_analyzed": full["Sectors_Analyzed"],
            "total_points": full["Total_Points"],
        },
        "raw": {"time": raw_t, "flux": raw_f, "trend_time": trend_t, "trend_flux": trend_f},
        "flattened": {"time": flat_t, "flux": flat_f},
        "bls": {"periods": bls_p, "powers": bls_pw},
        "phase_folded": {
            "zoom_hours": full["zoom_hours"],
            "points": {"phase_hours": fold_h, "flux": fold_f},
            "binned": {
                "phase_hours": [float(v) for v in full["binned_phase_hours"]],
                "flux_mean": [float(v) for v in full["binned_flux_mean"]],
                "flux_sem": [float(v) for v in full["binned_flux_sem"]],
            },
        },
    }


def analyze_target_json(tic_id, star_radius=1.0, min_p=0.5, max_p=25.0,
                        bls_points=25000, max_sectors=None, progress_callback=None,
                        detrend_window=101, max_points=DEFAULT_MAX_POINTS):
    """Bridge addition (c): same pipeline as analyze_target, but returns a
    JSON-serializable dict (metrics + downsampled arrays) for a future
    FastAPI/frontend layer. Note: like analyze_target, this renders the
    PNG and logs the target to discoveries.csv.
    """
    full = _run_pipeline(tic_id, star_radius=star_radius, min_p=min_p, max_p=max_p,
                         bls_points=bls_points, max_sectors=max_sectors,
                         progress_callback=progress_callback,
                         detrend_window=detrend_window)
    return full_result_to_json_dict(full, max_points=max_points)


# ---------------------------------------------------------------------------
# Stage 4 (d): Zooniverse already-known check (ported from Gemini's v1 app)
# ---------------------------------------------------------------------------

ZOONIVERSE_SEARCH_URL = (
    "https://talk.zooniverse.org/searches"
    "?section=project-5733&query={tic}&types[]=comments&types[]=discussions"
)


def is_already_known_online(tic_id):
    """True if this TIC is already discussed on Planet Hunters TESS
    (Zooniverse Talk, project-5733) — v1's pre-download skip check.

    FAIL-OPEN by design: any network error, timeout, non-200 status or
    malformed response returns False (treat the star as not known), so a
    flaky connection can never silently shrink a sweep.
    """
    try:
        r = requests.get(
            ZOONIVERSE_SEARCH_URL.format(tic=str(tic_id).strip()),
            headers={"Accept": "application/vnd.api+json; version=1"},
            timeout=5,
        )
        if r.status_code == 200 and len(r.json().get("searches", [])) > 0:
            return True
    except Exception:
        pass
    return False


# ---------------------------------------------------------------------------
# Stage 4 (f): Odd/Even eclipsing-binary check (v1's QA Validation Lab)
# ---------------------------------------------------------------------------

def _fetch_flattened(tic_id, max_sectors=None, progress_callback=None,
                     detrend_window=101):
    """Front half of Dev's analyze pipeline (search -> download -> stitch
    -> flatten), shared by odd_even_test. Unlike _run_pipeline this
    renders NO PNG and logs NOTHING — the odd/even test is a check on an
    existing candidate, not a discovery run.
    Returns (t, f, n_sectors, total_points).
    """
    _emit(progress_callback, f"Querying MAST for TIC {tic_id}...")

    search = lk.search_lightcurve(f"TIC {tic_id}", author=["SPOC", "TESS-SPOC", "QLP"])
    if len(search) == 0:
        search = lk.search_lightcurve(f"TIC {tic_id}")
    if len(search) == 0:
        raise RuntimeError(f"No mission data found for TIC {tic_id}.")

    sectors_to_fetch = search if max_sectors is None else search[:max_sectors]
    _emit(progress_callback,
          f"Downloading {len(sectors_to_fetch)} of {len(search)} sector(s) for TIC {tic_id}...")

    lc_collection = sectors_to_fetch.download_all()
    if not lc_collection or len(lc_collection) == 0:
        raise RuntimeError(f"Failed to download light curve data products for TIC {tic_id}.")
    n_sectors = len(lc_collection)

    lc_raw = (lc_collection.stitch(corrector_func=lambda x: x.normalize())
              .remove_nans().remove_outliers(sigma=5.0))
    total_points = int(len(lc_raw))
    lc_flat = lc_raw.flatten(window_length=detrend_window)
    t = np.asarray(lc_flat.time.value, dtype=float)
    f = np.asarray(lc_flat.flux.value, dtype=float)

    del lc_collection, lc_raw, lc_flat
    gc.collect()
    return t, f, n_sectors, total_points


# Depths within this relative difference are judged "the same dip".
ODD_EVEN_MATCH_TOLERANCE = 0.25


def odd_even_test(tic_id, period_days, sector_cap=None, progress_callback=None,
                  detrend_window=101):
    """Odd/Even fake-check (v1's QA Validation Lab, rebuilt on our engine).

    If a "planet" signal is really an eclipsing binary, its true period
    is TWICE the candidate period, and alternate transits are the two
    different eclipses (primary/secondary) — usually with clearly
    different depths. Folding at 2x the period separates them: genuine
    planet transits land in BOTH dip positions with the SAME depth.

    Method:
      * Download/stitch/flatten exactly like analyze_target
        (detrend_window default 101).
      * The fold needs a true transit epoch. A catalog period can be
        ~0.25% off the best-fit period, which over a multi-year
        baseline smears the fold by a full period — so first refine
        period/epoch/duration with a small focused BLS scan (+/-2%
        around the supplied period, 401 grid points, the pipeline's
        standard duration set). The fold uses the refined period.
      * Folded coordinate s in [-P, +P): transit families land at
        s = -P/2 ("odd" dips) and s = +P/2 ("even" dips) — v1's plot
        geometry.
      * Each dip's depth = 1 - median(flux) within +/- half_window of
        its center, where half_window = 0.04 * P clipped to
        [0.02 d, 0.25 * P] — wide enough to average down noise, narrow
        enough not to swallow the other dip or mostly baseline.
      * Verdict: relative depth difference |odd - even| / max(odd, even)
        <= 0.25 -> "planet-like"; beyond -> "likely-eclipsing-binary";
        no positive dip measured at either position -> "inconclusive".

    Returns a dict of scalars + numpy arrays (see
    odd_even_test_json for the JSON-serializable mirror).
    """
    tic_id = str(tic_id).strip()
    period_days = float(period_days)
    if not math.isfinite(period_days) or period_days <= 0:
        raise ValueError(f"period_days must be a positive number, got {period_days!r}.")

    _emit(progress_callback,
          f"Odd/Even test: TIC {tic_id} at candidate period {period_days:.4f} d "
          f"(folds at {2.0 * period_days:.4f} d)...")
    t, f, n_sectors, total_points = _fetch_flattened(
        tic_id, max_sectors=sector_cap, progress_callback=progress_callback,
        detrend_window=detrend_window)

    _emit(progress_callback, "Refining period/epoch with a focused BLS scan...")
    grid = np.linspace(period_days * 0.98, period_days * 1.02, 401) * u.day
    durations = np.linspace(0.03, 0.25, 14) * u.day
    bls = BoxLeastSquares(t * u.day, f)
    res = bls.power(grid, durations)
    best_idx = int(np.argmax(res.power))
    fit_period = float(res.period[best_idx].value)
    t0 = float(res.transit_time[best_idx].value)
    duration = float(res.duration[best_idx].value)
    del bls, res
    _emit(progress_callback,
          f"Refined period {fit_period:.5f} d (supplied {period_days:.5f} d); "
          f"folding at {2.0 * fit_period:.5f} d...")

    # Fold at 2x the refined period; coordinate s in [-P, +P) with the
    # two transit families centered at -P/2 (odd) and +P/2 (even).
    s = ((t - t0 + 0.5 * fit_period) % (2.0 * fit_period)) - fit_period

    half_window = float(min(max(0.04 * fit_period, 0.02), 0.25 * fit_period))
    centers = {"odd": -0.5 * fit_period, "even": 0.5 * fit_period}
    depths = {}
    for name, center in centers.items():
        in_dip = np.abs(s - center) <= half_window
        depths[name] = float(1.0 - np.median(f[in_dip])) if in_dip.any() else 0.0

    depth_odd, depth_even = depths["odd"], depths["even"]
    depth_max = max(depth_odd, depth_even)
    if depth_max <= 0.0:
        depth_ratio, depth_rel_diff = 1.0, 0.0
        verdict = "inconclusive"
        verdict_text = (
            "No dip could be measured at either expected position, so this "
            "check can't judge the signal either way.")
    else:
        depth_ratio = float(min(depth_odd, depth_even) / depth_max)
        depth_rel_diff = float(abs(depth_odd - depth_even) / depth_max)
        if depth_rel_diff <= ODD_EVEN_MATCH_TOLERANCE:
            verdict = "planet-like"
            verdict_text = (
                f"The two dips match — odd transits dip {depth_odd * 100:.3f}% and "
                f"even transits dip {depth_even * 100:.3f}%, within "
                f"{depth_rel_diff * 100:.0f}% of each other. That is what a real "
                f"planet crossing the same star every {fit_period:.2f} days "
                f"should look like.")
        else:
            verdict = "likely-eclipsing-binary"
            verdict_text = (
                f"The two dips are different sizes — odd transits dip "
                f"{depth_odd * 100:.3f}% but even transits dip "
                f"{depth_even * 100:.3f}% ({depth_rel_diff * 100:.0f}% apart). "
                f"That is the classic sign of an eclipsing binary whose real "
                f"period is twice the candidate period.")

    _emit(progress_callback,
          f"Odd depth {depth_odd * 100:.4f}% · Even depth {depth_even * 100:.4f}% "
          f"→ verdict: {verdict}")

    # Binned medians over the folded axis (60 bins) — v1's clean overlay line.
    edges = np.linspace(-fit_period, fit_period, 60 + 1)
    bin_idx = np.clip(np.digitize(s, edges) - 1, 0, 59)
    binned_t, binned_f = [], []
    for b in range(60):
        mask = bin_idx == b
        if not mask.any():
            continue
        binned_t.append(float(np.mean(s[mask])))
        binned_f.append(float(np.median(f[mask])))

    order = np.argsort(s)
    return {
        "TIC": tic_id,
        "Period_Given_Days": period_days,
        "Period_Fit_Days": fit_period,
        "Fold_Period_Days": 2.0 * fit_period,
        "Duration_Days": duration,
        "T0": t0,
        "Sectors_Analyzed": int(n_sectors),
        "Total_Points": int(total_points),
        "Half_Window_Days": half_window,
        "Center_Odd_Days": centers["odd"],
        "Center_Even_Days": centers["even"],
        "Depth_Odd": depth_odd,
        "Depth_Even": depth_even,
        "Depth_Ratio": depth_ratio,
        "Depth_Rel_Diff": depth_rel_diff,
        "Verdict": verdict,
        "Verdict_Text": verdict_text,
        # arrays
        "folded_time_days": np.asarray(s[order], dtype=float),
        "folded_flux": np.asarray(f[order], dtype=float),
        "binned_time_days": np.asarray(binned_t, dtype=float),
        "binned_flux": np.asarray(binned_f, dtype=float),
    }


def odd_even_result_to_json_dict(full, max_points=DEFAULT_MAX_POINTS):
    """Serialize an odd_even_test result to a JSON-safe dict."""
    fold_t, fold_f = _downsample_pair(full["folded_time_days"], full["folded_flux"], max_points)
    return {
        "metrics": {
            "tic_id": full["TIC"],
            "period_given_days": full["Period_Given_Days"],
            "period_fit_days": full["Period_Fit_Days"],
            "fold_period_days": full["Fold_Period_Days"],
            "duration_days": full["Duration_Days"],
            "t0_days": full["T0"],
            "sectors_analyzed": full["Sectors_Analyzed"],
            "total_points": full["Total_Points"],
            "half_window_days": full["Half_Window_Days"],
            "depth_odd": full["Depth_Odd"],
            "depth_even": full["Depth_Even"],
            "depth_odd_percent": full["Depth_Odd"] * 100.0,
            "depth_even_percent": full["Depth_Even"] * 100.0,
            "depth_ratio": full["Depth_Ratio"],
            "depth_rel_diff": full["Depth_Rel_Diff"],
            "verdict": full["Verdict"],
            "verdict_text": full["Verdict_Text"],
        },
        "folded": {
            "range_days": full["Period_Fit_Days"],  # axis spans -P .. +P
            "center_odd_days": full["Center_Odd_Days"],
            "center_even_days": full["Center_Even_Days"],
            "points": {"time_days": fold_t, "flux": fold_f},
            "binned": {
                "time_days": [float(v) for v in full["binned_time_days"]],
                "flux": [float(v) for v in full["binned_flux"]],
            },
        },
    }


def odd_even_test_json(tic_id, period_days, sector_cap=None, progress_callback=None,
                       detrend_window=101, max_points=DEFAULT_MAX_POINTS):
    """JSON mirror of odd_even_test (same pattern as analyze_target_json):
    metrics + downsampled folded arrays for the API/frontend layer."""
    full = odd_even_test(tic_id, period_days, sector_cap=sector_cap,
                         progress_callback=progress_callback,
                         detrend_window=detrend_window)
    return odd_even_result_to_json_dict(full, max_points=max_points)


# ---------------------------------------------------------------------------
# Sky sweeper
# ---------------------------------------------------------------------------

def sweep_sky(ra, dec, radius=0.15, limit=50, min_mag=11.5, max_mag=15.0,
              min_r=0.5, max_r=1.8, bls_points=10000, sector_cap=2,
              progress_callback=None, check_known=False):
    """Cone-search the TIC catalog and analyze each screened star.

    Returns the list of hits with SDE >= 8.0. Per-target errors are
    printed (not silently swallowed) and the sweep continues.

    Stage 4: ``check_known=True`` runs v1's Zooniverse already-known
    check on each screened star BEFORE any download; known stars are
    skipped and counted in the progress stream (and in the closing
    summary line). Default False = original behaviour.
    """
    _emit(progress_callback, f"Querying TIC catalog around RA {ra}, Dec {dec} (radius {radius}°)...")
    coord = SkyCoord(ra=ra * u.deg, dec=dec * u.deg)
    tic_catalog = Catalogs.query_region(coord, radius=radius * u.deg, catalog="TIC")

    mask = (
        (tic_catalog["Tmag"] >= min_mag) & (tic_catalog["Tmag"] <= max_mag) &
        (tic_catalog["rad"] >= min_r) & (tic_catalog["rad"] <= max_r)
    )
    screened_targets = tic_catalog[mask][:limit]
    _emit(progress_callback, f"Screened {len(screened_targets)} target(s); starting sweep...")

    hits = []
    skipped_known = 0
    for row in screened_targets:
        tic_id = str(row["ID"])
        star_rad = float(row["rad"])
        if check_known and is_already_known_online(tic_id):
            skipped_known += 1
            _emit(progress_callback,
                  f"Skipping TIC {tic_id} — already known on Zooniverse "
                  f"(skipped {skipped_known} so far).")
            continue
        try:
            result = analyze_target(tic_id, star_radius=star_rad,
                                    bls_points=bls_points, max_sectors=sector_cap,
                                    progress_callback=progress_callback)
            entry = {
                "TIC_ID": tic_id,
                "Tmag": float(row["Tmag"]),
                "Star_Radius_Rsun": star_rad,
                "Period_Days": result["Period"],
                "SDE": result["SDE"],
                "Planet_Radius_Re": result["Radius_Re"],
            }
            if result["SDE"] >= 8.0:
                hits.append(entry)
                _emit(progress_callback,
                      f"HIT: TIC {tic_id} — P={result['Period']:.4f} d, SDE={result['SDE']:.1f}")
        except Exception as e:
            # Printed, not swallowed — the sweep continues with the next star.
            print(f"Error analyzing TIC {tic_id}: {e}", flush=True)

    summary_line = f"Sweep complete: {len(hits)} hit(s) with SDE >= 8.0."
    if check_known:
        summary_line += f" Skipped {skipped_known} already-known star(s)."
    _emit(progress_callback, summary_line)
    return hits


# ---------------------------------------------------------------------------
# QA benchmarks
# ---------------------------------------------------------------------------

QA_BENCHMARKS = [
    # (name, TIC ID, star radius, expected period days, sectors)
    ("TOI-114", "322307342", 1.20, 3.59, 1),
    ("Pi Mensae c", "261136679", 1.14, 6.27, 2),
    ("WASP-126 b", "25155310", 1.30, 3.28, 1),
]


def run_qa(progress_callback=None):
    """Run the benchmark targets. PASS if |recovered - expected| < 0.05 d."""
    results = []
    for name, tic_id, star_rad, expected, sectors in QA_BENCHMARKS:
        _emit(progress_callback, f"\nQA: {name} (TIC {tic_id}) — expected {expected} d")
        try:
            result = analyze_target(tic_id, star_radius=star_rad, bls_points=10000,
                                    max_sectors=sectors, progress_callback=progress_callback)
            diff = abs(result["Period"] - expected)
            passed = diff < 0.05
            _emit(progress_callback,
                  f"QA {name}: recovered {result['Period']:.5f} d "
                  f"(Δ {diff:.5f} d) — {'PASS' if passed else 'FAIL'}")
            results.append({"name": name, "tic_id": tic_id, "expected": expected,
                            "recovered": result["Period"], "diff": diff,
                            "pass": passed, "result": result})
        except Exception as e:
            print(f"QA {name} (TIC {tic_id}) error: {e}", flush=True)
            results.append({"name": name, "tic_id": tic_id, "expected": expected,
                            "recovered": None, "diff": None, "pass": False,
                            "error": str(e)})
    return results


# ---------------------------------------------------------------------------
# Interactive terminal menu
# ---------------------------------------------------------------------------

def terminal_menu():
    while True:
        print("\n=== Exoplanet Hunter ===")
        print("1. Single target")
        print("2. Sky sweep")
        print("3. QA benchmarks")
        print("4. Purge download cache")
        print("5. Exit")
        choice = input("Select an option (1-5): ").strip()

        if choice == "1":
            tic_id = input("TIC ID: ").strip()
            radius_in = input("Host star radius (R☉) [1.0]: ").strip()
            star_radius = float(radius_in) if radius_in else 1.0
            sectors_in = input("Sector cap (blank = all): ").strip()
            max_sectors = int(sectors_in) if sectors_in else None
            grid_in = input("BLS grid points [25000]: ").strip()
            bls_points = int(grid_in) if grid_in else 25000
            result = analyze_target(tic_id, star_radius=star_radius,
                                    bls_points=bls_points, max_sectors=max_sectors)
            print(result)
        elif choice == "2":
            ra = float(input("RA (deg) [83.82]: ").strip() or 83.82)
            dec = float(input("Dec (deg) [-5.39]: ").strip() or -5.39)
            cone = float(input("Cone radius (deg) [0.15]: ").strip() or 0.15)
            limit = int(input("Max stars [50]: ").strip() or 50)
            hits = sweep_sky(ra, dec, radius=cone, limit=limit)
            print(f"{len(hits)} hit(s):")
            for hit in hits:
                print(hit)
        elif choice == "3":
            run_qa()
        elif choice == "4":
            purge_corrupt_cache()
        elif choice == "5":
            print("Exiting.")
            break
        else:
            print("Invalid choice — enter 1-5.")


# ---------------------------------------------------------------------------
# CLI (original flags; --json-out is the only bridge addition)
# ---------------------------------------------------------------------------

def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Exoplanet Hunter — local TESS/BLS diagnostic engine.")
    parser.add_argument("--tic", default=None, help="Target TIC ID")
    parser.add_argument("--radius", type=float, default=1.0,
                        help="Host star radius in solar radii (default: 1.0)")
    parser.add_argument("--sectors", type=int, default=None,
                        help="Sector cap (default: None = all sectors)")
    parser.add_argument("--grid", type=int, default=25000,
                        help="BLS grid points (default: 25000)")
    parser.add_argument("--sweep", action="store_true", help="Run a sky sweep")
    parser.add_argument("--ra", type=float, default=83.82, help="Sweep RA (deg)")
    parser.add_argument("--dec", type=float, default=-5.39, help="Sweep Dec (deg)")
    parser.add_argument("--cone", type=float, default=0.15, help="Sweep cone radius (deg)")
    parser.add_argument("--limit", type=int, default=50, help="Max stars in a sweep")
    parser.add_argument("--qa", action="store_true", help="Run the QA benchmark suite")
    # Bridge addition: write the JSON results dict (analyze_target_json) here.
    parser.add_argument("--json-out", default=None,
                        help="Also write JSON results (metrics + arrays) to this path "
                             "(single-target mode only)")
    args = parser.parse_args(argv)

    if args.qa:
        run_qa()
    elif args.sweep:
        hits = sweep_sky(args.ra, args.dec, radius=args.cone, limit=args.limit)
        for hit in hits:
            print(hit)
    elif args.tic:
        if args.json_out:
            data = analyze_target_json(args.tic, star_radius=args.radius,
                                       bls_points=args.grid, max_sectors=args.sectors)
            out_dir = os.path.dirname(os.path.abspath(args.json_out))
            os.makedirs(out_dir, exist_ok=True)
            with open(args.json_out, "w") as fh:
                json.dump(data, fh)
            print(f"Wrote {args.json_out}")
            m = data["metrics"]
            print({"TIC": m["tic_id"], "Period": m["best_period_days"],
                   "SDE": m["sde"], "Radius_Re": m["planet_radius_earth"]})
        else:
            result = analyze_target(args.tic, star_radius=args.radius,
                                    bls_points=args.grid, max_sectors=args.sectors)
            print(result)
    else:
        terminal_menu()
    return 0


if __name__ == "__main__":
    sys.exit(main())
