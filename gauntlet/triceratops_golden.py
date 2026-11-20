"""TRICERATOPS golden-fixture checks (Phase 3, P3-7 / P3-8).

One definition of "the golden test passes", shared by the
offline CI assertions (tests/test_triceratops_golden.py) and
the Mac nightly driver (scripts/triceratops_golden_nightly.py)
— the two must never drift apart.

A fixture is one JSON per target under
tests/fixtures/triceratops/ (see that directory's README):
the C-10 tool output + a scenario split + per-seed results +
the TB-4 `expected` block (tolerance bands, never exact
floats — TRICERATOPS fetches neighbours and TRILEGAL
remotely, so identical inputs do not guarantee
bitwise-identical output).

check_fixture_output() asserts a fresh tool output against
its fixture: the disposition (via the adapter, under the
given policy) plus the expected bands. check_seed_stability()
is the TB-4 seed check: same disposition across seeds AND
the FPP band clear of the decision boundaries.

FPP REPORTING POLICY (CC-4, Phase 4 completion vote) — the
rule every FPP report follows (Gaia-path, no contrast
curve):
  * Run >= 5 FIXED seeds (MIN_SEEDS_FOR_BAND). No single-seed
    FPP is ever quoted — one seed is a coin flip (TB-4: five
    WASP-29b seeds span [0.001776, 0.379185], a ~210x spread;
    one seed reads PASS while the other four read
    INCONCLUSIVE).
  * Quote the MEDIAN FPP as the central measurement, with the
    full [min, max] band, the per-seed values, N, and the
    convergence status. (WASP-29b median 0.168578 ->
    INCONCLUSIVE.)
  * BP-3 amendment (bulk_v6 step 6): the HEADLINE FPP is the
    MAX seed, not the median — on Zorro the median 0.003446
    reads PASS while the max 0.016801 reads FAIL, and the max
    is the honest headline. The median [min, max] is retained
    alongside it; the PASS rule is unchanged (every seed <=
    0.015). summarize_seed_band() is the one definition of
    the summary; the desk caller runs BP3_SEEDS (20261114–
    20261118) and aggregates via aggregate_triceratops_results.
  * PASS requires EVERY seed to pass (max FPP <= 0.015, the
    fpp_validate_max bar). A median that passes while one
    seed fails is not a PASS.
  * A target that passes in only some seeds cannot validate
    here and stays supporting-evidence-only (WASP-29b: 1 of
    5 seeds passing).
The stability assertion (check_seed_stability) is never
silently replaced: while the WASP-29b band fails it, the
golden test carries a STRICT xfail (BM-3) — the assertion
stays verbatim and XPASS-strict is the tripwire.
"""
import json
from pathlib import Path

FIXTURE_DIR = (Path(__file__).resolve().parent.parent
               / "tests" / "fixtures" / "triceratops")

# TB-4: a band's width comes from >= 5 seeds, never invented.
MIN_SEEDS_FOR_BAND = 5

# BP-3 (PIPE50-2, bulk_v6 step 6): the 5 deterministic
# validation seeds — the Zorro list (20261114–20261118).
# confirm_triceratops defaults to these seeds: the desk
# gauntlet runs the tool once per seed and aggregates.
# The policy's single seed (external_tools_v3, 20261114)
# is the FIRST of the five — the nightly's single-seed
# run is that seed, tagged PROVISIONAL_TRIAGE.
BP3_SEEDS = (20261114, 20261115, 20261116, 20261117, 20261118)

# A single-seed FPP is not a validation measurement
# (TB-4) — it is triage evidence only. Single-seed runs
# are tagged with this status wherever the template
# quotes them (scores, review item, nightly receipt).
SEED_STATUS_PROVISIONAL = "PROVISIONAL_TRIAGE"


def summarize_seed_band(seeds, policy):
    """The BP-3 seed-band summary for one target.

    seeds: [{seed, fpp, nfpp, ...}] — the fixture `seeds`
    shape (one entry per tool run). policy: the
    external-tools policy dict (its ["triceratops"]
    section carries the validation bars).
    Returns {"fpp_median", "fpp_band": [min, max],
    "per_seed": [{seed, fpp, nfpp}] in input order,
    "n_seeds", "headline_fpp" (the MAX seed — the honest
    headline, CC-4 display amendment: on Zorro the median
    0.003446 reads PASS while the max 0.016801 reads FAIL),
    "headline_nfpp" (max NFPP), "validates" (every seed
    clears the validation bars — max FPP <=
    fpp_validate_max AND max NFPP <= nfpp_validate_max),
    "seed_status" ("PROVISIONAL_TRIAGE" when n_seeds == 1,
    else None)}.
    Raises ValueError on an empty list (a band from zero
    seeds is unmeasured, not zero). A null or NaN FPP
    cannot pass: the band/median/headline are computed
    over the measured seeds, and validates is False when
    any seed is null or NaN (all-NaN: band/median/headline
    are NaN; the per_seed list still shows every seed).
    """
    import math
    import statistics
    if not seeds:
        raise ValueError("seed band needs >= 1 seed, got 0")
    per_seed = []
    fpps = []
    nfpps = []
    unmeasured = False
    for entry in seeds:
        fpp = entry.get("fpp")
        nfpp = entry.get("nfpp")
        per_seed.append({"seed": entry.get("seed"),
                         "fpp": fpp, "nfpp": nfpp})
        if fpp is None or (isinstance(fpp, float)
                           and math.isnan(fpp)):
            unmeasured = True
        else:
            fpps.append(fpp)
        if nfpp is None or (isinstance(nfpp, float)
                            and math.isnan(nfpp)):
            unmeasured = True
        else:
            nfpps.append(nfpp)
    if fpps:
        lo, hi = min(fpps), max(fpps)
        median = statistics.median(fpps)
    else:
        lo = hi = median = float("nan")
    headline_nfpp = max(nfpps) if nfpps else None
    tri = policy["triceratops"]
    validates = (
        not unmeasured
        and bool(fpps)
        and hi <= tri["fpp_validate_max"]
        and headline_nfpp is not None
        and headline_nfpp <= tri["nfpp_validate_max"])
    return {
        "fpp_median": median,
        "fpp_band": [lo, hi],
        "per_seed": per_seed,
        "n_seeds": len(seeds),
        "headline_fpp": hi,
        "headline_nfpp": headline_nfpp,
        "validates": bool(validates),
        "seed_status": (SEED_STATUS_PROVISIONAL
                        if len(seeds) == 1 else None),
    }


def load_fixture(tic):
    """One golden fixture dict (raises FileNotFoundError when
    the target has no fixture — TOI-700 c until measured)."""
    with open(FIXTURE_DIR / f"{tic}.json") as fh:
        return json.load(fh)


def fixture_tics():
    """TICs with a committed golden fixture, sorted."""
    return sorted(p.stem for p in FIXTURE_DIR.glob("[0-9]*.json"))


def scenario_from_probs_csv(path):
    """Per-scenario probabilities from a TRICERATOPS probs
    CSV (the wrapper's triceratops_probs.csv artifact):
    {scenario_lower: summed_prob}. Rows carry `scenario`,
    `prob`, `ID` (see run_triceratops._scenario_sum — this
    is the same name-based sum, stdlib-only so the nightly
    does not depend on pandas). Returns {} when the file
    cannot be read (the caller treats a missing split as
    "STP check skipped", never as a pass or a fail on its
    own — the disposition + FPP/NFPP bounds still apply).
    """
    import csv
    totals = {}
    try:
        with open(path, newline="") as fh:
            for row in csv.DictReader(fh):
                try:
                    totals[row["scenario"].lower()] = (
                        totals.get(row["scenario"].lower(), 0.0)
                        + float(row["prob"]))
                except (KeyError, ValueError, TypeError):
                    continue
    except OSError:
        return {}
    return totals


def check_fixture_output(fixture, output, policy, scenario=None):
    """Assert a tool output against its fixture. Returns a
    list of failure strings (empty = pass).

    fixture: the fixture dict. output: a TRICERATOPS output
    JSON (schema shape — the adapter input). policy: the
    external-tools policy dict (its ["triceratops"] section
    carries the bars). scenario: the FRESH run's
    per-scenario split (from scenario_from_probs_csv) — when
    None, the fixture's own `scenario` block is used (the CI
    case, where the output under test IS the fixture's
    recorded output). Checks, in order: the disposition
    under the policy equals expected.status; the FPP/NFPP
    hard bounds; the STP-dominance check where a scenario
    split is available (the STP-split BAND needs >= 5 seeds
    and is checked by check_seed_stability, not here).
    The caller validates the output against the schema first
    (validate_triceratops_output) — this function assumes a
    well-formed output.
    """
    from gauntlet.stage_result import triceratops_result
    failures = []
    expected = fixture["expected"]
    res = triceratops_result(output, policy=policy)
    if res.status != expected["status"]:
        failures.append(
            f"disposition {res.status} != expected "
            f"{expected['status']} (FPP "
            f"{output['metrics']['fpp']})")
    fpp = output["metrics"]["fpp"]
    nfpp = output["metrics"]["nfpp"]
    if fpp is None:
        failures.append("FPP is null (no measurement)")
        return failures
    if "fpp_min" in expected and fpp < expected["fpp_min"]:
        failures.append(f"FPP {fpp} below fpp_min "
                        f"{expected['fpp_min']}")
    if "fpp_max" in expected and fpp >= expected["fpp_max"]:
        failures.append(f"FPP {fpp} at/above fpp_max "
                        f"{expected['fpp_max']}")
    if "nfpp_max" in expected:
        if nfpp is None:
            failures.append("NFPP is null (no measurement)")
        elif nfpp >= expected["nfpp_max"]:
            failures.append(f"NFPP {nfpp} at/above nfpp_max "
                            f"{expected['nfpp_max']}")
    if scenario is None:
        scenario = fixture.get("scenario") or {}
    if ("stp_share_min" in expected and "stp" in scenario
            and fpp > 0):
        share = scenario["stp"] / fpp
        if share < expected["stp_share_min"]:
            failures.append(
                f"STP share of FPP {share:.2f} below "
                f"{expected['stp_share_min']}")
    return failures


def check_seed_stability(seeds, policy):
    """Seed-stability with boundary separation (TB-4).

    seeds: [{seed, fpp, nfpp, ...}] with >= MIN_SEEDS_FOR_BAND
    entries. policy: the external-tools policy dict.
    Returns (ok, reason). ok requires: every seed's FPP maps
    to the SAME decision region (below the validate bar /
    between the bars / above the refute bar — NFPP checked
    separately by the caller where it matters), AND the FPP
    band [min, max] does not touch either boundary — the
    disposition must have adequate separation from the
    decision boundary, not merely agree across seeds.
    Raises ValueError when fewer than MIN_SEEDS_FOR_BAND
    seeds are supplied (the band is unmeasured, not zero).
    """
    from gauntlet.stage_result import triceratops_disposition
    if len(seeds) < MIN_SEEDS_FOR_BAND:
        raise ValueError(
            f"seed band needs >= {MIN_SEEDS_FOR_BAND} seeds, "
            f"got {len(seeds)}")
    tri = policy["triceratops"]
    fpp_max = tri["fpp_validate_max"]
    fpp_refute = tri["fpp_refute_min"]
    statuses = set()
    fpps = []
    for entry in seeds:
        status, _ = triceratops_disposition(
            entry["fpp"], entry.get("nfpp", 0.0), False, policy)
        statuses.add(status)
        fpps.append(entry["fpp"])
    if len(statuses) != 1:
        return False, (f"disposition varies across seeds: "
                       f"{sorted(statuses)}")
    lo, hi = min(fpps), max(fpps)
    for boundary in (fpp_max, fpp_refute):
        if lo <= boundary <= hi:
            return False, (f"FPP band [{lo:.4f}, {hi:.4f}] "
                           f"touches the {boundary} boundary")
    return True, (f"stable: {statuses.pop()} across "
                  f"{len(seeds)} seeds, FPP band [{lo:.4f}, "
                  f"{hi:.4f}] clear of {fpp_max}/{fpp_refute}")
