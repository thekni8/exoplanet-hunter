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
* PM-1 (fail closed on a skipped background population):
  if the Gaia background query fails, the tool sets
  trilegal_missing and silently omits the 6 background
  scenarios (DTP, DEB, DEBx2P, BTP, BEB, BEBx2P) from the
  probability table. The wrapper fails the run instead of
  reporting an FPP computed without them: right after
  target construction when trilegal_missing is set, and
  after calc_probs when any of the 6 scenarios is absent
  from the table (skipped for a degenerate computation,
  whose table is meaningless). metrics.
  background_scenarios_checked records that the check ran
  and passed.
* N=1,000,000 is the tool default (the published cost,
  ~5–15 min/target). calc_probs is a blocking in-process
  call, so the RUNNER's timeout is the enforcement for
  the compute — the wrapper is killed, and the stage
  reads UNMEASURED. The NETWORK phases are different:
  the tool's remote calls (MAST TIC cone, Gaia TAP,
  per-sector TessCut) carry no timeout of their own, and
  on 2026-11-16 a WASP-29b run sat 50 minutes in a
  blocking SSL read on a MAST connection (7 s of CPU in
  50 min of wall) until the runner's cap killed it. The
  wrapper therefore bounds every socket read
  (socket.setdefaulttimeout, 300 s) and the target build
  (a SIGALRM phase budget, 2,400 s re-derived P4-8 from
  the measured healthy-init tail, retried once), and
  records per-phase seconds in metrics.phase_seconds
  plus a timestamped phase_log.txt in the workdir — so
  the next stall fails fast and names its phase instead
  of burning the whole cap in silence. P4-8 (proven from
  the tool's source): the SIGALRM budget does NOT enforce
  on a stall inside the per-sector TessCut loop
  (triceratops.py ~242 swallows it and drops the sector),
  so the wrapper also fails loudly whenever the tool
  builds fewer sectors than requested (len(TESS_images)
  vs len(sectors), recorded in metrics as
  sectors_built / sectors_requested) — a swallowed stall
  is a loud failure, never a partial FPP. The
  out-of-process runner cap is the ultimate bound.
* PROVENANCE LIMIT (P-4): inside target construction
  the tool fetches neighbour-star data from MAST and a
  background-star population from Gaia DR3 (the 1.1.0
  default; TRILEGAL only when explicitly requested) —
  the wrapper cannot hash what it does not download
  through its own code path, so input_hashes cover only
  the files the pipeline handed the tool (light curve +
  census). The seed + tool_version + policy_version make
  the run reproducible in principle, but a remote
  catalog change could move the number; the record does
  not pretend otherwise. When a Gaia background CSV the
  tool itself wrote for this target is already on disk,
  the wrapper passes it as trilegal_fname so a retry
  skips the live Gaia query with identical data.
* The per-scenario probability table is saved as
  triceratops_probs.csv in the run workdir (evidence
  artifact). No corner plot in v1.

Exit 0 means "an output JSON was written" (its `status`
field says whether TRICERATOPS completed or failed); a
non-zero exit means the wrapper itself crashed before
writing one.
"""
import argparse
import contextlib
import json
import os
import signal
import socket
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
# Network resilience (2026-11-16, re-derived 2026-11-17,
# P4-8): the tool's remote calls carry no timeout of their
# own — a stalled call waits forever and only the runner's
# cap ends it. The wrapper bounds every socket read AND
# the target build, and retries a stalled build once.
# P4-8 FINDING (proven from the tool's source,
# triceratops.py ~242): the SIGALRM budget does NOT
# enforce on a stall inside the per-sector TessCut loop —
# the tool catches every exception there, prints "Sector N
# raised exception. Ignoring for validation." and drops
# the sector, so the alarm is swallowed and the run
# proceeds on a partial sector set (inits ran 697.8 s /
# 1714.3 s / 2700 s+ against the old 600 s budget). The
# alarm still bounds hangs OUTSIDE that loop (the MAST
# cone / Gaia queries) and slow-flowing fetches, but the
# fail-loud mechanism for a swallowed stall is the
# dropped-sector check in run(): a shortfall in
# len(TESS_images) vs the requested sectors fails the run.
# The budget below is re-derived from the measured
# healthy-init tail — max 1,714.3 s (TIC 399571743),
# 1,611.4 s (TOI-700c), 1,190.9 s (TIC 12999193) — and
# must exceed it with margin: 2,400 s is ~1.4x the max.
# The old 600 s default is BELOW the tail and would trip
# on a healthy 20-sector init. Budgets are overridable by
# environment for tests. The out-of-process runner cap
# (policy timeout_s) is the ultimate bound.
SOCKET_TIMEOUT_S = 300
TARGET_INIT_TIMEOUT_S = 2400
TARGET_INIT_ATTEMPTS = 2
# The repo root, for finding a cached Gaia population CSV
# the tool itself wrote on an earlier run.
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
# Planet scenarios in the tool's naming (FPP = 1 - their sum,
# per the tool's own definition).
PLANET_SCENARIOS = ("TP", "PTP", "DTP")
# PM-1: the scenarios the tool computes only from the
# background-star population (Gaia DR3 by default). If the
# background query fails, the tool sets trilegal_missing
# and silently omits them from the probability table — the
# FPP it then reports was computed without the background
# scenarios. The wrapper fails closed on that (see run()).
BACKGROUND_SCENARIOS = ("DTP", "DEB", "DEBx2P", "BTP", "BEB",
                        "BEBx2P")
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


class _PhaseTimeout(TimeoutError):
    """A named tool phase ran past its budget."""

    def __init__(self, phase, budget_s):
        super().__init__(f"{phase} timed out after "
                         f"{budget_s}s")
        self.phase = phase
        self.budget_s = budget_s


@contextlib.contextmanager
def _phase_timeout(phase, budget_s):
    """Raise _PhaseTimeout if the phase runs longer than
    budget_s. SIGALRM-based: it interrupts blocking
    socket reads, which is the failure mode the tool's
    own calls have no defence against (a library that
    sets its own socket timeout defeats setdefaulttimeout,
    but nothing defeats the alarm). No-op on platforms
    without SIGALRM, and with a non-positive budget."""
    if budget_s is None or budget_s <= 0:
        yield
        return
    if not hasattr(signal, "SIGALRM"):
        yield
        return

    def _handler(signum, frame):
        raise _PhaseTimeout(phase, budget_s)

    old_handler = signal.signal(signal.SIGALRM, _handler)
    old_timer = signal.getitimer(signal.ITIMER_REAL)
    signal.setitimer(signal.ITIMER_REAL, budget_s)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, old_timer[0],
                         old_timer[1])
        signal.signal(signal.SIGALRM, old_handler)


def _env_int(name, default):
    """An integer environment override, or the default
    when unset or unparsable."""
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _cached_gaia_population(tic_id):
    """A Gaia background CSV the tool itself wrote for
    this target (same defaults every run), if one is on
    disk: passing it as trilegal_fname skips the live
    Gaia query with identical data. Looks in the working
    directory first, then the repo root (the tool writes
    the file to its cwd, which is the repo root for the
    nightly and panel drivers)."""
    name = f"{tic_id}_gaia_background.csv"
    for path in (os.path.join(os.getcwd(), name),
                 os.path.join(REPO_ROOT, name)):
        if os.path.isfile(path) and os.path.getsize(path) > 0:
            return path
    return None


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


def _missing_background_scenarios(probs):
    """Background scenarios absent from the probs table
    (PM-1). Fail closed: an unreadable table counts as all
    missing."""
    try:
        present = {str(row["scenario"])
                   for _, row in probs.iterrows()}
    except Exception:  # noqa: BLE001 - unreadable table
        return list(BACKGROUND_SCENARIOS)
    return [s for s in BACKGROUND_SCENARIOS
            if s not in present]


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
                  n_fold_points=None, phase_seconds=None,
                  sectors_requested=None, sectors_built=None):
    return {
        "fpp": None, "nfpp": None, "prob_planet": None,
        "prob_eb_target": None, "prob_eb_neighbour": None,
        "prob_hierarchical_eb": None, "n_samples": 0,
        "most_likely_false_positive": None,
        "fpp_degenerate": False,
        "dilution_corrected": dilution_corrected,
        "contrast_curve_used": contrast_curve_used,
        "n_fold_points": n_fold_points,
        "phase_seconds": phase_seconds,
        # P4-8: the sector-completeness record — how many
        # of the requested sectors the tool actually built
        # (len(TESS_images) vs len(sectors)). None when the
        # run failed before target construction.
        "sectors_requested": sectors_requested,
        "sectors_built": sectors_built,
        # PM-1: the background-scenario check did not pass
        # (it never ran, or it failed the run).
        "background_scenarios_checked": False,
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
    # Network-resilience record: per-phase wall seconds
    # (partial when a phase never started) and a
    # timestamped phase log that survives even if the
    # runner kills this process mid-run.
    phase_seconds = {}
    phase_log_path = os.path.join(workdir, "phase_log.txt")
    # P4-8: the sector-completeness record (see the
    # dropped-sector check after target construction).
    # Initialised here so _failed can report them even when
    # the run dies before construction.
    sectors_requested = None
    sectors_built = None

    def _log_phase(msg):
        line = (f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} "
                f"{msg}")
        print(line, flush=True)
        try:
            with open(phase_log_path, "a") as fh:
                fh.write(line + "\n")
        except OSError:
            pass

    def _failed(reason):
        warnings.append(reason)
        artifacts = ([phase_log_path]
                     if os.path.exists(phase_log_path) else [])
        return _output(
            tool_version, seed, config_hash, "failed", None,
            _null_metrics(dilution_corrected,
                          contrast_curve_used,
                          n_fold_points,
                          phase_seconds or None,
                          sectors_requested,
                          sectors_built),
            input_hashes, artifacts, warnings,
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
    sectors_requested = len(sectors)

    # ---- run the tool ------------------------------------------
    try:
        from triceratops.triceratops import target
    except ImportError as exc:
        return _failed(f"triceratops is not importable in "
                       f"this venv: {exc}")
    # Network resilience: bound every socket read (a
    # stalled socket raises after this long with no bytes;
    # a flowing download is unaffected), and make stdout
    # line-buffered so the tool's own per-sector prints
    # land in the log live instead of dying in the buffer
    # when the process is killed.
    socket_timeout_s = _env_int("TRICERATOPS_SOCKET_TIMEOUT_S",
                                SOCKET_TIMEOUT_S)
    init_timeout_s = _env_int("TRICERATOPS_INIT_TIMEOUT_S",
                              TARGET_INIT_TIMEOUT_S)
    init_attempts = max(1, _env_int(
        "TRICERATOPS_INIT_ATTEMPTS", TARGET_INIT_ATTEMPTS))
    socket.setdefaulttimeout(socket_timeout_s)
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except (AttributeError, ValueError):
        pass
    _log_phase(f"network budgets: socket_timeout="
               f"{socket_timeout_s}s target_init="
               f"{init_timeout_s}s x{init_attempts} attempt(s)")
    # Target construction is the network phase (MAST TIC
    # cone + Gaia background + one TessCut fetch per
    # sector) and the phase that hung on 2026-11-16, so it
    # gets the alarm and the retry; a non-network error
    # still fails fast with no retry.
    # P4-8: run the tool phases from the workdir, so the
    # Gaia background CSV the tool writes on a live query
    # (<tic>_gaia_background.csv — funcs.py:840, a relative
    # path, i.e. the process cwd) lands in the run workdir
    # instead of the repo root (clean worktree). The light
    # curve is already loaded; the contrast-curve path is
    # absolutised first so calc_probs still finds it after
    # the chdir. A failed chdir is non-fatal (the run
    # proceeds; the CSV may land in the repo root as
    # before) and is recorded as a warning.
    if cc_path:
        cc_path = os.path.abspath(cc_path)
    try:
        os.chdir(workdir)
    except OSError as exc:
        warnings.append(f"could not chdir to the run workdir "
                        f"({exc}); the Gaia CSV may land in "
                        f"the repo root")
        _log_phase(f"chdir to workdir failed: {exc}")
    trilegal_fname = _cached_gaia_population(tic)
    if trilegal_fname:
        _log_phase("reusing cached Gaia population "
                   f"{trilegal_fname}")
    tgt = None
    last_error = None
    for attempt in range(1, init_attempts + 1):
        np.random.seed(seed)
        _log_phase(f"target_init attempt {attempt}/"
                   f"{init_attempts} (TIC {tic}, sectors "
                   f"{sectors})")
        t_init = time.monotonic()
        try:
            with _phase_timeout("target_init", init_timeout_s):
                tgt = target(ID=int(tic),
                             sectors=np.array(sectors),
                             search_radius=SEARCH_RADIUS_PX,
                             trilegal_fname=trilegal_fname)
        except _PhaseTimeout as exc:
            last_error = str(exc)
            _log_phase(f"target_init attempt {attempt} "
                       f"TIMED OUT after {exc.budget_s}s")
            continue
        except (TimeoutError, ConnectionError,
                OSError) as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            _log_phase(f"target_init attempt {attempt} "
                       f"network error: {last_error}")
            continue
        except Exception as exc:  # noqa: BLE001 - non-network
            return _failed(f"target construction raised "
                           f"{type(exc).__name__}: {exc}")
        phase_seconds["target_init"] = time.monotonic() - t_init
        _log_phase(f"target_init attempt {attempt} done in "
                   f"{phase_seconds['target_init']:.1f}s")
        break
    if tgt is None:
        return _failed(f"target construction failed after "
                       f"{init_attempts} attempt(s): "
                       f"{last_error}")
    # P4-8: fail loudly on dropped sectors. The tool's
    # per-sector TessCut loop (triceratops.py ~242) catches
    # every exception, prints "Sector N raised exception.
    # Ignoring for validation." and continues — a stalled
    # fetch (or a swallowed phase timeout) silently drops
    # the sector and the tool returns with fewer images
    # than requested sectors. self.sectors is never
    # mutated, so the only honest record of what was built
    # is len(TESS_images). A shortfall fails the run: an
    # FPP computed on a subset of the requested sectors is
    # a partial result, never a completion. A missing
    # TESS_images attribute is the same failure (the
    # completeness is unverifiable).
    sectors_built = len(getattr(tgt, "TESS_images", None)
                        or [])
    if sectors_built != sectors_requested:
        _log_phase(f"SECTOR DROP: built {sectors_built} of "
                   f"{sectors_requested} requested sectors")
        return _failed(f"dropped sectors during target "
                       f"construction: built {sectors_built} "
                       f"of {sectors_requested} requested "
                       f"sectors (the tool silently skipped "
                       f"the rest); the FPP would be computed "
                       f"on a partial sector set")
    # PM-1: fail closed on a silently skipped background
    # population. If the Gaia query failed, the tool sets
    # trilegal_missing and omits the background scenarios
    # from the probability table — the FPP it would then
    # report was computed without them. Catch it here,
    # before the expensive calc_probs, instead of trusting
    # the number. No retry: the brief's condition is
    # fail-closed (a retry-on-trilegal-missing is a
    # possible 3.1 enhancement, not this build).
    if getattr(tgt, "trilegal_missing", False):
        _log_phase("target_init done but trilegal_missing "
                   "is set: background population skipped")
        return _failed("background population missing "
                       "(trilegal_missing): the tool skipped "
                       "the background scenarios; the FPP "
                       "would be computed without them")
    np.random.seed(seed)
    try:
        t_phase = time.monotonic()
        tgt.calc_depths(tdepth=depth_frac,
                        dilution_corrected=dilution_corrected)
        phase_seconds["calc_depths"] = time.monotonic() - t_phase
        _log_phase(f"calc_depths done in "
                   f"{phase_seconds['calc_depths']:.1f}s")
        t_phase = time.monotonic()
        tgt.calc_probs(ph_bin, f_bin, flux_err, P_orb=period,
                       contrast_curve_file=cc_path,
                       N=n_samples, exptime=cadence_s / 86400.0,
                       nsamples=20, verbose=0,
                       dilution_corrected=dilution_corrected)
        phase_seconds["calc_probs"] = time.monotonic() - t_phase
        _log_phase(f"calc_probs done in "
                   f"{phase_seconds['calc_probs']:.1f}s")
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
    # PM-1: verify the background scenarios are present in
    # the probability table — a silent skip must fail the
    # run, never report an FPP. Skipped for a degenerate
    # computation: its table is meaningless and the
    # degenerate flag already marks the run invalid (the
    # adapter maps it to UNMEASURED).
    background_scenarios_checked = False
    if not degenerate:
        missing = _missing_background_scenarios(probs)
        if missing:
            return _failed("background scenarios missing "
                           "from the probability table: "
                           + ", ".join(missing) +
                           " — the background population "
                           "was silently skipped; FPP is "
                           "not valid")
        background_scenarios_checked = True
        _log_phase("background check passed: 6/6 background "
                   "scenarios present")
    probs_path = os.path.join(workdir,
                              "triceratops_probs.csv")
    try:
        probs.to_csv(probs_path, index=False)
        artifacts = [probs_path]
    except Exception:  # noqa: BLE001 - evidence write failure
        artifacts = []
        warnings.append("could not write the scenario table")
    if os.path.exists(phase_log_path):
        artifacts.append(phase_log_path)
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
        "phase_seconds": phase_seconds,
        # P4-8: the sector-completeness record — equal here
        # (the run fails loudly above on any shortfall).
        "sectors_requested": sectors_requested,
        "sectors_built": sectors_built,
        "background_scenarios_checked":
            background_scenarios_checked,
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
    # P4-8: run() chdirs to the workdir, so relative argv
    # paths must be resolved against the CALLER's cwd
    # BEFORE the run — resolving them after run() would
    # nest them under the workdir (the first Mac fast smoke
    # failed all three targets this way).
    args.input = os.path.abspath(args.input)
    args.output = os.path.abspath(args.output)
    out = run(args.input, args.output)
    with open(args.output, "w") as fh:
        json.dump(out, fh, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
