# VSX New-Star Filing Packet — TIC 167367406 (EW contact binary)

Prepared 2026-11-06. Data prep only — nothing submitted. Supporting plot:
`TIC167367406_fold.png` (project root). Measurement record:
`vetting_results/167367406_vsx_packet.json`; driver `vsx_packet_167367406.py`.
Classification basis: `RA100_SWEEP_VETTING.md` (full gauntlet, 2026-11-06) and
`VSX_CROSSCHECK_2026-11-06.md` (absent from VSX and from Gaia DR3 variable
tables — a genuine new-star filing, not a revision).

## Form values (VSX new-star submission)

| Field | Value |
|---|---|
| Discoverer | Debashish Sarangi |
| Identifiers | TIC 167367406 · Gaia DR3 5280333334596470400 · 2MASS J06374379-6744390 · UCAC4 112-012153 · ALLWISE J063743.71-674438.4 |
| RA / Dec (J2000) | 06 37 43.69 / −67 44 38.0 (99.4320261°, −67.7438807°) |
| Type | EW |
| Period | 0.434613 d |
| Epoch of primary minimum | BJD 2460095.3776 (TDB) |
| Max magnitude | 14.08 (TESS) |
| Min I magnitude | 14.51 (TESS) |
| Min II magnitude | 14.50 (TESS) |
| Spectral type | M |
| Remarks | Discovered in TESS QLP photometry (sectors 31, 35, 36, 39, 61–67, 69, 87–89, 93, 96, 98) with a custom BLS pipeline; first detected at the 0.65192 d alias of the 0.21731 d photometric cycle. Mean magnitude from the TIC (Tmag 14.205); Gaia DR3 G mean 15.369. |
| Reference | TESS photometry (QLP HLSP, MAST); this work |
| Supporting file | TIC167367406_fold.png — phase-fold plot at the filed period |

## Measurements behind the values

**Orbital fold (P = 0.43461343 d, phase 0 = primary minimum).** The fold is a
textbook EW profile: continuous variation with no flat stretch, two
near-equal minima half a cycle apart (see the supporting plot). Depths
relative to the quadrature (out-of-eclipse) plateau flux 1.07428 ± 0.00017,
measured three ways, all agreeing that Min I is the deeper (primary) by a
small, consistent margin — a near-twin system:

| Estimator | Min I depth | Min II depth |
|---|---|---|
| Window means (±0.06 phase) | 25.88 ± 0.06 % | 25.71 ± 0.05 % |
| Harmonic model (k = 1–4) extrema | 29.84 % | 29.67 % |
| Parabola vertex on 100-bin profile bottom | **32.29 ± 0.11 %** | **31.97 ± 0.10 %** |

The window means dilute the V-shaped bottoms and the k ≤ 4 model smooths
them; the parabola-vertex values are the filed basis. Min I bottom flux
0.7274 ± 0.0012, Min II 0.7309 ± 0.0011 (per-sector median-normalized).

**Period.** Two-stage χ² scan of a k = 1–4 harmonic fit over the full
1901.2 d baseline (BTJD 2144.63–4045.86): **P = 0.43461343 ± 0.00000017 d**
(formal). Photometric cycle = P/2 = 0.21730672 d, matching the vetting's
Lomb–Scargle peak (0.21731 d). Cross-check: the BLS alias-derived value
0.43461013 d agrees within 3.3 × 10⁻⁶ d.

**Epoch.** From the global harmonic fit (Monte Carlo over the coefficient
covariance, 300 draws): primary minimum nearest mid-baseline at
**BJD_TDB 2460095.37763 ± 0.00005** (BTJD 3095.37763). Direct validation:
parabola vertices of the observed binned minima fall −0.0001 and −0.0007
cycles from the ephemeris phases 0.0 / 0.5 — the minima land on the
ephemeris to ≲ 0.0003 d.

**Magnitudes.** Convention: the phase-averaged (mean) flux of the folded
curve is set equal to the TIC catalogue magnitude (Tmag 14.2054); extrema
follow from the measured relative fluxes. TESS band: **max 14.084,
Min I 14.507, Min II 14.502** (statistical σ ≈ 0.002 mag) → filed rounded
to 14.08 / 14.51 / 14.50. Total TESS amplitude ≈ 0.42 mag. Gaia G: TIC
mean 15.3689 (Gaia DR3 phot_g_mean_mag 15.353); estimated G extrema
assuming the same fractional amplitude as TESS — max ≈ 15.25,
Min I ≈ 15.67, Min II ≈ 15.67 (caveat: G is bluer; the true G amplitude
may differ slightly). The filed magnitudes are the TESS ones, as with the
project's TIC 308851365 packet.

**Star.** TIC row (ID-verified): R* 0.389 R☉, M* 0.379 M☉, Teff 3542 ± 157 K
(≈ M3.5 dwarf → spectral type filed as "M"), Tmag 14.205, Gaia G 15.369,
contratio 0.197. No distance/parallax in the TIC row.

**Data & method notes.** TESS QLP HLSP light curves for the 18 sectors
listed in the remarks, read from the local MAST cache (KSPSAP_FLUX for
sectors ≤ 39, DET_FLUX for sectors ≥ 61), quality == 0 cadences only,
per-sector median normalization (the vetting stitch's convention),
154,687 cadences. This quality cut is slightly stricter than the vetting's
181,204-point stitch; all headline values were re-measured on this curve.
Standalone driver — hunter.py not imported; `data/hunter.db` md5
33b70438b3669f9c313b510488d20d48 and `discoveries.csv` md5
2c8abaae5be0456af6a7effa8a22b6ff verified unchanged after the run.
