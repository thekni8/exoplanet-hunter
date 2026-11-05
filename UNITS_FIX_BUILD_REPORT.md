# Units-fix build report — the sweep-5 target-11 stitch crash

**Status: built and acceptance-tested on this server. NOT pushed.**

## Root cause (recap)

TIC 349272923 has no SPOC/TESS-SPOC/QLP products, so the pipeline's
unfiltered fallback pulled a mixed eleanor-lite + TASOC set whose
never-used `flux_bkg` column carries incommensurable units (% vs
electron/s); `LightCurveCollection.stitch`'s inner vstack tries to
unify all shared columns and dies on that pair.

## What changed — `hunter.py` only, three surgical edits

1. **`_stitch_corrector(lc)`** (new, module-level): `lc.normalize()`
   then `keep_columns` down to exactly the columns the pipeline
   consumes — `("time", "flux", "flux_err", "quality")`
   (`_STITCH_COLUMNS`) — so auxiliary columns never reach vstack.
2. **Both stitch sites** now use that one shared corrector, so the
   paths cannot diverge:
   - `_run_pipeline` (line 553) — the sweep / single-star analyze path;
   - `_fetch_stitched` (line 855) — the fake-check path (odd/even,
     double-period) shared by `_fetch_flattened` and `_fetch_raw`.
   These were the only two `.stitch(` sites in production code.
3. **`_is_zero_median_product(lc)`** (new) + exclusion inside
   **`_download_products`** — the funnel both paths share, so the
   guard is inherited identically by both. A product is zero-centred
   when |median flux| ≤ 0.1 × its MAD-based robust σ (TASOC-class
   differential flux, median ≈ 0: `normalize()` divides by the median,
   so such products are un-normalizable garbage). Excluded products
   produce the progress line *"Skipping N zero-centred product(s)
   (uncalibrated flux, median ~ 0 — cannot be normalized) and
   continuing with the rest"*; if **all** downloaded products are
   zero-centred, a dedicated `RuntimeError` says so explicitly
   instead of masquerading as a download failure.
   Calibration on this star's real products: TASOC cbv
   |median|/σ_robust = 0.047, TASOC ens ≈ 0; eleanor-lite = 68 and
   209 — roughly three orders of magnitude of headroom on both sides
   of the 0.1 threshold. Standard products (SPOC/QLP/TESS-SPOC) are
   absolute-flux and never flagged (both regressions below ran with
   zero skips).

No selection-order, priority, or behaviour change for stars with
standard products; no refactors.

## Acceptance results (all via internals, `log_candidate` no-op'd —
the history-suppression mechanism prior vetting scripts used; the
FastAPI/DB layer was never started, port 8000 untouched)

| Test | Result |
|---|---|
| **TIC 349272923** end-to-end, sweep's own call shape (`analyze_target_json`, R★ 0.381, BLS 10,000, cap 20) | **Crash gone.** All 19 products downloaded, guard skipped the 8 TASOC, stitch succeeded on the 11 eleanor-lite products (11 sectors, 10,754 points), BLS + depth refinement + diagnostic PNG all completed. BLS result: **P = 13.4495 d, SDE = 10.34, refined depth = 1.196%** (nominal Rp 4.55 R⊕). Recorded as bare numbers only — above the 8.5 hit threshold, but unvetted; any scientific claim needs the standard gauntlet. |
| **Regression 1 — WASP-126 b** (TIC 25155310, cap 2, R★ 1.30, API defaults) | P **3.28919** d (baseline 3.28919), SDE **22.21** (22.21), refined depth **0.6328%** (0.6328%), Rp 11.28 R⊕ — unchanged. |
| **Regression 2 — TIC 349370417** (sweep-5 star; R★ 0.43, BLS 10,000, cap 20) vs `vetting_results/349370417.json` reproduction | **Bit-identical**: P 13.25107510751075, SDE 17.982033119400526, depth 0.8282978032687398%, Rp 4.269592834652488, 20 sectors, 181,917 points. |
| **Synthetic mixed-set check** (corrector alone, guard bypassed) | Stitching 1 eleanor-lite + 1 TASOC cbv product — the exact pair that crashed — now succeeds: 2,350 points, columns exactly `[time, flux, flux_err, quality]`, no `flux_bkg`. Guard unit checks: eleanor ×2 → kept; TASOC cbv/ens → flagged. |

## Deviations from Appendix A, and why

- Appendix A's snippet used `select_columns(...)`; **lightkurve
  2.6.0 has no such method** (`AttributeError`). Implemented with
  `keep_columns` on the normalized curve — the same reduction,
  verified on the real products.
- The appendix floated the zero-median treatment without fixing its
  location; per the build brief's preference (exclude, with a log
  line — never invent a calibration) the exclusion lives in
  `_download_products`, the single funnel both stitch paths share.
- `injection_harness.py` still carries its own legacy
  `stitch(corrector_func=lambda x: x.normalize())` at line 136. It is
  a frozen test harness (standard products only; its recorded results
  pair with its exact code) and was deliberately left untouched; a
  one-line switch to `hunter._stitch_corrector` is available if ever
  wanted. `gemini_pilot_qa_odd_even.py` is a reference script, also
  untouched.

## Data discipline

`data/hunter.db` md5 `33b70438b3669f9c313b510488d20d48` and
`discoveries.csv` md5 `2c8abaae5be0456af6a7effa8a22b6ff` — identical
before and after all tests (precautionary /tmp backups were taken;
no restoration was needed). Side effects are exactly the analyze
path's own production outputs: `reports/TIC_349272923_diagnostic.png`
(new — the star's first successful analysis) and re-rendered plates
for the two regression stars.
