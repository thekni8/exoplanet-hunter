# Sweep Vetting Report — CVZ Super-Earth Sweep Hits

**Sweep:** RA 90.22, Dec −65.39, cone 1.0°, R\* 0.2–0.5 R☉, Tmag 11.5–15,
sector cap 20, BLS 10,000 grid points → 9 hits / 20 stars.
**Vetted here:** the 6 requested hits (5 in the 13.1–14.1 d period cluster + the
9.65 d control). All tests run through the app's own production code
(`hunter.analyze_target_json`, `odd_even_test_json`, `double_period_test_json`,
`_fetch_stitched`) at sector cap 20, matching the sweep. Per-star raw numbers:
`vetting_results/<tic>.json`; driver: `vet_star.py`.

**Methods / caveats (read once, applies to every star below)**

- (a) "Reproduced" = re-analyze returns SDE ≥ 8.5 at the sweep period
  (within 2%, or its half/double). All 6 reproduced at the *identical* period.
- (b)/(c) are the app's own fake-checks at the recovered period.
- (d) Orbit-phase test: transit centers from the (a) ephemeris were placed on
  the TESS 13.7 d orbit cycle, phase = (t − segment start) mod 13.7, with
  segments split at data gaps > 0.5 d (so each segment starts at a data-resume
  point — a sector start or just after a downlink gap). Only centers that
  actually fall on data (±½ duration) are scored ("on-data"). The
  scattered-light danger zone is within 1.5 d of an orbit boundary (just after
  a resume or just before the next gap): expected fraction by chance =
  3.0/13.7 = **0.219**. R = circular concentration of the phases (0 = spread
  out, 1 = all at one phase).
- The app's raw-fold checks (odd/even, double-period) consistently measure
  *shallower* dips than the flattened-BLS depth from (a) — by ~2–7× across
  these stars (window dilution in the fold statistics). Their verdicts rest
  on depth *ratios* and out-of-eclipse *shape*, which is what they're for;
  absolute (a)-vs-(b)/(c) depth disagreement is noted per star but is not by
  itself disqualifying.
- (e) "Known" = the app's Zooniverse Planet Hunters Talk search
  (`is_already_known_online`, fail-open, 5 s timeout). VSX was **not run**:
  there is no VSX helper in the codebase and it needs a browser session.
- BLS duration came out at 5.98 h for four of the six stars — the pipeline's
  duration grid quantizes coarsely at these periods; treat durations as rough.

---

## Summary table

| TIC | P (d) | SDE | Depth (BLS) | Odd/Even | Double-period Δ | Orbit-phase frac@boundary (chance 0.219) | Verdict |
|---|---|---|---|---|---|---|---|
| 374942698 | 13.7509 | 14.2 | 1.53% | planet-like | +0.11% @ 4.5σ, flat | 0.14 (n=29) | **SURVIVES** |
| 41083982 | 13.1261 | 12.1 | 0.33% | inconclusive (no dip measured) | +0.01% @ 1.3σ, flat | 0.24 (n=25) | **INCONCLUSIVE** |
| 149932244 | 13.6039 | 12.0 | 1.25% | planet-like | −0.53% @ −18σ (quadrature dip) | 0.14 (n=28) | **INCONCLUSIVE** |
| 149975388 | 14.0768 | 9.8 | 5.43% | planet-like | +0.53% @ 17σ → binary | 0.29 (n=34) | **LIKELY BINARY** |
| 150066703 | 9.6541 | 10.4 | 0.31% | "likely-EB" (depths ≈ 0) | −0.01% @ −1.7σ, flat | 0.20 (n=45) | **INCONCLUSIVE** |
| 149914431 | 13.7264 | 10.0 | 1.84% | likely-EB (31% apart) | +0.58% @ 23σ → binary | **0.66 (n=32)** | **LIKELY BINARY** (phase pile-up flagged) |

None of the six is known on Zooniverse Talk ((e) = False for all six).

---

## 1. TIC 374942698 — P 13.7509 d, SDE 14.2, R\* 0.48 — **SURVIVES**

- **(a) Analyze:** reproduced exactly — P = 13.7509 d, SDE = 14.21,
  depth = 1.53%, Rp = 6.47 R⊕, duration 5.98 h, 16 sectors, 155,406 points.
- **(b) Odd/even:** **planet-like** — odd 0.352% vs even 0.365%, ratio 0.96
  ("within 4% of each other").
- **(c) Double-period:** **no-ellipsoidal-signal** — quadrature wave
  +0.114% ± 0.025% (4.5σ), below the app's binary threshold; out-of-eclipse
  light essentially flat. (The 2P refinement wandered to 28.01 d; 2P-fold
  eclipse depths 0.93% / 0.28%.)
- **(d) Orbit-phase:** 29 on-data centers spread over phases 0.16–11.82 d.
  Fraction within 1.5 d of an orbit boundary = **0.14**, *below* the 0.219
  chance level; fraction within 1.5 d after a segment start = 0.14;
  R = 0.37 (mild, driven by a loose group near 10.6–11.8 d, far from the
  danger zone). **No data-resume pile-up.**
- **(e)** Not known on Zooniverse Talk. VSX not run.
- **Verdict: SURVIVES (planet-consistent so far).** The strongest hit is also
  the cleanest: equal odd/even dips, flat out-of-eclipse light, transit
  centers indifferent to the orbit cycle. Caveats: P/orbit = 1.0037 is
  uncomfortably close to the TESS orbit on its face, and the (b)/(c) fold
  depths (~0.35%) are ~4× shallower than the BLS depth — the usual dilution
  caveat above. This is the one hit worth real follow-up (sector-by-sector
  check, then a CTOI-style report if it holds).

## 2. TIC 41083982 — P 13.1261 d, SDE 12.1, R\* 0.37 — **INCONCLUSIVE**

- **(a) Analyze:** reproduced exactly — P = 13.1261 d, SDE = 12.14,
  depth = 0.329%, Rp = 2.32 R⊕, duration 1.94 h, 20 sectors, 138,410 points.
- **(b) Odd/even:** **inconclusive** — the check measured *no dip at all* at
  either expected position (odd 0.000%, even 0.000%).
- **(c) Double-period:** no-ellipsoidal-signal — delta +0.009% @ 1.3σ, flat;
  but the 2P-fold eclipse depths are only 0.039% / 0.020%, ~10× shallower
  than the BLS depth.
- **(d) Orbit-phase:** 25 on-data centers spread over the full cycle
  (0.03–13.16 d); frac@boundary = 0.24 ≈ chance (0.219); R = 0.17.
  **No pile-up** — and at P/orbit = 0.958 this star is only a loose member
  of the "cluster" anyway.
- **(e)** Not known. VSX not run.
- **Verdict: INCONCLUSIVE.** The production BLS path shouts (SDE 12.1) but
  both independent fold checks find essentially nothing at the ephemeris —
  the signal lives in the detrended representation, not in measurable raw
  dips. No binary signature and no instrumental phase signature either.
  Not promotable; would need a by-eye fold inspection before any claim.

## 3. TIC 149932244 — P 13.6039 d, SDE 12.0, R\* 0.43 — **INCONCLUSIVE**

- **(a) Analyze:** reproduced exactly — P = 13.6039 d, SDE = 11.99,
  depth = 1.254%, Rp = 5.25 R⊕, duration 5.98 h, 15 sectors, 146,986 points.
- **(b) Odd/even:** **planet-like** — odd 0.077% vs even 0.068%, ratio 0.89.
- **(c) Double-period:** **inconclusive** — the quadratures *dip* by
  −0.53% at −18σ at the 27.21 d fold (2P-fold eclipse depths 0.56% / 0.50%,
  near-equal). The app's own text: starspots or leftover instrument wiggles
  can do this; the check cannot judge. Either way there is real, strong
  out-of-eclipse structure in the raw light curve.
- **(d) Orbit-phase:** 28 on-data centers; frac@boundary = **0.14** (below
  chance); R = 0.14 — the *least* concentrated of the six. Centers group
  loosely near phases 4.2–5.5 and 10.3–12.0 d, nowhere near the resume/gap
  zones. **No instrumental signature** — notable, since at P/orbit = 0.993
  this is the cluster member closest to the orbit period after 149914431.
- **(e)** Not known. VSX not run.
- **Verdict: INCONCLUSIVE.** Passes the planet tests that could judge it
  (equal odd/even dips, clean orbit-phase), but the −0.53% @ 18σ quadrature
  dip means the star/system has significant unexplained variability at
  twice the candidate period. Not a binary verdict (the wave has the wrong
  sign for ellipsoidal), not clean enough to survive.

## 4. TIC 149975388 — P 14.0768 d, SDE 9.8, R\* 0.41 — **LIKELY BINARY**

- **(a) Analyze:** reproduced exactly — P = 14.0768 d, SDE = 9.80,
  depth = **5.43%**, formal Rp = 10.43 R⊕ (a planet interpretation of an
  eclipse depth), duration 5.98 h, 16 sectors, 163,181 points.
- **(b) Odd/even:** planet-like (odd 0.792% vs even 0.700%, ratio 0.88) —
  at the *half* period, alternating primary/secondary eclipses of similar
  windowed depth can pass this check; the double-period test is the one
  that sees the full picture here.
- **(c) Double-period:** **likely-binary** — ellipsoidal wave
  **+0.53% at 17σ**; true period 2P = 28.38 d; eclipse depths at 2P
  1.54% / 0.86%. A planet cannot raise an ellipsoidal wave; two stars can.
- **(d) Orbit-phase:** 34 on-data centers; frac@boundary = 0.29 — modestly
  above chance (0.219) but with P/orbit = 1.0275 the centers march +0.38 d
  per orbit and cannot stay in any phase window; the mild early-phase
  weighting tracks which sectors hold data, not a resume-locked artifact.
- **(e)** Not known. VSX not run.
- **Verdict: LIKELY BINARY.** An eclipsing binary at 28.38 d whose
  half-period alias (14.08 d) is what the sweep caught. The 5.4% BLS depth
  was the tell the sweep couldn't see; the ellipsoidal wave settles it.

## 5. TIC 150066703 — P 9.6541 d, SDE 10.4, R\* 0.28 — **INCONCLUSIVE** (the control)

- **(a) Analyze:** reproduced exactly — P = 9.6541 d, SDE = 10.42,
  depth = 0.305%, Rp = 1.69 R⊕, duration 0.72 h, 20 sectors, 63,179 points.
- **(b) Odd/even:** app verdict **likely-eclipsing-binary** — but read the
  numbers: odd −0.004% vs even +0.009%. Both "depths" are zero within
  noise (≈30× shallower than the BLS claim). The verdict is the app's
  heuristic firing on a ratio of two nothings; there are no measurable
  eclipses in this fold to be unequal.
- **(c) Double-period:** no-ellipsoidal-signal — delta −0.012% @ −1.7σ;
  2P-fold eclipse depths 0.007% / 0.011% — again, nothing there.
- **(d) Orbit-phase:** 45 on-data centers (the most of any star) spread
  across the whole cycle; frac@boundary = 0.20 ≈ chance; R = 0.20.
  P/orbit = 0.70 — this period has nothing to do with the TESS orbit.
- **(e)** Not known. VSX not run.
- **Verdict: INCONCLUSIVE.** The control star's lesson cuts the other way
  from the cluster hypothesis: here is an SDE 10.4 "hit" at a period with
  no relation to 13.7 d whose signal *also* evaporates in both raw-fold
  checks. Whatever inflates BLS SDE on these faint multi-sector light
  curves, it is not specific to the orbit period. Not a planet candidate
  on present evidence; not classifiable as a binary either (no eclipses
  measurable). A flattening/periodogram artifact of low-level noise is
  the leading suspicion, unproven.

## 6. TIC 149914431 — P 13.7264 d, SDE 10.0, R\* 0.50 — **LIKELY BINARY** (orbit-phase pile-up flagged)

- **(a) Analyze:** reproduced exactly — P = 13.7264 d, SDE = 9.96,
  depth = 1.84%, Rp = 7.40 R⊕, duration 5.98 h, 17 sectors, 175,686 points.
  P/orbit = **1.0019** — the closest to 13.7 d of the entire sweep.
- **(b) Odd/even:** **likely-eclipsing-binary** — odd 0.379% vs even 0.262%,
  31% apart: alternating eclipses of genuinely different depth.
- **(c) Double-period:** **likely-binary** — ellipsoidal wave
  **+0.58% at 23σ**; true period 2P = 27.45 d; eclipse depths 1.70% / 2.06%.
- **(d) Orbit-phase:** **the one real pile-up of the batch.** 21 of 32
  on-data centers (frac@boundary = **0.66** vs 0.219 chance) sit within
  1.5 d of an orbit boundary; 15 of 32 (0.47) fall within 1.5 d *after a
  segment start*, phases 0.06–0.83 d, with a second group at 12.66–12.85 d
  (just before gaps); R = 0.47. Read alone, this is the textbook
  scattered-light geometry.
- **(e)** Not known. VSX not run.
- **Verdict: LIKELY BINARY — with the phase pile-up reported, not buried.**
  Two independent checks identify a 27.45 d eclipsing binary with a 23σ
  ellipsoidal wave, which scattered light cannot manufacture in a
  quadrature-symmetric 2P fold. The phase concentration also has an
  innocent mechanism for *this* star: at P = 13.7264 d the eclipse train
  drifts only +0.026 d per orbit against the 13.7 d grid, so it can sit
  inside one 1.5 d phase window for ~55 consecutive orbits — and the
  ephemeris evidently sits just after data-resume. The pile-up is what a
  near-commensurate EB looks like through this test. Recommended
  follow-up before fully closing it: eyeball the 27.45 d fold
  sector-by-sector (the ellipsoidal wave should be visible in individual
  sectors, an artifact would not be).

---

## Batch conclusion — is the 13.7-day cluster instrumental?

**No — not in the way suspected, and the cluster is not one thing.**

1. **The scattered-light signature is absent where it should be strongest.**
   For four of the five cluster members, transit centers are *indifferent*
   to the orbit cycle (frac@boundary 0.14–0.29 vs 0.219 by chance; the two
   lowest values in the batch belong to cluster members). Dips that
   recurred just after every downlink across 15–20 sectors would have lit
   this test up. They didn't.

2. **An orbit-locked artifact also can't explain the reproductions.**
   Every hit re-analyzed at the *identical* period with the *identical*
   SDE. A signal strictly periodic at 13.7 d, folded at 13.60 / 13.13 /
   14.08 d over baselines of 130+ orbits, decoheres (phase drift of
   0.4 d to tens of days); it cannot hold a coherent SDE 10–14 fold.
   The signals are genuinely periodic at their stated periods in the data.

3. **What the cluster actually is: half-period aliases of ~27–28 d
   eclipsing binaries, plus noise.** Two of five cluster members
   (149975388, 149914431) are EBs at 28.38 d and 27.45 d — BLS reported
   the half-period, and ~2 × 13.7 d binaries necessarily alias into the
   13.1–14.1 d bin. That, not the spacecraft, manufactures the "cluster."
   Of the rest: one clean survivor (374942698), and two signals
   (41083982, 149932244) that the fold checks can't confirm — matched by
   the 9.65 d control (150066703), whose SDE 10.4 signal likewise
   evaporates in the raw folds. The app has a background of
   BLS-only signals at the few-tenths-of-a-percent level on faint
   multi-sector stars, at *any* period.

4. **Net yield of the vetting:** of 6 hits vetted — 1 SURVIVES
   (374942698, P = 13.7509 d, the strongest hit of the sweep),
   2 LIKELY BINARY, 3 INCONCLUSIVE, 0 LIKELY SYSTEMATIC.
   The one survivor's period being 1.004× the orbit period is a
   coincidence the phase test specifically acquits — but it is exactly
   the candidate to spend the next follow-up hour on (sector-by-sector
   fold inspection), because if it holds, it holds despite sitting in
   the most suspicious period bin in TESS.

*VSX cross-check was not run for any star (no helper in the codebase;
needs a browser session) — "not known" above refers only to the
Zooniverse Talk check.*
