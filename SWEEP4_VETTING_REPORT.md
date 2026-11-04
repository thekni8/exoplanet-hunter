# Sweep 4 — Vetting Report

Patch centre: **RA 85.0, Dec −68.0**, cone 1.0° — the deepest bullseye
yet swept, 2.4° from the south ecliptic pole. Dev ran the sweep on the
new code (in-sweep persistence + contamination flag + raw-fold exhibit)
in a **fresh Codespace** on 2026-11-04 (job 8b5c9e68a2d547b9) after the
first attempt on this patch died with the deleted Codespace (HTTP 502;
its partial progress is unrecoverable and is NOT part of this record —
the sweep was re-run from scratch and completed 20/20). Sweep settings
as before: Tmag 11.5–15, R 0.2–0.5 R_sun, sector cap 20, Max Stars 20.
Result: **11 hits at SDE ≥ 8.5 — the richest patch yet** (sweeps 1–3
produced 9, 11 and 6). Every hit arrived pre-stamped by the in-sweep
persistence code; none was stamped "persistent" — 7 patchy, 4
fails-persistence. Method: the stage gauntlet (reproduce → odd/even →
double-period → orbit-phase → persistence), run post-gate where the
sweep-3 precedent requires it, plus TIC contamination, Zooniverse
known-check, and a NASA Exoplanet Archive TOI TAP check per star.
Patch context worth carrying through every section:

- **10 of 11 hits carried the high-contamination flag.** The TIC
  values, fetched for this report, run 0.109–0.525 — and the one
  unflagged hit (TIC 389367432) measures **0.098**, two percent under
  the 0.10 line. The flag mechanics are verified once more; this
  near-pole field is simply crowded.
- **7 of 11 hits fall in P 13.2–14.3 d** — the orbit-adjacent band
  (TESS orbit 13.7 d). Twice before, this band was acquitted as a
  systematic (the sweep-1 period cluster; TIC 294751586's orbit-phase
  test). This sweep's orbit-phase results are collected in the
  patch-level note after the per-star sections.

One catalogue caveat: the healed 1.0° TIC cone query (the sweep's own
call) kept dropping connections during this vetting session (attempt 1
died after ~10 min), so positions/contamination were harvested from
per-star `query_object` neighbourhood tables instead — same TIC
catalog, same values ExoFOP displays.

---

## Target 9 of 20 — TIC 277313805 — **LIKELY BINARY**

Sweep hit: **P = 0.5637 d, SDE = 50.8 — the highest SDE of the project,
twice the previous record** (TIC 231124169's 24.4), at cap 20 (48
sectors available). The HIT line carried the high-contamination flag;
the in-sweep stamp read **"13/20 sectors, mean depth 0.09% — patchy."**
Star: Tmag 14.23, TIC radius 0.265 R_sun, 0.237 M_sun, Teff 3520 K
(M dwarf), 83 pc. Position RA 84.43723°, Dec −67.60331° — 0.45° from
the patch centre. IDs: 2MASS 05374492-6736119,
Gaia DR3 4659383386920175872.

### Stage by stage

- **(f) Known checks:** Zooniverse Talk **False**. NASA Archive TOI
  table: **0 rows**. (The session's first-pass TAP query errored on
  this star — as on four others — in the degraded afternoon window;
  the retry returned 0. Nobody has claimed this star.)
- **(a) Reproduce: exact.** P = 0.56371 d (rel. diff 1.1×10⁻⁵),
  SDE 50.84, depth 0.090%, nominal Rp 0.85 R_earth, duration **5.976 h**,
  20 sectors, 39,830 points (sparse FFI products).
- **(b) Odd/even: alternating depths → driver kill, LIKELY BINARY.**
  Folded at 1.1274 d: odd **0.055%**, even **0.022%** — 60% apart.
  One eclipse train is two and a half times the other: the classic
  two-eclipse signature at twice the sweep period.
- **(c) Double-period (post-gate): a real but sub-line wave.**
  Refined 2P = **1.12745 d**; eclipse windows **0.072% / 0.064%**
  (near-equal); quadrature delta **+0.078% ± 0.012% at 6.7σ** —
  positive, significant, but under the pre-set +0.2% likely-binary
  line, so the stage's mechanical verdict is "no-ellipsoidal-signal."
  Read in context below.
- **(d) Orbit-phase: no pile-up** (irrelevant at this period, run for
  the record): ratio 0.041, 792 on-data centres, boundary fraction
  0.15, R = 0.197.
- **(e) Persistence at cap 20, re-derived independently: matches the
  in-sweep stamp digit for digit** — 20 usable sectors, **13/20
  ≥ 1.5σ**, weighted-mean depth **+0.090% ± 0.011%** (the stamp's
  13/20, 0.09%), χ² p = 0.093 (depths consistent with a constant).
  Per-sector depths are positive in both cadence regimes — year-1
  SPOC sectors (+0.07…+0.23%) and cycle-3 FFI sectors (+0.04…+0.13%)
  alike. The signal is coherent across the whole swept baseline.
  No monster sectors. **The in-sweep stage is validated against the
  standalone module on a fourth live star** (and a fifth and sixth —
  see the pair below).
- **Contamination: 0.137** (TIC contratio) — flagged, as the HIT line
  said.

### The shape exhibits (why this is a binary, not a pulsator, not a planet)

The brief for this star asked the stages to name it — ultra-short
period, extreme coherence, shallow mean. Three independent shape
measurements, all on the sweep's own (cap-20) data treatment:

1. **The duration is impossible for a transit.** The BLS duration is
   pinned at the grid maximum, 5.976 h — a 44% duty cycle. For this
   star (0.265 R_sun, 0.237 M_sun) Kepler gives a/R* = 6.8, so the
   longest possible central transit at P = 0.5637 d lasts **0.63 h**.
   The fitted event is **9.5× longer than any transit this star can
   host**. Whatever dips here is not a silhouette crossing the disc.
2. **The fold is a wave, not a box.** Fourier decomposition of the
   flattened curve: fundamental at 0.5637 d **A1 = 0.066% ± 0.006%**,
   first harmonic **A2 = 0.053% ± 0.006%** — A2/A1 ≈ 0.8. A pure
   sinusoid (spot rotation, most pulsation) is A1-dominant; a narrow
   transit box sprays power across many harmonics at a ~4% duty
   cycle. Comparable fundamental + harmonic is the fingerprint of a
   **double-waved light curve** — two minima per cycle of the true
   1.1274 d orbit. The binned folds agree: broad minima spanning
   ~40% of phase (deepest bins 0.9987–0.9992), broad maxima up to
   1.0020, and in the 2P fold the two minima clusters sit half a
   cycle apart (phases ≈ +0.03…+0.09 and ≈ −0.41…−0.44). A
   Lomb-Scargle scan concurs: top peak at exactly 0.5637 d, second
   at its harmonic 0.2819 d (absolute powers are small — the signal
   is 0.09% against ~1.5% per-point FFI scatter — but the ordering
   is exact).
3. **The quadrature wave is there.** Stage (c)'s +0.078% at 6.7σ is
   an ellipsoidal wave whose amplitude is *comparable to the eclipse
   depths themselves* (0.064–0.072%) — exactly the proportion a
   contact or near-contact binary shows, and exactly what the
   pre-set +0.2% line (calibrated on deep, undiluted EBs) cannot
   see at this dilution. The line is a threshold, not a law of
   nature; at 6.7σ the wave is real, and starspots do not raise one.

Against the pulsator reading: a 13.5 h pulsation on a 3520 K M dwarf
has no plausible mode, and pulsation does not alternate eclipse
depths at 2P (stage b) nor phase-lock a quadrature wave to the
orbital fold (stage c). Against rotation: a spot wave is one wave
per rotation (A1-dominant, no alternation); this star shows two
unequal minima per 1.1274 d with a tidal wave between them.

**The dilution is the remaining puzzle, and it points at the
neighbour.** An on-target contact binary eclipses at ≥10%, not
0.07%. At contratio 0.137 the aperture carries real neighbour light;
the coherent reading is an eclipsing binary **in the aperture** —
most likely a neighbour — diluted to the observed 0.07–0.12%. The
fold checks cannot centroid it (that is difference-imaging work),
and, per batch precedent, the planet reading is dead either way.

### The uncapped tiebreaker (all 48 sectors) — with a stitch warning

- **Uncapped analyze: the 0.5637 d peak dissolves.** Over 48 sectors
  the top BLS peak moves to P = 13.758 d at **SDE 7.82 — below the
  discovery bar** (depth 0.44%, duration again 5.976 h).
- **Uncapped persistence at the fixed cap-20 ephemeris:
  CONCENTRATED** — 45 usable, **8/45 ≥ 1.5σ**, weighted mean diluted
  to +0.016%. Era split: cycle-3 sectors (27–39) still carry
  **+0.085% ± 0.015% (5.5σ)** — the cap-20 value for those same
  sectors — while the year-1 group reads only +0.015% and sectors
  ≥ 60 read +0.010% (0.4σ).
- **Why the two stitches disagree about year 1 (recorded plainly):**
  the uncapped run's own BLS landed on the 13.758 d solution, so its
  depth-refinement pass masked *that* ephemeris, and its flattening
  window absorbs the 13.5 h wave differently in 2-minute SPOC data
  (year 1) than in FFI data (cycle 3) — the same cross-stitch
  softness flagged for TIC 177171983 in sweep 3, here with a
  identified mechanism. The signal's reality does not rest on the
  uncapped stitch: the cap-20 stitch measures it sector after sector
  in *both* cadence regimes, and the cycle-3 sectors agree across
  stitches at +0.085%. The verdict below uses none of the contested
  numbers.

### The missing "Refining depth" line — settled

This star's sweep log block was the only one of 20 without the
"Refining depth: re-detrending…" line. The code path makes it
determinable: the refinement pass is skipped when the pass-1 transit
mask would cover >50% of the curve (hunter.py, depth-fix guard). At
P = 0.5637 d with the pass-1 duration at the 0.249 d grid top, the
mask fraction is **(0.249 + 0.04) / 0.5637 = 51.3%** — over the line,
so the pass is skipped by design. Verified directly: a cap-20
pipeline rerun reproduces P/SDE exactly with the line **absent**,
while the uncapped run (whose pass-1 solution differs) emits it.
**The sweep's reported depth and SDE for this star are therefore
pass-1 (pre-refinement) values** — appropriate enough here, since
the "transit" being masked is a 44%-duty wave, not a transit.

**Verdict: LIKELY BINARY** — eclipsing binary in the aperture (most
likely a diluted neighbour), true period **1.12745 d**; the sweep's
0.5637 d is the half-period alias. The project's highest-SDE hit is
a contact-binary-class wave wearing a sub-Earth costume (nominal
0.85 R_earth) — the cleanest demonstration yet that SDE ranks
coherence, not planethood.

Raw record: `vetting_results/277313805.json`; fold-shape exhibits in
`vetting_results/277313805_foldshape.json`; persistence tables at
`vetting_results/277313805_persistence_cap20.json` and
`vetting_results/277313805_persistence_uncapped.json`; run logs in
`sweep4_logs/`.

---

## Targets 3 + 4 of 20 — the twin-period pair — **LIKELY BINARY × 2 (independent)**

Sweep hits, on adjacent target slots: **TIC 404931136 — P = 14.1724 d,
SDE = 10.6**, high-contamination flag, stamp **"5/14 sectors, mean
depth 1.20% — patchy"**; and **TIC 404924199 — P = 14.1895 d,
SDE = 12.0**, high-contamination flag, stamp **"6/18 sectors, mean
depth 0.12% — patchy."** The periods differ by 0.017 d, which raised
the shared-source hypothesis: one eclipsing binary, two apertures.
The pair was vetted jointly. It does not survive contact with the
geometry:

- **Separation: 0.4699° = 28.2 arcmin ≈ 80 TESS pixels.** TIC
  404931136 sits at RA 85.50667°, Dec −68.13119° (0.23° from centre;
  Tmag 14.82, 0.332 R_sun, 0.313 M_sun, Teff 3393 K, 134 pc;
  2MASS 05420160-6807521, Gaia DR3 4659287523242300032). TIC 404924199
  sits at RA 84.97344°, Dec −67.70623° (0.29° from centre; Tmag 13.81,
  0.480 R_sun, 0.477 M_sun, Teff 3575 K, 144 pc; 2MASS 05395361-6742223,
  Gaia DR3 4659367066043460096). Different stars, different distances,
  apertures that cannot overlap — PRF-wing coupling at 80 pixels is
  negligible. **One EB cannot light both apertures.**
- **The ephemerides disagree anyway.** Propagated to a common epoch,
  the two eclipse trains sit **0.164 cycles (55.8 h) apart** — not
  the ~0 a shared train requires — and the periods themselves differ
  by 0.017 d, which over the ~2,300 d baseline is ~2.8 cycles of
  drift. One source has one period and one phase; these have neither
  in common.
- **Each star convicts itself independently** (below). The period
  coincidence is the patch talking: both are ~28.4 d binaries whose
  half-period aliases landed in this patch's crowded 13.2–14.3 d
  cluster (see the patch-level note). Even their *true* periods
  coincide to 0.012 d (28.3887 vs 28.4009) — a genuine coincidence,
  checked against the instrument: their eclipse phases in absolute
  time differ (t0 mod 2P ≈ 18.7 vs 15.8 d), so this is not one
  systematic wearing two stars.

### TIC 404931136 — LIKELY BINARY (the deep one)

- **(f) Known checks:** Zooniverse Talk **False**. TOI table:
  **0 rows** (first-pass query errored; retry returned 0).
- **(a) Reproduce: exact.** P = 14.1724 d, SDE 10.57, depth **5.166%**,
  nominal Rp 8.18 R_earth, duration 5.976 h, 17 sectors, 177,611 points.
- **(b) Odd/even: planet-like** — odd 0.804%, even 0.845% (ratio
  0.95). The equal-twin blind spot (cf. TIC 308851365): twin eclipses
  of similar depth read as one planet-like train; the fold depths
  are median-window-diluted against the 5.17% BLS depth.
- **(c) Double-period: likely-binary, emphatic.** Refined 2P =
  **28.3887 d**; eclipse windows **1.179% / 1.895%** (unequal);
  ellipsoidal delta **+0.728% at 20.6σ** — a strong tidal wave on
  the target's own raw curve. Driver kill at (c).
- **(d) Orbit-phase: no pile-up** by the pre-set rule (32 on-data
  centres, boundary fraction 0.41, R = 0.229 — elevated fraction,
  R far under the 0.4 line).
- **(e) Persistence (post-gate):** 14 usable, **5/14 ≥ 1.5σ**,
  weighted mean **+1.196% ± 0.093%** — the stamp's 5/14 and 1.20%
  digit for digit (fifth live validation of the in-sweep stage).
  χ² p ≈ 2×10⁻¹⁸: the depths are grossly inconsistent — because
  sectors **97 (+35.7% raw) and 98 (+33.6% raw)** are monster
  sectors whose flattened in-window depths (+15.7%, +21.4%) swamp
  the table. Era split (the star has no year-1 sectors): cycle-3
  ranges +0.200% (1.2σ, 0/4); sectors ≥ 60 **+1.643% ± 0.112%
  (14.6σ, 5/10)** — the excess lives in the later cycles, monsters
  included. The conviction does not rest on persistence: a 20.6σ
  phase-coherent tidal wave across 177k points is not a two-sector
  artifact, and the eclipse pair is measured on the full raw curve.
- **Contamination: 0.153** — flagged; yet the wave amplitude (0.73%)
  and eclipse depths argue the binary is the target itself or a
  close companion, not a faint smear.

**Verdict: LIKELY BINARY** — eclipsing binary, true period
≈ **28.39 d**; the sweep's 14.1724 d is the half-period alias.

### TIC 404924199 — LIKELY BINARY (the shallow echo that wasn't)

- **(f) Known checks:** Zooniverse Talk **False**. TOI table:
  **0 rows**.
- **(a) Reproduce: exact.** P = 14.1895 d, SDE 12.00, depth 1.450%,
  nominal Rp 6.31 R_earth, duration 5.976 h, 19 sectors, 200,773 points.
- **(b) Odd/even: planet-like** — odd 0.258%, even 0.254% (ratio
  0.98). Same equal-twin blind spot.
- **(c) Double-period: likely-binary, the strongest wave of the
  project.** Refined 2P = **28.4009 d**; eclipse windows
  **0.589% / 0.513%**; ellipsoidal delta **+0.529% at 34.0σ**.
  Driver kill at (c).
- **(d) Orbit-phase: no pile-up** (36 on-data centres, boundary
  fraction 0.39, R = 0.200).
- **(e) Persistence (post-gate):** 18 usable, **6/18 ≥ 1.5σ**,
  weighted mean **+0.125% ± 0.031%** — the stamp's 6/18 and 0.12%
  digit for digit (sixth live validation). Monsters again in
  sectors 97 (+11.1% raw) and 98 (+11.8% raw); χ² p ≈ 6×10⁻¹⁸ on
  the same account. Era split: cycle-3 ranges −0.145% (−1.9σ, 1/4);
  sectors ≥ 60 **+0.174% ± 0.033% (5.2σ, 5/14)**.
- **Contamination: 0.179** — flagged; the 34σ on-curve wave again
  argues for the target itself.

**Verdict: LIKELY BINARY** — eclipsing binary, true period
≈ **28.40 d**; the sweep's 14.1895 d is the half-period alias.

**Joint pair verdict: two independent eclipsing binaries.** The
shared-source hypothesis is dead three ways (80-pixel separation;
ΔP = 0.017 d; 0.164-cycle phase offset), and no dilution story is
needed: each aperture holds its own binary, each convicted by its
own ellipsoidal wave (20.6σ and 34.0σ). What the pair actually
documents is the patch's alias factory — ~28.4 d binaries are
common here, and BLS reports them at ~14.2 d. (For the record: the
BLS depth ratio A/B is 3.6×; the persistence-mean ratio is 9.6× —
the "10×" that prompted the pair hypothesis. Both ratios are
between two different stars' different signals and need no common
cause.)

Raw records: `vetting_results/404931136.json`,
`vetting_results/404924199.json`; joint analysis in
`sweep4_logs/pair_analysis.json`; run logs in `sweep4_logs/`.

---

## Target 6 of 20 — TIC 389367432 — **INCONCLUSIVE**

Sweep hit: **P = 5.1677 d, SDE = 8.9** at cap 20 (46 sectors
available) — the weakest SDE of the sweep and the **only hit of the
eleven without the contamination flag**. In-sweep stamp: **"6/14
sectors, mean depth 0.33% — patchy."** Star: Tmag 14.21, TIC radius
0.256 R_sun, 0.227 M_sun, Teff 3424 K (M dwarf), 74 pc. Position
RA 85.71371°, Dec −67.72514° — 0.39° from the patch centre. IDs:
2MASS 05425128-6743307, Gaia DR3 4659322948134539648.

- **(f) Known checks:** Zooniverse Talk **False**. TOI table:
  **0 rows**.
- **(a) Reproduce: exact.** P = 5.1677 d, SDE 8.87, depth 0.333%,
  nominal Rp 1.64 R_earth, duration **0.72 h**, 20 sectors,
  42,197 points (sparse FFI).
- **(b) Odd/even: folds evaporate — through a blind estimator.**
  Odd **−0.014%**, even **−0.005%** → deepest fold dip 4.2% of the
  BLS depth → the driver's mechanical kill: PIPELINE PHANTOM (raw
  verdict preserved in the JSON). **Caveat, decisive:** the event
  lasts 0.72 h inside a ~±0.5 d median window — ~3% of window points
  are in transit, so the median sits on baseline whether or not the
  dips exist. This is precisely the configuration of the sweep-1
  BLS-only class and of TIC 177163233 (0.72 h) and TIC 177172764 in
  sweep 3 — every one ruled INCONCLUSIVE, not phantom, for exactly
  this reason.
- **(c) Double-period (post-gate): clean.** Quadrature delta
  +0.005% at 0.4σ; eclipse windows 0.007% / 0.002% — no binary
  at 2P.
- **(d) Orbit-phase: no pile-up** (89 on-data centres, boundary
  fraction 0.16, R = 0.157; P/orbit ratio 0.377 — nowhere near a
  resonance).
- **(e) Persistence (post-gate): the stamp, digit for digit, and a
  real excess.** 14 usable, **6/14 ≥ 1.5σ**, weighted-mean depth
  **+0.329% ± 0.056% (5.9σ)** — the stamp's 6/14, 0.33% (seventh
  live validation of the in-sweep stage). 56 fully-covered events,
  median event depth +0.268%; no monster sectors. χ² p = 0.049 —
  marginal depth consistency. Per-sector, the positives are
  era-weighted: cycle-3 sectors 30–34 carry +0.78/+0.57/+0.26/
  +0.48/+0.84% (3.3/2.6/1.7/3.1/4.2σ), with year-1 sector 4 at
  +0.57% (2.2σ).
- **Contamination: 0.098** — the cleanest aperture of the sweep,
  2% under the flag line (and the reason this HIT line carried no
  flag). The blend route is implausible.

### The uncapped tiebreaker (all 46 sectors)

- **Uncapped analyze: demoted.** Top peak moves to P = 14.4933 d at
  SDE 7.14 — below the discovery bar.
- **Uncapped persistence at the fixed ephemeris: CONCENTRATED** —
  40 usable, **3/40 ≥ 1.5σ**, weighted mean diluted to
  **+0.047% ± 0.023%**.
- **Era split — with the sweep's starkest cross-stitch warning:**
  the uncapped accounting reads its own first-20 (swept) subset at
  only **+0.036% ± 0.025% (1.4σ)**, where the cap-20 accounting
  measures the same sectors at **+0.329% ± 0.056% (5.9σ)** — the
  two pipeline stitches disagree by ~5σ on identical sky. Within
  the uncapped accounting: sectors 27–39 **+0.242% ± 0.064%
  (3.8σ)**; sectors ≥ 60 +0.139% ± 0.068% (2.0σ, 0/20 ≥ 1.5σ);
  the four year-1 ranges −0.001% (nothing). The cycle-3 weighting
  appears in both stitches; its absolute depth does not survive
  the stitch change.

### Why INCONCLUSIVE, not PHANTOM — and not a candidate

The phantom label rests entirely on a fold test that cannot see a
0.72 h event; the batch precedent (three prior cases, identical
shape) forbids convicting on it. And there is something underneath:
a 5.9σ cap-20 per-sector excess over 56 events, where every
convicted phantom in the project averages +0.02…+0.07%. But the
excess is era-weighted, depth-marginal (χ² p = 0.049), dissolves
under the full baseline (peak moves, SDE 7.14, uncapped folds to
+0.047%), and its measured depth depends on which stitch you
believe. A planet holds constant depth in every era and every
stitch; this does neither. The consistent reading is **stellar
variability on a 0.256 R_sun M dwarf** — a spot pattern near the
5.17 d period that BLS sharpened, strongest in cycle 3 — the third
member of the grey drawer, after sweep 3's pair.

**Verdict: INCONCLUSIVE** (not a candidate; the uncapped check
closes the planet reading — no further follow-up owed unless a
future era re-lights it).

Raw record: `vetting_results/389367432.json`; persistence tables at
`vetting_results/389367432_persistence_cap20.json` and
`vetting_results/389367432_persistence_uncapped.json`; run log in
`sweep4_logs/`.

---

## Target 10 of 20 — TIC 389564031 — **INCONCLUSIVE**

Sweep hit: **P = 14.3145 d, SDE = 17.3** — the second-strongest SDE
of the sweep — at cap 20, with **79 sectors available** (the deepest
baseline of any hit in any sweep) and the high-contamination flag set.
In-sweep stamp: **"10/18 sectors, mean depth 0.11% — patchy."**
Star: Tmag 12.62 (the brightest hit of the patch), TIC radius
0.421 R_sun, 0.415 M_sun, Teff 3397 K (M dwarf), 64 pc. Position
RA 86.12182°, Dec −67.81098° — 0.46° from the patch centre. IDs:
2MASS 05442921-6748395, Gaia DR3 4659317931613027840.

- **(f) Known checks:** Zooniverse Talk **False**. TOI table:
  **0 rows** (first-pass query errored; retry returned 0).
- **(a) Reproduce: exact.** P = 14.3145 d, SDE 17.33, depth 0.103%,
  nominal Rp 1.47 R_earth, duration **0.72 h**, 20 sectors,
  323,475 points.
- **(b) Odd/even: a mechanical mislabel — folds evaporate.** The
  app's ratio rule returned "likely-eclipsing-binary" on odd
  **+0.0027%** vs even **+0.0001%**: 96% apart, of two zeros. The
  deepest fold dip is 2.6% of the BLS depth. This is the
  TIC 294671640 / TIC 299900306 pattern verbatim, and the raw app
  verdict is preserved in the JSON as `driver_verdict_raw`. (The
  0.72 h duration also makes this fold estimator-blind in the
  by-now-familiar way — but nothing here needs the caveat: there
  is no alternation to rescue, only absence.)
- **(c) Double-period (post-gate): nothing.** Refined 28.4053 d
  (the patch's ~28.4 d landing spot again — measuring zeroes):
  eclipse windows 0.005% / 0.008%, quadrature delta −0.003% at
  −1.4σ → no binary at 2P.
- **(d) Orbit-phase: acquitted.** P/orbit ratio 1.045; 34 on-data
  centres, boundary fraction 0.18 vs 0.219 by chance, R = 0.272 —
  no pile-up. The 14.31 d period's orbit adjacency is not
  supported as an instrument coupling for this star.
- **(e) Persistence (post-gate): the stamp, digit for digit — and
  a real excess.** 18 usable, **10/18 ≥ 1.5σ**, weighted mean
  **+0.106% ± 0.014% (7.7σ)**, median event depth +0.107% — the
  full BLS depth — over 31 fully-covered events. No monsters.
  (Eighth live validation of the in-sweep stage.) But χ² = 51.9 on
  17 dof, **p = 2.1×10⁻⁵**: the per-sector depths are not constant.
- **Contamination: 0.113** — flagged, mildly; no eclipse exists in
  the aperture for it to explain (stage c).

### The uncapped tiebreaker (all 79 sectors)

- **Uncapped analyze: the peak moves.** Top BLS peak at
  P = 14.5007 d, SDE 9.2 over 79 sectors — still in the
  orbit-adjacent band, no longer the sweep's 14.3145 d solution.
  (Full metrics were printed to the run log; the JSON save of this
  stage was lost when the vetting chain's process died under
  memory pressure from a parallel job — the surviving values are
  recorded in the JSON with their provenance.)
- **Uncapped persistence at the fixed ephemeris: CONCENTRATED by
  fraction (8/72 ≥ 1.5σ) but era-spread in depth** — weighted mean
  **+0.045% ± 0.008% (5.6σ)**, χ² p ≈ 1.0 in this accounting, 131
  full events, median event depth +0.047%. Era split:

  | Data | Ranges ≥1.5σ | Weighted-mean depth |
  |---|---|---|
  | Year-1 sectors (≤13) | 3/23 | +0.035% ± 0.012% (3.0σ) |
  | Sectors 27–39 | 3/27 | +0.060% ± 0.013% (4.7σ) |
  | Sectors ≥ 60 | 2/22 | +0.039% ± 0.023% (1.7σ) |
  | Swept subset (first 20) | 2/18 | +0.059% ± 0.017% (3.5σ) |

  Every era is positive; no era carries the cap-20 depth. The two
  stitches disagree on the depth by a factor ~2.3 (the uncapped
  stitch's own solution sits at 14.5007 d, so its refinement mask
  preserved a different ephemeris).

### Why INCONCLUSIVE — neither the driver's EB, nor a phantom, nor a candidate

The driver's LIKELY BINARY is a mislabel on two zeros, refuted by
stage (c) itself. The phantom drawer is equally unavailable: both
pipeline stitches measure a positive fixed-ephemeris excess —
convicted phantoms average ~zero under exactly this test, in both
stitches. What remains is a shallow, era-spread, depth-unstable
excess on the patch's brightest M dwarf, which BLS sharpens into a
0.72 h box at SDE 17.3 in the swept subset and cannot hold at the
same period or depth over the full 79-sector baseline. That is
the grey drawer's signature, not a planet's: **stellar variability**
is the consistent reading.

**Verdict: INCONCLUSIVE** (not a candidate; the uncapped check
closes the planet reading).

Raw record: `vetting_results/389564031.json`; persistence tables at
`vetting_results/389564031_persistence_cap20.json` and
`vetting_results/389564031_persistence_uncapped.json`; run log in
`sweep4_logs/`.

---

## Target 18 of 20 — TIC 389672553 — **PIPELINE PHANTOM**

Sweep hit: **P = 13.6750 d, SDE = 10.2** at cap 20 (67 sectors
available) — the period sitting almost exactly **on** the 13.7 d
TESS orbit, vetted with the orbit-phase stage at full weight per
the brief. High-contamination flag set. In-sweep stamp: **"7/12
sectors, mean depth 0.03% — patchy."** Star: Tmag 12.53, TIC radius
0.488 R_sun, 0.486 M_sun, Teff 3624 K, 84 pc. Position
RA 86.95681°, Dec −67.92715° — 0.74° from the patch centre, the
second-most-distant hit in the cone. IDs: 2MASS 05474960-6755377,
Gaia DR3 4659302194853301632.

- **(f) Known checks:** Zooniverse Talk **False**. TOI table:
  **0 rows**.
- **(a) Reproduce: exact.** P = 13.6750 d, SDE 10.24, depth 0.114%,
  nominal Rp 1.80 R_earth, duration **0.72 h**, 20 sectors,
  203,072 points.
- **(b) Odd/even: total evaporation.** Odd **0.000%**, even
  **0.000%** → the driver's mechanical kill: PIPELINE PHANTOM.
  Recorded with the standing caveat — at 0.72 h inside a ±0.55 d
  window this fold is estimator-blind, so the conviction below
  does **not** rest on it.
- **(c) Double-period (post-gate): clean.** Quadrature delta
  −0.004% at −1.7σ; eclipse windows 0.014% / 0.010% — no binary.
- **(d) Orbit-phase, at full weight: elevated, sub-rule.** P/orbit
  ratio **0.9982** — a 1:1 lock. 26 on-data centres: boundary
  fraction **0.346** vs 0.219 by chance; circular **R = 0.492** —
  the highest R recorded in the project (the one convicted pile-up,
  TIC 177171983, had R = 0.471 with fraction 0.568). The pre-set
  rule needs fraction ≥ 0.5 AND R ≥ 0.4; the fraction acquits.
  The phase bins do cluster toward segment starts (9 and 7 centres
  in the first two 1.37 d bins) — documented, not convicted.
- **(e) Persistence (post-gate): the stamp's numbers — on a broken
  estimator.** 12 usable, **7/12 ≥ 1.5σ**, weighted mean
  **+0.031% ± 0.004%** — the stamp's 7/12 and 0.03% digit for digit
  (ninth live validation). But the per-sector table is nonsense:
  sector 2 reads +0.173% at **+26.2σ** while sector 5 reads
  −0.077% at **−10.8σ** and sector 6 −0.147% at −8.6σ;
  χ² = 922.6 on 11 dof (**p ≈ 10⁻¹⁹⁰**). The chunk-σ estimator
  collapses on this star's smooth 2-minute data — formal errors so
  small that sector-to-sector weather becomes tens of sigma in
  both directions. This accounting cannot testify.
- **Contamination: 0.178** — flagged; no eclipse exists in the
  aperture for it to explain (stage c).

### The uncapped tiebreaker (all 67 sectors)

- **Uncapped analyze:** top peak moves to P = 13.9126 d, SDE 9.8 —
  a different solution, still inside the orbit band.
- **Uncapped persistence at the fixed ephemeris: CONCENTRATED,
  and essentially zero.** 51 usable, **5/51 ≥ 1.5σ**, weighted
  mean **+0.012% ± 0.007% (1.7σ)**; median event depth collapses
  from +0.107% (cap-20 accounting) to **+0.010%** over 100 events.
- **Era split:**

  | Data | Ranges ≥1.5σ | Weighted-mean depth |
  |---|---|---|
  | Year-1 sectors (≤13) | 0/12 | +0.001% ± 0.008% (0.2σ) |
  | Sectors 27–39 | 3/21 | +0.056% ± 0.018% (3.1σ) |
  | Sectors ≥ 60 | 2/18 | +0.027% ± 0.030% (0.9σ) |
  | Swept subset (first 20 ranges) | 2/14 | +0.011% ± 0.011% (1.0σ) |

  Year 1 — the swept subset's own era in the other stitch's
  accounting — is exactly nothing. The one residue: cycle-3
  sectors carry a weak excess in both stitches (+0.056% here;
  ~+0.15% per sector for sectors 29/30/36/37/39 in the cap-20
  table, depths disagreeing 3× between stitches).

### Why PHANTOM — on the tiebreaker, not the fold

The grey-drawer rescues (sweep 3's pair, this sweep's two above)
were saved by a *hard* excess in at least one honest accounting —
7σ-class, depth-constant within its era. This star has none: its
loudest accounting is estimator-broken (26σ/−11σ neighbours), its
honest full-baseline accounting is 1.7σ from zero, and its period
is welded to the spacecraft orbit (ratio 0.9982) with the
project's highest orbit-phase R — the precise profile of an
orbit-band BLS ghost on 203k points of smooth data, kin to
TIC 294626348's "pipeline weather" in sweep 2. The cycle-3 residue
is recorded as an anomaly note, in the TIC 374942698 sense — not
a candidate, not a rescue.

**Verdict: PIPELINE PHANTOM** — instrumental/orbit-band false
alarm; conviction instrument is the uncapped tiebreaker plus the
persistence-estimator autopsy (the raw stage-gate label is
preserved in the JSON).

Raw record: `vetting_results/389672553.json`; persistence tables at
`vetting_results/389672553_persistence_cap20.json` and
`vetting_results/389672553_persistence_uncapped.json`; run log in
`sweep4_logs/`.

---

## Target 20 of 20 — TIC 276791802 — **LIKELY BINARY**

Sweep hit: **P = 13.7240 d, SDE = 11.2** at cap 20 (21 sectors
available) — the last target of the sweep, its period also in the
orbit-adjacent band. High-contamination flag set. In-sweep stamp:
**"5/16 sectors, mean depth 0.02% — patchy"** — the shallowest
stamp of the eleven. Star: Tmag 14.63, TIC radius 0.479 R_sun,
0.477 M_sun, Teff 3529 K, 201 pc. Position RA 83.15965°,
Dec −68.33119° — 0.76° from the patch centre, the most distant hit
of the cone. IDs: 2MASS 05323830-6819522,
Gaia DR3 4658560333740278656.

- **(f) Known checks:** Zooniverse Talk **False**. TOI table:
  **0 rows**.
- **(a) Reproduce: exact.** P = 13.7240 d, SDE 11.15, depth 0.942%,
  nominal Rp 5.08 R_earth, duration 5.976 h, 20 sectors,
  186,541 points.
- **(b) Odd/even: substantive alternation → driver kill, LIKELY
  BINARY.** Folded at 27.45 d: odd **0.232%**, even **0.335%** —
  real eclipses at both parities, 31% apart (not a ratio-rule
  misfire; these folds carry 25–36% of the BLS depth).
- **(c) Double-period (post-gate): confirms.** Refined 2P =
  **27.4587 d**; eclipse windows **0.883% / 0.639%**; ellipsoidal
  delta **+0.211% at 10.0σ** — just over the pre-set line.
- **(d) Orbit-phase: no pile-up** (35 on-data centres, boundary
  fraction 0.29, R = 0.249) — although the alias sits at ratio
  ~1.002 to the orbit, the test acquits the instrument; this is a
  star whose binary period (~27.46 d ≈ two TESS orbits) parks its
  alias on the resonance, the TIC 177171983 configuration without
  the pile-up.
- **(e) Persistence (post-gate):** 16 usable, **5/16 ≥ 1.5σ**,
  weighted mean +0.023% ± 0.055% — the stamp's 5/16 and 0.02%
  digit for digit (tenth live validation). At the *alias*
  ephemeris the fixed-window mean is ~zero, as expected when only
  one parity's eclipses land on the folded grid; persistence was
  never the instrument for this conviction. Monster sectors 67
  (+8.5% raw), 68 (+9.2%), 97 (+15.4%) — the usual family.
- **Contamination: 0.232** — flagged; an on-target-scale wave
  (0.21%) and 0.88% eclipses argue the binary is the target or a
  close companion regardless.

### The uncapped tiebreaker (all 21 sectors)

Uncapped analyze demotes the alias (top peak 13.9739 d, SDE 7.83);
uncapped persistence at the fixed alias ephemeris is
CONCENTRATED (2/17, weighted mean −0.003%) — the alias train does
not exist as a constant-depth signal on the full baseline, which
is precisely what a half-period alias of a 27.46 d binary should
do. Era split of the alias accounting: cycle-3 ranges −0.223%
(−1.4σ), sectors ≥ 60 +0.023% (0.4σ) — nothing anywhere, as
expected; the conviction lives entirely in the folds.

**Verdict: LIKELY BINARY** — eclipsing binary, true period
≈ **27.46 d**; the sweep's 13.7240 d is the half-period alias.
The shallowest stamp of the sweep hid the patch's fourth binary:
a lesson the stamp audit takes up below (the stamp measures the
alias's persistence, and an alias can be arbitrarily faint while
the binary is arbitrarily real).

Raw record: `vetting_results/276791802.json`; persistence tables
at `vetting_results/276791802_persistence_cap20.json` and
`vetting_results/276791802_persistence_uncapped.json`; run log in
`sweep4_logs/`.

---

# Fold completions — the four self-convicted

The four hits the in-sweep code stamped **fails-persistence —
blend-suspect** were convicted in the log before any human looked.
Per protocol they still received their fold trial (reproduce →
odd/even → double-period at cap 20): stamps are screens, not
verdicts, and the folds are the species court.

## Target 7 of 20 — TIC 277106730 — **LIKELY BINARY**

Sweep hit: **P = 1.7055 d, SDE = 10.4**; stamp **"2/20 sectors —
fails persistence — blend-suspect"**, contamination flag set.
Star: Tmag 13.46, TIC radius 0.492 R_sun, 0.490 M_sun, Teff 3602 K,
129 pc. Position RA 84.21265°, Dec −68.29850° — 0.42° from centre.
IDs: 2MASS 05365103-6817545, Gaia DR3 4657835515069813248.

- **(f)** Zooniverse Talk **False**; TOI table **0 rows**.
- **(a) Reproduce: exact.** P = 1.7055 d, SDE 10.44, depth 0.100%,
  duration 5.976 h, 20 sectors, 45,935 points.
- **(b) Odd/even: present/absent alternation → driver kill,
  LIKELY BINARY.** Odd **+0.017%**, even **−0.012%** — one parity
  dips, the other is flat-to-negative: a single eclipse train at
  twice the sweep period (absolute depths are shallow — the same
  dilution caveat as TIC 177171983's kill, and here stage (c)
  supplies the corroboration that star's wave supplied there).
- **(c) Double-period: an eclipse pair, no wave.** Refined 2P =
  **3.4822 d**; eclipse windows **0.102% / 0.042%** — the deeper
  window at the full BLS depth; quadrature delta +0.012% at 0.8σ
  → no ellipsoidal signal (an EB without a measurable wave at
  this dilution — ordinary).
- **Contamination: 0.109** — just over the flag line. At 0.10%
  observed depth, an on-target EB is implausible (it would eclipse
  far deeper); the host is most likely a neighbour in the
  aperture. The folds cannot centroid it; the planet reading is
  dead either way.

**Reconciliation: the folds AGREE with the stamp's bottom line
and IDENTIFY the object** — an eclipsing binary in the aperture,
true period ≈ **3.48 d**; the sweep's 1.7055 d is (to within the
refinement) its half-period alias.

**Verdict: LIKELY BINARY.**

Raw record: `vetting_results/277106730.json`; run log in
`sweep4_logs/`.

## Target 14 of 20 — TIC 276792620 — **LIKELY BINARY**

Sweep hit: **P = 13.7705 d, SDE = 10.5**; stamp **"5/18 sectors —
fails persistence — blend-suspect"**, contamination flag set.
Star: Tmag 14.29, TIC radius 0.359 R_sun, 0.345 M_sun, Teff 3417 K,
120 pc. Position RA 83.41331°, Dec −67.93693° — 0.60° from centre.
IDs: 2MASS 05333919-6756129, Gaia DR3 4658601256191937664.

- **(f)** Zooniverse Talk **False**; TOI table **0 rows**.
- **(a) Reproduce: exact.** P = 13.7705 d, SDE 10.54, depth
  **4.950%**, nominal Rp 8.74 R_earth, duration 5.976 h, 20 sectors,
  207,631 points.
- **(b) Odd/even: substantive alternation → driver kill, LIKELY
  BINARY.** Odd **0.120%**, even **0.340%** (ratio 0.35).
- **(c) Double-period: likely-binary — the most emphatic fold
  conviction of the project.** Refined 2P = **27.0967 d**; eclipse
  windows **8.487% / 11.734%** — the deepest eclipses yet measured
  in these sweeps — and an ellipsoidal delta of **+3.113% at
  20.2σ**: a severely tidally distorted binary, its out-of-eclipse
  wave alone larger than most hits' entire signals.
- **Contamination: 0.483** — the second-dirtiest aperture of the
  sweep, and irrelevant to the species: an 11.7% eclipse pair with
  a 3.1% tidal wave is the target itself (or a dominant companion),
  not a smear.
- Orbit-phase was not run (fold-completion scope); its 13.7705 d
  alias sits in the orbit band, but the conviction needs nothing
  from that stage.

**Reconciliation: the folds AGREE with the stamp's kill and
IDENTIFY the object.** The stamp failed this star because an
alias-folded EB is not a constant-depth planet train — its stated
job. Underneath the sweep's blandest stamp line sat the patch's
most violent binary.

**Verdict: LIKELY BINARY** — eclipsing binary, true period
≈ **27.10 d**; the sweep's 13.7705 d is the half-period alias.

Raw record: `vetting_results/276792620.json`; run log in
`sweep4_logs/`.

## Target 17 of 20 — TIC 425082819 — **PIPELINE PHANTOM**

Sweep hit: **P = 0.6421 d, SDE = 10.4**; stamp **"0/14 sectors —
fails persistence — blend-suspect"** — total evaporation already in
the sweep — with the contamination flag set. Star: Tmag 14.64, TIC
radius 0.351 R_sun, 0.335 M_sun, Teff 3271 K, 121 pc. Position
RA 83.10856°, Dec −67.90680° — 0.72° from centre. IDs:
2MASS 05322605-6754244, Gaia DR3 4658607647103919872.

- **(f)** Zooniverse Talk **False**; TOI table **0 rows**.
- **(a) Reproduce: exact.** P = 0.6421 d, SDE 10.44, depth 2.637%,
  duration 5.616 h, **14 sectors** (all that exist), 114,553 points.
- **(b) Odd/even: folds go NEGATIVE.** Odd **−0.087%**, even
  **−0.133%** — the folded curve *brightens* at both parities;
  deepest dip 5.0% of the BLS depth → fold evaporation, driver's
  PIPELINE PHANTOM.
- **(c) Double-period: no pair, no wave.** Quadrature delta
  −0.020% at −0.07σ. One fold window at the refined 1.3152 d reads
  1.349% — recorded honestly — but its partner window reads
  0.158%, the parity fold is negative at both parities, and the
  sweep's own per-sector test found **zero** of 14 sectors with a
  positive in-window depth. A lone window that fails the parity
  test is a raw-curve excursion, not an eclipse.
- **Contamination: 0.525** — the dirtiest aperture of the sweep,
  as the HIT line's flag said. But there is no eclipse signal
  anywhere in the aperture, blended or on-target, for the
  contamination to explain (the TIC 299900306 configuration).

**Reconciliation: the folds OVERTURN the stamp's blend reading
and uphold its kill.** Not a neighbour's eclipses leaking in — a
BLS-only signal (2.64% deep on paper!) on 14 sectors of FFI data
that evaporates in every fold and every sector.

**Verdict: PIPELINE PHANTOM.**

Raw record: `vetting_results/425082819.json`; run log in
`sweep4_logs/`.

## Target 19 of 20 — TIC 425082078 — **BLEND-SUSPECT**

Sweep hit: **P = 13.2045 d, SDE = 10.5**; stamp **"2/18 sectors —
fails persistence — blend-suspect"**, contamination flag set.
Star: Tmag 14.87, TIC radius 0.498 R_sun, 0.496 M_sun, Teff 3599 K,
249 pc. Position RA 83.12773°, Dec −68.27610° — 0.75° from centre.
IDs: 2MASS 05323064-6816340, Gaia DR3 4658578132086917632.

- **(f)** Zooniverse Talk **False**; TOI table **0 rows**
  (first-pass query errored; retry returned 0).
- **(a) Reproduce: exact.** P = 13.2045 d, SDE 10.52, depth
  1.855%, nominal Rp 7.43 R_earth, duration 5.976 h, 20 sectors,
  182,166 points.
- **(b) Odd/even: planet-like.** Odd **0.276%**, even **0.331%**
  (ratio 0.83) — consistent parities; no fold kill.
- **(c) Double-period: no wave, and a *matching* pair.**
  Quadrature delta −0.075% at −2.4σ → no ellipsoidal signal. The
  eclipse windows at the refined 26.4516 d read **0.875% /
  0.926%** — equal, as they must be if a single 13.2 d eclipse
  train is folded at twice its period (the same eclipse appears
  in both windows). An equal pair is not an alternation; this
  stage acquits.
- **(e) Persistence, re-derived standalone (the deciding stage):**
  **CONCENTRATED — 2/18 ≥ 1.5σ**, weighted mean **+0.024%**
  against the 1.855% BLS depth, monster sectors **93, 94, 96, 97**
  — the stamp's 2/18 reproduced digit for digit (the eleventh
  live validation of the in-sweep stage, counting this sweep's
  full-house re-derivations).
- **Contamination: 0.326** — a heavily mixed aperture.

**Reconciliation: the stamp is UPHELD in species as well as in
kill — the only one of the four self-convicted whose label
survives intact.** This is the TIC 231096116 configuration from
sweep 2 exactly: every fold check passed, persistence fatal. A
diluted neighbour signal in a 0.326-contaminated aperture, its
depth lurching sector to sector with the monster-era sectors
carrying the raw excursions, is the consistent reading; the folds
judge the *blended* curve and can pass it, which is precisely why
persistence — not the folds — is the load-bearing wall.

**Verdict: BLEND-SUSPECT** — not a planet; a neighbour-driven
false alarm in a crowded aperture.

Raw record: `vetting_results/425082078.json`; persistence table at
`vetting_results/425082078_persistence_cap20.json`; run log in
`sweep4_logs/`.

---

# Patch-level note — the 13.2–14.3 d band, judged

Seven of the eleven hits (13.2045, 13.6750, 13.7240, 13.7705,
14.1724, 14.1895, 14.3145 d) sit in the orbit-adjacent band. The
orbit-phase stage ran at full weight on the five band members that
received the full gauntlet:

| TIC | P (d) | P/orbit | Boundary frac. (chance 0.219) | R | Pile-up? |
|---|---|---|---|---|---|
| 404931136 | 14.1724 | 1.035 | 0.41 | 0.229 | No |
| 404924199 | 14.1895 | 1.036 | 0.39 | 0.200 | No |
| 389564031 | 14.3145 | 1.045 | 0.18 | 0.272 | No |
| 389672553 | 13.6750 | 0.998 | 0.35 | **0.492** | No |
| 276791802 | 13.7240 | 1.002 | 0.29 | 0.249 | No |

(The two fold-completion band members, 276792620 and 425082078,
were not orbit-tested; both were convicted on other stages.)

**Zero pile-ups.** The one elevated reading — TIC 389672553's
R = 0.492 at an exact 1:1 lock — comes with a sub-rule boundary
fraction (0.35), and that star was convicted as an orbit-band
ghost on its uncapped persistence, not on this stage. The census
explains the band without any instrument coupling: **four of the
seven are half-period aliases of the patch's ~26–28.4 d binary
family** (true periods 27.10, 27.46, 28.39, 28.40 d — the same
family sweeps 2 and 3 kept producing at ~25.9–27.5 d), one is a
blend, one a variability case, one the ghost. The band is a
*selection* pile-up — BLS reporting a real, period-clustered EB
population at half period — not a scattered-light artifact. That
is the third patch in a row where the orbit-phase stage acquits
the instrument (after the sweep-1 cluster scare and
TIC 294751586), and the first where the acquittal comes with a
complete alternative explanation in hand.

---

## Sweep 4 — FINAL tally (sweep complete, 2026-11-04)

**20 targets, 11 hits at SDE ≥ 8.5, all 11 hand-vetted:
0 survivors.**

- **6 eclipsing binaries:** TIC 277313805 (true P 1.127 d — the
  SDE 50.8 record-holder, a diluted contact-class wave),
  TIC 277106730 (≈ 3.48 d, in-aperture), TIC 404931136 (28.39 d,
  wave +0.728% @ 20.6σ), TIC 404924199 (28.40 d, wave +0.529%
  @ 34.0σ), TIC 276791802 (27.46 d, wave +0.211% @ 10.0σ),
  TIC 276792620 (27.10 d — eclipses to 11.7%, wave +3.113%
  @ 20.2σ, the most emphatic binary of the project). Four of the
  six are the ~27–28.4 d family whose half-period aliases built
  the patch's 13.2–14.3 d cluster.
- **2 pipeline phantoms:** TIC 389672553 (orbit-locked BLS ghost;
  uncapped persistence +0.012% at 1.7σ over 67 sectors) and
  TIC 425082819 (0/14 in-sweep evaporation upheld; a 2.64%-deep
  paper signal on 14 FFI sectors with no eclipse anywhere).
- **1 blend-suspect:** TIC 425082078 — the sweep's only
  stamp-exact conviction (folds passed, persistence fatal,
  contratio 0.326, monster sectors 93/94/96/97).
- **2 inconclusive — the grey drawer grows:** TIC 389367432
  (era-weighted excess, cycle-3-weighted, cross-stitch depth
  disagreement) and TIC 389564031 (era-spread shallow excess on
  the patch's brightest M dwarf, present in both stitches,
  constant in neither). Both are most consistent with stellar
  variability; neither is a candidate; neither is convictable as
  a pipeline invention.

**Audit of the self-vetting code** (its second unsupervised
sweep): the in-sweep stamps' bottom line — *not a planet* — was
upheld by hand vetting on **all 11 hits**. Species accounting:
the four "fails-persistence — blend-suspect" stamps resolved as
2 EB, 1 phantom, and 1 blend-suspect upheld exactly; the seven
"patchy" stamps resolved as 4 EB, 2 grey-drawer inconclusives and
1 phantom. The standalone persistence module **re-derived the
in-sweep stamp digit for digit on all 8 hits where it was re-run**
(the 3 fold-completion stars' stamps stand as the sweep's own
record). Trust-it-to-kill-not-to-name stands, with two corollaries
this sweep adds:

1. **The stamp grades the alias, not the object.** A patchy stamp
   at a half-period alias can carry an arbitrarily faint mean
   (TIC 276791802: stamp mean 0.02%, binary eclipsing at 0.88%)
   and a fails stamp can hide the deepest binary yet found
   (TIC 276792620). Stamp *strength* must never be read as
   object weakness.
2. **The stamp's significance accounting can break on smooth
   data.** On TIC 389672553 the module's chunk-σ estimator
   collapsed (adjacent sectors at +26σ and −11σ) — the stamp's
   sector *count* reproduced exactly, but its implied
   probabilities on such stars are not to be taken literally.

The hand gauntlet's own mechanical labels also misfired twice and
were reconciled in the open (raw verdicts preserved in every
JSON): the ratio rule's "likely-binary" on two zeros
(TIC 389564031, stage b) and the sub-line ellipsoidal threshold
reading "no signal" over a real 6.7σ wave (TIC 277313805,
stage c).

**Combined four-sweep ledger.** Sweeps 1–3 closed (per
SWEEP3_VETTING_REPORT.md) at **0 survivors / 19 convicted false
alarms (9 eclipsing binaries, 4 blend-suspects, 6 pipeline
phantoms), plus 2 inconclusive**, out of 26 hits (3 of sweep 1's
weakest never vetted; the early reports' class placement of the
sweep-1 BLS-only trio differs between ledgers by two stars, noted
here rather than silently adjusted). Sweep 4 adds 9 convicted
(6 EB, 1 blend, 2 phantoms) and 2 inconclusives: **combined —
0 survivors / 28 convicted false alarms (15 eclipsing binaries,
5 blend-suspects, 8 pipeline phantoms), plus 4 inconclusive
astrophysical cases, out of 37 hits across four patches.**

Sweep 4's patch (RA 85, Dec −68 — 2.4° from the pole, the deepest
water yet) was the richest and the most crowded yet swept: a
55% hit rate, ten of eleven hits in contaminated apertures, and a
yield dominated by a single astrophysical family — the ~27–28 d
eclipsing binaries of the southern CVZ, whose aliases BLS serves
up at ~14 d. Its two grey-drawer cases extend the pattern sweep 3
opened (real, shallow, era-structured variability excesses on
small M dwarfs that no fold can see and no planet can explain).
The survivor count across four patches remains zero — not because
the patches are empty, but because the gauntlet is honest: every
signal that reached it has so far been a binary, a blend, a
ghost, or a star talking to itself.

*Session notes (for the record): this vetting ran through a
degraded-MAST afternoon — the TIC cone query and several lightcurve
searches dropped connections and were healed or re-routed
(per-star query_object harvest for the catalog data); one vetting
chain process died mid-run when a parallel render job exhausted
the VM's memory, and the affected stages were re-run standalone
(the one unrecoverable item, TIC 389564031's uncapped-analyze JSON
save, is documented in that star's JSON with its surviving log
values). All other numbers in this report were re-derived locally
from the same code paths the sweep itself used.*

Per-star records: `vetting_results/{tic}.json` for all 11 hits,
plus `vetting_results/277313805_foldshape.json`, persistence
sidecars (`{tic}_persistence_cap20.json` /
`{tic}_persistence_uncapped.json`) where those stages ran, the
pair analysis at `sweep4_logs/pair_analysis.json`, catalog rows at
`sweep4_logs/catalog_rows.json`, and run logs in `sweep4_logs/`.
