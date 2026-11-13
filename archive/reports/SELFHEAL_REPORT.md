# Exoplanet Hunter — Stage 5: Self-Healing Downloads

**Date:** 2026-11-03 · **Scope:** `hunter.py` only (API/frontend unchanged).
All changes are in the download step shared by `analyze_target` /
`analyze_target_json` (via `_run_pipeline`), `odd_even_test` (via
`_fetch_flattened`) and `sweep_sky` (per-star analyzes + its TIC-catalog
query). Happy-path behaviour, progress messages, return contracts,
discoveries logging and CLI paths are unchanged.

## Headline fix: a bad product can no longer kill a run

Downloads are now **per product**. The old code called
`search.download_all()`, so one unreadable product failed the entire
job. Now each product is downloaded individually with self-heal
treatment; a product that still cannot be read is **skipped** with a
plain progress line —

```
Sector/product file unreadable — skipping it and continuing with the rest
```

— and the analysis proceeds on the remaining sectors. The job fails
only if **zero** products download, in which case the original error
is raised.

### Why skipping is necessary (two-machine evidence)

Dev hit two failures on TIC 308851365 (17 sectors) on 2026-11-03:

1. `ConnectionError: ('Connection aborted.', RemoteDisconnected('Remote
   end closed connection without response'))` — MAST dropped the
   connection mid-download; the job died.
2. On retry: `LightkurveError: Error in reading Data product
   .../hlsp_t16_tess_ffi_s0001-cam4-ccd3-..._llc.fits of type generic.
   This file may be corrupt due to an interrupted download...` — the
   interrupted download had left a truncated file in the cache,
   poisoning every later run.

Purge + re-download (the first version of this fix) turned out **not**
to be sufficient for that sector-1 HLSP product: on this machine the
purge-only build retried job `a729d13f8af544c1` three times, and every
fresh download of
`hlsp_t16_tess_ffi_s0001-cam4-ccd3-05277232093330484096_tess_v01_llc.fits`
landed at exactly **322,560 bytes** and was still unreadable — and the
parent agent reproduced the identical failure on a clean machine with
a fresh cache and no interrupted download. The product is broken at
the source (or its transfer is deterministically truncated); no
amount of re-downloading heals it. Dev confirms the pattern from his
side: runs including that sector fail immediately; a 2-sector run
using other products worked. Hence: **skip it and carry on.**

## Design

New pieces in `hunter.py` (Stage 5, docstring item (g)):

- **`_exception_chain(exc)`** — walks `__cause__` / `__context__` /
  exception-valued `args` (requests/urllib3 nest the real failure
  several layers deep; in Dev's failure #1 the `RemoteDisconnected`
  sits in the `args` of a requests `ConnectionError`).
- **`_is_connection_error(exc)`** — true if any chain member is an
  instance of `requests.exceptions.ConnectionError`,
  `requests.exceptions.Timeout`, `urllib.error.URLError`, builtin
  `ConnectionError` / `TimeoutError` / `socket.timeout`; or its class
  name is one of `ConnectTimeout`, `ReadTimeout`, `Timeout`,
  `RemoteDisconnected`, `NewConnectionError`, `MaxRetryError`,
  `ProtocolError`, `IncompleteRead`, `ChunkedEncodingError`,
  `ConnectionResetError`, `ConnectionAbortedError`, `BrokenPipeError`,
  `SocketTimeout`, `SSLEOFError`; or its message contains a marker
  such as `remote end closed connection`, `connection aborted`,
  `connection reset`, `max retries exceeded`, `timed out`,
  `eof occurred in violation of protocol`, `broken pipe`.
- **`_corrupt_cache_paths(exc)`** — returns the `.fits` path(s) to
  purge when any chain member is a `LightkurveError` naming a file, or
  a message says `may be corrupt`, or a message mentions `corrupt`
  together with a `.fits` path (paths extracted by regex from all
  chain messages). Verified against the live error shape for both a
  `generic` HLSP product and a `TessLightCurve` SPOC product — the
  message format is identical.
- **`_with_download_self_heal(step, progress_callback, max_attempts=4,
  corrupt_max_retries=None)`** — bounded retry wrapper:
  - connection-class → wait 5 s, then 15 s; max 3 attempts for that
    class; progress: `Connection dropped — retrying (attempt N of 3)…`
  - corrupt → delete ONLY the named file(s), progress: `Removed a
    corrupt downloaded file and re-downloading…`, retry.
  - total attempts capped at 4 across classes; after the final failed
    attempt the **original** error is re-raised.
  - non-transient errors (e.g. `RuntimeError: No mission data found
    for TIC ...`) match neither class and propagate immediately.
- **`_download_products(sectors_to_fetch, tic_id, progress_callback)`**
  — per-product loop: each row's `.download()` runs through the
  wrapper with `corrupt_max_retries=1` (purge + re-download **once**,
  per product). Failures are skipped with the headline progress line;
  a short summary (`Continuing with X of Y product(s) — Z skipped.`)
  is emitted when anything was skipped. Successful products are
  gathered into a `lk.LightCurveCollection`, which the existing
  stitch/flatten path consumes unchanged (`n_sectors` now counts the
  products actually used).

Call sites:

- `_run_pipeline` and `_fetch_flattened`: the MAST **search** runs
  through the wrapper (it is a network call too); the download runs
  through `_download_products`.
- `sweep_sky`: per-star work already flows through
  `analyze_target` (covered). Its standalone `Catalogs.query_region`
  TIC-catalog call is wrapped with the same wrapper.
- **Analyze-path radius lookup: none exists.** `star_radius` is a
  caller-supplied parameter everywhere in `hunter.py`, so there was
  no separate network call to protect.
- Out of scope (noted): `api.py`'s own `_run_sweep` duplicates a
  `Catalogs.query_region` call (api.py line ~283) that is not wrapped;
  its per-star downloads *are* covered via `analyze_target_json`.

Per Dev's cache rule — "keep hits, purge junk/corrupt" — the only
files ever deleted automatically are the exact `.fits` files named by
a corrupt-read error. The manual full-cache purge (menu option 4) is
untouched.

## Test evidence

### Simulations (labelled as such)

Real MAST connection drops cannot be scheduled, so the connection
branch and the skip logic were verified with monkeypatched steps /
stubbed product downloads (`/tmp/test_selfheal_unit.py`,
`/tmp/test_selfheal_products.py` in the test session):

- Wrapper suite, 11/11 pass: production-shaped `ConnectionError`
  (requests error carrying `RemoteDisconnected` in args) once →
  healed, progress shows `attempt 2 of 3`, recorded backoff `[5]`;
  always-down → original exception re-raised after exactly 3 calls,
  backoffs `[5, 15]`; `No mission data found` → 1 call, no sleeps;
  corrupt → file deleted + healed; corrupt-forever → capped at 4
  attempts, original error raised. (`time.sleep` was replaced with a
  recorder.)
- Per-product suite, 9/9 pass: fake rows [good, corrupt-forever,
  connection-forever, good] → collection of the 2 good products;
  corrupt row attempted exactly 2× (purge + one re-download);
  connection row attempted 3×; exactly 2 skip lines + purge line +
  summary line; all-bad input raises the original `LightkurveError`;
  `corrupt_max_retries=0` → single attempt.

### Real tests through the API (local server, this machine's cache)

1. **Invalid TIC still fails fast** — jobs `c4fcdef4660e4dcb` and
   `1ef1eb1ea5b5448a` (TIC 999999999999): failed in <10 s with
   `RuntimeError: No mission data found for TIC 999999999999.`, no
   retries, no extra progress lines.
2. **Deliberate local corruption heals (test a)** — WASP-126 b
   (TIC 25155310) sector-1 SPOC file truncated to half
   (2,039,040 → 1,019,520 bytes; backup kept at
   `/tmp/wasp_s0001_test_backup.fits`). Analyze job
   `e76b4ba5151d4742` (`sector_cap: 2`): **done in ~40 s**; progress
   contains `Removed a corrupt downloaded file and re-downloading…`
   followed by a clean re-download. The cache file was re-downloaded
   to the full 2,039,040 bytes by the job itself (backup not needed).
   Metrics: period **3.28919 d**, SDE **24.82**, 2 sectors, 36,535
   points (point count identical to Stage 1).
3. **Regression (test b)** — same job: period 3.28919 d ≈ 3.29 ✓.
   SDE 24.82 at the 25,000-point BLS grid vs 21.9 recorded in Stage 1
   at an 8,000-point grid — SDE is grid-dependent (the 10,000-grid QA
   run in QA_CUSTOM_REPORT.md recorded 24.60), so this is consistent,
   not a regression; the pipeline math is untouched. Odd/even
   regression on the final build — job `98c6e34663634326`
   (TIC 25155310 @ 3.2822 d): verdict **planet-like**, depths
   0.0852 % / 0.0813 %, refined period 3.28876 d — byte-identical
   results to Stage 4, through the new per-product path.
4. **Must-pass: Dev's failing target now completes** — TIC 308851365,
   job `5ac9413e7aca4696`, `sector_cap: 12`: **done**. Progress shows
   5 products each going corrupt → purge → one re-download → still
   unreadable → `Sector/product file unreadable — skipping it and
   continuing with the rest`, then `Continuing with 7 of 12
   product(s) — 5 skipped.`, then BLS and completion. Metrics from
   the 7 surviving products:
   - period **0.75873 d** (Dev's 2-sector plate: 0.75677 d — same
     signal),
   - SDE **46.60** (classification "Strong Transit"; the 2-sector
     run had 16.1),
   - depth 1.218 %, duration 5.98 h, planet radius 12.04 R⊕ (at the
     API's default host radius 1.0),
   - 7 sectors analyzed, 7,181 total points.

### Not verified / honest limits

- A real, live mid-download connection drop healing end-to-end could
  not be scheduled; the connection branch rests on the simulation
  suite plus a classifier matched against the verbatim production
  exception (type, nesting and message).
- The 5 skipped products in the must-pass test are counted, not
  individually named, in the job log (progress narration is kept to
  one plain line per skip by design). The sector-1 t16 product is
  confirmed as one of them — it is the file named in every pre-fix
  failure, and it was re-downloaded again during this test to the
  same 322,560 bytes.
- Whether the other 4 products are broken at the source or were
  truncated by an interrupted batch download in this cache cannot be
  distinguished locally; either way purge + one re-download + skip
  handles them.
