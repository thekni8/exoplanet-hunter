#!/usr/bin/env python
"""Twin-pair joint analysis for TIC 404931136 / TIC 404924199.

Shared-source test: if both apertures are lit by ONE eclipsing binary,
their BLS ephemerides must describe the SAME eclipse train — the phase
offset between the two (t0, P) solutions, propagated to a common epoch,
must be ~0 (mod 1), and the refined double-period solutions must agree.
Depth ratio vs angular separation tests the dilution geometry.
Reads the two gauntlet JSONs + sweep4_logs/catalog_rows.json, writes
sweep4_logs/pair_analysis.json and patches a "pair_analysis" block
into both star JSONs.
"""
import json
import math
from pathlib import Path

BASE = Path(__file__).resolve().parent
A, B = "404931136", "404924199"


def phase_offset(t0a, pa, t0b, pb, tref):
    """Phase of B's eclipse train relative to A's, evaluated at tref
    (cycles of A's period). Returns value in [-0.5, 0.5)."""
    # eclipse times near tref for each train
    ka = round((tref - t0a) / pa)
    kb = round((tref - t0b) / pb)
    ta = t0a + ka * pa
    tb = t0b + kb * pb
    dphi = (tb - ta) / pa
    return dphi - math.floor(dphi + 0.5), ta, tb


def main():
    da = json.loads((BASE / "vetting_results" / f"{A}.json").read_text())
    db = json.loads((BASE / "vetting_results" / f"{B}.json").read_text())
    cat = json.loads((BASE / "sweep4_logs" / "catalog_rows.json").read_text())
    rows, pair = cat["rows"], cat.get("pair", {})

    aa, ab = da["analyze"], db["analyze"]
    tref = 2459000.0 - 2457000.0  # BTJD ~ mid-baseline (TESS cycle 3)
    dphi, ta, tb = phase_offset(aa["t0_days"], aa["period_days"],
                                ab["t0_days"], ab["period_days"], tref)
    # also at each star's own t0 (no propagation)
    dphi0 = ((ab["t0_days"] - aa["t0_days"]) / aa["period_days"])
    dphi0 = dphi0 - math.floor(dphi0 + 0.5)

    out = {
        "pair": [A, B],
        "separation_deg": pair.get("pair_separation_deg"),
        "separation_arcmin": pair.get("pair_separation_arcmin"),
        "periods_days": {A: aa["period_days"], B: ab["period_days"]},
        "period_diff_days": abs(aa["period_days"] - ab["period_days"]),
        "phase_offset_at_common_epoch": {
            "tref_btjd": tref, "dphi_cycles": dphi,
            "eclipse_time_A_btjd": ta, "eclipse_time_B_btjd": tb,
            "offset_hours": abs(dphi) * aa["period_days"] * 24.0},
        "phase_offset_at_t0": {"dphi_cycles": dphi0},
        "bls_depth_ratio_A_over_B": (aa["depth_percent"] / ab["depth_percent"]
                                     if ab["depth_percent"] else None),
        "positions": {A: {"ra": rows[A].get("ra_deg"), "dec": rows[A].get("dec_deg")},
                      B: {"ra": rows[B].get("ra_deg"), "dec": rows[B].get("dec_deg")}},
        "contratio": {A: rows[A].get("contratio"), B: rows[B].get("contratio")},
        "note": ("Shared source supported if |dphi| is small (<~0.1 cycles) "
                 "at the common epoch: both apertures then time the same "
                 "eclipse train."),
    }
    for d, other in ((da, B), (db, A)):
        if "double_period" in d:
            out.setdefault("double_period_refined", {})[d["tic"]] = \
                d["double_period"].get("period_2p_refined_days")
    (BASE / "sweep4_logs" / "pair_analysis.json").write_text(
        json.dumps(out, indent=2, default=str))
    for d in (da, db):
        d["pair_analysis"] = out
        (BASE / "vetting_results" / f"{d['tic']}.json").write_text(
            json.dumps(d, indent=2, default=str))
    print(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    main()
