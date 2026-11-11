#!/usr/bin/env python
"""BULK SCREEN — the Exoplanet Hunter's sister pipeline (v1, 2026-11-11).

WHY THIS EXISTS
---------------
The production pipeline (hunter.py) is a microscope: it downloads every
sector of every star and runs the full two-pass analysis before moving
on — minutes per star, ~20-40 stars per sweep. That depth was right for
the learning phase (every stage of the gauntlet exists because it killed
a real false positive), but the project's goal is FINDING A PLANET, and
planet yield is partly a coverage game. Pavel Rabtsevich screened
126,246 TESS stars cheaply and let ONE survivor earn the expensive
vetting (his TIC 4206066 is now TOI-7930; see bulk/TEARDOWN.md).

This sister pipeline inverts the cost structure:

    cheap screen for EVERYONE  ->  expensive gauntlet for SURVIVORS ONLY

It never touches hunter.py / sweep_runner.py / api.py. It imports
hunter read-only for exactly two things: the TOI bulk ID set and the
fail-open known-source helpers used to annotate survivors.

HOW IT STAYS CHEAP (the whole design in five rules)
---------------------------------------------------
1. PRE-EXTRACTED LIGHT CURVES ONLY. QLP FFI HLSP files are ~80 KB per
   star per sector and live at a DETERMINISTIC MAST URL built from the
   TIC id — no per-star catalogue search, no lightkurve round-trip.
   One sector per star at screen time. No exceptions.
2. FILTER BEFORE COMPUTE. Known objects cost zero BLS:
   * TOI  — hunter._toi_tic_ids(): ONE bulk TAP pull for the whole run.
   * VSX  — the production per-star cone query (hunter.VSX_QUERY_URL,
     same raw-text parsing, same 30 arcsec match radius via
     hunter._sep_arcsec) issued ONCE PER TILE over the sample footprint
     instead of once per star, then matched locally.
   * Zooniverse — per-star Talk search has no bulk form (5 s HTTP per
     star); it is applied to SURVIVORS ONLY, before output, and matches
     are moved out of the survivor list. Documented deviation from the
     deep pipeline, where all three run pre-download; the screen pays
     the Zooniverse cost only for the handful of stars that earned it.
   Every source is FAIL-OPEN exactly as in production: an unreachable
   catalogue disables that check for the run and is logged, so a flaky
   network can never silently shrink the screen.
3. ONE FAST BLS, production-flavoured. Frequency-uniform period grid
   and the SAME robust SDE as hunter.py's BLS v2 (median/MAD of the
   periodogram excluding the 13.7 d systematic family), so a screen SDE
   and a pipeline SDE are the same currency — the screen is just poorer
   (one sector, fewer transits), which is why its bar is lower.
4. ONLY FREE VETOES. Odd/even depth comparison, a phase-0.5 secondary
   look, a duration sanity cap, and the SUB-FLOOR HARMONIC CHECK (the
   2026-11-10 TIC 29780280 lesson: a 0.207 d rotation fundamental sits
   BELOW the 0.5 d search floor, so BLS happily reports its 0.62 d
   harmonic as a "transit"; for any hit whose P/2 or P/3 falls below
   the floor, fold there and compare depths). Anything that costs real
   compute — persistence, raw-flux gates, holdout, imaging — belongs
   to the gauntlet, not the screen.
5. SURVIVORS LEAVE IN GAUNTLET SHAPE. One JSON object per line:
   {tic, period_days, t0_btjd, duration_hours, depth_percent, sde,
    sector, product, ...} — exactly what a desk check consumes.

THRESHOLDS (set in advance, 2026-11-11 — do not tune per run)
--------------------------------------------------------------
  RECORD_FLOOR_SDE = 6.0   hits below this are not even recorded
  SURVIVOR_SDE     = 7.0   screen bar (deep-pipeline discovery bar is
                           8.5 on multi-sector data; single-sector SDE
                           is suppressed by ~sqrt(N_transits), and the
                           gauntlet re-derives every survivor anyway —
                           the screen optimises RECALL, the gauntlet
                           owns PRECISION)
  DEPTH_MIN_PCT    = 0.02  below this, FFI single-sector dips at these
                           magnitudes are noise, not planets
  DEPTH_EB_PCT     = 3.0   deeper than this around a <=0.8 Rsun dwarf
                           is EB country; flagged and demoted
  Odd/even demote: both halves >= 3 sigma deep and depth ratio < 0.5
  Secondary demote: phase-0.5 dip >= 80% of primary depth at >= 3 sigma
  Harmonic demote: sub-floor fold depth >= 80% of primary depth
  Duration demote: duration > 0.35 x period (eclipse, not transit)

  v1.1 CALIBRATION (2026-11-11 — bulk/CALIBRATION_V1_1.md): v1's flat
  SDE>=7 rule passed 31.6% of the proof run (451/1,429) — ~40k
  survivors at 126k scale, which no gauntlet can eat. Survivorship now
  ALSO requires a pink-noise MES rescore (CDPP at the transit
  duration, LEO-Vetter style) in one of two tiers: A (periodic:
  >= 3 events, MES >= 9, >= 2 events individually >= 3 sigma) or
  B (few-transit: 1-2 events, best event >= 8 sigma, depth <= 1%).
  On the proof run this yields 23 survivors = 1.61% of searched, and
  the TOI-700 control survives in Tier B (MES 8.44, single event —
  sector 1 holds exactly one c transit, so it can never be Tier A
  in-sector; its periodicity test is the gauntlet's persistence run).
  Raising SDE alone was measured and rejected: SDE >= 20 still
  passes 4.3% AND kills the control (SDE 10.26).

DEFAULT STAR WINDOW (and why)
-----------------------------
  Tmag 10.0-13.5 — the QLP FFI product itself is the ceiling: QLP
    extracts light curves for stars brighter than ~13.5; fainter stars
    simply 404 (counted as no_product). Bright floor avoids saturation.
  Radius 0.2-0.8 Rsun — aligned with the deep pipeline's live TRIAL
    recipe (widened 2026-11-11 from 0.2-0.5): the screen feeds the same
    hunting ground the trial is testing, and Rabtsevich's own find was
    a late-K dwarf (~0.7 Rsun) that the old 0.2-0.5 window would have
    excluded outright.
  Sector: ONE, chosen per run (--sector). Proof run: sector 1, cone
    around TIC 150428135 (TOI-700) — see POSITIVE CONTROL below.

POSITIVE CONTROL
----------------
--control-tic whitelists ONE known-signal star past the known filter
(it would otherwise be skipped as a TOI — correctly!). The control is
screened like everyone else, flagged "control": true, excluded from
novel-survivor claims, and its SDE + rank are reported in the summary.
If the screen cannot see a known real signal, the screen is broken and
the run says so.

USAGE
-----
  python bulk_screen.py --sector 1 --ra 97.0969 --dec -65.5793 \
      --cone 6 --control-tic 150428135 --out-dir bulk/run_s0001
  python bulk_screen.py --stars-file sample.csv --sector 1 ...

Outputs in --out-dir: survivors.jsonl, screen_hits.jsonl (all recorded
hits incl. demoted), summary.json, run.log.
"""

import argparse
import csv
import json
import math
import os
import sys
import time
import warnings
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from pathlib import Path

import numpy as np

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

# ---------------------------------------------------------------------------
# Thresholds — set in advance (see module docstring). Do not tune per run.
# ---------------------------------------------------------------------------
RECORD_FLOOR_SDE = 6.0
SURVIVOR_SDE = 7.0
DEPTH_MIN_PCT = 0.02
DEPTH_EB_PCT = 3.0
# v1.1 calibration (2026-11-11, tuned ONLY on the sector-1 proof run;
# see bulk/CALIBRATION_V1_1.md). v1's flat SDE>=7 survivor rule passed
# 31.6% of searched stars — unusable at 126k scale. Survivors must now
# ALSO pass a pink-noise MES rescore (LEO-Vetter style, as in
# Rabtsevich's screen) in one of two tiers:
TIER_A_MES = 9.0            # periodic tier: MES_pink >= 9 (his floor)
TIER_A_MIN_EVENTS = 3       # ... with >= 3 observed transit events
TIER_A_MIN_STRONG = 2       # ... and >= 2 events individually >= 3 sigma
STRONG_EVENT_SNR = 3.0
TIER_B_EVENT_SNR = 8.0      # few-transit tier (1-2 events): the best
                            # single event must stand at >= 8 sigma pink
TIER_B_MAX_DEPTH_PCT = 1.0  # ... and depth <= 1% (deeper lone dips are
                            # EB/artifact country; they stay recorded)
MIN_PERIOD_D = 0.5
MAX_PERIOD_D = 20.0
BLS_GRID_POINTS = 12000
BLS_DURATIONS_D = (0.04, 0.06, 0.09, 0.13, 0.18, 0.25)
SYSTEMATIC_PERIODS = (13.7, 6.85, 27.4)  # mirrors hunter._SYSTEMATIC_PERIODS
PRODUCT = "QLP"
QLP_URL = ("https://mast.stsci.edu/api/v0.1/Download/file?uri="
           "mast:HLSP/qlp/s{sec:04d}/{a}/{b}/{c}/{d}/"
           "hlsp_qlp_tess_ffi_s{sec:04d}-{padded}_tess_v01_llc.fits")


def log(msg, logf=None):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    if logf is not None:
        logf.write(line + "\n")
        logf.flush()


# ---------------------------------------------------------------------------
# Star list
# ---------------------------------------------------------------------------

def cone_star_list(ra, dec, cone_deg, min_mag, max_mag, min_rad, max_rad,
                   logf=None, tile_deg=2.0):
    """TIC star list for a cone, window cuts applied SERVER-SIDE.

    Uses astroquery's Catalogs.query_criteria (the Filtered.Tic
    service) in overlapping tiles instead of the deep sweep's
    query_region call, for two measured reasons (2026-11-11):
    (1) query_region returns EVERY TIC column for every star in the
        cone — a 4 deg cone request died in the egress proxy after
        ~4.5 min without returning; the filtered service answers the
        same question in ~20 s because the cuts happen at MAST.
    (2) A single large filtered query appears to truncate silently
        near ~10^3 rows (a 4 deg query returned 966 window rows and
        dropped the cone-centre star, TIC 150428135, whose Tmag/rad are
        in-window). Tiles of tile_deg keep every response far below
        that; results are deduped by TIC and the window + exact cone
        are re-checked locally, so tiling can only cost duplicates,
        never stars.
    Returns list of dicts {tic, ra, dec, tmag, radius}."""
    from astroquery.mast import Catalogs
    from astropy.coordinates import SkyCoord
    import astropy.units as u
    centre = SkyCoord(ra=ra * u.deg, dec=dec * u.deg)
    seen = {}
    cosd = max(math.cos(math.radians(dec)), 0.2)
    n_steps = max(1, int(math.ceil(cone_deg / tile_deg)))
    centres = []
    for i in range(-n_steps, n_steps + 1):
        for j in range(-n_steps, n_steps + 1):
            t_ra = ra + i * tile_deg / cosd
            t_dec = dec + j * tile_deg
            if centre.separation(SkyCoord(ra=t_ra * u.deg,
                                          dec=t_dec * u.deg)).deg \
                    > cone_deg + tile_deg:
                continue
            centres.append((t_ra, t_dec))

    def _tile(tc):
        tab = Catalogs.query_criteria(
            catalog="Tic",
            coordinates=SkyCoord(ra=tc[0] * u.deg, dec=tc[1] * u.deg),
            radius=tile_deg * u.deg,
            Tmag=[min_mag, max_mag], rad=[min_rad, max_rad])
        return [{"tic": str(row["ID"]), "ra": float(row["ra"]),
                 "dec": float(row["dec"]), "tmag": float(row["Tmag"]),
                 "radius": float(row["rad"])} for row in tab]

    with ThreadPoolExecutor(max_workers=4) as ex:
        for rows in ex.map(_tile, centres):
            for s in rows:
                seen.setdefault(s["tic"], s)
    stars = [s for s in seen.values()
             if centre.separation(SkyCoord(ra=s["ra"] * u.deg,
                                           dec=s["dec"] * u.deg)).deg
             <= cone_deg]
    log(f"TIC cone r={cone_deg}deg (tiled criteria): {len(stars)} stars "
        f"in window (Tmag {min_mag}-{max_mag}, R {min_rad}-{max_rad})",
        logf)
    return stars


def file_star_list(path):
    """CSV with header tic,ra,dec,tmag,radius (radius/tmag optional)."""
    stars = []
    with open(path) as fh:
        for row in csv.DictReader(fh):
            stars.append({
                "tic": str(row["tic"]).strip(),
                "ra": float(row["ra"]), "dec": float(row["dec"]),
                "tmag": float(row["tmag"]) if row.get("tmag") else None,
                "radius": float(row["radius"]) if row.get("radius") else None,
            })
    return stars


# ---------------------------------------------------------------------------
# Known filter — filter before compute, counts kept separate per source
# ---------------------------------------------------------------------------

def vsx_batched_coords(stars, logf=None, tile_deg=3.0, center=None,
                       cone_deg=None):
    """VSX known-variable positions over the sample footprint.

    Production (hunter.is_known_in_vsx) fires one cone query per star
    and re-checks separations locally at 30 arcsec because the response
    is not distance-sorted. Here the SAME endpoint, SAME raw-text row
    parsing and the SAME local separation check are kept, but queries
    are issued per TILE and every returned coordinate is pooled.

    VSX 'size' semantics, measured 2026-11-11 against the production
    control position (TIC 308851365): unit=2 is ARCMINUTES (production's
    size=0.5&unit=2 is a 30 arcsec cone; size=120&unit=2 returned rows
    out to exactly 2.00 deg). A tile is therefore size=tile_deg*60,
    unit=2. Tiles sit on a grid spaced tile_deg apart (RA spacing
    corrected by cos(dec)) with radius tile_deg, restricted to centres
    within cone_deg+tile_deg of the sample centre when known.
    Returns a list of (ra, dec); [] on total failure (fail-open).
    """
    import requests
    import hunter  # read-only: regexes + _sep_arcsec

    if not stars:
        return []
    if center is None:
        ras = [s["ra"] for s in stars if s.get("ra") is not None]
        decs = [s["dec"] for s in stars if s.get("dec") is not None]
        center = ((min(ras) + max(ras)) / 2.0, (min(decs) + max(decs)) / 2.0)
        cone_deg = max(
            hunter._sep_arcsec(center[0], center[1], s["ra"], s["dec"])
            for s in stars if s.get("ra") is not None) / 3600.0
    cra, cdec = center
    cosd = max(math.cos(math.radians(cdec)), 0.2)
    size_arcmin = int(round(tile_deg * 60))
    coords = []
    n_tiles = 0
    n_rows = 0
    n_steps = int(math.ceil((cone_deg + tile_deg) / tile_deg))
    for i in range(-n_steps, n_steps + 1):
        for j in range(-n_steps, n_steps + 1):
            t_ra = cra + i * tile_deg / cosd
            t_dec = cdec + j * tile_deg
            if hunter._sep_arcsec(cra, cdec, t_ra, t_dec) \
                    > (cone_deg + tile_deg) * 3600.0:
                continue
            n_tiles += 1
            rows_here = 0
            for attempt in (1, 2):
                try:
                    url = ("https://vsx.aavso.org/index.php?"
                           "view=query.votable"
                           f"&coords={t_ra}+{t_dec}&size={size_arcmin}"
                           "&unit=2&order=9")
                    r = requests.get(url, timeout=120)
                    if r.status_code != 200:
                        raise RuntimeError(f"http {r.status_code}")
                    for tr in hunter._VSX_TR_SPLIT_RE.split(r.text)[1:]:
                        cells = [hunter._VSX_TAG_RE.sub("", c).strip()
                                 for c in hunter._VSX_TD_RE.findall(tr)]
                        for cell in cells:
                            m = hunter._VSX_COORD_RE.search(cell)
                            if m:
                                coords.append((float(m.group(1)),
                                               float(m.group(2))))
                                rows_here += 1
                                break  # one coordinate cell per row
                    break
                except Exception as e:
                    if attempt == 2:
                        log(f"VSX tile ({t_ra:.2f},{t_dec:.2f}) failed: "
                            f"{e} (fail-open)", logf)
            n_rows += rows_here
            if rows_here >= 20000:
                log(f"VSX tile ({t_ra:.2f},{t_dec:.2f}) returned "
                    f"{rows_here} rows — possible truncation; treat VSX "
                    f"coverage there as suspect", logf)
    log(f"VSX batched: {n_tiles} tiles, {n_rows} variable-star rows "
        f"pooled", logf)
    return coords


def _toi_ids_with_retry(logf=None, attempts=3):
    """hunter._toi_tic_ids() with retries around it. The production
    helper caches a FAILED pull as an empty set for the whole process,
    so a transient outage (e.g. the Exoplanet Archive's 2026-11-11
    maintenance 503s, observed live during the proof run) would
    disable the TOI check for an entire multi-hour screen. Here the
    identical TAP query (same URL, same parsing as hunter's) is
    retried with backoff; hunter's own result is used whenever it
    succeeds. Returns a set of TIC id strings, or an empty set when
    every attempt failed (fail-open, logged)."""
    import hunter
    ids = hunter._toi_tic_ids()
    if ids:
        return ids
    import requests
    for k in range(2, attempts + 1):
        time.sleep(20)
        try:
            r = requests.get(
                hunter.TOI_TAP_URL,
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
                    log(f"TOI pull recovered on attempt {k}: "
                        f"{len(got)} ids", logf)
                    return got
            log(f"TOI pull attempt {k}: http {r.status_code}", logf)
        except Exception as e:
            log(f"TOI pull attempt {k} failed: {e}", logf)
    return set()


def apply_known_filter(stars, control_tic=None, logf=None, center=None,
                       cone_deg=None):
    """Returns (kept, skipped) where skipped maps source -> [tic,...].
    Sources: 'toi' (bulk set), 'vsx' (batched cones, 30 arcsec).
    Zooniverse is deliberately NOT here — see module docstring; it is
    applied to survivors in annotate_survivors_zooniverse()."""
    import hunter  # read-only reuse
    skipped = {"toi": [], "vsx": []}
    kept = []

    toi_ids = _toi_ids_with_retry(logf)
    if toi_ids:
        log(f"TOI bulk pull: {len(toi_ids)} TIC ids", logf)
    else:
        log("TOI bulk pull FAILED — TOI check off for this run "
            "(fail-open)", logf)

    vsx_coords = vsx_batched_coords(stars, logf, center=center,
                                    cone_deg=cone_deg)

    for s in stars:
        tic = s["tic"]
        if control_tic and tic == str(control_tic):
            kept.append(s)
            continue
        if toi_ids and tic in toi_ids:
            skipped["toi"].append(tic)
            continue
        if vsx_coords and s.get("ra") is not None \
                and s.get("dec") is not None:
            hit = False
            for (vra, vdec) in vsx_coords:
                if abs(vdec - s["dec"]) > 0.02:
                    continue
                if hunter._sep_arcsec(s["ra"], s["dec"], vra, vdec) \
                        <= hunter.VSX_KNOWN_RADIUS_ARCSEC:
                    hit = True
                    break
            if hit:
                skipped["vsx"].append(tic)
                continue
        kept.append(s)
    log(f"known filter: kept {len(kept)}, skipped TOI "
        f"{len(skipped['toi'])}, VSX {len(skipped['vsx'])}", logf)
    return kept, skipped


def annotate_survivors_zooniverse(records, logf=None):
    """Zooniverse Talk check on survivors only (per-star HTTP, fail-open
    via hunter.is_already_known_online). Returns (novel, known) — known
    records leave the survivor list; they are discoveries of the
    catalogues, not of this screen."""
    import hunter
    novel, known = [], []
    for rec in records:
        if rec.get("control"):
            novel.append(rec)
            continue
        try:
            if hunter.is_already_known_online(rec["tic"]):
                rec = dict(rec)
                rec["known_source"] = "zooniverse"
                known.append(rec)
                continue
        except Exception:
            pass
        novel.append(rec)
    if known:
        log(f"zooniverse survivor check: {len(known)} survivor(s) "
            f"already discussed — moved out of the novel list", logf)
    return novel, known


# ---------------------------------------------------------------------------
# Download — deterministic QLP URLs, no per-star catalogue search
# ---------------------------------------------------------------------------

def qlp_url(tic, sector):
    padded = str(tic).strip().zfill(16)
    return QLP_URL.format(sec=int(sector), a=padded[0:4], b=padded[4:8],
                          c=padded[8:12], d=padded[12:16],
                          padded=padded)


def _download_one(args):
    tic, sector, cache_dir = args
    dest = Path(cache_dir) / f"s{int(sector):04d}" / f"{tic}.fits"
    if dest.exists() and dest.stat().st_size > 1000:
        return tic, "cached", dest.stat().st_size
    import requests
    try:
        r = requests.get(qlp_url(tic, sector), timeout=60)
        if r.status_code == 404:
            return tic, "no_product", 0
        if r.status_code != 200 or len(r.content) < 1000:
            return tic, f"http_{r.status_code}", 0
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(".part")
        tmp.write_bytes(r.content)
        tmp.rename(dest)
        return tic, "downloaded", len(r.content)
    except Exception as e:
        return tic, f"error:{type(e).__name__}", 0


def download_all(stars, sector, cache_dir, workers=8, logf=None):
    """Thread-pooled bulk fetch. Returns {tic: path} for stars with a
    local file, plus a stats dict. This stage — not BLS — is the real
    bottleneck of any bulk screen, so it is timed separately."""
    t0 = time.time()
    jobs = [(s["tic"], sector, cache_dir) for s in stars]
    paths, stats = {}, {"downloaded": 0, "cached": 0, "no_product": 0,
                        "errors": 0, "bytes": 0}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for tic, status, nbytes in ex.map(_download_one, jobs):
            stats["bytes"] += nbytes
            if status in ("downloaded", "cached"):
                stats[status] += 1
                paths[tic] = str(Path(cache_dir) / f"s{int(sector):04d}"
                                 / f"{tic}.fits")
            elif status == "no_product":
                stats["no_product"] += 1
            else:
                stats["errors"] += 1
    stats["seconds"] = time.time() - t0
    log(f"download: {stats['downloaded']} new + {stats['cached']} cached, "
        f"{stats['no_product']} no-product, {stats['errors']} errors, "
        f"{stats['bytes']/1e6:.1f} MB in {stats['seconds']:.0f}s", logf)
    return paths, stats


# ---------------------------------------------------------------------------
# Per-star screen — one fast BLS + free vetoes (process worker)
# ---------------------------------------------------------------------------

def _robust_sde(powers, period_vals):
    """hunter.py BLS-v2 SDE: (peak - median) / MAD-sigma of the
    periodogram, excluding the 13.7 d systematic family."""
    keep = np.ones(len(powers), dtype=bool)
    for s in SYSTEMATIC_PERIODS:
        keep &= np.abs(period_vals - s) > 0.03 * s
    base = np.asarray(powers, dtype=float)[keep]
    med = float(np.median(base))
    mad = float(np.median(np.abs(base - med))) * 1.4826
    scale = mad if mad > 0 else float(np.std(base))
    return med, (scale if scale > 0 else 1e-12)


def _fold_depth(t, f, period, t0, duration, phase_center=0.0):
    """Mean depth (fraction, positive = dip) of points whose phase is
    within +-duration/2 of phase_center, vs the out-of-window median.
    Returns (depth, n_in, noise_sigma_of_depth)."""
    phase = ((t - t0) / period + 0.5) % 1.0 - 0.5  # in [-0.5, 0.5)
    half = 0.5 * duration / period
    pc = phase_center
    dist = np.abs(((phase - pc + 0.5) % 1.0) - 0.5)
    inwin = dist <= half
    outwin = (dist > 2 * half) & (dist < 0.45)
    if inwin.sum() < 3 or outwin.sum() < 20:
        return 0.0, int(inwin.sum()), np.inf
    base = np.median(f[outwin])
    depth = float(base - np.mean(f[inwin]))
    # red-noise-aware-ish error: chunk out-of-window at duration scale
    noise = float(np.std(f[outwin]) / math.sqrt(max(inwin.sum(), 1)))
    return depth, int(inwin.sum()), noise


def _odd_even(t, f, period, t0, duration):
    """Alternate-transit depths. Returns (depth_odd, depth_even, ratio)
    with ratio = min/max in [0,1]; 1.0 = identical."""
    events = np.floor((t - t0) / period + 0.5)
    half = 0.5 * duration
    phase_t = t - (t0 + events * period)
    inwin = np.abs(phase_t) <= half
    outwin = (np.abs(phase_t) > 2 * duration)
    if inwin.sum() < 4 or outwin.sum() < 20:
        return 0.0, 0.0, 1.0
    base = np.median(f[outwin])
    res = []
    for parity in (0, 1):
        m = inwin & (np.abs(events % 2 - parity) < 0.5)
        res.append(float(base - np.mean(f[m])) if m.sum() >= 2 else 0.0)
    d_odd, d_even = res[1], res[0]
    hi = max(d_odd, d_even)
    ratio = (min(d_odd, d_even) / hi) if hi > 0 else 1.0
    return d_odd, d_even, float(ratio)


def _rescore(t, f, period, t0, duration):
    """Pink-noise MES rescore of a recorded hit (v1.1 calibration).

    Refolds the (already flattened) light curve at the BLS ephemeris and
    measures the noise the way LEO-Vetter does: CDPP at the transit
    duration — the std of means of out-of-transit chunks one duration
    long — so red noise on the transit timescale is priced in, unlike
    the white-noise fold error. MES = depth / CDPP * sqrt(N_events).
    Also returns per-event SNRs (an event = >= 1 in-window cadence;
    QLP FFI is 30-min, so a 1-2 h transit is only 2-4 points) and the
    folded profile's edge/centre depth ratio (box ~1, V-shape << 1).
    Returns None when the noise cannot be measured (< 5 chunks)."""
    phase_t = t - t0
    events = np.round(phase_t / period)
    centres = t0 + events * period
    inwin = np.abs(t - centres) <= 0.5 * duration
    if inwin.sum() < 3:
        return None
    ev_list = [e for e in np.unique(events[inwin])
               if (inwin & (events == e)).sum() >= 1]
    if not ev_list:
        return None
    phase = ((phase_t / period + 0.5) % 1.0) - 0.5
    outwin = (~inwin) & (np.abs(phase) < 0.45)
    if outwin.sum() < 20:
        return None
    base = np.median(f[outwin])
    depth = float(base - np.mean(f[inwin]))
    dt = float(np.median(np.diff(t)))
    chunk = max(int(round(duration / dt)), 1)
    out_idx = np.where(outwin)[0]
    means = []
    for seg in np.split(out_idx, np.where(np.diff(out_idx) > chunk)[0] + 1):
        for i in range(0, len(seg) - chunk + 1, chunk):
            means.append(np.mean(f[seg[i:i + chunk]]))
    if len(means) < 5:
        return None
    cdpp = float(np.std(means))
    if cdpp <= 0:
        return None
    ev_snr = [float(base - np.mean(f[inwin & (events == e)])) / cdpp
              for e in ev_list]
    off = t - centres
    c_m = inwin & (np.abs(off) <= duration / 6)
    e_m = inwin & (np.abs(off) > duration / 6)
    d_c = float(base - np.mean(f[c_m])) if c_m.sum() >= 1 else 0.0
    d_e = float(base - np.mean(f[e_m])) if e_m.sum() >= 1 else 0.0
    return {"mes_pink": depth / cdpp * math.sqrt(len(ev_list)),
            "cdpp_pct": cdpp * 100.0, "n_events": len(ev_list),
            "n_strong_events": int(sum(1 for s in ev_snr
                                       if s >= STRONG_EVENT_SNR)),
            "max_event_snr": float(max(ev_snr)) if ev_snr else 0.0,
            "v_ratio": (d_e / d_c) if d_c > 0 else 0.0}


def _screen_one(args):
    """Worker: screen one star's cached QLP file. Returns a record dict
    (always, with 'status'), so the parent can count every outcome."""
    tic, path, sector, star = args
    rec = {"tic": tic, "sector": int(sector), "product": PRODUCT,
           "ra": star.get("ra"), "dec": star.get("dec"),
           "tmag": star.get("tmag"), "radius_rsun": star.get("radius"),
           "status": "searched"}
    try:
        from astropy.io import fits
        from astropy.timeseries import BoxLeastSquares
        with fits.open(path, memmap=True) as hdul:
            data = hdul[1].data
            t = np.asarray(data["TIME"], dtype=float)
            flux = np.asarray(data["KSPSAP_FLUX"], dtype=float)
            qual = np.asarray(data["QUALITY"], dtype=int)
        # Quality mask = lightkurve's TESS DEFAULT bitmask (17087), NOT
        # quality==0. Lesson (proof-run smoke test, 2026-11-11): TOI-700
        # c's ONLY sector-1 transit sits entirely on cadences flagged
        # 4096 (bit 12, not in the default mask); requiring quality==0
        # deleted the transit and the control star vanished. The deep
        # pipeline keeps these cadences via lightkurve defaults — the
        # screen must see the same data the gauntlet sees.
        ok = np.isfinite(t) & np.isfinite(flux) & ((qual & 17087) == 0)
        t, f = t[ok], flux[ok]
        if len(t) < 200:
            rec["status"] = "too_few_points"
            return rec
        # normalise + clip (QLP KSPSAP is already detrended/normalised)
        med = np.median(f)
        f = f / med
        sd = 1.4826 * np.median(np.abs(f - 1.0))
        if sd > 0:
            keep = np.abs(f - 1.0) < 5 * sd
            t, f = t[keep], f[keep]
        # light flatten at the deep pipeline's ~2 d scale (Savitzky-Golay)
        from scipy.signal import savgol_filter
        dt = float(np.median(np.diff(t)))
        win = int(round(2.0 / dt)) if dt > 0 else 97
        win += (win % 2 == 0)
        win = int(min(max(win, 31), len(t) // 2 * 2 - 1))
        if win >= 31:
            trend = savgol_filter(f, win, 2)
            trend[trend == 0] = 1.0
            f = f / trend
        f = f - np.median(f) + 1.0

        periods = 1.0 / np.linspace(1.0 / MAX_PERIOD_D, 1.0 / MIN_PERIOD_D,
                                    BLS_GRID_POINTS)
        bls = BoxLeastSquares(t, f)
        res = bls.power(periods, list(BLS_DURATIONS_D))
        pv = np.asarray(res.period, dtype=float)
        pw = np.asarray(res.power, dtype=float)
        med_p, scale = _robust_sde(pw, pv)
        sde_all = (pw - med_p) / scale
        i = int(np.argmax(sde_all))
        period = float(pv[i])
        sde = float(sde_all[i])
        depth = float(res.depth[i])
        duration = float(res.duration[i])
        t0 = float(res.transit_time[i])
        rec.update({"period_days": period, "t0_btjd": t0,
                    "duration_hours": duration * 24.0,
                    "depth_percent": depth * 100.0, "sde": sde,
                    "near_systematic": bool(any(
                        abs(period - s) <= 0.03 * s
                        for s in SYSTEMATIC_PERIODS))})
        # Next two distinct peaks (hunter v2 pattern) ride along: a
        # single-sector screen can pin the wrong alias on a lone transit
        # (proof control: sector 1 holds ONE TOI-700 c transit; the
        # argmax lands on a long-period alias) — the gauntlet deserves
        # the alternates, not just the headline.
        _work = sde_all.copy()
        _work[np.abs(pv - period) <= 0.02 * period] = -np.inf
        alts = []
        for _ in range(2):
            _j = int(np.argmax(_work))
            if not np.isfinite(_work[_j]) or _work[_j] < 3.0:
                break
            alts.append({"period_days": float(pv[_j]),
                         "sde": float(_work[_j]),
                         "depth_percent": float(res.depth[_j]) * 100.0})
            _work[np.abs(pv - pv[_j]) <= 0.02 * pv[_j]] = -np.inf
        if alts:
            rec["alt_peaks"] = alts
        if sde < RECORD_FLOOR_SDE:
            rec["status"] = "below_floor"
            return rec

        # --- free vetoes -------------------------------------------------
        flags = []
        depth_odd, depth_even, oe_ratio = _odd_even(t, f, period, t0,
                                                    duration)
        rec["odd_even_ratio"] = oe_ratio
        _, _, noise = _fold_depth(t, f, period, t0, duration)
        sig = (min(depth_odd, depth_even) / noise) if np.isfinite(noise) \
            else 0.0
        if oe_ratio < 0.5 and sig >= 3.0:
            flags.append("ODD_EVEN_EB")
        sec_depth, _, sec_noise = _fold_depth(t, f, period, t0, duration,
                                              phase_center=0.5)
        rec["secondary_depth_percent"] = sec_depth * 100.0
        if depth > 0 and sec_depth >= 0.8 * depth and \
                (sec_depth / sec_noise if np.isfinite(sec_noise) else 0) \
                >= 3.0:
            flags.append("SECONDARY_EB")
        if duration > 0.35 * period:
            flags.append("DURATION_EB")
        if depth * 100.0 > DEPTH_EB_PCT:
            flags.append("DEPTH_EB")
        if depth * 100.0 < DEPTH_MIN_PCT:
            flags.append("DEPTH_TOO_SHALLOW")
        # sub-floor harmonic check (TIC 29780280 lesson): if P/2 or P/3
        # falls below the search floor, BLS could not have seen the true
        # fundamental — fold there and compare binned profile depth.
        for k in (2, 3):
            psub = period / k
            if psub < MIN_PERIOD_D + 0.05:
                dsub, _, _ = _fold_depth(t, f, psub, t0, duration / k)
                if depth > 0 and dsub >= 0.8 * depth:
                    flags.append(f"HARMONIC_P{k}_SUSPECT")
        rec["flags"] = flags
        demote = [x for x in flags if x.endswith("_EB")
                  or "HARMONIC" in x or x == "DEPTH_TOO_SHALLOW"]
        # v1.1: pink-noise MES rescore decides survivorship (tiers in
        # the constants block). SDE >= SURVIVOR_SDE stays a necessary
        # condition — both currencies must agree.
        rs = _rescore(t, f, period, t0, duration)
        if rs is not None:
            rec.update(rs)
        tier = None
        if rs is not None and sde >= SURVIVOR_SDE:
            if rs["n_events"] >= TIER_A_MIN_EVENTS and \
                    rs["mes_pink"] >= TIER_A_MES and \
                    rs["n_strong_events"] >= TIER_A_MIN_STRONG:
                tier = "A"
            elif rs["n_events"] < TIER_A_MIN_EVENTS and \
                    rs["max_event_snr"] >= TIER_B_EVENT_SNR and \
                    depth * 100.0 <= TIER_B_MAX_DEPTH_PCT:
                tier = "B"
        rec["tier"] = tier
        if demote:
            rec["status"] = "demoted"
        elif tier is not None:
            rec["status"] = "survivor"
        else:
            rec["status"] = "recorded"
        return rec
    except Exception as e:
        rec["status"] = "error"
        rec["error"] = f"{type(e).__name__}: {e}"
        return rec


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(description="Exoplanet Hunter bulk screen")
    ap.add_argument("--sector", type=int, default=1)
    ap.add_argument("--ra", type=float, default=None)
    ap.add_argument("--dec", type=float, default=None)
    ap.add_argument("--cone", type=float, default=6.0,
                    help="cone radius in degrees (with --ra/--dec)")
    ap.add_argument("--stars-file", default=None,
                    help="CSV tic,ra,dec,tmag,radius instead of a cone")
    ap.add_argument("--min-mag", type=float, default=10.0)
    ap.add_argument("--max-mag", type=float, default=13.5)
    ap.add_argument("--min-rad", type=float, default=0.2)
    ap.add_argument("--max-rad", type=float, default=0.8)
    ap.add_argument("--limit", type=int, default=None,
                    help="cap the star list (testing)")
    ap.add_argument("--control-tic", default=None,
                    help="known-signal star whitelisted past the filter")
    ap.add_argument("--skip-filter", action="store_true",
                    help="skip the known filter entirely (testing)")
    ap.add_argument("--dl-workers", type=int, default=8)
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count()
                                                          or 2) - 1))
    ap.add_argument("--cache-dir", default=str(ROOT / "bulk" / "cache"))
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args(argv)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    logf = open(out_dir / "run.log", "a")
    run_t0 = time.time()
    summary = {"tool": "bulk_screen v1.1", "sector": args.sector,
               "product": PRODUCT,
               "window": {"min_mag": args.min_mag, "max_mag": args.max_mag,
                          "min_rad": args.min_rad, "max_rad": args.max_rad},
               "thresholds": {"record_floor_sde": RECORD_FLOOR_SDE,
                              "survivor_sde": SURVIVOR_SDE,
                              "depth_min_pct": DEPTH_MIN_PCT,
                              "depth_eb_pct": DEPTH_EB_PCT,
                              "period_range_d": [MIN_PERIOD_D,
                                                 MAX_PERIOD_D],
                              "tier_a_mes": TIER_A_MES,
                              "tier_a_min_events": TIER_A_MIN_EVENTS,
                              "tier_a_min_strong": TIER_A_MIN_STRONG,
                              "tier_b_event_snr": TIER_B_EVENT_SNR,
                              "tier_b_max_depth_pct": TIER_B_MAX_DEPTH_PCT},
               "control_tic": args.control_tic}

    # 1 — star list ------------------------------------------------------
    if args.stars_file:
        stars = file_star_list(args.stars_file)
    else:
        if args.ra is None or args.dec is None:
            ap.error("--ra/--dec required without --stars-file")
        stars = cone_star_list(args.ra, args.dec, args.cone, args.min_mag,
                               args.max_mag, args.min_rad, args.max_rad,
                               logf)
    if args.limit:
        stars = stars[:args.limit]
    # control star must be present even if outside the window
    if args.control_tic and not any(s["tic"] == str(args.control_tic)
                                    for s in stars):
        log(f"control TIC {args.control_tic} not in star list — "
            f"appending it bare (filter-whitelisted)", logf)
        stars.append({"tic": str(args.control_tic), "ra": None,
                      "dec": None, "tmag": None, "radius": None})
    summary["stars_in"] = len(stars)
    log(f"star list: {len(stars)} stars, sector {args.sector}", logf)

    # 2 — known filter (before any compute) ------------------------------
    t = time.time()
    if args.skip_filter:
        kept, skipped = stars, {"toi": [], "vsx": []}
        log("known filter SKIPPED (--skip-filter)", logf)
    else:
        kept, skipped = apply_known_filter(
            stars, args.control_tic, logf,
            center=((args.ra, args.dec) if args.ra is not None else None),
            cone_deg=(args.cone if args.ra is not None else None))
    summary["filter_seconds"] = time.time() - t
    summary["skipped_known"] = {k: len(v) for k, v in skipped.items()}
    summary["skipped_known_tics"] = skipped
    summary["stars_after_filter"] = len(kept)

    # 3 — bulk download ----------------------------------------------------
    paths, dl_stats = download_all(kept, args.sector, args.cache_dir,
                                   args.dl_workers, logf)
    summary["download"] = dl_stats

    # 4 — screen -----------------------------------------------------------
    t = time.time()
    by_tic = {s["tic"]: s for s in kept}
    jobs = [(tic, paths[tic], args.sector, by_tic[tic]) for tic in paths]
    records = []
    counts = {}
    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        for rec in ex.map(_screen_one, jobs, chunksize=8):
            records.append(rec)
            counts[rec["status"]] = counts.get(rec["status"], 0) + 1
    screen_seconds = time.time() - t
    summary["screen_seconds"] = screen_seconds
    summary["screen_counts"] = counts
    summary["stars_searched"] = len(jobs)
    if screen_seconds > 0:
        summary["screen_stars_per_hour"] = round(
            len(jobs) / screen_seconds * 3600)
    log(f"screen: {counts} in {screen_seconds:.0f}s "
        f"({summary.get('screen_stars_per_hour', 0)} stars/h compute)",
        logf)

    # 5 — survivors: gauntlet-shaped output --------------------------------
    hits = [r for r in records
            if r.get("sde") is not None and r["sde"] >= RECORD_FLOOR_SDE]
    hits.sort(key=lambda r: -r["sde"])
    survivors = [r for r in hits if r["status"] == "survivor"]
    for r in survivors:
        r["control"] = bool(args.control_tic
                            and r["tic"] == str(args.control_tic))
    summary["survivor_tiers"] = {
        t: sum(1 for r in survivors if r.get("tier") == t)
        for t in ("A", "B")}
    novel, zoo_known = annotate_survivors_zooniverse(survivors, logf)
    summary["zooniverse_known_survivors"] = [r["tic"] for r in zoo_known]

    def emit(rec):
        keys = ("tic", "period_days", "t0_btjd", "duration_hours",
                "depth_percent", "sde", "sector", "product", "ra", "dec",
                "tmag", "radius_rsun", "flags", "odd_even_ratio",
                "secondary_depth_percent", "near_systematic", "control",
                "status", "known_source", "alt_peaks", "mes_pink",
                "cdpp_pct", "n_events", "n_strong_events",
                "max_event_snr", "v_ratio", "tier")
        return {k: rec.get(k) for k in keys if rec.get(k) is not None}

    with open(out_dir / "survivors.jsonl", "w") as fh:
        for r in novel:
            fh.write(json.dumps(emit(r)) + "\n")
    with open(out_dir / "screen_hits.jsonl", "w") as fh:
        for r in hits:
            fh.write(json.dumps(emit(r)) + "\n")

    # control verdict — the run's honesty check
    if args.control_tic:
        crec = next((r for r in records if r["tic"] == str(args.control_tic)),
                    None)
        if crec is None or crec.get("sde") is None:
            summary["control"] = {"tic": args.control_tic,
                                  "result": "NOT_SCREENED",
                                  "status": (crec or {}).get("status")}
        else:
            rank = 1 + sum(1 for r in hits if r["sde"] > crec["sde"])
            summary["control"] = {
                "tic": args.control_tic, "result": "SCREENED",
                "sde": crec["sde"], "period_days": crec.get("period_days"),
                "depth_percent": crec.get("depth_percent"),
                "status": crec["status"], "rank_by_sde": rank,
                "mes_pink": crec.get("mes_pink"),
                "tier": crec.get("tier"),
                "caught_as_survivor": crec["status"] == "survivor"}
        log(f"CONTROL {args.control_tic}: {summary['control']}", logf)

    summary["hits_recorded"] = len(hits)
    summary["survivors"] = len(novel)
    summary["survivor_tics"] = [r["tic"] for r in novel]
    summary["wall_seconds"] = time.time() - run_t0
    total_stars = summary["stars_after_filter"]
    if summary["wall_seconds"] > 0 and total_stars:
        summary["end_to_end_stars_per_hour"] = round(
            total_stars / summary["wall_seconds"] * 3600)
    with open(out_dir / "summary.json", "w") as fh:
        json.dump(summary, fh, indent=2)
    log(f"DONE: {len(novel)} novel survivors, {len(hits)} recorded hits, "
        f"wall {summary['wall_seconds']:.0f}s, end-to-end "
        f"{summary.get('end_to_end_stars_per_hour', 0)} stars/h", logf)
    logf.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
