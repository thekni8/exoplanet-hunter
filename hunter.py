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
    never called automatically by the pipeline — unlike app.py, which
    purged on every run.
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
# Sky sweeper
# ---------------------------------------------------------------------------

def sweep_sky(ra, dec, radius=0.15, limit=50, min_mag=11.5, max_mag=15.0,
              min_r=0.5, max_r=1.8, bls_points=10000, sector_cap=2,
              progress_callback=None):
    """Cone-search the TIC catalog and analyze each screened star.

    Returns the list of hits with SDE >= 8.0. Per-target errors are
    printed (not silently swallowed) and the sweep continues.
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
    for row in screened_targets:
        tic_id = str(row["ID"])
        star_rad = float(row["rad"])
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

    _emit(progress_callback, f"Sweep complete: {len(hits)} hit(s) with SDE >= 8.0.")
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
