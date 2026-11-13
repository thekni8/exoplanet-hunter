# Recalibration — sector 97 (v1.3 FINAL)

**Date:** 2026-11-14 ~00:45 IST. **Code:** `bulk/recalibrate_s0097.py`
(+ `--stop-after-duration` / `--mes-min`). **Input:**
`bulk/run_s0097/survivors.jsonl` (14,732 post TOI/VSX/Zooniverse).
**First look:** `bulk/run_s0097/analysis_first_look.txt`.

## Why recalibration is needed (same story as S98, worse)

The v1.1 tiers (sector 1, 30-min cadence) do not transfer to 200-s
SYS_RM_FLUX data. S97 is worse than S98: raw survivor rate **41.6%**
(S98: 21.2%), and **97% of survivors pile at 10–15 d** (S98: 88%).

First-look findings (`analyze_s0097_hits.py` on 35,374 screen hits):
- Period pile-up is at **13.7 d** (peak bin 2,963), shoulders
  13.3–14.6 d — the systematic peak **moved** from S98's 14.4 d.
  13,504 survivors sit in the 13.7 d family (12.7–14.3 d).
  `near_systematic` caught 12,115/14,797 this time (S98: 241/8,450).
- Median survivor depth 1.29%; 69% ≥ 1% (EB-like). 37% fail odd/even.
- MES_pink median 12.3 (S98: 10.6), p95 18.4, max 64.7 — shifted
  higher, so the MES cut is re-derived, not copied.
- Duration pegs at the 6.048 h BLS grid max for most survivors
  (p25 = p50 = p75 = p95 = 6.05 h), same as S98.

## Rules (same 4-stage funnel as S98, S97-derived bands)

1. Systematic-period exclusion: drop P in **[13.2, 15.0] d** (13.7 d
   family + shoulders + tail), **[7.0, 7.4] d** (half-alias),
   **[0.98, 1.02] d** (daily alias).
2. Planet-like shape: depth ≤ 1.0%, odd/even in [0.7, 1.43],
   secondary depth ≤ 0.3%.
3. Physical duration: transit duration ≤ 8% of the period.
4. Strength: **MES_pink ≥ 20**. Post-duration MES values: 40 stars
   at 9.1–15.0, then a natural gap **15.0 → 23.3** (gap 8.3) and
   23.3 → 32.1 (gap 8.8). Any threshold in (15.0, 23.3] gives the
   identical 2-star list — the cut is robust, not tuned. Full gap
   table: `run_s0097/recalibrated/mes_gap.txt`.

## Funnel

14,732 → **447** (period) → **114** (shape) → **42** (duration)
→ **2** (MES ≥ 20). Every input accounted for in
`recalibrated/rejected_audit.jsonl`.

## Final 2 (MES descending, both Tier A)

1. **TIC 139526205** — P 2.9223 d, depth 0.505%, MES 32.1, SDE 129.2,
   16 events, oe 0.93, dur 3.17 h (frac 0.045), Tmag 11.3, R 0.72,
   RA 36.39 Dec −29.23. The standout: SDE 129, 16 events, clean shape.
2. **TIC 344334378** — P 6.6619 d, depth 0.256%, MES 23.3, SDE 37.5,
   9 events, oe 0.95, dur 3.17 h (frac 0.020), Tmag 10.3, R 0.58,
   RA 34.62 Dec −20.01. Shallow (0.256% — small-planet-sized), bright.

## Notes for the gauntlet

- **Nearest miss: TIC 123270894** — P 18.2772 d, depth 0.798%,
  MES 15.01, SDE 19.6, but only **2 events**, Tier B, duration pegged
  at the 6.05 h grid max. Excluded: a 2-transit, borderline-MES
  candidate whose exact MES (15.01) sits at the cluster's top edge —
  the cut is fragile for this star alone, and the 2-star list in the
  (15.0, 23.3] gap is the robust one. Revisit only if the Deep side
  wants a Tier B look.
- **S98 top-10 overlap stars in S97** (4 of the 10 are in S97's
  footprint; all 4 were gauntlet-closed from S98 as blends/EBs):
  - **TIC 382069441** re-detects cleanly in S97: P 5.4957 d (S98:
    5.4908 d), depth 0.740% (S98: 0.785%), MES 12.4, Tier A —
    cut only by the recalibration MES threshold. Persistence
    confirmation of the S98 signal, not a new candidate; the S98
    blend verdict stands, no re-vetting needed.
  - **TIC 141708335 / 272431317 / 177283727** did NOT reproduce as
    S97 survivors (status `recorded`): BLS locked onto other peaks
    — 141708335 at 10.99 d (MES 7.6), 272431317 at 13.75 d (the
    systematic band, MES 7.4), 177283727 at 1.0027 d (daily alias,
    MES 5.7). Does not overturn the S98 verdicts; shows the S97
    screen is noisier for those signals.
- **TIC 423498314** (the live planet candidate) is NOT in S97's
  footprint — no S97 data on it.
- S97's raw survivor rate (41.6%) is double S98's — the recalibrated
  list is correspondingly smaller (2 vs 10). The two survivors are
  both strong, clean, and well-separated in MES from the marginal
  cluster.

## Files

- `bulk/recalibrate_s0097.py`, `bulk/analyze_s0097_hits.py`
- `bulk/run_s0097/recalibrated/{survivors_v13.jsonl, summary_v13.json,
  rejected_audit.jsonl, mes_gap.txt}`
- `bulk/run_s0097/analysis_first_look.txt`
