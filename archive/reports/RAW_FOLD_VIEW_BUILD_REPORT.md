# Raw-Fold View — Build Report

**Date:** 2026-11-04 · **Scope:** import the one advantage of Gemini's pilot
Colab QA (`gemini_pilot_qa_odd_even.py`) — the RAW unflattened fold plot —
into the app's odd/even check as an exhibit under the numeric verdict.
Built and tested on Pingu's server; **not pushed** (parent pushes).

## Why

The numeric odd/even test judges **flattened** flux. On TIC 294665246 the
flattening ironed a stormy light curve into two tidy "matching" dips and
the check passed the star planet-like (odd 0.385%, even 0.362%); only the
sector-persistence stage convicted it (BLEND-SUSPECT). Dev, looking at the
Gemini Colab cell's raw fold, called it "mayhem" by eye in one glance.
This build gives the app that same raw view — with our numeric verdict
kept as the judge, byte-for-byte unchanged.

## Design

### Backend — `hunter.py`

- `odd_even_test` computes the numeric verdict exactly as before, then
  builds the exhibit from a **separate raw fetch**: `_fetch_raw` (the
  double-period check's raw path — same sector set, lightkurve-cached,
  no new network cost beyond cache hits).
- Fold: 2 × the **refined** period with the **same refined epoch** as the
  numeric fold, using the identical coordinate formula, so the two dip
  families land at s = −P/2 / +P/2 and the frontend markers sit on the
  events. (Deliberate difference from the Colab cell, whose default-epoch
  markers are nominal.)
- Display processing only: NaN removal → 5.0σ clip (Gemini-style) →
  median normalization to brightness % (×100). `_fetch_stitched` already
  applies NaN removal + σ=5 outlier removal to the stitched curve; the
  exhibit's clip is a second, display-only pass on the folded values.
- Failure of the raw fetch is caught, logged to progress
  ("Raw-fold exhibit unavailable (…) — numeric verdict unaffected."),
  and degrades to `raw_fold = null`. The check never fails over the
  exhibit. (Verified by forced-failure test, below.)
- `odd_even_result_to_json_dict` stride-downsamples the points to at
  most `RAW_FOLD_MAX_POINTS = 15000` (same `_downsample_pair` idiom as
  every other series in the payload).
- The full (non-JSON) result dict gains `raw_folded_time_days`,
  `raw_folded_brightness_pct`, `raw_fold_total_points` (arrays / None).
- Module docstring records this as bridge addition (i). `api.py`
  untouched — `_run_oddeven` already stores the full payload, so
  `raw_fold` flows to `/api/jobs/{id}/result` automatically.

Payload shape (`odd_even_test_json` result, new top-level sibling of
`metrics` / `folded`):

```json
"raw_fold": {
  "fold_period_days": 27.967334039999997,
  "points": [[-13.9836, 100.42], ["s_days", "brightness_pct"], "..."],
  "n_total": 207792,
  "n_shown": 14843
}
```
or `"raw_fold": null` when the raw fetch failed.

### Frontend — `charts.jsx` + `fakecheck.jsx`

Note on location: the brief pointed at `components.jsx`, but the shared
odd/even result panel used by Scanner, Sweeper, History and Observatory
is `FakeCheck` in **`frontend/src/fakecheck.jsx`** (components.jsx holds
only generic Panel/Field/Metric widgets; the QA view runs analyze
benchmarks and renders no odd/even panel). The panel was patched where
it actually lives, so every view that shows an odd/even verdict gets
the exhibit.

- New `RawFoldChart` in `charts.jsx`, following the `OddEvenChart`
  canvas idiom (`setup`/`axes`/`rangeOf`/`ChartShell`): gray scatter of
  the raw points (no binning line — the rawness is the point), dashed
  100% median line, dashed vertical markers at −P/2 (crimson,
  "Odd Transits (Dip 1)") and +P/2 (dodgerblue, "Even Transits (Dip 2)"),
  y ticks in % ("Brightness (%)"), x ticks in days; shell title exactly
  **"Raw fold — unflattened data (what the star actually looks like)"**,
  right slot reads "x: Days from Center · y: Brightness (%) · N of M points".
- `FakeCheck` renders `<RawFoldChart>` directly under `<OddEvenChart>`
  when `result.raw_fold` is present; renders nothing extra when null.
- Frontend rebuilt (`npm run build`): new bundle
  `dist/assets/index-_ugEdOvO.js`; `dist/index.html` updated to reference
  it; CSS bundle byte-identical (same hash `index-D9VV5TYh.css`).
  Bundle grep confirms "Raw fold — unflattened data" and
  "Odd Transits (Dip 1)" are in the shipped JS.

## Test evidence

Method: the same harness ran **before** the change (baseline) and after,
calling `odd_even_test_json` directly; the after-run programmatically
asserted float-equality of verdict / depth_odd / depth_even /
depth_ratio / period_fit_days / fold_period_days against baseline.

### 1. TIC 294665246 @ P 13.8906, cap 20 — the mayhem star

- Numeric metrics **identical** to baseline and to the vetting record
  (SWEEP2_VETTING_REPORT): verdict **planet-like**, odd depth
  0.385709%, even depth 0.360413%, ratio 0.934417, refined period
  13.983667 d — the flattened judge still says what it said; the
  exhibit is what changes.
- `raw_fold`: fold period 27.967334 d, **n_total 207,792**,
  **n_shown 14,843** (≤ 15,000 ✔).
- **Storm preserved:** brightness range **78.95% … 120.68%**
  (assertions: max > 115% ✔, min < 85% ✔), median 100.02%. The raw
  fold is decisively NOT flattened — the mayhem is visible in the
  payload exactly as it was in the Colab plot.

### 2. WASP-126 b (TIC 25155310) @ P 3.2822, cap 2 — the real-planet control

- Verdict **planet-like**, metrics identical to baseline (odd 0.085156%,
  even 0.081337%, ratio 0.955163 — matches DOUBLE_PERIOD_REPORT test 3a).
- `raw_fold`: n_total 36,535, n_shown 12,179.
- **The real dip is visible in the raw data:** median brightness inside
  the odd dip window (487 shown points) = **99.7552%**, vs out-of-window
  baseline median **100.0074%** — the transit sits ~0.25% below baseline
  in unflattened data; the even window likewise (99.7781%). A genuine
  dip survives in raw; 294665246's does not need to — its "dip" was
  manufactured by flattening, and its raw fold is a storm instead.

### 3. TIC 308851365 @ P 0.75873, cap 2 — regression, with a correction

- Metrics **identical** to baseline: depths 0.755663% / 0.885983%,
  ratio 0.852909, refined period 0.756681 d; `raw_fold` present
  (n_total 1,895, range 94.78% … 103.66%).
- **Correction to the brief's stated expectation:** the odd/even verdict
  for this star is **planet-like**, not "likely-eclipsing-binary" — and
  it has never been otherwise. The project's own record
  (CANDIDATE_TIC308851365.md) documents odd/even as planet-like at two
  data depths (12 sectors: 1.312% vs 1.260%; 2 sectors: 0.756% vs
  0.886% — the 2-sector numbers reproduce here exactly). Twin stars
  with near-equal eclipses are odd/even's documented blind spot; the
  binary conviction for 308851365 belongs to the **double-period**
  check (+1.09% quadrature wave at 37σ). The regression invariant —
  numeric output unchanged by this build — holds float-for-float.

### 4. Degrade path (forced failure)

With `hunter._fetch_raw` monkeypatched to raise, `odd_even_test_json`
for TIC 308851365 still returned verdict planet-like with
`"raw_fold": null` and the progress line
"Raw-fold exhibit unavailable (…) — numeric verdict unaffec
...[truncated 2115 chars]