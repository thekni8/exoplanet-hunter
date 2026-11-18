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

STAR LIST — TARGET-LIST METHOD (v1.2, 2026-11-11)
-------------------------------------------------
--target-list builds the list the way Rabtsevich did (teardown §1):
the sector's QLP target-list CSV (archive.stsci.edu/hlsps/qlp/
target_lists/sXXXX.csv; sector 98 = 628,730 unique TICs, re-verified
locally) + batched TIC 8.2 lookups by ID (batches of 5,000) for
Tmag/radius, window applied locally. Raw CSV and enriched metadata
are cached under bulk/cache/target_lists/ and the metadata cache is
appended batch-by-batch, so a cold sector build is resumable; warm
builds are instant. His recount rule (Tmag <= 11.5, no radius cut —
use --min-mag 0 --max-mag 11.5 and require_radius off via the API)
reproduces his 126,246 for sector 98.

USAGE
-----
  python bulk_screen.py --sector 1 --ra 97.0969 --dec -65.5793 \
      --cone 6 --control-tic 150428135 --out-dir bulk/run_s0001
  python bulk_screen.py --sector 98 --target-list --out-dir bulk/run_s0098
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
from concurrent.futures import (FIRST_COMPLETED, ProcessPoolExecutor,
                              ThreadPoolExecutor, wait as _futures_wait)
from pathlib import Path

import numpy as np

import netbound as _net
import provenance as _prov
from atomic_io import atomic_write_json as _atomic_write_json
from atomic_io import atomic_writer as _atomic_writer
from calibration import CalibrationError as _CalibrationError
from calibration import load_profile as _load_profile
from calibration import short_version as _short_version
from quality_flags import SPOC_DEFAULT_MASK as _SPOC_DEFAULT_MASK
from quality_flags import tally_unmasked_bits as _tally_unmasked_bits
from mad_clip import PROFILE_OPTIONS as _CLIP_PROFILE_OPTIONS
from mad_clip import ALL_OPTIONS as _CLIP_ALL_OPTIONS
from mad_clip import mad_clip_mask as _mad_clip_mask
import ingest as _ingest
import search_health as _search_health
from bulk.grid_edge import build_handoff_record as _build_handoff_record
from bulk.grid_edge import disposition_grid_edge as _disposition_grid_edge
# P3-15: the adopted tier-B gates live in bulk/replay_matrix.py —
# the screen calls them, it does not re-implement them.
from bulk.replay_matrix import CLUSTER_MIN_SIZE as _RM_CLUSTER_MIN_SIZE
from bulk.replay_matrix import CLUSTER_TOL_P as _RM_CLUSTER_TOL_P
from bulk.replay_matrix import CLUSTER_TOL_T0_D as _RM_CLUSTER_TOL_T0_D
from bulk.replay_matrix import (sector_epoch_cluster_tics as
                                _sector_epoch_cluster_tics)
from bulk.replay_matrix import two_event_combined as _two_event_combined
from validation import validate_survivor as _validate_survivor

# Thresholds — loaded from the versioned calibration profile
# (Phase 1.1, item 2; see calibration/README.md). The profile file
# is the single source of truth: to change a threshold, copy
# calibration/bulk_v1.yaml to bulk_v2.yaml, bump the version, and
# point the loader at the new version — never edit a profile that
# has already stamped records. Module-level names are kept so
# importers (and the golden suite) see the same constants as before.
#
# Selection (Phase 1.2, item B-2): v1 stays the DEFAULT — the
# import-time load below is bulk_v1 unless EXHUNT_BULK_CALIBRATION
# names another profile (the offline-suite-under-v2 seam, same
# pattern as EXHUNT_FIXTURE_DIR). Real runs select the version
# once, up front, with --calibration; set_calibration() is what
# the flag calls. Per-star switching would make screens
# incomparable, so there is no per-call selection.
def _apply_profile(prof):
    """Derive the module constants from a loaded profile dict."""
    global _BULK_CAL, CALIBRATION_VERSION, CALIBRATION_MAP
    global RECORD_FLOOR_SDE, SURVIVOR_SDE, DEPTH_MIN_PCT, DEPTH_EB_PCT
    global TIER_A_MES, TIER_A_MIN_EVENTS, TIER_A_MIN_STRONG
    global STRONG_EVENT_SNR, TIER_B_EVENT_SNR, TIER_B_MAX_DEPTH_PCT
    global MIN_PERIOD_D, MAX_PERIOD_D, BLS_GRID_POINTS, BLS_DURATIONS_D
    global SYSTEMATIC_PERIODS, CLIP_OPTION, SYSTEMATIC_WINDOWS
    global QUALITY_MASK
    global GRID_EDGE_MIN_IN_TRANSIT, GRID_EDGE_MAX_UNMASKED_FRACTION
    global TWO_COMBINED_ENABLED, EPOCH_CLUSTER_VETO_ENABLED
    global EPOCH_CLUSTER_VETO_TIER_A
    global EPOCH_CLUSTER_TOL_P, EPOCH_CLUSTER_TOL_T0_D
    global EPOCH_CLUSTER_MIN_SIZE
    global EVENT_GUARD_D, EVENT_GAP_D, EVENT_MIN_COVERAGE
    global EVENT_MIN_CADENCES
    _BULK_CAL = prof
    CALIBRATION_VERSION = prof["version"]
    # Provenance map (A-2): per-subsystem bare versions, {"bulk": "v1"}.
    CALIBRATION_MAP = {"bulk": _short_version(CALIBRATION_VERSION)}
    RECORD_FLOOR_SDE = prof["record_floor_sde"]
    SURVIVOR_SDE = prof["survivor_sde"]
    DEPTH_MIN_PCT = prof["depth_min_pct"]
    DEPTH_EB_PCT = prof["depth_eb_pct"]
    TIER_A_MES = prof["tier_a_mes"]
    TIER_A_MIN_EVENTS = prof["tier_a_min_events"]
    TIER_A_MIN_STRONG = prof["tier_a_min_strong"]
    STRONG_EVENT_SNR = prof["strong_event_snr"]
    TIER_B_EVENT_SNR = prof["tier_b_event_snr"]
    TIER_B_MAX_DEPTH_PCT = prof["tier_b_max_depth_pct"]
    MIN_PERIOD_D = prof["min_period_d"]
    MAX_PERIOD_D = prof["max_period_d"]
    BLS_GRID_POINTS = prof["bls_grid_points"]
    BLS_DURATIONS_D = tuple(prof["bls_durations_d"])
    SYSTEMATIC_PERIODS = tuple(prof["systematic_periods"])
    # Clip option (B-2): v1 profiles predate the field and mean
    # the symmetric 5-sigma clip. A profile may only declare a
    # real option — "none" is the grid's unclipped reference and
    # is rejected here, never a runnable calibration.
    CLIP_OPTION = prof.get("clip_option", "symmetric")
    if CLIP_OPTION not in _CLIP_PROFILE_OPTIONS:
        raise _CalibrationError(
            f"calibration profile {prof['version']!r} declares "
            f"clip_option {CLIP_OPTION!r} — expected one of "
            f"{', '.join(_CLIP_PROFILE_OPTIONS)}")
    # Per-sector systematic windows (B-2): measured pile-up bands
    # from the RECALIBRATION reports, hard-coded in the profile —
    # never derived from survivor histograms. v1 has none.
    SYSTEMATIC_WINDOWS = {
        int(sector): [tuple(w) for w in windows]
        for sector, windows
        in prof.get("systematic_windows", {}).items()}
    # Quality mask (bulk_v3): which QUALITY bits exclude a cadence
    # from BLS input. v1/v2 profiles predate the field and mean
    # lightkurve's TESS default (SPOC_DEFAULT_MASK, 17087 — bits
    # 0,1,2,3,4,5,7,9,14; see quality_flags.py for the named table
    # and sources). v3 adds bits 29/30 (QLP flags, outside SPOC's
    # 16-bit table): the bulk_v2 rescore gauntlet found 18/25 NEW
    # S96 leads were dips living only on bit-29/30 cadences, which
    # the 17087 mask keeps and v2's 10% clip floor preserves. The
    # value must be a plain integer bitmask — a profile that
    # declares anything else fails loudly here, never silently at
    # screen time.
    QUALITY_MASK = prof.get("quality_mask", _SPOC_DEFAULT_MASK)
    if isinstance(QUALITY_MASK, bool) \
            or not isinstance(QUALITY_MASK, int) or QUALITY_MASK < 0:
        raise _CalibrationError(
            f"calibration profile {prof['version']!r} declares "
            f"quality_mask {QUALITY_MASK!r} — expected a "
            f"non-negative integer bitmask")
    # Grid-edge floor (P3-14): the quality floor for
    # SINGLE_TRANSIT_POOL — no unmasked in-transit flags and >= 4
    # in-transit cadences. Profiles that predate the fields mean
    # the vote's values (the quality_mask/clip_option pattern):
    # the floor is a disposition rule, not a threshold change, so
    # it applies under every profile.
    GRID_EDGE_MIN_IN_TRANSIT = int(prof.get(
        "grid_edge_min_in_transit_cadences", 4))
    GRID_EDGE_MAX_UNMASKED_FRACTION = float(prof.get(
        "grid_edge_max_unmasked_flag_fraction", 0.0))
    # Tier-B tightening gates (P3-15, bulk_v4): profiles that
    # predate the keys mean the gates OFF — a frozen profile's
    # behaviour must not change. The epoch-cluster criterion
    # defaults to the P3-13 values (inert while the veto is
    # off). A profile that declares criterion values MUST match
    # replay_matrix's P3-13 constants: the criterion is
    # vote-frozen, and a profile declaring different values is
    # a bug, not a feature — fail loud here, never silently at
    # screen time.
    TWO_COMBINED_ENABLED = bool(prof.get("two_combined_enabled",
                                         False))
    EPOCH_CLUSTER_VETO_ENABLED = bool(prof.get(
        "epoch_cluster_veto_enabled", False))
    # Tier-A veto extension (bulk_v5, fixes round 1): profiles
    # that predate the key mean False (tier-A flagged, never
    # demoted) — a frozen profile's behaviour must not change.
    EPOCH_CLUSTER_VETO_TIER_A = bool(prof.get(
        "epoch_cluster_veto_tier_a", False))
    EPOCH_CLUSTER_TOL_P = float(prof.get(
        "epoch_cluster_tol_p", _RM_CLUSTER_TOL_P))
    EPOCH_CLUSTER_TOL_T0_D = float(prof.get(
        "epoch_cluster_tol_t0_d", _RM_CLUSTER_TOL_T0_D))
    EPOCH_CLUSTER_MIN_SIZE = int(prof.get(
        "epoch_cluster_min_size", _RM_CLUSTER_MIN_SIZE))
    if (EPOCH_CLUSTER_TOL_P != _RM_CLUSTER_TOL_P
            or EPOCH_CLUSTER_TOL_T0_D != _RM_CLUSTER_TOL_T0_D
            or EPOCH_CLUSTER_MIN_SIZE != _RM_CLUSTER_MIN_SIZE):
        raise _CalibrationError(
            f"calibration profile {prof['version']!r} declares "
            f"epoch-cluster criterion ({EPOCH_CLUSTER_TOL_P}, "
            f"{EPOCH_CLUSTER_TOL_T0_D}, {EPOCH_CLUSTER_MIN_SIZE}) "
            f"— expected the P3-13 criterion "
            f"({_RM_CLUSTER_TOL_P}, {_RM_CLUSTER_TOL_T0_D}, "
            f"{_RM_CLUSTER_MIN_SIZE}) from bulk/replay_matrix.py")
    # Event-count rule (P4-2, Phase 4): an event counts only if
    # its full window lies within one contiguous valid segment
    # with a guard clearance from the segment edges, with
    # in-window coverage >= EVENT_MIN_COVERAGE of the expected
    # cadences and >= EVENT_MIN_CADENCES cadences. Profiles that
    # predate the fields mean the PB-6 pre-registered values
    # (guard 0.0, gap 0.05 d, coverage 0.5, min 3 cadences) —
    # the rule is a measurement correction, not a threshold
    # change, so it applies under every profile; the guard is
    # the one tunable, chosen from the PB-2 curve. A profile
    # that declares invalid values fails loudly here.
    EVENT_GUARD_D = float(prof.get("event_guard_d", 0.0))
    EVENT_GAP_D = float(prof.get("event_gap_d", 0.05))
    EVENT_MIN_COVERAGE = float(prof.get("event_min_coverage", 0.5))
    EVENT_MIN_CADENCES = int(prof.get("event_min_cadences", 3))
    if EVENT_GUARD_D < 0 or EVENT_GAP_D <= 0 \
            or not (0 < EVENT_MIN_COVERAGE <= 1.0) \
            or EVENT_MIN_CADENCES < 1:
        raise _CalibrationError(
            f"calibration profile {prof['version']!r} declares "
            f"invalid event-count rule "
            f"(guard {EVENT_GUARD_D}, gap {EVENT_GAP_D}, "
            f"coverage {EVENT_MIN_COVERAGE}, "
            f"min cadences {EVENT_MIN_CADENCES})")


def set_calibration(name):
    """Load profile `name` (registry-verified) and re-derive the
    module constants. Restores are the caller's job (tests:
    setUp/tearDown back to bulk_v1)."""
    _apply_profile(_load_profile(name))


def set_clip_option(option):
    """Override the clip option in-process — GRID + TESTS ONLY.
    Real runs get the option from the profile; this exists so the
    clip grid can evaluate options through the real screen path
    without a profile per option. "none" (the grid's unclipped
    reference) is allowed here and only here."""
    global CLIP_OPTION
    if option not in _CLIP_ALL_OPTIONS:
        raise ValueError(
            f"unknown clip option {option!r} — expected one of "
            f"{', '.join(_CLIP_ALL_OPTIONS)}")
    CLIP_OPTION = option


def set_event_guard(guard_d):
    """Override the event-count guard in-process — MEASUREMENT +
    TESTS ONLY. Production runs get the guard from the profile
    (default 0.0); this exists so the guard curve can be
    measured through the real screen path without a profile per
    guard value (the set_clip_option pattern)."""
    global EVENT_GUARD_D
    guard_d = float(guard_d)
    if guard_d < 0:
        raise ValueError(
            f"event guard must be >= 0, got {guard_d}")
    EVENT_GUARD_D = guard_d


def _init_worker(calibration, event_guard_d=None):
    """ProcessPoolExecutor initializer (P4-2): each worker sets
    its own calibration (+ optional event-guard override), so a
    spawn worker (macOS) screens under the requested profile
    instead of the import-time bulk_v1 default. The
    inject_campaign.py _init_worker pattern. Without this,
    every bulk_screen.py CLI run on macOS screened with bulk_v1
    preprocessing regardless of --calibration while stamping
    records with the requested calibration (PB-2, proven
    2026-11-17)."""
    set_calibration(calibration)
    if event_guard_d is not None:
        set_event_guard(event_guard_d)


_apply_profile(_load_profile(
    os.environ.get("EXHUNT_BULK_CALIBRATION", "bulk_v1")))


# Sectors screened under v1 (S96-S98). v1's MAD clip has a known
# sensitivity defect (no depth floor); no NEW sector may screen
# under v1 without an explicit --allow-v1 (B-2).
V1_SECTORS = (96, 97, 98)


def enforce_v1_gate(calibration_name, sector, allow_v1):
    """Refuse a screen outside the v1 sectors under a v1
    calibration, unless --allow-v1 was passed. Raises
    CalibrationError — main() turns it into a CLI error."""
    if (calibration_name == "bulk_v1" and int(sector) not in V1_SECTORS
            and not allow_v1):
        raise _CalibrationError(
            f"refusing to screen sector {sector} under bulk_v1: "
            f"v1's MAD clip has no depth floor (bulk_v2 fixes it). "
            f"Screen under bulk_v2 (--calibration bulk_v2) or pass "
            f"--allow-v1 to proceed knowingly.")

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

# ---------------------------------------------------------------------------
# Non-calibration constants (product + data source, not thresholds)
# ---------------------------------------------------------------------------
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
        # C-1: astroquery takes no timeout — watch the call, or a
        # hung tile hangs the whole cone query. A timeout fails
        # the run (fail-LOUD): a missing tile would silently drop
        # stars from the window.
        tab = _net.mast_call(
            lambda: Catalogs.query_criteria(
                catalog="Tic",
                coordinates=SkyCoord(ra=tc[0] * u.deg,
                                     dec=tc[1] * u.deg),
                radius=tile_deg * u.deg,
                Tmag=[min_mag, max_mag], rad=[min_rad, max_rad]),
            name=f"TIC tile ({tc[0]:.2f},{tc[1]:.2f})")
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


TARGET_LIST_URL = ("https://archive.stsci.edu/hlsps/qlp/"
                   "target_lists/s{sec:04d}.csv")
TIC_BATCH = 5000  # Rabtsevich's deposited recount used batches of 5,000


def _tic_batch(ids):
    """One batched TIC 8.2 lookup (Catalogs.query_criteria by ID list).
    Returns {tic: {ra, dec, tmag, radius}}; NaNs become None."""
    from astroquery.mast import Catalogs

    def _f(v):
        try:
            x = float(v)
        except (TypeError, ValueError):
            return None
        return None if math.isnan(x) else x

    tab = _net.mast_call(
        lambda: Catalogs.query_criteria(catalog="Tic",
                                        ID=[int(i) for i in ids]),
        name=f"TIC batch lookup ({len(ids)} ids)")
    out = {}
    for row in tab:
        out[str(row["ID"])] = {"ra": _f(row["ra"]), "dec": _f(row["dec"]),
                               "tmag": _f(row["Tmag"]),
                               "radius": _f(row["rad"])}
    return out


def target_list_star_list(sector, min_mag, max_mag, min_rad, max_rad,
                          cache_dir, logf=None, require_radius=True,
                          limit_ids=None, workers=3):
    """Sector target-list method — how Rabtsevich built his 126k list
    (teardown §1, recounted and verified there):

    1. The sector's QLP target list (TIC_ID, RA, DEC for every star QLP
       extracted that sector) is a plain CSV at archive.stsci.edu.
    2. Tmag / radius come from batched TIC 8.2 lookups by ID
       (query_criteria, batches of 5,000 — his deposited batch size).
    3. The window is applied locally.

    Both downloads are cached under <cache_dir>/target_lists/: the raw
    CSV (sXXXX.csv) and the enriched metadata (sXXXX_tic.csv), the
    latter appended batch-by-batch so an interrupted build RESUMES —
    a full sector is ~470-630k IDs and a lookup batch takes ~0.5-2 min
    through the proxy, so a cold build is a long, cache-building job,
    not a per-run cost. Returns (stars, stats)."""
    tl_dir = Path(cache_dir) / "target_lists"
    tl_dir.mkdir(parents=True, exist_ok=True)
    raw_path = tl_dir / f"s{sector:04d}.csv"
    if not raw_path.exists():
        url = TARGET_LIST_URL.format(sec=sector)
        log(f"target list: downloading {url}", logf)
        # C-1: urlretrieve takes no timeout — a hung CSV download
        # hung the build forever. Streaming + timeout + atomic
        # rename instead.
        _net.download_file(url, raw_path)
    ids, seen = [], set()
    with open(raw_path) as fh:
        fh.readline()  # '#TIC_ID,RA,DEC'
        for line in fh:
            tic = line.split(",", 1)[0].strip()
            if tic and tic not in seen:
                seen.add(tic)
                ids.append(str(int(tic)))
    if limit_ids:
        ids = ids[:limit_ids]
    stats = {"sector": sector, "target_list_ids": len(ids)}
    log(f"target list s{sector:04d}: {len(ids)} unique TIC IDs", logf)

    meta_path = tl_dir / f"s{sector:04d}_tic.csv"
    meta = {}
    if meta_path.exists():
        with open(meta_path) as fh:
            for row in csv.DictReader(fh):
                meta[row["tic"]] = {
                    "ra": float(row["ra"]) if row["ra"] else None,
                    "dec": float(row["dec"]) if row["dec"] else None,
                    "tmag": float(row["tmag"]) if row["tmag"] else None,
                    "radius": (float(row["radius"]) if row["radius"]
                               else None)}
    todo = [tid for tid in ids if tid not in meta]
    if todo:
        batches = [todo[i:i + TIC_BATCH]
                   for i in range(0, len(todo), TIC_BATCH)]
        log(f"target list: {len(todo)} IDs need TIC metadata "
            f"({len(batches)} batches of {TIC_BATCH})", logf)
        fh = open(meta_path, "a", newline="")
        w = csv.writer(fh)
        if meta_path.stat().st_size == 0:
            w.writerow(["tic", "ra", "dec", "tmag", "radius"])
        done = 0
        with ThreadPoolExecutor(max_workers=workers) as ex:
            for got in ex.map(_tic_batch, batches):
                meta.update(got)
                for tic, m in got.items():
                    w.writerow([tic, m["ra"], m["dec"], m["tmag"],
                                m["radius"]])
                fh.flush()
                done += 1
                log(f"target list: batch {done}/{len(batches)} cached "
                    f"({len(meta)} IDs enriched)", logf)
        fh.close()
    stats["tic_enriched"] = len(meta)

    stars, n_no_tmag, n_no_rad = [], 0, 0
    for tid in ids:
        m = meta.get(tid)
        if m is None or m["tmag"] is None:
            n_no_tmag += 1
            continue
        if not (min_mag <= m["tmag"] <= max_mag):
            continue
        if m["radius"] is None:
            n_no_rad += 1
            if require_radius:
                continue
        elif not (min_rad <= m["radius"] <= max_rad):
            continue
        stars.append({"tic": tid, "ra": m["ra"], "dec": m["dec"],
                      "tmag": m["tmag"], "radius": m["radius"]})
    stats.update({"in_window": len(stars), "missing_tmag": n_no_tmag,
                  "missing_radius_in_mag_window": n_no_rad})
    log(f"target list: {len(stars)} stars in window (Tmag {min_mag}-"
        f"{max_mag}, R {min_rad}-{max_rad}); {n_no_tmag} no-Tmag, "
        f"{n_no_rad} no-radius in mag window", logf)
    return stars, stats


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

def _near_systematic(period, sector):
    """True when the period sits in the generic systematic family
    (+-3% of 13.7/6.85/27.4 d) or inside a measured per-sector
    systematic window (bulk_v2+; v1 has no windows). A flag, not
    a veto — the recalibration step is the defense."""
    if any(abs(period - s) <= 0.03 * s for s in SYSTEMATIC_PERIODS):
        return True
    for lo, hi in SYSTEMATIC_WINDOWS.get(int(sector), ()):
        if lo <= period <= hi:
            return True
    return False


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


def segments_from_times(t, gap_d=None):
    """Contiguous valid segments: list of (start_idx, end_idx)
    (end exclusive) split wherever consecutive times jump more
    than gap_d (default the profile's EVENT_GAP_D)."""
    if gap_d is None:
        gap_d = EVENT_GAP_D
    if len(t) == 0:
        return []
    breaks = np.where(np.diff(t) > gap_d)[0]
    bounds = [0] + [int(b) + 1 for b in breaks] + [len(t)]
    return [(bounds[i], bounds[i + 1])
            for i in range(len(bounds) - 1)]


def _rescore(t, f, period, t0, duration, guard_d=None,
             min_cov_frac=None, filter_events=True):
    """Pink-noise MES rescore of a recorded hit (v1.1 calibration).

    Refolds the (already flattened) light curve at the BLS ephemeris and
    measures the noise the way LEO-Vetter does: CDPP at the transit
    duration — the std of means of out-of-transit chunks one duration
    long — so red noise on the transit timescale is priced in, unlike
    the white-noise fold error. MES = depth / CDPP * sqrt(N_events).
    Also returns per-event SNRs and the folded profile's edge/centre
    depth ratio (box ~1, V-shape << 1).
    Returns None when the noise cannot be measured (< 5 chunks).

    P4-2 event-count rule (default): an event counts only if its
    full [centre-D/2, centre+D/2] window lies within one
    contiguous valid segment (a gap is a jump > EVENT_GAP_D
    between consecutive valid cadences) with `guard_d` clearance
    from the segment edges, with in-window coverage >=
    min_cov_frac of the expected cadences and >=
    EVENT_MIN_CADENCES cadences. Dropped events contribute
    nothing to depth/MES. guard_d/min_cov_frac default to the
    profile values (EVENT_GUARD_D / EVENT_MIN_COVERAGE).
    filter_events=False reproduces the pre-P4-2 rule (an event =
    >= 1 in-window cadence) — a MEASUREMENT seam only, for
    validating fresh screens against recorded rows; production
    always filters. When no event survives the filter, returns a
    zero-event dict (not None: the noise IS measurable, the
    event count is what changed)."""
    if guard_d is None:
        guard_d = EVENT_GUARD_D
    if min_cov_frac is None:
        min_cov_frac = EVENT_MIN_COVERAGE
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
    kept, dropped = [], []
    if filter_events:
        segs = segments_from_times(t)
        dt = float(np.median(np.diff(t))) if len(t) > 1 else 0.0
        expected = max(duration / dt, 1.0) if dt > 0 else 1.0
        for e in ev_list:
            c = float(t0 + e * period)
            lo, hi = c - 0.5 * duration, c + 0.5 * duration
            n_in = int(((t >= lo) & (t <= hi)).sum())
            cov = n_in / expected
            in_seg = False
            for (a, b) in segs:
                if t[a] - 1e-9 <= lo and hi <= t[b - 1] + 1e-9:
                    if (lo - t[a] >= guard_d - 1e-9
                            and t[b - 1] - hi >= guard_d - 1e-9):
                        in_seg = True
                    break
            if (in_seg and cov >= min_cov_frac
                    and n_in >= EVENT_MIN_CADENCES):
                kept.append(e)
            else:
                dropped.append(e)
    else:
        kept = list(ev_list)
    if not kept:
        # No event survives the filter: the signal has no counted
        # event. Return a zero-event rescore (not None: the noise
        # IS measurable, the event count is what changed).
        out = {"mes_pink": 0.0, "cdpp_pct": None, "n_events": 0,
               "n_strong_events": 0, "max_event_snr": 0.0,
               "v_ratio": 0.0, "n_events_dropped": len(dropped),
               "events_kept": [],
               "events_dropped": [float(e) for e in dropped]}
        # cdpp still measurable: compute it for the record.
        phase = ((phase_t / period + 0.5) % 1.0) - 0.5
        outwin = (~inwin) & (np.abs(phase) < 0.45)
        if outwin.sum() >= 20:
            dt2 = float(np.median(np.diff(t))) if len(t) > 1 else 0.0
            chunk = max(int(round(duration / dt2)), 1) if dt2 > 0 \
                else 1
            out_idx = np.where(outwin)[0]
            means = []
            for seg in np.split(out_idx,
                                np.where(np.diff(out_idx) > chunk)[0] + 1):
                for i in range(0, len(seg) - chunk + 1, chunk):
                    means.append(np.mean(f[seg[i:i + chunk]]))
            if len(means) >= 5:
                out["cdpp_pct"] = float(np.std(means)) * 100.0
        return out
    phase = ((phase_t / period + 0.5) % 1.0) - 0.5
    outwin = (~inwin) & (np.abs(phase) < 0.45)
    if outwin.sum() < 20:
        return None
    base = np.median(f[outwin])
    kept_mask = np.isin(events, kept)
    inwin_k = inwin & kept_mask
    depth = float(base - np.mean(f[inwin_k]))
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
              for e in kept]
    off = t - centres
    c_m = inwin_k & (np.abs(off) <= duration / 6)
    e_m = inwin_k & (np.abs(off) > duration / 6)
    d_c = float(base - np.mean(f[c_m])) if c_m.sum() >= 1 else 0.0
    d_e = float(base - np.mean(f[e_m])) if e_m.sum() >= 1 else 0.0
    return {"mes_pink": depth / cdpp * math.sqrt(len(kept)),
            "cdpp_pct": cdpp * 100.0, "n_events": len(kept),
            "n_strong_events": int(sum(1 for s in ev_snr
                                       if s >= STRONG_EVENT_SNR)),
            "max_event_snr": float(max(ev_snr)) if ev_snr else 0.0,
            "v_ratio": (d_e / d_c) if d_c > 0 else 0.0,
            "n_events_dropped": len(dropped),
            "events_kept": [float(e) for e in kept],
            "events_dropped": [float(e) for e in dropped]}


def _raw_in_transit_flags(t_raw, q_raw, period, t0, duration):
    """(flagged fraction, unmasked-bit tally, n_in_transit) of
    the in-transit cadences on the RAW (pre-mask) arrays at an
    ephemeris (M-4, 2026-11-15 vote; n_in_transit added P3-14
    as the grid-edge floor's cadence-count input).

    The fraction is the share of in-transit cadences carrying ANY
    quality flag, measured BEFORE masking -- so a survivor whose
    signal lives mostly on flagged cadences is visible as a
    flagged-cadence artifact suspect even when the mask kept its
    cadences (e.g. bit 11/12, which the mask deliberately does not
    exclude). The tally counts, per bit, the in-transit cadences
    carrying a bit the screen mask does NOT exclude -- it answers
    sector-wide whether bit 11 ever appears without bits 29/30.
    n_in_transit is the raw in-transit cadence count (0 when no
    raw cadence falls in transit). Returns (None, {}, 0) when no
    raw cadence falls in transit.
    `duration` is in days.
    """
    phase = ((t_raw - t0) / period + 0.5) % 1.0 - 0.5
    in_tr = np.abs(phase) < (duration / period) / 2
    n_in = int(in_tr.sum())
    if n_in == 0:
        return None, {}, 0
    q_in = np.asarray(q_raw, dtype=np.int64)[in_tr]
    frac = float((q_in != 0).sum()) / n_in
    return frac, _tally_unmasked_bits(q_in, QUALITY_MASK), n_in


def _header_int(value):
    """FITS header value as an int, or None (P3-14 camera/CCD —
    the hand-off record wants them when the header carries them)."""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _attach_grid_edge_disposition(rec, camera=None, ccd=None):
    """P3-14: attach the grid-edge disposition + hand-off record
    to an above-floor screen record, when it is a grid-edge
    record and the floor is evaluable on the available evidence.
    No-op otherwise — the record keeps no disposition field.
    The floor constants come from the profile (via the module
    globals _apply_profile derives)."""
    disposition, _reason = _disposition_grid_edge(
        rec, max_period_d=MAX_PERIOD_D,
        min_in_transit=GRID_EDGE_MIN_IN_TRANSIT,
        max_unmasked_fraction=GRID_EDGE_MAX_UNMASKED_FRACTION)
    if disposition is None:
        return
    rec["disposition"] = disposition
    rec["grid_edge"] = _build_handoff_record(
        rec, camera=camera, ccd=ccd, max_period_d=MAX_PERIOD_D,
        min_in_transit=GRID_EDGE_MIN_IN_TRANSIT,
        max_unmasked_fraction=GRID_EDGE_MAX_UNMASKED_FRACTION)


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
            # Flux column differs by QLP HLSP version: older sectors
            # (e.g. S1) carry KSPSAP_FLUX; newer ones (e.g. S98) dropped
            # it for SYS_RM_FLUX (the systematics-removed flux — the
            # column Rabtsevich's S98 screen used) with DET_FLUX as the
            # plain detrended fallback. Lesson 2026-11-11: chunk_00 of
            # the S98 run errored on all 5,000 stars with
            # KeyError KSPSAP_FLUX before this fallback existed.
            cols = data.columns.names
            fcol = next((c for c in ("KSPSAP_FLUX", "SYS_RM_FLUX",
                                     "DET_FLUX") if c in cols), None)
            if fcol is None:
                raise KeyError(f"no known flux column in {cols}")
            # F-4: the FITS-read boundary — time/flux go through
            # the shared float64 ingest (FITS flux is typically
            # float32; the savgol detrend below accumulates in
            # the input dtype — see ingest.py).
            t, flux, _ = _ingest.as_float64(data["TIME"],
                                            data[fcol])
            qual = np.asarray(data["QUALITY"], dtype=int)
            # P3-14: camera/CCD for the grid-edge hand-off
            # record (None when the header lacks them).
            _hdr = hdul[0].header
            camera = _header_int(_hdr.get("CAMERA"))
            ccd = _header_int(_hdr.get("CCD"))
        # Quality mask — profile-driven (QUALITY_MASK, derived in
        # _apply_profile), NOT quality==0. v1/v2 mean lightkurve's
        # TESS DEFAULT bitmask (17087). Lesson (proof-run smoke
        # test, 2026-11-11): TOI-700 c's ONLY sector-1 transit sits
        # entirely on cadences flagged 4096 (bit 12, not in the
        # default mask); requiring quality==0 deleted the transit
        # and the control star vanished. The deep pipeline keeps
        # these cadences via lightkurve defaults — the screen must
        # see the same data the gauntlet sees. v3 (bulk_v3) adds
        # bits 29/30 (TESS scattered light): the bulk_v2 rescore
        # gauntlet found 18/25 NEW S96 leads were dips living only
        # on bit-29/30 cadences, which 17087 keeps and v2's 10%
        # clip floor preserves.
        # M-4: keep the pre-mask arrays — the raw in-transit
        # flagged fraction + unmasked-bit tally are measured on
        # them at the found ephemeris, after BLS.
        t_raw, q_raw = t, qual
        ok = np.isfinite(t) & np.isfinite(flux) & ((qual & QUALITY_MASK) == 0)
        t, f = t[ok], flux[ok]
        if len(t) < 200:
            rec["status"] = "too_few_points"
            return rec
        # normalise + clip (QLP KSPSAP is already detrended/normalised).
        # The clip is the shared function (mad_clip.py, B-2); the
        # OPTION comes from the calibration profile (v1: symmetric
        # 5-sigma — the inline expression this replaces, bit for
        # bit; v2: the grid's choice).
        med = np.median(f)
        f = f / med
        keep = _mad_clip_mask(f, CLIP_OPTION)
        t, f = t[keep], f[keep]
        # light flatten at the deep pipeline's ~2 d scale (Savitzky-Golay)
        from scipy.signal import savgol_filter
        # F-4 tripwire: the detrend must never see a float32
        # array — a path that bypassed ingest fails here.
        _ingest.assert_float64(t, f, "detrend entry (_screen_one)")
        dt = float(np.median(np.diff(t)))
        win = int(round(2.0 / dt)) if dt > 0 else 97
        win += (win % 2 == 0)
        win = int(min(max(win, 31), len(t) // 2 * 2 - 1))
        if win >= 31:
            trend = savgol_filter(f, win, 2)
            trend[trend == 0] = 1.0
            f = f / trend
        f = f - np.median(f) + 1.0

        # Layer 2 provenance (A-2): the exact arrays entering BLS,
        # hashed so a result can be traced to the data it was
        # computed from — not just the code that ran. In-memory
        # and cheap; attached to every record that reaches BLS.
        # F-4 tripwire: BLS must never see a float32 array.
        _ingest.assert_float64(t, f, "BLS entry (_screen_one)")
        bls_hash = _prov.bls_input_hash(t, f)
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
                    "near_systematic": _near_systematic(period, sector),
                    "input_identity": _prov.input_identity(
                        product_ids=[Path(path).name],
                        sectors=[int(sector)], author=PRODUCT,
                        bls_input_hash=bls_hash)})
        # P3-1 (DF-20): periodogram health check. A degenerate
        # search records SEARCH_INVALID and returns here — it is
        # never a survivor, never a "below_floor" valid search,
        # and never enters a training or calibration dataset.
        # BOUNDARY_LIMITED searches continue normally (P3-14
        # dispositions them); the 20 d edge holds legitimate
        # single dips.
        _health, _health_reason = _search_health.assess_periodogram(
            pw, pv, i, sde, SYSTEMATIC_PERIODS, RECORD_FLOOR_SDE)
        rec["search_health"] = _health
        rec["search_health_reason"] = _health_reason
        if _health == _search_health.SEARCH_INVALID:
            rec["status"] = "search_invalid"
            return rec
        # (M-4 fields are attached below, after the record floor:
        # a below-floor record has no detection, so its BLS argmax
        # is a noise peak and an "in-transit flagged fraction" at
        # that ephemeris would measure noise, not the signal.)
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

        # M-4: raw in-transit flagged fraction + unmasked-bit
        # tally, on the pre-mask arrays at the found ephemeris.
        # Only for records that clear the record floor -- below
        # it there is no detection to diagnose.
        frac, tally, n_in_transit = _raw_in_transit_flags(
            t_raw, q_raw, period, t0, duration)
        rec["flagged_in_transit_frac"] = frac
        rec["unmasked_bits_in_transit"] = tally
        # P3-14: the raw in-transit cadence count — the
        # grid-edge floor's cadence-count input.
        rec["n_in_transit"] = n_in_transit

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
        # P3-15 (bulk_v4): TWO-COMBINED — a 2-event tier-B row
        # needs both events strong AND mes_pink >= 9.0 (the
        # tier_a_mes bar, reused). Rows with n_events != 2 are
        # unaffected (1-event rows are P3-14's singles; >=3
        # -event rows already meet tier A's >=2-strong
        # requirement). A failure demotes with flag
        # TWO_EVENT_WEAK + gate_reason FAILED_TWO_COMBINED —
        # the row is marked "unsure" for manual review, never
        # deleted: it stays in screen_hits.jsonl, queryable
        # (disposition == DEMOTED_SECTOR_EPOCH_CLUSTER OR
        # gate_reason present). The tier field is kept (the row
        # DID meet tier B) — the gate is the verdict, as with
        # the EB vetoes. The implementation is replay_matrix's
        # two_event_combined, called with the profile's
        # tier_a_mes; bulk_v1/v2/v3 never reach this branch
        # (TWO_COMBINED_ENABLED is False there).
        if tier == "B" and TWO_COMBINED_ENABLED and \
                not _two_event_combined(rec, mes_bar=TIER_A_MES):
            flags.append("TWO_EVENT_WEAK")
            demote.append("TWO_EVENT_WEAK")
            rec["gate_reason"] = "FAILED_TWO_COMBINED"
        if demote:
            rec["status"] = "demoted"
        elif tier is not None:
            rec["status"] = "survivor"
        else:
            rec["status"] = "recorded"
        # P3-14: grid-edge disposition for non-demoted
        # above-floor records. Demoted records keep their
        # demotion — the EB veto is the verdict there.
        if rec["status"] in ("survivor", "recorded"):
            _attach_grid_edge_disposition(rec, camera, ccd)
        if rec["status"] == "survivor":
            # Input file hash, survivors only (bounded cost): the
            # file was just read, so it is warm in the page cache.
            # A survivor's identity is its data, not just its numbers.
            file_sha = _prov.file_sha256(path)
            if file_sha is not None:
                rec["input_identity"]["input_file_sha256"] = file_sha
        return rec
    except Exception as e:
        rec["status"] = "error"
        rec["error"] = f"{type(e).__name__}: {e}"
        return rec


# ---------------------------------------------------------------------------
# Output records
# ---------------------------------------------------------------------------

_EMIT_KEYS = ("tic", "period_days", "t0_btjd", "duration_hours",
              "depth_percent", "sde", "sector", "product", "ra", "dec",
              "tmag", "radius_rsun", "flags", "odd_even_ratio",
              "secondary_depth_percent", "near_systematic", "control",
              "status", "search_health", "search_health_reason",
              "known_source", "alt_peaks", "mes_pink",
              "cdpp_pct", "n_events", "n_strong_events",
              "max_event_snr", "v_ratio", "tier", "input_identity",
              "flagged_in_transit_frac", "unmasked_bits_in_transit",
              "n_in_transit", "disposition", "grid_edge",
              "gate_reason")


def emit_survivor_record(rec, prov):
    """The gauntlet-shaped record for one screened star: the
    schema fields from the raw screen record plus the run's
    provenance header (Phase 1.1, item 1). None-valued fields are
    dropped — a missing measurement is absent, never a null that
    downstream code has to defend against. The provenance fields
    are always present (they are never None)."""
    out = {k: rec.get(k) for k in _EMIT_KEYS if rec.get(k) is not None}
    out.update(prov)
    return out


class CircuitBreakerError(RuntimeError):
    """Raised when MAX_CONSECUTIVE_TIMEOUTS watchdog timeouts
    occur in a row (F-13): the screen is timing out
    systematically — an outage, not a pathological star — and
    continuing would record the outage as '0 survivors'.
    main() catches it, logs a clear error, and returns non-zero
    WITHOUT writing a summary, so the slice is not checkpointed
    and the driver stops the run instead of merging a hollow
    result."""


# Consecutive watchdog timeouts that trip the circuit breaker
# (F-13). One pathological star is data; 25 in a row with no
# success in between is a systematic failure (a MAST outage, a
# hung filesystem, a broken worker). The limit counts timeout
# EVENTS in collection order — a successful completion resets
# it to 0 — so a healthy screen with occasional slow stars
# never trips.
MAX_CONSECUTIVE_TIMEOUTS = 25


def _collect_screen_results(ex, jobs, worker, timeout_s, logf=None,
                            max_consecutive_timeouts=None,
                            max_in_flight=None):
    """Submit screen jobs in a bounded in-flight window and
    collect the records, with a per-star watchdog (C-1) and a
    consecutive-timeout circuit breaker (F-13).

    At most ``max_in_flight`` jobs (default 16) are submitted
    at any time; a new job is submitted only when a slot frees.
    Each future gets ``timeout_s`` from submission, so
    submitting every job up front would make each queued job
    "time out" once the run's wall time passed ``timeout_s`` --
    the 2026-11-16 inverted-null run (36,075 jobs, one pool
    call) tripped its breaker exactly 600 s after launch on
    stars that screen in ~0.7 s. The bounded window keeps a
    submitted job within ~one star's runtime of its actual
    start, so a timeout means the star's own screen hung, not
    that it waited in the queue. A star that has not returned
    by then is recorded as ``status="unmeasured"`` with a
    ``watchdog_timeout`` reason and the run moves on to the
    next star — a pathological star must never hang a whole
    slice. The late result, if it ever arrives, is ignored (the
    star is already accounted for). ``worker`` is _screen_one in
    production; tests pass a fake.

    Circuit breaker: consecutive watchdog timeouts are counted
    in collection order (a successful completion resets the
    count to 0); at ``max_consecutive_timeouts`` (default
    MAX_CONSECUTIVE_TIMEOUTS) the function raises
    CircuitBreakerError instead of recording another unmeasured
    star — the screen stops with a clear error rather than
    turning an outage into a hollow '0 survivors' slice.

    Caveat, stated plainly: with a ProcessPoolExecutor the hung
    worker process keeps running the star's BLS until it finishes
    (a worker cannot be killed mid-task), so executor shutdown
    still waits for it. BLS is finite compute — the watchdog's
    value is that the star is RECORDED as unmeasured and the
    other stars keep screening, instead of the slice hanging
    with no output at all. Returns (records, counts).
    """
    if max_consecutive_timeouts is None:
        max_consecutive_timeouts = MAX_CONSECUTIVE_TIMEOUTS
    if max_in_flight is None:
        max_in_flight = 16
    max_in_flight = max(1, max_in_flight)
    job_iter = iter(jobs)
    futures = {}
    records, counts = [], {}
    consecutive_timeouts = 0

    def _top_up():
        # Submit until the in-flight window is full or the
        # jobs run out (see the docstring: the watchdog's
        # submission-time clock is only honest if a submitted
        # job starts promptly).
        while len(futures) < max_in_flight:
            try:
                job = next(job_iter)
            except StopIteration:
                return
            futures[ex.submit(worker, job)] = (job, time.monotonic())

    _top_up()
    pending = set(futures)
    while pending:
        done, pending = _futures_wait(
            pending, timeout=timeout_s,
            return_when=FIRST_COMPLETED)
        for fut in done:
            rec = fut.result()
            del futures[fut]
            records.append(rec)
            counts[rec["status"]] = counts.get(rec["status"], 0) + 1
            # A success breaks the consecutive-timeout run.
            consecutive_timeouts = 0
        now = time.monotonic()
        for fut in list(pending):
            job, t0 = futures[fut]
            if now - t0 > timeout_s:
                pending.discard(fut)
                del futures[fut]
                tic, _path, sector, star = job
                rec = {"tic": tic, "sector": int(sector),
                       "product": PRODUCT,
                       "ra": star.get("ra"), "dec": star.get("dec"),
                       "tmag": star.get("tmag"),
                       "radius_rsun": star.get("radius"),
                       "status": "unmeasured",
                       "reason": ("watchdog_timeout: screen "
                                  f"exceeded {timeout_s:g}s")}
                records.append(rec)
                counts["unmeasured"] = counts.get("unmeasured", 0) + 1
                consecutive_timeouts += 1
                if consecutive_timeouts >= max_consecutive_timeouts:
                    raise CircuitBreakerError(
                        f"{consecutive_timeouts} consecutive "
                        f"watchdog timeouts (limit "
                        f"{max_consecutive_timeouts}) — the "
                        f"screen is timing out systematically, "
                        f"not on one pathological star; "
                        f"stopping the slice")
                log(f"star {tic}: WATCHDOG — screen exceeded "
                    f"{timeout_s:g}s, recorded unmeasured", logf)
        # Refill the in-flight window; `futures` now holds
        # exactly the live futures (done and timed-out ones
        # were removed above), so it is the next round's
        # pending set.
        _top_up()
        pending = set(futures)
    # Completion order is nondeterministic; sort by TIC so the
    # slice's output files are identical run to run (the old
    # ex.map loop preserved submission order).
    records.sort(key=lambda r: r["tic"])
    return records, counts


# --- SECTOR_EPOCH_CLUSTER veto (P3-15, bulk_v4) --------------------------

# Flag appended to every veto-cluster member (tier-B demoted,
# tier-A flagged). The flag names the veto; the disposition
# (tier-B only) names the verdict.
SECTOR_EPOCH_CLUSTER_FLAG = "SECTOR_EPOCH_CLUSTER"

# gate_reason value for TWO-COMBINED failures (set in
# _screen_one). Rows carrying it are v3-tier survivors the v4
# gate demoted — they join the veto's clustering input (see
# apply_epoch_cluster_veto).
GATE_REASON_TWO_COMBINED = "FAILED_TWO_COMBINED"


def _append_flag(rec, flag):
    """Append `flag` to rec["flags"] once (idempotent) —
    the veto is safe to re-apply to an already-flagged set."""
    flags = rec.get("flags")
    if flags is None:
        rec["flags"] = [flag]
    elif flag not in flags:
        flags.append(flag)


def apply_epoch_cluster_veto(survivors, hits=None, tol_p=None,
                             tol_t0_d=None, min_size=None,
                             demote_tier_a=None):
    """Apply the SECTOR_EPOCH_CLUSTER veto (P3-15, bulk_v4) to
    a sector's survivor set. Returns (kept_survivors, summary).

    `survivors`: the sector's survivor records (v3 tiers —
    the set the veto clusters). `hits`: the sector's full
    screen-hits records, or None; when given, the veto updates
    the hit copies in place (demoted rows carry the demotion
    there; flagged tier-A rows carry the flag there), so the
    merged screen_hits.jsonl stays consistent with the merged
    survivors.jsonl. Tolerances default to the profile-derived
    module globals (the P3-13 criterion). `demote_tier_a`
    defaults to the profile-derived EPOCH_CLUSTER_VETO_TIER_A
    (bulk_v5 True, earlier profiles False).

    Criterion (P3-13, implemented by replay_matrix's
    sector_epoch_cluster_tics — called here, not
    re-implemented): per sector, cluster (P, T0) within 1% /
    3 h (union-find); clusters of >20 stars are
    SECTOR_EPOCH_CLUSTER. Tier-B members are DEMOTED (status
    "demoted", disposition DEMOTED_SECTOR_EPOCH_CLUSTER, flag
    SECTOR_EPOCH_CLUSTER) and removed from the kept survivors.
    Tier-A members are DEMOTED too when demote_tier_a is true
    (bulk_v5, fixes round 1 — the S98 one-shot showed v4's
    flag-only treatment leaves 42.2% of the queue in the 13.7 d
    band) and FLAGGED (flag only) and kept otherwise (v4).
    Rows with no tier are neither (matches the replay).

    Clustering input: the v3-tier survivor set — the current
    survivors PLUS the TWO-COMBINED-demoted rows (still in
    hits with gate_reason FAILED_TWO_COMBINED).
    TWO-COMBINED runs at screen time, before the veto; without
    the demoted rows in the input, borderline clusters would
    shrink below the >20 bar and escape the veto — the P3-11
    replay clustered the full 4,692 v3 survivors, and the veto
    must see the same population. The demoted rows are
    clustering input only, never demotion targets (they are
    already demoted).

    P3-14 interaction (decision doc §6.1): P3-14 dispositions
    at screen time, per record; the veto dispositions at merge
    time, whole-set. The veto OVERWRITES a P3-14 disposition
    on a demoted row — the veto is the later, stronger verdict
    (the row is a cluster artifact, not a genuine single
    transit) — and the P3-14 finding survives in the row's
    grid_edge hand-off record. The reduction is counted once:
    the veto's demotion count includes the grid-edge singles
    it removes; the SINGLE_TRANSIT_POOL is defined over the
    surviving rows after the veto, so a veto-demoted single is
    not pool material.

    Chaining (decision doc §6.2): union-find chaining can link
    sparse rows into one wide cluster (clusters 8/11/10 in the
    replay). A cluster-diameter cap was CONSIDERED and NOT
    adopted here — the P3-13 criterion is measured as
    specified, not re-tuned in this step; the cap is recorded
    for 3.1.

    Merge-only, never per-slice: clusters span slices, so a
    per-slice veto would under-demote (a 25-star sector
    cluster split 21/4 across slices would keep the 4). The
    caller is run_chunked's merge (and only the merge — a
    direct bulk_screen.py run does not apply the veto; see the
    bulk_v4 profile header). Demotion is reversible: demoted
    rows keep their disposition and stay queryable in
    screen_hits.jsonl; the manual-review ("unsure") queue is
    disposition == DEMOTED_SECTOR_EPOCH_CLUSTER OR gate_reason
    present. Nothing is deleted anywhere.
    """
    if tol_p is None:
        tol_p = EPOCH_CLUSTER_TOL_P
    if tol_t0_d is None:
        tol_t0_d = EPOCH_CLUSTER_TOL_T0_D
    if min_size is None:
        min_size = EPOCH_CLUSTER_MIN_SIZE
    if demote_tier_a is None:
        demote_tier_a = EPOCH_CLUSTER_VETO_TIER_A
    cluster_rows = list(survivors)
    if hits is not None:
        survivor_tics = {r["tic"] for r in survivors}
        cluster_rows += [r for r in hits
                         if r.get("gate_reason")
                         == GATE_REASON_TWO_COMBINED
                         and r["tic"] not in survivor_tics]
    # Rows without (P, T0) cannot be shown to share an epoch —
    # they stay unclustered (kept). Survivors always carry
    # both; this is defence against malformed input, not a code
    # path production reaches.
    clusterable = [r for r in cluster_rows
                   if r.get("period_days") is not None
                   and r.get("t0_btjd") is not None]
    clustered, clusters = _sector_epoch_cluster_tics(
        clusterable, tol_p=tol_p, tol_t0_d=tol_t0_d, min_size=min_size)
    hits_by_tic = {}
    if hits is not None:
        for r in hits:
            hits_by_tic.setdefault(r["tic"], r)
    kept = []
    demoted_tier_b_tics = []
    demoted_tier_a_tics = []
    flagged_tics = []

    def _demote(r):
        hit = hits_by_tic.get(r["tic"])
        target = hit if hit is not None else r
        target["status"] = "demoted"
        target["disposition"] = (
            _search_health.DEMOTED_SECTOR_EPOCH_CLUSTER)
        _append_flag(target, SECTOR_EPOCH_CLUSTER_FLAG)

    for r in survivors:
        if r["tic"] not in clustered:
            kept.append(r)
            continue
        if r.get("tier") == "A" and not demote_tier_a:
            _append_flag(r, SECTOR_EPOCH_CLUSTER_FLAG)
            hit = hits_by_tic.get(r["tic"])
            if hit is not None and hit is not r:
                _append_flag(hit, SECTOR_EPOCH_CLUSTER_FLAG)
            flagged_tics.append(r["tic"])
            kept.append(r)
        elif r.get("tier") == "A":
            _demote(r)
            demoted_tier_a_tics.append(r["tic"])
        elif r.get("tier") == "B":
            _demote(r)
            demoted_tier_b_tics.append(r["tic"])
        else:
            # No tier: not a veto target (matches the replay).
            kept.append(r)
    summary = {
        "n_clusters": len(clusters),
        "cluster_sizes": sorted((len(c) for c in clusters),
                                reverse=True),
        # P4-2 (IB-3): cluster identity + membership, explicitly
        # recorded. cluster_id is the rank in largest-first
        # order (0 = largest); members are the cluster's TICs,
        # sorted. Deterministic: the union-find input order is
        # the survivor order and the output is sorted.
        "clusters": [{"cluster_id": i, "size": len(c),
                      "members": sorted(c)}
                     for i, c in enumerate(clusters)],
        "n_clustered": len(clustered),
        "demoted_tier_b": len(demoted_tier_b_tics),
        "demoted_tier_a": len(demoted_tier_a_tics),
        "flagged_tier_a": len(flagged_tics),
        "demoted_tics": sorted(demoted_tier_b_tics
                               + demoted_tier_a_tics),
        "flagged_tics": sorted(flagged_tics),
    }
    return kept, summary


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
    ap.add_argument("--target-list", action="store_true",
                    help="build the star list from the sector's QLP "
                         "target list + batched TIC lookups (cached)")
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
    ap.add_argument("--run-id", default=None,
                    help="run id stamped on every record (default: "
                         "auto-generated; the chunked driver passes "
                         "one id for the whole run so all slices "
                         "share it)")
    ap.add_argument("--recipe-hash", default=None,
                    help="sha256 of the resolved recipe driving this "
                         "run (the chunked driver passes it); "
                         "omitted when the run had no recipe")
    ap.add_argument("--mixed-pipeline", action="store_true",
                    help="stamp mixed_pipeline=true on every record "
                         "(A-3): the chunked driver passes this when "
                         "the run resumed across a result-affecting "
                         "code change under --accept-code-change")
    ap.add_argument("--calibration", default="bulk_v1",
                    help="bulk calibration profile (default: bulk_v1; "
                         "bulk_v2 fixes the MAD-clip defect)")
    ap.add_argument("--event-guard", type=float, default=None,
                    help="event-count guard in days (P4-2 "
                         "measurement seam; default: the profile "
                         "value, 0.0)")
    ap.add_argument("--allow-v1", action="store_true",
                    help="allow screening a sector outside 96-98 "
                         "under bulk_v1 (known MAD-clip defect — "
                         "prefer --calibration bulk_v2)")
    args = ap.parse_args(argv)

    # Calibration selection + the v1 gate (B-2) — before any work:
    # a refused run must not download anything or write records.
    try:
        set_calibration(args.calibration)
        enforce_v1_gate(args.calibration, args.sector, args.allow_v1)
        if args.event_guard is not None:
            set_event_guard(args.event_guard)
    except (_CalibrationError, ValueError) as exc:
        ap.error(str(exc))

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    logf = open(out_dir / "run.log", "a")
    run_t0 = time.time()
    # Provenance, built once for the whole run (Phase 1.1, item 1):
    # one run id, one timestamp, one calibration version — every
    # record this run writes carries the same header.
    run_id = args.run_id or _prov.new_run_id("bulk")
    started_at = _prov.utc_now_iso()
    prov = _prov.provenance_header(
        run_id, CALIBRATION_MAP,
        recipe_hash=args.recipe_hash,
        timestamp_utc=started_at,
        mixed_pipeline=args.mixed_pipeline)
    # C-2: the run-level components of every record's work-item
    # id (TIC + sector vary per record; these three are fixed for
    # the run). Computed once — fingerprint_result_affecting walks
    # the repo tree.
    _code_fp = _prov.fingerprint_result_affecting()
    try:
        _cal_hash = _prov.calibration_content_hash(CALIBRATION_MAP)
    except Exception:
        _cal_hash = None

    def _stamp_work_item_id(rec):
        """Stamp the deterministic work-item id (C-2) on an
        emitted record, in place."""
        rec["work_item_id"] = _prov.work_item_id(
            rec["tic"], args.sector, _code_fp, _cal_hash,
            args.recipe_hash)
        return rec
    manifest = _prov.build_manifest(
        run_id, CALIBRATION_MAP, sector=args.sector,
        product=PRODUCT, sha=prov["pipeline_git_sha"],
        timestamp_utc=started_at, status="started",
        code_fingerprint=_code_fp)
    _prov.write_manifest(out_dir, manifest)
    log(f"run_id: {run_id} (calibration {CALIBRATION_VERSION}, "
        f"git {prov['pipeline_git_sha']})", logf)
    summary = {"tool": "bulk_screen v1.2", "sector": args.sector,
               "product": PRODUCT,
               "provenance": prov,
               "window": {"min_mag": args.min_mag, "max_mag": args.max_mag,
                          "min_rad": args.min_rad, "max_rad": args.max_rad},
               "thresholds": {"record_floor_sde": RECORD_FLOOR_SDE,
                              "survivor_sde": SURVIVOR_SDE,
                              "depth_min_pct": DEPTH_MIN_PCT,
                              "depth_eb_pct": DEPTH_EB_PCT,
                              "clip_option": CLIP_OPTION,
                              "period_range_d": [MIN_PERIOD_D,
                                                 MAX_PERIOD_D],
                              "tier_a_mes": TIER_A_MES,
                              "tier_a_min_events": TIER_A_MIN_EVENTS,
                              "tier_a_min_strong": TIER_A_MIN_STRONG,
                              "tier_b_event_snr": TIER_B_EVENT_SNR,
                              "tier_b_max_depth_pct": TIER_B_MAX_DEPTH_PCT,
                              "event_guard_d": EVENT_GUARD_D,
                              "event_gap_d": EVENT_GAP_D,
                              "event_min_coverage": EVENT_MIN_COVERAGE,
                              "event_min_cadences": EVENT_MIN_CADENCES},
               "control_tic": args.control_tic}

    # 1 — star list ------------------------------------------------------
    if args.target_list:
        stars, tl_stats = target_list_star_list(
            args.sector, args.min_mag, args.max_mag, args.min_rad,
            args.max_rad, args.cache_dir, logf)
        summary["target_list"] = tl_stats
    elif args.stars_file:
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
    # P4-2: the pool initializer propagates the calibration (+
    # event-guard override) to each worker — without it, spawn
    # workers (macOS) re-import this module and fall back to
    # bulk_v1 regardless of --calibration (PB-2, proven
    # 2026-11-17).
    with ProcessPoolExecutor(max_workers=args.workers,
                             initializer=_init_worker,
                             initargs=(args.calibration,
                                       args.event_guard)) as ex:
        # C-1: per-star watchdog — a pathological star is recorded
        # unmeasured instead of hanging the slice. F-13: the
        # circuit breaker stops the slice on systematic timeouts
        # — no summary is written, so the slice is not
        # checkpointed and the driver stops the run.
        try:
            records, counts = _collect_screen_results(
                ex, jobs, _screen_one, _net.STAR_TIMEOUT_S, logf,
                max_in_flight=2 * args.workers)
        except CircuitBreakerError as exc:
            log(f"CIRCUIT BREAKER: {exc}", logf)
            log("slice NOT checkpointed (no summary written) — "
                "the driver will stop the run rather than merge "
                "a hollow result", logf)
            logf.close()
            return 1
    screen_seconds = time.time() - t
    summary["screen_seconds"] = screen_seconds
    summary["screen_counts"] = counts
    summary["stars_searched"] = len(jobs)
    # F-13: stars MEASURED (searched minus watchdog timeouts) is
    # the number to quote as "N screened" — a run that timed out
    # on half its stars did not screen them.
    summary["stars_measured"] = (
        len(jobs) - counts.get("unmeasured", 0))
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

    # Atomic writes (Phase 1.1, item 8): a VM kill mid-write must
    # never leave a truncated survivors/hits file behind — the
    # chunk checkpoint (summary.json, written last) is only valid
    # if the files it describes are complete.
    with _atomic_writer(out_dir / "survivors.jsonl") as fh:
        for r in novel:
            rec = emit_survivor_record(r, prov)
            _stamp_work_item_id(rec)
            # Fail loud on a malformed record (Phase 1.1, item 3):
            # a bad record is a code bug, and the run must stop,
            # not write a corrupt handoff to the gauntlet.
            _validate_survivor(rec)
            fh.write(json.dumps(rec) + "\n")
    with _atomic_writer(out_dir / "screen_hits.jsonl") as fh:
        for r in hits:
            rec = emit_survivor_record(r, prov)
            _stamp_work_item_id(rec)
            _validate_survivor(rec)
            fh.write(json.dumps(rec) + "\n")

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
    _atomic_write_json(out_dir / "summary.json", summary)
    manifest["execution"]["status"] = "completed"
    manifest["execution"]["wall_seconds"] = round(
        summary["wall_seconds"])
    manifest["counts"] = {
        "stars_searched": summary["stars_searched"],
        "stars_measured": summary["stars_measured"],
        "hits_recorded": summary["hits_recorded"],
        "survivors": summary["survivors"],
        "screen_counts": summary["screen_counts"],
    }
    _prov.write_manifest(out_dir, manifest)
    log(f"DONE: {len(novel)} novel survivors, {len(hits)} recorded hits, "
        f"wall {summary['wall_seconds']:.0f}s, end-to-end "
        f"{summary.get('end_to_end_stars_per_hour', 0)} stars/h", logf)
    logf.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
