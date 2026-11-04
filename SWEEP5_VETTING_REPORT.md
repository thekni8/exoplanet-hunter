# Sweep 5 — Vetting Report

Patch centre: **RA 110.0, Dec −63.0**, cone 1.0° — the easternmost
pointing of the queue, 9.2° from the south ecliptic pole. Dev ran the
sweep on the current code (in-sweep persistence + contamination flag +
raw-fold exhibit) in his Codespace on 2026-11-04 (job
8e8bdb2465314eb5). Sweep settings as before: Tmag 11.5–15, R 0.2–0.5
R_sun, sector cap 20, Max Stars 20. Result: **16 hits at SDE ≥ 8.5
from 19 analyzed targets — an 84% hit rate, the richest yet** (sweeps
1–4 produced 9, 11, 6, 11) — plus one target (11) that failed before
analysis on a data-format fault diagnosed in Appendix A. Every hit
arrived pre-stamped by the in-sweep persistence code; **none was
stamped "persistent"** — 5 patchy, 11 fails-persistence. Method: the
stage gauntlet (reproduce → odd/even → double-period → orbit-phase →
persistence), run post-gate where the sweep-3/4 precedent requires it,
plus TIC contamination, Zooniverse known-check, and a NASA Exoplanet
Archive TOI TAP check per star. The five patchy hits also received
the standing uncapped era-split tiebreaker. Fold-completion
(reproduce + odd/even + double-period) was run for the eleven
fails-persistence hits; the trio member among them (TIC 349268505)
was run in full mode so its orbit-phase and persistence stages also
exist.

Patch context worth carrying through every section:

- **The contamination flag mechanics verified a fifth time.** The 7
  flagged hits measure TIC contratio 0.156–2.524; the 9 unflagged
  hits measure 0.012–0.075. The 0.10 line separates the two groups
  exactly, with no borderline cases this patch.
- **BLS durations pin at the 5.976 h grid maximum on 10 of 16
  hits** — the pipeline is fitting broad, shallow structures, not
  box-shaped transits. This patch's hits are variability-flavoured
  to a degree the previous four were not.
- **Three hits share P = 13.7215 d exactly** — the TESS orbit
  period. Their cross-check has its own section below; the short
  version is that they are three independent locks onto the shared
  window alias, not one systematic and not one contaminator.
- **A ~24 d sub-cluster** (targets 3, 7, 10) resolves as three
  independent ~47–48 d eclipsing-binary-family objects, one octave
  up from sweep 4's alias band (note after target 10's section).

History discipline for this vetting: `data/hunter.db` was never
touched (no API server ran; md5 `33b70438…` before and after), and
`discoveries.csv` appends were suppressed in the vetting driver
(`hunter.log_candidate` no-op); the one un-patched auxiliary run (the
fold-shape exhibit) appended two rows, which were removed and the
file verified byte-identical to its pre-session md5 (`2c8abaae…`).
Nothing in this report was pushed anywhere.

---

## Target 15 of 20 — TIC 349481800 — **INCONCLUSIVE** (the spot case)

Sweep hit: **P = 19.4477 d, SDE = 9.4**, no contamination flag; the
in-sweep stamp read **"9/17 sectors, mean depth 0.53% — patchy."**
Star: Tmag 14.73, TIC radius 0.401 R_sun, 0.392 M_sun, Teff 3442 K
(M dwarf), 166 pc. Position RA 110.98109°, Dec −63.31668° — 0.55°
from the patch centre. IDs: 2MASS 07235545-6319000,
Gaia DR3 5288720718529490560.

This is the star the brief flagged as the near-twin of sweep 3's
TIC 177172764 (P 19.89, patchy, real excess, depth-inconsistent →
evolving starspots, INCONCLUSIVE). It lands in the same place, by a
route that runs through a machine misfire the record has seen
before — so the section is explicit about what was overruled and
why.

### Stage by stage

- **(f) Known checks:** Zooniverse Talk **False**. NASA Archive TOI
  table: **0 rows** (first-pass TAP query errored in the afternoon's
  degraded window; the retry confirmed 0, as for all 16 hits).
- **(a) Reproduce: exact.** P = 19.4477 d, SDE 9.42, depth 0.884%,
  nominal Rp 4.10 R_earth, duration 1.94 h, 20 sectors, 201,360
  points.
- **(b) Odd/even: the driver's kill — and a documented misfire.**
  The machine verdict is "likely-eclipsing-binary" on odd **+0.077%**
  vs even **−0.061%** ("180% apart"). The even fold is a *brightening*;
  both folds are ~0.07% against a BLS depth of 0.884% — the ratio
  rule fired on two zeros. This is the exact misfire class the
  sweep-4 audit recorded (TIC 389564031's "EB" on 0.0027%/0.0001%;
  TIC 294671640 before it). A verdict cannot rest on it, so the
  remaining stages were read on their own evidence.
- **(c) Double-period: no binary there either.** Refined 2P =
  38.8951 d; eclipse windows **+0.253% / −0.020%** — one shallow
  window and one negative: no eclipse pair. Quadrature delta
  **+0.095% ± 0.019% at 4.9σ** — real but under the pre-set +0.2%
  likely-binary line, and without a pair it convicts nothing.
- **(d) Orbit-phase: no pile-up** (P/orbit ratio 1.42): on-data
  boundary fraction 0.25 vs 0.219 by chance, R = 0.28.
- **(e) Persistence at cap 20, re-derived independently: matches
  the in-sweep stamp digit for digit** — 17 usable sectors, **9/17
  ≥ 1.5σ**, weighted-mean depth **+0.527% ± 0.078% (6.7σ)** (the
  stamp's 9/17, 0.53%). But the depths are grossly inconsistent
  with a constant: χ² p = 1.5×10⁻⁸, per-sector values running
  −0.87% to +4.29%. Raw monster sectors: 37 (−7.9%), 67 (−12.0%),
  95 (+11.4%).
- **Contamination: 0.047** — a clean aperture; nobody else's
  eclipse is available to blame.

### The uncapped tiebreaker (all 23 sectors) — with the cross-stitch warning

Uncapped BLS abandons the swept period: peak moves to **14.3757 d,
SDE 15.68, depth 1.856%, duration pinned at the 5.976 h grid
maximum** — a broad wave, not a box. Persistence at the *fixed*
19.4477 d ephemeris over all 23 sectors: CONCENTRATED by count
(3/20 sectors ≥ 1.5σ) yet the weighted mean stays positive,
**+0.448% ± 0.104% (4.3σ)**. Era split of that stitch: sectors
27–39 +0.440% at 1.1σ (3 ranges), sectors ≥ 60 +0.449% at 4.2σ
(17 ranges). The two stitches disagree on sector *counts* (the
cap-20 stitch's swept subset reads 9/17 positive; the uncapped
stitch's same-subset reads 3/17) while agreeing on the weighted
mean (+0.45…+0.53%) — the cross-stitch caution from sweep 4
applies verbatim: different product sets flatten differently, and
per-sector significances are the soft quantity; the weighted
excess is the hard one.

### The shape exhibit (why spots, not a silhouette)

Fold-shape analysis at both candidate periods
(`vetting_results/349481800_foldshape.json`):

- At 19.4477 d: Fourier fundamental **A1 = 0.030% (3.4σ)**,
  harmonic **A2 = 0.015%** — A1-dominant ≈ 2:1. A transit train is
  harmonic-rich; an ellipsoidal wave is A2-dominant; a single
  sinusoid is what rotation looks like. The binned fold spans
  0.9950–1.0013 — a broad shallow wave with no box edge. (The
  physical maximum transit duration at this period is 2.67 h
  against the fitted 1.94 h, so duration alone cannot acquit or
  convict here.)
- At 14.3757 d (the uncapped peak): **A1 = 0.234% at ~27σ**,
  A2 = 0.126% — a strong, coherent, A1-dominant modulation. The
  star is plainly a vigorous variable; which of the two periods is
  the rotation fundamental and which the alias, the fold cannot
  say — and does not need to.

### Verdict

**INCONCLUSIVE** — reclassified from the driver's mechanical
LIKELY BINARY (raw verdict preserved in the JSON and above). The
evidence profile is sweep 3's spot case restated: a real excess in
the swept subset (both stitches +0.45…+0.53%), depths inconsistent
with any constant-depth silhouette (χ² p ~ 10⁻⁸), no eclipse at
either parity, no eclipse pair and no tidal wave at double
period, a clean aperture, and a wave morphology at every period
the data offers. On a 3442 K M dwarf, evolving starspots at or
near the rotation period remain the only reading that fits all of
it. Not a candidate; not convictable as anything else.

---

## Target 17 of 20 — TIC 349519662 — **LIKELY BINARY**

Sweep hit: **P = 14.7923 d, SDE = 15.2**, high-contamination flag;
stamp **"9/19 sectors, mean depth 0.34% — patchy."** Star: Tmag
14.94, TIC radius 0.478 R_sun, 0.476 M_sun, Teff 3400 K, 218 pc.
RA 111.21742°, Dec −63.15861° — 0.57° from centre. IDs:
2MASS 07245216-6309309, Gaia DR3 5288757380370348672.

- **(f)** Zooniverse **False**; TOI **0 rows**.
- **(a) Reproduce: exact.** P = 14.7923 d, SDE 15.16, depth 0.736%,
  Rp 4.49, duration 5.976 h (grid maximum), 20 sectors, 187,273
  points.
- **(b) Odd/even: machine kill, LIKELY BINARY** — odd **0.074%**,
  even **0.111%** (ratio 0.66). On its own this would be another
  shallow-ratio firing (the folds carry only ~10–15% of the BLS
  depth); it does not carry the verdict alone.
- **(c) Double-period: the conviction's substance.** Refined 2P =
  **29.0024 d** — note, 0.58 d (2%) from the exact double, the
  refinement doing real work — with eclipse windows **0.606% /
  0.461%**: a genuine, comparable pair at depths of the same order
  as the BLS signal itself. Quadrature delta **+0.178% ± 0.024% at
  7.3σ** — 0.022% under the pre-set +0.2% line, the same species
  of near-line wave the sweep-4 record read as real at 6.7σ
  (TIC 277313805). Spots do not raise a phase-locked quadrature
  wave; a diluted binary does.
- **(d) Orbit-phase: no pile-up** (ratio 1.080): boundary fraction
  0.333, R = 0.277.
- **(e) Persistence: stamp re-derived digit for digit** — MIXED,
  **9/19 ≥ 1.5σ**, weighted mean **+0.345% ± 0.062% (5.6σ)** (the
  stamp's 9/19, 0.34%), χ² p = 3.4×10⁻⁸ (depths inconsistent —
  dilution varying by sector, as in-aperture binaries do).
  Monsters: sectors 95 (+14.9% raw) and 96 (+6.1%).
- **Uncapped tiebreaker (22 sectors):** BLS peak wanders to
  13.8269 d (SDE 13.76, duration still grid-max) — the variability
  background is strong — but persistence at the fixed ephemeris
  keeps a positive excess in both eras (27–39: **+0.229% at 1.5σ**,
  3 ranges; ≥ 60: **+0.181% at 2.6σ**, 18 ranges; all-sector
  +0.189% ± 0.063%). An era-confined spot pattern (the sweep-3
  failure mode) would zero one side; this does not.
- **Contamination: 0.302** (flagged, as the HIT line said). Folds
  cannot separate a target EB from a neighbour EB at this
  dilution; the planet reading is dead either way.

**Verdict: LIKELY BINARY** (driver's verdict upheld, on stage (c)'s
evidence rather than stage (b)'s ratio). The weakest of this
sweep's wave-supported convictions, and recorded as such: pair +
7.3σ near-line wave + era-spread persistence, against a noisy,
monster-bearing, variability-heavy background.

---

## Target 19 of 20 — TIC 349193983 — **LIKELY BINARY**

Sweep hit: **P = 13.2094 d, SDE = 15.0**, high-contamination flag;
stamp **"6/15 sectors, mean depth 0.05% — patchy."** Star: Tmag
14.83, TIC radius 0.464 R_sun, 0.462 M_sun, Teff 3642 K, 229 pc.
RA 108.67108°, Dec −63.15135° — 0.62° from centre. IDs:
2MASS 07144105-6309048, Gaia DR3 5285802545949777536.

- **(f)** Zooniverse **False**; TOI **0 rows**.
- **(a) Reproduce: exact.** P = 13.2094 d, SDE 14.99, depth 1.434%,
  Rp 6.01, duration 5.976 h, 20 sectors (all that exist), 182,599
  points.
- **(b) Odd/even: planet-like** — odd 0.255%, even 0.290%, within
  12%. The equal-twin configuration; this stage is blind here by
  design, which is what stage (c) exists for.
- **(c) Double-period: LIKELY BINARY by the book.** Refined 2P =
  **26.5142 d**; eclipse windows **0.254% / 0.708%** (unequal
  pair); ellipsoidal wave **+0.447% ± 0.029% at 15.2σ** — more
  than twice the pre-set +0.2% line at three times its
  significance floor. Quadratures brighten to 1.0026 against
  shoulders at 0.9981: two stars tidally distorted, showing their
  wide faces twice per orbit. Starspots cannot manufacture this.
- **(d) Orbit-phase: no pile-up** (ratio 0.964): boundary fraction
  0.293, R = 0.100 — the cleanest acquittal of the patch.
- **(e) Persistence (post-gate): stamp re-derived digit for
  digit** — MIXED, **6/15**, weighted mean **+0.053% ± 0.047%**
  (the stamp's 6/15, 0.05%), χ² p = 9.7×10⁻⁹. Monsters: sectors
  68 (+15.4% raw), 69 (+15.3%), 97 (+12.0%) — none of them at the
  eclipse phase often enough to build the fold.
- **Era split (uncapped = cap-20 set; 20 sectors total):** the
  eclipse signal is cycle-2-weighted — sectors 27–39 **+0.700% ±
  0.146% at 4.8σ (4/5 sectors positive)** against sectors ≥ 60 at
  −0.024% (null). Era weighting in a *binary* is no contradiction:
  the aperture (and with it the dilution) changes every sector,
  and this star's aperture is the patch's second-dirtiest.
- **Contamination: 0.899** (flagged). The binary may be the target
  or a bright neighbour; photometry at this dilution cannot say,
  and the planet reading is dead either way.

**Verdict: LIKELY BINARY** — the patchy five's cleanest conviction,
and another exhibit for the audit's standing corollary: a stamp
mean of 0.05% hid a +0.45% tidal wave. The stamp grades the alias,
not the object.

---

## Target 8 of 20 — TIC 349309779 — **BLEND-SUSPECT** (trio member)

Sweep hit: **P = 13.7215 d, SDE = 16.5**, no contamination flag;
stamp **"5/16 sectors, mean depth −0.18% — patchy."** Star: Tmag
14.57, TIC radius 0.348 R_sun, 0.332 M_sun, Teff 3329 K, 123 pc.
RA 109.61916°, Dec −62.66736° — 0.38° from centre. IDs:
2MASS 07182858-6240025, Gaia DR3 5291823639125779456.

- **(f)** Zooniverse **False**; TOI **0 rows**.
- **(a) Reproduce: exact.** P = 13.72152 d, SDE 16.55, depth
  2.810%, Rp 6.40, duration 5.976 h (grid maximum), 19 sectors
  (all that exist), 174,506 points.
- **(b) Odd/even: planet-like** — odd 0.452%, even 0.390%, within
  14%. Real fold dips at both parities — but at ~0.42% they carry
  only ~15% of the 2.81% BLS depth.
- **(c) Double-period: a pair that the sectors disown.** Refined
  2P = 27.4488 d; windows 0.557% / 0.477%; quadrature delta
  +0.128% at 6.0σ (sub-line). Read alone, an EB-shaped fold. Read
  with stage (e), the pair is built from a handful of episodic
  sectors (below) and does not correspond to a steady train.
- **(d) Orbit-phase, at full weight: no pile-up by the pre-set
  rule.** P/orbit ratio **1.0016** — the period is the orbit
  period to 0.16%. On-data centres (n = 33): fraction within
  1.5 d of a segment start **0.121** (centres *avoid* the
  downlink-adjacent phases), fraction within 1.5 d of an orbit
  boundary **0.394** (chance 0.219), circular resultant
  **R = 0.46**. The rule (boundary fraction ≥ 0.5 AND R ≥ 0.4)
  does not fire: the phases cluster loosely (R) but not at the
  boundary. Recorded exactly; the trio section takes up what the
  three members' results mean together.
- **(e) Persistence: stamp re-derived digit for digit** — MIXED,
  **5/16 ≥ 1.5σ**, weighted-mean depth **−0.178% ± 0.045%
  (−4.0σ)**, χ² p = 7.6×10⁻³⁸. Raw monster sectors: 62 (+15.7%),
  68 (+10.0%), 97 (+22.1%). The uncapped run is the same 19
  sectors and returns the same table (era split: sectors 27–39
  **−0.250% at −2.6σ**, 0/5 positive; sectors ≥ 60 **−0.158% at
  −3.1σ**, 5/11 positive).
- **Contamination: 0.040** — clean by the TIC's accounting.

### The negative mean, explained (as the brief required)

A weighted-mean depth of −0.178% ± 0.045% next to an SDE of 16.5
looks like a contradiction; the per-sector table resolves it.
Sector depths at the fixed ephemeris run from **−0.949% to
+14.25%**. The σ-weighting is dominated by a few *quiet* sectors
with very small chunk-σ and negative depths — sector 64 at
**−0.949% ± 0.088% (−10.7σ)** and sector 31 at −0.552% ± 0.141%
(−3.9σ) outweigh everything else in the mean. The positive side
is carried by monster sectors whose depths are enormous but
whose σ's are too (sector 97: +14.25% ± 2.95%; sector 68:
+5.72% ± 1.31%; sector 62: +12.13%, no usable σ). The *median
full event* is +0.29% deep. So: BLS, stacking the whole stitched
curve, coherently accumulates the episodic monster-sector dips
into SDE 16.5; the persistence mean, honestly weighted, reports
that the *typical quiet sector* shows a slight brightening at
that phase and the dips live in a few violent sectors. A negative
weighted mean beside a huge SDE is the fingerprint of episodic,
sector-confined dip violence — not of a steady eclipse train,
which would price in at a consistent positive depth everywhere.
Planets do not switch on for sectors 62/68/97 and off elsewhere;
neither do steady binaries. Aperture-dependent blends and
era-episodic artifacts do exactly this.

**Verdict: BLEND-SUSPECT** (driver's verdict, via the pre-set
rule: MIXED persistence + raw monsters ≥ 5%). The attribution
tension is recorded plainly: the TIC calls the aperture clean
(0.040), so the "blend" here most plausibly names the
sector-aperture-dependent / era-episodic source family rather
than a catalogued neighbour; centroid/difference imaging is the
instrument that could settle the address, as with TIC 374942698's
residue. What is not available on this evidence is a planet.

---

## Target 12 of 20 — TIC 349268662 — **BLEND-SUSPECT** (trio member)

Sweep hit: **P = 13.7215 d, SDE = 10.4**, no contamination flag;
stamp **"6/17 sectors, mean depth 0.01% — patchy."** Star: Tmag
14.70, TIC radius 0.433 R_sun, 0.428 M_sun, Teff 3520 K, 187 pc.
RA 108.92817°, Dec −62.87807° — 0.50° from centre. IDs:
2MASS 07154275-6252410, Gaia DR3 5285997468745187328.

- **(f)** Zooniverse **False**; TOI **0 rows**.
- **(a) Reproduce: exact.** P = 13.72152 d (the trio value to all
  printed digits), SDE 10.41, depth 1.866%, Rp 6.41, duration
  5.976 h, 19 sectors, 173,321 points.
- **(b) Odd/even: planet-like** — odd 0.331%, even 0.393%, within
  16%.
- **(c) Double-period: windows without a wave, pointing the
  wrong way.** Refined 2P wanders to 27.1644 d; windows 0.951% /
  0.832%; quadrature delta **−0.116% ± 0.022% at −5.4σ** — the
  shoulders sit *above* the quadratures, the opposite of an
  ellipsoidal wave. The windows are the monster-sector stack
  (below), not an eclipse pair with a binary's out-of-eclipse
  signature.
- **(d) Orbit-phase, full weight: no pile-up.** Ratio 1.0016;
  on-data n = 34; fraction after segment start 0.147; boundary
  fraction **0.412**; R = 0.337. Rule does not fire.
- **(e) Persistence: stamp re-derived digit for digit** — MIXED,
  **6/17**, weighted mean **+0.015% ± 0.055% (0.3σ — zero)**,
  χ² p = 2.5×10⁻⁵. **Six** raw monster sectors: 39 (−11.5%),
  61 (−6.1%), 68 (+7.8%), 94 (+8.8%), 96 (+19.2%), 97 (+18.1%) —
  of both signs. Event median +0.184%. Era split (uncapped = the
  same 19 sectors): 27–39 **+0.088% at 0.5σ** (nothing); ≥ 60
  **+0.005% at 0.09σ** (nothing). At the fixed ephemeris there is
  no steady excess in either era; the entire BLS signal is the
  monster sectors' episodic dips, stacked.
- **Contamination: 0.047** — clean, as with its trio siblings.

**Verdict: BLEND-SUSPECT** (driver's: MIXED + monsters). The
stamp said "patchy"; the species is refined, the bottom line —
not a planet — is upheld: a zero weighted mean in both eras, with
±6–19% raw excursions supplying the whole signal, is not a
transit train on this star.

---

## Target 14 of 20 — TIC 349268505 — **BLEND-SUSPECT** (trio member)

Sweep hit: **P = 13.7215 d, SDE = 10.3**, no contamination flag;
stamp **"4/16 sectors — fails persistence — blend-suspect."**
Star: Tmag 13.93, TIC radius 0.400 R_sun, 0.392 M_sun, Teff
3434 K, 116 pc. RA 108.89192°, Dec −63.14151° — 0.52° from
centre. IDs: Gaia DR3 in JSON; 2MASS via catalogue JSON.

Run in full mode (not folds-only) so the trio cross-check would
have its orbit-phase and persistence stages.

- **(f)** Zooniverse **False**; TOI **0 rows**.
- **(a) Reproduce: exact.** P = 13.72152 d, SDE 10.32, depth
  0.929%, Rp 4.21, duration 5.976 h, 20 sectors, 186,920 points.
- **(b) Odd/even: planet-like** — odd 0.187%, even 0.155%, within
  17%.
- **(c) Double-period: the project's most extreme out-of-eclipse
  structure.** Refined 2P = 27.4252 d; windows 0.306% / −0.010%;
  quadrature delta **−0.489% ± 0.013% at −37σ** — at double
  period the light *dips* at both quadrature phases. The driver's
  gate fired here: INCONCLUSIVE ("unexplained out-of-eclipse
  structure"). In the trio's context the structure has an
  explanation: dips at the anti-phase of the 1P ephemeris (which
  land on the 2P fold's quadratures) are the same episodic
  population seen at phase 0 — the fold is sampling dip violence
  at both parities of the alias grid.
- **(d) Orbit-phase, full weight: no pile-up.** Ratio 1.0016;
  on-data n = 38; fraction after segment start **0.105**;
  boundary fraction 0.342; R = 0.442. Rule does not fire.
- **(e) Persistence (post-gate): CONCENTRATED, 4/16** — the
  in-sweep stamp's count re-derived exactly — weighted mean
  **−0.088% ± 0.027% (−3.3σ)**, χ² p = 4.6×10⁻¹⁰. **Six** raw
  monsters of both signs: 62 (+5.7%), 67 (+5.6%), 68 (−9.3%),
  69 (−10.3%), 95 (+12.6%), 97 (+12.5%). Event median +0.079%.
- **Contamination: 0.012** — the cleanest aperture of the trio.

**Verdict: BLEND-SUSPECT** — reclassified from the driver's
stage-(c) INCONCLUSIVE (raw verdict preserved in the JSON). The
reasoning is consistency on identical evidence: this star's
stage-(e) profile (CONCENTRATED, negative weighted mean, six
bidirectional monsters) is the same profile that classed both
its trio siblings BLEND-SUSPECT, and unlike the patch's one
genuine grey case (TIC 349481800) there is no steady excess here
to leave unexplained — the weighted mean is *negative*. The
in-sweep stamp's species is thereby upheld after all.

---

## The 13.7215 trio — cross-check

Three of the patch's twenty targets — TIC 349309779 (t8),
TIC 349268662 (t12), TIC 349268505 (t14) — hit at **P = 13.7215 d
exactly** (all three reproductions return 13.72152 d, the same
BLS grid point, which sits 0.16% from the 13.7 d TESS orbit).
Three hypotheses were on the table: one shared contaminator, one
shared (scattered-light / window) systematic, or three separate
alias locks of the sweep-4 kind. The evidence:

**Not one contaminator.** Pairwise separations: 779↔662
**22.8′**, 779↔505 **34.7′**, 662↔505 **15.8′** — 45 to 99 TESS
pixels apart. No aperture couples them; all three TIC
contamination ratios are clean (0.040 / 0.047 / 0.012).

**Not one instant-stamped systematic.** If a single
absolute-time phenomenon (e.g. a scattered-light episode train)
had imprinted all three, their eclipse centres would share an
absolute phase. They do not: the refined epochs fold to absolute
phases **0.797 / 0.854 / 0.810** of the common period — pairwise
offsets **0.19 d, 0.59 d, 0.78 d** against an event duration of
0.25 d. (779↔505 at 0.19 d is within one duration; the others are
2.4–3.1 durations apart.) And each star's own orbit-phase test
*acquits* the downlink-scattered-light shape: centres avoid
segment starts (fractions 0.105–0.147 within 1.5 d of a start,
where the systematic would pile them), boundary fractions
0.342–0.412 stay under the pre-set 0.5 line, and the pile-up
rule fires for **none** of the three — the fourth patch in a row
where the orbit-phase test acquits the instrument, here at the
exact period it was built for.

**Not sweep 4's alias family either.** Sweep 4's 13.2–14.3 d
band dissolved into half-period aliases of real ~27–28 d
binaries. The trio's double-period stages do not converge on a
shared binary family: 779 shows a 27.449 d pair its own sectors
disown; 662's refinement wanders to 27.164 d with a *negative*
quadrature delta; 505 shows a quadrature *dip* at 27.425 d
instead of a pair. There is no common ~27.44 d structure.

**What they share is a population and a window.** All three
carry the monster-era signature — raw excursions of ±6–22% in
sectors ≥ 60 (94/96/97 recur; 62/68/69 join) — and all three
stars' sector sets are near-identical (same patch, same cycles),
so their BLS window functions are near-identical too. Episodic
dips recurring through a shared gappy window give BLS a common
alias to lock: the grid point nearest the spacecraft's own
cadence, 13.7215 d. Each star's noise picked its own phase at
that period; each star's persistence then failed or scattered in
its own way (weighted means −0.178%, +0.015%, −0.088%). Three
independent locks, one explanation — the patch-level cousin of
sweep 4's band, with the monster-era dip population in place of
the binary family as the raw material.

Each member's verdict stands on its own stages: **BLEND-SUSPECT
× 3**. Full numbers: `sweep5_logs/trio_analysis.json`.

---

## Target 13 of 20 — TIC 349309664 — **LIKELY BINARY** (fold completion)

Sweep hit: **P = 13.2462 d, SDE = 10.4**, no flag; stamp
**"4/15 — fails persistence — blend-suspect."** Star: Tmag 14.83,
R 0.414 R_sun, 0.407 M_sun, Teff 3320 K, 172 pc; 0.52° from
centre. Contratio **0.035**.

- **(f)** Zooniverse **False**; TOI **0 rows**.
- **(a) Reproduce: exact.** P = 13.2462, SDE 10.42, depth 2.345%,
  20 sectors.
- **(b) Odd/even: planet-like** — 0.467% / 0.352% (deep folds;
  the equal-twin configuration again).
- **(c) Double-period: the patch's most emphatic binary.**
  Refined 2P = **27.0237 d**; eclipse windows **1.804% /
  0.607%**; ellipsoidal wave **+1.098% ± 0.029% at 37.9σ** — the
  second-strongest tidal wave in the project's five patches
  (after sweep 4's +3.113%). No reading of this star survives
  except a binary; its true period is 27.02 d and the sweep's
  13.25 d was the half-alias.

**Verdict: LIKELY BINARY.** The stamp's "fails persistence" was
the alias ephemeris failing, as calibrated — the object behind
it is the least ambiguous binary of the patch.

---

## Target 18 of 20 — TIC 349193749 — **LIKELY BINARY** (fold completion)

Sweep hit: **P = 13.9690 d, SDE = 12.5**, no flag; stamp
**"3/16 — fails persistence — blend-suspect."** Star: Tmag 14.97,
R 0.497 R_sun, 0.495 M_sun, Teff 3558 K, 255 pc; 0.59° from
centre. Contratio **0.026** — the patch's cleanest flagged-class
aperture among the hits.

- **(f)** Zooniverse **False**; TOI **0 rows**.
- **(a) Reproduce: exact.** P = 13.9690, SDE 12.49, depth 1.997%,
  20 sectors.
- **(b) Odd/even: planet-like** — 0.401% / 0.340% (deep, matched).
- **(c) Double-period: LIKELY BINARY by the book.** Refined 2P =
  **27.9824 d**; windows **0.784% / 0.889%** (near-equal — the
  twin configuration stage (b) cannot judge); wave **+0.301% ±
  0.027% at 11.2σ**, over the +0.2% line. This is the
  TIC 308851365 mechanism verbatim: equal eclipses acquitted by
  odd/even, convicted by the tidal wave at double period.

**Verdict: LIKELY BINARY**, true period ≈ 27.98 d.

---

## Target 1 of 20 — TIC 349370722 — **LIKELY BINARY** (fold completion)

Sweep hit: **P = 13.2045 d, SDE = 11.6**, high-contamination flag;
stamp **"1/13 — fails persistence — blend-suspect"** (the patch's
thinnest persistence count). Star: Tmag 14.54, R 0.300 R_sun,
0.276 M_sun, Teff 3282 K; 0.11° from centre. Contratio **0.156**.

- **(f)** Zooniverse **False**; TOI **0 rows**.
- **(a) Reproduce: exact.** P = 13.2045, SDE 11.56, depth 2.239%,
  duration 4.39 h, 16 sectors.
- **(b) Odd/even: alternating** — 0.134% / 0.210% (36% apart).
- **(c) Double-period: emphatic.** Refined 2P = **27.1189 d**;
  windows **1.490% / 0.582%**; wave **+0.748% ± 0.027% at
  27.3σ**. A deep unequal pair plus one of the project's
  strongest waves: the 1/13 persistence count was the alias
  failing on a diluted aperture, nothing more.

**Verdict: LIKELY BINARY**, true period ≈ 27.12 d — another
member of the southern ~27 d family, caught at its half-period.

---

## Target 6 of 20 — TIC 349370417 — **LIKELY BINARY** (fold completion)

Sweep hit: **P = 13.2511 d, SDE = 18.0 — the patch's highest
SDE**, no flag; stamp **"4/15 — fails persistence —
blend-suspect."** Star: Tmag 14.27, R 0.433 R_sun, 0.429 M_sun,
Teff 3437 K, 146 pc; 0.36° from centre. Contratio **0.043**.

- **(f)** Zooniverse **False**; TOI **0 rows**.
- **(a) Reproduce: exact.** P = 13.2511, SDE 18.03, depth 0.828%,
  duration 5.976 h, 20 sectors.
- **(b) Odd/even: alternating** — 0.139% / 0.078% (ratio 0.56).
- **(c) Double-period:** refined 2P = **26.6673 d**; windows
  **0.466% / 0.073%** (a very unequal pair — the shallow window
  is 6× down); quadrature delta **+0.118% ± 0.013% at 9.1σ** —
  sub-line in amplitude, unambiguous in significance, the
  TIC 277313805 configuration. Alternation + unequal pair + a
  9σ wave: the binary reading is the only one that fits all
  three.

**Verdict: LIKELY BINARY**, true period ≈ 26.67 d.

---

## Target 3 of 20 — TIC 349408892 — **LIKELY BINARY** (fold completion)

Sweep hit: **P = 24.2110 d, SDE = 13.0**, high-contamination flag;
stamp **"5/18 — fails persistence — blend-suspect."** Star: Tmag
14.68, R 0.481 R_sun, 0.479 M_sun, Teff 3629 K, 217 pc; 0.31°
from centre. Contratio **0.363**.

- **(f)** Zooniverse **False**; TOI **0 rows**.
- **(a) Reproduce: exact.** P = 24.2110, SDE 13.01, depth 0.861%,
  duration 5.976 h, 20 sectors.
- **(b) Odd/even: machine kill on a near-zero ratio** — odd
  0.004%, even 0.044% ("91% apart"). Noted as the fragile class;
  the verdict rests on (c).
- **(c) Double-period: LIKELY BINARY on the wave.** Refined 2P =
  **48.0060 d**; windows **0.401% / −0.290%** — one eclipse
  window and one *negative* (no second eclipse at this phase —
  an eccentric or single-eclipse geometry, or the secondary
  lost in the contaminated aperture); quadrature wave
  **+0.205% ± 0.024% at 8.7σ**, at the pre-set +0.2% line. The
  wave is the conviction: a phase-locked tidal signal at 48 d
  does not arise from spots or pipeline weather.

**Verdict: LIKELY BINARY**, true period ≈ 48.0 d (single-eclipse
morphology recorded honestly). Member of the ~24 d sub-cluster —
see the note after target 10.

---

## Target 7 of 20 — TIC 349370907 — **LIKELY BINARY** (fold completion)

Sweep hit: **P = 23.9292 d, SDE = 11.0**, high-contamination flag;
stamp **"3/18 — fails persistence — blend-suspect."** Star: Tmag
14.22, R 0.433 R_sun, 0.428 M_sun, Teff 3536 K, 152 pc; 0.36°
from centre. Contratio **0.163**.

- **(f)** Zooniverse **False**; TOI **0 rows**.
- **(a) Reproduce: exact** (after a ~6.5-minute MAST download
  stall in this stage, which healed — see session notes).
  P = 23.9292, SDE 11.02, depth 0.455%, 20 sectors.
- **(b) Odd/even: machine kill on a ratio against zero** — odd
  0.025%, even **0.000%** (deepest fold 5% of BLS depth). The
  gate's firing is recorded; it carries no weight.
- **(c) Double-period: the actual evidence.** Refined 2P =
  **47.8523 d**; windows **0.228% / 0.088%** (unequal pair,
  primary at ~50% of the BLS depth); quadrature delta
  **+0.076% ± 0.013% at 6.0σ** (sub-line amplitude, significant
  — the recurring near-line class). An unequal eclipse pair is
  morphology a planet fold cannot produce; with the 6σ wave
  beside it, the binary reading stands.

**Verdict: LIKELY BINARY**, true period ≈ 47.85 d — graded the
weaker tier of the patch's pair-based convictions. Sub-cluster
member; see note after target 10.

---

## Target 10 of 20 — TIC 349273239 — **LIKELY BINARY** (fold completion)

Sweep hit: **P = 23.5201 d, SDE = 11.0**, high-contamination flag;
stamp **"3/19 — fails persistence — blend-suspect."** Star: Tmag
13.81, R 0.365 R_sun, 0.352 M_sun, Teff 3469 K, 100 pc; 0.41°
from centre. Contratio **1.025** — the aperture carries more
contaminating flux than target flux.

- **(f)** Zooniverse **False**; TOI **0 rows**.
- **(a) Reproduce: exact.** P = 23.5201, SDE 11.04, depth 0.870%,
  duration 5.976 h, 20 sectors.
- **(b) Odd/even: alternating, shallow** — 0.052% / 0.010%
  (deepest fold 6% of BLS depth).
- **(c) Double-period:** refined 2P = **47.3766 d**; windows
  **0.501% / 0.106%** (4.7× unequal; primary at 58% of the BLS
  depth); delta +0.054% at 2.9σ (no wave support). The pair
  convicts by the project's standing precedent (an unequal pair
  at the refined double is not producible by a 1P silhouette);
  in a contratio-1.03 aperture the binary is presumably the
  neighbour's, which the class name already allows — the target
  is not a planet host on this evidence either way.

**Verdict: LIKELY BINARY** (in-aperture), true period ≈ 47.38 d.

### The ~24 d sub-cluster, resolved

Targets 3, 7, 10 hit at 24.2110 / 23.9292 / 23.5201 d. Their
double-period refinements land at **48.006 / 47.852 / 47.377 d**
— close, but mutually incoherent (the 0.63 d spread is > 1 full
phase cycle of drift across the baseline), and the stars sit
**38.6′ / 35.7′ / 36.2′** apart pairwise. No shared ~12 d
structure appears in any stage. Conclusion: three independent
long-period binary-family objects whose half-period aliases
clustered at ~24 d — sweep 4's band phenomenon one octave up,
not a shared source and not a systematic.

---

## Target 2 of 20 — TIC 349370477 — **LIKELY BINARY** (fold completion)

Sweep hit: **P = 12.9374 d, SDE = 12.7**, no flag; stamp
**"5/19 — fails persistence — blend-suspect."** Star: Tmag 13.95,
R 0.370 R_sun, 0.357 M_sun, Teff 3415 K, 104 pc; 0.27° from
centre. Contratio **0.068**.

- **(f)** Zooniverse **False**; TOI **0 rows**.
- **(a) Reproduce: exact.** P = 12.9374, SDE 12.69, depth 0.456%,
  duration 4.75 h, 20 sectors.
- **(b) Odd/even: machine kill on near-zeros** — 0.028% / 0.073%
  (deepest fold 16% of BLS depth). Recorded; carries no weight
  alone.
- **(c) Double-period: the pair.** Refined 2P = **25.1784 d**;
  windows **0.205% / 0.331%** (45% and 73% of the BLS depth);
  delta +0.016% at 1.5σ (no wave).

**Verdict: LIKELY BINARY** — and the reasoning is precedent,
checked numerically rather than assumed. This profile (folds at
the exact double nearly evaporated; a window pair recovered at
the freely-refined double; no wave) is sweep 4's TIC 277106730
restated — BLS depth 0.100%, folds at 17% of it, pair
0.102%/0.042%, delta 0.8σ — which the accepted sweep-4 record
convicted as an in-aperture binary. The present pair is stronger
in absolute terms. The conviction is graded the weakest tier of
the patch (no wave, no alternation substance), and the
alternative — that the (c) refinement is fitting noise maxima —
is recorded; on the project's own rules and precedent, the pair
at a coherent refined period is evidence, and it points one way.

---

## Target 5 of 20 — TIC 349477874 — **LIKELY BINARY** (fold completion)

Sweep hit: **P = 12.7610 d, SDE = 8.7 — the patch's weakest
hit**, no flag; stamp **"4/17 — fails persistence —
blend-suspect."** Star: Tmag 14.88, R 0.448 R_sun, 0.444 M_sun,
Teff 3522 K, 209 pc; 0.35° from centre. Contratio **0.075**.

- **(f)** Zooniverse **False**; TOI **0 rows**.
- **(a) Reproduce: exact.** P = 12.7610, SDE 8.70, depth 0.838%,
  duration 3.96 h, 20 sectors.
- **(b) Odd/even: alternating** — 0.090% / 0.047% (deepest fold
  11% of BLS depth).
- **(c) Double-period:** refined 2P = **26.2806 d**; windows
  **0.790% / 0.272%** — the primary window is ~94% of the full
  BLS depth: a real, deep, unequal eclipse pair at 26.28 d.
  Quadrature delta −0.128% at −4.9σ (shoulders bright — uneven
  out-of-eclipse light, common on active stars; it does not
  acquit an eclipse pair).

**Verdict: LIKELY BINARY**, true period ≈ 26.28 d. The weakest
BLS hit of the patch hid one of its deepest eclipse pairs —
the alias corollary again.

---

## Target 16 of 20 — TIC 349478154 — **BLEND-SUSPECT** (fold completion)

Sweep hit: **P = 13.1335 d, SDE = 10.7**, high-contamination
flag; stamp **"4/17 — fails persistence — blend-suspect."**
Star: Tmag 14.82, R 0.365 R_sun, 0.351 M_sun, Teff 3366 K,
149 pc; 0.56° from centre. Contratio **2.524** — the patch's
most contaminated aperture by a factor of 2.5 over the runner-up.

- **(f)** Zooniverse **False**; TOI **0 rows**.
- **(a) Reproduce: exact.** P = 13.1335, SDE 10.65, depth 1.057%,
  duration 3.53 h, 20 sectors.
- **(b) Odd/even: machine kill on a 0.031% / 0.045% ratio**
  (deepest fold 4% of BLS depth) — the fragile class, recorded.
- **(c) Double-period: a real pair the gauntlet cannot judge.**
  Refined 2P = **25.7448 d**; windows **0.903% / 0.831%** — deep
  and near-equal; delta **−0.092% at −3.0σ** (no wave). A
  near-equal pair with no ellipsoidal support is the
  equal-twin blind spot (TIC 308851365's morphology): it is
  exactly as consistent with a 12.87 d planet folded at its
  double as with twin stars, and only the wave — absent here —
  has ever broken that tie in this project.

**Verdict: BLEND-SUSPECT** — reclassified from the driver's
LIKELY BINARY (raw verdict preserved in the JSON). The swept
13.1335 d ephemeris evaporates in folds (4% of BLS depth) and
failed persistence in-sweep; the one coherent structure lives
at 25.74 d inside an aperture whose contaminating flux is 2.5×
the target's. Whatever the pair is, it most plausibly belongs
to the contaminating flux, and the swept hit is not a
target-star planet. The in-sweep stamp's species is upheld.

---

## Appendix A — Target 11 (TIC 349272923): the failure, diagnosed

Target 11 failed in-sweep at the stitch step, after all 19
sectors downloaded, with:
`'%' (dimensionless) and 'electron / s' are not convertible`.
The failure was **reproduced locally, end to end**, with the
identical exception, and the chain is fully identified
(`sweep5_logs/diag_349272923.json` holds the product inventory
and the captured traceback). Star: Tmag 14.44, R 0.381 R_sun,
0.392 M_sun, 259 pc; RA 109.31924°, Dec −62.69357°.

**What the star's products are.** TIC 349272923 has **no SPOC,
TESS-SPOC or QLP products at all**. The pipeline's authors-filtered
search returns 0, so its documented fallback (unfiltered search)
fired — in Dev's Codespace and here alike — and returned 19
community products: **11 × GSFC-ELEANOR-LITE** (sectors 1, 3–11,
13; FFI, 1800 s) and **8 × TASOC** (sectors 3–6, cbv and ens
variants). This is the first target in five sweeps whose coverage
exists only outside the pipeline's author families.

**Where it blows up.** `hunter._run_pipeline` (and identically
`_fetch_stitched`) does
`lc_collection.stitch(corrector_func=lambda x: x.normalize())`.
lightkurve's stitch normalizes each curve, then calls
`astropy.table.vstack(join_type="inner")` over the columns the
products *share*. `normalize()` fixes the headline flux clash
(eleanor flux arrives in **electron / s**, TASOC flux in
**ppm** — dimensionless after division either way), but it never
touches the auxiliary **`flux_bkg`** column — and there the two
families disagree irreconcilably: **eleanor-lite writes
`flux_bkg` in `%`, TASOC writes it in `electron / s`**. vstack's
column unification hits that pair and raises the exact
UnitConversionError from the sweep log. The pipeline never reads
`flux_bkg` anywhere; the column kills the run purely by existing
in both flavours. The no-corrector control stitch fails one step
earlier on the raw flux units (`electron / s` vs `ppm`), which
confirms the crash sits in vstack's unit unification, not in any
pipeline arithmetic.

**Root cause, one line:** the unfiltered-fallback path admits
mixed-author HLSP products whose never-used `flux_bkg` column
carries incommensurable units (% vs electron/s) across families,
and `LightCurveCollection.stitch`'s inner vstack cannot unify
them — any star covered only by an eleanor-lite + TASOC mix will
fail identically, on any machine.

**Smallest fix shape (for a later build brief; not applied
here):** make the stitch corrector column-lean at both call
sites — e.g. `corrector_func=lambda x: x.normalize()
.select_columns(["time", "flux", "flux_err", "quality"])` — so
auxiliary columns never reach vstack. That is behaviour-
preserving for every star the pipeline currently handles (only
flux/time/quality are consumed downstream) and removes the whole
class, not just this instance. One follow-on hazard to note in
the same brief: TASOC curves are zero-centred (median ≈ 0), so
even past the stitch, `normalize()` divides them by ~0 — a
robust fix should also treat near-zero-median products
explicitly rather than letting them through silently.

No manual-workaround analysis of this star was attempted, per
the brief; it remains an un-analyzed target until the fix lands.

---

## Sweep 5 — FINAL tally

- **Targets in patch: 20.** Analyzed: 19. **Failed before
  analysis: 1** (TIC 349272923, Appendix A).
- **Hits (SDE ≥ 8.5): 16 of 19 analyzed (84%).**
- **Survivors: 0.**
- **Convicted: 15** — **11 eclipsing binaries** (TIC 349519662,
  349193983, 349370722, 349370477, 349408892, 349477874,
  349370417, 349370907, 349273239, 349309664, 349193749) and
  **4 blend-suspects** (TIC 349309779, 349268662, 349268505,
  349478154). Phantoms: 0.
- **Inconclusive: 1** — TIC 349481800 (evolving-starspot
  profile; driver's mechanical EB label reclassified, see its
  section).

**Combined five-sweep ledger: 53 hits, 0 survivors, 43 convicted
(26 EB, 9 blends, 8 phantoms), 5 inconclusive** — updating sweeps
1–4's 37 hits / 28 convicted (15 EB, 5 blends, 8 phantoms) / 4
inconclusive; the 3 un-vetted sweep-1 hits and the earliest
reports' two-star class ambiguity (footnoted in the sweep-4
report) carry forward unchanged. Five patches, 100 targets,
53 hits — and the count of photometric candidates still standing
is **zero**. The (RA 95, Dec −64) pointing is next in the queue.

**Stamp audit for sweep 5.** The in-sweep stamp's bottom line —
"not a planet at the swept ephemeris" — is upheld **16/16**;
"not a planet" now stands **33/33** across sweeps 3–5's fully
vetted hits (the sweep-2 six were hand-vetted before stamps
existed). Species resolution this patch: the eleven
fails-persistence stamps resolved to **9 eclipsing binaries,
2 blend-suspects** (TIC 349268505 and 349478154 — the stamp's
own species, exact on those two; refined to EB on the other
nine, per the calibrated expectation that the stamp convicts
without naming). The five patchy stamps resolved to 2 EB,
2 blend-suspects, 1 inconclusive. The standalone persistence
module re-derived the in-sweep stamp **digit for digit on all
six stars where both numbers exist** (sector counts and
weighted means: 9/17 +0.527%, 9/19 +0.345%, 5/16 −0.178%,
6/17 +0.015%, 6/15 +0.053%, 4/16). Three corollaries join the
standing two (stamp grades the alias; stamps can carry
monster-sector raw folds, reconfirmed at +22.1% for
TIC 349309779):

1. **Stage (b)'s ratio rule is now the machine labels' dominant
   failure mode**: it fired "likely-EB" on fold pairs whose
   deepest member is ≤ 16% of the BLS depth in **4 of 16** cases
   this sweep (349481800 — overturned; 349408892, 349370907,
   349478154 — gated there, with (c) sustaining only two of
   them). A (b) label on folds under ~20% of BLS depth should be
   treated as uninformative until stage (c) speaks.
2. **Stage (c)'s free period refinement did the convicting all
   patch**: the refined doubles sit 0.4–3% off the exact 2P in
   eight of the eleven EB convictions (29.002 vs 29.585;
   25.178 vs 25.875; 27.119 vs 26.409). BLS periods on diluted,
   variable stars are simply too imprecise for exact-double
   folds; the refinement is load-bearing and any future
   automation must keep it.
3. **The monster-era dip population is patch-independent**: the
   sectors ≥ 60 excursions (esp. 94–97) supplied the trio's
   entire signal and appear among the raw monsters of 9 of the
   16 hits. At fixed ephemeris they are indistinguishable from
   dips; only per-sector accounting separates them, every time.

**Session notes.** All 16 gauntlets plus the diagnosis ran
locally on 2026-11-04, sequentially (RAM discipline as in sweep
4); total driver wall time ≈ 56 min including two multi-minute
MAST download stalls (TIC 349370907 ~6.5 min, TIC 349193749
~5 min — both healed without intervention) and one degraded-MAST
window in which the TOI TAP check errored on 10 stars (all
retried clean: 0 rows) and the TIC 349272923 authors-filtered
search returned 0 on eight consecutive attempts while the
unfiltered search returned its 19 (consistent with the Codespace
sweep having taken the same fallback path). Verification files:
one JSON per hit in `vetting_results/` (plus the fold-shape
exhibit for TIC 349481800), `sweep5_logs/catalog_rows.json`,
`sweep5_logs/trio_analysis.json`, `sweep5_logs/diag_349272923.json`.
DB and discoveries.csv ended the session byte-identical to
their pre-session md5s (`33b70438…`, `2c8abaae…`).
