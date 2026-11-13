# Sweep Persistence + Contamination Integration — Build Report

**Date:** 2026-11-04 (~03:00 IST) · **Status:** built + tested on this server, NOT pushed
**Scope:** `api.py` only (729 → 834 lines). `persistence.py`, `hunter.py` and the
frontend are untouched. No DB schema changes; discoveries logging semantics unchanged.

## What was built

The two vetting stages that killed both blend mirages of the first sweeps now run
**inside** `api.py`'s `_run_sweep` — the shared path, so Sweeper and Scanner modes
inherit both. Runtime cost is confined to hits (one extra pipeline run per hit,
inside `persistence.py`'s own design); non-hit stars see no behaviour change
beyond one new field.

### 1. Contamination at screen time (flag only)

- Verified live: the `Catalogs.query_region(..., catalog="TIC")` result used by
  the sweep **does include a `contratio` column** (confirmed against MAST,
  2026-11-04). When the column is present, each target's value is read from its
  catalog row — screen time stays a single catalog call, no per-star ExoFOP
  fetches. When absent, entries record `null`.
- Values pass through `_clean_catalog_float`: NaN / masked / unparseable → `null`,
  so the field is always present and always JSON-safe.
- Every analyzed entry now carries `"contratio"`. For **hits** with
  `contratio >= 0.10` (`CONTAMINATION_FLAG_THRESHOLD`, api.py:90):
  - the hit entry gains `"contamination_flag": "high-contamination — blend risk"`;
  - the HIT progress line gains the suffix ` — high-contamination — blend risk`.
- **No star is dropped, skipped or deprioritized because of contamination.**
  (Reference points: the two mirages sat at ExoFOP 0.136 / 0.186; a real EB at 0.272.)

### 2. Persistence per hit (`_run_hit_persistence`, api.py:268)

In the hit branch, **after** `record_discovery` (which is byte-for-byte
unchanged and still happens first), the sweep calls
`persistence.sector_persistence(...)` — the exact module validated against
`CANDIDATE_374942698_FOLLOWUP.md` and used by the SWEEP2 vetting — at the hit's
own ephemeris (`best_period_days`, `t0_days`, `duration_hours` from the analyze
that produced the hit), with the sweep's own `sector_cap`, so the sector set is
the same first-N products the analyze just used (downloads cached). The stage's
internal pipeline chatter is muted; the sweep emits exactly **one** extra
progress line per hit.

Attached to the hit's JSON entry as a compact summary (not the full
per-sector table):

```json
"persistence": {
  "sectors_usable": 15, "sectors_with_dip": 4,
  "frac_ge_1p5sigma": 0.2667, "weighted_mean_depth_pct": -0.0422,
  "chi2": 147.03, "chi2_p": 2.82e-24,
  "module_verdict": "CONCENTRATED", "verdict": "fails-persistence — blend-suspect"
}
```

Verdict labels (preset rules from the follow-up: CONSISTENT = ≥70% of usable
sectors ≥1.5σ **and** chi² p > 0.01; CONCENTRATED = ≤30%):

| persistence.py verdict | sweep label |
|---|---|
| CONSISTENT | `persistent` |
| CONCENTRATED | `fails-persistence — blend-suspect` |
| MIXED | `patchy` |
| NO USABLE SECTORS | `inconclusive` (extra label — see deviations) |

Progress-line formats (exact):

- `↳ persistence: {n_pos}/{n_usable} sectors, mean depth {wmean:.2f}% — persistent`
- `↳ persistence: {n_pos}/{n_usable} sectors, mean depth {wmean:.2f}% — patchy`
- `↳ persistence: {n_pos}/{n_usable} sectors — fails persistence — blend-suspect`
- `↳ persistence: no usable sectors — inconclusive`
- on stage error: `persistence check unavailable: {error}`

**Failure discipline:** the stage never raises into the sweep. Any exception is
caught, logged as the `persistence check unavailable: ...` line, and the hit —
already recorded in discoveries — stands exactly as before.

## Deviations from the brief (all measured, none silent)

1. **Wiring test ran at sector_cap 3, not 2.** Direct measurement of the wiring
   target through the production analyze: cap 2 → **SDE 8.36** (a hair *below*
   the 8.5 hit bar — the first sweep attempt at cap 2, job `a271c1598cc1427a`,
   duly produced 0 hits); cap 3 → **SDE 17.30**; cap 4 → SDE 16.77 (and recovers
   the true 1.512 d period). The test was re-run at cap 3, the smallest cap that
   produces the engineered hit. The machinery asserted is identical.
2. **TIC 308851365's TIC `contratio` is NaN** in the catalog, so its hit entry
   carries `"contratio": null` — the field is present and the sanitization path
   is itself part of what the test exercised. (Its blend-risk flag therefore
   correctly did not fire.)
3. **One extra verdict label, `inconclusive`**, covers persistence.py's fourth
   outcome (`NO USABLE SECTORS`), which the brief's three labels don't reach.
   It occurs only when a hit's sectors contain no fully-covered transit event
   by the persistence definition.
4. The persistence stage re-derives fluxes via persistence.py's internal
   pipeline run (bls_points 10000, the sweep's sector cap) — that is the
   validated module's design; the *ephemeris* it measures at is the sweep
   analyze's own. No part of persistence.py was rewritten.

## Test evidence (all runs 2026-11-04, test server on port 8001; port 8000 untouched)

### A. Wiring test — real API sweep engineered to hit · job `35e60efe95854993`
Cone on TIC 308851365 (RA 122.5655, Dec −63.5582, cone 0.1°), screens
Tmag 13–15.5, rad 0.2–1.0, limit 1, sector_cap 3, scanner off → 1 target,
1 hit. Progress (verbatim tail):

```
HIT: TIC 308851365 — P=0.7622 d, SDE=17.3
↳ persistence: 2/3 sectors, mean depth 0.78% — patchy
Sweep complete: 1 hit(s) with SDE >= 8.5 out of 1 target(s).
```

Result-JSON hit entry carries `"contratio": null` and the full persistence
block: usable 3, with-dip 2, frac 0.667, weighted-mean depth 0.778%,
chi² 12.20, chi² p 0.00224, module verdict MIXED → label `patchy`. (At 3
sectors the verdict itself is weak, exactly as the brief anticipated — both
CONSISTENT legs fail: frac 0.667 < 0.70 and p ≤ 0.01. The machinery, not the
verdict, was under test.) Assertions on field presence: **PASS**.

### B. Blend regression — TIC 231096116 at cap 20, direct stage invocation
Fed the integrated `_run_hit_persistence` the vetting ephemeris
(P 13.13836 d, T0 2148.53349, duration 5.976 h, data cached from SWEEP2):

```
entry.persistence = {sectors_usable: 15, sectors_with_dip: 4,
  frac_ge_1p5sigma: 0.2667, weighted_mean_depth_pct: -0.0422,
  chi2: 147.03, chi2_p: 2.82e-24, module_verdict: "CONCENTRATED",
  verdict: "fails-persistence — blend-suspect"}
progress line: "↳ persistence: 4/15 sectors — fails persistence — blend-suspect"
```

Matches SWEEP2_VETTING_REPORT.md (4/15 sectors, mean depth −0.04%): **PASS**.

### C. No-hit regression · job `eb845776672a4319`
RA 345.992 / Dec −22.568, cone 0.15°, defaults screens, limit 3, cap 2 →
3 analyzed, 0 hits, 0 errors. Summary keys exactly the pre-change set
`{ra, dec, cone, targets_total, targets_analyzed, hits, errors, scanner,
skipped_known}`: **PASS**. (An earlier attempt with tighter screens screened
0 targets — job `9e4b90448b2843fd` — and also completed with identical shape.)

### D. QA regression · job `c43c367386e3466a`
**WASP-126 b: PASS** — recovered 3.28838 d vs expected 3.28 d (Δ 0.00838 d),
Rp 11.31 R⊕. TOI-114 and Pi Mensae c report DRIFT, as they did before this
change: both were proven pre-existing during the depth-fix work (identical
failures under the pristine pre-fix `hunter.py`), and this diff does not touch
the QA path at all.

### E. Helper sanity + error path (direct, no server)
`_clean_catalog_float` NaN/garbage/None handling, label map, threshold
constant: PASS. Bogus-TIC invocation of the stage emitted
`persistence check unavailable: No mission data found for TIC 0.`, left the
entry untouched and did not raise: **PASS**.

## Cleanup / state restoration

- Test server (8001) stopped; port 8000 never started or touched.
- `data/hunter.db` restored from the pre-test backup — md5
  `7c23041c32f8403445c7e836691bfe70`, byte-identical; the test jobs and the
  wiring hit's discovery row exist only in this report.
- `discoveries.csv` restored byte-identical (md5 `e2beb4439d750b6216576008eecfaf70`);
  test-job files removed from `data/results` / `data/plates`.

## Files for the push (precisely these)

- `api.py` (modified — the only code change)
- `SWEEP_PERSISTENCE_BUILD_REPORT.md` (new — this file)
