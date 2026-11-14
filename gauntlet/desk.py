"""Desk driver (Phase 2, 2A) — the vetting-manual desk checks,
automated into the A-5 stage runner.

The manual gauntlet (docs/vetting-manual.md §0-§9) ran by hand:
census25.py for the catalogue check, rawflux_check.py + a phase
scan for the desk folds, flagcheck.py for the clean-data test,
tesscut_fetch + diffimg for imaging, transit_fit for the formal
fit, and a human verdict at the end. This module is the layer
the A-5 runner was built for: it produces the runner's natives
by invoking the existing gauntlet tools, in manual order, then
runs the runner and builds the verdict record.

Two passes, matching the runner's DAG: the cheap stages first
(catalogue, clean_refold, refine, raw_flux, persistence, shape,
odd_even, blend, pixel_check). A FAIL at any cheap stage ends
the run — the expensive natives (holdout, diffimg, transit_fit)
are never produced, exactly as the manual gauntlet stopped at
the first kill. Only a cheap-pass survivor pays for the
expensive stages.

Data comes through a DeskDataSource: LiveDataSource downloads
from MAST and shells out to the diffimg / transit_fit CLIs;
tests substitute a fake that serves synthetic arrays and canned
tool outputs. The native builders in this module are pure
functions on arrays — they are the testable core, and the
18 flagged-cadence artifacts of the 2026-11-14 rescore gauntlet
are their regression material (a signal living only in flagged
cadences must die at the clean re-fold gate).

Known gaps (documented, not hidden):
  * holdout re-runs the pipeline (holdout_test.holdout_test
    calls hunter._run_pipeline internally) instead of reusing
    the driver's fetched arrays — an array-based holdout is a
    follow-up, not a 2A blocker;
  * the P/2 alias test and the phase-0.5 secondary fold are
    recorded as evidence in desk_natives.json, not as stage
    criteria — the manual gives no numeric kill threshold for
    them (open question for the Phase 2 vote);
  * transit_fit runs on QLP sectors only (its loader reads
    qlp_sNNN.npz); TESSCut-sector fits need tesscut_extract
    wired in (follow-up);
  * the diffimg on-target bar (1 px) and the pixel-check bars
    are judgment calls recorded in PHASE_2_PROGRESS.md.
"""
import hashlib
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field

import numpy as np

from gauntlet.census import (brightest_neighbour, catalogue_native,
                             run_census)
from gauntlet.common import (event_parity_depths, flatten_transit_masked,
                             fold_depth, load_tpf)
from gauntlet.evidence import build_evidence_package
from gauntlet.external_tool import (build_tool_input,
                                    run_external_tool, sha256_file)
from gauntlet.pixel_check import pixel_check_native
from gauntlet.refine import refine_native
from gauntlet.runner import (Ephemeris, TargetContext, run_gauntlet)
from gauntlet.stage_result import (EXEC_ERROR, STATUS_UNMEASURED,
                                   StageResult, latte_result,
                                   triceratops_result)
from gauntlet.verdict import build_verdict

CLEAN_GATE_SIGMA_MIN = 3.0
SEGMENT_GAP_D = 1.0
SEGMENT_MIN_SIGNIF = 1.5
DIFFIMG_ON_TARGET_PX = 1.0
TESS_ARCSEC_PER_PX = 21.0
R_SUN_OVER_R_EARTH = 109.2
RHO_SUN_G_CM3 = 1.408
SUBPROCESS_TIMEOUT_S = 1800
MAX_DIFFIMG_SECTORS = 6


@dataclass
class Survivor:
    """A bulk-screen survivor (or an ad-hoc target) to vet."""
    tic: str
    period_d: float
    t0_btjd: float
    duration_h: float
    depth_pct: float
    sde: float = None
    sector: int = None          # discovery sector (clean gate, TPF)
    bulk_survivor: bool = True
    n_events: int = None


# ---------------------------------------------------------------------------
# Pure native builders (offline-testable)
# ---------------------------------------------------------------------------

def count_events(t, period, t0, duration_d):
    """Distinct transit events with in-transit points."""
    t = np.asarray(t, dtype=float)
    ph = ((t - t0 + 0.5 * period) % period) - 0.5 * period
    in_tr = np.abs(ph) <= duration_d / 2
    if not in_tr.any():
        return 0
    return int(len(np.unique(np.round((t[in_tr] - t0) / period))))


def _flagged_fold(t, f, q, period, t0, dur_h):
    """The flagcheck fold: do the FLAGGED cadences carry a dip?
    The flagged in-transit median is measured against the CLEAN
    out-of-transit baseline (the star's normal flux) — the
    flagged cadences alone may have no out-of-transit points
    at all (in the rescore artifacts, every flagged cadence
    sat inside a transit window). Returns the clean_fold dict
    shape (n_in / n_events count flagged in-transit cadences).
    """
    from bulk.clean_refold_gate import mad_sigma
    t = np.asarray(t, dtype=float)
    f = np.asarray(f, dtype=float)
    q = np.asarray(q)
    m = np.isfinite(t) & np.isfinite(f) & (f > 0)
    t, f, q = t[m], f[m], q[m]
    phase = ((t - t0) / period + 0.5) % 1.0 - 0.5
    dur_frac = dur_h / 24.0 / period
    in_tr = np.abs(phase) < dur_frac / 2
    clean_out = (q == 0) & ~in_tr
    flagged_in = (q != 0) & in_tr
    n_in = int(flagged_in.sum())
    ev = np.unique(np.floor((t[flagged_in] - t0) / period).astype(int)) \
        if n_in else []
    out = {"n_clean": int((q == 0).sum()), "n_in": n_in,
           "n_events": int(len(ev)),
           "depth_percent": None, "snr": None}
    if n_in < 2 or clean_out.sum() < 10:
        return out
    base = np.median(f[clean_out])
    depth = 1 - np.median(f[flagged_in]) / base
    sig = (mad_sigma(f[clean_out]) * 1.2533 / np.sqrt(n_in)
           / base)
    out["depth_percent"] = float(depth * 100)
    out["snr"] = float(depth / sig) if sig and np.isfinite(sig) else None
    return out


def clean_refold_native(t, f, q, period, t0, dur_h,
                        sigma_min=CLEAN_GATE_SIGMA_MIN):
    """The clean-data re-fold gate (manual §1) on one sector's
    light curve with quality flags. Returns the (fold, verdict)
    tuple the clean_refold adapter takes.

    Three-way, mirroring the manual flagcheck: the clean fold
    (quality==0) decides PASS/FAIL when it has enough cadences.
    When it does not (INSUFFICIENT), the flagged-only fold is
    tested — if the flagged cadences alone carry a significant
    dip, the signal lives only in flagged cadences and the
    verdict is FAIL, not INSUFFICIENT. That is the decisive
    test for the flagged-cadence artifact class (18 of the 25
    rescore leads had ZERO clean in-transit cadences — a bare
    clean_fold would read them INSUFFICIENT and let them
    through as unvetted). The bulk gate CLI keeps its current
    verdict_for behaviour; this stricter rule lives in the
    driver, which has the full quality-flagged light curve."""
    from bulk.clean_refold_gate import (MIN_EVENTS, MIN_IN,
                                        clean_fold, verdict_for)
    t = np.asarray(t, dtype=float)
    f = np.asarray(f, dtype=float)
    q = np.asarray(q)
    fold = clean_fold(t, f, q, period, t0, dur_h)
    verdict = verdict_for(fold, sigma_min)
    if verdict == "INSUFFICIENT":
        flagged = _flagged_fold(t, f, q, period, t0, dur_h)
        if (flagged["n_in"] >= MIN_IN
                and flagged["n_events"] >= MIN_EVENTS
                and flagged["snr"] is not None
                and flagged["snr"] >= sigma_min):
            verdict = "FAIL"
            fold = dict(fold)
            fold["flagged_fold"] = flagged
    return fold, verdict


def raw_flux_native(t, f, period, t0, duration_d):
    """fold_depth on unflattened flux + the event count the
    raw_flux adapter's min_events check needs. fold_depth
    returns None when too few points are in transit — the
    adapter reads that as UNMEASURED via the n_in check, so the
    fold dict is still built (with None depth)."""
    fold = fold_depth(t, f, period, t0, duration_d)
    n_in = 0
    t = np.asarray(t, dtype=float)
    ph = ((t - t0 + 0.5 * period) % period) - 0.5 * period
    n_in = int((np.abs(ph) <= duration_d / 2).sum())
    n_ev = count_events(t, period, t0, duration_d)
    if fold is None:
        return {"depth_pct": None, "signif_white": None,
                "signif_red": None, "n_in": n_in, "n_events": n_ev}
    fold = dict(fold)
    fold["n_events"] = n_ev
    return fold


def shape_native(t, f, period, t0, duration_d, rho_star):
    """trapezoid_shape_gate, wrapped so a fit exception reads
    UNMEASURED instead of killing the run."""
    from gauntlet.rawflux_check import trapezoid_shape_gate
    try:
        return trapezoid_shape_gate(t, f, period, t0, duration_d,
                                    rho_star)
    except Exception as e:
        return {"verdict": "unmeasured",
                "reason": f"shape gate failed: {type(e).__name__}: {e}",
                "shape_verdict": "unmeasured"}


def odd_even_native(t, f, period, t0, duration_d):
    """event_parity_depths + the desk_finish evidence folds:
    the P/2 alias fold and the phase-0.5 secondary fold. Returns
    (odd, even, extra) — the runner native is (odd, even); extra
    is evidence for desk_natives.json, not a stage criterion."""
    odd, even = event_parity_depths(t, f, period, t0, duration_d)
    extra = {}
    half = fold_depth(t, f, period / 2.0, t0, duration_d)
    if half is not None:
        extra["half_period_fold"] = {
            "depth_pct": half["depth_pct"],
            "signif_white": half["signif_white"],
            "n_in": half["n_in"]}
    sec = fold_depth(t, f, period, t0, duration_d, centre_phase=0.5)
    if sec is not None:
        extra["secondary_phase0.5_fold"] = {
            "depth_pct": sec["depth_pct"],
            "signif_white": sec["signif_white"],
            "n_in": sec["n_in"]}
    return odd, even, extra


def persistence_native(t, f, period, t0, duration_d):
    """Fold the dip per time-gap segment (sector approximation).
    CONSISTENT when every usable segment shows the dip at >=1.5
    sigma; MIXED otherwise; no verdict when no segment is
    usable (UNMEASURED). Generalised from
    scripts/toi_population.py:_persistence_native (F-8) — the
    F-8 copy is left untouched so its baseline stays frozen
    evidence."""
    t = np.asarray(t, dtype=float)
    order = np.argsort(t)
    t, f = t[order], np.asarray(f, dtype=float)[order]
    breaks = np.where(np.diff(t) > SEGMENT_GAP_D)[0] + 1
    segments = np.split(np.arange(len(t)), breaks)
    usable = 0
    all_show = True
    for idx in segments:
        if len(idx) < 50:
            continue
        fold = fold_depth(t[idx], f[idx], period, t0, duration_d)
        if fold is None:
            continue
        usable += 1
        if fold["depth_pct"] <= 0 \
                or fold["signif_white"] < SEGMENT_MIN_SIGNIF:
            all_show = False
    if usable == 0:
        return {"n_usable": 0}
    return {"verdict": "CONSISTENT" if all_show else "MIXED",
            "n_usable": usable}


def dip_free_neighbour(t, f, period, t0, duration_d):
    """The target flux with in-transit points replaced by the
    out-of-transit median: a neighbour that provably does not
    show the dip (the F-1 no-false-kill control). Used as the
    blend native only when the 180\" cone has NO neighbour to
    test — a real neighbour is always folded for real."""
    t = np.asarray(t, dtype=float)
    f = np.asarray(f, dtype=float)
    n_ev = np.round((t - t0) / period)
    dt = t - (t0 + n_ev * period)
    in_tr = np.abs(dt) < duration_d / 2.0
    out = f.copy()
    out[in_tr] = np.median(f[~in_tr])
    return out


def rho_star_from_census(target):
    """Stellar density in SOLAR units from a census TIC row
    (mass / radius^3) — the units trapezoid_shape_gate expects
    (its rho_star_solar field; cf. rawflux_check.tic_density).
    None when mass or radius is missing."""
    if not target:
        return None
    mass, rad = target.get("mass"), target.get("rad")
    if mass is None or rad is None or rad <= 0:
        return None
    return float(mass) / float(rad) ** 3


def rho_circ_from_fit(period_d, a_over_rstar):
    """Circular-orbit stellar density implied by a transit fit
    (Kepler's third law): rho = 3 pi (a/R*)^3 / (G P^2)."""
    G_CGS = 6.67430e-8
    p_s = float(period_d) * 86400.0
    return 3.0 * np.pi * float(a_over_rstar) ** 3 / (G_CGS * p_s ** 2)


def diffimg_native_for(results, blend_host_tic=None):
    """diffimg_results.json -> the diffimg adapter native.

    diffimg.py writes maps and centroids but no on-target
    verdict — the driver derives it from the WCS-aligned stack
    centroid: on-target when the centroid sits within 1 TESS
    pixel (21\") of the target AND closer to the target than to
    the neighbour. The 1-px bar is a judgment call (the manual
    gives no number; the 423498314 on-target case was 0.06 px).
    No stack centroid -> on_target None -> UNMEASURED."""
    if not results:
        return None
    stack = results.get("stack") or {}
    d_t = stack.get("dist_to_target_px")
    d_n = stack.get("dist_to_neighbour_px")
    n_sectors = len(results.get("sectors") or {})
    if d_t is None:
        return {"on_target": None, "offset_px": None,
                "offset_arcsec": None, "blend_host_tic": None,
                "n_sectors": n_sectors}
    on_target = bool(d_t < DIFFIMG_ON_TARGET_PX
                     and (d_n is None or d_t < d_n))
    return {"on_target": on_target,
            "offset_px": float(d_t),
            "offset_arcsec": float(d_t) * TESS_ARCSEC_PER_PX,
            "blend_host_tic": (None if on_target
                               else blend_host_tic),
            "n_sectors": n_sectors}


def transit_fit_native_for(ls_fit, r_star_rsun, rho_star):
    """ls_fit.json (transit_fit ls stage) -> the transit_fit
    adapter native. theta_ls is [P, T0, rp, a, b, q1, q2] with
    rp in stellar radii and a in a/R*. The density flag uses
    the policy's density_ratio_min bar (0.80, gauntlet_v2):
    rho_circ/rho_star < 0.80 means the fitted duration is
    impossible for a planet on this star. Returns None when the
    fit record is unusable (no converged fit -> UNMEASURED)."""
    if not ls_fit:
        return None
    theta = ls_fit.get("theta_ls")
    if not theta or len(theta) < 5:
        return None
    try:
        p_fit, _t0, rp, a, b = (float(v) for v in theta[:5])
    except (TypeError, ValueError):
        return None
    if not all(np.isfinite(v) for v in (p_fit, rp, a, b)):
        return None
    if r_star_rsun is None or r_star_rsun <= 0:
        return None
    from gauntlet.transit_fit import t14_days
    rp_re = rp * float(r_star_rsun) * R_SUN_OVER_R_EARTH
    try:
        t14_h = float(t14_days(p_fit, rp, a, b)) * 24.0
    except Exception:
        t14_h = None
    density_flag = False
    if rho_star is not None and rho_star > 0 and a > 0:
        # rho_star is in solar units (rho_star_from_census);
        # rho_circ_from_fit returns g/cm3, so convert.
        rho_circ = rho_circ_from_fit(p_fit, a) / RHO_SUN_G_CM3
        density_flag = bool(rho_circ / rho_star < 0.80)
    return {"b": float(b), "rp_re": float(rp_re),
            "t14_h": t14_h, "density_flag": density_flag,
            "converged": True,
            "chi2": ls_fit.get("chi2"),
            "npts": ls_fit.get("npts")}


def external_tool_sections(tic, target, period_d, t0, duration_h,
                           depth_pct, t, f, sectors, pfx, census,
                           workdir):
    """The C-10 external-tool input sections from the driver's
    data. Writes the stitched light curve to
    workdir/tool_lc.npz (time/flux) and the census to
    workdir/stage0_census.json when it is not already there,
    and hashes both. Returns (sections, ffi_mode) where
    sections carries target/signal/lightcurve/neighbours and
    ffi_mode says whether LATTE must run in FFI mode (any
    light curve that is not SPOC 2-minute data). Raises
    ValueError when required data is missing — the driver
    catches it per tool and records the error, never a run
    kill."""
    if target is None:
        raise ValueError("no census target row")
    missing = [k for k in ("ra", "dec", "Tmag", "rad", "Teff",
                           "mass")
               if target.get(k) is None]
    if missing:
        raise ValueError(
            f"census target row lacks {', '.join(missing)}")
    if depth_pct is None:
        raise ValueError("no filed depth for the tool input")
    t = np.asarray(t, dtype=float)
    f = np.asarray(f, dtype=float)
    if len(t) < 2:
        raise ValueError("stitched light curve has < 2 points")
    cadence_s = float(np.median(np.diff(t))) * 86400.0
    if not np.isfinite(cadence_s) or cadence_s <= 0:
        raise ValueError("stitched light curve has no cadence")
    sectors = [int(s) for s in (sectors or [])]
    if not sectors:
        raise ValueError("stitched light curve has no sectors")
    lc_path = os.path.join(workdir, "tool_lc.npz")
    np.savez(lc_path, time=t, flux=f)
    census_path = os.path.join(workdir, "stage0_census.json")
    if not os.path.exists(census_path):
        if census is None:
            raise ValueError("no census record for the tool "
                             "input")
        with open(census_path, "w") as fh:
            json.dump(census, fh)
    duration_d = float(duration_h) / 24.0
    sections = {
        "target": {
            "tic": str(tic), "ra_deg": float(target["ra"]),
            "dec_deg": float(target["dec"]),
            "tmag": float(target["Tmag"]),
            "star_radius_rsun": float(target["rad"]),
            "star_mass_msun": float(target["mass"]),
            "teff_k": float(target["Teff"])},
        "signal": {
            "period_d": float(period_d), "t0_bjd": float(t0),
            "duration_h": float(duration_h),
            "depth_frac": float(depth_pct) / 100.0,
            "n_transits": count_events(t, period_d, t0,
                                       duration_d)},
        "lightcurve": {
            "path": lc_path, "input_hash": sha256_file(lc_path),
            "sectors": sectors, "cadence_s": cadence_s},
        "neighbours": {
            "path": census_path,
            "input_hash": sha256_file(census_path),
            "radius_arcsec": 180.0},
    }
    return sections, (pfx != "spoc")


# Output-JSON adapters per external tool (stage_result.py).
_TOOL_ADAPTERS = {"latte": latte_result,
                  "triceratops": triceratops_result}

# Light-curve products whose stitched flux is already
# dilution-corrected: lightkurve's default flux column is
# PDCSAP for SPOC/TESS-SPOC and KSPSAP for QLP (pinned by
# lightkurve 2.6.0 in requirements.lock). TRICERATOPS needs
# the flag to match — it corrects internally when False.
DILUTION_CORRECTED_PRODUCTS = ("spoc", "tspc")


def _run_external_tools(configs, tic, census, period_d, t0,
                        duration_h, survivor, t, f, stitched,
                        workdir, prov, extra):
    """Run each configured external tool and record its
    StageResult (as a dict) in extra[\"external_tools\"] and
    its raw output JSON in extra[\"external_tools_raw\"].
    Evidence only — the results are never fed to
    aggregate_verdict (see PHASE_2_PROGRESS.md, 2B judgment
    calls 2–3). Never raises: a per-tool failure is recorded
    in extra[\"<tool>_error\"] and the run continues."""
    if census is None or census.get("target") is None:
        extra["external_tools_error"] = (
            "no census target row: external tools need "
            "ra/dec/Tmag/radius/mass/Teff")
        return
    for tool, config in configs.items():
        adapter = _TOOL_ADAPTERS.get(tool)
        if adapter is None:
            extra[f"{tool}_error"] = (
                f"no adapter registered for tool {tool!r}")
            continue
        try:
            sections, ffi_mode = external_tool_sections(
                tic, census["target"], period_d, t0, duration_h,
                survivor.depth_pct, t, f,
                stitched.get("sectors"), stitched.get("pfx"),
                census, workdir)
            inp = build_tool_input(
                tool, config.tool_version, config.seed,
                config.config_hash, sections["target"],
                sections["signal"], sections["lightcurve"],
                sections["neighbours"],
                contrast_curve=(False if tool == "latte"
                                else None),
                timeout_s=config.timeout_s)
            if tool == "latte":
                inp["ffi_mode"] = ffi_mode
            if tool == "triceratops":
                inp["dilution_corrected"] = (
                    stitched.get("pfx")
                    in DILUTION_CORRECTED_PRODUCTS)
            res = run_external_tool(
                config, inp,
                os.path.join(workdir, f"tool-{tool}"))
        except Exception as exc:  # noqa: BLE001 - per-tool
            extra[f"{tool}_error"] = (
                f"{type(exc).__name__}: {exc}")
            continue
        if res.status == "completed":
            try:
                result = adapter(res.output, prov)
            except Exception as exc:  # noqa: BLE001 - the
                # adapter must not kill the run either.
                result = StageResult(
                    tool, STATUS_UNMEASURED,
                    f"adapter raised {type(exc).__name__}: {exc}",
                    dict(prov), {},
                    execution_status=EXEC_ERROR)
            extra.setdefault("external_tools_raw",
                             {})[tool] = res.output
        else:
            result = StageResult(
                tool, STATUS_UNMEASURED,
                f"external tool {tool}: {res.status} — "
                f"{res.stderr_tail}",
                dict(prov), {},
                execution_status=EXEC_ERROR)
        extra.setdefault("external_tools", {})[tool] = (
            result.to_dict())


# ---------------------------------------------------------------------------
# Data sources
# ---------------------------------------------------------------------------

class DeskDataSource:
    """What the desk driver needs from the world. Methods return
    None when the data is unavailable (the stage then reads
    UNMEASURED) instead of raising — a failed download is not a
    scientific verdict. Subclasses may raise only for
    programmer errors."""

    def census(self, tic, period, workdir):
        raise NotImplementedError

    def discovery_lc(self, tic, sector):
        """(t, f, q) for the discovery sector, UNMASKED (the
        clean gate needs the quality flags)."""
        raise NotImplementedError

    def stitched_lc(self, tic, workdir):
        """{"pfx", "sectors", "t", "f", "spans"} — the selected
        pipeline set's stitched raw flux (quality==0, 10%
        MAD-clip floor, as in rawflux_check.load_stitched)."""
        raise NotImplementedError

    def neighbour_lc(self, tic, workdir):
        """(t, f) stitched neighbour flux, median-normalised."""
        raise NotImplementedError

    def tesscut(self, tic, sectors, workdir, ra, dec, neighbour):
        """Fetch TESSCut cutouts + identity. Returns
        (tesscut_dir, identity_path) or None. neighbour is a
        census cone row or None."""
        raise NotImplementedError

    def holdout(self, tic, period, t0, duration_h, star_radius=1.0):
        """The holdout verdict string (HOLDOUT-PASS/FAIL/
        INSUFFICIENT-DATA)."""
        raise NotImplementedError

    def diffimg(self, tic, period, t0, duration_d, workdir,
                census_path, depth_pct):
        """diffimg_results.json content (dict) or None."""
        raise NotImplementedError

    def transit_fit(self, tic, period, t0, duration_d, workdir,
                    qlp_sectors, r_star, r_star_err, m_star,
                    m_star_err, depth_pct):
        """ls_fit.json content (dict) or None."""
        raise NotImplementedError


class LiveDataSource(DeskDataSource):
    """The real tools: MAST downloads + the diffimg /
    transit_fit CLIs as subprocesses."""

    def __init__(self, repo_root=None, python=None):
        self.repo_root = repo_root or os.path.dirname(
            os.path.dirname(os.path.abspath(__file__)))
        self.python = python or sys.executable

    def census(self, tic, period, workdir):
        return run_census(tic, period, workdir)

    def discovery_lc(self, tic, sector):
        if sector is None:
            return None
        # Cache first: the bulk screen's cached FITS is the exact
        # data the screen saw (no re-download, no drift).
        from bulk.clean_refold_gate import load_fits
        cache = os.path.join(self.repo_root, "bulk", "cache",
                             f"s{int(sector):04d}", f"{tic}.fits")
        if os.path.exists(cache):
            t, f, q, _col = load_fits(cache)
            m = np.isfinite(t) & np.isfinite(f)
            return t[m], f[m], q[m]
        import lightkurve as lk
        import netbound as _net
        try:
            sr = _net.mast_call(
                lambda: lk.search_lightcurve(
                    f"TIC {tic}", author="QLP", sector=int(sector)),
                name=f"desk discovery search TIC {tic} s{sector}")
        except Exception:
            return None
        if len(sr) == 0:
            return None
        try:
            lc = _net.mast_call(
                lambda: sr[0].download(),
                name=f"desk discovery download TIC {tic} s{sector}")
        except Exception:
            return None
        if lc is None:
            return None
        t = np.asarray(lc.time.value, dtype=float)
        f = np.asarray(lc.flux.value, dtype=float)
        q = np.asarray(lc.quality)
        m = np.isfinite(t) & np.isfinite(f)
        return t[m], f[m], q[m]

    def stitched_lc(self, tic, workdir):
        from gauntlet import rawflux_check as rfc
        data_dir = os.path.join(workdir, "data")
        os.makedirs(data_dir, exist_ok=True)
        sets = {}
        for author, pfx in rfc.AUTHORS:
            sets[pfx] = rfc.download_author(
                author, pfx, tic=tic, data_dir=data_dir)
        pfx, secs = rfc.select_pipeline_set(sets)
        if pfx is None or not secs:
            return None
        t, f, spans = rfc.load_stitched(pfx, secs, data_dir=data_dir)
        return {"pfx": pfx, "sectors": secs, "t": t, "f": f,
                "spans": spans, "sets": sets}

    def neighbour_lc(self, tic, workdir):
        from gauntlet.neighbour_fold import fetch_neighbour
        outdir = os.path.join(workdir, "neighbour")
        try:
            lcs = fetch_neighbour(tic, outdir, max_sectors=6)
        except Exception:
            return None
        if not lcs:
            return None
        ts, fs = [], []
        for sec in sorted(lcs):
            t, f = lcs[sec]
            t = np.asarray(t, dtype=float)
            f = np.asarray(f, dtype=float)
            m = np.isfinite(t) & np.isfinite(f) & (f > 0)
            if m.sum() < 50:
                continue
            ts.append(t[m])
            fs.append(f[m] / np.median(f[m]))
        if not ts:
            return None
        t = np.concatenate(ts)
        f = np.concatenate(fs)
        o = np.argsort(t)
        return t[o], f[o]

    def tesscut(self, tic, sectors, workdir, ra, dec, neighbour):
        tesscut_dir = os.path.join(workdir, "tesscut")
        ident_path = os.path.join(workdir, "identity.json")
        cmd = [self.python,
               os.path.join(self.repo_root, "gauntlet",
                            "tesscut_fetch.py"),
               str(tic), "--ra", str(ra), "--dec", str(dec),
               "--sectors"] + [str(s) for s in sectors] + [
               "--outdir", tesscut_dir, "--identity-out", ident_path]
        if neighbour is not None:
            cmd += ["--neighbour-tic", str(neighbour["tic_id"]),
                    "--neighbour-ra", str(neighbour["ra"]),
                    "--neighbour-dec", str(neighbour["dec"])]
            if neighbour.get("Tmag") is not None:
                cmd += ["--neighbour-tmag", str(neighbour["Tmag"])]
        try:
            subprocess.run(cmd, cwd=self.repo_root, check=True,
                           capture_output=True, text=True,
                           timeout=SUBPROCESS_TIMEOUT_S)
        except Exception:
            return None
        if not os.path.exists(ident_path):
            return None
        return tesscut_dir, ident_path

    def holdout(self, tic, period, t0, duration_h, star_radius=1.0):
        import holdout_test
        try:
            res = holdout_test.holdout_test(
                tic, period, t0, duration_h,
                star_radius=star_radius)
        except Exception:
            return "HOLDOUT-INSUFFICIENT-DATA"
        return res.get("verdict", "HOLDOUT-INSUFFICIENT-DATA")

    def diffimg(self, tic, period, t0, duration_d, workdir,
                census_path, depth_pct):
        tesscut_dir = os.path.join(workdir, "tesscut")
        ident_path = os.path.join(workdir, "identity.json")
        outdir = os.path.join(workdir, "diffimg")
        if not os.path.exists(ident_path):
            return None
        ident = json.load(open(ident_path))
        sectors = sorted(int(s) for s, r in ident["sectors"].items()
                         if r.get("status") == "OK")
        if not sectors:
            return None
        cmd = [self.python,
               os.path.join(self.repo_root, "gauntlet", "diffimg.py"),
               str(tic), "--period", str(period), "--t0", str(t0),
               "--duration", str(duration_d),
               "--identity", ident_path, "--tesscut-dir", tesscut_dir,
               "--sectors"] + [str(s) for s in sectors] + [
               "--outdir", outdir, "--depth-pct", str(depth_pct)]
        if census_path and os.path.exists(census_path):
            cmd += ["--census-json", census_path]
        try:
            subprocess.run(cmd, cwd=self.repo_root, check=True,
                           capture_output=True, text=True,
                           timeout=SUBPROCESS_TIMEOUT_S)
        except Exception:
            return None
        path = os.path.join(outdir, "diffimg_results.json")
        if not os.path.exists(path):
            return None
        return json.load(open(path))

    def transit_fit(self, tic, period, t0, duration_d, workdir,
                    qlp_sectors, r_star, r_star_err, m_star,
                    m_star_err, depth_pct):
        if not qlp_sectors:
            return None
        outdir = os.path.join(workdir, "transit_fit")
        os.makedirs(outdir, exist_ok=True)
        cmd = [self.python,
               os.path.join(self.repo_root, "gauntlet",
                            "transit_fit.py"),
               str(tic), "ls", "--period", str(period),
               "--t0", str(t0), "--duration", str(duration_d),
               "--data-dir", os.path.join(workdir, "data"),
               "--qlp-sectors"] + [str(s) for s in qlp_sectors] + [
               "--r-star", str(r_star), "--r-star-err",
               str(r_star_err), "--m-star", str(m_star),
               "--m-star-err", str(m_star_err),
               "--depth-pct", str(depth_pct),
               "--outdir", outdir]
        try:
            subprocess.run(cmd, cwd=self.repo_root, check=True,
                           capture_output=True, text=True,
                           timeout=SUBPROCESS_TIMEOUT_S)
        except Exception:
            return None
        path = os.path.join(outdir, "ls_fit.json")
        if not os.path.exists(path):
            return None
        return json.load(open(path))


# ---------------------------------------------------------------------------
# The driver
# ---------------------------------------------------------------------------

@dataclass
class DeskResult:
    """Everything a desk run produced."""
    run: object                 # GauntletRun (final pass)
    verdict: dict               # build_verdict record
    natives: dict               # stage -> native (arrays included)
    extra_evidence: dict        # P/2 fold, secondary fold, chi2, ...
    workdir: str
    cheap_kill: bool            # True when a cheap stage ended the run
    evidence_package: dict | None = None  # 2D package (None only
    # when the driver predates it — run_desk_gauntlet always
    # builds one)


def _provenance(run_id, repo_root):
    """The runner's provenance header: calibration version, git
    sha, run id, timestamp."""
    import datetime
    sha = "unknown"
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repo_root,
            capture_output=True, text=True,
            timeout=30).stdout.strip() or "unknown"
    except Exception:
        pass
    return {"calibration_version": "gauntlet_v2",
            "pipeline_git_sha": sha, "run_id": run_id,
            "timestamp_utc": datetime.datetime.now(
                datetime.timezone.utc).isoformat()}


def _jsonable(value):
    """A JSON-able summary of a native value: arrays become
    {shape, sha256} so desk_natives.json stays small and
    auditable without embedding light curves."""
    if isinstance(value, np.ndarray):
        h = hashlib.sha256(np.ascontiguousarray(
            value).tobytes()).hexdigest()
        return {"__array__": True, "shape": list(value.shape),
                "dtype": str(value.dtype), "sha256": h}
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, (np.floating, np.integer)):
        return float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    return value


def _effective_waivers(waivers, results):
    """Waivers that apply to these results: only a stage reading
    inconclusive or not_applicable may be waived (the promotion
    allowlist — a pass needs no waiver, a fail or unmeasured
    can never be waived). Returns (effective, dropped); dropped
    maps stage -> the reason it does not apply, for the record.
    """
    by_stage = {r.stage: r for r in results}
    effective, dropped = {}, {}
    for stage, reason in (waivers or {}).items():
        r = by_stage.get(stage)
        if r is not None and r.status in ("inconclusive",
                                          "not_applicable"):
            effective[stage] = reason
        else:
            dropped[stage] = (f"stage reads "
                              f"{r.status if r else 'not run'}")
    return effective, dropped


def run_desk_gauntlet(survivor, workdir, source=None, policy=None,
                      waivers=None, run_expensive=True, run_id=None,
                      repo_root=None, external_tools=None):
    """Run the automated desk gauntlet on one survivor.

    Two passes (see the module docstring): cheap stages first,
    expensive stages only on a cheap-pass survivor. Writes
    verdict_record.json + desk_natives.json into workdir and
    returns a DeskResult. Never raises for a data failure — a
    failed download reads UNMEASURED on its stage, never a run
    kill.

    Waivers are filtered, never blindly forwarded: pass 1 runs
    without waivers (the cheap-kill decision is about FAILs,
    which waivers cannot touch); pass 2 and the verdict get
    only the waivers that apply (a stage reading inconclusive
    or not_applicable). Dropped waivers are recorded in
    extra_evidence["waivers_dropped"] — a waiver for a stage
    that reads unmeasured is operator error, not a run kill.

    external_tools: None (default — no external tools) or a
    dict {tool: ToolConfig} (gauntlet/external_tool.py;
    load_external_tool_configs builds it from the
    external_tools_v1 policy). The tools run as post-runner
    EVIDENCE stages after pass 2, only on a survivor no stage
    failed; their StageResults land in
    extra_evidence["external_tools"] (+ raw outputs in
    ["external_tools_raw"]) and never feed the verdict.
    """
    import provenance as _prov
    tic = str(survivor.tic)
    period = float(survivor.period_d)
    t0 = float(survivor.t0_btjd)
    dur_h = float(survivor.duration_h)
    dur_d = dur_h / 24.0
    workdir = str(workdir)
    os.makedirs(workdir, exist_ok=True)
    source = source or LiveDataSource(repo_root=repo_root)
    repo_root = repo_root or os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))
    run_id = run_id or _prov.new_run_id("desk")
    prov = _provenance(run_id, repo_root)

    natives = {}
    extra = {"survivor": {"tic": tic, "period_d": period,
                          "t0_btjd": t0, "duration_h": dur_h,
                          "depth_pct": survivor.depth_pct,
                          "sde": survivor.sde,
                          "sector": survivor.sector,
                          "bulk_survivor": survivor.bulk_survivor}}
    census = None
    rho_star = None
    r_star = None
    m_star = None

    # ---- stage 0: catalogue -------------------------------------------
    try:
        census = source.census(tic, period, workdir)
    except Exception as e:
        extra["census_error"] = f"{type(e).__name__}: {e}"
        census = None
    if census is not None:
        native = catalogue_native(census, period)
        if native is not None:
            natives["catalogue.native"] = native
        rho_star = rho_star_from_census(census.get("target"))
        target = census.get("target") or {}
        r_star = target.get("rad")
        m_star = target.get("mass")
        extra["census_flags"] = census.get("flags", [])
        extra["census_errors"] = census.get("errors", [])

    # ---- stage 1: clean-data re-fold gate (filed ephemeris) ----------
    if survivor.bulk_survivor and survivor.sector is not None:
        try:
            disc = source.discovery_lc(tic, survivor.sector)
        except Exception as e:
            extra["discovery_lc_error"] = f"{type(e).__name__}: {e}"
            disc = None
        if disc is not None:
            dt, df, dq = disc
            fold, verdict = clean_refold_native(
                dt, df, dq, period, t0, dur_h)
            natives["clean_refold.native"] = (fold, verdict)
            extra["clean_refold_fold"] = fold

    # ---- stitched light curves (the fold stages' data) ----------------
    stitched = None
    try:
        stitched = source.stitched_lc(tic, workdir)
    except Exception as e:
        extra["stitched_lc_error"] = f"{type(e).__name__}: {e}"
    n_sectors = 0
    if stitched is not None:
        n_sectors = len(stitched.get("sectors") or [])
        t_raw = np.asarray(stitched["t"], dtype=float)
        f_raw = np.asarray(stitched["f"], dtype=float)
        extra["pipeline_set"] = {"pfx": stitched.get("pfx"),
                                 "sectors": stitched.get("sectors")}
        # ---- stage 2a: refine (flattened flux, narrow BLS grid) ------
        f_flat = flatten_transit_masked(t_raw, f_raw, period, t0,
                                        dur_d)
        ref = refine_native(t_raw, f_flat, period, t0, dur_d,
                            n_eras=max(n_sectors, 1))
        natives["refine.native"] = ref
        if ref["converged"]:
            p_ref, t0_ref = ref["period_d"], ref["t0"]
        else:
            p_ref, t0_ref = period, t0
        extra["refined_ephemeris"] = {"period_d": p_ref,
                                      "t0_btjd": t0_ref,
                                      "converged": ref["converged"]}
        # ---- stage 2b: raw flux / shape / odd-even / persistence -----
        natives["raw_flux.native"] = raw_flux_native(
            t_raw, f_raw, p_ref, t0_ref, dur_d)
        natives["shape.native"] = shape_native(
            t_raw, f_raw, p_ref, t0_ref, dur_d, rho_star)
        odd, even, odd_extra = odd_even_native(
            t_raw, f_raw, p_ref, t0_ref, dur_d)
        natives["odd_even.native"] = (odd, even)
        extra.update(odd_extra)
        natives["persistence.native"] = persistence_native(
            t_raw, f_raw, p_ref, t0_ref, dur_d)
        # ---- stage 6b: blend (brightest neighbour, or the dip-free
        # control when the 180" cone is empty) ------------------------
        neighbour = (brightest_neighbour(census)
                     if census is not None else None)
        if neighbour is not None:
            try:
                nb = source.neighbour_lc(neighbour["tic_id"],
                                         workdir)
            except Exception as e:
                extra["neighbour_lc_error"] = (
                    f"{type(e).__name__}: {e}")
                nb = None
            if nb is not None:
                natives["blend.native"] = {
                    "target_t": t_raw, "target_f": f_raw,
                    "neighbour_t": nb[0], "neighbour_f": nb[1],
                    "period_d": p_ref, "t0": t0_ref,
                    "duration_d": dur_d,
                    "neighbour_tic": neighbour["tic_id"],
                    "separation_arcsec": neighbour.get("sep_arcsec"),
                    "census_radius_arcsec": 180.0}
        else:
            natives["blend.native"] = {
                "target_t": t_raw, "target_f": f_raw,
                "neighbour_t": t_raw,
                "neighbour_f": dip_free_neighbour(
                    t_raw, f_raw, p_ref, t0_ref, dur_d),
                "period_d": p_ref, "t0": t0_ref,
                "duration_d": dur_d, "neighbour_tic": None,
                "separation_arcsec": None,
                "census_radius_arcsec": 180.0}
    else:
        p_ref, t0_ref = period, t0

    # ---- stage 7: pixel check (P >= 8 d only; the runner assigns
    # NOT_APPLICABLE below it) ------------------------------------------
    tesscut_ready = None
    if stitched is not None and p_ref >= 8.0 and census is not None:
        target = census.get("target") or {}
        ra, dec = target.get("ra"), target.get("dec")
        sector = survivor.sector or (stitched.get("sectors") or [None])[0]
        if ra is not None and dec is not None and sector is not None:
            neighbour = brightest_neighbour(census)
            try:
                tesscut_ready = source.tesscut(
                    tic, [sector], workdir, ra, dec, neighbour)
            except Exception as e:
                extra["tesscut_error"] = f"{type(e).__name__}: {e}"
            if tesscut_ready is not None:
                tesscut_dir, ident_path = tesscut_ready
                try:
                    ident = json.load(open(ident_path))
                    isec = ident["sectors"].get(str(sector)) or {}
                    tpx = isec.get("target_px")
                    t_pf, flux_cube, _tpf = load_tpf(
                        os.path.join(tesscut_dir,
                                     f"tesscut_s{int(sector):03d}.fits"))
                    if tpx is not None:
                        natives["pixel_check.native"] = (
                            pixel_check_native(
                                flux_cube, t_pf, p_ref, t0_ref,
                                dur_d, tuple(tpx)))
                except Exception as e:
                    extra["pixel_check_error"] = (
                        f"{type(e).__name__}: {e}")

    # ---- pass 1: the cheap stages (no waivers — the cheap-kill
    # decision is about FAILs, which waivers cannot touch) --------
    ctx = TargetContext(
        tic=tic,
        ephemeris=Ephemeris(kind="bulk", period_d=period, t0=t0,
                            duration_d=dur_d, source="desk"),
        artifacts=dict(natives), provenance=prov, imaging=None,
        bulk_survivor=survivor.bulk_survivor)
    run = run_gauntlet(ctx, mode="short_circuit", waivers=None,
                       policy=policy,
                       work_dir=os.path.join(workdir, "cache"))
    cheap_kill = any(r.status == "fail" for r in run.results)
    imaging = None

    # ---- pass 2: the expensive stages (cheap-pass survivors only) -----
    if not cheap_kill and run_expensive and stitched is not None:
        # holdout: the sector count decides the native without a
        # run (1 sector -> NOT_APPLICABLE, 2 -> INSUFFICIENT).
        if n_sectors <= 1:
            natives["holdout.native"] = "HOLDOUT-NOT-APPLICABLE"
        elif n_sectors == 2:
            natives["holdout.native"] = "HOLDOUT-INSUFFICIENT-DATA"
        else:
            try:
                natives["holdout.native"] = source.holdout(
                    tic, p_ref, t0_ref, dur_h,
                    star_radius=r_star or 1.0)
            except Exception as e:
                extra["holdout_error"] = f"{type(e).__name__}: {e}"
        # diffimg: fetch the cutouts for the stitched sectors
        # (capped), then run the CLI and derive the native.
        if census is not None:
            target = census.get("target") or {}
            ra, dec = target.get("ra"), target.get("dec")
            sectors = (stitched.get("sectors") or [])
            sectors = sectors[:MAX_DIFFIMG_SECTORS]
            if ra is not None and dec is not None and sectors:
                neighbour = brightest_neighbour(census)
                try:
                    got = source.tesscut(
                        tic, sectors, workdir, ra, dec, neighbour)
                except Exception as e:
                    extra["tesscut_error"] = (
                        f"{type(e).__name__}: {e}")
                    got = None
                if got is not None:
                    tesscut_ready = got
                    try:
                        res = source.diffimg(
                            tic, p_ref, t0_ref, dur_d, workdir,
                            os.path.join(workdir,
                                         "stage0_census.json"),
                            survivor.depth_pct)
                    except Exception as e:
                        extra["diffimg_error"] = (
                            f"{type(e).__name__}: {e}")
                        res = None
                    if res is not None:
                        host = (neighbour["tic_id"]
                                if neighbour is not None else None)
                        native = diffimg_native_for(res, host)
                        if native is not None:
                            natives["diffimg.native"] = native
                            if native.get("on_target") is not None:
                                imaging = {
                                    "on_target": native["on_target"],
                                    "offset_px": native.get("offset_px"),
                                    "offset_arcsec": native.get(
                                        "offset_arcsec"),
                                    "blend_host_tic": native.get(
                                        "blend_host_tic")}
        # transit_fit: LS stage on the QLP sectors.
        qlp_secs = (stitched.get("sets", {}).get("qlp") or [])
        if qlp_secs and r_star is not None and m_star is not None:
            try:
                ls = source.transit_fit(
                    tic, p_ref, t0_ref, dur_d, workdir, qlp_secs,
                    r_star, 0.1 * r_star, m_star, 0.1 * m_star,
                    survivor.depth_pct)
            except Exception as e:
                extra["transit_fit_error"] = (
                    f"{type(e).__name__}: {e}")
                ls = None
            if ls is not None:
                native = transit_fit_native_for(ls, r_star, rho_star)
                if native is not None:
                    natives["transit_fit.native"] = native
                    extra["transit_fit_chi2"] = native.get("chi2")
                    extra["transit_fit_npts"] = native.get("npts")
        ctx = TargetContext(
            tic=tic,
            ephemeris=Ephemeris(kind="bulk", period_d=period, t0=t0,
                                duration_d=dur_d, source="desk"),
            artifacts=dict(natives), provenance=prov,
            imaging=imaging,
            bulk_survivor=survivor.bulk_survivor)
        # Pass 2 waivers, filtered a priori: the three waivable
        # stages read NOT_APPLICABLE only under these conditions
        # (holdout: 1 sector; clean_refold: not a bulk survivor;
        # pixel_check: P < 8 d). Anything else is dropped and
        # recorded — a waiver for a measured stage is operator
        # error, not a run kill.
        waivable = set()
        if n_sectors <= 1:
            waivable.add("holdout")
        if not survivor.bulk_survivor:
            waivable.add("clean_refold")
        if p_ref < 8.0:
            waivable.add("pixel_check")
        waivers_pass2 = {k: v for k, v in (waivers or {}).items()
                         if k in waivable}
        dropped_pass2 = {k: "stage does not read not_applicable "
                            "for this target"
                         for k in (waivers or {})
                         if k not in waivable}
        if dropped_pass2:
            extra.setdefault("waivers_dropped", {}).update(
                dropped_pass2)
        run = run_gauntlet(ctx, mode="short_circuit",
                           waivers=waivers_pass2 or None,
                           policy=policy,
                           work_dir=os.path.join(workdir, "cache"))

        # ---- external tools (LATTE / TRICERATOPS): post-runner
        # evidence stages, expensive-gated like holdout/diffimg/
        # transit_fit — they run only on a survivor no stage
        # failed (a dead candidate is not worth 5–15 min of
        # Mac time per tool). Their results are evidence only
        # and never feed the verdict (PHASE_2_PROGRESS.md, 2B
        # judgment calls 2–3).
        if external_tools and not any(
                r.status == "fail" for r in run.results):
            _run_external_tools(
                external_tools, tic, census, p_ref, t0_ref,
                dur_h, survivor, t_raw, f_raw, stitched,
                workdir, prov, extra)

    # ---- verdict + records ----------------------------------------------
    filed = {"period_days": period, "t0_btjd": t0,
             "duration_hours": dur_h,
             "depth_pct": survivor.depth_pct}
    if survivor.sde is not None:
        filed["sde"] = survivor.sde
    ephemeris_used = {"period_d": p_ref, "t0": t0_ref,
                      "duration_d": dur_d,
                      "source": ("refined" if natives.get(
                          "refine.native", {}).get("converged")
                          else "bulk")}
    # The verdict's waivers are filtered against the FINAL
    # results (the definitive check — a waiver only applies
    # where the stage reads inconclusive or not_applicable).
    waivers_final, dropped_final = _effective_waivers(
        waivers, run.results)
    if dropped_final:
        extra.setdefault("waivers_dropped", {}).update(dropped_final)
    verdict = build_verdict(
        tic, filed, run.results, imaging=imaging,
        ephemeris_used=ephemeris_used,
        verdict_note=run.verdict_note, run_id=run_id,
        waivers=waivers_final or None, policy=policy)
    with open(os.path.join(workdir, "verdict_record.json"),
              "w") as fh:
        json.dump(verdict, fh, indent=2, default=str)
    with open(os.path.join(workdir, "desk_natives.json"), "w") as fh:
        json.dump({"natives": _jsonable(natives),
                   "extra_evidence": _jsonable(extra),
                   "run": {"final_verdict": run.final_verdict,
                           "verdict_note": run.verdict_note,
                           "skipped": sorted(run.skipped),
                           "cached": run.cached,
                           "context_hash": run.context_hash}},
                  fh, indent=2, default=str)
    # 2D: the evidence package is built LAST — it hashes the
    # two files above, so they must exist first.
    package = build_evidence_package(
        tic, verdict, extra, workdir)
    with open(os.path.join(workdir, "evidence_package.json"),
              "w") as fh:
        json.dump(package, fh, indent=2, default=str)
    return DeskResult(run=run, verdict=verdict, natives=natives,
                      extra_evidence=extra, workdir=workdir,
                      cheap_kill=cheap_kill,
                      evidence_package=package)
