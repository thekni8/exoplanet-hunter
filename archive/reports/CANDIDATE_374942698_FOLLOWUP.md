# TIC 374942698 — Follow-up vetting: sector persistence + catalog checks

**Candidate as swept:** P = 13.7509 d, SDE 14.2, depth 1.53%, Rp 6.47 R⊕,
R\* = 0.48 R☉. Ephemeris used (production analyze, pass 2): P = 13.750925 d,
T0 = 2148.30222 BTJD, duration 5.976 h. All 16 sectors the sweep used.

**Bottom line: FALLS.** The catalog side is spotless — nothing anywhere has
ever flagged this star. But the persistence test kills the candidate as
characterized: the 1.53% "transit" is not a steady dip that shows up sector
after sector. It is an average of mostly nothing — plus a handful of
enormously deep events in a few sectors that drag the combined fold up.
A real planet on a 13.75-day orbit cannot take sectors off.

---

## 1. Sector-by-sector persistence test

**Method (primary):** the production pipeline's own stitched, two-pass
transit-masked flattened flux (exactly what the BLS detection saw), split
back into its 16 sectors. Per sector: depth = mean(out-of-transit) −
mean(in-transit) at the fixed ephemeris; uncertainty from the scatter of
out-of-transit means chunked at the transit-duration timescale (prices in
red noise). A sector is *usable* if it contains ≥1 transit window covered
≥80%. Verdict rules (set before looking): CONSISTENT = ≥70% of usable
sectors show a dip ≥1.5σ AND depths compatible with a constant (χ² p >
0.01); CONCENTRATED = positive sectors ≤30%; else MIXED.

| Sector | Points | In-transit pts | Full transits | Depth % | ±σ % | Significance | Raw depth % | Usable |
|---|---|---|---|---|---|---|---|---|
| 31 | 3,443 | 70 | 2 | +0.02 | 0.18 | +0.1σ | +0.34 | yes |
| 35 | 2,693 | 55 | 0 | +1.38 | — | — | −0.78 | no — no fully-covered transit |
| 37 | 3,453 | 72 | 2 | −0.07 | 0.19 | −0.4σ | +0.80 | yes |
| 61 | 10,653 | 215 | 2 | −0.01 | 0.16 | −0.0σ | +0.41 | yes |
| 62 | 10,397 | 81 | 0 | +1.13 | — | — | +1.46 | no — no fully-covered transit |
| 63 | 10,941 | 216 | 2 | +1.33 | 0.09 | **+14.9σ** | −3.32 | yes |
| 64 | 11,275 | 215 | 2 | +0.04 | 0.08 | +0.5σ | +2.33 | yes |
| 68 | 9,459 | 117 | 0 | +7.12 | — | — | **+14.73** | no — transits only partially covered |
| 69 | 9,476 | 198 | 2 | −0.97 | 1.09 | −0.9σ | +3.41 | yes |
| 87 | 11,338 | 215 | 2 | +0.44 | 0.10 | **+4.5σ** | −0.19 | yes |
| 88 | 11,718 | 215 | 2 | +0.26 | 0.08 | **+3.2σ** | +1.24 | yes |
| 89 | 11,411 | 215 | 2 | −0.18 | 0.09 | −2.0σ | +0.39 | yes |
| 90 | 11,180 | 215 | 2 | +1.02 | 1.41 | +0.7σ | +3.73 | yes |
| 95 | 9,484 | 0 | 0 | — | — | — | — | no — transit windows fall entirely in data gaps |
| 96 | 9,684 | 75 | 0 | +9.65 | — | — | **+18.81** | no — transits only partially covered |
| 97 | 18,801 | 310 | 3 | +6.80 | 0.93 | **+7.3σ** | **+17.47** | yes |

**Persistence numbers (11 usable sectors):**
- Sectors with a dip ≥1.5σ: **4 of 11 (36%)** — sectors 63, 87, 88, 97.
  The CONSISTENT bar was 70%.
- Weighted-mean sector depth: **0.32% ± 0.05%** — a factor ~5 shallower
  than the pipeline's 1.53%.
- χ² test against a constant depth: **χ² = 235.1 on 10 dof, p ≈ 7×10⁻⁴⁵.**
  The sector depths are decisively *not* one constant depth; they range
  from −0.97% to +6.80%, with several sectors consistent with zero and
  one (89) mildly *negative*.
- **Verdict by the stated rules: MIXED** (36% is neither ≥70% nor ≤30%) —
  and even that word is generous, because the χ² leg of CONSISTENT fails
  catastrophically, not marginally.

**Event-level view (23 fully-covered transits, production flux):** median
event depth **+0.35%**, mean +1.04%, only 57% of events positive. The mean
is dragged up by sector 97's three consecutive events at **+9.2%, +4.5%,
+6.8%**; sector 69 contributes a −2.8% "event". This median (+0.35%)
agrees with the vetting round's raw-fold odd/even depths (0.352% / 0.365%)
and with the sector weighted mean (0.32%) — there *is* a persistent
shallow ~0.35% periodic component. What there is not: a persistent
1.53% one.

**The monsters are in the raw data.** Sectors 68, 96 and 97 show dips of
+14.7%, +18.8% and +17.5% at the fold phase in *normalize-only* flux —
the flattening shrinks them, it does not create them. In sectors 68 and
96 the transit windows are only partially covered, so those fragments sit
on something 10× deeper than the claimed transit. Deep, sector-dependent
events like this are the classic signature of a **blended eclipsing
binary in the aperture** (ExoFOP lists a TIC contamination ratio of
0.136 for this target) whose eclipse train beats against the 13.75 d
fold and is sampled differently as the spacecraft geometry changes from
cycle to cycle — or of episodic artifacts in those sectors. Either way,
they are not the swept candidate, and they poison its fold.

**Cross-check (independent per-sector detrending, same two-pass masked
recipe run sector-by-sector from scratch):** 13 usable sectors, weighted
mean depth 0.87%, and a global red-noise factor β ≈ 24 at the
transit-duration timescale — the star's ~6-hour correlated noise is
ferocious. With those (much larger) error bars only 1 of 13 sectors
reaches 1.5σ. The two uncertainty models bracket the truth; both agree
on the essential point: **no sector-by-sector case for a steady 1.53%
dip exists.**

Combined fold plot: `candidate_374942698_fold.png` (all 16 sectors,
production pass-2 flux, binned; orange band = BLS transit window, red
dashed line = the pipeline's 1.53% depth, which the bin means visibly
fail to reach as a steady feature).

Per-sector machine-readable results: `sector_persistence_374942698.json`.

## 2. Known-catalog checks

- **ExoFOP-TESS** (target page, fetched 2026-11-03): **TOIs 0. Community
  Planet Candidates 0. Confirmed Planet(s): N/A.** No files, no
  observations, nothing uploaded. Cross-IDs: 2MASS J05570011-6503385,
  Gaia DR3 4755995549491699840, UCAC4 125-008188, WISE J055700.02-650337.9.
  Coordinates (ICRS): RA 89.24992°, Dec −65.060454°. TIC contamination
  ratio 0.136.
- **NASA Exoplanet Archive, TOI table** (TAP query `tid = 374942698`):
  **0 rows.** It has never been a TESS Object of Interest.
- **NASA Exoplanet Archive, confirmed-planets (PS) table** (TAP query
  `tic_id = '374942698'`): **0 rows.** No confirmed planet.
- **AAVSO VSX** (API Anything has no VSX site, so plain read-only fetch
  of the VSX VOTable query): by identifier "TIC 374942698" — **empty
  result**. By position (cone around the target's coordinates, 36
  catalogued variables returned, mostly Gaia RR Lyrae / rotational
  variables in this Dorado field): **the target's Gaia ID does not
  appear and no row sits at its coordinates** (nearest VSX variable ≳5′
  away). **No VSX entry for this star.**
- **SIMBAD:** not retrieved — the SIMBAD TAP endpoint returned empty
  responses on repeated attempts and the ASCII route yielded nothing
  extractable. Optional item; noted for completeness, and moot given
  the outcome below.
- (From the earlier vetting round: Zooniverse Planet Hunters Talk —
  not flagged.)

## 3. Bottom line: FALLS

Plain language: the swept candidate said "a 6.5-Earth-radius planet
crossing this star every 13.75 days, dipping its light by 1.53%."
Sector by sector, that dip mostly isn't there — 7 of 11 usable sectors
show nothing significant, one shows a slight *brightening*, and the
depths that do appear swing from 0.26% to 6.8%, which a constant transit
cannot do (χ² p ≈ 10⁻⁴⁴). The combined 1.53% is an average inflated by
a few gigantic events (up to ~19% deep in raw flux) that live in
specific sectors — most likely a blended eclipsing binary or episodic
artifacts, not this star's planet. The catalogs, for their part, are
completely silent: never a TOI, never a community candidate, no
confirmed planet, no variable-star entry. The star is unflagged *and*
the signal is not persistent — it fails the test that matters.

What remains, honestly stated: a shallow ~0.35% periodic residue
(median event depth, sector weighted mean, and the earlier odd/even
fold all agree) that *could* be a ~3 R⊕ object — buried in a noisy,
possibly contaminated light curve, next to unexplained 15–19% episodic
dips. That is not a candidate; it is an anomaly with homework
(difference-image/centroid checks on sectors 96–97, aperture inspection
for the blend). The 13.7509 d / 1.53% / 6.47 R⊕ candidate from the sweep
should not be carried forward or reported.
