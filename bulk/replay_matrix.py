"""3B replay matrix (Phase 3, P3-11).

Candidate bulk_v4 gates replayed offline against survivor
records (dicts in the rescore-v3 schema). Every gate is a pure
function over row dicts — no I/O inside the gate functions, so
they are unit-testable on synthetic rows.

The gates and the adoption rule they are judged against are
pre-registered in docs/bulk_v4_adoption_rule.md (committed
before the replay ran). This module implements the rule's
candidate definitions exactly; it does not choose a threshold.

Constants reused from the frozen bulk_v3 profile
(calibration/bulk_v3.yaml) — no new threshold is invented here:
  survivor_sde 7.0, tier_a_mes 9.0, strong_event_snr 3.0,
  odd/even EB ratio 0.5 (bulk_screen.py ODD_EVEN_EB veto).

Candidate gates (rule doc §3):
  SDE-8.0 / SDE-9.0 / SDE-10.0 — SDE bars, replay-only.
  TWO-STRONG   — 2-event rows need both events strong (>= 3 sigma).
  TWO-COMBINED — 2-event rows need both strong AND mes_pink >= 9.0.
  PHASE-DEPTH  — >=2-event rows need odd_even_ratio >= 0.5
                 (depth consistency; the phase half is untestable
                 from rescore rows — see the rule doc).
  DEMOTE-SYS   — tier-B rows with near_systematic demoted.
  EPOCH-CLUSTER — SECTOR_EPOCH_CLUSTER veto (P3-13 criterion):
                 (P, T0) within 1% / 3 h, clusters >20 stars;
                 tier-B members demoted, tier-A members flagged.
  DEMOTE-ALL   — union of DEMOTE-SYS + EPOCH-CLUSTER demotions.

Every candidate reports survivor reduction (counts + % by tier)
AND per-class losses (known planets, gauntlet EBs, gauntlet
refuted-other) — never reduction alone.

P3-15: the adopted gates (TWO-COMBINED, EPOCH-CLUSTER) are
implemented HERE and called by the screen (bulk_screen.py) —
the screen does not re-implement them. The gate functions take
their criterion as optional parameters defaulting to the
frozen values below, so the screen can pass its
profile-derived values while the replay (which always uses
the defaults) reproduces the recorded P3-11 numbers exactly.
"""

import json
import math
from collections import defaultdict

# --- frozen bulk_v3 constants, reused (calibration/bulk_v3.yaml) ---
SURVIVOR_SDE = 7.0        # adopted bulk bar; unchanged in Phase 3
TIER_A_MES = 9.0          # reused as the combined-significance bar
STRONG_EVENT_SNR = 3.0    # what counts as a "strong" single event
ODD_EVEN_MIN_RATIO = 0.5  # bulk_screen.py ODD_EVEN_EB veto threshold

# --- SECTOR_EPOCH_CLUSTER criterion (P3-13) ---
CLUSTER_TOL_P = 0.01      # periods within 1%
CLUSTER_TOL_T0_D = 0.125  # T0 within 3 h
CLUSTER_MIN_SIZE = 21     # clusters of >20 stars

# --- T0-cluster veto criterion (F-1, bulk_v6 / PIPE50-1) ---
# Mirrors the P3-13 criterion's T0 half: T0-only union-find
# linkage within 3 h, clusters of >20 stars, few-event rows
# only (n_events <= 2, the tier-B population). The profile
# must declare these exact values — bulk_screen._apply_profile
# fails loud on a mismatch (the P3-15 pattern). The criterion
# mirrors P3-13 and must NOT be tuned on S98 or on the BP-1
# numbers (see calibration/bulk_v6.yaml).
T0_CLUSTER_TOL_T0_D = 0.125  # T0 within 3 h
T0_CLUSTER_MIN_SIZE = 21     # clusters of >20 stars
T0_CLUSTER_MAX_EVENTS = 2    # few-event rows only

# --- pre-registered adoption rule (rule doc §2) ---
MAX_CAMPAIGN_LOSS = 0.05       # point-estimate loss bar, 1-2-event regime
MAX_CAMPAIGN_LOSS_UPPER = 0.10  # 95% Wilson upper-bound bar
MIN_CAMPAIGN_N = 200           # minimum 1-2-event injections

# Known planets (11). TOI-700 c (150428135) is not a survivor in
# the S96 single-sector rescore, so a replay against that file
# measures losses on the 10 present; see the rule doc §1.
KNOWN_PLANET_TICS = frozenset({
    "382602147", "229111835", "389753172", "27966179",
    "349410350", "300604770", "209310912", "399571743",
    "12999193",   # the 9 recovered TOIs
    "183537452",  # WASP-29b
    "150428135",  # TOI-700 c
})

# Per-class loss labels. Rows with no label are "unlabelled"
# (the gauntlet vetted only the 256 NEW tier-A leads).
CLASS_PLANET = "planet"
CLASS_EB = "eb"
CLASS_REFUTED_OTHER = "refuted_other"

CANDIDATES = (
    "SDE-8.0", "SDE-9.0", "SDE-10.0",
    "TWO-STRONG", "TWO-COMBINED", "PHASE-DEPTH",
    "DEMOTE-SYS", "EPOCH-CLUSTER", "DEMOTE-ALL",
)

# Candidates that can never be adopted in Phase 3 (SDE bars are
# fixed by the 3/3 vote; the replay values are evidence for 3.1).
EVIDENCE_ONLY = frozenset({"SDE-8.0", "SDE-9.0", "SDE-10.0"})


# --- per-row gates: True = kept, False = removed/demoted ---------

def sde_bar(row, bar):
    """Keep rows with SDE >= bar (replay candidate only)."""
    return row["sde"] >= bar


def two_event_strong(row):
    """2-event rows need both events individually strong.

    Rows with n_events != 2 are unaffected: 1-event rows are
    P3-14's singles (untestable here), >=3-event rows already
    meet tier A's >=2-strong requirement.
    """
    if row["n_events"] != 2:
        return True
    return row["n_strong_events"] >= 2


def two_event_combined(row, mes_bar=TIER_A_MES):
    """2-event rows need both events strong AND mes_pink >= 9.0.

    mes_pink is the combined (pink-noise) significance across
    events; 9.0 reuses the frozen tier_a_mes bar. `mes_bar` is
    a parameter (default the frozen bar) so the screen can pass
    its profile-derived tier_a_mes — the replay always uses the
    default, so the recorded P3-11 numbers are unchanged.
    """
    if row["n_events"] != 2:
        return True
    return row["n_strong_events"] >= 2 and row["mes_pink"] >= mes_bar


def phase_depth_consistent(row):
    """Depth consistency between alternating events.

    odd_even_ratio is min/max of the odd- and even-event fold
    depths (1.0 = identical); 0.5 is the pipeline's own
    ODD_EVEN_EB veto threshold. 1-event rows are untestable
    (no second event to compare) and pass through unchanged.
    The phase half (per-event phase residuals) needs per-event
    times, which rescore rows do not carry — see the rule doc.
    """
    if row["n_events"] < 2:
        return True
    return row["odd_even_ratio"] >= ODD_EVEN_MIN_RATIO


def demote_systematic(row):
    """near_systematic tier-B demotion (3B(3)).

    Tier-B rows inside a near_systematic window are demoted;
    tier-A rows are untouched by this gate.
    """
    if row["tier"] == "B" and row["near_systematic"]:
        return False
    return True


# --- epoch clustering (P3-13 criterion, whole survivor set) ------

def _union_find_clusters(n, adjacent):
    """Union-find (LINKAGE) over n items; adjacent(i, j) says
    whether items i and j link. Returns clusters (lists of
    indices), size > 1 only, largest first. The pairwise loop
    order is fixed (i < j), so the grouping is deterministic.
    Shared by epoch_clusters (P, T0) and t0_clusters (T0 only)
    — the F-1 veto reuses the P3-13 union-find with a T0-only
    distance (BULKV6_DESIGN §2), not a second copy of it.
    """
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for i in range(n):
        for j in range(i + 1, n):
            if adjacent(i, j):
                union(i, j)
    groups = defaultdict(list)
    for i in range(n):
        groups[find(i)].append(i)
    return sorted((g for g in groups.values() if len(g) > 1),
                  key=len, reverse=True)


def epoch_clusters(rows, tol_p=CLUSTER_TOL_P,
                   tol_t0_d=CLUSTER_TOL_T0_D):
    """Union-find clusters of rows sharing (P, T0) within 1% / 3 h.

    Returns a list of clusters (each a list of row indices),
    size > 1 only, largest first. The period test is the
    symmetric form of P3-13's |pi-pj|/pi <= 1%: |pi-pj| <= 1%
    of the larger period (P3-13's form is order-dependent at
    the boundary; the symmetric form differs only there).
    The tolerances are parameters (defaults the P3-13
    criterion) so the screen can pass its profile values —
    the replay always uses the defaults, so the recorded
    P3-11 numbers are unchanged.
    """
    periods = [r["period_days"] for r in rows]
    t0s = [r["t0_btjd"] for r in rows]

    def adjacent(i, j):
        return (abs(periods[i] - periods[j])
                <= tol_p * max(periods[i], periods[j])
                and abs(t0s[i] - t0s[j]) <= tol_t0_d)

    return _union_find_clusters(len(rows), adjacent)


def sector_epoch_cluster_tics(rows, tol_p=CLUSTER_TOL_P,
                              tol_t0_d=CLUSTER_TOL_T0_D,
                              min_size=CLUSTER_MIN_SIZE):
    """TICs in SECTOR_EPOCH_CLUSTERs: clusters of >20 stars.

    Returns (clustered_tics, clusters): the set of TICs in
    >20-star clusters and the list of those clusters (each a
    list of TICs, largest first). Parameters default to the
    P3-13 criterion (see epoch_clusters).
    """
    big = [c for c in epoch_clusters(rows, tol_p=tol_p,
                                    tol_t0_d=tol_t0_d)
           if len(c) >= min_size]
    clusters = [[rows[i]["tic"] for i in c] for c in big]
    clustered = {t for c in clusters for t in c}
    return clustered, clusters


# --- T0 clustering (F-1 criterion, bulk_v6 / PIPE50-1) -----------

def t0_clusters(rows, tol_t0_d=T0_CLUSTER_TOL_T0_D):
    """Union-find clusters of rows sharing T0 within 3 h (F-1).

    Period-agnostic: the (P, T0) veto cannot catch few-event
    rows because their periods are meaningless (one dip), so
    the event time is the discriminator (NULL_DIAGNOSIS_BP1
    §7 — max (P, T0) cluster 16 vs max T0-only cluster 30 in
    the same data). LINKAGE (transitive chaining, not fixed
    bins): a chain of rows each within 3 h of the next is one
    cluster however far it spans (A1). Returns a list of
    clusters (each a list of row indices), size > 1 only,
    largest first. Same union-find as epoch_clusters.
    """
    t0s = [r["t0_btjd"] for r in rows]

    def adjacent(i, j):
        return abs(t0s[i] - t0s[j]) <= tol_t0_d

    return _union_find_clusters(len(rows), adjacent)


def t0_cluster_rows(rows, tol_t0_d=T0_CLUSTER_TOL_T0_D,
                    min_size=T0_CLUSTER_MIN_SIZE, count_rows=None):
    """Qualifying T0 clusters as row-index lists (F-1).

    A cluster qualifies when its counted size reaches
    min_size. `count_rows` is an optional predicate: when
    given, only rows satisfying it count toward the bar, but
    ALL members of a qualifying cluster are returned
    (D-F1K3: the bar counts pass-1 rows only — `k3_pass is
    None` — while K=3 rows inside a qualifying cluster are
    demoted too). Without a predicate every member counts
    (the sector_epoch_cluster_tics form). The veto demotes
    by ROW (cluster membership), not by TIC: a star's
    pass-1 row can sit in a cluster while its K=3 row does
    not, and the non-clustered row must survive.
    """
    big = []
    for c in t0_clusters(rows, tol_t0_d=tol_t0_d):
        n_counted = (sum(1 for i in c if count_rows(rows[i]))
                     if count_rows is not None else len(c))
        if n_counted >= min_size:
            big.append(c)
    return big


def t0_cluster_tics(rows, tol_t0_d=T0_CLUSTER_TOL_T0_D,
                    min_size=T0_CLUSTER_MIN_SIZE, count_rows=None):
    """TICs in T0-CLUSTERs: clusters of >20 stars (F-1).

    Returns (clustered_tics, clusters): the set of TICs in
    >20-star clusters and the list of those clusters (each a
    list of TICs, largest first). Same return shape as
    sector_epoch_cluster_tics. `count_rows` is the D-F1K3
    counting predicate (see t0_cluster_rows).
    """
    big = t0_cluster_rows(rows, tol_t0_d=tol_t0_d,
                          min_size=min_size, count_rows=count_rows)
    clusters = [[rows[i]["tic"] for i in c] for c in big]
    clustered = {t for c in clusters for t in c}
    return clustered, clusters


# --- matrix driver (pure: rows in, counts out) --------------------

def _class_counts(rows, labels, removed):
    """Per-class losses among `removed` (a set of TICs)."""
    losses = {CLASS_PLANET: 0, CLASS_EB: 0, CLASS_REFUTED_OTHER: 0}
    lost_tics = {CLASS_PLANET: [], CLASS_EB: [],
                 CLASS_REFUTED_OTHER: []}
    for row in rows:
        tic = row["tic"]
        if tic in removed:
            cls = labels.get(tic)
            if cls in losses:
                losses[cls] += 1
                lost_tics[cls].append(tic)
    return losses, lost_tics


def _result(name, rows, labels, removed, flagged=()):
    """One candidate's result: reduction + per-class losses."""
    n_total = len(rows)
    n_a = sum(1 for r in rows if r["tier"] == "A")
    n_b = n_total - n_a
    rem_a = sum(1 for r in rows
                if r["tic"] in removed and r["tier"] == "A")
    rem_b = sum(1 for r in rows
                if r["tic"] in removed and r["tier"] == "B")
    losses, lost_tics = _class_counts(rows, labels, removed)
    return {
        "candidate": name,
        "n_in": n_total,
        "n_in_tier_a": n_a,
        "n_in_tier_b": n_b,
        "removed": len(removed),
        "removed_pct": 100.0 * len(removed) / n_total if n_total else 0.0,
        "removed_tier_a": rem_a,
        "removed_tier_a_pct": 100.0 * rem_a / n_a if n_a else 0.0,
        "removed_tier_b": rem_b,
        "removed_tier_b_pct": 100.0 * rem_b / n_b if n_b else 0.0,
        "flagged_tier_a": len(flagged),
        "losses": losses,
        "lost_tics": lost_tics,
    }


def run_matrix(rows, labels):
    """Replay every candidate gate over `rows`.

    `rows`: survivor-record dicts (never mutated). `labels`:
    tic -> class ("planet" / "eb" / "refuted_other"); rows
    without a label are unlabelled. Returns {candidate: result}.
    """
    clustered, clusters = sector_epoch_cluster_tics(rows)
    results = {}

    def _removed(pred):
        return {r["tic"] for r in rows if not pred(r)}

    for bar, name in ((8.0, "SDE-8.0"), (9.0, "SDE-9.0"),
                      (10.0, "SDE-10.0")):
        results[name] = _result(
            name, rows, labels,
            _removed(lambda r, b=bar: sde_bar(r, b)))
    results["TWO-STRONG"] = _result(
        "TWO-STRONG", rows, labels, _removed(two_event_strong))
    results["TWO-COMBINED"] = _result(
        "TWO-COMBINED", rows, labels, _removed(two_event_combined))
    results["PHASE-DEPTH"] = _result(
        "PHASE-DEPTH", rows, labels, _removed(phase_depth_consistent))
    results["DEMOTE-SYS"] = _result(
        "DEMOTE-SYS", rows, labels, _removed(demote_systematic))

    # EPOCH-CLUSTER: tier-B members demoted, tier-A flagged.
    demoted = {r["tic"] for r in rows
               if r["tic"] in clustered and r["tier"] == "B"}
    flagged = {r["tic"] for r in rows
               if r["tic"] in clustered and r["tier"] == "A"}
    results["EPOCH-CLUSTER"] = _result(
        "EPOCH-CLUSTER", rows, labels, demoted, flagged=flagged)

    # DEMOTE-ALL: union of the two demotions (tier-B only);
    # tier-A flagged members are the epoch-cluster ones.
    demoted_all = {r["tic"] for r in rows
                   if (r["tic"] in clustered and r["tier"] == "B")
                   or (r["tier"] == "B" and r["near_systematic"])}
    results["DEMOTE-ALL"] = _result(
        "DEMOTE-ALL", rows, labels, demoted_all, flagged=flagged)

    results["_epoch_clusters"] = {
        "n_clusters_gt20": len(clusters),
        "sizes": sorted((len(c) for c in clusters), reverse=True),
        "n_clustered": len(clustered),
    }
    return results


# --- adoption-rule checker (rule doc §4) --------------------------

def wilson_upper(k, n, z=1.96):
    """95% Wilson score upper bound on a proportion k/n."""
    if n <= 0:
        return 1.0
    p = k / n
    denom = 1.0 + z * z / n
    centre = (p + z * z / (2.0 * n)) / denom
    half = z * math.sqrt(p * (1.0 - p) / n
                         + z * z / (4.0 * n * n)) / denom
    return min(1.0, centre + half)


def check_adoption(result, campaign=None):
    """Judge one candidate result against the pre-registered rule.

    `result`: a run_matrix entry. `campaign`: None (campaign not
    run yet) or {"n_1_2_event": n, "losses_1_2_event": k} from
    the P3-10 campaign. Returns (verdict, reason) with verdict
    in RULE-REJECTED / EVIDENCE-ONLY / UNDECIDED / ADOPTABLE /
    REJECTED. No threshold is chosen by this function — it
    applies the rule; ADOPTABLE is a property of the evidence,
    and adoption itself is a P3-15 / parent decision.
    """
    name = result["candidate"]
    if result["losses"][CLASS_PLANET] > 0:
        return ("RULE-REJECTED",
                "drops %d known planet(s): %s"
                % (result["losses"][CLASS_PLANET],
                   ", ".join(result["lost_tics"][CLASS_PLANET])))
    if name in EVIDENCE_ONLY:
        return ("EVIDENCE-ONLY",
                "SDE bars are fixed in Phase 3 (3/3 vote); the "
                "replay value is evidence for the 3.1 decision")
    if campaign is None:
        return ("UNDECIDED",
                "P3-10 campaign loss measurement does not exist yet")
    n = campaign["n_1_2_event"]
    k = campaign["losses_1_2_event"]
    if n < MIN_CAMPAIGN_N:
        return ("UNDECIDED",
                "campaign n=%d below the %d minimum — inconclusive"
                % (n, MIN_CAMPAIGN_N))
    point = k / n
    upper = wilson_upper(k, n)
    if upper > MAX_CAMPAIGN_LOSS_UPPER:
        return ("UNDECIDED",
                "95%% upper bound %.1f%% exceeds the %.0f%% bar — "
                "inconclusive" % (100 * upper,
                                  100 * MAX_CAMPAIGN_LOSS_UPPER))
    if point > MAX_CAMPAIGN_LOSS:
        return ("REJECTED",
                "campaign loss %.1f%% exceeds the %.0f%% bar"
                % (100 * point, 100 * MAX_CAMPAIGN_LOSS))
    return ("ADOPTABLE",
            "zero known-planet losses; campaign loss %.1f%% "
            "(95%% upper %.1f%%) within the bar"
            % (100 * point, 100 * upper))


# --- replay driver (the only I/O in this module) ------------------

def load_rescore(path):
    """Read a rescore JSONL file; returns the survivor rows."""
    with open(path) as fh:
        return [json.loads(line) for line in fh if line.strip()]


def load_labels(path):
    """Read a labels JSON file: {tic: class}."""
    with open(path) as fh:
        return json.load(fh)


def counts_only(results):
    """Strip per-TIC detail from matrix results (for the repo
    summary: counts only, no per-star data)."""
    out = {}
    for name, res in results.items():
        if name.startswith("_"):
            out[name] = res
            continue
        out[name] = {k: v for k, v in res.items()
                     if k not in ("lost_tics",)}
    return out


def main(argv=None):
    """Replay driver: rescore JSONL + labels JSON -> summary JSON.

    Usage: python -m bulk.replay_matrix --rescore <path>
               --labels <path> --out <path>
    The labels JSON maps TIC -> class and is derived from the
    gauntlet ledger (see the P3-11 replay results record for
    the exact derivation command).
    """
    import argparse
    ap = argparse.ArgumentParser(
        description="Replay the P3-11 candidate gates over a "
                    "rescore file (read-only input).")
    ap.add_argument("--rescore", required=True)
    ap.add_argument("--labels", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    rows = load_rescore(args.rescore)
    labels = load_labels(args.labels)
    results = run_matrix(rows, labels)
    verdicts = {name: check_adoption(res)
                for name, res in results.items()
                if not name.startswith("_")}
    summary = counts_only(results)
    summary["_verdicts"] = {name: {"verdict": v, "reason": r}
                            for name, (v, r) in verdicts.items()}
    summary["_inputs"] = {
        "rescore": args.rescore,
        "n_rows": len(rows),
        "n_labelled": len(labels),
    }
    with open(args.out, "w") as fh:
        json.dump(summary, fh, indent=2, sort_keys=True)
        fh.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
