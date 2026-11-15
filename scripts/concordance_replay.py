#!/usr/bin/env python
"""Real-data concordance replay (Phase 2 vote follow-up P-12).

Replays the 25 hand-vetted rescore-v2 S96 leads through the
automated desk driver and compares each automated outcome to
the manual verdict recorded in
tests/fixtures/concordance/manual_verdicts.json (transcribed
from the 2026-11-14 rescore gauntlet LEDGER, 0 survivors).

Concordance rule, per lead:
  * "agree" leads: concordant when the driver KILLS the lead
    (final verdict anything but CANDIDATE) at one of the
    expected stages. The expected set is the manual kill
    ground expressed as driver stages — e.g. the 18
    flagged-cadence artifacts must die at clean_refold, the
    catalogued planet at catalogue.
  * "mismatch" leads (one: TIC 307433122, harmonic alias):
    the automated outcome is RECORDED, not asserted — no
    stage covers harmonic-alias grounds, so agreement is not
    expected and its outcome never fails the replay.

Usage:
  concordance_replay.py [--only TIC[,TIC...]] [--out PATH]
      [--workdir DIR] [--no-expensive]

The full 25-lead replay downloads real light curves from MAST
and takes ~1-2 h — it is a Mac/live-CI job (the live test in
tests/test_concordance_live.py runs it in live.yml, weekly +
on merge). Use --only for a subset: one lead per class is the
in-session proof. Workdirs land under vetting_results/
(run data, gitignored) unless --workdir is given.
"""
import argparse
import json
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

from gauntlet.desk import (LiveDataSource, Survivor,  # noqa: E402
                           run_desk_gauntlet)

FIXTURE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "tests", "fixtures", "concordance", "manual_verdicts.json")


def load_fixture(path=FIXTURE):
    """The manual-verdict fixture (list of lead dicts)."""
    with open(path) as fh:
        return json.load(fh)["leads"]


def compare_lead(lead, verdict, kill_stages):
    """Concordance for one replayed lead.

    verdict: the driver's final verdict (or None on a run
    error). kill_stages: the driver's FAIL stages. Returns
    (concordant, note): concordant is True/False for "agree"
    leads, None for "mismatch" leads (recorded, not
    asserted).
    """
    if lead["expected"] == "mismatch":
        return None, ("expected mismatch — no stage covers "
                      "harmonic-alias grounds; outcome recorded, "
                      "not asserted")
    expected = set(lead["expected_kill_stages"])
    if verdict is None:
        return False, "driver run failed (see error)"
    if verdict == "CANDIDATE":
        return False, ("driver returned CANDIDATE; manual "
                       f"verdict is {lead['manual_verdict']}")
    hit = sorted(set(kill_stages) & expected)
    if hit:
        return True, f"killed at {', '.join(hit)}"
    return False, (f"killed at {', '.join(kill_stages) or 'none'}"
                   f"; expected one of {', '.join(sorted(expected))}")


def run_replay(leads, workdir, repo_root, run_expensive=True,
               log=print):
    """Run the driver on each lead; return the report dict."""
    source = LiveDataSource(repo_root=repo_root)
    results = []
    for lead in leads:
        tic = lead["tic"]
        log(f"TIC {tic} ({lead['manual_verdict']}) ...",
            flush=True)
        survivor = Survivor(
            tic=tic, period_d=lead["period_d"],
            t0_btjd=lead["t0_btjd"],
            duration_h=lead["duration_h"],
            depth_pct=lead["depth_pct"], sde=lead["sde"],
            sector=lead["sector"], bulk_survivor=True)
        entry = {"tic": tic,
                 "manual_verdict": lead["manual_verdict"],
                 "expected_kill_stages":
                     lead["expected_kill_stages"],
                 "expected": lead["expected"]}
        try:
            result = run_desk_gauntlet(
                survivor, os.path.join(workdir, tic),
                source=source, run_expensive=run_expensive,
                repo_root=repo_root)
            verdict = result.run.final_verdict
            kills = [r.stage for r in result.run.results
                     if r.status == "fail"]
            entry["automated_verdict"] = verdict
            entry["automated_kill_stages"] = kills
        except Exception as exc:  # noqa: BLE001 - recorded
            entry["automated_verdict"] = None
            entry["automated_kill_stages"] = []
            entry["error"] = (f"{type(exc).__name__}: {exc}\n"
                              + traceback.format_exc())
            verdict, kills = None, []
        concordant, note = compare_lead(lead, verdict, kills)
        entry["concordant"] = concordant
        entry["note"] = note
        tag = ("MISMATCH-RECORDED" if concordant is None else
               "AGREE" if concordant else "DISAGREE")
        log(f"  {tag}: {verdict} killed at "
            f"{', '.join(kills) or 'none'} — {note}", flush=True)
        results.append(entry)
    agree = [r for r in results if r["concordant"] is True]
    disagree = [r for r in results if r["concordant"] is False]
    recorded = [r for r in results if r["concordant"] is None]
    return {"n_leads": len(results),
            "n_agree": len(agree),
            "n_disagree": len(disagree),
            "n_mismatch_recorded": len(recorded),
            "disagree_tics": [r["tic"] for r in disagree],
            "results": results}


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Replay the 25 hand-vetted S96 leads "
                    "through the automated desk driver.")
    ap.add_argument("--only", default=None,
                    help="comma-separated TICs to run (default: "
                         "all 25)")
    ap.add_argument("--out", default=None,
                    help="write the JSON report here")
    ap.add_argument("--workdir", default=None,
                    help="workdir root (default: vetting_results/"
                         "concordance under the repo root)")
    ap.add_argument("--no-expensive", action="store_true",
                    help="cheap stages only")
    args = ap.parse_args(argv)
    repo_root = os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))
    leads = load_fixture()
    if args.only:
        wanted = {t.strip() for t in args.only.split(",")}
        leads = [l for l in leads if l["tic"] in wanted]
        missing = wanted - {l["tic"] for l in leads}
        if missing:
            ap.error(f"TIC(s) not in the fixture: "
                     f"{', '.join(sorted(missing))}")
    workdir = args.workdir or os.path.join(
        repo_root, "vetting_results", "concordance")
    report = run_replay(
        leads, workdir, repo_root,
        run_expensive=not args.no_expensive)
    print(f"concordance: {report['n_agree']}/{report['n_leads']} "
          f"agree, {report['n_disagree']} disagree, "
          f"{report['n_mismatch_recorded']} mismatch-recorded",
          flush=True)
    if report["disagree_tics"]:
        print("disagreeing TICs: "
              + ", ".join(report["disagree_tics"]), flush=True)
    if args.out:
        with open(args.out, "w") as fh:
            json.dump(report, fh, indent=2)
            fh.write("\n")
        print(f"report written to {args.out}", flush=True)
    return 1 if report["n_disagree"] else 0


if __name__ == "__main__":
    sys.exit(main())
