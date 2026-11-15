# Injection-recovery smoke-test substrate

`substrate_238620464.npz` — the stitched, cleaned light curve of
TIC 238620464 (Tmag ~12 QLP star, 8 sectors, 35,323 points,
2226-d baseline), fetched 2026-11-13 for the injection-recovery
run (see `~/workspace/goals/exoplanet-hunter/hidden_files/
science-vet/injection-recovery/INJECTION_RECOVERY.md`, host2).

`substrate_s96_31852076.npz` — one REAL Sector 96 QLP light
curve (TIC 31852076, Tmag 12.2, 10,819 points, SYS_RM_FLUX),
with its real TIME, flux and QUALITY columns, exported
2026-11-15 for the mask-fix follow-up M-6: 28.0% of its
cadences carry quality bit 29 and 9.9% carry bit 30, the
heaviest flagging of the six S96 files on the VM. The test
(`tests/test_inject_real_s96.py`) injects trapezoid transits
into it and screens under bulk_v2 vs bulk_v3; the full 6-star
run is `bulk/inject_real_s96.py`, summary in
`bulk/inject_real_s96_summary.json`.

The smoke test (`tests/test_injection.py`) injects trapezoid
transits into this substrate and runs the pipeline mirror
(`injection_harness.run_pipeline_mirror`) — no downloads. The
trials are the STRONG cells from the 2026-11-13 run, which
detected at SDE 31–106: the smoke test proves the detection
machinery still works, it does not re-measure the completeness
floor (that is the full harness's job, run manually).
