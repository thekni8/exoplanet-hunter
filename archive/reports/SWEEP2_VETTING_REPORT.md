# Sweep-2 Vetting Report — (RA 70, Dec −70) sweep, first 13 targets

**Run:** 2026-11-03/04 (Pingu's server, production `hunter.py` / `api.py` internals,
sector_cap 20, BLS grid 10,000 — identical recipe to Dev's sweep).
**Driver:** `vet_star2.py` (stage-gated gauntlet) + `persistence.py` (sector persistence,
validated against the TIC 374942698 follow-up — see below).
**Per-star raw JSONs:** `vetting_results/<tic>.json`; run logs in `sweep2_logs/`.

## The gauntlet (in order, per star)

(a) analyze reproduce at cap 20 → (b) odd/even fake-check → (c) double-period check →
(d) orbit-phase boundary fraction (eccentric-EB pile-up screen, run only for context on
stars reaching it) → (e) **only if planet-consistent through (c)**: sector-by-sector
persistence (per-sector depths at fixed ephemeris; CONSISTENT = ≥70% of usable sectors
≥1.5σ and χ² constant-depth p > 0.01) + ExoFOP contamination ratio.

**Persistence-method validation:** before use, `persistence.py` was re-run on
TIC 374942698 and reproduced the follow-up's table (11 usable sectors, 4/11 ≥1.5σ,
monster sectors 68/96/97 at raw depths 14.6/18.7/17.2% vs the reference 14.7/18.8/17.5%;
identical per-sector event counts everywhere). Per-sector depths jitter ~0.5% between
detrending runs (same spread the follow-up's own independent cross-check showed), but
verdicts are decisive either way.

**Coordinate note:** positions in this report come from MAST TIC ID-criteria lookups and
were verified against ExoFOP for both pair members. (An initial cone-table row extraction
produced wrong coordinates for these stars and was discarded; the sweep's own TIC-ID-based
downloads were never affected.)

## Results at a glance

| # | TIC | Sweep P / SDE | Verdict | Killed at |
|---|-----|---------------|---------|-----------|
| 1 | 231124169 | 1.4580 d / 24.4 | **LIKELY BINARY** | (c) double-period |
| 2 | 294671352 | 13.1286 d / 14.1 | **LIKELY BINARY** | (b) odd/even |
| 3 | 231096116 | 13.1384 d / 13.1 | **BLEND-SUSPECT** | (e) persistence |
| 4 | 294782870 | 24.5222 d / 13.1 | **LIKELY BINARY** | (b) odd/even |
| 5 | 294671640 | 24.2649 d / 9.9 | **PIPELINE PHANTOM** | (b) fold evaporation |

Known-online check (`is_already_known_online`, Zooniverse Talk search): **False for all 5.**

---

## 1. TIC 231124169 — LIKELY BINARY (killed at stage c)

- **(a) Reproduce: exact.** P 1.45805 d, SDE 24.45, depth 0.208%, Rp 2.19 R⊕,
  20 sectors / 67,262 points. The strongest signal of both sweeps.
- **(b) Odd/even: planet-like** — odd 0.192%, even 0.201%, ratio 0.95. Equal eclipses
  pass this test by construction.
- **(c) Double-period: decisive kill.** Ellipsoidal wave **+0.871% at 92σ** → likely-binary.
  True period **2.91396 d**; at 2P the two eclipses are 0.957% / 0.963% deep — the BLS
  "0.21% planet" was the diluted half-period alias of a twin-star system (the BLS
  duration grid, 5.98 h on a 1.46 d orbit, smears the narrow eclipses).
- Stages (d)/(e) not run — killed at (c).

**Verdict: LIKELY BINARY.** Same failure family as sweep 1's two EBs: the biggest SDE in
the batch is two stars, not a planet.

## 2. TIC 294671352 — LIKELY BINARY (killed at stage b) — pair member A

- **(a) Reproduce: exact.** P 13.12856 d, SDE 14.09, depth 0.847%, Rp 3.72 R⊕,
  20 sectors / 175,850 points.
- **(b) Odd/even: likely-eclipsing-binary.** Folding at 26.25450 d: odd eclipses 0.152%,
  even eclipses 0.105% — alternating depths, the half-period-alias signature. The true
  period is ≈ **26.25 d**; the sweep's 13.1286 d is its half.
- Stages (c)–(e) not run — killed at (b).
- ExoFOP (fetched for the pair check): contamination ratio **0.272** — 27% of the
  aperture light is neighbours (154 TIC targets within 1′). TOIs 0, candidates 0.
  Position (70.69796, −69.55422), Gaia DR3 4655030622248269696 — both match the
  TIC criteria lookup.

**Verdict: LIKELY BINARY** — the star itself is the EB; no external contaminator needed.

## 3. TIC 231096116 — BLEND-SUSPECT (killed at stage e) — pair member B

- **(a) Reproduce: exact.** P 13.13840 d, SDE 13.05, depth 0.586%, Rp 3.26 R⊕,
  20 sectors / 176,132 points.
- **(b) Odd/even: planet-like** — 0.094% / 0.093%, ratio 0.99.
- **(c) Double-period: flat** — ellipsoidal delta −0.029% at −2.0σ → no-ellipsoidal-signal.
- **(d) Orbit-phase: no pile-up** — event-centre boundary fraction 0.29 (chance 0.219),
  circular R 0.381, P/TESS-orbit ratio 0.959. Clean.
- **(e) Persistence: FAIL — CONCENTRATED, and this is where it dies.** 15 usable sectors,
  only **4/15 ≥1.5σ**; per-sector depths scatter from −0.48% (sector 90, at **−8.4σ** —
  an anti-signal) to +3.05%; **weighted-mean depth −0.042% ± 0.029%** — sector-by-sector,
  the "0.586% transit" averages to *zero*. χ² = 147 on 14 dof (p ≈ 3×10⁻²⁴) against a
  constant depth. Raw-data monster sectors: **61 (5.0%), 95 (10.1%), 96 (8.5%)** — a few
  sectors carry episodic deep events that beat against the fold while most sectors show
  nothing. Event-fold median depth 0.114%, 56% of events positive — a shallow residue
  exists, exactly like TIC 374942698's, and is just as unclaimable.
- ExoFOP: contamination ratio **0.186**; TOIs 0, community candidates 0. Position
  (69.20596, −70.15365), Gaia DR3 4655645975075011840 — matches the TIC lookup.

**Verdict: BLEND-SUSPECT.** It passed every fold test and died on the test that killed
374942698: the signal is not in most sectors. With 18.6% contaminating light and raw
monsters in 3 sectors, a blended EB / episodic-artifact origin is the working reading.
Homework if ever revisited: centroid / difference imaging on sectors 95–96. Not a candidate.

## 4. TIC 294782870 — LIKELY BINARY (killed at stage b)

- **(a) Reproduce: exact.** P 24.52220 d, SDE 13.05, depth 0.790%, Rp 3.59 R⊕,
  20 sectors / 178,604 points.
- **(b) Odd/even: likely-eclipsing-binary — present/absent alternation.** Folding at
  49.04 d (2P): odd eclipses 0.038%, even eclipses −0.005%. One parity shows a dip, the
  other shows nothing at all — an eclipse train that only exists on alternate cycles is
  an eclipsing binary read at half its true period. True period ≈ **49.04 d**; the
  sweep's 24.5222 d is its half.
- **Caveat, recorded:** the surviving fold dip (0.038%) is ~20× shallower than the
  pipeline depth (0.790%). Raw folds systematically under-read these stacked, diluted
  signals, so it is the *alternation pattern* that convicts this star, not the fold
  amplitude — the same care taken with every stage-(b) call in this report.
- Stages (c)–(e) not run — killed at (b).

**Verdict: LIKELY BINARY** — a ~49 d eclipsing binary caught at its half-period alias.

## 5. TIC 294671640 — PIPELINE PHANTOM (killed at stage b)

- **(a) Reproduce: exact.** P 24.26493 d, SDE 9.88, depth 0.434%, Rp 3.23 R⊕,
  20 sectors / 177,238 points.
- **(b) Odd/even: the signal evaporates — this is where it dies.** The app's ratio rule
  mechanically returned "likely-eclipsing-binary" (odd −0.001%, even +0.003%, "136%
  apart"), but both parities are noise-level: the raw fold contains **no eclipse at
  either parity** (−0.001% / +0.003% against a 0.434% pipeline depth). A ratio computed
  on two nothings is not an alternation — there is nothing here to alternate.
  Reclassified **PIPELINE PHANTOM** per the sweep-1 definition; the raw app verdict is
  preserved in the JSON (`app_odd_even_verdict_raw`).
- Stages (c)–(e) not run — killed at (b).

**Verdict: PIPELINE PHANTOM.** The flatten/BLS path manufactured a periodic signal the
raw light curve does not contain — the third species of false alarm in this batch, and
the weakest hit of the five (SDE 9.9).

## The 13.13-day pair — cross-check (TIC 294671352 × TIC 231096116)

Two hits in one sweep whose sweep periods agree within 0.01 d (13.1286 vs 13.1384 d),
in a cone holding 472 catalogued variables, demanded a shared-contaminator check before
either verdict could be trusted. It does not survive the geometry:

- **Separation: 47.4 arcmin** (≈135 TESS pixels at 21″/pixel) between the verified
  positions — 294671352 at (70.69796, −69.55422), 231096116 at (69.20596, −70.15365),
  from MAST TIC ID-criteria lookups cross-checked against ExoFOP. Apertures span ~1–2′;
  no object bleeds a coherent signal into both apertures across 47′.
- **Contamination is local, and independent:** ExoFOP ratios 0.272 (294671352) and
  0.186 (231096116) — each aperture is crowded by its *own* neighbours.
- **The VSX midpoint cone was NOT run** — stated plainly: the AAVSO VSX endpoint
  returned HTTP 403 via the page fetcher, and the check was not retried through
  alternate endpoints. The gap is moot rather than material: a midpoint cone would
  sample sky ~23′ from either star, and the separation already excludes a shared
  contaminator on its own.
- **Conclusion: NO common contaminator.** Two independent false alarms whose
  half-period aliases happen to land in the same 0.01 d period bin — one star is itself
  a genuine 26.25 d EB (§2), the other a blend mirage (§3). In a 472-variable cone,
  that coincidence is expected, not suspicious.

## Pattern notes

- **Zero survivors, again.** Across both fully vetted sweeps the ledger stands at
  **0 survivors / 9 false alarms** — 5 binaries, 2 blend-suspects, 2 phantoms — before
  the late hit appended below. Known-online (Zooniverse Talk): False for all 5 here.
- **At sector cap 20, SDE ≥ 8.5 alone no longer means discovery** — sweep 1's lesson,
  now with a second sweep of evidence. The gauntlet is the discovery instrument; the
  SDE is only the net. Raw-fold depths ran 2–20× shallower than BLS depths across this
  batch (window dilution), so early stages judge fold *patterns*, not amplitudes — and
  for anything that survives the folds, sector persistence is the decisive stage:
  231096116 passed every fold check and still averaged −0.04% sector-by-sector.
- **Persistence + contamination screening belong inside the sweep — now BUILT.**
  Pushed 2026-11-04 (commit `e8d18535`): the sweep reads TIC contratio at screen time
  (hits with contratio ≥ 0.10 are stamped "high-contamination — blend risk") and
  persistence-tests every hit in the net, with the verdict in the live log as a `↳`
  line. Acceptance evidence: the integrated stage re-convicted TIC 231096116 standalone
  (4/15 sectors, weighted-mean depth −0.042%) — from the next sweep onward, mirages
  die where they're caught instead of in a report written the following night.

---

## Late hit — Target 16 of 25 — TIC 231092486 — PIPELINE PHANTOM (killed at stage b)

*Appended 2026-11-04 ~03:20 IST. This hit surfaced in Dev's still-running sweep after
the first-13 batch above was vetted; Dev passed the HIT line over and it was run through
the identical gauntlet (`vet_star2.py`, cap 20, BLS 10,000) on Pingu's server.
Sweep values: P = 12.7512 d, SDE = 14.0, R* = 0.50 R☉, Tmag = 14.6, 22 sectors
available. Raw JSON: `vetting_results/231092486.json`; log: `sweep2_logs/231092486.log`.*

- **Known-online: False** (Zooniverse Talk, same check as the batch). NASA Exoplanet
  Archive TOI table (TAP, tid = 231092486): **0 rows**.
- **(a) Reproduce: exact.** P 12.75123 d, SDE 13.95, depth 0.749%, Rp 4.72 R⊕,
  duration 5.18 h, 20 sectors / 179,516 points. The pipeline signal is really in the
  processed light curve — the question is what it is.
- **(b) Odd/even: the signal evaporates — this is where it dies.** Folding at
  2P = 25.50245 d: odd **+0.001%**, even **+0.010%**. The app's ratio rule mechanically
  returned "likely-eclipsing-binary" (ratio 0.126, "87% apart"), but both parities are
  noise-level: the deepest fold dip is **1.3% of the 0.749% BLS depth**, far under the
  25% evaporation threshold. There is no eclipse at either parity, so there is nothing
  to alternate — the exact pattern of TIC 294671640 in the batch above. Contrast with a
  genuine stage-(b) EB from this same batch (TIC 294671352: folds 0.152% / 0.105%,
  ~12–18% of its BLS depth). Raw app verdict preserved in the JSON
  (`app_odd_even_verdict_raw`); final classification follows the sweep-1 definition.
- Stages (c)–(e) not run — stage-gate kill at (b), same as every stage-(b) kill in
  this report.
- **Contamination (context): 0.650** — TIC contratio (MAST criteria lookup; the value
  ExoFOP displays). 65% of the aperture light belongs to neighbours — by far the most
  contaminated hit of this sweep (batch range 0.186–0.272). Position
  (69.08032, −69.31916), Gaia DR3 4655843367495154432; TIC stellar: Tmag 14.64,
  0.496 R☉, 0.494 M☉, Teff 3601 K.

**Verdict: PIPELINE PHANTOM.** A BLS-only signal at SDE ~14 that leaves no eclipse in
the raw fold at either parity — the flatten/BLS path manufactured it, in the most
crowded aperture the sweep has produced so far. Not a binary (no eclipses to
alternate), not a blend-suspect by this report's definition (no persistence stage was
reached and no sector monsters were measured), and not a candidate.

---

## Late hit — Target 18 of 25 — TIC 294626348 — PIPELINE PHANTOM (killed at stage b)

*Appended 2026-11-04 ~03:35 IST. Second late hit from Dev's still-running sweep,
passed over as a bare HIT line and run through the identical gauntlet
(`vet_star2.py`, cap 20, BLS 10,000) on Pingu's server. Sweep values: P = 1.8084 d,
SDE = 11.3, R* = 0.48 R☉, Tmag = 12.6, 85 sectors available (20 used). Raw JSON:
`vetting_results/294626348.json`; log: `sweep2_logs/294626348.log`.*

- **Known-online: False** (Zooniverse Talk, same check as the batch). NASA Exoplanet
  Archive TOI table (TAP, tid = 294626348): **0 rows**.
- **(a) Reproduce: exact.** P 1.80843 d, SDE 11.35, depth **0.048%**, Rp **1.14 R⊕**,
  duration 0.72 h, 20 sectors / 188,288 points. On paper this was the dream profile —
  an Earth-sized dip on a 1.8-day orbit around a small dwarf, precisely the class
  this hunt exists for. Which is exactly why the fold checks matter.
- **(b) Odd/even: total evaporation — this is where it dies.** Folding at
  2P = 3.61686 d: odd **0.000%**, even **0.000%**. No dip could be measured at either
  expected position; the deepest fold dip is **0% of the 0.048% BLS depth** — the
  limiting case of the gauntlet's evaporation rule (deepest fold dip < 25% of BLS
  depth → phantom). The app's own verdict is an honest "inconclusive"; there is
  simply nothing there to judge. Same species as the sweep-1 BLS-only signals
  (TIC 41083982, TIC 150066703): present in the processed curve, absent in the raw
  fold.
- Stages (c)–(e) not run — stage-gate kill at (b), same as every stage-(b) kill in
  this report.
- **Contamination (context): 0.132** — TIC contratio (MAST criteria lookup; the
  value ExoFOP displays). Above the 0.10 flag line the new in-sweep screening
  stamps, but modest — well under this sweep's blend-driven hits (0.186–0.650).
  This phantom needed no crowded aperture and no sector monsters: ~190k stacked
  points and the flatten/BLS path were enough to manufacture an Earth-sized dip
  out of correlated noise. Position (70.45582, −70.75017), Gaia DR3
  4654862779210025728; TIC stellar: Tmag 12.62, 0.476 R☉, 0.474 M☉, Teff 3678 K.

**Verdict: PIPELINE PHANTOM.** An SDE-11.4 signal claiming a 1.14 R⊕ planet that
leaves literally zero dip in the raw fold at either parity — and by far the
shallowest hit of this sweep (0.048% vs 0.43–0.79% for its siblings). The clearest
proof yet that at cap 20 with ~190k points, the SDE ≥ 8.5 bar can be crossed by
pure pipeline weather even on a comparatively clean star.

---

## Late hit — Target 19–25 of 25 — TIC 231079765 — LIKELY BINARY (killed at stage b)

*Appended 2026-11-04 ~03:57 IST. Third late hit from Dev's still-running sweep,
passed over as a bare HIT line (target number within 19–25 not specified) and run
through the identical gauntlet (`vet_star2.py`, cap 20, BLS 10,000) on Pingu's
server. Sweep values: P = 13.1261 d, SDE = 9.8, 21 sectors available (20 used).
Raw JSON: `vetting_results/231079765.json`; log: `sweep2_logs/231079765.log`.
This is the **third ~13.13 d hit in this patch** (after TIC 294671352, §2, and
TIC 231096116, §3), so it carries a dedicated geometry check, below.*

- **Known-online: False** (Zooniverse Talk, same check as the batch). NASA
  Exoplanet Archive TOI table (TAP, tid = 231079765): **0 rows**.
- **(a) Reproduce: exact.** P 13.12611 d, SDE 9.76, depth 1.259%, Rp 4.16 R⊕
  (at the TIC radius 0.335 R☉), duration 5.98 h, 20 sectors / 187,750 points.
- **(b) Odd/even: likely-eclipsing-binary — this is where it dies.** The focused
  scan refined the period to 13.12480 d and folded at **26.24960 d**: odd
  eclipses **0.0738%**, even eclipses **0.0275%** — 63% apart, ratio 0.37.
  Alternating eclipse depths at twice the sweep period: the star is itself an
  eclipsing binary with true period ≈ **26.25 d**, and the sweep's 13.1261 d is
  its half-period alias — the same signature, and nearly the same true period,
  as TIC 294671352 in §2 (26.25450 d). Caveat, same as §4: the fold depths are
  ~17–46× shallower than the 1.259% BLS depth (the batch's usual raw-fold
  dilution), so it is the *alternation pattern* that convicts, not the fold
  amplitude.
- Stages (c)–(e) not run — stage-gate kill at (b), same as every stage-(b)
  kill in this report.
- **Contamination (context): 0.175** — TIC contratio (MAST criteria lookup; the
  value ExoFOP displays). Above the 0.10 in-sweep flag line, but unremarkable
  for this patch (batch range 0.132–0.650) and not the kill mechanism: the
  eclipses are in this star's own fold. Position (67.96483, −69.53040), Gaia
  DR3 4655826054468446848; TIC stellar: Tmag 14.50, 0.335 R☉, 0.317 M☉,
  Teff 3457 K.

**Special check — is this a second blend victim of the §2 EB? No, on geometry
alone.** Verified positions (MAST TIC ID-criteria lookups; pair members from
`sweep2_coords.json`): this star sits **57.3′ from TIC 294671352** (the genuine
26.25 d EB) and **45.4′ from TIC 231096116** (the blend mirage) — ≈163 and
≈129 TESS pixels respectively, against apertures of ~1–2′. Both separations are
far outside the ~5′ trigger, so the conditional fold test (this star's data at
the EB's 26.25 d ephemeris) was not run: no object can bleed a coherent signal
into an aperture 57′ away, and stage (b) had already folded this star's own
data at 26.24960 d and found its *own* alternating eclipses. What remains is a
coincidence worth one sentence: three hits in one cone alias into the same
0.01 d bin at ~13.13 d, with three independent causes — a genuine EB (§2), a
blend mirage (§3), and now a second, unrelated EB whose true period (26.2496 d)
matches the first EB's (26.2545 d) to within 0.005 d. In a cone holding 472
catalogued variables, that is expected, not suspicious — the same conclusion
the pair cross-check reached, now with a third member.

**Verdict: LIKELY BINARY.** A ~26.25 d eclipsing binary caught at its
half-period alias — the third ~13.13 d false alarm in this patch, and the
second genuine EB hiding in that bin.

---

## Late hit — TIC 294665246 — BLEND-SUSPECT (killed at stage e)

*Appended 2026-11-04 ~04:25 IST. Fourth late hit from Dev's still-running sweep,
passed over as a HIT line and run through the identical gauntlet (`vet_star2.py`,
cap 20, BLS 10,000) on Pingu's server. Sweep values: P = 13.8906 d, SDE = 9.2,
20 sectors available (20 used). Raw JSON: `vetting_results/294665246.json`;
log: `sweep2_logs/294665246.log`. The second hit of this sweep to pass every
fold check — and the second to die on persistence.*

- **Known-online: False** (Zooniverse Talk, same check as the batch). NASA
  Exoplanet Archive TOI table (TAP, tid = 294665246): **0 rows**.
- **(a) Reproduce: exact.** P 13.89059 d, SDE 9.16, depth 1.297%, Rp 5.47 R⊕,
  duration 5.98 h, 20 sectors / 208,530 points.
- **(b) Odd/even: planet-like.** A focused scan refined the period to
  13.98366 d; odd transits 0.385%, even transits 0.362%, ratio 0.94 — equal
  depths at both parities.
- **(c) Double-period: no-ellipsoidal-signal.** At 2P (refined 27.96321 d) the
  two eclipses measure 0.451% / 0.399% and the out-of-eclipse quadrature delta
  is **+0.191% ± 0.018% (10.9σ)** — a hair *under* the pre-set +0.2%
  likely-binary line, so the stage passed it as planet-consistent. Recorded
  as-is, not relitigated: the kill below stands independently of this stage.
- **(d) Orbit-phase: no pile-up.** 39 on-data event centres; fraction within
  1.5 d of an orbit boundary 0.231 (chance 0.219), circular R 0.329,
  P/TESS-orbit ratio 1.014. Clean.
- **(e) Persistence: FAIL — CONCENTRATED, and this is where it dies.** 18 usable
  sectors, only **3/18 ≥1.5σ** (17%, against the ≤30% CONCENTRATED bar);
  **weighted-mean depth +0.034% ± 0.029%** against the 1.297% BLS depth — the
  "transit" averages to ~zero sector-by-sector, 38× shallower than the pipeline
  claims. χ² = 50.1 on 17 dof (p ≈ 4×10⁻⁵) against a constant depth. The three
  positive sectors are carried by episodic events: **sectors 95, 96, 97, 98 —
  four consecutive sectors — hold raw fold depths of +14.3% / +19.8% / +11.8% /
  +14.5%** (sector 96 was not formally usable — no fully-covered event — but
  carries the largest raw depth of the set), and sector 61 adds +2.24% at
  +4.9σ. Event-fold median depth +0.026%, 67% of 36 fully-covered events
  positive — the same shallow ~0.03% residue class as TIC 374942698 and
  TIC 231096116, and just as unclaimable.
- **Contamination: 0.061** — TIC contratio (MAST criteria lookup; the value
  ExoFOP displays). **Below** the 0.10 in-sweep flag line — the cleanest
  aperture of any hit in this sweep, and the one caveat this star adds to the
  batch: the static contamination ratio did *not* warn here. Whatever produced
  the sector 95–98 monsters is episodic, not a steady neighbour glow, and only
  the persistence stage could see it. Position (70.44059, −69.15263), Gaia DR3
  4656166490753685120; TIC stellar: Tmag 14.30, 0.442 R☉, 0.438 M☉, Teff 3405 K.

**Verdict: BLEND-SUSPECT.** It passed reproduction, odd/even, double-period
and orbit-phase, then failed persistence exactly as TIC 231096116 did —
signal concentrated in a run of monster sectors (95–98, plus 61) while the
remaining sectors average to zero. The 374942698 pattern for the third time.
Homework if ever revisited: centroid / difference imaging on sectors 95–98.
Not a candidate.

---

## Late hit — Target 24 of 25 — TIC 231077422 — PIPELINE PHANTOM (killed at stage b)

*Appended 2026-11-04 ~05:10 IST. One of the final two HIT lines from Dev's
now-complete sweep, passed over after his own checks for independent
confirmation, and run through the identical gauntlet (`vet_star2.py`, cap 20,
BLS 10,000) on Pingu's server. Sweep values: P = 1.8819 d, SDE = 13.3,
R* = 0.39 R☉, Tmag = 13.1, 96 sectors available (20 used). Raw JSON:
`vetting_results/231077422.json`; log: `sweep2_logs/231077422.log`.*

- **Known-online: False** (Zooniverse Talk, same check as the batch). NASA
  Exoplanet Archive TOI table (TAP, tid = 231077422): **0 rows**.
- **(a) Reproduce: exact.** P 1.88194 d, SDE 13.27, depth 0.049%, Rp 0.94 R⊕,
  duration 0.72 h, 20 sectors / 316,288 points. On paper the sweep's second
  Earth-costume: a sub-Earth-radius dip in the same depth class as
  TIC 294626348 (0.048%).
- **(b) Odd/even: the fold evaporated — this is where it dies.** The app's
  ratio rule mechanically labelled it "likely-eclipsing-binary," but the
  measured parities are odd **+0.001%** and even **−0.007%** — the even
  window is a *brightening*, not an eclipse. There is no dip at either
  parity: the deepest fold feature is 13.5% of the BLS depth by the
  max-abs convention (the only true dip, odd parity, is 1.6%), far under
  the 25% evaporation line. With no eclipses present there is nothing to
  alternate, so the raw app verdict is preserved in the JSON
  (`app_odd_even_verdict_raw`) and the star is classified **PIPELINE
  PHANTOM** per the sweep-1 definition — the TIC 294671640 precedent,
  exactly. Stages (c)–(e) not run (stage-gate kill), consistent with
  every stage-(b) kill in this report.
- **Contamination: 0.013** — TIC contratio (MAST criteria lookup; the value
  ExoFOP displays). **The cleanest aperture of all 11 hits in this
  sweep.** Like TIC 294626348, this phantom needed no crowded field:
  316k stacked points and the flatten/BLS path alone manufactured a
  sub-Earth dip out of correlated weather. Position (67.71937,
  −70.41886), Gaia DR3 4655668034027799040; TIC stellar: Tmag 13.06,
  0.388 R☉, 0.378 M☉, Teff 3398 K.

**Verdict: PIPELINE PHANTOM.** An exact reproduction, an evaporated fold,
and nothing underneath — the shallow-costume species for the second time
in this sweep.

---

## Late hit — Target 25 of 25 — TIC 294751586 — BLEND-SUSPECT (killed at stage e)

*Appended 2026-11-04 ~05:10 IST. The final target of the sweep and its
second-strongest hit. Because its period sits beside the 13.7 d TESS-orbit
band, stage (d) is given full weight below. Run through the identical
gauntlet (`vet_star2.py`, cap 20, BLS 10,000) on Pingu's server. Sweep
values: P = 13.6137 d, SDE = 17.3, R* = 0.40 R☉, Tmag = 14.1, 21 sectors
available (20 used). Raw JSON: `vetting_results/294751586.json`; log:
`sweep2_logs/294751586.log`. The third hit of this sweep to pass every
fold check — and the third to die on persistence.*

- **Known-online: False** (Zooniverse Talk, same check as the batch). NASA
  Exoplanet Archive TOI table (TAP, tid = 294751586): **0 rows**.
- **(a) Reproduce: exact.** P 13.61371 d, SDE 17.29, depth 0.768%,
  Rp 3.82 R⊕, duration 5.98 h, 20 sectors / 191,857 points.
- **(b) Odd/even: planet-like.** Odd transits 0.110%, even transits
  0.115%, ratio 0.95 — equal depths at both parities (fold depths ~7×
  below the BLS depth, the batch's usual window dilution).
- **(c) Double-period: no-ellipsoidal-signal.** Quadrature delta
  +0.064% ± 0.011% (5.8σ), under the +0.2% likely-binary line. One honest
  wrinkle, recorded as-is: the two eclipse windows at 2P are unequal
  (0.335% vs 0.051%). The stage passed the star on its pre-set rule; the
  kill at (e) stands independently of it.
- **(d) Orbit-phase: NO pile-up — and this stage earns its keep here.**
  The candidate period's ratio to the TESS orbit is **0.9937**: within
  0.6% of the spacecraft's own 13.7 d cycle, the one configuration in
  which a scattered-light artifact could stay phase-locked across
  sectors, and in which an honest signal's centres drift only slowly.
  If these dips were downlink-edge systematics, their centres would hug
  the orbit boundary. They do not: **37 on-data centres, fraction within
  1.5 d of a boundary 0.216 against 0.219 expected by chance — exactly
  chance** — with circular R 0.315, under the 0.4 pile-up line; all 135
  centres agree (0.237 vs 0.219, R 0.176). Stated plainly: the
  orbit-phase test *exonerates the instrument* for this star — the
  13.7 d adjacency is a coincidence of the period, not the cause of the
  signal. The same verdict this stage returned for sweep 1's whole
  13.1–14.1 d cluster. What convicts this star is not where its period
  sits, but where its depth lives.
- **(e) Persistence: FAIL — and this is where it dies.** 17 usable
  sectors, **6/17 ≥1.5σ (35%** — MIXED by the fraction rule, just over
  the CONCENTRATED bar); **weighted-mean depth +0.071% ± 0.029%** against
  the 0.768% BLS depth, ~11× shallower; **χ² = 291.8 on 16 dof
  (p ≈ 1.3×10⁻⁵²)** against a constant depth — this "transit" is never
  the same depth twice. The depth it does have is concentrated in the
  monster era: **sectors 94, 96, 97 carry raw fold depths of +7.9% /
  +9.0% / +8.5%** (flattened 6.3% / 3.6% / 3.2%), while the six genuinely
  positive sectors (39, 63, 65, 87, 90, and 97 itself) sit at
  0.35–0.87%. Event-fold median depth +0.247%, 72% of 32 fully-covered
  events positive — the familiar shallow-residue class of TIC 374942698
  and TIC 294665246: something weak may genuinely recur here, but the
  headline 0.768% / 3.82 R⊕ characterization is monster-carried and
  unclaimable. Homework if ever revisited: centroid / difference
  imaging on sectors 94–97.
- **Contamination: 0.082** — TIC contratio (MAST criteria lookup; the
  value ExoFOP displays). Below the 0.10 in-sweep flag line, so once
  again (cf. TIC 294665246 at 0.061) the static ratio is not what caught
  it: persistence is the load-bearing wall of this gauntlet, and it has
  now convicted three of the sweep's hits (231096116, 294665246, this
  one) that no fold check could. Position (71.16031, −69.17338), Gaia
  DR3 4655418376192486528; TIC stellar: Tmag 14.06, 0.396 R☉, 0.387 M☉,
  Teff 3543 K.

**Verdict: BLEND-SUSPECT.** The sweep's second-strongest hit passed
reproduction, odd/even, double-period, and a full-weight orbit-phase
examination that cleared the spacecraft — then failed persistence, its
depth concentrated in the same sector 94–98 monster era that produced
both earlier mirages. The 374942698 pattern for the fourth time.

---

## Sweep 2 — FINAL tally (sweep complete, 2026-11-04)

**25 targets, 11 hits at SDE ≥ 8.5, all 11 vetted through the full
gauntlet: 0 survivors.**

- **4 eclipsing binaries:** TIC 231124169 (true P 2.914 d), TIC 294671352
  (26.25 d), TIC 294782870 (~49 d), TIC 231079765 (26.25 d)
- **4 pipeline phantoms:** TIC 294671640, TIC 231092486, TIC 294626348,
  TIC 231077422
- **3 blend-suspects:** TIC 231096116, TIC 294665246, TIC 294751586 —
  every one convicted by sector persistence alone

Running ledger for fully vetted hits across **both** sweeps:
**0 survivors / 15 false alarms** (6 eclipsing binaries, 4
blend-suspects, 5 pipeline phantoms).

The patch itself remains what PATCH_STUDY_70_-70.md measured —
observed-but-unexamined at this layer (0 of 32 screened stars in the
TOI, confirmed-planet, or VSX catalogues). This sweep converted 25 of
those 32 from *unknown* to *measured across the transiting slice and
ruled out at SDE ≥ 8.5 sensitivity*; the 7 screened stars behind the
Max Stars cap were never run. And the instrument that starts the next
patch is not the one that started this one: persistence + contamination
screening now fire inside the sweep itself (commit `e8d18535`), and
every odd/even verdict now carries its raw-fold exhibit (commit
`08f427d8`) — both built from this sweep's own false alarms.
