# Blend fixture — TIC 139526205 (synthetic)

The S97 case: TIC 139526205 showed a 0.505% dip at P 2.9220404 d
(MES 32.1, 16 events, 3.17 h) that turned out to be a BLEND — a
photocopy of a ~22% eclipsing binary on TIC 139524628, 66.5″ away
(see `archive/bulk-screens/s0097/RECALIBRATION_S0097.md`).

**These light curves are synthetic.** No real TIC 139526205 data is
on disk (the S97 run data lives on the Mac). The fixture is box
transits at the real ephemeris with the real depths (0.505% target,
22% neighbour) and white noise scaled to a target significance in
the same ballpark as the real MES 32.1. What it proves is the
blend function's verdict on a photocopy case — not the real star's
photometry.

- `tic139526205_target.npz` — target time/flux (30 d, 2-min cadence)
- `tic139526205_neighbour.npz` — neighbour time/flux (same grid)
- `case.json` — the real-case facts + the synthetic disclaimer
- `make_fixture.py` — deterministic generator (seed 42); re-run it
  to regenerate
