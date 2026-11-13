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

Stage 5 additions (Pingu — self-healing downloads; see
SELFHEAL_REPORT.md). They change nothing on the happy path:
  (g) ``_with_download_self_heal`` wraps the network steps (MAST
      search in the analyze pipeline and the odd/even fetch, sweep
      TIC-catalog query): connection-class failures retry with backoff
      (5 s, 15 s; max 3 attempts for that class), and a corrupt cached
      .fits named by a LightkurveError is deleted and re-downloaded
      (Dev's cache rule: "keep hits, purge junk/corrupt"). Total
      attempts capped at 4; non-transient errors (e.g. "No mission
      data found") still fail immediately with the original error.
      Downloads themselves are PER-PRODUCT (``_download_products``):
      one bad product can no longer kill the rest — after its own
      purge + single re-download it is SKIPPED and the analysis
      proceeds on the remaining sectors. (Some products are broken at
      the source: TIC 308851365's sector-1 HLSP file re-downloads to
      the same truncated bytes on two machines, so skipping is the
      only cure.) The job fails only if ZERO products download.
  (h) ``double_period_test(...)`` / ``double_period_test_json(...)``:
      the ellipsoidal (twin-star) check that resolved TIC 308851365.
      Odd/even cannot separate a planet at P from equal twins at 2P;
      this test folds the RAW (unflattened) light curve at 2P and
      measures the out-of-eclipse light: twin stars brighten at both
      quadratures (tidal distortion), a planet leaves them flat.
      Renders NO PNG and logs NOTHING — a check, not a discovery.
  (i) ``odd_even_test`` results gain a ``raw_fold`` exhibit: the RAW
      (unflattened) light curve folded at 2x the refined period with
      the SAME refined epoch as the numeric test, display-cleaned
      (NaN removal, 5-sigma clip, median-normalized to brightness %)
      and stride-downsampled for the frontend. It imports the one
      advantage of Gemini's pilot Colab QA
      (gemini_pilot_qa_odd_even.py) — the raw-data view that exposes
      stormy light curves the flattened numeric test can iron flat
      (TIC 294665246) — while the numeric verdict stays the judge,
      byte-for-byte unchanged. A failed raw fetch degrades to
      raw_fold = None and never fails the check.

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
import re
import shutil
import socket
import sys
import time
import urllib.error
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

# Raw-fold exhibit (bridge addition (i)): the odd/even JSON payload also
# carries up to this many RAW folded points — enough for the eye to judge
# the storm, small enough to ship as JSON.
RAW_FOLD_MAX_POINTS = 15000


# ---------------------------------------------------------------------------
# Progress (bridge addition (a): optional callback, default = print)
# ---------------------------------------------------------------------------

def _emit(progress_callback, message):
    if progress_callback is None:
        print(message, flush=True)
    else:
        progress_callback(str(message))


# ---------------------------------------------------------------------------
# Self-healing downloads (Stage 5)
#
# Built from two real production failures on TIC 308851365 (2026-11-03):
#   1. requests ConnectionError ("Remote end closed connection without
#      response") mid-download killed the whole job.
#   2. The interrupted download left a truncated .fits in the lightkurve
#      cache; every later run then died with LightkurveError "... This
#      file may be corrupt due to an interrupted download. Please remove
#      it from your disk and try again." — permanently, until a human
#      deleted the file by hand.
# Per Dev's cache rule ("keep hits, purge junk/corrupt"), the wrapper
# below retries transient connection failures with backoff and deletes
# ONLY the corrupt file(s) an error names, then re-downloads them.
# ---------------------------------------------------------------------------

# Total attempts for one search+download step, corrupt purges included.
_DOWNLOAD_MAX_ATTEMPTS = 4
# Connection-class failures: at most 3 attempts (initial + 2 retries),
# waiting 5 s then 15 s between them.
_CONNECTION_MAX_ATTEMPTS = 3
_CONNECTION_BACKOFF_SECONDS = (5, 15)

# The sweep's TIC cone query gets a much deeper connection budget
# (Stage 5c): it is a single cheap catalog call, but it gates the whole
# sweep — a sustained MAST bad patch killed a sweep before a single
# star ran (2026-11-03 06:52 IST) once the shared 3-attempt budget was
# exhausted. 8 attempts, waiting 5/15/30/60/60/60/60 s between them
# (~5 min of persistence for one catalog call). Cone query ONLY —
# analyze/oddeven/doubleperiod fetches keep the shared budget above.
_SWEEP_CONNECTION_MAX_ATTEMPTS = 8
_SWEEP_CONNECTION_BACKOFF_SECONDS = (5, 15, 30, 60, 60, 60, 60)

# Class names (matched against every exception in the chain) that mark a
# transient connection failure — MAST or the network dropped us.
_CONNECTION_CLASS_NAMES = frozenset({
    "ConnectionError",        # requests + builtin
    "ConnectTimeout", "ReadTimeout", "Timeout",   # requests timeouts
    "RemoteDisconnected",     # http.client
    "URLError",               # urllib
    "NewConnectionError", "MaxRetryError", "ProtocolError",  # urllib3
    "IncompleteRead", "ChunkedEncodingError",
    "ConnectionResetError", "ConnectionAbortedError", "BrokenPipeError",
    "TimeoutError", "SocketTimeout", "SSLEOFError",
    "RemoteServiceError",     # astroquery/MAST transient service failure
                              # (run #16, 2026-11-09: an unretried
                              # RemoteServiceError from the TIC cone query
                              # killed the sweep in 3 minutes)
})

# Lowercase message fragments that mark a transient connection failure.
_CONNECTION_MESSAGE_MARKERS = (
    "remote end closed connection",
    "remote disconnected",
    "remotedisconnected",
    "connection aborted",
    "connection reset",
    "connection refused",
    "max retries exceeded",
    "eof occurred in violation of protocol",
    "timed out",
    "read timed out",
    "connect timeout",
    "broken pipe",
)

_FITS_PATH_RE = re.compile(r"[^\s'\"]+?\.fits\b")


def _exception_chain(exc):
    """Yield exc plus everything reachable via __cause__ / __context__
    and exception-valued args (requests/urllib3 nest the real failure
    several layers deep)."""
    seen = set()
    stack = [exc]
    while stack:
        item = stack.pop()
        if item is None or id(item) in seen:
            continue
        seen.add(id(item))
        yield item
        stack.append(getattr(item, "__cause__", None))
        stack.append(getattr(item, "__context__", None))
        for arg in getattr(item, "args", ()) or ():
            if isinstance(arg, BaseException):
                stack.append(arg)


def _is_connection_error(exc):
    """True if exc (or anything in its chain) is a transient
    connection-class failure worth retrying."""
    conn_types = (requests.exceptions.ConnectionError,
                  requests.exceptions.Timeout,
                  urllib.error.URLError,
                  ConnectionError, TimeoutError, socket.timeout)
    for item in _exception_chain(exc):
        if isinstance(item, conn_types):
            return True
        if type(item).__name__ in _CONNECTION_CLASS_NAMES:
            return True
        msg = str(item).lower()
        if any(marker in msg for marker in _CONNECTION_MESSAGE_MARKERS):
            return True
    return False


def _corrupt_cache_paths(exc):
    """If exc looks like a corrupt cached download, return the .fits
    path(s) it names; otherwise return an empty list.

    Matches the real failure shape (verified against live errors): a
    LightkurveError whose message says the file "may be corrupt" and
    names it, or any chain message mentioning corruption together with
    a .fits path.
    """
    paths = []
    corrupt = False
    for item in _exception_chain(exc):
        msg = str(item)
        found = _FITS_PATH_RE.findall(msg)
        for path in found:
            if path not in paths:
                paths.append(path)
        low = msg.lower()
        if "may be corrupt" in low:
            corrupt = True
        elif "corrupt" in low and found:
            corrupt = True
        elif type(item).__name__ == "LightkurveError" and found:
            corrupt = True
    return paths if corrupt else []


def _purge_corrupt_files(paths):
    """Delete the given cached files; return how many were removed."""
    removed = 0
    for path in paths:
        try:
            if os.path.isfile(path):
                os.remove(path)
                removed += 1
        except OSError:
            pass
    return removed


def _with_download_self_heal(step, progress_callback=None,
                             max_attempts=None, corrupt_max_retries=None,
                             connection_max_attempts=None,
                             connection_backoff_seconds=None):
    """Run ``step()`` (a network callable) with bounded retries.

    * Connection-class failure -> backoff (5 s, then 15 s) and retry;
      at most _CONNECTION_MAX_ATTEMPTS attempts for that class.
      ``connection_max_attempts`` / ``connection_backoff_seconds``
      override that budget for callers that need deeper persistence
      (the sweep's TIC cone query — see _SWEEP_CONNECTION_* above);
      the backoff sequence's last value repeats if failures outrun it.
    * Corrupt cached file -> the named .fits file(s) are deleted and
      the step retries so lightkurve re-downloads just those.
    * Total attempts are capped at _DOWNLOAD_MAX_ATTEMPTS unless
      ``max_attempts`` overrides it; a corrupt purge therefore cannot
      loop forever, and purges share the same overall budget.
      ``corrupt_max_retries`` optionally caps how many purge+retry
      cycles are allowed (the per-product downloader uses 1: purge and
      re-download ONCE, then give up on that product).
    * Anything else — e.g. RuntimeError("No mission data found ...") —
      propagates immediately, and after the final failed attempt the
      ORIGINAL error is re-raised unchanged.
    """
    if max_attempts is None:
        max_attempts = _DOWNLOAD_MAX_ATTEMPTS
    if connection_max_attempts is None:
        connection_max_attempts = _CONNECTION_MAX_ATTEMPTS
    if connection_backoff_seconds is None:
        connection_backoff_seconds = _CONNECTION_BACKOFF_SECONDS
    attempts = 0
    connection_failures = 0
    corrupt_retries = 0
    while True:
        attempts += 1
        try:
            return step()
        except Exception as e:
            corrupt_paths = _corrupt_cache_paths(e)
            if (corrupt_paths and attempts < max_attempts
                    and (corrupt_max_retries is None
                         or corrupt_retries < corrupt_max_retries)):
                if _purge_corrupt_files(corrupt_paths):
                    corrupt_retries += 1
                    _emit(progress_callback,
                          "Removed a corrupt downloaded file and re-downloading…")
                    continue
            if (_is_connection_error(e)
                    and connection_failures < connection_max_attempts - 1
                    and attempts < max_attempts):
                wait = connection_backoff_seconds[
                    min(connection_failures,
                        len(connection_backoff_seconds) - 1)]
                connection_failures += 1
                _emit(progress_callback,
                      f"Connection dropped — retrying "
                      f"(attempt {connection_failures + 1} of "
                      f"{connection_max_attempts})…")
                time.sleep(wait)
                continue
            raise


# ---------------------------------------------------------------------------
# Stitch hygiene (sweep-5 target-11 fix; SWEEP5_VETTING_REPORT.md App. A)
# ---------------------------------------------------------------------------

# The only columns the pipeline consumes downstream. Auxiliary columns
# are stripped before LightCurveCollection.stitch vstacks the curves:
# mixed-author HLSP sets (eleanor-lite + TASOC) carry a never-used
# flux_bkg column whose units are incommensurable across families
# (% vs electron/s), and vstack's unit unification dies on it.
_STITCH_COLUMNS = ("time", "flux", "flux_err", "quality")


def _stitch_corrector(lc):
    """Per-curve corrector used at BOTH stitch sites (_run_pipeline and
    _fetch_stitched): normalize, then keep only the columns the pipeline
    uses, so incompatible auxiliary columns never reach vstack.
    (Appendix A prescribed select_columns(); lightkurve 2.6 has no such
    method — keep_columns performs the same reduction.)"""
    lc = lc.normalize()
    lc.keep_columns([c for c in _STITCH_COLUMNS if c in lc.columns])
    return lc


def _is_zero_median_product(lc):
    """True if a product's flux is zero-centred — |median| within a tenth
    of its own robust scatter. TASOC-class HLSPs publish differential
    flux (ppm around zero); normalize() divides by the median, so such a
    product would enter the stitch as garbage, and it is excluded
    instead (Appendix A's follow-on hazard). Absolute-flux products
    (SPOC, QLP, TESS-SPOC, eleanor-lite) sit tens-to-hundreds of
    robust-sigmas from zero and are never flagged."""
    try:
        vals = np.asarray(lc.flux.value, dtype=float)
    except Exception:
        return False
    vals = vals[np.isfinite(vals)]
    if vals.size == 0:
        return False
    med = float(np.median(vals))
    robust_std = 1.4826 * float(np.median(np.abs(vals - med)))
    return abs(med) <= 0.1 * robust_std


def _download_products(sectors_to_fetch, tic_id, progress_callback=None):
    """Download search results ONE product at a time (Stage 5b).

    A single download_all() lets one bad product kill every sector —
    and some products are bad at the source: TIC 308851365's sector-1
    HLSP (t16) file re-downloads to the exact same truncated bytes on
    two different machines, so purge+re-download can never heal it.
    Here each product gets the self-heal treatment (connection retries;
    corrupt -> purge + ONE re-download); a product that still fails is
    SKIPPED with a progress line and the rest carry on. Raises the last
    error only if ZERO products could be downloaded.

    Zero-centred products (TASOC-class: differential flux, median ~ 0)
    are likewise excluded, with a progress line: normalize() divides by
    the median, so they cannot be stitched meaningfully. If EVERY
    downloaded product is zero-centred, that is raised as its own
    explicit error rather than masquerading as a download failure.
    """
    total = len(sectors_to_fetch)
    collected = []
    skipped = 0
    last_error = None
    for i in range(total):
        row = sectors_to_fetch[i]
        try:
            item = _with_download_self_heal(
                lambda row=row: row.download(), progress_callback,
                corrupt_max_retries=1)
        except Exception as e:
            last_error = e
            skipped += 1
            _emit(progress_callback,
                  "Sector/product file unreadable — skipping it and "
                  "continuing with the rest")
            continue
        if item is None:
            skipped += 1
            last_error = RuntimeError(
                f"Failed to download light curve data products for TIC {tic_id}.")
            _emit(progress_callback,
                  "Sector/product file unreadable — skipping it and "
                  "continuing with the rest")
            continue
        if isinstance(item, lk.LightCurveCollection):
            collected.extend(list(item))
        else:
            collected.append(item)
    usable = [lc for lc in collected if not _is_zero_median_product(lc)]
    n_zero_median = len(collected) - len(usable)
    if n_zero_median:
        _emit(progress_callback,
              f"Skipping {n_zero_median} zero-centred product(s) "
              f"(uncalibrated flux, median ~ 0 — cannot be normalized) "
              f"and continuing with the rest")
        collected = usable
    if not collected and n_zero_median:
        raise RuntimeError(
            f"All {n_zero_median} downloaded product(s) for TIC {tic_id} "
            f"are zero-centred (uncalibrated flux, median ~ 0) — no "
            f"usable light curve to analyze.")
    if not collected:
        if last_error is not None:
            raise last_error
        raise RuntimeError(
            f"Failed to download light curve data products for TIC {tic_id}.")
    if skipped:
        _emit(progress_callback,
              f"Continuing with {len(collected)} of {total} product(s) "
              f"— {skipped} skipped.")
    return lk.LightCurveCollection(collected)


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
# Product selection + systematic helpers (2026-11-08 upgrade)
# ---------------------------------------------------------------------------

_AUTHOR_PRIORITY = ("SPOC", "TESS-SPOC", "QLP")

# TESS orbital systematic family (days): the 13.7 d spacecraft orbit and
# its 6.85 / 27.4 d harmonics. Peaks here are artifacts until vetted, and
# the family is excluded when the periodogram's noise scale is measured,
# so the artifact forest stops taxing every real peak's SDE.
_SYSTEMATIC_PERIODS = (13.7, 6.85, 27.4)


def _near_systematic(period):
    """True if a period sits within 3% of the TESS systematic family."""
    return any(abs(period - s) <= 0.03 * s for s in _SYSTEMATIC_PERIODS)


def _search_author(tic_id, author):
    """One author's light-curve search for a TIC.

    Returns the SearchResult (possibly empty), or None if the query
    succeeded with a non-connection error treated as 'no usable
    result'. Raises requests.exceptions.ConnectionError if the query
    FAILED (after one internal retry): a failed query is not the same
    as an empty one, and the caller's self-heal wrapper must get the
    chance to retry the whole selection rather than the star being
    silently demoted to worse data (the 308851365 fallback incident
    during the 2026-11-08 upgrade tests)."""
    last_exc = None
    for _attempt in range(2):
        try:
            return lk.search_lightcurve(f"TIC {tic_id}", author=author)
        except Exception as e:
            if _is_connection_error(e):
                raise
            last_exc = e
            time.sleep(3)
    raise requests.exceptions.ConnectionError(
        f"Author query failed for TIC {tic_id} ({author}): {last_exc}")


def _select_products(tic_id, max_sectors, progress_callback=None):
    """Deterministic per-star product selection (2026-11-08).

    Why: the 2026-11-08 TOI-700 control post-mortem. The old path took
    the first ``max_sectors`` ROWS of one multi-author search (plus a
    silent unfiltered fallback), so which pipeline's data a star was
    analyzed on — SPOC 2-minute PDCSAP, TESS-SPOC FFI, QLP, or an HLSP
    mixture — depended on MAST's row order that day. Identical
    production code scores TOI-700 c at SDE 42.8 on SPOC products and
    SDE 7.5 (noise) on the set the Actions runner happened to draw.

    Selection is now explicit and homogeneous per star:

    * query SPOC, TESS-SPOC and QLP separately;
    * pick ONE author per star — most distinct sectors wins, author
      priority (SPOC > TESS-SPOC > QLP) breaks ties;
    * within the author, one product per sector, preferring the
      120 s cadence over 20 s when both exist;
    * keep the earliest ``max_sectors`` distinct sectors;
    * if no named author has products, fall back to an unfiltered
      search WITH a loud progress warning (never silently).

    Returns a lightkurve SearchResult (possibly a subset).
    """
    best = None  # (n_sectors, -priority, author, search, row_indices)
    for prio, author in enumerate(_AUTHOR_PRIORITY):
        search = _search_author(tic_id, author)
        if search is None or len(search) == 0:
            continue
        try:
            table = search.table
            by_sector = {}
            for idx in range(len(table)):
                sector = int(table["sequence_number"][idx])
                exptime = float(table["exptime"][idx])
                cur = by_sector.get(sector)
                if cur is None or (exptime == 120.0
                                   and float(table["exptime"][cur]) != 120.0):
                    by_sector[sector] = idx
            sectors = sorted(by_sector)
            cand = (len(sectors), -prio, author, search,
                    [by_sector[s] for s in sectors])
        except Exception:
            # Unexpected table shape: degrade to this author's raw rows
            # rather than failing the star.
            cand = (0, -prio, author, search, list(range(len(search))))
        if best is None or (cand[0], cand[1]) > (best[0], best[1]):
            best = cand
    if best is not None:
        _, _, author, search, row_idx = best
        if max_sectors is not None:
            row_idx = row_idx[:max_sectors]
        _emit(progress_callback,
              f"Products: {author} — {len(row_idx)} sector(s) selected "
              f"(deterministic selection).")
        try:
            return search[row_idx]
        except Exception:
            return search
    _emit(progress_callback,
          "WARNING: no SPOC/TESS-SPOC/QLP products found — falling back "
          "to an unfiltered search (mixed HLSP data, reduced reliability).")
    search = lk.search_lightcurve(f"TIC {tic_id}")
    if len(search) == 0:
        raise RuntimeError(f"No mission data found for TIC {tic_id}.")
    if max_sectors is not None:
        search = search[:max_sectors]
    return search


# --- Pass-2 raw-flux gate (2026-11-10) ------------------------------------
# TIC 294873918 post-mortem (candidates-vetting/294873918/VETTING_REPORT.md):
# the transit-masked re-flatten (pass 2) manufactured a BLS peak at
# P = 1.5452 d (SDE 53) out of a broad ~1.20 d variability wave — in RAW
# flux the adopted ephemeris has depth -0.0006%, i.e. no dip at all.
# Before a pass-2 result may replace pass 1, its ephemeris must show a
# genuine dip in the unflattened (outlier-cleaned only) stitched flux.
#
# The bar: depth > 0 AND significance >= _PASS2_GATE_MIN_SIGNIF, with the
# significance priced in red noise (out-of-transit flux chunked at the
# transit-duration timescale, persistence.py style). 3 sigma is the
# right height for a VETO (not a detector): the artefact measures ~0
# sigma, a real adopted signal measures far more (TOI-700 c ~15 sigma
# fixed-ephemeris raw), and a false veto costs nothing — pass 1's
# metrics simply stand, exactly as when the refinement itself fails.
_PASS2_GATE_MIN_SIGNIF = 3.0


def _raw_fold_depth(t, f, period, t0, duration):
    """Depth of a candidate ephemeris in UNFLATTENED flux.

    Returns (depth_pct, signif). In-transit = |phase| <= duration/2;
    baseline = |phase| > duration (a one-duration guard band keeps
    ingress/egress wings out of the baseline). Depth is the median
    difference, in percent (the stitched flux is ~1-normalised).
    Signif uses a chunked red-noise sigma: out-of-transit points are
    chunked at the transit-duration timescale and
    sigma = chunk_sigma * sqrt(1/n_events + 1/n_chunks).
    Unmeasurable configurations return (0.0, 0.0) — the gate then
    fails closed and pass 1 stands.
    """
    t = np.asarray(t, dtype=float)
    f = np.asarray(f, dtype=float)
    ok = np.isfinite(t) & np.isfinite(f)
    t, f = t[ok], f[ok]
    if len(t) < 200 or period <= 0 or duration <= 0:
        return 0.0, 0.0
    phase = ((t - t0 + 0.5 * period) % period) - 0.5 * period
    in_m = np.abs(phase) <= duration / 2.0
    out_m = np.abs(phase) > duration
    if in_m.sum() < 20 or out_m.sum() < 50:
        return 0.0, 0.0
    depth_pct = (float(np.median(f[out_m]))
                 - float(np.median(f[in_m]))) * 100.0
    t_out, f_out = t[out_m], f[out_m]
    cid = np.floor((t_out - t_out.min()) / duration).astype(np.int64)
    cnt = np.bincount(cid)
    sums = np.bincount(cid, weights=f_out)
    good = cnt >= 3
    if good.sum() < 2:
        return depth_pct, 0.0
    chunk_means = sums[good] / cnt[good]
    chunk_sigma_pct = float(np.std(chunk_means, ddof=1)) * 100.0
    n_events = max(1, len(np.unique(np.round((t[in_m] - t0) / period))))
    sigma_pct = chunk_sigma_pct * math.sqrt(1.0 / n_events
                                            + 1.0 / float(good.sum()))
    signif = depth_pct / sigma_pct if sigma_pct > 0 else 0.0
    return depth_pct, float(signif)


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
    sectors_to_fetch = _with_download_self_heal(
        lambda: _select_products(tic_id, max_sectors, progress_callback),
        progress_callback)
    _emit(progress_callback,
          f"Downloading {len(sectors_to_fetch)} sector product(s) for TIC {tic_id}...")
    lc_collection = _download_products(sectors_to_fetch, tic_id, progress_callback)
    n_sectors = len(lc_collection)

    lc_raw = (lc_collection.stitch(corrector_func=_stitch_corrector)
              .remove_nans().remove_outliers(sigma=5.0))

    # --- Detrend window in TIME units (2026-11-08 upgrade) -------------
    # detrend_window=101 was born on 30-minute data, where 101 points is
    # ~2.1 days. On SPOC 2-minute data the same 101 points span 3.4
    # HOURS, so the Savitzky-Golay trend absorbs whole transits
    # (measured on TOI-700 c: depth 0.095% at a 101-point window vs
    # 0.173% at a true 2-day window, same data). The window is now
    # derived from the stitched curve's median cadence, targeting
    # ~2.0 days at every cadence; the detrend_window argument remains
    # only as the fallback if the cadence cannot be measured.
    _times = np.asarray(lc_raw.time.value, dtype=float)
    _win = detrend_window
    if _times.size > 10:
        _dt = float(np.median(np.diff(_times)))
        if _dt > 0:
            _target = int(round(2.0 / _dt))
            _target += (_target % 2 == 0)
            _win = int(min(max(_target, 31), 4001))
            _max_odd = int(_times.size) // 2 * 2 - 1
            if _win > _max_odd:
                _win = max(31, _max_odd)
            _emit(progress_callback,
                  f"Detrend window: {_win} points "
                  f"(~{_win * _dt:.2f} d at {_dt * 1440.0:.0f}-min cadence).")
    lc_flat, trend = lc_raw.flatten(window_length=_win, return_trend=True)
    t = lc_flat.time.value
    f = lc_flat.flux.value

    # --- BLS v2 (2026-11-08 upgrade; multi-peak refinement 2026-11-13) --
    # * Frequency-uniform grid (3x the requested points, minimum 30k):
    #   the old linear-in-period grid under-samples long periods over a
    #   multi-year stitched baseline.
    # * Robust SDE: median/MAD of the periodogram EXCLUDING the TESS
    #   13.7 d systematic family, so the artifact forest no longer sets
    #   the noise scale every real peak is divided by.
    # * Top-15 distinct peaks are extracted (sub-harmonics masked) and
    #   EACH is refined on the fine grid — not just the headline. The
    #   coarse grid cannot stay coherent over a multi-year baseline at
    #   long periods (measured 7-18x too coarse at 10-16 d over 1007 d),
    #   so a true period can smear BELOW its own P/2 alias coarsely
    #   while refining far above it (TOI-700 c: coarse SDE 19.7 vs alias
    #   48.3; refined 258 vs 106). Refining only the headline locked in
    #   the alias and hid the second planet. Harmonic families are
    #   de-duplicated on the REFINED values; the headline is the best
    #   refined non-systematic peak when one clears SDE 6.5, else the
    #   best refined peak overall. The top-3 refined distinct signals
    #   ride along as refined_signals so second planets survive to the
    #   ledger.
    _n_grid = int(max(bls_points * 3, 30000))
    _emit(progress_callback, f"Running BLS ({_n_grid:,} grid points) for TIC {tic_id}...")
    periods = (1.0 / np.linspace(1.0 / max_p, 1.0 / min_p, _n_grid)) * u.day
    durations = np.linspace(0.03, 0.25, 14) * u.day

    def _sde_scale(powers, period_vals):
        keep = np.ones(len(powers), dtype=bool)
        for _s in _SYSTEMATIC_PERIODS:
            keep &= np.abs(period_vals - _s) > 0.03 * _s
        base = np.asarray(powers, dtype=float)[keep]
        med = float(np.median(base))
        mad = float(np.median(np.abs(base - med))) * 1.4826
        scale = mad if mad > 0 else float(np.std(base))
        return med, (scale if scale > 0 else 1e-12)

    def _bls_best(tt, ff):
        """BLS v2 -> (res, period, depth, duration, t0, sde, candidates,
        refined_signals). candidates and refined_signals are both the
        top-3 refined DISTINCT signals (same list at this stage; they
        diverge later only because TLS rescue prepends to candidates)."""
        _bls = BoxLeastSquares(tt * u.day, ff)
        _res = _bls.power(periods, durations)
        _pv = np.asarray(_res.period.value, dtype=float)
        _pw = np.asarray(_res.power, dtype=float)
        _med, _scale = _sde_scale(_pw, _pv)
        _work = (_pw - _med) / _scale

        def _refine_one(_cand):
            """Refine one candidate on the fine local grid (+/-1.5%,
            800 points) — the old headline-only refinement, factored
            out so every extracted peak gets the same treatment. Adopts
            the refined values only if the refined SDE is no more than
            1.0 below the coarse SDE; otherwise (or on any failure) the
            coarse values stand, exactly as before."""
            try:
                _fine = np.linspace(_cand["period"] * 0.985,
                                    _cand["period"] * 1.015, 800) * u.day
                _fres = _bls.power(_fine, durations)
                _fi = int(np.argmax(_fres.power))
                _fsde = float((_fres.power[_fi] - _med) / _scale)
                if _fsde >= _cand["sde"] - 1.0:
                    return {
                        "period": float(_fres.period[_fi].value),
                        "sde": _fsde,
                        "depth": float(_fres.depth[_fi]),
                        "duration": float(_fres.duration[_fi].value),
                        "t0": float(_fres.transit_time[_fi].value),
                        "near_systematic": bool(_near_systematic(
                            float(_fres.period[_fi].value))),
                        "detector": "BLS",
                    }
            except Exception:
                pass
            return _cand

        # Extract the top 15 peaks, masking each accepted peak's
        # SUB-harmonics (P/2, P/3, P/4) as well as the peak itself: a
        # signal at P also peaks at P/2, P/3... (every other/third
        # transit still folds), so those are the same signal, not new
        # ones. Multiples (2P, 3P) are deliberately NOT masked here:
        # when the coarse grid smears a true period below its own P/2
        # alias, the alias is accepted first and masking 2P would kill
        # the true period itself (TOI-700 c: alias 8.026 d accepted,
        # true 16.051 d = 2P). Multiples are de-duplicated AFTER
        # refinement instead, when the true fundamental is known.
        # N=15 is measured, not guessed: on TOI-700, planet b ranks
        # 15th (pass 1) / 12th (pass 2) at coarse SDE ~13, so N=10
        # would miss it on both passes.
        _cands = []
        for _k in range(15):
            _i = int(np.argmax(_work))
            if not np.isfinite(_work[_i]):
                break
            _cands.append({
                "period": float(_pv[_i]),
                "sde": float(_work[_i]),
                "depth": float(_res.depth[_i]),
                "duration": float(_res.duration[_i].value),
                "t0": float(_res.transit_time[_i].value),
                "near_systematic": bool(_near_systematic(float(_pv[_i]))),
                "detector": "BLS",
            })
            for _q in (1.0, 0.5, 1.0 / 3.0, 0.25):
                _hp = float(_pv[_i]) * _q
                _work[np.abs(_pv - _hp) <= 0.02 * _hp] = -np.inf
        if not _cands:
            _i = int(np.argmax(_pw))
            _cands = [{
                "period": float(_pv[_i]),
                "sde": float((_pw[_i] - _med) / _scale),
                "depth": float(_res.depth[_i]),
                "duration": float(_res.duration[_i].value),
                "t0": float(_res.transit_time[_i].value),
                "near_systematic": bool(_near_systematic(float(_pv[_i]))),
                "detector": "BLS",
            }]
        # Refine every extracted peak, then de-duplicate harmonic
        # families on the REFINED values: sort by refined SDE and
        # greedily accept, dropping any peak whose period is a small
        # rational multiple (m/n, m,n <= 8) of an accepted signal.
        # Doing this after refinement is what rescues smeared true
        # periods: the alias refines to 106 while the true period
        # refines to 258, so the true period is accepted first and the
        # alias drops as its P/2 harmonic. The wide ratio set matters:
        # a strong signal's 4:3, P/5 and P/7 aliases refine to SDE
        # 40-50 on TOI-700 and would otherwise crowd out the real
        # second planet. The window is TIGHT (+/-0.2%) because refined
        # periods are precise to ~0.01% — a wide window would kill real
        # near-resonant planets (TOI-700 b/c sit 0.54% from 8:5).
        # Known limitation: a genuine companion within 0.2% of a small
        # rational ratio (e.g. an exact-resonance chain) is deduped.
        _refined = [_refine_one(_c) for _c in _cands]
        _refined.sort(key=lambda _c: _c["sde"], reverse=True)
        _ratios = sorted({m / n for m in range(1, 9)
                          for n in range(1, 9)})
        _distinct = []
        for _c in _refined:
            _dup = False
            for _a in _distinct:
                _ratio = _c["period"] / _a["period"]
                for _r in _ratios:
                    if abs(_ratio - _r) <= 0.002 * _r:
                        _dup = True
                        break
                if _dup:
                    break
            if not _dup:
                _distinct.append(_c)
        _cands = _distinct[:3]
        _head_idx = 0
        for _k, _c in enumerate(_cands):
            if not _c["near_systematic"]:
                if _c["sde"] >= 6.5:
                    _head_idx = _k
                break
        _head = _cands[_head_idx]
        return (_res, _head["period"], _head["depth"], _head["duration"],
                _head["t0"], _head["sde"], _cands,
                [dict(_c) for _c in _cands])

    (res, best_period, best_depth, best_duration, t0, sde, candidates,
     refined_signals) = _bls_best(t, f)

    # --- Depth-recovery pass (2026-11-03 depth fix) -----------------------
    # Autopsy on WASP-126 b (DEPTH_FIX_REPORT.md): lightkurve's flatten
    # lets the trend absorb most of every transit — the removed trend sags
    # ~0.43% in-transit at EVERY window length (101/301/501/1001), so the
    # BLS depth read 0.217% where the raw data carries a 0.63% signal.
    # Fix: re-flatten with the pass-1 transits masked out of the trend fit
    # (lightkurve's mask= exists exactly for this: "data you want to
    # preserve, e.g. transits") and re-run the identical BLS. All reported
    # metrics come from this second pass. Skipped if the pass-1 "transit"
    # would mask more than 50% of the curve (pathological duty cycle —
    # too little unmasked curve left to anchor the trend). The 50% line
    # still admits high-duty-cycle signals like TIC 308851365's eclipses
    # (38% masked), whose depth was otherwise left unrecovered.
    # Pass bookkeeping (2026-11-10): every run records how pass 1 and
    # pass 2 compared, whether the raw-flux gate vetoed a pass-2
    # adoption, and whether pass 2's SDE jumped >= 2x over pass 1
    # (the manufacture signature from the TIC 294873918 autopsy).
    pass1_sde = float(sde)
    pass2_sde = None
    pass2_gate_failed = False
    sde_jump_flag = False
    _gate_raw_depth_pct = None
    _gate_raw_signif = None
    # Set only when the >50% mask guard blocks pass 2 outright, so the
    # null pass-2 fields in the harvested JSON explain themselves.
    pass2_skip_reason = None

    # The mask is built from the REFINED pass-1 headline (Fix 4,
    # 2026-11-13): since _bls_best now returns the refined multi-peak
    # headline, the mask anchors on the true period rather than a
    # coarse alias, so the real transits are masked out of the trend
    # fit even when the coarse grid smeared them.
    _phase1 = ((t - t0 + 0.5 * best_period) % best_period) - 0.5 * best_period
    _transit_mask = np.abs(_phase1) <= (best_duration / 2.0 + 0.02)
    if _transit_mask.mean() <= 0.50:
        _emit(progress_callback,
              "Refining depth: re-detrending with transits masked out of the trend fit...")
        try:
            _lc2, _trend2 = lc_raw.flatten(window_length=_win,
                                           return_trend=True,
                                           mask=_transit_mask)
            _t2 = _lc2.time.value
            _f2 = _lc2.flux.value
            (_res2, _per2, _dep2, _dur2, _t02, _sde2,
             _cand2, _ref2) = _bls_best(_t2, _f2)
            pass2_sde = float(_sde2)
            sde_jump_flag = bool(pass2_sde >= 2.0 * pass1_sde)
            # --- Raw-flux gate: the pass-2 ephemeris must show a real
            # dip in the UNFLATTENED flux before it may replace pass 1
            # (see _raw_fold_depth). A veto keeps pass 1's metrics and
            # flattened arrays, exactly as a failed refinement does.
            try:
                _gate_raw_depth_pct, _gate_raw_signif = _raw_fold_depth(
                    np.asarray(lc_raw.time.value, dtype=float),
                    np.asarray(lc_raw.flux.value, dtype=float),
                    _per2, _t02, _dur2)
            except Exception as _ge:
                _emit(progress_callback,
                      f"Pass-2 raw-flux gate could not run ({_ge}); "
                      "keeping pass-1 result.")
            if (_gate_raw_depth_pct is not None
                    and _gate_raw_depth_pct > 0.0
                    and (_gate_raw_signif or 0.0) >= _PASS2_GATE_MIN_SIGNIF):
                res, best_period, best_depth = _res2, _per2, _dep2
                best_duration, t0, sde = _dur2, _t02, _sde2
                candidates = _cand2
                refined_signals = _ref2
                lc_flat, trend, t, f = _lc2, _trend2, _t2, _f2
            else:
                pass2_gate_failed = True
                _emit(progress_callback,
                      "Pass-2 result REJECTED by the raw-flux gate "
                      f"(raw depth {_gate_raw_depth_pct}%, signif "
                      f"{_gate_raw_signif}); keeping pass-1 result.")
        except Exception as _e:
            # The masked re-flatten can reject the window when the
            # unmasked trend support is short (seen 2026-11-09 on
            # TIC 308851365 fallback data). Pass-1 metrics stand —
            # a failed refinement must never kill the target.
            _emit(progress_callback,
                  f"Depth refinement skipped ({_e}); keeping pass-1 result.")
    else:
        # The guard above blocks pass 2 entirely when the pass-1
        # "transit" would mask more than half the curve. Record WHY
        # (and say so in the progress log) — a silent skip left
        # TIC 375034833's null pass-2 fields unexplained in Batch 8.
        _mask_frac = float(_transit_mask.mean())
        pass2_skip_reason = f"mask_fraction_{_mask_frac:.2f}_gt_0.50"
        _emit(progress_callback,
              "Depth refinement skipped (pass-1 transit mask covers "
              f"{_mask_frac * 100.0:.0f}% of the curve, > 50%); "
              "keeping pass-1 result.")

    # --- TLS rescue (2026-11-08 upgrade) -------------------------------
    # Transit Least Squares fits true transit shapes where BLS fits
    # boxes (~10-20% more small-planet sensitivity in the literature).
    # Bounded: it runs ONLY when the BLS headline is sub-threshold but a
    # non-systematic BLS candidate reached SDE 5 (something may be
    # there), on a ~10-minute binned curve to bound the cost, and its
    # candidate is adopted only at SDE >= 10. Any TLS failure leaves
    # the BLS result untouched. Validated on TOI-700 c (binned SPOC
    # curve): TLS recovers P 16.053 d at SDE 11.1, depth 0.174%.
    if sde < 8.5 and any((not c["near_systematic"]) and c["sde"] >= 5.0
                         for c in candidates):
        try:
            from transitleastsquares import transitleastsquares as _tls
            _emit(progress_callback,
                  "TLS rescue: BLS headline sub-threshold — running "
                  "Transit Least Squares on a binned curve...")
            _w = 10.0 / 1440.0
            _idx = np.floor((t - t.min()) / _w).astype(int)
            _cnt = np.bincount(_idx)
            _tb = np.bincount(_idx, weights=t) / _cnt
            _fb = np.bincount(_idx, weights=f) / _cnt
            _ok = np.isfinite(_tb) & np.isfinite(_fb)
            _mstar = (float(star_radius) if star_radius <= 1.0
                      else float(star_radius ** 2.3))
            _model = _tls(_tb[_ok], _fb[_ok])
            _tres = _model.power(period_min=min_p, period_max=max_p,
                                 show_progress_bar=False,
                                 R_star=float(star_radius), M_star=_mstar)
            _tsde = float(_tres.SDE)
            _tdepth = float(np.atleast_1d(_tres.depth)[0])
            _emit(progress_callback,
                  f"TLS best: P={float(_tres.period):.4f} d, SDE={_tsde:.1f}")
            if _tsde >= 10.0 and 0.0 < _tdepth < 0.05:
                _tcand = {
                    "period": float(_tres.period),
                    "sde": _tsde,
                    "depth": _tdepth,
                    "duration": float(_tres.duration),
                    "t0": float(_tres.T0),
                    "near_systematic": bool(_near_systematic(
                        float(_tres.period))),
                    "detector": "TLS",
                }
                candidates = [_tcand] + candidates
                best_period = _tcand["period"]
                best_depth = _tcand["depth"]
                best_duration = _tcand["duration"]
                t0 = _tcand["t0"]
                sde = _tsde
                _emit(progress_callback,
                      f"TLS rescue ADOPTED: P={best_period:.4f} d at "
                      f"SDE {sde:.1f} replaces the BLS headline.")
        except Exception as _e:
            _emit(progress_callback, f"TLS rescue skipped ({_e}).")

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
        # 2026-11-08: top-3 BLS peaks (headline first is NOT guaranteed;
        # consumers should treat Period/SDE as the headline candidate and
        # this list as the full peak set for triage). Since 2026-11-13
        # these are the top-3 REFINED distinct signals (harmonic families
        # de-duplicated on refined values); TLS rescue may prepend a TLS
        # candidate, so this list is the triage list, not pure BLS.
        "Candidates": candidates,
        # 2026-11-13: top-3 refined distinct BLS signals (period, SDE,
        # depth, duration, t0) — the same list as Candidates at the BLS
        # stage, but never touched by TLS rescue, so it always records
        # the pure BLS multi-signal result (second planets survive here).
        "refined_signals": refined_signals,
        # 2026-11-10: pass-2 gate bookkeeping (see _raw_fold_depth).
        # pass2_sde is None when pass 2 never ran (mask > 50% or the
        # refinement raised); pass2_gate_failed marks a vetoed adoption.
        "pass1_sde": pass1_sde,
        "pass2_sde": pass2_sde,
        "pass2_gate_failed": bool(pass2_gate_failed),
        "sde_jump_flag": bool(sde_jump_flag),
        "pass2_raw_depth_pct": _gate_raw_depth_pct,
        "pass2_raw_signif": _gate_raw_signif,
        "pass2_skip_reason": pass2_skip_reason,
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

    del lc_collection, lc_raw, lc_flat, trend, res
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
            "candidates": full.get("Candidates", []),
            "refined_signals": full.get("refined_signals", []),
            "pass1_sde": full.get("pass1_sde"),
            "pass2_sde": full.get("pass2_sde"),
            "pass2_gate_failed": full.get("pass2_gate_failed", False),
            "sde_jump_flag": full.get("sde_jump_flag", False),
            "pass2_raw_depth_pct": full.get("pass2_raw_depth_pct"),
            "pass2_raw_signif": full.get("pass2_raw_signif"),
            "pass2_skip_reason": full.get("pass2_skip_reason"),
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
# Skip-known build (2026-11-09): VSX + TOI checks alongside Zooniverse.
# Batch 4's Zooniverse-only filter skipped 0 of 75 targets (runs
# #18-#20, skipped_known = 0 in all three) — these two catalogue
# sources are the added coverage Dev asked for ("filtering out known
# candidates from Zooniverse and other forums"). Same FAIL-OPEN
# contract as is_already_known_online: any error = not known.
# ---------------------------------------------------------------------------

VSX_QUERY_URL = (
    "https://vsx.aavso.org/index.php?view=query.votable"
    "&coords={ra}+{dec}&size=0.5&unit=2&order=9"
)
_VSX_TR_SPLIT_RE = re.compile(r"<TR\b", re.IGNORECASE)
_VSX_TD_RE = re.compile(r"<TD[^>]*>(.*?)</TD>", re.IGNORECASE | re.DOTALL)
_VSX_TAG_RE = re.compile(r"<[^>]+>")
_VSX_COORD_RE = re.compile(r"(-?\d+\.\d+)\s*,\s*(-?\d+\.\d+)")
VSX_KNOWN_RADIUS_ARCSEC = 30.0


def _sep_arcsec(ra1, dec1, ra2, dec2):
    """Great-circle separation in arcseconds (haversine; degrees in)."""
    p1, p2 = math.radians(dec1), math.radians(dec2)
    dp = p2 - p1
    dl = math.radians(ra2 - ra1)
    a = (math.sin(dp / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2)
    return math.degrees(2 * math.asin(min(1.0, math.sqrt(a)))) * 3600.0


def is_known_in_vsx(ra, dec):
    """True if VSX (AAVSO Variable Star Index) lists a variable star
    within ~30 arcsec of (ra, dec) — the target is already a known
    variable. The query.votable response is parsed as RAW XML TEXT:
    astropy's votable table parser crashes/mangles VSX string columns
    (proven 2026-11-09, Batch 4 triage). Each row's coordinate cell is
    found with a comma-anchored regex and separations are recomputed
    locally — the cone response is NOT distance-sorted. Route and
    layout validated 2026-11-09 on the TIC 308851365 control (its ROT
    entry recovered at 0.14 arcsec, P 0.75629).

    FAIL-OPEN: any network error, timeout or non-200 returns False.
    """
    try:
        r = requests.get(
            VSX_QUERY_URL.format(ra=float(ra), dec=float(dec)), timeout=20)
        if r.status_code != 200:
            return False
        for tr in _VSX_TR_SPLIT_RE.split(r.text)[1:]:
            cells = [_VSX_TAG_RE.sub("", c).strip()
                     for c in _VSX_TD_RE.findall(tr)]
            for cell in cells:
                m = _VSX_COORD_RE.search(cell)
                if m:
                    if _sep_arcsec(float(ra), float(dec),
                                   float(m.group(1)),
                                   float(m.group(2))) \
                            <= VSX_KNOWN_RADIUS_ARCSEC:
                        return True
                    break  # one coordinate cell per row
    except Exception:
        pass
    return False


TOI_TAP_URL = "https://exoplanetarchive.ipac.caltech.edu/TAP/sync"
_TOI_TIC_CACHE = None  # None = bulk pull not attempted yet this process


def _toi_tic_ids():
    """Bulk-pull the NASA Exoplanet Archive TOI table's TIC IDs ONCE
    per process and cache them as a set of strings (the TIC column is
    `tid`; ~7.8k unique IDs). Returns the set, or None when the pull
    fails — the TOI check is then off for this process (fail-open)
    instead of being retried per target."""
    global _TOI_TIC_CACHE
    if _TOI_TIC_CACHE is not None:
        return _TOI_TIC_CACHE
    ids = None
    try:
        r = requests.get(
            TOI_TAP_URL,
            params={"query": "SELECT tid FROM toi", "format": "csv"},
            timeout=90)
        if r.status_code == 200:
            got = set()
            for line in r.text.splitlines()[1:]:
                v = line.split(",")[0].strip().strip('"')
                if v.endswith(".0"):
                    v = v[:-2]
                if v:
                    got.add(v)
            if got:
                ids = got
    except Exception:
        ids = None
    _TOI_TIC_CACHE = ids if ids is not None else set()
    return ids


def is_known_in_toi(tic_id):
    """True if this TIC hosts a TESS Object of Interest (NASA
    Exoplanet Archive TOI table). FAIL-OPEN: a failed bulk pull
    disables the check and returns False."""
    ids = _toi_tic_ids()
    if not ids:
        return False
    return str(tic_id).strip() in ids


def known_skip_source(tic_id, ra=None, dec=None):
    """Which known source already has this star: "zooniverse", "vsx",
    "toi", or None — checked in that order (Dev's order, 2026-11-09).
    VSX needs the target's catalog coordinates; without them it is
    skipped. Every source is fail-open, so None also covers 'every
    check failed' — a sweep can never shrink silently on an error."""
    if is_already_known_online(tic_id):
        return "zooniverse"
    if ra is not None and dec is not None and is_known_in_vsx(ra, dec):
        return "vsx"
    if is_known_in_toi(tic_id):
        return "toi"
    return None


# ---------------------------------------------------------------------------
# Stage 4 (f): Odd/Even eclipsing-binary check (v1's QA Validation Lab)
# ---------------------------------------------------------------------------

def _fetch_stitched(tic_id, max_sectors=None, progress_callback=None):
    """Shared front half of the fetch path (search -> download -> stitch
    -> per-sector normalize -> NaN/outlier cleaning), used by both
    _fetch_flattened (odd/even check) and _fetch_raw (double-period
    test). Returns (lc_raw, n_sectors): the stitched LightCurve exactly
    as the pre-refactor _fetch_flattened built it, plus the sector
    count. Callers flatten it or extract its arrays as they need.
    """
    _emit(progress_callback, f"Querying MAST for TIC {tic_id}...")
    sectors_to_fetch = _with_download_self_heal(
        lambda: _select_products(tic_id, max_sectors, progress_callback),
        progress_callback)
    _emit(progress_callback,
          f"Downloading {len(sectors_to_fetch)} sector product(s) for TIC {tic_id}...")
    lc_collection = _download_products(sectors_to_fetch, tic_id, progress_callback)
    n_sectors = len(lc_collection)

    lc_raw = (lc_collection.stitch(corrector_func=_stitch_corrector)
              .remove_nans().remove_outliers(sigma=5.0))
    del lc_collection
    gc.collect()
    return lc_raw, n_sectors


def _fetch_flattened(tic_id, max_sectors=None, progress_callback=None,
                     detrend_window=101):
    """Front half of Dev's analyze pipeline (search -> download -> stitch
    -> flatten), shared by odd_even_test. Unlike _run_pipeline this
    renders NO PNG and logs NOTHING — the odd/even test is a check on an
    existing candidate, not a discovery run.
    Returns (t, f, n_sectors, total_points).
    """
    lc_raw, n_sectors = _fetch_stitched(
        tic_id, max_sectors=max_sectors, progress_callback=progress_callback)
    total_points = int(len(lc_raw))
    lc_flat = lc_raw.flatten(window_length=detrend_window)
    t = np.asarray(lc_flat.time.value, dtype=float)
    f = np.asarray(lc_flat.flux.value, dtype=float)

    del lc_raw, lc_flat
    gc.collect()
    return t, f, n_sectors, total_points


def _fetch_raw(tic_id, max_sectors=None, progress_callback=None):
    """Same fetch as _fetch_flattened but WITHOUT the flatten step.

    The double-period (ellipsoidal) test needs the raw normalized
    curve: flatten(window=101) is an hours-scale detrending filter that
    can erase the ~1.5-day ellipsoidal wave the test measures.
    Returns (t, f, n_sectors, total_points).
    """
    lc_raw, n_sectors = _fetch_stitched(
        tic_id, max_sectors=max_sectors, progress_callback=progress_callback)
    total_points = int(len(lc_raw))
    t = np.asarray(lc_raw.time.value, dtype=float)
    f = np.asarray(lc_raw.flux.value, dtype=float)

    del lc_raw
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
      * Exhibit (not a measurement): the result also carries the RAW
        unflattened curve folded with the same refined epoch,
        display-cleaned (NaN removal, 5-sigma clip) and normalized to
        brightness % — the view that exposes stormy data the flattened
        verdict can iron flat (bridge addition (i)).

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

    # Raw-fold exhibit (bridge addition (i)): the same sector set,
    # UNflattened, folded at 2x the refined period with the SAME refined
    # epoch as the numeric fold above — so the dip families land at the
    # same s = -P/2 / +P/2 and the frontend's markers stay honest (the
    # Colab cell this view is modelled on folds at a default epoch, so
    # its markers are only nominal). Display processing ONLY: NaN
    # removal, a 5-sigma clip (Gemini-style), median normalization to
    # brightness %. The numeric verdict above is untouched by this
    # block, and a failed raw fetch degrades to raw_fold = None in the
    # JSON — it never fails the check.
    raw_s = raw_pct = None
    raw_total = None
    _emit(progress_callback,
          "Building raw-fold exhibit from the unflattened light curve...")
    try:
        t_raw, f_raw, _, _ = _fetch_raw(
            tic_id, max_sectors=sector_cap,
            progress_callback=progress_callback)
        finite = np.isfinite(t_raw) & np.isfinite(f_raw)
        t_raw, f_raw = t_raw[finite], f_raw[finite]
        if t_raw.size == 0:
            raise RuntimeError("no finite raw points")
        med = float(np.median(f_raw))
        spread = float(np.std(f_raw))
        if spread > 0.0:
            keep = np.abs(f_raw - med) <= 5.0 * spread
            t_raw, f_raw = t_raw[keep], f_raw[keep]
        if t_raw.size == 0:
            raise RuntimeError("no raw points survive display cleaning")
        s_raw = ((t_raw - t0 + 0.5 * fit_period) % (2.0 * fit_period)) - fit_period
        order_raw = np.argsort(s_raw)
        raw_s = np.asarray(s_raw[order_raw], dtype=float)
        raw_pct = np.asarray(f_raw[order_raw] / med * 100.0, dtype=float)
        raw_total = int(raw_s.size)
        del t_raw, f_raw, s_raw
        gc.collect()
    except Exception as e:
        _emit(progress_callback,
              f"Raw-fold exhibit unavailable ({e}) — "
              f"numeric verdict unaffected.")
        raw_s = raw_pct = None
        raw_total = None

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
        # raw-fold exhibit (arrays, or None when the raw fetch failed)
        "raw_folded_time_days": raw_s,
        "raw_folded_brightness_pct": raw_pct,
        "raw_fold_total_points": raw_total,
    }


def odd_even_result_to_json_dict(full, max_points=DEFAULT_MAX_POINTS):
    """Serialize an odd_even_test result to a JSON-safe dict."""
    fold_t, fold_f = _downsample_pair(full["folded_time_days"], full["folded_flux"], max_points)
    # Raw-fold exhibit: stride-downsampled [s_days, brightness_pct]
    # pairs, or None when the raw fetch failed (exhibit absent, the
    # numeric result stands alone — the frontend renders nothing extra).
    raw_fold = None
    raw_t = full.get("raw_folded_time_days")
    raw_p = full.get("raw_folded_brightness_pct")
    if raw_t is not None and raw_p is not None and len(raw_t) > 0:
        xs, ys = _downsample_pair(raw_t, raw_p, RAW_FOLD_MAX_POINTS)
        raw_fold = {
            "fold_period_days": full["Fold_Period_Days"],
            "points": [[x, y] for x, y in zip(xs, ys)],
            "n_total": int(full.get("raw_fold_total_points") or len(raw_t)),
            "n_shown": len(xs),
        }
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
        "raw_fold": raw_fold,
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
# Double-period (ellipsoidal / twin-star) test — the check that resolved
# TIC 308851365 (planet-like by odd/even; +1.09% quadrature wave here)
# ---------------------------------------------------------------------------

# Phase windows over the 2P fold (fractions of the doubled period).
# Eclipse 1 sits at phase 0 (the BLS epoch), eclipse 2 half a cycle
# later; quadratures are the quarter-orbit points where tidally
# distorted stars present their wide sides and the system brightens.
# The shoulder windows hug the eclipses but stay clear of their wings.
DP_ECLIPSE1_WINDOWS = [(0.94, 1.0), (0.0, 0.06)]
DP_ECLIPSE2_WINDOWS = [(0.44, 0.56)]
DP_QUADRATURE_WINDOWS = [(0.19, 0.31), (0.69, 0.81)]
DP_SHOULDER_WINDOWS = [(0.08, 0.17), (0.58, 0.67), (0.83, 0.92), (0.33, 0.42)]

# A quadrature wave at least this big AND this significant is the
# twin-star signature. Thresholds fixed by the two reference cases:
# TIC 308851365 (delta +1.09% at 37 sigma -> binary) vs the WASP-126 b
# control (flat out-of-eclipse light -> no signal).
DP_DELTA_THRESHOLD_PERCENT = 0.2
DP_SIGMA_THRESHOLD = 5.0


def _phase_window_stats(phase, flux, windows):
    """Median flux + scatter/sqrt(N) standard error over the union of
    the given phase windows. Returns (median, se, n); median/se are
    None when the windows hold no points."""
    mask = np.zeros(phase.shape, dtype=bool)
    for lo, hi in windows:
        mask |= (phase >= lo) & (phase <= hi)
    vals = flux[mask]
    n = int(vals.size)
    if n == 0:
        return None, None, 0
    median = float(np.median(vals))
    se = float(np.std(vals) / math.sqrt(n)) if n > 1 else 0.0
    return median, se, n


def double_period_test(tic_id, period_days, sector_cap=None, progress_callback=None):
    """Double-period ellipsoidal (twin-star) test.

    The odd/even check has a blind spot: twin stars of similar size in
    a 2P orbit eclipse with EQUAL depths and pass as "planet-like".
    But close twins raise tides on each other — squeezed out of round,
    they show their wider sides at the quarter-orbit points
    (quadratures), so the light curve folded at 2P BRIGHTENS there,
    twice per orbit. A planet is far too light to bend its star, so it
    can never produce this wave. This is the test that unmasked
    TIC 308851365 (+1.09% at 37 sigma; reclassified EB in VSX).

    Method:
      * Fetch the RAW normalized light curve (_fetch_raw — NO
        flatten; the flatten filter can erase the wave).
      * Refine the fold period with a focused BLS scan around 2P
        (+/-3%, 3000 periods, durations 0.08/0.15/0.25 d); its
        transit_time is the fold epoch, so eclipse 1 sits at phase 0.
      * Median flux in the eclipse / quadrature / shoulder phase
        windows (module constants above); delta = median(Q) -
        median(S), standard error combined in quadrature from each
        window set's scatter/sqrt(N); sigma = delta / SE.
      * Verdicts: delta >= +0.2% at >= 5 sigma -> "likely-binary";
        delta <= -0.2% at >= 5 sigma -> "inconclusive" (a quadrature
        DIP is not the twin signature — spots/systematics can do it);
        anything else -> "no-ellipsoidal-signal".

    Returns a dict of scalars + the binned folded curve (see
    double_period_test_json for the JSON-serializable mirror).
    Renders NO PNG and logs NOTHING — a check, not a discovery.
    """
    tic_id = str(tic_id).strip()
    period_days = float(period_days)
    if not math.isfinite(period_days) or period_days <= 0:
        raise ValueError(f"period_days must be a positive number, got {period_days!r}.")

    _emit(progress_callback,
          f"Double-period test: TIC {tic_id} at candidate period {period_days:.4f} d "
          f"(folding the RAW light curve at {2.0 * period_days:.4f} d)...")
    t, f, n_sectors, total_points = _fetch_raw(
        tic_id, max_sectors=sector_cap, progress_callback=progress_callback)

    _emit(progress_callback, "Refining the double period with a focused BLS scan...")
    p2_guess = 2.0 * period_days
    grid = np.linspace(p2_guess * 0.97, p2_guess * 1.03, 3000) * u.day
    durations = np.array([0.08, 0.15, 0.25]) * u.day
    bls = BoxLeastSquares(t * u.day, f)
    res = bls.power(grid, durations)
    best_idx = int(np.argmax(res.power))
    p2 = float(res.period[best_idx].value)
    t0 = float(res.transit_time[best_idx].value)
    duration = float(res.duration[best_idx].value)
    del bls, res
    _emit(progress_callback,
          f"Refined double period {p2:.5f} d (supplied 2P = {p2_guess:.5f} d); "
          f"measuring the out-of-eclipse light...")

    phase = ((t - t0) % p2) / p2
    e1_med, _e1_se, _e1_n = _phase_window_stats(phase, f, DP_ECLIPSE1_WINDOWS)
    e2_med, _e2_se, _e2_n = _phase_window_stats(phase, f, DP_ECLIPSE2_WINDOWS)
    q_med, q_se, _q_n = _phase_window_stats(phase, f, DP_QUADRATURE_WINDOWS)
    s_med, s_se, _s_n = _phase_window_stats(phase, f, DP_SHOULDER_WINDOWS)

    if q_med is None or s_med is None or e1_med is None or e2_med is None:
        delta = delta_percent = delta_se = delta_sigma = None
        verdict = "inconclusive"
        verdict_text = (
            "Too few out-of-eclipse points landed in the measurement "
            "windows, so this check can't judge the signal either way.")
    else:
        delta = float(q_med - s_med)
        delta_percent = delta * 100.0
        delta_se = float(math.hypot(q_se or 0.0, s_se or 0.0))
        delta_sigma = float(delta / delta_se) if delta_se > 0 else 0.0
        if (delta_percent >= DP_DELTA_THRESHOLD_PERCENT
                and delta_sigma >= DP_SIGMA_THRESHOLD):
            verdict = "likely-binary"
            verdict_text = (
                f"The light between the eclipses is not flat — at the "
                f"quarter-orbit points the system brightens to {q_med:.4f} "
                f"while the shoulders beside the eclipses sit at {s_med:.4f}: "
                f"a {delta_percent:.2f}% wave at {abs(delta_sigma):.0f}σ. "
                f"That brightening is two stars squeezed out of round by "
                f"each other's gravity, showing us their wider sides twice "
                f"per orbit — a planet is far too light to bend its star "
                f"like this. These are twin stars orbiting every "
                f"{p2:.2f} days, not a planet.")
        elif (delta_percent <= -DP_DELTA_THRESHOLD_PERCENT
                and delta_sigma <= -DP_SIGMA_THRESHOLD):
            verdict = "inconclusive"
            verdict_text = (
                f"The light between the eclipses DIPS at the quarter-orbit "
                f"points instead of brightening ({delta_percent:.2f}% at "
                f"{abs(delta_sigma):.0f}σ) — that is not the twin-star "
                f"signature this test looks for. Starspots or leftover "
                f"instrument wiggles can bend the out-of-eclipse light "
                f"this way, so this check can't judge the signal.")
        else:
            verdict = "no-ellipsoidal-signal"
            verdict_text = (
                f"The light between the eclipses is flat — quadratures "
                f"sit at {q_med:.4f} and the shoulders at {s_med:.4f}, a "
                f"difference of {delta_percent:+.3f}% ± {delta_se * 100.0:.3f}%, "
                f"so there is no twin-star ellipsoidal wave. That is "
                f"consistent with a real planet — or with a binary whose "
                f"stars are too far apart to distort each other.")

    if delta_percent is not None:
        _emit(progress_callback,
              f"Quadratures {q_med:.5f} · Shoulders {s_med:.5f} · "
              f"wave {delta_percent:+.3f}% ({abs(delta_sigma):.1f}σ) "
              f"→ verdict: {verdict}")
    else:
        _emit(progress_callback,
              f"Not enough out-of-eclipse data → verdict: {verdict}")

    # Binned medians over the 2P phase fold (100 bins) for the chart.
    edges = np.linspace(0.0, 1.0, 100 + 1)
    bin_idx = np.clip(np.digitize(phase, edges) - 1, 0, 99)
    binned_phase, binned_flux = [], []
    for b in range(100):
        mask = bin_idx == b
        if not mask.any():
            continue
        binned_phase.append(float(0.5 * (edges[b] + edges[b + 1])))
        binned_flux.append(float(np.median(f[mask])))

    return {
        "TIC": tic_id,
        "Period_Given_Days": period_days,
        "Period_2P_Refined_Days": p2,
        "T0_2P": t0,
        "Duration_2P_Days": duration,
        "Sectors_Analyzed": int(n_sectors),
        "Total_Points": int(total_points),
        "Eclipse1_Median": e1_med,
        "Eclipse2_Median": e2_med,
        "Quadrature_Median": q_med,
        "Shoulder_Median": s_med,
        "Quadrature_SE": q_se,
        "Shoulder_SE": s_se,
        "Delta": delta,
        "Delta_Percent": delta_percent,
        "Delta_SE": delta_se,
        "Delta_Sigma": delta_sigma,
        "Verdict": verdict,
        "Verdict_Text": verdict_text,
        # arrays
        "binned_phase": np.asarray(binned_phase, dtype=float),
        "binned_median_flux": np.asarray(binned_flux, dtype=float),
    }


def double_period_result_to_json_dict(full):
    """Serialize a double_period_test result to a JSON-safe dict."""
    def _opt(v):
        return None if v is None else float(v)

    def _depth(median):
        return None if median is None else (1.0 - median) * 100.0

    return {
        "metrics": {
            "tic_id": full["TIC"],
            "period_given_days": full["Period_Given_Days"],
            "period_2p_refined_days": full["Period_2P_Refined_Days"],
            "t0_2p_days": full["T0_2P"],
            "duration_2p_days": full["Duration_2P_Days"],
            "sectors_used": full["Sectors_Analyzed"],
            "total_points": full["Total_Points"],
            "eclipse1_median": _opt(full["Eclipse1_Median"]),
            "eclipse2_median": _opt(full["Eclipse2_Median"]),
            "eclipse1_depth_percent": _depth(full["Eclipse1_Median"]),
            "eclipse2_depth_percent": _depth(full["Eclipse2_Median"]),
            "quadrature_median": _opt(full["Quadrature_Median"]),
            "shoulder_median": _opt(full["Shoulder_Median"]),
            "delta_percent": _opt(full["Delta_Percent"]),
            "delta_se_percent": (None if full["Delta_SE"] is None
                                 else full["Delta_SE"] * 100.0),
            "delta_sigma": _opt(full["Delta_Sigma"]),
            "verdict": full["Verdict"],
            "verdict_text": full["Verdict_Text"],
        },
        "folded": {
            "period_2p_days": full["Period_2P_Refined_Days"],
            "binned": {
                "phase": [float(v) for v in full["binned_phase"]],
                "median_flux": [float(v) for v in full["binned_median_flux"]],
            },
        },
    }


def double_period_test_json(tic_id, period_days, sector_cap=None,
                            progress_callback=None):
    """JSON mirror of double_period_test (same pattern as
    odd_even_test_json): metrics + binned folded curve for the
    API/frontend layer."""
    full = double_period_test(tic_id, period_days, sector_cap=sector_cap,
                              progress_callback=progress_callback)
    return double_period_result_to_json_dict(full)


# ---------------------------------------------------------------------------
# Sky sweeper
# ---------------------------------------------------------------------------

def _query_tic_cone_healed(coord, radius_deg, progress_callback=None):
    """TIC cone query with the sweep's deep connection budget (Stage 5c).

    Both sweep paths (hunter.sweep_sky and the API's sweep runner)
    start with this one cheap catalog call, and it gates everything:
    if it dies, zero stars are analyzed. It therefore retries
    connection-class failures up to _SWEEP_CONNECTION_MAX_ATTEMPTS
    times with a growing backoff instead of the shared download
    budget tuned for bulk light-curve fetches. Non-connection errors
    propagate immediately; if every attempt drops, a final progress
    line is emitted and the original error propagates unchanged.
    """
    try:
        return _with_download_self_heal(
            lambda: Catalogs.query_region(coord, radius=radius_deg * u.deg,
                                          catalog="TIC"),
            progress_callback,
            max_attempts=_SWEEP_CONNECTION_MAX_ATTEMPTS,
            connection_max_attempts=_SWEEP_CONNECTION_MAX_ATTEMPTS,
            connection_backoff_seconds=_SWEEP_CONNECTION_BACKOFF_SECONDS)
    except Exception as e:
        if _is_connection_error(e):
            _emit(progress_callback,
                  f"TIC catalog unreachable after "
                  f"{_SWEEP_CONNECTION_MAX_ATTEMPTS} attempts — "
                  f"sweep aborted.")
        raise


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
    tic_catalog = _query_tic_cone_healed(coord, radius, progress_callback)

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
            _emit(progress_callback,
                  f"TIC {tic_id} failed ({type(e).__name__}) — continuing "
                  f"with the next star.")

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
