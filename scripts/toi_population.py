"""Labelled-population TOI run (Phase 1.2 follow-up F-8).

Runs a labelled population of real TOIs (confirmed planets +
dispositioned false positives) through the gauntlet runner and
emits per-stage confusion counts — the artifact Phase 2A will
consume as its acceptance test. The offline population is the
three golden fixtures (TOI-700 c + WASP-126 b, planets; TIC
308851365, a VSX eclipsing binary). The live extension (more
TOIs, fetched from MAST) is documented in
docs/toi-population-live.md; run this script with --live.

Per star, the harness runs hunter._run_pipeline (via the
EXHUNT_FIXTURE_DIR seam offline, live downloads with --live)
for the ephemeris, then builds runner natives from the
pipeline's own raw arrays:

  * refine: the pipeline's BLS-refined ephemeris (converged;
    n_eras is the number of observed transits).
  * raw_flux: fold_depth on the raw flux (+ n_events).
  * shape: trapezoid_shape_gate (rho_star from the population
    entry when known, else None — no density flag without a
    density).
  * odd_even: event_parity_depths on the raw flux.
  * blend: a DIP-FREE neighbour (the target flux with
    in-transit points replaced by the out-of-transit median)
    — the F-1 no-false-kill control: the blend check must not
    kill a planet when no neighbour shows the dip.
  * catalogue: {"known": False} for planets (the check is for
    known variables/EBs, and a known planet is not one);
    {"known": True, "source": "VSX", "period_match": True}
    for the EB.
  * clean_refold: NOT_APPLICABLE + waived (not_bulk_survivor
    — these are deep-pipeline targets, not bulk survivors).
    Waivers are decided from a PROBE run (no waivers): the
    waived stages are exactly those that came back
    NOT_APPLICABLE with a code — an expensive stage
    short-circuited after an earlier FAIL is unmeasured and
    can never be waived, so waivers cannot be predicted
    upfront.
  * persistence: fold_depth per time-gap segment (segments
    split at >1 d gaps, approximating sectors); CONSISTENT
    when every usable segment shows the dip at >=1.5 sigma
    (the sector stamp's own bar).
  * holdout: HOLDOUT-NOT-APPLICABLE + waived (single_sector)
    when the target has 1 sector; HOLDOUT-INSUFFICIENT-DATA
    (UNMEASURED, never waivable) when it has 2 — a held-out
    sector exists then, but the holdout test needs 3 folds.
  * diffimg / transit_fit: NO native offline (no TESSCut/TPF/
    per-sector npz) — UNMEASURED, recorded as known gaps, NOT
    fabricated. pixel_check is NOT_APPLICABLE + waived
    (period_lt_8d) below 8 d, UNMEASURED above (no TPF).

No star can reach CANDIDATE offline (diffimg/transit_fit are
unmeasured), so the confusion is at STAGE level: planets must
pass every measured stage, FPs must be killed by at least one
discriminating stage. The test (tests/test_toi_population.py)
diffs the counts + per-star stage statuses against
tests/fixtures/toi_population/baseline.json — a change fails
the test and forces a deliberate baseline update.
"""
import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import hunter  # noqa: E402
from gauntlet.common import (  # noqa: E402
    event_parity_depths, fold_depth)
from gauntlet.rawflux_check import trapezoid_shape_gate  # noqa: E402
from gauntlet.runner import (  # noqa: E402
    Ephemeris, TargetContext, run_gauntlet)

ROOT = Path(__file__).resolve().parent.parent
FIXTURE_DIR = ROOT / "tests" / "fixtures" / "golden"

# The offline labelled population: the golden fixtures. Labels
# are dispositions, not pipeline verdicts — TOI-700 c and
# WASP-126 b are confirmed planets, TIC 308851365 is a VSX
# eclipsing binary (resolved 2026-11-03). star_radius /
# max_sectors mirror tests/test_golden_fixtures.py exactly.
# rho_star_solar is the TIC stellar density where the fixture
# meta carries it (the EB only); None means the shape gate runs
# without a density flag.
POPULATION = [
    {"tic": "150428135", "label": "planet", "name": "TOI-700 c",
     "star_radius": 0.42, "max_sectors": 2,
     "rho_star_solar": None},
    {"tic": "25155310", "label": "planet", "name": "WASP-126 b",
     "star_radius": 1.30, "max_sectors": 1,
     "rho_star_solar": None},
    {"tic": "308851365", "label": "fp_eb", "name": "TIC 308851365 EB",
     "star_radius": 1.0, "max_sectors": 1,
     "rho_star_solar": 0.767541551868733},
]

PROV = {"calibration_version": "gauntlet_v2",
        "pipeline_git_sha": "toi-population",
        "run_id": "toi-population",
        "timestamp_utc": "2026-11-14T00:00:00+00:00"}

# Persistence bar: a segment counts as showing the dip at the
# sector stamp's own 1.5-sigma bar (persistence.py).
SEGMENT_MIN_SIGNIF = 1.5
# Time-gap split for persistence segments (days): TESS sector
# gaps are days; within-sector cadence is 2 minutes.
SEGMENT_GAP_D = 1.0


def _n_events(t, period, t0, duration_d):
    """Distinct transit events with in-transit points."""
    n_ev = np.round((np.asarray(t, dtype=float) - t0) / period)
    dt = np.asarray(t, dtype=float) - (t0 + n_ev * period)
    in_tr = np.abs(dt) < duration_d / 2.0
    return len(np.unique(n_ev[in_tr])) if in_tr.any() else 0


def _persistence_native(t, f, period, t0, duration_d):
    """Fold the dip per time-gap segment (sector approximation).
    CONSISTENT when every usable segment shows the dip at
    >=1.5 sigma; MIXED otherwise; no verdict when no segment
    is usable (UNMEASURED)."""
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


def _dip_free_neighbour(t, f, period, t0, duration_d):
    """The target flux with in-transit points replaced by the
    out-of-transit median: a neighbour that provably does not
    show the dip (the F-1 no-false-kill control)."""
    t = np.asarray(t, dtype=float)
    f = np.asarray(f, dtype=float)
    n_ev = np.round((t - t0) / period)
    dt = t - (t0 + n_ev * period)
    in_tr = np.abs(dt) < duration_d / 2.0
    out = f.copy()
    out[in_tr] = np.median(f[~in_tr])
    return out


def run_star(entry, live=False):
    """One labelled star through the pipeline + runner. Returns
    the per-star artifact dict."""
    tic = entry["tic"]
    full = hunter._run_pipeline(
        tic, star_radius=entry["star_radius"],
        max_sectors=entry["max_sectors"])
    period = float(full["Period"])
    t0 = float(full["T0"])
    duration = float(full["Duration_Days"])
    t = np.asarray(full["raw_time"], dtype=float)
    f = np.asarray(full["raw_flux"], dtype=float)
    f = f / np.median(f)  # fold_depth assumes ~unity flux
    n_sectors = int(full["Sectors_Analyzed"])
    n_events = _n_events(t, period, t0, duration)

    natives = {}
    natives["catalogue.native"] = (
        {"known": True, "source": "VSX",
         "var_type": "ECLIPSING BINARY", "period_match": True}
        if entry["label"] == "fp_eb" else {"known": False})
    natives["refine.native"] = {
        "period_d": period, "t0": t0, "duration_d": duration,
        "converged": True, "rms_resid_d": None,
        "n_eras": n_events}
    fold = fold_depth(t, f, period, t0, duration)
    if fold is not None:
        natives["raw_flux.native"] = dict(fold)
        natives["raw_flux.native"]["n_events"] = n_events
    natives["shape.native"] = trapezoid_shape_gate(
        t, f, period, t0, duration, entry["rho_star_solar"])
    natives["odd_even.native"] = event_parity_depths(
        t, f, period, t0, duration)
    natives["persistence.native"] = _persistence_native(
        t, f, period, t0, duration)
    natives["blend.native"] = {
        "target_t": t, "target_f": f,
        "neighbour_t": t,
        "neighbour_f": _dip_free_neighbour(
            t, f, period, t0, duration),
        "period_d": period, "t0": t0, "duration_d": duration,
        "neighbour_tic": None, "separation_arcsec": None}
    natives["holdout.native"] = (
        "HOLDOUT-NOT-APPLICABLE" if n_sectors == 1
        else "HOLDOUT-INSUFFICIENT-DATA")
    # diffimg / transit_fit: no native offline (known gaps —
    # the runner skips them as unmeasured). pixel_check: the
    # runner assigns NOT_APPLICABLE below 8 d itself; above 8 d
    # there is no TPF offline, so it is unmeasured.

    # Waivers are decided from a PROBE run, not predicted
    # upfront: an expensive stage (holdout) that is
    # short-circuited after an earlier FAIL is unmeasured, and
    # an unmeasured stage can never be waived — so the waivers
    # are exactly the stages that came back NOT_APPLICABLE with
    # a code in the probe run. (The runner is fast; the
    # pipeline run above is the slow part.)
    waivers = {
        "clean_refold": "deep-pipeline target, no bulk gate",
        "holdout": "single-sector target: no held-out sector "
                   "exists",
        "pixel_check": (f"period {period:.2f} d < 8 d: the TPF "
                        f"pixel check does not apply"),
    }

    ctx = TargetContext(
        tic=tic,
        ephemeris=Ephemeris("bulk", period, t0, duration,
                            source="filed"),
        artifacts=natives, provenance=dict(PROV), imaging=None,
        bulk_survivor=False)
    probe = run_gauntlet(ctx)
    applied = {r.stage: waivers[r.stage]
               for r in probe.results
               if r.status == "not_applicable"
               and r.waiver_code is not None
               and r.stage in waivers}
    run = run_gauntlet(ctx, waivers=applied)

    stages = {r.stage: r.status for r in run.results}
    gaps = ["diffimg (no TESSCut offline)",
            "transit_fit (no per-sector npz offline)"]
    if period >= 8.0:
        gaps.append("pixel_check (no TPF offline)")
    return {
        "tic": tic, "label": entry["label"],
        "name": entry["name"],
        "ephemeris": {"period_d": period, "t0": t0,
                      "duration_d": duration,
                      "sde": float(full["SDE"]),
                      "n_sectors": n_sectors,
                      "n_events": n_events},
        "stages": stages,
        "final_verdict": run.final_verdict,
        "waivers": sorted(applied),
        "kill_stages": sorted(s for s, st in stages.items()
                              if st == "fail"),
        "gaps": gaps,
    }


def confusion_counts(stars):
    """Per-stage confusion counts — the artifact 2A consumes.
    `all_measured_pass`: every measured stage (pass/fail/
    inconclusive — unmeasured and waived not_applicable do not
    count) passes. `killed`: at least one FAIL."""
    counts = {"planets": {"n": 0, "all_measured_pass": 0,
                          "any_fail": 0},
              "fps": {"n": 0, "killed": 0, "kill_stages": {}},
              "stages": {}}
    for star in stars:
        group = ("planets" if star["label"] == "planet"
                 else "fps")
        counts[group]["n"] += 1
        measured = {s: st for s, st in star["stages"].items()
                    if st not in ("unmeasured", "not_applicable")}
        if group == "planets":
            if all(st == "pass" for st in measured.values()):
                counts["planets"]["all_measured_pass"] += 1
            if any(st == "fail" for st in measured.values()):
                counts["planets"]["any_fail"] += 1
        else:
            if star["kill_stages"]:
                counts["fps"]["killed"] += 1
            for stage in star["kill_stages"]:
                ks = counts["fps"]["kill_stages"]
                ks[stage] = ks.get(stage, 0) + 1
        for stage, status in sorted(star["stages"].items()):
            by_label = counts["stages"].setdefault(stage, {})
            by_status = by_label.setdefault(group, {})
            by_status[status] = by_status.get(status, 0) + 1
    return counts


def run_population(live=False, population=None):
    """Run the whole population; return the artifact dict."""
    if not live:
        os.environ["EXHUNT_FIXTURE_DIR"] = str(FIXTURE_DIR)
    stars = [run_star(entry, live=live)
             for entry in (population or POPULATION)]
    return {"population": "golden-fixtures" if not live else "live",
            "n_stars": len(stars),
            "stars": stars,
            "counts": confusion_counts(stars)}


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Labelled-population TOI run (F-8): run the "
                    "golden fixtures (or --live TOIs) through the "
                    "gauntlet and emit per-stage confusion counts.")
    ap.add_argument("--live", action="store_true",
                    help="fetch from MAST instead of the golden "
                         "fixtures (see docs/toi-population-live.md)")
    ap.add_argument("--out", default=None,
                    help="write the JSON artifact to this path "
                         "(default: print to stdout)")
    args = ap.parse_args(argv)
    artifact = run_population(live=args.live)
    text = json.dumps(artifact, indent=2, sort_keys=True)
    if args.out:
        Path(args.out).write_text(text + "\n")
    else:
        print(text)
    counts = artifact["counts"]
    print(f"planets: {counts['planets']['all_measured_pass']}/"
          f"{counts['planets']['n']} all-measured-pass; "
          f"FPs killed: {counts['fps']['killed']}/"
          f"{counts['fps']['n']}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
