# Custom QA Target — "Check your own star" — Report

**Date:** 2026-11-02 · **Ask (Dev):** the QA Benchmarks view only offers
the 3 built-in benchmarks (TOI-114, Pi Mensae c, WASP-126 b) — there is
no way to type a manual TIC ID. Fix: let a user QA **their own star**.

Everything below is additive. The 3 benchmarks, `hunter.run_qa`, and
the no-body `POST /api/qa` behaviour are untouched.

## The existing contract (read before changing anything)

- **Engine** — `hunter.run_qa()` iterates `QA_BENCHMARKS`
  `(name, TIC, star radius, expected period, sectors)` =
  TOI-114 (322307342, 3.59 d, 1 sector), Pi Mensae c (261136679,
  6.27 d, 2 sectors), WASP-126 b (25155310, 3.28 d, 1 sector). Each is
  run through `analyze_target(..., bls_points=10000, max_sectors=…)`.
  **Verdict rule: PASS iff |recovered − expected| < 0.05 d.**
- **API** — `_run_qa` maps each engine result to
  `{name, tic_id, expected_period_days, recovered_period_days,
  diff_days, status: "PASS"|"DRIFT", sde?, planet_radius_re?, error?}`
  and stores `{benchmarks: [...], passed, total}` as the job summary.
  `POST /api/qa` previously took an empty body and always ran all 3.

## 1. Backend — `api.py`

- **Request model:** `QaRequest` gains one optional field,
  `custom: Optional[QaCustomTarget]`, where
  `QaCustomTarget = {tic: str, expected_period_days: float, label?: str}`.
  No field / empty body → benchmarks, exactly as before.
- **Validation (in `post_qa`, clean 422s):** TIC must be all digits and
  > 0 (`"custom.tic must be a positive integer TIC ID"`); expected
  period must be within **0.1–100 days**
  (`"custom.expected_period_days must be between 0.1 and 100 days"`).
  Non-numeric values are rejected by pydantic with a 422 before that.
- **Runner:** `_run_qa` checks `params["custom"]` first; when present
  it runs exactly one target via the new `_qa_custom_entry()` helper
  and stores the **same summary shape** (`{benchmarks: [entry], passed,
  total}` plus `"custom": true`; the entry also carries
  `"custom": true`). The helper deliberately mirrors `run_qa`'s
  recipe: `analyze_target` with the same 10,000-point BLS grid and the
  same < 0.05 d PASS rule. Sector cap is 2 (top of the benchmarks'
  1–2 range) and host radius 1.0 — radius only scales the derived
  planet radius, never the period verdict. Job target label in
  history: `QA custom TIC <id>`. Failures land in the entry's `error`
  field with status DRIFT, matching how benchmark errors are reported.

## 2. Frontend — `frontend/src/views/QaBenchmarks.jsx`

- New **"Check your own star"** `Panel` below the benchmark cards /
  suite summary (benchmark cards and the Run QA Suite flow untouched).
- One explainer sentence: *"Found a candidate somewhere else? Type its
  TIC ID and the period you expect — the app re-runs the detection and
  tells you if it matches."*
- Two fields using the shared `Field` component with the range hints
  from the range-labels pass, identical wording to the Observatory:
  **TIC ID** — `Range: positive whole number`; **Expected period
  (days)** — `Range: 0.1 – 100` (with `min`/`max`/`step` attributes).
- **"Run QA check"** button styled like "Run QA Suite". Pre-submit
  guard reuses the established pattern (positive-whole-number TIC
  check from Observatory + `rangeError('Expected period', …, 0.1,
  100)`); an out-of-range value is never submitted — the message shows
  in the view's submit-error line.
- The custom job is polled with its own `useJobPolling` instance;
  progress streams in a `ProgressLog` under the panel, and the result
  renders as a card in the benchmark cards' visual language: TIC +
  name header, expected period, then the coloured result box —
  PASS/DRIFT badge with icon, Recovered period, Δ vs expected, SDE.

## 3. Real test evidence (no mocks)

**Bad-input rejections** (all against the running server):

| Request | Response |
|---|---|
| `{"custom": {"tic": "25155310", "expected_period_days": 500}}` | **422** — `custom.expected_period_days must be between 0.1 and 100 days` |
| `{"custom": {"tic": "abc", "expected_period_days": 3.2822}}` | **422** — `custom.tic must be a positive integer TIC ID` |
| `{"custom": {"tic": "25155310", "expected_period_days": 0.05}}` | **422** — period range message |

**Real run — WASP-126 b submitted as a custom target**
`POST /api/qa {"custom": {"tic": "25155310", "expected_period_days": 3.2822}}`

- **Job ID `e6e63a6c60ab48e3`** — status `done`
  (created 2026-11-02T18:29:53Z, finished 18:30:12Z; TESS data already
  in the local download cache).
- **Verdict: PASS** ✅ — recovered **3.28838 d** vs expected 3.2822 d,
  **Δ 0.00618 d** (rule: < 0.05 d). Recovered ≈ 3.29 d as expected
  from every prior Stage 1–4 run of this target.
- **SDE 24.60** (higher than the ~21.9 seen before because the custom
  path's 2-sector cap pulls more data than the benchmark's 1 sector —
  same engine, more sectors). Planet radius 5.07 R⊕ at the default
  1.0 R☉ host radius (benchmark card uses the known 1.30 R☉; radius
  does not affect the verdict).
- Stored summary: `{"benchmarks": [ {…, "status": "PASS",
  "custom": true, "sde": 24.604…, "planet_radius_re": 5.073…} ],
  "passed": 1, "total": 1, "custom": true}`.

## 4. Build & smoke test

- `cd frontend && npm run build` — **succeeded** (Vite, 1,591 modules):
  JS **`index-BTdLlTaS.js` — 224.25 kB (gzip 67.61 kB)**,
  CSS `index-XghstCMH.css` — 22.09 kB.
- **Simulator grep:** `src/` — zero hits for
  `generateAstrophysicsData`, `INITIAL_SWEEP`, `pseudoRandom`,
  `Math.random`. Bundle — zero hits for the three identifiers; the
  only 2 `Math.random` occurrences are React DOM internals
  (`_reactListening…`, `__reactFiber…`), same as every prior stage.
- Server restarted via `bash run.sh` (left running on :8000):
  `GET /health` → `{"ok": true}`; `GET /` serves the new bundle
  (`index-BTdLlTaS.js`, asset fetch 200, 224,725 B); the served bundle
  contains the new "Check your own star" panel.

**Files changed:** `api.py`, `frontend/src/views/QaBenchmarks.jsx`,
`frontend/dist/` (rebuilt). No git commit/push — left for the parent
agent (ritual after push unchanged: `git pull` → restart →
Cmd+Shift+R).
