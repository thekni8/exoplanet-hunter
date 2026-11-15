"""Drive TRICERATOPS (Giacalone et al. 2021) for one target
(Phase 2, 2C).

Runs INSIDE the TRICERATOPS venv on the Mac, invoked by
gauntlet/external_tool.py as:

    python run_triceratops.py --input <input.json> --output <output.json>

Reads the C-10 input JSON, phase-folds the stitched light
curve at the refined ephemeris, bins the fold to ~200 bins
within a ±3-duration window (P-15), and runs the tool's API
(TRICERATOPS 1.1.0, verified against the source):

    np.random.seed(seed)                     # no seed parameter exists
    tgt = target(ID, sectors, search_radius=10)
    tgt.calc_depths(tdepth, dilution_corrected=...)
    tgt.calc_probs(t_fold, f_fold, f_err, P_orb,
                   contrast_curve_file=..., N=1_000_000,
                   exptime=cadence_days, nsamples=20, verbose=0,
                   dilution_corrected=...)

then writes the C-10 output JSON (schema
triceratops-output-schema.json) with FPP/NFPP from the
tool's own attributes (tgt.FPP, tgt.NFPP) and the
per-scenario breakdown aggregated BY SCENARIO NAME from
tgt.probs — never by row index, so the mapping survives
layout changes in the tool.

TRICERATOPS specifics, verified against the 1.1.0 source:

* calc_probs takes the PHASE-FOLDED light curve (time in
  days from transit midpoint) and a scalar flux error.
  flux_err is the robust (MAD) scatter of the out-of-transit
  folded flux.
* P-15 BINNING: the folded curve is binned to ~200 bins
  (per-bin median flux, median phase as the bin centre)
  within a ±3-duration window around mid-transit before
  calc_probs — the full curve is tens of thousands of
  cadences, and the fit cost scales with the point count.
  The out-of-transit baseline beyond ±3 durations carries
  no transit information. flux_err stays the UNBINNED
  out-of-transit MAD scatter — conservative: binned fluxes
  have smaller errors, so the unbinned scalar overstates
  the noise and can only make the tool's fits more
  cautious, never more confident. The number of input
  cadences inside the window is recorded as
  metrics.n_fold_points; empty bins are dropped, so the
  bin count is approximate ("about 200", not exactly 200).
* Seeding is via np.random.seed(): the MC draws from the
  global generator and calc_probs takes no seed. The seed
  is set before target construction so the whole run is
  reproducible.
* The search radius is 10 pixels (~200 arcsec at the TESS
  20.25 arcsec/px scale), covering the vetting manual's
  180-arcsecond neighbour rule.
* dilution_corrected comes from the input (the desk driver
  sets it from the light-curve product: SPOC/TESS-SPOC
  PDCSAP is corrected, QLP KSPSAP is not — lightkurve's
  default flux columns, pinned by lightkurve 2.6.0). It is
  recorded in the output metrics so the record says what
  was assumed, and passed identically to calc_depths and
  calc_probs (the tool requires the same value in both).
* Without a contrast curve, NFPP is an upper bound — the
  output carries that warning verbatim.
* A DEGENERATE computation (all scenario log-evidences
  -inf) reports FPP=1.0 for a failed computation, not a
  confident false positive. The wrapper still reports
  status "completed" with fpp_degenerate=true so the
  evidence is preserved; the ADAPTER maps degenerate to
  UNMEASURED + EXEC_ERROR.
* N=1,000,000 is the tool default (the published cost,
  ~5–15 min/target). There is no nested timeout: calc_probs
  is a blocking in-process call, so the RUNNER's timeout
  (1800 s) is the enforcement — the wrapper is killed, and
  the stage reads UNMEASURED.
* PROVENANCE LIMIT (P-4): inside calc_probs the tool
  fetches neighbour-star data and TRILEGAL simulations
  from remote catalogs — the wrapper cannot hash what it
  does not download through its own code path, so
  input_hashes cover only the files the pipeline handed
  the tool (light curve + census). The seed +
  tool_version + policy_version make the run reproducible
  in principle, but a remote catalog change could move
  the number; the record does not pretend otherwise.
* The per-scenario probability table is saved as
  triceratops_probs.csv in the run workdir (evidence
  artifact). No corner plot in v1.

Exit 0 means "an output JSON was written" (its `status`
field says whether TRICERATOPS completed or failed); a
non-zero exit means the wrapper itself crashed before
writing one.
"""
import argparse
import json
import os
import sys
import time

# Monte Carlo draws per calc_probs call — the tool default.
N_SAMPLES = 1_000_000
# TESS pixels from the target to search for nearby stars
# (10 px x 20.25 arcsec/px ~ 200 arcsec > the 180" rule).
SEARCH_RADIUS_PX = 10
# P-15: phase-fold bins for calc_probs, within a ±3-duration
# window around mid-transit.
N_FOLD_BINS = 200
FOLD_WINDOW_DURATIONS = 3.0
# Planet scenarios in the tool's naming (FPP = 1 - their sum,
# per the tool's own definition).
PLANET_SCENARIOS = ("TP", "PTP", "DTP")
EB_TARGET_SCENARIOS = ("EB", "EBx2P")
EB_NEIGHBOUR_SCENARIOS = ("BEB", "BEBx2P")
EB_HIERARCHICAL_SCENARIOS = ("PEB", "PEBx2P", "SEB", "SEBx2P")


def _installed_version(fallback):
    """The installed triceratops version, or the input's
    expected version with a warning when the distribution
    metadata is unavailable."""
    try:
        from importlib import metadata
        return metadata.version("triceratops"), None
    except Exception:  # noqa: BLE001 - any metadata failure
        return fallback, ("could not read the installed "
                          "triceratops version; reporting the "
                          "input's expected version")


def _robust_sigma(values):
    """MAD-based sigma (1.4826 factor)."""
    import numpy as np
    med = float(np.median(values))
    return float(np.median(np.abs(values - med))) * 1.4826


def _bin_fold(ph, f, duration_d, n_bins=N_FOLD_BINS,
              window=FOLD_WINDOW_DURATIONS):
    """Bin the phase-folded curve (P-15).

    Keeps the cadences within ±`window` durations of
    mid-transit and bins them into ~`n_bins` equal-width
    bins (per-bin median flux, median phase as the bin
    centre — the points are not uniformly distributed, so
    the median phase is more honest than the geometric
    centre). Returns (bin_phase, bin_flux, n_points):
    the bin centres, the per-bin median fluxes, and the
    number of input cadences inside the window. Empty bins
    are dropped, so the bin count is approximate.
    """
    import numpy as np
    window_d = window * duration_d
    in_window = np.abs(ph) <= window_d
    n_points = int(in_window.sum())
    if n_points == 0:
        return (np.asarray([]), np.asarray([]), 0)
    edges = np.linspace(-window_d, window_d, n_bins + 1)
    pw = ph[in_window]
    fw = f[in_window]
    idx = np.clip(np.digitize(pw, edges) - 1, 0, n_bins - 1)
    centres, fluxes = [], []
    for b in range(n_bins):
        m = idx == b
        if not m.any():
            continue
        centres.append(float(np.median(pw[m])))
        fluxes.append(float(np.median(fw[m])))
    return (np.asarray(centres), np.asarray(fluxes), n_points)


def _scenario_sum(probs, scenarios):
    """Summed probability of the named scenarios, from the
    probs DataFrame (name-based, never index-based)."""
    total = 0.0
    for _, row in probs.iterrows():
        if str(row["scenario"]) in scenarios:
            total += float(row["prob"])
    return total


def _most_likely_fp(probs):
    """Highest-probability non-planet scenario as
    '<scenario> on TIC <id>', or None when the table is
    empty."""
    best = None
    best_prob = -1.0
    for _, row in probs.iterrows():
        scenario = str(row["scenario"])
        if scenario in PLANET_SCENARIOS:
            continue
        prob = float(row["prob"])
        if prob > best_prob:
            best_prob = prob
            best = f"{scenario} on TIC {int(row['ID'])}"
    return best


def _output(tool_version, seed, config_hash, status, value,
            metrics, input_hashes, artifacts, warnings,
            wall_time_s, n_transits):
    return {
        "tool": "triceratops",
        "tool_version": tool_version,
        "seed": seed,
        "config_hash": config_hash,
        "status": status,
        "value": value,
        "metrics": metrics,
        "input_hashes": input_hashes,
        "artifacts": artifacts,
        "warnings": warnings,
        "wall_time_s": wall_time_s,
        "n_transits": n_transits,
    }


def _null_metrics(dilution_corrected, contrast_curve_used,
                  n_fold_points=None):
    return {
        "fpp": None, "nfpp": None, "prob_planet": None,
        "prob_eb_target": None, "prob_eb_neighbour": None,
        "prob_hierarchical_eb": None, "n_samples": 0,
        "most_likely_false_positive": None,
        "fpp_degenerate": False,
        "dilution_corrected": dilution_corrected,
        "contrast_curve_used": contrast_curve_used,
        "n_fold_points": n_fold_points,
    }


def run(input_path, output_path):
    """Run TRICERATOPS for the target in input_path; write
    the output JSON to output_path. Returns the output dict."""
    # Deferred imports: this module must import cleanly in
    # the pipeline venv (for tests), where triceratops is
    # NOT installed. Inside the tool venv these resolve to
    # the real packages (or the test fakes on PYTHONPATH).
    import numpy as np
    with open(input_path) as fh:
        inp = json.load(fh)
    workdir = os.path.dirname(os.path.abspath(output_path))
    os.makedirs(workdir, exist_ok=True)
    tic = str(inp["target"]["tic"])
    seed = inp["seed"]
    config_hash = inp["config_hash"]
    # P3-8: the input may override the draw count — the
    # golden-test nightly's fast smoke passes n_samples=10000
    # for iteration; the default (and every C-10 / panel run)
    # is the full 1,000,000. The output records the count
    # actually used, so a fast run can never masquerade as a
    # full one.
    n_samples = int(inp.get("n_samples", N_SAMPLES))
    n_transits = inp["signal"].get("n_transits")
    dilution_corrected = bool(inp.get("dilution_corrected",
                                      False))
    cc = inp.get("contrast_curve") or {}
    cc_path = cc.get("path")
    contrast_curve_used = bool(cc_path)
    input_hashes = {
        "lightcurve": inp["lightcurve"]["input_hash"],
        "neighbours": inp["neighbours"]["input_hash"],
    }
    warnings = []
    tool_version, version_warning = _installed_version(
        inp.get("tool_version", "unknown"))
    if version_warning:
        warnings.append(version_warning)
    if not contrast_curve_used:
        warnings.append("no contrast curve: NFPP is an upper "
                        "bound")
    start = time.monotonic()
    # P-15: the fold-point count, known once the curve is
    # binned; failure records carry it when it is known.
    n_fold_points = None

    def _failed(reason):
        warnings.append(reason)
        return _output(
            tool_version, seed, config_hash, "failed", None,
            _null_metrics(dilution_corrected,
                          contrast_curve_used,
                          n_fold_points),
            input_hashes, [], warnings,
            time.monotonic() - start, n_transits)

    # ---- phase-fold the stitched light curve -------------------
    try:
        z = np.load(inp["lightcurve"]["path"])
        t = np.asarray(z["time"], dtype=float)
        f = np.asarray(z["flux"], dtype=float)
    except Exception as exc:  # noqa: BLE001 - unreadable input
        return _failed(f"could not load the light curve: {exc}")
    period = float(inp["signal"]["period_d"])
    t0 = float(inp["signal"]["t0_bjd"])
    duration_d = float(inp["signal"]["duration_h"]) / 24.0
    depth_frac = float(inp["signal"]["depth_frac"])
    ph = ((t - t0 + 0.5 * period) % period) - 0.5 * period
    order = np.argsort(ph)
    ph, f = ph[order], f[order]
    out_mask = np.abs(ph) > 1.5 * duration_d
    if out_mask.sum() < 50:
        out_mask = np.ones_like(ph, dtype=bool)
    flux_err = _robust_sigma(f[out_mask])
    if not np.isfinite(flux_err) or flux_err <= 0:
        return _failed("flux error is zero or non-finite "
                       "(out-of-transit scatter unmeasurable)")
    # P-15: bin the fold before calc_probs (~200 bins in a
    # ±3-duration window). flux_err above is the UNBINNED
    # scatter — conservative for the binned fluxes.
    ph_bin, f_bin, n_fold_points = _bin_fold(ph, f, duration_d)
    if n_fold_points == 0:
        return _failed("no folded cadences within "
                       "±3 durations of mid-transit")
    cadence_s = float(inp["lightcurve"]["cadence_s"])
    sectors = [int(s) for s in inp["lightcurve"]["sectors"]]

    # ---- run the tool ------------------------------------------
    try:
        from triceratops.triceratops import target
    except ImportError as exc:
        return _failed(f"triceratops is not importable in "
                       f"this venv: {exc}")
    np.random.seed(seed)
    try:
        tgt = target(ID=int(tic), sectors=np.array(sectors),
                     search_radius=SEARCH_RADIUS_PX)
        tgt.calc_depths(tdepth=depth_frac,
                        dilution_corrected=dilution_corrected)
        tgt.calc_probs(ph_bin, f_bin, flux_err, P_orb=period,
                       contrast_curve_file=cc_path,
                       N=n_samples, exptime=cadence_s / 86400.0,
                       nsamples=20, verbose=0,
                       dilution_corrected=dilution_corrected)
    except Exception as exc:  # noqa: BLE001 - tool failure
        return _failed(f"TRICERATOPS raised "
                       f"{type(exc).__name__}: {exc}")
    wall = time.monotonic() - start
    fpp = float(tgt.FPP)
    nfpp = float(tgt.NFPP)
    degenerate = bool(getattr(tgt, "FPP_degenerate", False))
    if degenerate:
        warnings.append(
            "degenerate computation: all scenario "
            "log-evidences -inf; FPP=1.0 reflects a failed "
            "computation, not a confident false positive")
    probs = tgt.probs
    probs_path = os.path.join(workdir,
                              "triceratops_probs.csv")
    try:
        probs.to_csv(probs_path, index=False)
        artifacts = [probs_path]
    except Exception:  # noqa: BLE001 - evidence write failure
        artifacts = []
        warnings.append("could not write the scenario table")
    metrics = {
        "fpp": fpp, "nfpp": nfpp,
        "prob_planet": 1.0 - fpp,
        "prob_eb_target": _scenario_sum(
            probs, EB_TARGET_SCENARIOS),
        "prob_eb_neighbour": _scenario_sum(
            probs, EB_NEIGHBOUR_SCENARIOS),
        "prob_hierarchical_eb": _scenario_sum(
            probs, EB_HIERARCHICAL_SCENARIOS),
        "n_samples": n_samples,
        "most_likely_false_positive": _most_likely_fp(probs),
        "fpp_degenerate": degenerate,
        "dilution_corrected": dilution_corrected,
        "contrast_curve_used": contrast_curve_used,
        "n_fold_points": n_fold_points,
    }
    return _output(tool_version, seed, config_hash, "completed",
                   fpp, metrics, input_hashes, artifacts,
                   warnings, wall, n_transits)


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Drive TRICERATOPS for one target.")
    ap.add_argument("--input", required=True,
                    help="C-10 input JSON")
    ap.add_argument("--output", required=True,
                    help="C-10 output JSON to write")
    args = ap.parse_args(argv)
    out = run(args.input, args.output)
    with open(args.output, "w") as fh:
        json.dump(out, fh, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
