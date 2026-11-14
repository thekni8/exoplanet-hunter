# Sector-98 recalibration (v1.3) — 2026-11-12

## Why
The v1.1 MES/CDPP tier calibration (sector 1, 30-min cadence, 27.8 d)
does NOT transfer to sector-98 data (200-s cadence, SYS_RM_FLUX,
57.4 d span). The raw screen passed 8,450 survivors (21% of stars
searched) — an order of magnitude above the 1.61% sector-1 rate.
First look (`analyze_s0098_hits.py`, output
`run_s0098/analysis_first_look.txt`) showed the list is dominated by
an instrumental pile-up, not planets.

## Rules (applied in order to the 8,450 final survivors)
1. **Systematic-period exclusion** — drop P in [13.5, 15.0] d (the
   13.7 d TESS-orbit family + the 14.4 d peak + shoulders), [7.0, 7.4] d
   (half-alias), [0.98, 1.02] d (daily alias). 88% of survivors sat at
   10–15 d (median 14.4 d; the 14.4 d bin alone held 3,848); the
   screen's `near_systematic` flag caught only 241 of them. A real
   planet in these bands cannot be told from the systematic in
   single-sector data.
2. **Planet-like shape** — depth ≤ 1.0%, odd/even in [0.7, 1.43],
   secondary depth ≤ 0.3%. (Median survivor depth was 1.33%; 66% were
   ≥1%, and 33% failed odd/even.)
3. **Physical duration** — transit duration ≤ 8% of the period. A
   planet's T/P ≈ (R★/a)/π, at most ~0.05–0.08 even for grazing
   ultra-short-period cases around small stars. 50/62 post-shape
   candidates had durations >15% of the period (48 pegged at the
   6.048 h grid max) — rotators, pulsators, long-eclipse EBs, or
   systematics, not planets.
4. **Strength** — MES_pink ≥ 15. The duration-plausible MES values
   show a natural gap (14.3 → 18.8), so any threshold in (14.3, 18.8]
   gives the identical list — the cut is robust, not tuned.

## Funnel
| stage | remaining | removed |
|---|---|---|
| input (final survivors) | 8,450 | — |
| 1. period exclusion | 517 | 7,933 |
| 2. shape cuts | 167 | 350 |
| 3. duration ≤8% | 27 | 140 |
| 4. MES ≥ 15 | **10** | 17 |

## Final list (MES descending)
| TIC | P (d) | depth % | MES | SDE | n_ev | Tmag | R★ |
|---|---|---|---|---|---|---|---|
| 14081980 | 2.9195 | 0.783 | 55.9 | 284.5 | 20 | 10.5 | 0.62 |
| 31054247 | 0.8737 | 0.618 | 31.7 | 93.8 | 65 | 12.3 | 0.76 |
| 423498314 | 0.8270 | 0.966 | 24.8 | 83.1 | 66 | 13.4 | 0.67 |
| 14174515 | 3.0895 | 0.600 | 22.5 | 68.2 | 18 | 12.5 | 0.75 |
| 77437461 | 0.6079 | 0.691 | 20.8 | 51.0 | 91 | 11.3 | 0.49 |
| 382069441 | 5.4908 | 0.785 | 20.7 | 131.8 | 11 | 11.4 | 0.74 |
| 141708335 | 4.7602 | 0.826 | 20.2 | 76.5 | 12 | 12.1 | 0.42 |
| 272431317 | 3.0109 | 0.850 | 19.8 | 54.5 | 18 | 12.7 | 0.47 |
| 177283727 | 3.9554 | 0.559 | 19.1 | 68.0 | 15 | 12.4 | 0.69 |
| 255569654 | 5.9994 | 0.802 | 18.8 | 57.0 | 8 | 12.1 | 0.79 |

Standout: **TIC 14081980** — MES 55.9 (3× the next tier), 20 events,
bright (Tmag 10.5), implied size ~6 R⊕ on a 0.62 R☉ star. All 10 are
Tier A (periodic, ≥3 events); no Tier B candidate survived.

## Notes for the gauntlet
- **TIC 77437461 / 77437462 pair**: same period (~0.608 d), adjacent
  TICs; 77437462 sits at MES 14.0 just below the cut. Likely one
  signal in two apertures — centroid check decides which star hosts it.
- **Likely EBs at double period** (strong, duration-rejected, NOT in
  the list): TIC 66775591 (MES 28.0, P 1.30 d, dur frac 0.138) and
  TIC 123627758 (MES 20.4, P 0.68 d, dur frac 0.136). At 2× period
  their duration fractions become plausible for EBs. Cheap double-
  period check if the Deep side wants them.
- Every input survivor is accounted for in
  `run_s0098/recalibrated/rejected_audit.jsonl` (stage of removal).

## Files
- Script: `archive/bulk-screens/s0098/recalibrate_s0098.py`
- List: `bulk/run_s0098/recalibrated/survivors_v13.jsonl`
- Summary: `bulk/run_s0098/recalibrated/summary_v13.json`
- Funnel log: `bulk/run_s0098/recalibrated/funnel_v13.txt`
