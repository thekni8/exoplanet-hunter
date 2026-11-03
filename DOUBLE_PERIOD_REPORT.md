# Double-Period (Ellipsoidal) Test — Build Report

**Built:** 2026-11-03 (IST), after the TIC 308851365 resolution.
**Status:** Complete. All tests real, run through the live API on the new
code. Server left RUNNING on port 8000 with the new build. **Not pushed
to GitHub** — parent agent reviews and pushes.

---

## 1. What this is

The odd/even fake-check has a known blind spot: twin stars of similar
size orbiting at **twice** the candidate period eclipse with equal
depths and pass as "planet-like". That is exactly what TIC 308851365
did (odd/even: planet-like; SDE up to 66.2).

The double-period test closes the blind spot. Fold the light curve at
2P and look at the light **between** the eclipses. Close twin stars
raise tides on each other and are squeezed out of round; twice per
orbit they present their wider sides (at the quarter-orbit points —
the quadratures) and the system **brightens**. A planet is far too
light to bend its star, so its fold stays flat. On TIC 308851365 the
wave measured **+1.09% at 37σ** — the evidence behind the VSX
reclassification ROT → EB (revid 853367).

## 2. Design

### Raw, not flattened — the critical data rule

`double_period_test` reads the **raw normalized** light curve via the
new `_fetch_raw`. It must NOT use the flattened curve:
`flatten(window_length=101)` is an hours-scale detrending filter, and
the ellipsoidal wave it would need to preserve has a ~1.5-day period —
flattening can iron the signal flat and manufacture a "no signal"
answer. Every number below comes from unflattened data.

### Fetch refactor (minimal, behaviour-preserving)

`hunter.py`'s `_fetch_flattened` front half was extracted into
`_fetch_stitched(tic_id, max_sectors, progress_callback)` (search →
self-healing download → stitch with per-sector normalize →
remove_nans/remove_outliers σ=5). It returns the stitched LightCurve
itself, so `_fetch_flattened` flattens literally the same object it
always did, then extracts arrays — its behaviour is unchanged (proven
by regression test 3a reproducing the Stage-4 odd/even numbers to full
precision). The new `_fetch_raw` extracts arrays from the same
stitched curve without flattening. Both return
`(t, f, n_sectors, total_points)`.

### Measurement

1. Focused BLS refinement around 2P: ±3%, 3000 periods, durations
   [0.08, 0.15, 0.25] d. Its `transit_time` is the fold epoch, so
   eclipse 1 sits at phase 0.
2. Phase-fold at the refined 2P; median flux over fixed windows:
   - Eclipse 1: [0.94, 1.0] ∪ [0.0, 0.06]
   - Eclipse 2: [0.44, 0.56]
   - Quadratures Q: [0.19, 0.31] ∪ [0.69, 0.81]
   - Shoulders S: [0.08, 0.17] ∪ [0.58, 0.67] ∪ [0.83, 0.92] ∪ [0.33, 0.42]
3. `delta = median(Q) − median(S)`; SE from each window set's
   scatter/√N combined in quadrature; `sigma = delta / SE`.
4. Verdicts (fixed thresholds, module constants):
   - delta ≥ +0.2% **and** sigma ≥ 5 → **likely-binary**
   - delta ≤ −0.2% **and** sigma ≤ −5 → **inconclusive** (a quadrature
     *dip* is not the twin signature; spots/systematics can do it)
   - otherwise → **no-ellipsoidal-signal** (flat out-of-eclipse light;
     consistent with a planet, or a binary too wide to distort)

## 3. Inventory

### Backend — `hunter.py`
- `_fetch_stitched` (extracted), `_fetch_flattened` (rebuilt on it),
  `_fetch_raw` (new)
- `DP_ECLIPSE1_WINDOWS / DP_ECLIPSE2_WINDOWS / DP_QUADRATURE_WINDOWS /
  DP_SHOULDER_WINDOWS`, `DP_DELTA_THRESHOLD_PERCENT = 0.2`,
  `DP_SIGMA_THRESHOLD = 5.0`
- `_phase_window_stats(phase, flux, windows)`
- `double_period_test(tic_id, period_days, sector_cap=None,
  progress_callback=None)` → scalars + 100-bin folded curve
- `double_period_result_to_json_dict(full)`,
  `double_period_test_json(...)`
- Metrics emitted: `tic_id, period_given_days,
  period_2p_refined_days, t0_2p_days, duration_2p_days, sectors_used,
  total_points, eclipse1_median, eclipse2_median,
  eclipse1_depth_percent, eclipse2_depth_percent,
  quadrature_median, shoulder_median, delta_percent,
  delta_se_percent, delta_sigma, verdict, verdict_text`, plus
  `folded.binned.{phase, median_flux}`

### Backend — `api.py`
- `POST /api/doubleperiod` → job type `"doubleperiod"` through the
  same single-worker queue (`_run_doubleperiod` mirrors
  `_run_oddeven`: full payload stored to `data/results/<job>.json`,
  metrics as the job summary, job period = refined 2P)
- `DoublePeriodRequest`: `tic: str`, `period: float` (Field gt=0),
  `sector_cap: int` (default 2, 1..40). Out-of-range requests return
  422 (verified: period=0, sector_cap=0, sector_cap=41)

### Frontend
- `frontend/src/doubleperiod.jsx` (new) — mirrors the fakecheck
  family exactly: `DoublePeriodToggleButton` (sky-themed, Waves icon,
  "Double-period check"), `DoublePeriodCheck` (POST → poll → verdict
  box with the full verdict sentence, quadrature/shoulder medians,
  delta % at σ, refined 2P, sectors; red tone for likely-binary,
  green for no-ellipsoidal-signal, zinc for inconclusive),
  `DoublePeriodButton` (one-piece widget)
- `frontend/src/charts.jsx` — `DoublePeriodChart`: binned median over
  phase 0..1 in percent, eclipse windows shaded red, quadrature
  windows shaded green, zero line dashed. (Implemented on canvas like
  every other chart in this codebase, OddEvenChart included.)
- Placements, always next to the fake-check with the same
  `tic_id`/`period_days` props:
  - **Observatory**: `DoublePeriodButton` directly under
    `FakeCheckButton` in the result area
  - **Sweeper** `HitRow`: toggle in the actions cell + full-width
    expansion row
  - **History & Discoveries** `DiscoveryRow`: toggle in the actions
    cell + full-width expansion row
  - **Scanner** `SignalEntry`: toggle in the button row of both the
    strong-hit card and the weaker-signal row, panel below
- QA Benchmarks untouched. UI jobs post `sector_cap: 2`, mirroring
  FakeCheck.

### Bundle hashes
- Before: JS `index-vtTY13EG.js`, CSS `index-BL3vLpjt.css`
- After: JS `index-OYu1Pmn1.js` (231.90 kB, gzip 69.00 kB),
  CSS `index-D9VV5TYh.css`
- `npm run build` clean; `GET /` serves the new hash;
  `GET /api/health` → `{"ok": true}`

## 4. Tests — all real, through the running API

### Test 1a — TIC 308851365 @ 0.75677, sector_cap 2 → likely-binary ✔
Job `c8ca623393e64ed3`, done in 60 s.
| metric | value |
|---|---|
| period_2p_refined_days | 1.5132826124041348 |
| sectors_used / total_points | 2 / 1,900 |
| eclipse1_median (depth) | 0.992291271686554 (0.771%) |
| eclipse2_median (depth) | 0.9939589500427246 (0.604%) |
| quadrature_median | 1.0064669847488403 |
| shoulder_median | 1.001139521598816 |
| delta_percent | **+0.5327463150024414%** |
| delta_se_percent | 0.049255781047246955% |
| delta_sigma | **10.82σ** |
| verdict | **likely-binary** |

### Test 1b — TIC 308851365 @ 0.75677, uncapped (sector_cap 40) → likely-binary ✔
Job `638e141ae2964c6f`, done in 10 s (warm cache). **Reproduces
tonight's standalone reference run to full float precision** — same
fetch/stitch path and window math:
| metric | value | tonight's reference |
|---|---|---|
| period_2p_refined_days | 1.5127678372124043 | 1.51277 |
| sectors_used / total_points | 12 / 12,578 | 12 / 12,578 |
| eclipse1_median | 0.9886882305145264 | 0.9887 |
| eclipse2_median | 0.9892029464244843 | 0.9892 |
| quadrature_median | 1.0114473700523376 | 1.01145 |
| shoulder_median | 1.0005112886428833 | 1.00051 |
| delta_percent | **+1.0936081409454346%** | +1.094% |
| delta_sigma | **36.99σ** | ≈37 |
| verdict | **likely-binary** | — |

### Test 2 — CONTROL: WASP-126 b (TIC 25155310) @ 3.2822, cap 2 → no-ellipsoidal-signal ✔
Job `7c25e8bc9de94491` (final build; an identical-metrics run,
`846c7d6cc2424244`, preceded the verdict-text formatting tweak in §5).
The lie-detector holds: the known planet's fold is flat.
| metric | value |
|---|---|
| period_2p_refined_days | 6.574972208069356 |
| sectors_used / total_points | 2 / 36,535 |
| eclipse1_median / eclipse2_median | 0.9997817575931549 / 0.9996955394744873 |
| quadrature_median | 1.0000613927841187 |
| shoulder_median | 1.0000916719436646 |
| delta_percent | **−0.0030279159545898438%** |
| delta_sigma | **−1.63σ** |
| verdict | **no-ellipsoidal-signal** |

### Test 3a — Regression: odd/even WASP-126 b @ 3.2822, cap 2 → planet-like ✔
Job `9f19e6f43b8d464e`, done in 6 s. Fit period 3.2887644 d; depths
odd 0.0852% / even 0.0813%; rel diff 0.0448; ratio 0.9552 — the
Stage-4 reference numbers exactly. The `_fetch_flattened` refactor
changed nothing.

### Test 3b — Regression: analyze smoke, WASP-126 b, cap 2 → done ✔
Job `ae3ee3bbbb2f4e34`, done in 25 s. Best period 3.2891915676627064 d,
SDE 24.82, depth 0.2173%, classification "Strong Transit", diagnostic
PNG written. (Radius/depth under-recovery vs catalog is the known
pre-existing Stage-1 caveat, unchanged.)

### Test 4 — Invalid TIC 999999999 doubleperiod → clean failure ✔
Job `7117b2ebb82c400e`, failed in 10 s with the original error,
unmangled: `RuntimeError: No mission data found for TIC 999999999.`

### Test 5 — Build / serving ✔
`npm run build` succeeded; server restarted (kill port-8000 process,
`nohup .venv/bin/python -m uvicorn api:app --host 0.0.0.0 --port 8000`);
health ok; `/` serves `index-OYu1Pmn1.js`; built bundle greps positive
for "Double-period check".

## 5. Honest notes

- **Cap-2 attenuation (real, worth knowing):** the UI's fixed
  sector_cap 2 (mirroring FakeCheck) reads only the first two MAST
  products for TIC 308851365 — both FFI-cadence, 1,900 points — so the
  in-app check shows +0.53% at 10.8σ where the full data gives +1.09%
  at 37σ. Verdict and sign are robust, but treat the button as a
  screen: a borderline star deserves an uncapped run. Eclipse depths
  attenuate the same way (0.77%/0.60% at cap 2 vs 1.13%/1.08%
  uncapped — FFI pixel dilution + fewer points).
- **One text tweak mid-testing:** the first control run's flat-verdict
  sentence rendered "−0.00% ± 0.00%" (two-decimal rounding of genuinely
  tiny numbers). The `no-ellipsoidal-signal` branch now prints three
  decimals ("−0.003% ± 0.002%"). Metrics and verdicts were bit-identical
  on the re-run; only the sentence changed.
- **Test 1b matching the standalone run to the last digit** is not a
  coincidence to marvel at — tonight's standalone script used the same
  fetch/stitch and window definitions that were ported into the
  engine. It does confirm the port is faithful.
- The BLS refinement runs on the **raw** curve here (odd/even refines
  on the flattened one). Sector-level systematics survive in raw data,
  but the ±3% focused grid around a known-strong signal locked on
  cleanly in every test (2P within 0.04–0.16% of the supplied double).
- Server restart note: after relaunch, `/api/health` took ~15 s to
  answer (hunter.py import cost — lightkurve/astroquery). Normal for
  this app; not a hang.
- Nothing was pushed to GitHub, per instructions. Files changed:
  `hunter.py`, `api.py`, `frontend/src/doubleperiod.jsx` (new),
  `frontend/src/charts.jsx`, `frontend/src/views/{Observatory,
  Sweeper, HistoryView, Scanner}.jsx`, `frontend/dist/` (rebuilt),
  and this report.
