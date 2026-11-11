# Target-list method (v1.2) — how a full-sector star list is built

**Date:** 2026-11-11. **Code:** `bulk_screen.py: target_list_star_list`
(+ `--target-list` CLI), driver `bulk/build_target_list.py`.
hunter.py untouched; cone and CSV star lists unchanged.

## The method (Rabtsevich's, from teardown §1)

1. **Sector QLP target list** — plain CSV at
   `https://archive.stsci.edu/hlsps/qlp/target_lists/sXXXX.csv`
   (TIC_ID, RA, DEC for every star QLP extracted that sector).
   Re-verified locally 2026-11-11: sector 98 = **628,730 unique
   TICs** (exactly his deposited count), sector 1 = 469,735, and the
   proof control TIC 150428135 is in the sector-1 list.
2. **Batched TIC 8.2 lookups by ID** — `Catalogs.query_criteria`,
   batches of **5,000** (his deposited batch size), returning
   Tmag / radius / RA / Dec. Batch wall time through the proxy is
   variable (~10 s–2 min); there is no columns filter on this service.
3. **Window applied locally** — Tmag ∈ [min, max], radius ∈
   [min, max]; stars with no Tmag are always excluded; stars with no
   radius are excluded when `require_radius` (default for screening)
   and counted either way.

## Caching / resumability

Raw CSV → `bulk/cache/target_lists/sXXXX.csv`; enriched metadata →
`sXXXX_tic.csv`, **appended batch-by-batch**, so an interrupted build
resumes from the last cached batch. A cold sector build is a
one-time cache-building job (~126 batches for S98); warm builds are
instant. The enriched cache is sector-independent knowledge (TIC
metadata), reusable across windows.

## Smoke validation (sector 1, first 20,000 IDs, 2026-11-11)

- 20,000/20,000 enriched, 0 missing Tmag.
- Our window (Tmag 10–13.5, R 0.2–0.8): **1,573 stars in window
  (7.9%)**; 1,128 further stars were in the mag window but have no
  TIC radius — excluded and counted (this is the honest price of the
  radius cut: TIC simply doesn't know those radii).
- Spot checks: 3 random enriched TICs re-queried singly — Tmag,
  radius and RA match the batch cache exactly, including a NaN
  radius round-tripping as missing.

## Sector-98 recount (his rule: Tmag ≤ 11.5, no radius cut)

**PASSED — exact.** Cold build 2026-11-11 12:02–12:21 IST (126
batches, ~19 min): 628,730 target IDs → 628,730 enriched, **0
missing Tmag** (matches his `n_missing_in_tic = 0`), **126,246 with
Tmag ≤ 11.5 — his verified figure to the star.** 5,882 of those have
no TIC radius (counted; irrelevant under his no-radius rule).

## What this buys for a future run

- The enriched S98 metadata is now cached locally: a warm window
  rebuild for the whole sector takes **~5 seconds**.
- Our screening window (Tmag 10–13.5, R 0.2–0.8, radius required) on
  S98 = **39,939 stars** (32,051 more in the mag window lack a TIC
  radius and are excluded). At the proof run's measured rates that
  is ~3.5 h of screen compute (~8 h end-to-end with downloads),
  and at v1.1's 1.61% pass rate roughly ~640 survivors in tier
  order — the first realistic full-sector run, when Dev says go.
