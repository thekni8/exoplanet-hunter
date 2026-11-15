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

`substrate_s01_149269965.npz` — one REAL Sector 1 QLP light
curve (TIC 149269965, 1,281 points at 30-min cadence,
sap_flux), exported 2026-11-15 for the deep-fix follow-up
DF-4: ZERO cadences carry quality bits 29/30 (Sector 1
predates the scattered-light flagging — 1,429 of the VM's
cached S1 stars are clean), 15 cadences carry default-mask
bits, 288 carry bit 12. The DF-4 identity test
(`tests/test_deep_identity.py`) runs the deep pipeline under
deep_v1 and deep_v2 on it and asserts bitwise-identical
search outputs.

`substrate_s01_150428135_spoc.npz` — one REAL Sector 1 SPOC
light curve (TIC 150428135 = TOI-700, 120 s, 19,261 points,
pdcsap_flux), downloaded 2026-11-15 for DF-4: ZERO cadences
carry bits 29/30 (SPOC QUALITY is 16-bit, so bits 29/30
cannot occur), 982 carry default-mask bits. The SPOC half of
the DF-4 identity test.
