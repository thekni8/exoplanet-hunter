# Sweep-Heal Report — deep retry budget for the TIC cone query (Stage 5c)

**Date:** 2026-11-03 · **Status:** built, tested on real data, server left
running on the new code. **Not pushed** (parent reviews and pushes).

## The failure

Dev's History, 2026-11-03 06:52 IST: a SWEEP job (RA 345.992,
Dec −22.568) FAILED outright with

```
ConnectionError: ('Connection aborted.', RemoteDisconnected('Remote end closed connection without response'))
```

before a single star ran.

## Diagnosis — verified in code (with one refinement)

The parent's diagnosis holds for `hunter.sweep_sky`: its cone query ran
under the shared self-heal budget (connection failures capped at
`_CONNECTION_MAX_ATTEMPTS = 3` attempts inside `_DOWNLOAD_MAX_ATTEMPTS
= 4` total), so a sustained MAST bad patch exhausted the retries and
the original `ConnectionError` killed the job.

**Refinement found while verifying:** the sweep that actually failed
came through the API, and `api.py`'s `_run_sweep` does **not** call
`hunter.sweep_sky` — it re-implements the sweep and called
`Catalogs.query_region(...)` **bare, with no retry wrapper at all**
(one dropped connection = instant death). The fix therefore had to
land on both cone-query call sites. It is implemented once, in
`hunter.py`, as a shared helper both paths now use; the `api.py`
change is a single call-site line.

Secondary wart confirmed: `hunter.sweep_sky`'s per-star `except` branch
only `print()`ed — a failed star never reached `progress_callback`, so
it was invisible in the UI. (`api.py`'s runner already reported
per-star failures to progress; unchanged.)

## Code changes

### `hunter.py`

1. **New constants** (beside the existing self-heal budgets):
   ```python
   _SWEEP_CONNECTION_MAX_ATTEMPTS = 8
   _SWEEP_CONNECTION_BACKOFF_SECONDS = (5, 15, 30, 60, 60, 60, 60)
   ```
2. **`_with_download_self_heal`** gained two optional kwargs —
   `connection_max_attempts` and `connection_backoff_seconds` —
   defaulting to the existing globals, so every current caller behaves
   byte-identically. The retry branch now uses the effective values
   (backoff index clamped to the sequence's last entry), and the
   progress line reads "Connection dropped — retrying (attempt N of
   M)…" with the effective M.
3. **New helper `_query_tic_cone_healed(coord, radius_deg,
   progress_callback)`**: runs the TIC `Catalogs.query_region` through
   the wrapper with `max_attempts=8`,
   `connection_max_attempts=8`, and the sweep backoff schedule.
   Corrupt-cache semantics and immediate propagation of non-connection
   errors are the wrapper's, unchanged. If every attempt fails with a
   connection-class error, it first emits
   `TIC catalog unreachable after 8 attempts — sweep aborted.` and
   then re-raises the original error.
4. **`sweep_sky`**: cone query now calls the helper. Its per-star
   `except` branch keeps the existing `print(...)` and additionally
   emits `TIC {tic_id} failed ({ExceptionClass}) — continuing with
   the next star.` to `progress_callback`.

### `api.py`

5. **`_run_sweep`**: the bare
   `Catalogs.query_region(coord, radius=cone * u.deg, catalog="TIC")`
   is now `hunter._query_tic_cone_healed(coord, cone, cb)` — the API
   sweep (including Scanner mode) gets the identical deep budget and
   progress/abort lines. (The function's local
   `from astroquery.mast import Catalogs` import is now unused; left in
   place deliberately to keep the diff to one line — it is harmless.)

### Retry schedule now in force (cone query ONLY)

8 attempts total; waits between attempts: **5, 15, 30, 60, 60, 60,
60 s** (≈ 4 min 50 s of persistence for one cheap catalog call).
Analyze / odd-even / double-period fetches keep the tuned shared
budget (4 total attempts, 3 connection attempts, 5 s → 15 s backoff).

## Tests — all real, through the running API (server restarted first)

### 1. MUST-PASS — the user's exact failed sweep

`POST /api/sweep {"ra": 345.992, "dec": -22.568, "cone": 0.10,
"limit": 20, "scanner": true}` → job **`bf3e0cb5938a473f`** →
**DONE** (no error).

- Cone query succeeded; `Screened 5 target(s); starting sweep (no cap
  beyond requested limit=20).` (112 catalog rows in the cone; the
  Scanner faint-dwarf screen leaves 5.)
- All 5 targets genuinely attempted and analyzed
  (`targets_analyzed: 5`, `errors: []`) — TIC 204317981, 204316124,
  204317973, 204316103, 204317967.
- Closing progress line: `Sweep complete: 0 hit(s) with SDE >= 8.5
  out of 5 target(s). Skipped 0 already-known star(s).`
- The run even exercised the older heals en route: two stars had a
  corrupt product purged/re-downloaded and one unreadable product
  skipped, and still completed.

### 2. Retry-engagement proof (LABELLED SIMULATION)

`/tmp/sweep_heal_sim.py` stubs `hunter.Catalogs.query_region`:

- **Scenario A** — raise the exact production error
  (`requests.ConnectionError` wrapping `RemoteDisconnected`) twice,
  then delegate to the real MAST query (real 5 s + 15 s sleeps):
  3 calls total, progress lines `Connection dropped — retrying
  (attempt 2 of 8)…` and `(attempt 3 of 8)…`, then success —
  112 catalog rows returned.
- **Scenario B** — always raise (sleeps stubbed to run the full budget
  instantly): exactly **8 calls**, retry lines for attempts 2–8, then
  `TIC catalog unreachable after 8 attempts — sweep aborted.`, and the
  original `ConnectionError` propagated unchanged.

### 3. Regressions (real, queued through the same API)

| Job | Test | Result |
|---|---|---|
| `bb7ba3cf699b4ac7` | analyze WASP-126 b, cap 2 | **done** — period **3.28919 d**, SDE 24.82, 2 sectors |
| `9f25e0be07284c20` | doubleperiod TIC 308851365 @ 0.75677, cap 2 | **likely-binary** — Δ **+0.533 %** at **10.82 σ**, P₂ refined 1.51328 d (matches the double-period build's cap-2 reference) |
| `c0c4575bd5044c50` | odd/even WASP-126 b, cap 2 | **planet-like** — odd 0.0852 % / even 0.0813 %, ratio 0.955 (Stage-4 reference numbers exactly) |

### 4. Server state

Restarted on the new code (old PID 19202 killed; relaunched with
`nohup .venv/bin/python -m uvicorn api:app --host 0.0.0.0 --port
8000`); `/health` → `{"ok": true}`; `/` serves the unchanged frontend
bundle `index-OYu1Pmn1.js` (no frontend changes, no rebuild).
Server **left running**.

## Anything unexpected

- The diagnosis refinement above (API sweep had *no* wrapper at all)
  is the one surprise; the fix covers both sweep paths through the
  shared helper, so `hunter.sweep_sky` (CLI/library use) and the API
  runner now behave identically at the cone query.
- The must-pass sweep's final star appeared stalled at "Querying
  MAST…" for several minutes; its progress tail showed it was in fact
  grinding through corrupt-product purge/re-download cycles (Stage 5
  heals) and it completed normally. Not related to this change.
