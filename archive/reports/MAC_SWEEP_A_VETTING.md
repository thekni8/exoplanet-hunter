# Mac Sweep A — Vetting Report: TIC 149631332

**Field:** RA 88.0, Dec −62.0, cone 0.5° — the first completed sweep on
the Mac (job `fe4de5dbf42c48ec`, finished 2026-11-05 23:50 IST;
5 targets screened, 4 hits). This star was target 2 of 5 and the
sweep's headline hit. Vetting run VM-local the same night through
`macsweep_vet.py` (the sweep-5 gauntlet driver, field label changed
only) plus hand stages; history logging suppressed in-process,
`data/hunter.db` and `discoveries.csv` verified byte-identical
(md5 `33b70438…` / `2c8abaae…`) before and after. Full numbers:
`vetting_results/149631332.json` (+ persistence sidecars).

**The hit as swept:** TIC 149631332, R\* = 0.29 R☉, Tmag = 14.0 —
P = 2.6807 d, **SDE = 41.7** (project #3), in-sweep persistence stamp
**19/20 sectors, mean depth 0.22% — "patchy"**, no contamination flag.

**Catalogue (ID-verified row):** RA 87.6485°, Dec −62.1754°;
TIC radius 0.2905 R☉, mass 0.2659 M☉, Teff 3404 K (mid-M dwarf),
distance 79.9 pc, Gaia DR3 4758184780212113408. **Contratio 0.034**
— the value from the row whose ID is exactly 149631332 (the table's
neighbour 149631327 carries 1.20; not this star's number). Crowded
field (102 TIC rows within 2′) but nothing bright close: nearest
neighbour 0.47′ away is fainter (Tmag 15.78); the brightest within
2′ (Tmag 10.67) sits 1.76′ off. Not flagged on Zooniverse Talk.

## Stage results

**(a) Reproduction — exact.** P = 2.680718 d (rel. diff 7×10⁻⁶),
SDE = 41.68, depth 0.244%, Rp = 1.56 R⊕, 20 sectors, 39,142 points.
Duration fitted at **5.976 h — the BLS grid maximum** (see duration
sanity below).

**(b) Machine odd/even stamp — "likely-eclipsing-binary."** Verbatim:
*"The two dips are different sizes — odd transits dip 0.065% but even
transits dip 0.112% (41% apart). That is the classic sign of an
eclipsing binary whose real period is twice the candidate period."*
This stamp fired the driver's stage-gate (mechanical verdict LIKELY
BINARY, preserved verbatim in the JSON as `driver_verdict_raw`).

**Hand odd/even — the stamp's split does not survive uncertainties.**
On the same flattened data with per-event scatter uncertainties:
odd **+0.117% ± 0.009% (13.0σ, 78 events)**, even **+0.097% ± 0.010%
(9.9σ, 77 events)** — a difference of **1.5σ: equal dips**. This is
the known stage-(b) mislabel on shallow patchy profiles (cf. TIC
349481800, sweep 5). The 2P fold tells the same story: eclipse pair
+0.092% ± 0.010% and +0.113% ± 0.009% — present, and equal.

**The dip has no transit-shaped core.** Re-folding with a physical
1.2 h window instead of the 5.976 h BLS window, the depth collapses
to **+0.043% ± 0.022% (2.0σ)**. The signal's power lives in its
breadth, not in a silhouette.

**(c) Double-period / ellipsoidal — no wave, three ways.** Machine
(raw curve): quadrature−shoulder delta **−0.021% ± 0.007% (−3.1σ)**,
stamp text "no twin-star ellipsoidal wave." Hand (flattened):
Q−S **−0.017% ± 0.007% (−2.5σ)**; out-of-eclipse sinusoid at P:
amplitude **0.0065% ± 0.0038% (1.7σ)**. A slight quadrature *dip*,
never a brightening. The twin-star channel is closed. Fourier at P
is likewise empty (A1 0.0015% ± 0.0036%, A2 0.0040% ± 0.0036%) —
the signal is a dip train, not a coherent wave.

**(d) Orbit-phase — acquitted.** 155 on-data centres, boundary
fraction 0.10, R = 0.252, no pile-up. Not a window artifact.

**(e) Persistence — real everywhere, and the uncapped trap.**
Cap-20 module run reproduces the stamp exactly: 19/20 sectors
≥1.5σ, weighted mean +0.218% ± 0.009%, verdict MIXED on depth
χ² (97.4 / 19 dof, p = 1.6×10⁻¹²); no raw monster sectors.
The uncapped module run at the fixed ephemeris reads CONCENTRATED
(+0.038%, 11/45) — **but that column is contaminated here**: the
uncapped pipeline's BLS locked onto 13.3466 d, so its transit mask
protected the wrong ephemeris and the flatten partially absorbed
the 2.6807 d dips (sector-by-sector, `depth_pct` collapses while
`depth_raw_pct` is identical between runs). The honest tiebreaker
is the **raw-flux measurement at the fixed ephemeris** (hand stage,
chunk-σ mirror of the module): over all 46 products,
**+0.133% ± 0.013% at 10.6σ**, era-split —

| Era | Products | Weighted mean depth | Sig. | χ² p |
|---|---|---|---|---|
| sectors ≤ 26 | 11 | +0.131% ± 0.017% | 7.5σ | 0.21 |
| sectors 27–59 | 15 | +0.130% ± 0.019% | 6.8σ | 0.98 |
| sectors ≥ 60 | 20 | +0.189% ± 0.054% | 3.5σ | ≈1.0 |

— positive and mutually consistent in **every** era. Not
era-confined, not concentrated, not a pipeline phantom. Largest
single product: sector 96 at +1.456% ± 0.775% (1.9σ, below the 5%
monster rule; no monsters flagged).

**Uncapped analyze context:** over all 46 sectors BLS prefers
**P = 13.3466 d, SDE = 30.0**, depth 0.605%. Folded there, the full
data show a deeper, narrower phenomenon: binned fold minimum
**−0.335%**, duty cycle below half-depth 8.3%, Fourier A1
**0.089% ± 0.004% (25σ)**, A2 0.035% ± 0.004%. The star is
photometrically active on a ~13.3 d scale; 13.3466 / 2.6807 = 4.98.

**(f) Duration sanity — the event cannot be a transit.** Kepler
with the TIC mass gives a/R\* = 18.0; the longest possible central
transit at P = 2.6807 d is **1.19 h** (1.14 h for Rp → 0). The BLS
duration, 5.976 h, is **5.0× longer than any transit this star can
host**, a 9.3% duty cycle. (The 277313805 test, at 5.0× instead of
9.5×.)

## Verdict: INCONCLUSIVE — real signal, spot-modulation profile

The stamp's bottom line — *not a planet* — is **upheld**; its
species (LIKELY BINARY) is **refuted by hand** and the driver's
mechanical verdict is reconciled here, with `driver_verdict_raw`
preserved in the JSON. The planet reading is independently barred
by duration (5.0× the physical maximum; no transit-width core).
The binary reading fails on equal odd/even folds (1.5σ) and three
null wave tests. The phantom reading fails on the raw era-split:
a depth-consistent ~0.13% dimming at the ephemeris across the
whole mission, on a clean aperture (contratio 0.034), with no
orbit-phase pile-up. What remains is the project's recognised
spot-profile class (TIC 177172764, TIC 349481800): a rotating,
spotted mid-M dwarf whose spot geometry projects a broad,
persistent dip train near P_rot/5 (P_rot candidate 13.35 d) —
real photometry, wrong species for both convictions, unprovable
in detail from photometry alone.

**Decisive test:** the hand odd/even fold (it removes the only
conviction on the table). **Untested:** centroid/difference
imaging (not demanded — contamination is low and the signal is
consistent across pipelines and eras); the 13.3466 d phenomenon's
own gauntlet (context here, not a sweep hit at that period).

---

# Addendum (2026-11-06): TIC 374912514 — second vetted hit of Mac Sweep A

**The hit as swept:** TIC 374912514, target 5 of 5 in the same Mac
Sweep A job — R\* = 0.27 R☉, Tmag = 12.9 — P = 18.8229 d,
**SDE = 13.4**, in-sweep persistence stamp **11/19 sectors, mean
depth 0.13% — "patchy"**, no contamination flag. Vetting run
VM-local through `macsweep_vet.py` plus hand stages, sequential
single processes (memory discipline); history logging suppressed
in-process, `data/hunter.db` and `discoveries.csv` verified
byte-identical (md5 `33b70438…` / `2c8abaae…`) before and after.
Full numbers: `vetting_results/374912514.json` (+ persistence
sidecars). The star was independently re-detected with identical
parameters in Mac Sweep B (RA 89, Dec −62) — the same sectors
underlie both sweeps, so that re-proves pipeline reproducibility,
not independence.

**Catalogue (ID-verified row):** RA 89.0305°, Dec −61.8787°;
TIC radius 0.2700 R☉, mass 0.2428 M☉, Teff 3250 K (M dwarf),
distance 41.2 pc, Gaia DR3 4758253568407026176. **Contratio
0.007** — the cleanest aperture of any vetted hit. 54 TIC rows
within 2′, but the brightest (Tmag 14.45) is 1.5 mag fainter at
1.04′ and the closest neighbours are Tmag ≥ 20.

## Stage results

**(a) Reproduction — exact.** P = 18.822932 d (rel. diff
1.7×10⁻⁶), SDE = 13.42, depth 0.144%, Rp = 1.12 R⊕, duration
**0.72 h**, 20 sectors (1–13, 27–34), 307,610 points.

**(b) Machine odd/even stamp — "likely-eclipsing-binary," and
itself broken.** Verbatim: *"The two dips are different sizes —
odd transits dip −0.009% but even transits dip 0.004% (302%
apart)."* Both machine depths are noise: the machine fold
recovered **neither** dip, and the conviction is a ratio of two
~zero numbers. This stamp fired the driver's stage-gate
(mechanical verdict LIKELY BINARY, preserved verbatim in the
JSON as `driver_verdict_raw`).

**Hand odd/even — the kill does not survive contact with the
ephemeris.** Per-event folds on the production flattened curve
at the analyze ephemeris: odd **+0.126% ± 0.063% (2.0σ, 10
events)**, even **+0.157% ± 0.049% (3.2σ, 11 events)** — a
difference of **0.39σ: equal dips**, both matching the BLS depth
and the module's cap-20 weighted mean (+0.128% ± 0.020%). The
2P fold pair is likewise present and equal (+0.157% /
+0.126%). A new flavour of the stage-(b) failure family: total
fold evaporation followed by a ratio-of-noise conviction.

**(c) Double-period / ellipsoidal — no wave, four ways.**
Machine (raw curve, its own fold refined to 36.58 d): delta
+0.015% ± 0.003% at 5.1σ but far below the +0.2% amplitude
threshold — stamp "no-ellipsoidal-signal"; its eclipse windows
measure noise (−0.017% / +0.010%). Hand, at the fixed
ephemeris: quadrature−shoulder on the flattened curve
**+0.0008% ± 0.0027% (0.3σ)**; out-of-eclipse sinusoid at P
0.0006% ± 0.0014% (0.4σ); Fourier at P empty (A1 0.0009%,
A2 0.0001%). The twin-star channel is closed.

**(d) Orbit-phase — acquitted.** 21 on-data centres, boundary
fraction 0.14 (rule: ≥0.5 to convict), R = 0.44. No pile-up.

**(e) Persistence — two columns, two stories, one arbiter.**
Cap-20 module run reproduces the stamp exactly: 11/19 sectors
≥1.5σ, weighted mean +0.128% ± 0.020%, verdict MIXED on depth
χ² (53.1 / 18 dof, p = 2.5×10⁻⁵); no raw monster sectors.
The uncapped module run reads CONCENTRATED (13/96 ranges,
+0.072%) — **but that column is mask-contaminated again**: the
uncapped pipeline's own BLS locked onto 14.4027 d (context
stage below), its transit mask protected the wrong ephemeris,
and the flatten absorbed the 18.8229 d dips (sector 61 range:
flattened −0.013% vs raw +0.479%). The honest tiebreaker is
the **raw-flux measurement at the fixed ephemeris**, de-
duplicated to distinct sectors (110 product ranges = only 44
distinct sectors; duplicate ranges are the same photons via
SPOC / TESS-SPOC / QLP, so sigmas are not shrunk): overall
**+0.148% ± 0.047% at 3.1σ**, χ² p = 0.69, era-split —

| Era | Distinct sectors | Weighted mean raw depth | Sig. | χ² p |
|---|---|---|---|---|
| sectors ≤ 26 | 11 | +0.218% ± 0.098% | 2.2σ | 0.26 |
| sectors 27–59 | 11 | +0.235% ± 0.081% | 2.9σ | 0.37 |
| sectors ≥ 60 | 16 | +0.040% ± 0.072% | 0.6σ | 0.99 |

— a constant ~0.22% depth through mission years 1–3, and
**nothing in years 5+**. A transiting planet cannot switch
off between eras; that single fact bars the planet reading
without any help from the (refuted) binary stamp.

**Uncapped context:** over all 110 products the two-pass BLS
prefers **P = 14.4027 d, SDE = 22.8**, depth 0.053%, duration
at the 5.976 h grid maximum; folded there the data show a
narrow dip (binned minimum −0.045%, duty cycle below
half-depth 2%) riding on a coherent wave (Fourier A1
**0.0107% ± 0.0008% at 13.8σ**, A2 0.0051%). The star's
dominant full-mission phenomenon is this 14.40 d activity
signal; 18.8229 / 14.4027 = 1.307 — no low-order harmonic
relates the hit to it.

**(f) Duration sanity — no bar, for once.** Kepler with the
TIC mass gives a/R\* = 68.8; the longest possible central
transit at P = 18.8229 d is **2.17 h**, and the BLS duration
is 0.72 h — a ratio of **0.33**, comfortably physical
(a 0.16% duty cycle). The physical-window morphology check
agrees weakly: folding in a 2.17 h window gives +0.020% ±
0.024%, against +0.048% expected from pure dilution of a
0.72 h box — 1.2σ low, consistent within noise. The event is
genuinely narrow; its problem is not its shape but its
lifespan.

## Verdict: INCONCLUSIVE — real in years 1–3, gone by year 5

The stamp's bottom line — *not a planet* — is **upheld**; its
species (LIKELY BINARY) is **refuted by hand**, and the
driver's mechanical verdict is reconciled here, with
`driver_verdict_raw` preserved in the JSON. The binary reading
fails on equal odd/even folds (0.39σ), an equal 2P pair, and
four null wave measurements. The blend reading has no support
(contratio 0.007, no bright close neighbour, no monsters) and
a neighbour eclipse would not vanish from the late-era
aperture either. The phantom reading fails for eras 1–2: the
signal reproduces exactly, folds coherently (all-events
+0.142% ± 0.038%), and sits in the raw flux at a
χ²-consistent constant depth across 22 distinct sectors. The
survivor reading fails on the era split: sectors ≥60 —
16 distinct sectors, more data than either early era — show
+0.040% ± 0.072%. What remains is the project's era-confined
spot-profile class (precedent TIC 177163233): a real, narrow,
periodic dip train at 18.8229 d on a 3250 K M dwarf that
persisted through mission years 1–3 and was gone by year 5,
on a star with a stronger, separate 14.40 d activity signal.

**Decisive test:** the de-duplicated raw-flux era split (it
bars the planet — signals cannot switch off — and, for the
early eras, the phantom). The hand odd/even fold removes the
only conviction. **Untested:** centroid/difference imaging
(would settle on-target vs the 1.04′ neighbour definitively;
not demanded — contratio 0.007 and the era behaviour argue
on-target stellar); ExoFOP disposition; epoch-drift/TTV
structure within sectors 1–39; the 14.4027 d phenomenon's own
gauntlet (context here, not a sweep hit).

---

# Addendum (2026-11-06): TIC 374912514 — closing test, the late-era loophole

The vetting above left one named loophole: the era split was measured
at the **fixed** ephemeris, and if the period were fractionally off,
phase error grows with time — the fold would smear the late sectors
first, mimicking a switch-off. This test settles it with a
**late-era-only free search**: nothing about the late data is folded
at the old ephemeris unless the data itself puts it there.

**Setup.** Distinct sectors ≥ 60 only — the vet's 16 usable distinct
sectors (61–69, 87, 89, 90, 93, 96, 97, 98; sectors 88, 94, 95 have
products but were not usable in the vet's raw measurement and are
excluded, as are all duplicate-pipeline ranges — first usable
product per distinct sector in collection order, a rule verified to
reproduce the vet's distinct-sector aggregates to <0.001%). Same
download/stitch/flatten conventions as the gauntlet (production
two-pass mirror), run under both flatten variants: (A) strict
production replication (the era's own pass-1 BLS picks the re-flatten
mask) and (B) candidate-masked re-flatten (mask at the fixed
ephemeris — the depth-recovery pass aimed at the candidate, the
construction the vet's own fold numbers enjoyed). Control: the
identical free-phase fold on the middle era (27–59, 11 distinct
sectors), where the raw signal measured +0.235%. Drivers:
`closing_test_374912514.py`, `closing_test_374912514_stage2.py`;
full numbers in `vetting_results/374912514.json`
(`closing_test_late_era_search`) + fold-scan sidecars.

**Test 1 — free BLS, late era alone.** The periodogram has *nothing*
at the candidate: the local peak within ±0.5% of 18.822932 d sits at
18.76413 d with **SDE 0.13** (production pass 2), 0.12 (pass 1),
0.14 (candidate-masked). The global bests are the broad ~14.3–15.0 d
activity complex at SDE 5.3–5.6, duration pinned at the 5.98 h grid
maximum. A period fractionally off would still pile BLS power within
a few tenths of a percent of the truth; there is no power there at
all.

**Test 2 — free-phase fold at P = 18.822932 d, late era.** Depth and
phase both free (0.01 d scan steps, vet per-event estimator). At the
ephemeris: **−0.021% ± 0.045%** (candidate-masked), +0.033% ± 0.071%
(production). No phase recovers the signal: the largest point
estimate is +0.131% ± 0.081% at φ = +0.50 d (1.6σ), and the scan's
nominal significance maximum is **+0.069% ± 0.027% (2.5σ) at
φ = 11.00 d** — half the vetted depth, 0.58 P from the ephemeris,
and below the ~3σ maximum expected from ~630 independent phase
cells under the null. The smearing hypothesis predicted a real
0.14–0.24% dip train at a drifted phase; no phase has one.

**Test 3 — control, middle era.** Healthy. On the identical
candidate-masked construction, the middle era's free BLS top peak
*is* the candidate: **P = 18.88419 d** (0.33% from the ephemeris),
**SDE 7.69, depth 0.153%, duration 0.72 h**; the fold recovers
+0.089% ± 0.059% at φ = 0 and +0.085% ± 0.019% (4.5σ) at
φ = +0.30 d. The depths are attenuated against the raw +0.235% —
flatten absorption, on the vet's own flattened scale (0.128–0.148%) —
but period, duration, phase and depth all land on the candidate, so
the construction demonstrably *can* see this signal where it lives.
The late-era null is a property of the late-era data. (Context, not
used in the decision: under the era-own mask the middle era's BLS is
dominated by a separate 15.41464 d phenomenon, SDE 18.46 — the
mask-hijack failure mode that motivated variant B.)

**Decision.** LIVE required a near-period BLS peak at SDE ≥ 8.5
*and* a free-phase depth of 0.14–0.24%: the actuals are SDE 0.13
and no signal-consistent depth at any phase — it fails both clauses
by an order of magnitude. CLOSED required SDE < 8.5 (met, 0.13),
a ~zero free-phase depth (met: −0.5σ at the ephemeris; the one
disclosed nuance is the 2.5σ nominal scan maximum — applying the
"<2σ" wording to it with zero trials correction is the only route
to AMBIGUOUS, and it recovers neither the depth, the phase, nor any
BLS support), and a healthy control (met). **The loophole is
closed.** The signal was real in mission years 1–3 and absent in
years 5+; no drifted ephemeris resurrects it. The verdict —
**INCONCLUSIVE, era-confined spot profile (TIC 177163233 class)** —
is final, and the "epoch drift within sectors 1–39" item comes off
the untested list insofar as it bore on this question.

*history logging suppressed in-process; `data/hunter.db` and
`discoveries.csv` md5-verified byte-identical before and after
(`33b70438…` / `2c8abaae…`); no server run; Mac untouched; nothing
pushed.*
