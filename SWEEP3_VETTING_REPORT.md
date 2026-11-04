# Sweep 3 — Vetting Report

Patch centre: **RA 105.0, Dec −71.0 (PRESUMED)**, cone 1.0° — the overnight sweep
launched 2026-11-04 ~06:05 IST on the new code (in-sweep persistence + raw-fold
exhibit). Sweep settings as before: Tmag 11.5–15, R 0.2–0.5 R_sun, sector cap 20,
Max Stars 20. This report opens with the sweep's first hit, vetted urgently the
same morning. Method: the `vet_star2.py` stage-gated gauntlet (reproduce →
odd/even → double-period → orbit-phase → persistence), plus TIC contamination,
Zooniverse known-check, and a NASA Exoplanet Archive TOI TAP check.

---

## Target 1 of 20 — TIC 177172764 — **INCONCLUSIVE**

Sweep hit: **P = 19.8937 d, SDE = 10.3** at cap 20 (24 sectors available).
Star: Tmag 14.36, TIC radius 0.486 R_sun, 0.484 M_sun, Teff 3597 K (M dwarf).
Position RA 104.81248°, Dec −70.90007° — 0.12° from the presumed patch centre,
consistent with the (105, −71) pointing. IDs: 2MASS 06591499-7054003,
Gaia DR3 5267326215116754176.

In-sweep persistence stamp (new code, from the user's own run):
**"10/19 sectors, mean depth 0.52% — patchy."**

### Stage by stage

- **(f) Known checks:** Zooniverse Talk **False**. NASA Archive TOI table
  (TAP, tid=177172764): **0 rows**. Nobody has claimed this star.
- **(a) Reproduce: exact.** P = 19.89369 d (rel. diff 5×10⁻⁷), SDE 10.29,
  depth 0.661%, nominal Rp 4.35 R_earth, duration 1.94 h, 20 sectors,
  178,925 points. The BLS signal is really in the pipeline's stitched curve.
- **(b) Odd/even: total evaporation on paper — with an estimator caveat.**
  Folded at 39.78738 d: odd **0.000%**, even **0.000%** → driver verdict
  "inconclusive," and the stage gate killed it here as PIPELINE PHANTOM
  (deepest fold dip = 0% of the BLS depth). **Caveat recorded:** the event
  duration is only 1.94 h while the odd/even median window is ±0.80 d —
  a ~20× dilution. A median over that window sits on baseline even when
  short dips exist, so this test is at its weakest for exactly this
  period/duration shape. This is the signature the sweep-1 batch recorded
  as the "BLS-only" class (TIC 41083982, TIC 150066703 — folds ~0.00%
  despite SDE ≥ 10), ruled INCONCLUSIVE there.
- **(c)/(d) Not run** — stage gate stopped at (b), per protocol.
- **(e) Persistence, re-derived independently (post-gate diagnostic):**
  **reproduces the in-sweep stamp digit for digit** — 19 usable sectors,
  **10/19 ≥ 1.5σ**, weighted-mean depth **+0.522% ± 0.064%**, module verdict
  MIXED (= the sweep's "patchy"). The new in-sweep stage is validated
  against the standalone module on live data. **But:** χ² = 144.8 on
  18 dof, **p ≈ 7.7×10⁻²²** — the per-sector depths are grossly
  inconsistent with a constant-depth transit train. No monster sectors.
- **Contamination: 0.016** (TIC contratio) — among the cleanest apertures
  of any hit in any sweep; the blend route is implausible.

### Why INCONCLUSIVE, not PHANTOM

The driver's mechanical label (preserved in the JSON as
`driver_verdict_raw`) is PIPELINE PHANTOM, and that is the correct call
for a pure fold-evaporation with nothing underneath. Here there *is*
something underneath, measured twice with identical results: a per-sector
in-window excess averaging **+0.52% at 8.1σ from zero**. Every convicted
phantom and mirage across both earlier sweeps averaged **+0.03…+0.07%** —
zero. This star does not average to zero. What it also is not: a planet —
a real transit train holds a constant depth across sectors (χ² forbids
it here) and shows in the fold. The pattern — recurring shallow in-window
dips at roughly the BLS period, depth varying wildly sector to sector,
on a cool M dwarf — is most consistent with **stellar variability
(evolving spots) near a ~19.9 d rotation period** that BLS locked onto:
an astrophysical false positive, not a pipeline invention and not a
planet.

**Verdict: INCONCLUSIVE** (not a candidate; not cleared as pure noise).
Tiebreaker for a later pass, if wanted: a rotation/variability check on
the raw curve (periodogram + spot-evolution look) and a fold at the
analyze epoch with a duration-matched window rather than the ±0.8 d
median window, optionally uncapped over all 24 sectors.

Raw record: `vetting_results/177172764.json`; run logs in `sweep3_logs/`.

---

## Target 3 of 20 — TIC 177163233 — **INCONCLUSIVE**

Sweep hit: **P = 12.4523 d, SDE = 8.8** at cap 20 (84 sectors available —
the deepest data stack of any hit so far). Star: Tmag 13.05, TIC radius
0.332 R_sun, 0.313 M_sun, Teff 3453 K (M dwarf), 60.8 pc. Position
RA 104.46747°, Dec −70.95906° — 0.18° from the presumed patch centre,
consistent with the (105, −71) pointing. IDs: 2MASS 06575217-7057324,
Gaia DR3 5267331540876168192.

In-sweep persistence stamp (new code, from the user's own run):
**"12/18 sectors, mean depth 0.12% — patchy."**

### Stage by stage

- **(f) Known checks:** Zooniverse Talk **False**. NASA Archive TOI table
  (TAP, tid=177163233): **0 rows**. Nobody has claimed this star.
- **(a) Reproduce: exact.** P = 12.45230 d (rel. diff 3.8×10⁻⁷),
  SDE 8.85, depth 0.138%, nominal Rp 1.34 R_earth, duration **0.72 h**,
  20 sectors, 175,945 points.
- **(b) Odd/even: total evaporation — with the strongest estimator
  caveat yet.** Folded at the refined period: odd **0.000%**, even
  **0.000%** → the driver's stage gate killed it here as PIPELINE
  PHANTOM (raw verdict preserved in the JSON as `driver_verdict_raw`).
  **Caveat:** the event lasts 0.72 h while the odd/even median window is
  ±0.50 d — in-transit points are ~3% of the window, so the median sits
  on baseline even if real 0.72 h dips exist. For this period/duration
  shape the test cannot see the signal either way (the same blindness
  recorded for TIC 177172764 and the sweep-1 BLS-only class).
- **(c) Double-period (post-gate diagnostic): clean.**
  **no-ellipsoidal-signal** — quadrature delta **+0.009% ± 0.004%**
  (2.5σ, far under the +0.2% / ≥5σ twin-star line); the 2P eclipse
  windows hold 0.011% / 0.000% — no eclipse pair, no ellipsoidal wave.
  A binary at 24.9 d is not supported.
- **(d) Orbit-phase (post-gate diagnostic): no pile-up.** P/TESS-orbit
  ratio 0.909 — not near a resonance. 20 on-data centres, boundary
  fraction 0.35 vs 0.219 by chance, circular R = 0.195: the pre-set
  pile-up rule (fraction ≥ 0.5 AND R ≥ 0.4) is not met.
- **(e) Persistence at cap 20, re-derived independently: matches the
  in-sweep stamp digit for digit** — 18 usable sectors, **12/18 ≥ 1.5σ**,
  weighted-mean depth **+0.122% ± 0.017%** — 7.2σ from zero and 89% of
  the BLS depth. Module verdict MIXED ("patchy"). 35 fully-covered
  events, median event depth +0.119%, 71% of events positive. No
  monster sectors. (χ² = 53.1 on 17 dof, p ≈ 1.4×10⁻⁵ — some
  sector-to-sector depth scatter in this accounting.) The in-sweep
  stage is validated against the standalone module on live data for
  the second star running.
- **Contamination: 0.019** (TIC contratio) — a very clean aperture;
  the blend route is implausible.

### The uncapped tiebreaker (all 84 sectors)

The signal is shallow, so the full baseline was used as the arbiter —
an uncapped BLS analyze plus persistence folded at the **fixed**
cap-20 ephemeris over every sector:

- **Uncapped analyze (84 sectors, 557,582 points): the top BLS peak
  moved** — to P = 14.4517 d, SDE 9.54, depth 0.094%. With the full
  baseline the 12.4523 d peak is no longer the periodogram winner.
- **Uncapped persistence at the fixed ephemeris: CONCENTRATED** —
  80 usable sector-ranges, 154 fully-covered events, only
  **13/80 ≥ 1.5σ (16%)**; weighted-mean depth diluted to
  **+0.075% ± 0.012%**; median event depth collapses from +0.119%
  (cap 20) to **+0.040%**.
- **Era split** (this is the decisive table):

  | Data | Ranges ≥1.5σ | Weighted-mean depth |
  |---|---|---|
  | Year-1 sectors (the swept subset) | 8/20 | **+0.137% ± 0.019% (7.2σ)** |
  | Sectors 27–39 (cycle 3) | 0/26 | −0.030% ± 0.025% (−1.2σ) |
  | Sectors ≥ 60 (later cycles) | 2/25 | +0.000% ± 0.031% (0.0σ) |

  Within the year-1 subset the depths are consistent with a constant
  +0.137% (χ² p = 0.85 in the uncapped accounting). Outside year 1
  there is, to measurement precision, **nothing at all**.

### Why INCONCLUSIVE, not PHANTOM — and not a candidate

The driver's mechanical label (preserved in the JSON) is PIPELINE
PHANTOM, and it would be right for a signal that collapses under
per-sector means. This one does not collapse at sweep depth: at the
fixed ephemeris the year-1 sectors carry a constant **+0.13–0.14%**
dip at 7σ, measured identically by the in-sweep stage and the
standalone module. Flattening phantoms in this project's record
average to ~zero under exactly this test. So the dips are genuinely
in the year-1 data. But a transiting planet cannot switch off:
the same ephemeris measures **0.0σ in sectors ≥ 60** and −1.2σ in
cycle 3. A blend cannot explain it either (contamination 0.019, no
monster sectors — and a blended eclipsing binary would keep
eclipsing in later cycles). The consistent reading is
**era-confined stellar variability**: a long-lived spot pattern in
the year-1 cycles recurring near 12.45 d, sharpened by BLS into a
transit-like train, decayed before cycle 3 — the shallow sibling of
TIC 177172764's case (whose excess spans its whole baseline with
wildly variable depth; this one's is depth-constant but confined to
one era). Different sub-flavours of the same grey drawer: something
real in the data, demonstrably not a planet, not convictable as a
pipeline invention.

**Verdict: INCONCLUSIVE** (not a candidate; the uncapped check
closes the planet reading — no further follow-up is owed unless a
future era re-lights the signal).

Raw record: `vetting_results/177163233.json`; full persistence tables
at `vetting_results/177163233_persistence_cap20.json` and
`vetting_results/177163233_persistence_uncapped.json`; run logs in
`sweep3_logs/`.

---

## Target 18 of 20 — TIC 177171983 — **LIKELY BINARY**

Sweep hit: **P = 13.7632 d, SDE = 12.2** at cap 20 (23 sectors
available) — the strongest unvetted hit of the sweep, and the one whose
period sits almost exactly on the 13.7 d TESS orbit. Star: Tmag 14.91,
TIC radius 0.499 R_sun, 0.497 M_sun, Teff 3614 K (M dwarf), 257 pc.
Position RA 104.85908°, Dec −70.27732° — 0.72° from the presumed patch
centre, inside the 1.0° cone toward its northern edge. IDs: 2MASS
06592619-7016382, Gaia DR3 5268119100439111296.

In-sweep persistence stamp (new code, from the user's own run):
**"9/17 sectors, mean depth 0.48% — patchy."**

### Stage by stage

- **(f) Known checks:** Zooniverse Talk **False**. NASA Archive TOI
  table (TAP, tid=177171983): **0 rows**. Nobody has claimed this star.
- **(a) Reproduce: exact.** P = 13.76318 d (rel. diff 1.7×10⁻⁶),
  SDE 12.19, depth 1.071%, nominal Rp 5.64 R_earth, duration 2.38 h,
  20 sectors, 186,324 points.
- **(b) Odd/even: present/absent alternation → driver kill,
  LIKELY BINARY.** Folded at 27.526 d: odd **0.077%**, even
  **−0.002%** ("103% apart") — one eclipse train present, the other
  absent: the classic single-eclipse signature of an EB at twice the
  sweep period (cf. TIC 294782870 in sweep 2). Scale caveat recorded:
  the fold depths are ~7% of the BLS depth — the 2.38 h event sits in
  a ±0.55 d median window (~9% of points in transit), so the median
  estimator dilutes heavily; here the *pattern*, backed by stage (c),
  is what convicts.
- **(c) Double-period (post-gate, CONFIRMS the kill): likely-binary.**
  The focused scan refines the doubled period to **27.0519 d**, where
  the two eclipse windows measure **0.853% and 0.567%** — real,
  unequal eclipses — and the quadrature (ellipsoidal) delta is
  **+0.228% at 11.6σ**, over the pre-set likely-binary line
  (+0.2% at ≥5σ). A tidally distorted eclipsing binary; the sweep's
  13.7632 d is its half-period alias.
- **(d) Orbit-phase (post-gate, given full weight per brief):
  PILE-UP — the first of the project.** P/TESS-orbit ratio **1.0046**,
  the near-1:1 phase-lock configuration. 37 on-data transit centres:
  boundary fraction **0.568** vs 0.219 expected by chance, circular
  R = **0.471** — the pre-set pile-up rule (fraction ≥ 0.5 AND
  R ≥ 0.4) fires. Every previous hit in three sweeps was acquitted by
  this stage (fractions 0.14–0.35); this one is not. Reading: at this
  commensurability the eclipse train stays clustered against orbit
  boundaries, and a scattered-light contribution to the alias's depth
  cannot be excluded — but the conviction does not rest on it: the
  ellipsoidal wave at (c) is the target's own physics and no
  instrument effect manufactures one.
- **(e) Persistence at cap 20, re-derived independently: matches the
  in-sweep stamp digit for digit** — 17 usable sectors, **9/17
  ≥ 1.5σ**, weighted-mean depth **+0.480% ± 0.079%**, module verdict
  MIXED ("patchy"); 32 fully-covered events, median event depth
  +0.465%. (χ² = 34.5 on 16 dof, p ≈ 0.0047 — depth scatter beyond
  formal errors, but an EB's eclipses *do* recur sector to sector;
  persistence was never going to acquit this star. The in-sweep stage
  is validated against the standalone module on a third live star.)
  Cap-20 raw monster sectors: 68 (+8.1% raw) and 94 (+6.7%).
- **Contamination: 0.029** (TIC contratio) — a clean aperture; the
  blend route is implausible, and an ellipsoidal wave is on-target
  physics by construction.

### The uncapped tiebreaker (all 23 sectors)

- **Uncapped analyze: the signal is demoted.** Over all 23 sectors
  (sectors 35–39 and 61–98 — this star has *no* year-1 sectors), the
  top BLS peak moves to P = 13.9371 d at **SDE 8.01 — below the 8.5
  discovery bar**. The 13.7632 d peak does not survive the full
  baseline as the periodogram winner.
- **Uncapped persistence at the fixed cap-20 ephemeris:
  CONCENTRATED** — 22 usable ranges, only **4/22 ≥ 1.5σ**,
  weighted-mean depth diluted to **+0.273% ± 0.082%**. Raw monster
  sectors in the uncapped accounting: 37 (+5.3%), 68 (+11.7%),
  94 (+10.3%) and **98 (+38.7% raw; +24.6% flattened in-window)** —
  the 94–98 monster-era family of both earlier patches, present here
  too.
- **Era split** (the star's eras are cycle-3 and later; there is no
  year-1 data to split):

  | Data | Ranges ≥1.5σ | Weighted-mean depth |
  |---|---|---|
  | Sectors 27–39 (4 ranges: 35, 36, 37, 39) | 0/4 | +0.120% ± 0.371% (0.3σ) |
  | Sectors ≥ 60 (18 ranges) | 4/18 | **+0.281% ± 0.084% (3.4σ)** |
  | Swept subset (first 20 ranges, uncapped accounting) | 4/20 | +0.274% ± 0.082% (3.4σ) |

  The folded excess lives in the later cycles — the same cycles that
  carry the 94–98 monsters — and is absent from the cycle-3 ranges:
  the inverse of TIC 177163233's era pattern.
- **Methodological caution (recorded plainly):** per-sector flattened
  depths differ materially between the cap-20 and uncapped pipeline
  stitches for this star (sector 93: +2.41% at 3.7σ in the cap-20
  accounting vs −0.53% uncapped; sector 89: +0.54% at 3.9σ vs +0.14%
  at 0.9σ). The uncapped run's first-20 subset therefore does **not**
  reproduce the cap-20 persistence table (9/17) the way it did for
  TIC 177163233 — cross-stitch subset comparisons are soft evidence
  here. The verdict below does not use them.

### Why LIKELY BINARY, not another INCONCLUSIVE

The two earlier "patchy" hits of this patch were rescued from their
gate kills because nothing in their data required a binary: flat
double-period, clean apertures, per-sector excesses with no fold
signature — spots were the consistent reading. This star is the
opposite case. The driver's stage-(b) kill is **upheld and
independently confirmed** at (c): two unequal eclipse windows
(0.853% / 0.567%) at a refined 27.0519 d with a +0.228% ellipsoidal
wave at 11.6σ. Starspots do not raise a tidal-distortion wave
phase-locked at exactly twice the sweep period; a blended neighbour
is excluded by the clean aperture (0.029) and could not produce an
on-target ellipsoidal signal anyway. The orbit-phase pile-up — the
project's first — and the uncapped demotion (SDE 8.01, peak moved)
compound the picture of a resonance-flattered alias, but they are
documentation, not the conviction.

**Verdict: LIKELY BINARY** — eclipsing binary, true period
≈ 27.05 d; the sweep's 13.7632 d is the half-period alias, sitting
on the ~1:1 TESS-orbit resonance (ratio 1.0046). VSX-reportable in
principle, like the sweep-2 binaries, if the user ever wants the
filing.

Raw record: `vetting_results/177171983.json`; persistence tables at
`vetting_results/177171983_persistence_cap20.json` and
`vetting_results/177171983_persistence_uncapped.json`; run logs in
`sweep3_logs/`.

---

## Target 7 of 20 — TIC 177239316 — **LIKELY BINARY**

Sweep hit: **P = 12.9644 d, SDE = 11.8** at cap 20 (23 sectors
available). The HIT line carried the new code's
**high-contamination — blend risk** flag, and the in-sweep stamp read:
**"5/18 sectors — fails persistence — blend-suspect."** This section
is the fold completion for that self-conviction. Star: Tmag 14.98,
TIC radius 0.418 R_sun, 0.412 M_sun, Teff 3579 K, 213 pc. Position
RA 105.48404°, Dec −70.64154° — 0.39° from the presumed patch centre.
IDs: 2MASS 07015615-7038295, Gaia DR3 5267365625736548096.

- **(f) Known checks:** Zooniverse Talk **False**. NASA Archive TOI
  table (TAP, tid=177239316): **0 rows**.
- **(a) Reproduce: exact.** P = 12.9644 d, SDE 11.84, depth 1.147%,
  nominal Rp 4.91 R_earth, duration 5.98 h, 20 sectors, 183,455
  points.
- **(b) Odd/even: alternating eclipse depths → driver kill,
  LIKELY BINARY.** Folded at 25.93 d: odd **0.288%**, even **0.143%**
  — both parities carry real eclipses, 50% apart (ratio 0.50). This
  is the substantive alternation pattern, not a ratio-rule misfire.
- **(c) Double-period (post-gate):** refined 2P = **25.9239 d**;
  eclipse windows **0.411% / 0.274%** (unequal, ratio 0.67);
  quadrature delta −0.092% at −3.7σ → **no ellipsoidal signal** (an
  EB without a measurable tidal wave — ordinary).
- **Contamination: 0.301** (TIC contratio) — flagged, as the sweep's
  own HIT line said. The binary sits in a crowded aperture; the fold
  checks cannot separate a target EB from a neighbour EB at this
  contamination (that is centroid work), and it does not matter for
  the verdict: the planet reading is dead either way.

**Reconciliation with the in-sweep stamp: the folds AGREE with and
REFINE it.** The stamp's failure verdict ("not a constant-depth
planet train at the alias ephemeris") stands; the folds identify
the object the stamp could only suspect — an eclipsing binary.
Verdict class follows the batch precedent for this fold signature
(cf. TIC 294671352, contratio 0.272, LIKELY BINARY).

**Verdict: LIKELY BINARY** — eclipsing binary in the aperture, true
period ≈ 25.92 d; the sweep's 12.9644 d is the half-period alias.

Raw record: `vetting_results/177239316.json`; run log in
`sweep3_logs/`.

---

## Target 13 of 20 — TIC 177239184 — **LIKELY BINARY**

Sweep hit: **P = 13.1433 d, SDE = 10.6** at cap 20 (22 sectors
available). In-sweep stamp: **"3/17 sectors — fails persistence —
blend-suspect"** (no contamination flag on this HIT line). Star:
Tmag 14.90, TIC radius 0.314 R_sun, 0.293 M_sun, Teff 3392 K,
130 pc. Position RA 105.48533°, Dec −70.42916° — 0.59° from the
presumed patch centre. IDs: 2MASS 07015648-7025450, Gaia DR3
5268121780498760704.

- **(f) Known checks:** Zooniverse Talk **False**. NASA Archive TOI
  table (TAP, tid=177239184): **0 rows**.
- **(a) Reproduce: exact.** P = 13.1433 d, SDE 10.63, depth 2.779%,
  nominal Rp 5.64 R_earth, duration 5.98 h, 20 sectors, 185,941
  points.
- **(b) Odd/even: alternating eclipse depths → driver kill,
  LIKELY BINARY.** Folded at 26.29 d: odd **0.399%**, even **0.274%**
  — both parities real, 31% apart.
- **(c) Double-period (post-gate): likely-binary, emphatic.**
  Refined 2P = **25.9413 d**; eclipse windows **2.155% / 1.363%**
  (deep, unequal); ellipsoidal delta **+0.592% at 12.5σ** — a strong
  tidal-distortion wave, the clearest twin-star signature of this
  sweep.
- **Contamination: 0.026** (TIC contratio) — a clean aperture. The
  binary is the target star itself; the blend route was never
  plausible here, and an ellipsoidal wave is on-target physics.

**Reconciliation with the in-sweep stamp: the folds AGREE with its
suspicion and IDENTIFY the object.** The stamp's generic
"blend-suspect" is the persistence module's label for any
non-constant-depth alias signal; it is refined, not substantively
overturned — persistence failed this star because an alias-folded
EB is not a constant-depth planet train, which is exactly what the
stamp exists to say. The species is supplied by the folds.

**Verdict: LIKELY BINARY** — on-target twin-star eclipsing binary,
true period ≈ 25.94 d; the sweep's 13.1433 d is the half-period
alias. The most clear-cut binary of the sweep.

Raw record: `vetting_results/177239184.json`; run log in
`sweep3_logs/`.

---

## Target 15 of 20 — TIC 299900306 — **PIPELINE PHANTOM**

Sweep hit: **P = 11.3423 d, SDE = 10.7** at cap 20 (42 sectors
available). The HIT line carried the **high-contamination — blend
risk** flag, and the in-sweep stamp read: **"5/20 sectors — fails
persistence — blend-suspect."** Star: Tmag 12.89, TIC radius
0.474 R_sun, 0.75 M_sun, Teff 4709 K (late-K dwarf — the warmest
target of the sweep), 161 pc. Position RA 106.05448°,
Dec −70.42164° — 0.68° from the presumed patch centre. IDs: 2MASS
07041309-7025178, Gaia DR3 5267377647349000960.

- **(f) Known checks:** Zooniverse Talk **False**. NASA Archive TOI
  table (TAP, tid=299900306): **0 rows**.
- **(a) Reproduce: exact.** P = 11.3423 d, SDE 10.74, depth 0.120%,
  nominal Rp 1.78 R_earth, duration 5.18 h, 20 sectors — but only
  **42,957 points** (FFI-cadence products; the sparsest data of any
  hit this sweep).
- **(b) Odd/even: a mechanical mislabel — folds evaporate.** The
  app's ratio rule returned "likely-eclipsing-binary" on odd
  **+0.004%** vs even **−0.003%**: "159% apart" of two zeros. There
  is no eclipse at either parity; the deepest fold dip is 3.3% of
  the BLS depth, far under the 25% evaporation line. Per the batch
  definition (identical pattern: TIC 294671640 in sweep 2) this is
  a phantom; the raw app verdict is preserved in the JSON as
  `driver_verdict_raw`.
- **(c) Double-period (post-gate): nothing.** Refined 22.266 d:
  eclipse windows 0.048% / −0.008% (no pair), quadrature delta
  +0.009% at 1.6σ → **no ellipsoidal signal**. No binary at 2P
  either.
- **Contamination: 0.574** (TIC contratio) — the dirtiest aperture
  of the sweep, as the HIT line's flag said. But there is no
  eclipse signal anywhere in the aperture, blended or on-target,
  for the contamination to explain: a neighbour EB diluted into
  this aperture would still fold into an eclipse pair, and none
  exists.

**Reconciliation with the in-sweep stamp: the folds OVERTURN its
blend reading.** The stamp convicted on persistence (5/20) plus
the contamination flag; the fold completion shows the conviction's
mechanism was wrong — not a neighbour's eclipses leaking in, but a
BLS-only signal on sparse FFI data that evaporates in every fold.
The stamp's bottom line (not a planet) stands; its species label
does not.

**Verdict: PIPELINE PHANTOM** — the third mechanical-mislabel case
in the project's record, and the first the in-sweep code (rather
than the hand gauntlet) initially stamped with the wrong species.

Raw record: `vetting_results/299900306.json`; run log in
`sweep3_logs/`.

---

## Sweep 3 — FINAL tally (sweep complete, 2026-11-04)

**20 targets, 6 hits at SDE ≥ 8.5, all 6 hand-vetted: 0 survivors.**

- **3 eclipsing binaries:** TIC 177171983 (true P ≈ 27.05 d,
  ellipsoidal +0.228% @ 11.6σ, plus the project's first orbit-phase
  pile-up at the ~1:1 resonance), TIC 177239316 (≈ 25.92 d, in a
  0.301-contaminated aperture), TIC 177239184 (≈ 25.94 d, on-target,
  ellipsoidal +0.592% @ 12.5σ). Note the family resemblance: two of
  the three are ~25.9 d binaries — the ~26 d EB pile-up in these
  CVZ patches is what keeps manufacturing the ~13 d alias cluster,
  in sweep 3 as in sweep 2.
- **1 pipeline phantom:** TIC 299900306 (fold evaporation on sparse
  FFI data; the app's ratio rule mislabelled it EB on two zeros).
- **2 inconclusive — the grey drawer:** TIC 177172764 and
  TIC 177163233, both real per-sector excesses on M dwarfs that no
  fold can see and no planet can explain (wildly variable depth;
  era-confined) — most consistent with evolving / long-lived
  starspot patterns. Neither is a candidate; neither is convictable
  as a pipeline invention.

**Audit of the self-vetting code** (this was the first sweep run on
it, unsupervised): its in-sweep stamps' bottom line — *not a
planet* — was upheld by hand vetting on **all 6 hits**. Species
labels were refined in 3 of 6 cases (two "blend-suspects" were
identified EBs; one was a phantom), both "patchy" stamps with real
excesses resolved as the two grey cases, and the third patchy stamp
(177171983) proved to be a binary the folds convicted. The
in-sweep persistence numbers were re-derived by the standalone
module **digit for digit on all three patchy stars** — the stamp
is now a validated instrument, with the fold checks remaining the
species court.

**Combined three-sweep ledger.** Sweeps 1–2 closed (per
SWEEP2_VETTING_REPORT.md) at **0 survivors / 15 convicted false
alarms** (6 eclipsing binaries, 4 blend-suspects, 5 pipeline
phantoms). Sweep 3 adds 4 convicted false alarms (3 EB, 1 phantom)
and 2 inconclusives: **combined — 0 survivors / 19 convicted false
alarms (9 eclipsing binaries, 4 blend-suspects, 6 pipeline
phantoms), plus 2 inconclusive astrophysical cases**, out of
26 hits across three patches (23 hand-vetted; the 3 weakest
sweep-1 hits were never vetted).

Sweep 3's patch (RA 105, Dec −71, presumed) was, like sweep 2's, an
observed-but-unexamined layer — none of its 6 hits appears in the
TOI table or on Zooniverse Talk. Its yield was characteristically
different from sweep 2's, though: where sweep 2's false alarms were
dominated by blends and phantoms, sweep 3 produced three genuine
binaries and the project's first two grey-drawer spot cases — and
its strongest hit sat exactly on the TESS-orbit resonance and drew
the project's first orbit-phase pile-up conviction to prove it.
