# Bulk screen — proof run notes (run_s0001_proof)

**Date:** 2026-11-11 (01:53–02:16 IST). **Machine:** Muse VM
(4 shared vCPU visible, ~1.5 CPU effective, ~8 GB RAM).
**Command:** `bulk_screen.py --stars-file proof_stars.csv --sector 1
--control-tic 150428135 --out-dir bulk/run_s0001_proof --workers 3
--dl-workers 8`. The star file was built by the pipeline's own
`cone_star_list`: 6° cone on TOI-700 (RA 97.0969, Dec −65.5793),
window Tmag 10.0–13.5, R 0.2–0.8 R_sun → 2,210 stars (list build took
245 s of tiled MAST Filtered-TIC queries).

## Numbers (from summary.json)

- Stars in: **2,210**
- Known filter (224 s): VSX skipped **558** (25.3%) via 31 tiled VSX
  cone queries (167,092 variable rows pooled, matched locally at 30″);
  TOI skipped **0 — check OFF**: the NASA Exoplanet Archive TAP
  returned HTTP 503 "Under Maintenance" on the initial pull and on 3
  retries during the run (verified independently by curl at
  01:45–01:57 IST). Fail-open behaved exactly as designed; TOI hosts
  therefore remained in this sample (the control is one).
- Downloads (231 s): 1,428 fetched + 1 cached, **223 no-product**
  (13.5% of post-filter stars — the QLP faint/silicon ceiling),
  0 errors, **115.2 MB**.
- Screened: **1,429 stars in 449 s = 11,450 stars/h compute**
  (3 workers). Outcomes: 348 below record floor (SDE < 6), 1,081
  recorded hits (268 below survivor bar, 362 demoted by free vetoes,
  **451 survivors**). Zooniverse Talk check on survivors: 0 known.
- **Wall clock total 1,236 s → 4,811 stars/h end-to-end.**

## Positive control — CAUGHT

TIC 150428135 (TOI-700) **survived the screen**: SDE **10.26**,
depth 0.140%, rank **169 of 1,081** recorded hits. Caveat: sector 1
contains exactly ONE TOI-700 c transit (P 16.0511 d), so the BLS peak
sits at the 20 d grid edge — a lone-transit alias, not the true
period. A screen only has to surface the star; the gauntlet
re-derives the ephemeris. (Also note: the recovered star initially
VANISHED under a strict quality==0 mask — its only sector-1 transit
sits on QUALITY=4096 cadences. The pipeline therefore uses the
lightkurve TESS default bitmask 17087, like production SPOC work.)

## Honest problems

1. **Survivor flood.** 451/1,429 = 31.6% pass rate is far too high
   to feed a gauntlet (a 126k-star run at this rate yields ~40k
   "survivors"). Survivor SDE median is only 8.3 (202/451 ≥ 8.5,
   92 ≥ 10, 29 ≥ 12); 145 survivors sit in the 8–14 d
   systematic-rich period band and 101 are sub-day (mostly unlisted
   rotators/EBs the free vetoes can't catch — equal-depth EBs evade
   odd/even). Root causes: sector 1 QLP is the noisiest sector in
   the mission (30-min cadence, early-mission systematics), and a
   single-sector robust-SDE scale is NOT the deep pipeline's
   multi-sector SDE scale. v1 proves mechanics + recall; threshold
   calibration per product/sector is the v1.1 job (candidates:
   higher survivor bar for single-sector QLP, a folded-shape SNR,
   or a split-sector consistency requirement).
2. **TOI stage outage** (above). The retry wrapper added in this
   build (hunter's helper caches a failed pull process-wide) is
   necessary but not sufficient against a multi-hour maintenance.
3. **Star-list cost.** Cone-mode list building took 245 s for one
   6° cone (tiled Filtered-TIC queries; the sweep's query_region
   route dies in this network's proxy and single large filtered
   queries truncate silently near ~10³ rows — the cone-centre star
   was dropped by a single 4° query and recovered by tiling).
   For full-sector runs, adopt Rabtsevich's own star-list method
   (TEARDOWN.md §1): the QLP sector target-list CSV + batched TIC
   Tmag lookups — one download per sector, no cones.

## What the numbers say about scale

Measured on this VM: downloads ~25,700 stars/h (not the bottleneck
at 80 KB/star), compute 11,450 stars/h, end-to-end 4,811 stars/h
(filter/list stages included). A 126,246-star run (his list size)
would take ~26 h end-to-end on this VM as-is — but would produce
~40k survivors at the current calibration, which is the real wall:
the gauntlet, and the per-survivor Zooniverse HTTP check (~0.7 s
each → ~8 h for 40k), cannot eat that. Closing the gap needs, in
order: (1) threshold/shape calibration to a ≤1–2% pass rate;
(2) sector target-list star lists; (3) more compute workers
(the screen is embarrassingly parallel; the Mac or a future
Actions workflow would multiply throughput linearly).
