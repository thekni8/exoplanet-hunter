"""Vetting gauntlet — the desk-check tools that turn a sweep hit into a
candidate (or kill it).

A sweep hit (SDE >= 8.5) is a suspicion, not a candidate. The gauntlet
runs, in order:

    1. catalogue check  — VSX / TOI / Zooniverse (see gauntlet/README.md)
    2. raw-flux desk check + trapezoid shape gate  — rawflux_check.py
    3. refined-ephemeris verification folds        — desk_finish.py
    4. holdout prediction test                     — holdout_test.py (repo root),
                                                   holdout_supp.py, holdout_extended.py
    5. difference imaging / host localisation      — tesscut_fetch.py,
                                                   tesscut_extract.py, diffimg.py
    6. formal transit fit                          — transit_fit.py,
                                                   transit_fit_report.py

Every tool is a standalone CLI (argparse, --help). Shared helpers live in
common.py. Run from the repo root, e.g.:

    python gauntlet/rawflux_check.py TIC --result-json result.json --workdir work/TIC
"""
