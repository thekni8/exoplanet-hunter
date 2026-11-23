"""Phase 5.6: coherent joint multi-sector fit (DESIGN_5_6.md, vote
V56-20261123, RATIFIED 2026-11-23 23:06 IST, path (a)).

Stage J1 extracts the top-15 BLS peaks from the stitched pass-2
periodogram (the hunter.py _bls_best pattern, VERBATIM), refines each
on the fine local grid (+-1.5%, 800 points), de-duplicates harmonic
families on the refined values, and keeps the top 3 distinct signals.

Stage J2 fits a box transit (P, T0, duration, depth COMMON across
sectors + one flux offset per sector) to the per-sector K=2-masked
arrays, weights 1/sigma_s^2. Optimizer (C1, ratified): variable
projection (closed-form weighted linear least squares for depth +
offsets) + scipy.optimize.minimize (Powell) over (P, T0, duration).
`least_squares`/trf is FORBIDDEN: its default finite-difference step
moves zero cadences across the box edge, so the Jacobian columns for
(P, T0, duration) are exactly zero and the fitter silently returns
J1's grid ephemeris (proven numerically, 5-6-vote/p6p9_check.py; the
C1 unit test in tests/test_joint_fit.py reproduces the control).

Bounds (P10) are enforced in the objective (a penalty wall outside
the box) plus best-in-bounds tracking -- NOT via scipy's `bounds`
parameter, deliberately. scipy's BOUNDED Powell line search
(_minimize_scalar_bounded) searches the ENTIRE bound interval by
golden section and ignores the direction scale, so on the box
objective's narrow valley it never samples the valley: measured on
the p6p9 toy (2026-11-23, scipy 1.18.1), bounded Powell lands at
chi2 75592.6 / P err -7.4e-4 d, while unbounded Powell with the
frozen direction scales + penalty lands at chi2 74961.7 / P err
-1.5e-4 d (truth chi2 74933.9). The unbounded-Brent line search
brackets outward from the direction scale, which is the behaviour
the frozen step scales (dP = 1e-4*P, dT0 = 0.01 d, dD = 0.01 d)
assume. The returned point is always the best IN-BOUNDS point
evaluated, so the bounds ARE enforced on the output; the penalty
steers the search back inside. The fit also never returns a point
worse than its start (Powell's line search can accept a worse point
on a step-function objective -- observed on the toy, where the
returned point was chi2 76526.7 against a best-evaluated 75592.6).

Selection (C2, ratified): highest dchi2 = chi2_null - chi2_model
wins (offsets-only null on identical masked data); tie (dchi2 within
1%, or |dchi2_1 - dchi2_2| < 1.0) -> higher originating BLS SDE.
Total-chi2 selection and total-chi2 tie-breakers are FORBIDDEN (the
1% band on total chi2 ~ 550-750 exceeds a threshold planet's whole
dchi2 signal ~ 81-225; COMPARISON R2).

Fallback (P15): all 3 fits fail -> the caller keeps the stitched-BLS
ephemeris; this module reports fitted=False and never deletes a
baseline result. A6: hitting the 200-evaluation cap with finite
chi2, dchi2 > 0, depth > 0 counts as CONVERGED, flagged
hit_max_nfev; otherwise a cap-hit is a failure.

Diagnostics (B1/A7/B2/B3): run_joint_fit returns per-trial top-15 /
top-3 period-inclusion tracking (1% period-matching, when the
injected period is given), fallback accounting (entered / no usable
candidate / fitted / failed / fallback, with denominators), and J1
+ J2 wall seconds separately. All returned values are JSON-safe
(plain floats/ints/bools/strings/None/lists).

Pure functions where possible; no I/O, no downloads, no BLS search
(the coarse periodogram is an INPUT -- re-running the coarse BLS
inside the joint fit is forbidden; J1's refinement evaluates only
the 800-point local grids, which is part of J1 by design).
"""

import time

import numpy as np
from scipy.optimize import minimize

import bulk_screen as bs

# Frozen parameters (DESIGN_5_6.md section 4, as amended).
N_PEAKS = 15  # P2: top-15 extraction (N=15 measured, TOI-700 b)
N_FIT_SIGNALS = 3  # P5: top-3 distinct refined signals are fitted
REFINE_SPAN = 0.015  # P3: fine local grid +-1.5%
REFINE_POINTS = 800  # P3: 800 points per peak
REFINE_ADOPT_SDE_DROP = 1.0  # P3: adopt iff refined SDE >= coarse - 1.0
DEDUP_RATIO_MAX = 8  # P4: harmonic ratios m/n, m,n <= 8
DEDUP_WINDOW = 0.002  # P4: +-0.2% dedup window on refined values
SUBHARMONIC_FACTORS = (1.0, 0.5, 1.0 / 3.0, 0.25)  # P2: peak + P/2,P/3,P/4
SUBHARMONIC_WINDOW = 0.02  # P2: +-2% sub-harmonic masking
MAX_NFEV = 200  # P12: max objective evaluations per signal
POWELL_XTOL = 1e-8  # P12: Powell tolerances
POWELL_FTOL = 1e-8
TIE_REL = 0.01  # P13: dchi2 tie band, relative
TIE_ABS = 1.0  # P13: dchi2 tie band, absolute
PERIOD_MATCH_TOL = 0.01  # B1: 1% period-matching
MIN_SECTORS = 2  # the joint fit needs >= 2 sectors (section 2.1)
# Penalty wall outside the P10 bounds, in chi2 units above the null:
# any in-bounds point has chi2 <= chi2_null (depth=0 recovers the
# null), so chi2_null + PENALTY_BASE is worse than every in-bounds
# point; the quadratic term slopes back toward the box.
PENALTY_BASE = 1e4


# ---------------------------------------------------------------------------
# Stage J1 -- peak extraction (hunter.py _bls_best pattern, verbatim)
# ---------------------------------------------------------------------------

def extract_peaks(periodogram):
    """Top-15 coarse peaks by SDE, masking each accepted peak's
    SUB-harmonics (P/2, P/3, P/4) at +-2% as well as the peak itself.
    Multiples (2P, 3P) are deliberately NOT masked (a true period can
    smear below its own P/2 alias coarsely while refining far above
    it -- TOI-700 c). periodogram carries periods/powers/depths/
    durations/transit_times/med/scale (the _screen_one exposure).
    Returns a list of candidate dicts (possibly empty)."""
    pv = np.asarray(periodogram["periods"], dtype=float)
    pw = np.asarray(periodogram["powers"], dtype=float)
    depths = np.asarray(periodogram["depths"], dtype=float)
    durations = np.asarray(periodogram["durations"], dtype=float)
    t0s = np.asarray(periodogram["transit_times"], dtype=float)
    med = float(periodogram["med"])
    scale = float(periodogram["scale"])
    work = (pw - med) / scale
    cands = []
    for _ in range(N_PEAKS):
        i = int(np.argmax(work))
        if not np.isfinite(work[i]):
            break
        cands.append({
            "period": float(pv[i]),
            "sde": float(work[i]),
            "depth": float(depths[i]),
            "duration": float(durations[i]),
            "t0": float(t0s[i]),
            "detector": "BLS",
        })
        for q in SUBHARMONIC_FACTORS:
            hp = float(pv[i]) * q
            work[np.abs(pv - hp) <= SUBHARMONIC_WINDOW * hp] = -np.inf
    if not cands:
        # hunter.py fallback: the raw-power argmax, when finite.
        i = int(np.argmax(pw))
        if np.isfinite(pw[i]):
            cands = [{
                "period": float(pv[i]),
                "sde": float((pw[i] - med) / scale),
                "depth": float(depths[i]),
                "duration": float(durations[i]),
                "t0": float(t0s[i]),
                "detector": "BLS",
            }]
    return cands


def refine_peak(bls, cand, med, scale, durations):
    """Refine one candidate on the fine local grid (+-1.5%, 800
    points) -- hunter.py _refine_one, verbatim. Adopts the refined
    values only if the refined SDE is no more than 1.0 below the
    coarse SDE; otherwise (or on any failure) the coarse values
    stand."""
    try:
        fine = np.linspace(cand["period"] * (1.0 - REFINE_SPAN),
                           cand["period"] * (1.0 + REFINE_SPAN),
                           REFINE_POINTS)
        fres = bls.power(fine, list(durations))
        fi = int(np.argmax(fres.power))
        fsde = float((fres.power[fi] - med) / scale)
        if fsde >= cand["sde"] - REFINE_ADOPT_SDE_DROP:
            return {
                "period": float(np.asarray(fres.period)[fi]),
                "sde": fsde,
                "depth": float(np.asarray(fres.depth)[fi]),
                "duration": float(np.asarray(fres.duration)[fi]),
                "t0": float(np.asarray(fres.transit_time)[fi]),
                "detector": "BLS",
            }
    except Exception:
        pass
    return dict(cand)


def dedup_peaks(refined):
    """De-duplicate harmonic families on the REFINED values: sort by
    refined SDE and greedily accept, dropping any peak whose period
    is a small rational multiple (m/n, m,n <= 8) of an accepted
    signal within a +-0.2% window. hunter.py _bls_best, verbatim."""
    ordered = sorted(refined, key=lambda c: c["sde"], reverse=True)
    ratios = sorted({m / n for m in range(1, DEDUP_RATIO_MAX + 1)
                     for n in range(1, DEDUP_RATIO_MAX + 1)})
    distinct = []
    for c in ordered:
        dup = False
        for a in distinct:
            ratio = c["period"] / a["period"]
            for r in ratios:
                if abs(ratio - r) <= DEDUP_WINDOW * r:
                    dup = True
                    break
            if dup:
                break
        if not dup:
            distinct.append(c)
    return distinct


def extract_top3(periodogram, t, f, durations=None):
    """Stage J1: top-15 extraction + per-peak fine refinement +
    harmonic dedup -> top-3 distinct refined signals. (t, f) is the
    PREPROCESSED stitched masked curve (the same arrays the pass-2
    BLS saw); a BoxLeastSquares object is built on it for the local
    refinement grids only -- the coarse search is never re-run.
    Returns {"top3", "top15_coarse", "top15_refined", "seconds_j1"}.
    durations defaults to the live calibration's BLS grid."""
    t_start = time.time()
    if durations is None:
        durations = bs.BLS_DURATIONS_D
    med = float(periodogram["med"])
    scale = float(periodogram["scale"])
    coarse = extract_peaks(periodogram)
    top3 = []
    refined = []
    if coarse:
        from astropy.timeseries import BoxLeastSquares
        bls = BoxLeastSquares(np.asarray(t, dtype=float),
                              np.asarray(f, dtype=float))
        refined = [refine_peak(bls, c, med, scale, durations)
                   for c in coarse]
        top3 = dedup_peaks(refined)[:N_FIT_SIGNALS]
    return {"top3": top3, "top15_coarse": coarse,
            "top15_refined": refined,
            "seconds_j1": time.time() - t_start}


# ---------------------------------------------------------------------------
# Stage J2 -- coherent fit (variable projection + Powell)
# ---------------------------------------------------------------------------

class JointFitData:
    """Precomputed per-sector sums for the variable-projection solve.

    Model: f = offset_s - depth * I(t in transit), one depth COMMON
    across sectors, one offset per sector. Weights w = 1/sigma_s^2.
    For fixed (P, T0, duration) the linear parameters are solved in
    closed form from the normal equations, which need only per-sector
    weighted sums -- O(N) per evaluation, no matrix build. Flux is
    centred (g = f - 1) for conditioning; the offsets absorb the mean,
    so the model is identical. Verified against a brute-force weighted
    lstsq: chi2 agrees to ~1e-11 (see tests/test_joint_fit.py).

    sectors is a list of dicts with t/f (preprocessed, K=2-masked)
    and sigma (sector_sigma of the preprocessed sector curve, the
    same sigmas the stitch uses). Sectors with no cadences or no
    usable sigma must be filtered by the caller.
    """

    def __init__(self, sectors):
        self.n_sectors = len(sectors)
        t_list = [np.asarray(s["t"], dtype=float) for s in sectors]
        self.t = np.concatenate(t_list)
        self._g = np.concatenate(
            [np.asarray(s["f"], dtype=float) - 1.0 for s in sectors])
        self.sec_idx = np.concatenate(
            [np.full(len(t), k, dtype=int)
             for k, t in enumerate(t_list)])
        self.w = np.concatenate(
            [np.full(len(t), 1.0 / float(s["sigma"]) ** 2)
             for t, s in zip(t_list, sectors)])
        self.W = np.bincount(self.sec_idx, weights=self.w,
                             minlength=self.n_sectors)
        self.WG = np.bincount(self.sec_idx, weights=self.w * self._g,
                              minlength=self.n_sectors)
        self.WG2 = float(np.sum(self.w * self._g * self._g))
        # Offsets-only null: per-sector weighted mean.
        self.chi2_null = float(
            self.WG2 - np.sum(self.WG * self.WG / self.W))
        self.t_median = float(np.median(self.t))

    def solve(self, period, t0, duration):
        """Closed-form weighted LS at (period, t0, duration).
        Returns (chi2, depth, offsets). depth=0 with chi2_null when
        no cadence is in transit or the normal equations degenerate
        (every cadence in transit -- impossible for D < P on a real
        sector, guarded anyway)."""
        ph = ((self.t - t0 + 0.5 * period) % period) - 0.5 * period
        in_tr = np.abs(ph) < 0.5 * duration
        off_null = self.WG / self.W
        if not in_tr.any():
            return self.chi2_null, 0.0, off_null
        wi = self.w * in_tr
        WIs = np.bincount(self.sec_idx, weights=wi,
                          minlength=self.n_sectors)
        WIG = float(np.sum(wi * self._g))
        WI = float(np.sum(WIs))
        denom = WI - float(np.sum(WIs * WIs / self.W))
        if denom <= 0.0:
            return self.chi2_null, 0.0, off_null
        depth = (float(np.sum(WIs * self.WG / self.W)) - WIG) / denom
        off = (self.WG + WIs * depth) / self.W
        chi2 = (self.WG2 - 2.0 * float(np.sum(off * self.WG))
                + 2.0 * depth * WIG
                + float(np.sum(off * off * self.W
                               - 2.0 * off * depth * WIs
                               + depth * depth * WIs)))
        return chi2, depth, off


def fit_signal(data, candidate, max_nfev=MAX_NFEV):
    """Fit one J1 signal with variable projection + Powell.

    x0 is the refined BLS ephemeris, with T0 mapped to the transit
    nearest the baseline median time (P11). Bounds (P10): P +-1.5%
    of the refined period, T0 +-0.5*P, duration [0.04, 0.25] d,
    depth > 0 (a non-positive fitted depth is a fit FAILURE, not a
    detection). Initial step scales (P9): dP = 1e-4*P, dT0 = 0.01 d,
    dD = 0.01 d. max_nfev defaults to the frozen 200 (P12); tests
    may pass a smaller value to exercise the A6 cap-hit rule.

    Returns a JSON-safe dict: fitted (P, T0, duration, depth),
    chi2, dchi2 vs the offsets-only null, converged, hit_max_nfev,
    n_evaluations, seconds, origin_sde, and error (None on success).
    The returned point is the best IN-BOUNDS point evaluated -- never
    worse than the start, never out of bounds."""
    t_start = time.time()
    p0 = float(candidate["period"])
    t0_raw = float(candidate["t0"])
    d0 = float(candidate["duration"])
    k = float(np.round((data.t_median - t0_raw) / p0))
    t0_0 = t0_raw + k * p0
    x0 = np.array([p0, t0_0, d0])
    lo = np.array([p0 * (1.0 - REFINE_SPAN), t0_0 - 0.5 * p0, 0.04])
    hi = np.array([p0 * (1.0 + REFINE_SPAN), t0_0 + 0.5 * p0, 0.25])
    half = 0.5 * (hi - lo)
    chi2_0, _depth_0, _off_0 = data.solve(x0[0], x0[1], x0[2])
    best = {"x": x0.copy(), "chi2": float(chi2_0)}
    n_eval = [0]

    def objective(x):
        n_eval[0] += 1
        if np.all(x >= lo) and np.all(x <= hi):
            c, _d, _o = data.solve(x[0], x[1], x[2])
            if np.isfinite(c) and c < best["chi2"]:
                best["x"] = np.array(x, dtype=float)
                best["chi2"] = float(c)
            return c
        v = float(np.max(np.maximum((lo - x) / half, (x - hi) / half)))
        return data.chi2_null + PENALTY_BASE * (1.0 + v * v)

    error = None
    try:
        res = minimize(
            objective, x0, method="Powell",
            options={"xtol": POWELL_XTOL, "ftol": POWELL_FTOL,
                     "maxfev": max_nfev,
                     "direc": np.diag([1e-4 * p0, 0.01, 0.01])})
        powell_success = bool(res.success)
    except Exception as exc:  # noqa: BLE001 -- a crashed optimizer
        # is a fit failure, never a campaign error.
        error = "%s: %s" % (type(exc).__name__, exc)
        powell_success = False
    bx = best["x"]
    chi2, depth, _off = data.solve(bx[0], bx[1], bx[2])
    dchi2 = data.chi2_null - chi2
    hit_max = bool(n_eval[0] >= max_nfev)
    # A6: a cap-hit counts as converged iff finite chi2, dchi2 > 0,
    # depth > 0 -- the same conditions as any other termination, so
    # one check covers both. An optimizer exception is a failure.
    converged = bool(error is None and np.isfinite(chi2)
                     and dchi2 > 0 and depth > 0)
    return {
        "period": float(bx[0]),
        "t0": float(bx[1]),
        "duration": float(bx[2]),
        "depth": float(depth),
        "chi2": float(chi2),
        "dchi2": float(dchi2),
        "chi2_null": float(data.chi2_null),
        "converged": converged,
        "hit_max_nfev": hit_max,
        "powell_success": powell_success,
        "n_evaluations": int(n_eval[0]),
        "seconds": time.time() - t_start,
        "origin_sde": float(candidate["sde"]),
        "error": error,
    }


def select_winner(fits):
    """C2: the converged fit with the HIGHEST dchi2 wins; tie (dchi2
    within 1% of the max, or |dchi2_1 - dchi2_2| < 1.0) -> higher
    originating BLS SDE. Never total chi2. Returns None when no fit
    converged (the caller falls back to the BLS ephemeris)."""
    ok = [f for f in fits if f["converged"]]
    if not ok:
        return None
    best_d = max(f["dchi2"] for f in ok)
    band = max(TIE_REL * best_d, TIE_ABS)
    tied = [f for f in ok if best_d - f["dchi2"] <= band]
    return max(tied, key=lambda f: f["origin_sde"])


def _period_match(periods, period_inj):
    """(matched, rank): the best (lowest-index) entry of `periods`
    within 1% of period_inj, or (False, None)."""
    if period_inj is None:
        return False, None
    best_rank = None
    for i, p in enumerate(periods):
        if p is not None and abs(p - period_inj) / period_inj \
                <= PERIOD_MATCH_TOL:
            best_rank = i
            break
    return best_rank is not None, best_rank


def run_joint_fit(periodogram, t_stitched, f_stitched, sectors,
                  period_inj=None, durations=None):
    """Run the full joint fit for one trial (J1 + J2 + selection).

    periodogram is the _screen_one exposure (periods/powers/depths/
    durations/transit_times/med/scale); (t_stitched, f_stitched) is
    the PREPROCESSED stitched masked curve (J1's BLS object + the
    rescore input); sectors is a list of dicts with t/f/sigma per
    sector (preprocessed, K=2-masked). period_inj enables the B1
    diagnostics (None on the null leg).

    Returns a JSON-safe dict: fitted (bool), winner (ephemeris +
    fit stats, or None), signals (per-signal fit results),
    seconds_j1/seconds_j2, fallback / joint_fit_failed /
    no_usable_candidate flags, and diagnostics (A7 counts +
    denominators, B1 inclusion fields, top-15/top-3 period lists).
    Never raises on bad fit input: a J1 failure returns a
    no-usable-candidate result with the error recorded.
    """
    t_start = time.time()
    sectors_used = []
    sectors_dropped = []
    for s in sectors:
        sig = s.get("sigma")
        if len(np.asarray(s["t"])) == 0 or sig is None or sig <= 0:
            sectors_dropped.append(s.get("sector"))
        else:
            sectors_used.append(s)
    base = {
        "fitted": False,
        "fallback": True,
        "joint_fit_failed": False,
        "no_usable_candidate": False,
        "no_candidate_reason": None,
        "winner": None,
        "signals": [],
        "seconds_j1": 0.0,
        "seconds_j2": 0.0,
        "diagnostics": {
            "entered": False,
            "no_usable_candidate": False,
            "n_candidates": 0,
            "n_fitted": 0,
            "n_failed": 0,
            "fallback": True,
            "joint_fit_failed": False,
            "hit_max_nfev": 0,
            "seconds_j1": 0.0,
            "seconds_j2": 0.0,
            "sectors_used": [s.get("sector") for s in sectors_used],
            "sectors_dropped": sectors_dropped,
            "top15_periods": [],
            "top15_sdes": [],
            "top3_periods": [],
            "top3_sdes": [],
        },
    }
    if len(sectors_used) < MIN_SECTORS:
        base["no_usable_candidate"] = True
        base["no_candidate_reason"] = "fewer-than-2-sectors"
        base["diagnostics"]["no_usable_candidate"] = True
        base["diagnostics"]["no_candidate_reason"] = (
            "fewer-than-2-sectors")
        return base
    try:
        j1 = extract_top3(periodogram, t_stitched, f_stitched,
                          durations=durations)
    except Exception as exc:  # noqa: BLE001 -- a J1 failure falls
        # back to the BLS ephemeris, never errors the trial.
        base["no_usable_candidate"] = True
        base["no_candidate_reason"] = "j1-error"
        base["diagnostics"]["no_usable_candidate"] = True
        base["diagnostics"]["no_candidate_reason"] = "j1-error"
        base["diagnostics"]["error"] = "%s: %s" % (
            type(exc).__name__, exc)
        return base
    base["seconds_j1"] = float(j1["seconds_j1"])
    base["diagnostics"]["seconds_j1"] = float(j1["seconds_j1"])
    top3 = j1["top3"]
    coarse = j1["top15_coarse"]
    base["diagnostics"]["top15_periods"] = [
        float(c["period"]) for c in coarse]
    base["diagnostics"]["top15_sdes"] = [
        float(c["sde"]) for c in coarse]
    base["diagnostics"]["top3_periods"] = [
        float(c["period"]) for c in top3]
    base["diagnostics"]["top3_sdes"] = [
        float(c["sde"]) for c in top3]
    if not top3:
        base["no_usable_candidate"] = True
        base["no_candidate_reason"] = "no-j1-candidates"
        base["diagnostics"]["no_usable_candidate"] = True
        base["diagnostics"]["no_candidate_reason"] = (
            "no-j1-candidates")
        return base
    base["diagnostics"]["entered"] = True
    base["diagnostics"]["n_candidates"] = len(top3)
    data = JointFitData(sectors_used)
    t_j2 = time.time()
    signals = []
    for rank, cand in enumerate(top3):
        fit = fit_signal(data, cand)
        fit["origin_rank"] = rank
        fit["origin_period"] = float(cand["period"])
        signals.append(fit)
    seconds_j2 = time.time() - t_j2
    base["signals"] = signals
    base["seconds_j2"] = float(seconds_j2)
    base["diagnostics"]["seconds_j2"] = float(seconds_j2)
    base["diagnostics"]["n_fitted"] = len(signals)
    base["diagnostics"]["n_failed"] = sum(
        1 for f in signals if not f["converged"])
    base["diagnostics"]["hit_max_nfev"] = sum(
        1 for f in signals if f["hit_max_nfev"])
    winner = select_winner(signals)
    if winner is None:
        base["joint_fit_failed"] = True
        base["diagnostics"]["joint_fit_failed"] = True
        base["diagnostics"]["fallback"] = True
    else:
        base["fitted"] = True
        base["fallback"] = False
        base["winner"] = winner
        base["diagnostics"]["fallback"] = False
        base["diagnostics"]["winner_origin_rank"] = winner[
            "origin_rank"]
        base["diagnostics"]["winner_dchi2"] = float(
            winner["dchi2"])
    # B1: top-15/top-3 period-inclusion tracking (1% matching).
    if period_inj is not None:
        in15, rank15 = _period_match(
            [c["period"] for c in coarse], period_inj)
        in3, rank3 = _period_match(
            [c["period"] for c in top3], period_inj)
        won = False
        if winner is not None:
            won = abs(winner["period"] - period_inj) / period_inj \
                <= PERIOD_MATCH_TOL
        base["diagnostics"].update({
            "in_top15": bool(in15),
            "top15_rank": rank15,
            "in_top3": bool(in3),
            "top3_rank": rank3,
            # Every top-3 signal is fitted, so fitted == in_top3;
            # recorded explicitly (the protocol asks for the field).
            "injected_fitted": bool(in3),
            "injected_won": bool(won),
        })
    base["diagnostics"]["seconds_total"] = time.time() - t_start
    return base
