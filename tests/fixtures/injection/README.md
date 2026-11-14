# Injection-recovery smoke-test substrate

`substrate_238620464.npz` — the stitched, cleaned light curve of
TIC 238620464 (Tmag ~12 QLP star, 8 sectors, 35,323 points,
2226-d baseline), fetched 2026-11-13 for the injection-recovery
run (see `~/workspace/goals/exoplanet-hunter/hidden_files/
science-vet/injection-recovery/INJECTION_RECOVERY.md`, host2).

The smoke test (`tests/test_injection.py`) injects trapezoid
transits into this substrate and runs the pipeline mirror
(`injection_harness.run_pipeline_mirror`) — no downloads. The
trials are the STRONG cells from the 2026-11-13 run, which
detected at SDE 31–106: the smoke test proves the detection
machinery still works, it does not re-measure the completeness
floor (that is the full harness's job, run manually).
