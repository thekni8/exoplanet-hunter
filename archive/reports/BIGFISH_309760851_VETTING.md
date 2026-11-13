# TIC 309760851 — Full Gauntlet Vetting

**Verdict: BLEND — the signal is the pulsation of a catalogued RR Lyrae
star 23.6″ away, photocopied onto the target by aperture leakage.
Not a planet. Nothing to file (the true source is already in VSX).**

Candidate (big-fish sweep, RA 80.0 / Dec −65.0, found independently by the
Codespace run job 1d517ced231f4db1 and the Mac re-run job 3f8d55d080cf4161,
identical numbers both times): P 0.7083 d, SDE 19.2, depth ~0.12%,
persistence stamp 11/12, implied Rp ~6.0 R⊕ on R* 1.64 R☉, Tmag 14.23.

Target: TIC 309760851 — RA 80.105330, Dec −65.099181; Teff 6155 K,
R 1.639 R☉, M 1.17 M☉, Gaia DR3 4661020662808439680, G 14.65.
Data reality: NO SPOC/TESS-SPOC/QLP products exist for this star. All 27
archive products are HLSP extractions (eleanor-lite, TGLC, T16) covering
only 10 unique sectors (1, 2, 4–9, 11, 12 — TESS Year 1). The sweep's
"11/12 persistence" was over products, not 12 distinct sectors.

## Stage 0 — catalogues / identity

- VSX cone 120″ (query.votable route, raw-XML parse; positive control
  TIC 308851365 returned at 0.02″, ROT, P 0.75629 — route validated):
  - **Gaia DR3 4661020830290636544 = TIC 733257403, 23.6″ away, type
    RRAB, P 0.70817 d, mag 18.44–19.15** (Tmag 18.54, Teff 6679 K).
    Our period: 0.70827 d (ΔP = 1.0×10⁻⁴ d, within BLS precision over
    the Year-1 baseline).
  - TIC 309760861 at 94″, type L (irregular, no period) — not implicated.
- TIC census 150″: 1,064 sources (crowded CVZ field). Brightest
  neighbours: TIC 309760854 (14.2″, Tmag 15.78), TIC 309760840 (50.4″,
  Tmag 12.25 — itself a sweep target in the same patch, no hit),
  TIC 309760844 (88″, Tmag 14.09). TIC contratio for the target: none
  listed (flag only, never used as clearance).
- Dilution arithmetic: the RR Lyrae carries ~1.9% of the target's flux
  but pulsates ~0.7 mag peak-to-peak; ~20–30% aperture capture of its
  variation reproduces the observed 0.12% depth. Physically comfortable.
- Gaia ESA TAP was SSL-broken from this VM and the AIP mirror timed out
  on the cone query, so Gaia vari-table rows were not retrieved; the VSX
  entry (itself Gaia-DR3-derived) carries the classification and period.

## Stage 1 — reproduce (driver bf851_vet.py, cap 20)

Reproduced exactly: **P 0.70827083 d, T0 1325.86547 BTJD, SDE 19.2,
depth 0.114%, Rp 6.04 R⊕** — a third independent reproduction.
Uncapped analyze (19 products): BLS SDE 33.0. The signal is unquestionably
real in the extracted light curves.

## Stage 2 — raw-flux persistence at the fixed ephemeris

- Cap-20 persistence: positive depth 0.07–0.17% in 11 of 12 usable
  product entries (only sector 11 flat, −0.02%).
- Uncapped persistence: **CONSISTENT — 19 usable, 17 positive,
  weighted mean depth 0.132%.**
- All data is Year-1 (sectors 1–12), so no late-era test exists for this
  star; persistence is across time within Year 1 and across three
  independent extraction pipelines.

## Stage 3 — character

- **Duration kill:** BLS duration 5.98 h = 35% of the cycle. The maximum
  possible transit duration on this star at P 0.708 d is ~2.5 h
  (a ≈ 2.27 R*). The event is **2.4× too wide to be a transit of the
  target** — the same signature that convicted TIC 149631332.
- **Fold shape (production diagnostic, 19 products):** the binned fold
  is a broad, asymmetric wave — gentle decline into a wide minimum, then
  a distinct brightening bump peaking ~+5.5 h at +0.14% above baseline.
  Pulsation morphology, not a flat-bottomed box with sharp contacts.
- Odd/even (driver stage b): odd 0.034% vs even 0.103% at 2P — the
  mechanical gate fired "likely-eclipsing-binary". Read in context:
  folding a single asymmetric pulsation wave at twice a slightly-off
  period makes alternate cycles sample different phases of the steep
  limb, manufacturing an odd/even split; it does not require two
  distinct eclipses. Double-period stage: no ellipsoidal wave
  (+0.040% ± 0.011%).
- The RR Lyrae has no light-curve products of its own in the archive,
  so a neighbour-fold photocopy comparison was done in pixel space
  instead (Stage 4 aperture folds).

## Stage 4 — difference imaging (TESSCut, sectors 2 / 8 / 12)

Difference = median out-of-dip − in-dip at the sweep ephemeris.

| Sector | Centroid to target | Centroid to RR Lyrae | Dip depth, tight target ap. | Dip depth, std target ap. | Dip depth, RR-Lyrae ap. | Phase amp, RR-Lyrae ap. |
|---|---|---|---|---|---|---|
| 2  | 36.8″ | **16.3″** | 0.05% | 0.07% | 0.14% | 3.50% |
| 8  | 36.9″ | **13.7″** | 0.13% | 0.34% | 0.50% | 3.69% |
| 12 | **9.3″** | 32.0″ | 0.21% | 0.33% | 0.99% | 3.28% |

- Centroids sit on the RR Lyrae in 2 of 3 sectors. Sector 12's centroid
  sits target-side — recorded honestly; at 0.12% depth the
  difference-image centroid is noise-prone (single-pixel peak positions
  were unusable in all three sectors, 45–143″ away).
- The aperture depth gradient points at the RR Lyrae in every sector:
  the dip deepens monotonically as the aperture moves from tight-on-
  target → standard → centred on the RR Lyrae (up to 0.99% in sector
  12), and the RR-Lyrae-centred aperture carries a ~3.3–3.7% full
  phase amplitude at the candidate period in all three sectors.

## Reconciliation

The driver's mechanical class is LIKELY BINARY (its class set has no
pulsator-blend label; the kill fired at the odd/even gate). The
hand-vetted class, on the full evidence — a catalogued RRAB at the same
period 23.6″ away, an impossibly wide "transit", a pulsation-shaped
fold, difference-image centroids on the neighbour in 2/3 sectors, and a
depth gradient that grows toward the neighbour in 3/3 — is:

**BLEND: TIC 309760851's 0.7083 d signal is the blended pulsation of
TIC 733257403 (VSX RRAB, P 0.70817 d). Not a planet, not a binary on the
target. The big-fish patch (RA 80 / Dec −65) closes with 0 survivors
from 6 hits. No filing: the source is already catalogued.**

## Bookkeeping

- hunter.db md5 33b70438b3669f9c313b510488d20d48 and discoveries.csv
  md5 2c8abaae5be0456af6a7effa8a22b6ff — byte-identical before and after
  (driver history logging suppressed, per house discipline).
- Side files: vetting_results/bf851_stage0.json, bf851_vsx.json,
  309760851.json, 309760851_persistence_cap20.json, bf851_stage4.json,
  bf851_driver.log; scripts bf851_stage0.py, bf851_vsx.py, bf851_vet.py,
  bf851_stage4_diffimg.py. (bf851_folds.json is a failed standalone
  TGLC-stitch fold — flux handling bug, superseded by the production
  diagnostic fold in reports/TIC_309760851_diagnostic.png.)
- Parser lesson logged: a `\D+` separator in a coordinate regex eats the
  minus sign of a negative declination (`,-`); comma-anchor the split.
