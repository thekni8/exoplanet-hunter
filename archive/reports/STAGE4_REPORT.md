# Exoplanet Hunter — Stage 4 Report

**Date:** 2026-11-02 · **Scope:** Stage 4 only — give the live app the soul
of Gemini's v1 app (see GEMINI_V1_ANALYSIS.md) as the default experience,
fixing v1's three fatal pains: (1) it died after ~10–15 stars (Streamlit
1 GB RAM + in-request execution), (2) results were ephemeral (manual PNG
saving before a rerun wiped them), (3) no routing (hit details had to be
retyped into the QA tab by hand). No existing endpoint or view was
removed or changed in behaviour; all API changes are additive.
Real NASA data only — every number below is from a real run.

**How each v1 pain is fixed by this build**
1. *Died at quantity* → scans are background jobs on the Stage 2 queue
   (one at a time, always finish the full screened list), on Codespaces'
   8 GB instead of Streamlit's 1 GB. Nothing about a scan runs inside a
   web request.
2. *Ephemeral results* → every scan is a persisted job; hits are in the
   hits-only discoveries table (SDE ≥ 8.5, unchanged rule), and the
   Scanner view reloads the most recent scan's hits from History on
   every visit, labelled with its date. Nothing to save by hand.
3. *Manual retyping into QA* → every hit card has an "Is it a fake? →"
   button that runs the odd/even check with that hit's TIC **and found
   period** pre-loaded, and "Open in Observatory" (Stage 3 routing)
   beside it.

## What was built

### `hunter.py` (engine — additive only; originals untouched)

- **`is_already_known_online(tic_id)`** — faithful port of v1's
  Zooniverse check: GET
  `https://talk.zooniverse.org/searches?section=project-5733&query=<tic>&types[]=comments&types[]=discussions`,
  header `Accept: application/vnd.api+json; version=1`, timeout 5 s;
  True iff HTTP 200 and `searches` is non-empty. **Fail-open**: any
  error returns False. Verified live from this VM (see tests).
- **`sweep_sky(..., check_known=False)`** — new keyword, default off
  (original behaviour byte-identical). When on, each screened star is
  checked BEFORE download; known stars are skipped, counted, and
  reported via progress messages + the closing summary line. The
  return contract (list of hit dicts) is unchanged, so the CLI/menu
  paths are untouched; the count that flows to the product UI lives in
  the API summary (below).
- **`odd_even_test(tic_id, period_days, sector_cap=None,
  progress_callback=None, detrend_window=101)`** — v1's QA Validation
  Lab rebuilt: download/stitch/flatten exactly like `analyze_target`
  (shared front-half helper `_fetch_flattened`; renders NO PNG, logs
  NOTHING to discoveries.csv — it judges a candidate, it doesn't
  discover one), then:
  - **Period/epoch refinement (documented deviation from a naive
    port):** folding at exactly 2× a catalog period smears over long
    baselines (a 0.25% period error drifts a full period over
    ~1,300 days). A focused BLS scan (±2% around the supplied period,
    401 points, the pipeline's standard durations) recovers the fit
    period, transit epoch and duration from the data; the fold uses
    the fit period. Both periods are returned/reported.
  - Fold coordinate s ∈ [−P, +P); dip centers at −P/2 (odd) and +P/2
    (even) — v1's plot geometry.
  - Depth of each dip = 1 − median flux within ±half_window of its
    center, half_window = 0.04·P clipped to [0.02 d, 0.25·P]
    (documented choice: wide enough to average down noise, narrow
    enough to stay clear of the other dip; it is ~2× the typical dip
    duration, so absolute depths are diluted ~2× — but equally for
    both dips, which is what the comparison depends on).
  - Verdict: relative difference |odd−even| / max(odd, even) ≤ 0.25 →
    `planet-like`; beyond → `likely-eclipsing-binary`; no positive
    dip at either position → `inconclusive`. Also returns the ratio
    and a plain-language `verdict_text` sentence.
  - Returns scalars + arrays: folded scatter (sorted), 60-bin median
    overlay (v1's clean line), centers, window.
- **`odd_even_test_json(...)`** — JSON mirror in
  `analyze_target_json`'s pattern: `metrics` (incl. given/fit periods,
  depths + percents, ratio, rel. diff, verdict, verdict_text, sectors,
  points) + `folded` (downsampled scatter, binned medians, centers,
  axis range).

### `api.py` (additive only — all Stage 2 fields intact)

- **`POST /api/oddeven`** `{tic, period, sector_cap?}` → queued job
  (new type `oddeven`, same single-worker queue). Runner stores the
  full payload at `data/results/<job_id>.json` (so
  `GET /api/jobs/{id}/result` returns metrics + folded chart arrays)
  and the metrics dict as the job summary. No discovery is recorded.
- **`POST /api/sweep` gains optional `scanner: true`.** In the sweep
  runner, scanner mode forces v1's catalog screen (Tmag 13.5–15.4,
  radius 0.2–1.5 R☉; the request's filter values are ignored), runs
  the Zooniverse check per candidate before download, and the job
  summary gains two additive fields: `"scanner": true` and
  `"skipped_known": <count>`. Discoveries logging is EXACTLY as
  before (hits only, SDE ≥ 8.5); the SDE ≥ 11 "unflagged" bar is
  presentation-only in the UI, per the brief.

### Frontend (React — dark zinc theme kept, zero simulator code)

- **`src/views/Scanner.jsx` (new, the default home view)** — v1's
  face: pre-filled RA 124.456 / Dec −67.568 (v1's exact patch), search
  radius slider 0.01–1.0° (default 0.10), "Stars to scan" slider
  5–100 (default 20), ONE big primary "Initialize Scan" button, and
  plain-English microcopy (hunts new unflagged signals; known stars
  skipped automatically; scans are saved). During a scan: ONE progress
  bar + ONE friendly status line derived from the job's real progress
  stream ("Scanning star 7 of 20…", "Skipping stars that are already
  known… (3 skipped so far)"); the raw engine log lives only under a
  "Detailed log" expander. Results: count summary ("Scanned N · X
  already known / no usable data · Y nothing found · Z strong
  signals"); SDE ≥ 11 hits as bold cards — "🎯 NEW UNFLAGGED SIGNAL —
  TIC …", period (days), approx. planet size, SDE — each with
  **"Is it a fake? →"** (runs the odd/even job with TIC + found period
  pre-loaded; renders the odd/even chart and a plain verdict sentence:
  "The two dips match — this looks planet-like." / "The dips are
  different sizes — this is likely a binary star faking a planet.")
  and **"Open in Observatory"**; 8.5 ≤ SDE < 11 hits as a quieter
  "Weaker signals" list (same two buttons). On load, the view fetches
  History, finds the newest finished scanner sweep, and re-displays
  its hits under "Your last scan — <date>".
- **`src/charts.jsx`** — new `OddEvenChart`: draw-once canvas in the
  existing style; brightness-drop percent vs folded days, gray cadence
  scatter, crimson 60-bin median line, dashed center markers labelled
  "Odd dips" / "Even dips" (crimson / blue).
- **`src/App.jsx`** — default view is now `scanner`; nav regrouped:
  "Deep Space Scanner" first under "Start here", then an "Advanced
  tools" divider with the unchanged Observatory / Sky Sweeper / QA
  Benchmarks / History & Discoveries. Global settings sidebar
  untouched.

## Test evidence (all real, this VM, real MAST/Zooniverse)

### 1. Zooniverse check is live (not silently failing open)
Raw probes of the exact endpoint from this VM for TICs 25155310,
261136679, 307218289 → **HTTP 200** with a well-formed `searches`
array, **0 results** for each — i.e. the check genuinely asks
Zooniverse and these TICs genuinely have no Talk search hits under
that query; `is_already_known_online` returned False accordingly.

### 2. Odd/Even engine test — WASP-126 b (TIC 25155310, period 3.2822, sector_cap 2)
Direct call to `hunter.odd_even_test_json`, BEFORE wiring the UI:
- Wall time **16.9 s**; 2 sectors, **36,535 points** (the same dataset
  Stages 1–3 verified).
- Focused BLS refinement: supplied 3.2822 d → **fit 3.28876 d**,
  duration **0.132 d** (identical to Stage 1's BLS duration), fold at
  6.57753 d, half-window 0.1316 d.
- **Depth odd = 0.0852% · Depth even = 0.0813%** · ratio **0.955** ·
  relative difference **4.5%** → **verdict: planet-like** ✓ (a real
  planet, as expected; dips roughly equal, as required).

### 3. API end-to-end — odd/even job (server: new api.py on :8000)
`POST /api/oddeven {"tic":"25155310","period":3.2822,"sector_cap":2}`
→ job `e4f829a43a3048f0`: queued → running → **done in ~10 s** (warm
cache). Job summary metrics identical to the direct engine run
(3.28876 d fit, 0.0852% / 0.0813%, planet-like).
`GET /api/jobs/e4f829a43a3048f0/result` → full payload: `metrics` +
`folded` with **3,654 scatter points, 60 binned points, centers
−1.6443822 / +1.6443822 d** (= ∓P/2 of the fit period ✓).

### 4. API end-to-end — scanner-mode sweep at v1 defaults, limit 3
`POST /api/sweep {"ra":124.456,"dec":-67.568,"cone":0.10,"limit":3,
"scanner":true}` → job `d78cdb6763c94b5d`: **done in ~3 min 16 s**
(04:25:02 → 04:28:18 UTC, cold downloads).
- Screened exactly 3 targets under the **v1 filter** — TICs 307164903
  (Tmag 15.1, R 0.88), 307164915 (Tmag 15.1, R 1.20), 307164924
  (Tmag 15.1, R 1.40). Proof the override engaged: Tmag 15.1 stars
  would be **excluded** by the normal sweep screen (max_mag 15.0).
- Zooniverse check ran before every download: **skipped_known = 0**
  (all three TICs returned no Talk hits — consistent with test 1).
- Each target analyzed for real (2 of 17 sectors each, BLS 10,000):
  **targets_analyzed 3, hits 0, errors 0** — a quiet patch of sky is
  the honest outcome here; the machinery, counts and summary shape
  (`"scanner": true, "skipped_known": 0` alongside every pre-existing
  field) are verified. No star crossed SDE 8.5, so — correctly — no
  discoveries rows were added by this scan.
- Discoveries correctly stayed at the 2 pre-existing Stage 3 rows
  (verified below), since nothing crossed the threshold.

### 5. Build + serving + regressions
- `npm run build` **succeeded** (Vite 5.4.21, 1,590 modules):
  JS **198.8 kB (gzip 60.3 kB)**, CSS 19.5 kB. Bundle contains the
  Stage 4 strings ("Deep Space Scanner", "Initialize Scan", "NEW
  UNFLAGGED SIGNAL", "Is it a fake", "Odd / Even Dip Comparison").
- Simulator grep (Stage 3 rule — `generateAstrophysicsData`,
  `INITIAL_SWEEP`, `pseudoRandom`) over `src/` and the built bundle:
  **none**. `Math.random` in `src/`: none.
- Server restarted via **`bash run.sh`** (skips rebuild, serves new
  dist): `GET /` → app HTML referencing the new bundle; JS asset
  `200 text/javascript, 198,934 B`; `/health` → `{"ok": true}`;
  `/openapi.json` lists all **10 routes** (9 old + `/api/oddeven`).
- `/api/history` newest-first: the scanner sweep (params show
  `"scanner": true` — the exact key the Scanner view's last-scan
  loader matches), the oddeven job, then the untouched Stage 2/3
  analyze jobs. `/api/discoveries` still returns the 2 Stage 3
  WASP-126 b hit rows (SDE 21.86) — hits-only rule intact.
- Analyze regression under the new code: invalid-TIC job
  `eb210f26d76e4be8` failed cleanly in ~16 s with the real
  `RuntimeError: No mission data found for TIC 999999999999.` —
  Stage 2 behaviour preserved; the queue never wedged (it processed
  oddeven → sweep → analyze in submission order all session).

## Deviations & honest notes

- **Fold uses a data-refined period** (±2% focused BLS around the
  supplied period) instead of folding at exactly 2× the supplied
  value — necessary to keep the fold coherent over long baselines
  (see method above). The supplied period is reported alongside
  (`period_given_days` vs `period_fit_days`) everywhere it matters.
- **Absolute odd/even depths read ~2× shallow** (0.085% measured vs
  the engine's 0.204% BLS depth for WASP-126 b) because the prescribed
  ±0.04·P median window is ~2× the dip duration, so ~half the window
  is baseline. The dilution is symmetric between the two dips, so the
  ratio/verdict — the actual product of this test — is unaffected.
- **Zooniverse semantics are v1's, faithfully**: the Talk *search*
  endpoint matches discussion text; it is a heuristic "someone has
  talked about this TIC number", not an authoritative known-planet
  registry. It can miss known planets and the three TICs probed here
  returned no hits. Fail-open means a Zooniverse outage degrades the
  scanner to a plain sweep, never to a broken one.
- **`hunter.sweep_sky`'s skipped-known count** travels via its
  progress stream + summary line (its list-of-hits return contract is
  Dev's original and was not changed); the structured count for the
  product lives in the API sweep summary, which is what the UI reads.
- **Scanner recipe scope:** the brief mandated the v1 catalog screen +
  known-check for scanner mode; those are exact. Per-target analysis
  deliberately reuses the standard engine settings (sector cap 2, 10k
  BLS grid, detrend 101) rather than v1's flatten-71 / 20k-grid /
  single-pipeline-≥2-sectors variants, keeping scanner results
  comparable with Sweeper/Observatory results and discoveries.
- **Visual check remains compile-and-serve verified** (no headless
  browser on this VM, same as Stage 3) — first Codespace launch after
  this stage is again the visual test. The Scanner's last-scan section
  will show today's real scanner job (limit-3 test scan, 0 hits) until
  Dev runs a bigger one.
- The VM's old Stage 3 server was stopped; a server from `bash run.sh`
  is **left running** on 0.0.0.0:8000 with all Stage 4 test jobs in
  history. Nothing was committed or pushed.
