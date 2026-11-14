#!/usr/bin/env python3
"""Generate the synthetic TIC 139526205 blend fixture.

The REAL case (S97, archive/bulk-screens/s0097/RECALIBRATION_S0097.md):
TIC 139526205 showed a 0.505% dip at P 2.9220404 d (filed 2.9223 d),
MES 32.1, 16 events, duration 3.17 h, Tmag 11.3, R 0.72 R_sun —
and it was a BLEND: the dip is a photocopy of a ~22% eclipsing
binary on the neighbour TIC 139524628, 66.5 arcsec away.

No real TIC 139526205 light curve is on disk (the S97 run data
lives on the Mac), so this fixture is SYNTHETIC: box transits at
the real ephemeris with the real depths (0.505% target, 22%
neighbour) and white noise scaled to give a target significance
in the same ballpark as the real MES 32. What the fixture
proves is the BLEND FUNCTION's verdict on a photocopy case —
not the real star's photometry.

Deterministic (seed 42). Regenerate with:
  python tests/fixtures/blend/make_fixture.py
"""
import json
import os

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))

# Real case facts (RECALIBRATION_S0097.md).
PERIOD_D = 2.9220404
FILED_PERIOD_D = 2.9223
T0 = 1500.5  # BTJD; arbitrary anchor (the real T0 is sector-bound)
DURATION_H = 3.17
TARGET_DEPTH_PCT = 0.505
NEIGHBOUR_DEPTH_PCT = 22.0
TARGET_TIC = "139526205"
NEIGHBOUR_TIC = "139524628"
SEPARATION_ARCSEC = 66.5

# Synthetic time base: 30 d at 2-min cadence (~1 sector).
N_DAYS = 30.0
CADENCE_D = 2.0 / 1440.0
SEED = 42


def _box(t, depth_pct):
    ph = (((t - T0) / PERIOD_D + 0.5) % 1.0) - 0.5
    hw = 0.5 * (DURATION_H / 24.0) / PERIOD_D
    return np.where(np.abs(ph) < hw, 1.0 - depth_pct / 100.0, 1.0)


def main():
    rng = np.random.default_rng(SEED)
    n = int(N_DAYS / CADENCE_D)
    t = 1500.0 + np.arange(n) * CADENCE_D
    # Target: 0.505% dip, sigma 0.5% per cadence -> ~30 sigma
    # on ~950 in-transit cadences (the real MES was 32.1).
    f_target = _box(t, TARGET_DEPTH_PCT) + rng.normal(
        0, 0.005, n)
    # Neighbour: 22% EB, sigma 1% per cadence.
    f_neighbour = _box(t, NEIGHBOUR_DEPTH_PCT) + rng.normal(
        0, 0.01, n)
    np.savez_compressed(
        os.path.join(HERE, "tic139526205_target.npz"),
        time=t, flux=f_target)
    np.savez_compressed(
        os.path.join(HERE, "tic139526205_neighbour.npz"),
        time=t, flux=f_neighbour)
    case = {
        "target_tic": TARGET_TIC,
        "neighbour_tic": NEIGHBOUR_TIC,
        "separation_arcsec": SEPARATION_ARCSEC,
        "period_d": PERIOD_D,
        "filed_period_d": FILED_PERIOD_D,
        "t0": T0,
        "duration_h": DURATION_H,
        "target_depth_pct": TARGET_DEPTH_PCT,
        "neighbour_depth_pct": NEIGHBOUR_DEPTH_PCT,
        "real_mes": 32.1,
        "real_n_events": 16,
        "real_tmag": 11.3,
        "real_radius_rsun": 0.72,
        "synthetic": True,
        "seed": SEED,
        "note": "Synthetic box transits at the real ephemeris "
                "with the real depths. The curves are NOT the "
                "real star's photometry; the verdict (blend) "
                "is the real case's verdict.",
    }
    with open(os.path.join(HERE, "case.json"), "w") as fh:
        json.dump(case, fh, indent=1)
    print(f"wrote fixture: {n} cadences, "
          f"{N_DAYS} d at 2-min cadence")


if __name__ == "__main__":
    main()
