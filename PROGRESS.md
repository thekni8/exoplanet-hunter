# Quality-mask fix — PROGRESS.md

Fix for the flagged-cadence artifact failure mode the bulk_v2 rescore
gauntlet exposed (2026-11-14/15). Branch `fix/quality-mask`, based on
`standardize/phase-1` at HEAD 4acbc16. Dev authorized 2026-11-15
00:03 IST ("fix anything quality mask or whatever"). No push, no
merge — Dev runs the AI votes when he wakes.

## The finding (parent-verified)

The bulk_v2 rescore of S96 found 116 NEW survivors v1 missed. The
gauntlet vetted the 25 cleanest (tier-A non-systematic): 0 survived,
and 18/25 were flagged-cadence artifacts — dips of 1.5–9.3% present
ONLY in quality bit-29/30 cadences, with ZERO clean cadences in
transit in s96. Mechanism: bulk_v2's 10% MAD-clip floor keeps deep
flagged dropouts (4–9%) that v1's sigma-based clip removed, so v2
scores them above the survivor bar. The clip fix traded one failure
mode for another. Evidence: gauntlet ledger
`~/workspace/goals/exoplanet-hunter/hidden_files/science-vet/rescore-gauntlet-2026-11-14/LEDGER.md`
(the 18 artifact TICs; e.g. 382256433 9.10%, 207213492 9.25%,
381951178 8.98% unmasked dips, all RAW-REFUTED in clean data).
Same lesson earlier: TIC 344334378 (signal only in bit-30 cadences).

## Root cause (read from the code, 2026-11-15)

- `bulk_screen._screen_one` masks quality with lightkurve's TESS
  DEFAULT bitmask **17087** = bits [0,1,2,3,4,5,7,9,14]. TESS
  scattered-light flags **bits 29/30 are not masked**, so their
  cadences enter the detrend, the clip, and BLS.
- The mask is hardcoded in THREE places: `bulk_screen.py:926`,
  `bulk/rescore_v2.py:58` (`QUALITY_BITMASK = 17087`, used by
  `_load_flux` to compute clip levels), and
  `bulk/calibrate_analysis.py:37` (frozen historical proof-run
  analysis — left alone, see judgment call 6).
- `hunter.py` (deep pipeline) never filters on quality itself; it
  relies on lightkurve's default download mask (also 17087), so
  bits 29/30 pass there too. Out of scope here (see judgment
  call 5).
- The clean-data re-fold gate (`bulk/clean_refold_gate.py`) already
  exists and already FAILs this class (quality==0 fold at the
  ephemeris; validated on TIC 344334378 + two real signals). It
  runs as a gauntlet stage and as a standalone CLI on
  recalibrated survivors — it protects verdicts, not the screen.

## Design (judgment calls)

1. **Fix = quality mask at screen input (option a), NOT the gate
   as a mandatory pre-survivor stage (option b).** The mask is the
   root-cause fix: bad cadences never enter BLS, so BLS cannot
   lock onto polluted periods/aliases, and the survivor stream is
   clean at the source. The gate already exists downstream
   (gauntlet stage 1 + CLI) and already FAILs this class — it
   protects verdicts today. Adding it inside the screen would
   duplicate gate logic in `_screen_one` and change output
   semantics for no additional correctness once the mask is in.
   Defense in depth already exists downstream; the mask is the
   missing layer upstream.
2. **Bits = lightkurve default 17087 + bits 29 and 30.**
   New mask = 17087 | (1<<29) | (1<<30) = **1610629823**.
   Evidence: all 18 artifacts' in-transit cadences carry bits
   29/30. Bit 11 (stray light) appears on ONE artifact's
   cadences (207213492) but always alongside 29/30, so masking
   29/30 removes those cadences anyway — no independent evidence
   for masking it. quality==0 is REJECTED: the TOI-700 c lesson
   (proof run, 2026-11-11) — bit 12 (4096) carries a real
   transit; quality==0 deletes it. The mask must stay selective.
3. **Calibration = bulk_v3 (new version, supersedes bulk_v2).**
   The mask changes detection behavior (which cadences enter
   BLS), so v3 records are not comparable to v2 records without
   the version stamp. bulk_v2 has stamped real records (the
   S96–98 rescore) and is frozen — it cannot be amended. All v2
   thresholds carried over unchanged; only `quality_mask` is new.
   v1/v2 profiles predate the field and default to 17087 (same
   back-compat pattern as `clip_option`).
4. **One source of truth.** `bulk_screen.QUALITY_MASK` is derived
   from the profile in `_apply_profile`; `_screen_one` uses it.
   `rescore_v2._load_flux` uses `bs.QUALITY_MASK` instead of its
   hardcoded constant — behavior-preserving under v2 (the
   rescore hardcodes bulk_v2), and the two tools can no longer
   drift apart.
5. **Scope = bulk screen path only** (`_screen_one` + rescore).
   The deep pipeline (`hunter.py`) keeps lightkurve's default
   mask; its defenses are the pass-2 raw-flux gate + the gauntlet
   clean gate. Changing hunter would need a deep_v2 profile and
   a deep-pipeline sensitivity re-measurement — a follow-up, not
   this fix.
6. **`bulk/calibrate_analysis.py` left unchanged.** It is a
   frozen one-off analysis of the v1 proof run (nothing imports
   it); its hardcoded 17087 + 5-sigma clip deliberately replicate
   the v1-era screen. Updating it would rewrite a historical
   analysis. Noted here so the remaining hardcoded 17087 is a
   known, deliberate exception — not an oversight.

## Claims ledger

- [x] C-1: Under bulk_v3, flagged-only dips at the artifact
  periods/depths (12.64 d, 6.27 d; screen depths 0.5–2.9%;
  bits 29 and 30; flagged fractions 0.7 and 1.0) do NOT reach
  survivor status; under bulk_v2 the same fixtures DO (the
  failure reproduction). VERIFIED 2026-11-15 by
  `tests/test_quality_mask.py` (5 cells: all survivor/A under
  v2 with SDE 24.6–44.3, all below_floor under v3 with SDE
  4.2–4.5). Note: fixture depths are the SCREEN-measured depths
  from the ledger (0.5–2.9%), not the raw fold depths
  (1.5–9.3%) — real scattered-light ramps are not box-shaped,
  so BLS measures a shallower effective depth.
- [x] C-2: A clean WASP-29b-equivalent transit (P 3.9227 d,
  1.14%) still survives under bulk_v3. VERIFIED — survivor/A,
  SDE 50.0, identical under v2 and v3.
- [x] C-3: A real transit with scattered-light flags on
  non-transit cadences (10% flagged) still survives under v3.
  VERIFIED — survivor/A under v3 (SDE 46.1 vs 50.0 under v2).
- [x] C-4: A transit on bit-12 (4096) cadences still survives
  under v3 (the mask must not include bit 12). VERIFIED —
  survivor/A, SDE 50.0, identical under v2 and v3.
- [x] C-5: The full clip grid under bulk_v3 reproduces the v2
  numbers (deep-quiet 16/16, null FA 0/12, 0 monotonicity
  violations) — the mask is a no-op on clean data. VERIFIED —
  `EXHUNT_BULK_CALIBRATION=bulk_v3`, floor_10pct option, 60
  runs: summary dict identical to the committed v2 numbers
  (recovery_all 35/48, deep-quiet 16/16, null FA 0/12, 0
  monotonicity violations). Also pinned in CI by
  `test_monotonicity_under_v3` (v3 headline-pair SDEs equal v2's).
- [x] C-6: Flag-fraction sweep bounds the cadence-loss cost
  (recovery with realistic bits 29/30 fractions on
  non-transit cadences, mask on vs off). VERIFIED —
  `bulk/flag_fraction_sweep.py` (committed in M-5; the
  original /tmp script was lost to a VM replacement and
  rewritten from the SENSITIVITY_MAP.md §v3 table + this
  record — numbers close to the original's, not bit-identical):
  WASP-29b survives at every
  flag fraction (5/10/20%, all-cadence and off-transit-only);
  v3 SDE costs up to ~20% at 20% flagging (50.0 → 39.3) but
  MES preserved or improved in every cell (17.5 → 17.3–18.8);
  no real transit lost. One marginal shallow cell (0.5%,
  MES 8.5 under v2) crossed the other way under v3 at 10–20%
  flagging (MES 9.3, survivor A) — at the boundary the mask's
  MES effect can go either way; no systematic gain claimed.
  Table in `bulk/SENSITIVITY_MAP.md` §v3.
- [x] C-7: Frozen v1 calibration files byte-identical at the end
  (bulk_v1/deep_v1/gauntlet_v1); registry append-only (existing
  entries untouched); full golden suite green. VERIFIED
  2026-11-15 — `git diff 4acbc16` on all v1/v2 calibration
  files is empty; registry diff purely additive (7 insertions,
  0 deletions); full suite `--fast` PASS: 393 tests
  (385 offline at HEAD + 8 new), expected failures=1 (the v1
  xfail), 1142.7 s. Discovery count confirms 397 total incl.
  4 live tests (389 + 8).
- [x] C-8: `test_flagged_cadence_signal_gate_fails` updated to
  the new pinned behavior (v2 promotes + gate FAILs; v3 does
  not promote) with the behavior change stated in the commit.
  VERIFIED — commit f92d583 states the behaviour change; the
  gate's FAIL verdict is still pinned on the v2-promoted signal.

## Commits

Hashes below are the REBASED hashes (branch rebased onto
origin/main e55eaf2 on 2026-11-15, clean, 16/16, no conflicts).
Pre-rebase hashes: 169b0c8, 7e7770b, 2e56634, 7444ea5,
f92d583, 3a3cb22, 535cc16, dd6602f (original fix); 77fea01,
7e00ce3, b47afe8, 1c899fb, 0d5cd7d, 012a875, 365ae43, 5f24134
(M-1…M-12).

Original fix (8 commits; the list previously showed 7 —
dd6602f was missing — fixed in M-12):
- b353aba — design record (this file)
- bd2c378 — synth_fits: flag_bit parameter for flagged-only fixtures
- 0d031c5 — bulk_v3: quality mask excludes bits 29/30 at screen input (profile + registry + bulk_screen + rescore_v2)
- 3700456 — quality-mask regression tests (5 tests, artifact cells + guards)
- 899f3cf — pin the NEW flagged-cadence behaviour under bulk_v3 (test_false_positives)
- 55f3e74 — bulk_v3 profile values + v3 clip-grid monotonicity tests
- 165a66d — v3 section in SENSITIVITY_MAP.md, bulk_v3 row in calibration/README.md, claims ledger completed
- 905a536 — mark C-7 verified (frozen files untouched, full suite 393 PASS)

Vote follow-up (M-1…M-12, 2026-11-15):
- 815e81a — M-1: named flag constants (`quality_flags.py`,
  cited sources) + pin 1610629823 in a test
- 6696782 — M-2: clean-refold gate uses QUALITY_MASK (not
  quality==0) + bit-12 regression test through the actual gate
- 0327428 — M-3: rescore_v2 pins the v2 mask explicitly,
  `--profile` flag for a future bulk_v3 rescore
- edf217f — M-4: survivor records log raw in-transit flagged
  fraction + tally of unmasked bits
- 3bf5ae2 — M-5: flag-fraction sweep committed (seeded,
  re-runnable) + contiguous-block variant
- 096ce7b — M-6: injection-recovery into real S96 light curves
  carrying 29/30 flags, v2 vs v3 (v2 2/12, v3 8/12)
- b2212e2 — M-7: S96 25-lead replay under v3, v2 vs v3 (the
  merge gate — artifact signals gone 18/18, gates PASS)
- 14fb71f — M-8/M-9/M-10/M-11/M-12: grep record, ledger-note
  pointer, 7/25 breakdown, deep_v2 follow-up record,
  commit-list nit fixed, C-6 /tmp path corrected to
  bulk/flag_fraction_sweep.py
- (docs, this commit) — rebase hash update (this list)

## Vote follow-up (M-7 replay) — expected outcome, written BEFORE the run

2026-11-15 ~06:30 IST. The ~30-star S96 replay (M-7) is the merge
gate (Claude, 2026-11-15 vote): the 25 vetted rescore leads
(`leads25.json`, rescore-gauntlet-2026-11-14 — all tier A under
v2, SDE 11.5–29.2), screened under v2 (control: must reproduce
as survivors) and v3. Expected outcome, per gauntlet verdict:

| Group (n) | TICs | Expected under v3 |
|---|---|---|
| 18 flagged-cadence artifacts | 355401152, 382571558, 140599833, 149307626, 141865558, 33836426, 389501533, 294665553, 176959220, 381951178, 149060820, 260004306, 382256433, 370220679, 370228465, 55402407, 207213492, 38635773 | Below the survivor bar (below_floor or recorded). Their dips live ONLY on bit-29/30 cadences (0 clean in-transit); the mask removes the dip before BLS. The synthetic cells (test_quality_mask) all went below_floor. |
| 1 catalogued planet | 183537452 (WASP-29b / TOI-192.01) | SURVIVES (tier A, SDE ~29). A real planet on clean cadences; the mask must not touch it. |
| 2 real clean-data signals | 101945781 (era-confined V-shaped wave), 307433122 (harmonic alias, real 8–17% s96 dips) | SURVIVE. The gauntlet killed them on shape/era grounds, not flags — their signals are in clean data. v3 does not remove real signals. |
| 4 flagged-amplified weak dips | 41361938, 141708967, 142087258, 141680194 | SDE drops SHARPLY; expected below the survivor bar. They carry a small real clean dip (0.12–0.63%) amplified 2–10x by flagged dropouts; with the amplification gone, the clean dip alone should not clear the bar. Least certain group — the actual SDEs decide. |

Net expectation: v2 reproduces 25/25 survivors; v3 keeps 3
(WASP-29b + the 2 real signals) and drops 22 (18 artifacts + 4
amplified weak dips). Any artifact that still survives under v3
is a finding against the fix, not a pass. Any of the 3 real
signals dropping under v3 is a finding against the mask's
selectivity.

Actual result (2026-11-15 ~06:45 IST, script
`bulk/replay_s96_leads.py`, summary
`bulk/replay_s96_leads_summary.json`, 54 s):
- v2 control: 25/25 survivors, SDEs matching the ledger within
  0.5 on all 25 — the VM run reproduces the Mac rescore.
- v3 survivors: 6/25 (183537452, 101945781, 41361938,
  142087258, 294665553, 382256433). WASP-29b survives at its
  ledger period with SDE 59.1 (vs 29.2 under v2 — masking the
  flagged noise DOUBLED the real planet's SDE).
- **Artifact signals gone under v3: 18/18.** None of the 18
  reproduces its ledger period as a survivor; their SDEs
  collapse (11.5–26.5 → 4.7–12.2), mostly to `recorded`
  (SDE 6–11, no tier — the two-currency SDE+MES bar holds)
  or below_floor.
- The gate as FIRST written (star-level: "no artifact star
  survives") FAILED on three stars, and the investigation is
  recorded here because it changed the gate — see the
  refinement note in the script docstring:
  * 294665553, 382256433: the v3 survivors are at DIFFERENT
    periods (13.27 d, 20.0 d — the grid edge) with much
    shallower depths (0.28%, 0.35%) than the ledger artifacts.
    The artifact signals are gone; what survives is unrelated
    tier-B residue (2-event / 1-event detections). M-4 fields
    corroborate: under v2 frac_flagged=1.0 with unmasked bits
    29/30; the v3 detections have unmasked={}.
  * 307433122: v3 finds the SAME period at SDE 55.2 (vs 24.5)
    with the true depth 5.45% (vs 2.23% diluted) — and
    DEPTH_EB correctly demotes it. The mask un-diluted a real
    deep signal; the veto did its job.
  The gate was refined to test the SIGNALS (period match),
  which is what "the artifacts drop below the survivor bar"
  always meant. It is stricter in one dimension (it now
  checks the period) and the residue is reported, not hidden.
- **New finding (not a merge-blocker): tier-B residue.** 4
  stars survive under v3 via tier B at non-ledger periods
  (294665553, 382256433 + amplified 41361938, 142087258;
  plus 101945781, a real variable at a different peak of the
  same variability). Tier B's few-event bar (n_events < 3 +
  one strong event) admits single/double-event systematic
  residue. Pre-existing calibration property — tier B is
  unchanged by v3 — and the gauntlet kills 1–2-event
  survivors on persistence/holdout grounds. Follow-up for the
  post-merge acceptance rescore (count tier-B residue
  sector-wide); a tier-B tightening is a calibration decision
  for Phase 3, not this fix.
- The 4 amplified weak dips split 2/2 as the soft expectation
  allowed: 141708967 → recorded, 141680194 → below_floor;
  41361938, 142087258 survive via tier B at DIFFERENT periods
  (10.63 d, 10.26 d) — their 6.2683 d ledger signals are gone.
- Refined gates: ALL PASS (exit 0).

## What killed the other 7/25 (M-10)

From the rescore gauntlet ledger
(`rescore-gauntlet-2026-11-14/LEDGER.md`, 25/25 vetted,
0 survivors). The 18 flagged-cadence artifacts are above;
the other 7 were NOT flag artifacts:

| Group (n) | TICs | What killed them |
|---|---|---|
| 4 s96-only single-event / weak dips, flagged-amplified | 41361938, 141708967, 142087258, 141680194 | A small real clean dip (0.12–0.63%) amplified 2–10x by flagged dropouts; three share the P 6.2682513 d ephemeris. Killed on single-event / weak-dip grounds, not flags alone. |
| 1 catalogued known planet | 183537452 (WASP-29b / TOI-192.01) | Stage-0 catalogue kill. The v2 rescore RECOVERED a real planet v1 missed — sensitivity validation, not a failure. |
| 1 era-confined V-shaped variability | 101945781 | Late sectors only; T14 28 h vs 3.2 h max; brightens at phase 0.5. A variable star, not a transit. |
| 1 harmonic alias | 307433122 | Real 8–17% s96 dips, but unequal depths (6.6% vs 14.5%), absent in other sectors; free BLS finds strong sub-day signals (0.796 d SDE 34.4, 0.733 d SDE 26.1) = 11x/12x harmonics of the filed 8.77 d period. Possible short-period EB or spotted rotator on an M dwarf; unvetted as a variable-star lead. |

Follow-on (Claude, vote): the 10% clip floor lets any
UNFLAGGED dropout under 10% through too — the mask does not
address that class. The tier-B residue finding in M-7 is the
same family: single/double-event detections from unflagged
systematic residue. A clip-floor / tier-B tightening is a
calibration decision for Phase 3, not this fix.

## Other mask forms in the repo (M-8 grep)

Grep 2026-11-15 for `quality == 0`, `"default"`, `175`,
`1 << 29` / `2**29` / `2**30` / `1610629823`:
- `bulk/clean_refold_gate.py:60` — the clean-refold gate used
  `quality == 0` literally (ChatGPT's catch, confirmed).
  FIXED in M-2: the gate now takes QUALITY_MASK.
- `gauntlet/common.py:209` `load_tpf` — `m = (q == 0)` on
  TPFs for centroid/diffimg pixel work. Deep pipeline, out of
  scope for this fix — recorded here (see M-11).
- `gauntlet/rawflux_check.py:171` — `m &= (q == 0)`: the
  raw-flux tiebreaker DOES use quality==0 literally, so a
  genuine bit-12 transit would show no dip there and read
  RAW-REFUTED. A real instance of ChatGPT's catch in the deep
  pipeline; out of scope here, recorded for deep_v2 (M-11).
- `gauntlet/stage_result.py:404` — message string only
  ("clean (quality==0) flux"); updated in M-2.
- `archive/scripts/blend_stage2_folds.py`,
  `blend_stage3_diffimg.py` — frozen history, untouched.
- `"default"` bitmask: no direct code matches.
- Literal 17087: `bulk/calibrate_analysis.py:37` (frozen
  v1-era analysis, deliberately unchanged — leave it, record
  it), `bulk_screen.py` comments + the `_apply_profile`
  default (now the named constant, M-1), gate/rescore
  comments.
- `175`: no matches — no such mask form exists.
- `1<<29` / `2**29` / `2**30` / 1610629823: no code matches
  outside tests/YAML. The integer lives in
  `calibration/bulk_v3.yaml` + `calibration/registry.json`,
  pinned in `tests/test_calibration.py:121,142`,
  `tests/test_quality_mask.py:98`, and now in
  `tests/test_quality_flags.py` (M-1).

## Open follow-ups (not this fix)

- **Deep pipeline mask fix (deep_v2) — VERIFIED EXPOSED
  (M-11, 2026-11-15).** `hunter.py` uses lightkurve
  `search_lightcurve` + `row.download()` with NO explicit
  quality_bitmask anywhere, so lightkurve's reader defaults
  apply. For QLP files, `read_qlp_lightcurve` with
  quality_bitmask="default" = 17087 → bits 29/30 are KEPT
  (lightkurve only adds the QLP 2^30 flag under "hard" /
  "hardest", and never 2^29). For SPOC 2-min products, bits
  29/30 don't exist (16-bit QUALITY). Conclusion: the deep
  pipeline IS exposed to the flagged-cadence artifact class
  for QLP targets — the majority, since SPOC 2-min covers
  only ~10^5 stars/sector and the deep pipeline falls back
  to QLP. The fix is a deep_v2 profile + deep sensitivity
  re-measurement; it also needs the two deep-pipeline
  quality==0 uses found in M-8 (`gauntlet/common.py:209`
  load_tpf; `gauntlet/rawflux_check.py:171` — a genuine
  bit-12 transit would read RAW-REFUTED there). Needs Dev's
  go; not this branch. Durable home for this record: this
  file (travels with the branch) + a pointer in the goal's
  GOAL.md (Phase 1 section).
- A bulk_v3 rescore of S96–S98 (or at least the 116 NEW v2
  survivors) is the real-world validation of this fix — needs
  Dev's go + Mac time; the S97/S98 caches are being downloaded
  overnight for exactly this kind of work.
- The remaining 91 NEW v2 survivors (tier B/C + near-systematic)
  are very likely the same artifact class; v3 should kill most
  of them at screen time.

---

# Deep-pipeline quality-mask fix (deep_v2) — progress record

Branch `fix/deep-quality-mask`, off origin/main edbbc61 (after the
PR #4 live-timeout merge). Dev's go 2026-11-15 ~10:00 IST.
No PR, no merge — the parent reviews and decides on a vote first.

## The exposure (M-11, verified 2026-11-15)

`hunter.py` downloads through lightkurve with no explicit
`quality_bitmask`, so lightkurve's reader defaults apply. For QLP
files, `read_qlp_lightcurve` with quality_bitmask="default" =
17087 → bits 29/30 are KEPT (lightkurve only adds the QLP 2^30
flag under "hard"/"hardest", and never 2^29). Verified against
the installed lightkurve 2.6.0 during this build: the readers
REMOVE default-flagged rows at read time and keep the QUALITY
column on the survivors — so a post-download mask on the
surviving quality values is exactly the right placement. For
SPOC 2-min products, bits 29/30 don't exist (16-bit QUALITY).
Conclusion: the deep pipeline IS exposed to the flagged-cadence
artifact class for QLP targets — the majority, since SPOC 2-min
covers only ~10^5 stars/sector and the deep pipeline falls back
to QLP.

## Design

Mirrors bulk_v3 (PR #2), adapted to the deep pipeline's shape:

- **Named masks** (`quality_flags.py`): `DEEP_V1_MASK` (17087)
  and `DEEP_V2_MASK` (1610629823 = default + QLP bits 29/30,
  the same integer as `BULK_V3_MASK`, pinned under its own name
  so the deep drift test pins it). Bit 11 and bit 12 stay out
  (TOI-700 c lesson; 2026-11-15 vote 2/3 against bit 11).
- **Profile** (`calibration/deep_v2.yaml`): every deep_v1
  threshold carried over unchanged + `quality_mask: 1610629823`,
  status + rationale. Registered (supersedes deep_v1). README
  table updated.
- **hunter.py**: `CALIBRATION_VERSION = "deep_v2"` (the fix is
  the default — the deep pipeline runs per-target on demand,
  so unlike the bulk screen there is no in-flight v1 run to
  protect) and `QUALITY_MASK`, with `set_calibration(name)`
  mirroring bulk_screen's seam (deep_v1 = 17087 for sensitivity
  comparisons). `_apply_quality_mask(lc)` drops rows carrying
  ANY masked bit; a curve without a `quality` column passes
  through unchanged.
- **Placement** (mask at input, before detrend/BLS):
  - `_run_pipeline` live path: stitch → mask → remove_nans /
    remove_outliers.
  - `_run_pipeline` fixture path: mask right after the fixture
    binds (fixtures WITH a q array are masked exactly as the
    live path is).
  - `_fetch_stitched`: per-curve mask BEFORE normalise —
    `normalise_lightcurve` rebuilds a time/flux/flux_err curve
    and drops the quality column, so masking after it would
    no-op.
  - The fixture seam gains an optional `q` array (backward
    compatible: existing fixtures have no q array and build
    exactly as before; the mask no-ops on them). This is what
    makes the mask testable offline through the real path.
- **Gauntlet** (M-8): `load_tpf` and `download_author` used
  `quality == 0` literally, so a genuine bit-12 transit lost
  its in-transit cadences from the pixel work and read
  RAW-REFUTED in the raw-flux tiebreaker. Both now take a
  `quality_mask` parameter defaulting to the deep_v2 mask:
  "clean" = kept by the pipeline's mask (the M-2 lesson
  applied to the deep pipeline's gauntlet). TPFs are SPOC
  products (16-bit QUALITY), so bits 29/30 never appear there
  — the mask's effect on a TPF is the SPOC default plus the
  bit-12 keep.
- **Out of scope (noted, not fixed — CORRECTED 2026-11-15, DF-1/DF-3)**:
  the original build record claimed the gauntlet's other download
  sites (`gauntlet/desk.py`, `gauntlet/neighbour_fold.py`,
  `gauntlet/tesscut_fetch.py`) "do not filter on quality==0".
  That was WRONG for `desk.py`: `_flagged_fold` split
  clean/flagged as `(q == 0)` / `(q != 0)` literally, so a
  genuine bit-12 transit read as a flagged-only artifact — fixed
  in DF-1 (mask-consistent split). It was RIGHT for
  `neighbour_fold.py` (no quality filtering at all — but it
  downloads QLP first, so it CAN see bits 29/30: masked in DF-3)
  and `tesscut_fetch.py` (no quality filtering; TESSCut FFI
  cutouts carry 16-bit QUALITY, so bits 29/30 cannot occur —
  verified and documented in DF-3, left unmasked).

## Commits

- ab1534c Name the deep-pipeline quality masks (deep_v2 prep)
- 5e1da67 Add the deep_v2 calibration profile (quality-mask fix)
- ef5f0e8 Mask bits 29/30 at deep-pipeline input (deep_v2)
- 960923b Gauntlet 'clean' = kept by the pipeline's mask (M-8)
- 75a1fe5 Deep-v2 regression tests: artifact dies, bit-12 survives
- a660ab2 hunter: raise CalibrationError for a bad mask (bulk parity)
- f2ef631 registry: keep existing entries byte-identical
- 483b76f Deep sensitivity re-measurement: v1 0/12, v2 7/12 (real S96 hosts)

## Tests

- `tests/test_deep_quality_mask.py` (8 tests, ~91 s): the real
  `_run_pipeline` through the fixture seam — a bit-30-only
  artifact is a hit under deep_v1 (SDE >= 8.5 at the injected
  period) and not a hit under deep_v2; a bit-12 transit and a
  clean WASP-29b-equivalent transit are hits under both.
  Unit tests pin `_apply_quality_mask` directly. The gauntlet
  gates run through the real functions: `download_author` with
  a mocked MAST download (a bit-12 transit measures in raw
  flux under the new default, vanishes under old quality==0
  semantics) and `load_tpf` with a stubbed `lk.read` (bit-12
  cadences kept, bit-30 dropped).
- `tests/test_calibration.py`: deep_v2 values + carry-over +
  drift test against hunter's constants + set_calibration seam.
- `tests/test_quality_flags.py`: DEEP mask pins + straylight
  bits out of deep_v2.

## Sensitivity re-measurement (deep M-6 mirror)

Script: `bulk/inject_deep_real_s96.py` — the same six M-6
hosts, same two trials (A: 2.0% @ 5.123 d; B: 1.0% @ 3.317 d),
the REAL deep pipeline via the fixture seam, deep_v1 vs deep_v2.
Recovery = headline Period within 1% AND SDE >= 8.5.

**MEASURED 2026-11-15 ~10:35 IST** (697 s, 6 stars x 2 trials
x 2 calibrations; full table in
`bulk/inject_deep_real_s96_summary.json`):

- deep_v1: **0/12** recovered. deep_v2: **7/12** recovered.
  (7/12 is roughly a 32–81% interval — small-n on a
  flagged-heavy stress set. The blindness is fixed;
  completeness is unmeasured. P3-6, 2026-11-15: the
  "sensitivity proven" reading of 7/12 is corrected
  wherever it appears; the bundle's "roughly 30–85%"
  estimate is superseded by the 32–81% Wilson interval.)
- The v1 story is NOT false positives: on 5 of 6 hosts the
  unmasked pipeline's BLS periodogram is degenerate (SDE NaN,
  period pinned at the 25 d search ceiling) — it finds nothing
  at all. On the 6th (382069441) it finds a ~12.9 d systematic
  at SDE 29-38. The bit-29/30 cadences don't just add
  artifacts; on heavily-flagged hosts (9-30% flagged) they
  destroy the pipeline's sensitivity outright. The v1-vs-v2
  difference is the mask alone: same fixture, same code path.
- Two of the five v2 misses are harmonic aliases of the
  injected signal — 31852076 trial A lands on the 3:2 alias
  (7.683 d, SDE 25.5, right depth), 382069441 trial A on the
  2:1 alias (10.246 d, SDE 13.0). Counting aliases as
  detections, v2 detects 9/12.
- 231852754 is a host-property limit, not a mask failure: the
  star's own ~6% dips at 5.78 d dominate BLS under both masks
  (v2 finds them at SDE ~40; v1 finds nothing).
- 382069441 trial B under v2 finds P=10.864 d at SDE 19.2 —
  not a harmonic of the injected 3.317 d. **RESOLVED (P3-3 /
  DF-18, 2026-11-15):** 10.864 d is the near-2:1 alias of the
  host's own persistent ~5.50 d variability (un-injected
  baseline: 5.4856 d, SDE 41.9; shifted epochs return to the
  5.50 d fundamental; the injected signal survives the mask
  and folds at its full 0.95% depth but is outranked). A
  host-dominated miss, not a mask failure — the mask is
  exonerated. Do NOT pin 10.864 d in CI. Full record in
  SENSITIVITY_MAP.md + `phase3-vote/df18-triage.md`.
- Pin test: `tests/test_inject_deep_real_s96.py` (3 tests)
  pins trial B on 31852076 — v1 not recovered, v2 recovered
  (P=3.3165, SDE 48.1 measured) — and trial A as a RECOVERY
  under v2 (P=5.1227, SDE 40.4 measured), reusing the committed
  bulk substrate, no duplicate fixture. (DF-7: trial A was
  "deliberately NOT pinned" in the build record because the
  summary measured it as a 3:2 alias — but that measurement ran
  on a fresh sap_flux download, while the committed substrate
  is SYS_RM_FLUX, on which trial A recovers. See the module
  docstring and the DF-7 entry in the vote-follow-up section
  below.)

## Vote follow-up (DF-items) — 2026-11-15

Vote 2026-11-15 10:50–11:08 IST: unanimous 3/3 GO WITH CHANGES
(ChatGPT Think, Gemini 4 Argon, Claude pasted by Dev). Brief:
`~/workspace/goals/exoplanet-hunter/hidden_files/science-vet/deepfix-vote/FOLLOWUP_BRIEF.md`
(21 items) + COMPARISON.md (tie-breaks). Same branch
(`fix/deep-quality-mask`), small focused commits. Entries below
cover DF-1–DF-12, DF-16, DF-17, DF-18, DF-19, DF-20; DF-13,
DF-14, DF-15, DF-21 entries are appended as their runs complete.
The claims ledger (§7 format) closes the section.

### DF-6 — set_calibration context manager (160c23a)
- `hunter.calibration_context(name)`: restores the previous
  version AND mask directly in `finally`; on a failed switch
  restores the previous values before re-raising
  (set_calibration assigns before it validates).
  set_calibration kept for CLI/script startup.
- New `tests/calibration_guard.py`: `DeepCalibrationGuardCase`
  asserts deep_v2 (version + mask) restored after every test.
  Migrated: test_deep_quality_mask, test_inject_deep_real_s96,
  test_calibration TestDeepDrift, bulk/inject_deep_real_s96.py
  run_star + main(). 2 new tests (restores-on-exception;
  failed-switch restores). Scratch leak test failed as
  expected (deleted after).
- GAUNTLET BINDING DECISION (KEEP fixed default, documented in
  common.py load_tpf + rawflux_check.py download_author
  docstrings): the gauntlet vets hits the v2 pipeline found —
  it deliberately does NOT follow hunter.set_calibration;
  gauntlet defaults resolve from fixed DEEP_V2_MASK at call
  time.
- Tests: test_calibration 26 PASS, test_deep_quality_mask 8
  PASS, test_inject_deep_real_s96 2 PASS (at commit time).

### DF-1 — desk.py _flagged_fold mask-consistent split (8c1745d)
- `_flagged_fold` now takes `quality_mask=None` (defaults to
  DEEP_V2_MASK), splits `(q & mask) == 0` / `!= 0` with q cast
  to int64. Return shape UNCHANGED (no quality_mask field —
  tests/test_schema.py:253 pins this). `clean_refold_native`
  gains `quality_mask=None` passed to both folds. Both stale
  docstrings fixed. This corrects the build record's claim
  that desk.py "does not filter on quality==0" — it DID, and
  the split was the bug (a genuine bit-12 transit read as a
  flagged-only artifact).
- Regression tests in tests/test_desk.py TestNativeBuilders:
  bit-12 transit through _flagged_fold → n_in == 0, gate
  PASSes; bit-30 artifact → n_in > 0, snr > 3, depth ≈ 1%.
  test_desk 22 PASS. grep for raw `q == 0` / `q != 0` in
  desk.py finds nothing.

### DF-2 — quality guard test (4537417)
- New tests/test_quality_guard.py: tokenize-based scan of the
  62 production .py files (tests/, archive/ (56 files),
  __pycache__ excluded) for raw `(q|quality) ==/!= 0` splits
  (both comparison orders); comments/strings stripped so the
  quality==0 prose in common.py:213 / rawflux_check.py:198
  does not trip it.
- Allowlist (file, line) with reasons — all diagnostics
  measuring any-flag fractions: bulk/flag_fraction_sweep.py:159
  (`actual_frac`), bulk/inject_real_s96.py:127,
  bulk/inject_deep_real_s96.py:117 (both `frac_any_flag`).
  A moved allowlisted line fails loudly; stale entries fail
  loudly. KNOWN_UNMASKED documents gauntlet/tesscut_fetch.py
  (DF-3: 16-bit FFI, no filtering) — documentation, NOT a scan
  exemption.
- Verified: temporarily re-introduced `return q != 0` in
  desk.py → guard FAILED naming desk.py:1334; revert → PASS
  (2 tests).

### DF-3 — neighbour_fold / tesscut_fetch product checks (b9a6d34)
- neighbour_fold.py CAN see bits 29/30: `fetch_neighbour`
  tries QLP first (`for author in ('QLP', None)`, line 56),
  downloads with no bitmask, extracts t/f with no quality
  filter → MASKED: `fetch_neighbour(..., quality_mask=None)`
  defaulting to DEEP_V2_MASK resolved at call time (M-8
  pattern); new `_masked_keep(lc, mask)` applies
  `(q & mask) == 0` post-download before the finite filter and
  before the npz write; no quality column (some HLSP) keeps
  all cadences; masked counts print in the log.
- tesscut_fetch.py CANNOT see 29/30: lk.search_tesscut FFI
  cutouts carry SPOC-style 16-bit QUALITY (max bit 15) →
  left unmasked, documented in the module docstring with
  evidence. Low-bit handling verified (identity_for's
  unfiltered medians robust for WCS identity; photometry via
  M-8-masked load_tpf).
- New tests/test_neighbour_fold.py 4 PASS (29/30 dropped,
  bit 12 kept, no-column None, uint16 no-overflow, explicit
  mask).
- PRE-EXISTING BUG FOUND (NOT fixed — out of scope):
  `gauntlet/tesscut_fetch.py:62` has `sector=sectortor`
  (NameError on every call) — confirmed present on
  origin/main via `git show origin/main:gauntlet/tesscut_fetch.py`
  (introduced in Phase 1.2 C-1 commit 2d38151 or gauntlet
  consolidation aa2b839). `fetch_sector` is unusable as-is.
  Flagged to the parent; needs its own fix, not this PR.

### DF-12 — shared named-flag definition (9601d10)
- quality_flags.py now defines ONE `SHARED_QUALITY_MASK =
  SPOC_DEFAULT_MASK | QLP_UNDOCUMENTED_29 |
  QLP_LOW_PRECISION`; `BULK_V3_MASK = DEEP_V2_MASK =
  SHARED_QUALITY_MASK`. Mask integer stays 1610629823
  (refactor, not behaviour change). hunter.py comment cites
  the shared constant instead of the bare integer. New
  TestSharedQualityMask pins the shared constant, both
  aliases, and both YAML declarations. Bare-integer grep in
  production .py finds only the quality_flags.py definition
  comment. YAML profiles legitimately carry the bare integer
  (they ARE the declarations). test_calibration 27 PASS.

### DF-5 — uint16 regression + dtype/NaN edge cases (48a6e25)
- Verified empirically: bare `uint16 & 1610629823` raises
  OverflowError under numpy 2.x (the hazard is real); all
  three mask sites already cast to int64. Tests in
  test_deep_quality_mask.py (6 new): uint16 into
  _apply_quality_mask (exact row drops: bit 0 + bit 14
  dropped, bit 12 kept); masked-array quality → masked
  entries DROPPED (unknown quality is not clean — the mask
  survives the cast into the boolean index); NaN flux +
  valid quality → NaN-flux clean cadence kept; uint16
  through download_author (mocked MAST, 500→400 rows) and
  load_tpf (stubbed lk.read, 100→80).
- REAL BUG FOUND by the edge cases: a quality column of None
  CRASHED _apply_quality_mask (TypeError) — fixed to pass
  through unchanged like a missing column (object-dtype check
  in hunter.py; docstring updated).
- rawflux_check.py: the `try/except Exception: pass` around
  the mask is REMOVED — a malformed quality column on a live
  download is now a hard error, not a silent unmasked pass
  (fail loud, DF-10 principle; choice recorded in the code
  comment).
- test_deep_quality_mask 14 PASS at commit time;
  test_product_selection 8 PASS (unaffected).

### DF-8 — separate bit-29 regression case (57bec9a)
- Bit-29-only artifact pipeline test (mirror of the bit-30
  test, flag_bit=29, fixture TIC 900000006): hit under v1,
  not under v2. 1 test PASS (33 s).

### DF-9 — stamping: mask, n_masked, flagged fraction (3bcc5b9)
- `full` dict + JSON metrics now carry `calibration_version`,
  `quality_mask_applied` (ACTIVE profile's mask at run time),
  `n_masked`, `flagged_fraction`.
- n_masked = reader-layer drop (new `_reader_dropped_rows`,
  counted per product from `lc.meta["QUALITY_MASK"]` lengths
  vs len(lc) BEFORE stitching) + post-download drop (len
  before − len after `_apply_quality_mask`); the layers
  partition the removed rows, nothing counted twice.
  flagged_fraction = n_masked / pre-mask total (reader-drop +
  stitched length). Products whose reader sets no
  QUALITY_MASK meta contribute 0 → n_masked is a LOWER BOUND
  on those stars (documented in the helper docstring).
  Fixture path: reader layer 0 by construction. New metric
  keys use full.get (None default) so older full dicts still
  serialize.
- Tests: test_stamp_on_flagged_fixture (hand-counted against
  the fixture's own q array; v1 stamps 17087/n_masked 0, v2
  stamps 1610629823/hand count; JSON metrics carry the same
  stamp) + test_stamp_on_clean_fixture (0 / 0.0), both PASS.

### DF-10 — raise on missing quality, LIVE path only (d383d86)
- `_apply_quality_mask` gains `require_quality=False,
  product_label=None`: with require_quality=True, a missing
  or unusable (None/object-dtype) quality column RAISES
  naming the product and the column.
- `_run_pipeline`'s LIVE branch passes require_quality=True
  exactly when `_input_identity.get("author")` is in
  _AUTHOR_PRIORITY (SPOC/TESS-SPOC/QLP — selection is
  homogeneous per star, author knowable before download via
  `_search_result_identity`).
- BOUNDARY (recorded in the docstring): offline fixtures keep
  default False; unfiltered HLSP fallback stays non-raising;
  unreadable input identity ({}) fails open to non-raising.
- Tests: 3 unit (raise without column with product+column in
  message; raise on None column; no-op with usable column) +
  2 live-path wiring tests with mocked _select_products /
  _download_products (SPOC without QUALITY raises before any
  search work; ELEANOR without QUALITY runs through, stamps
  n_masked 0). 12/12 PASS in the two classes.
- RESIDUAL LIMITATION: the SPOC reader
  (`read_tess_lightcurve`) SYNTHESIZES a zeros quality column
  when QUALITY is missing, so a genuinely missing QUALITY on
  a SPOC file is undetectable post-download — DF-10 cannot
  catch it. The QLP reader does NOT synthesize (raises
  KeyError itself on missing QUALITY). Both verified from
  installed lightkurve 2.6.0 sources.

### DF-11 — explicit quality_bitmask at every download (e6ca702)
- hunter._download_products → `quality_bitmask=QUALITY_MASK`
  (active profile; stale "no explicit quality_bitmask"
  comment corrected); rawflux download_author + neighbour
  fetch_neighbour → `quality_bitmask=quality_mask`
  (post-download filters stay as defence-in-depth, covering
  readers that ignore the bitmask e.g. cdips); desk
  discovery_lc → `quality_bitmask="none"` (DOCUMENTED
  EXCEPTION — clean gate + _flagged_fold need to SEE flagged
  cadences; matches the cache path's raw FITS read);
  bulk/inject_deep_real_s96.py → `quality_bitmask="default"`
  (DOCUMENTED — sensitivity substrates DEPEND on the default
  reader mask; "none" would invalidate the 0/12→7/12
  comparison). tesscut_fetch: no bitmask (TPF download;
  DF-3). bulk_screen download_all: out of scope (bulk merged).
- Verified from installed lightkurve 2.6.0:
  `SearchResult.download(quality_bitmask=X)` accepts int or
  str; both SPOC and QLP readers set meta QUALITY_MASK +
  QUALITY_BITMASK; `create_quality_mask` does
  `(quality_array & bitmask) == 0` with NO cast.
- INTERACTION CHECKS (real data): QLP TIC 31852076 S96
  (3,028 bit-29 + 1,074 bit-30 cadences): reader drop 3,212
  == mask-alone drop 3,212; post-download drop on the
  reader-masked curve 0; surviving times identical; 0
  surviving rows carry a masked bit; QLP quality dtype >i4.
  SPOC TOI-700 (TIC 150428135) sector 1, 120 s: reader
  ACCEPTS the 32-bit mask (no OverflowError — SPOC QUALITY
  reads as int32 >i4); reader drop 982 == mask-alone drop
  982; 0 bit-29/30 cadences in the file (16-bit confirmed —
  SPOC unaffected by the extension, as designed).
- Test mocks updated (2 `_Row.download(self)` → `**kwargs`).
  TestGauntletMaskGates 4 PASS, test_desk 22 PASS,
  test_product_selection 8 PASS.

### DF-7 — trial A pin (d2d288f)
- Trial A pinned as a RECOVERY on the committed substrate —
  the brief's classification pin could NOT be fulfilled as
  specified, and the tests caught it (first attempt:
  classification pin FAILED, xfail XPASSed).
- DIAGNOSIS (verified, not assumed): the summary JSON's
  trial-A alias row (3:2, 7.683 d, SDE 25.5) was measured on
  a FRESH QLP download (lightkurve default sap_flux, default
  reader mask, 10,807 rows), while the committed substrate
  `tests/fixtures/injection/substrate_s96_31852076.npz` is
  SYS_RM_FLUX with all 10,819 rows (substrate flux equals the
  FITS SYS_RM_FLUX column exactly, max diff 0; differs from
  SAP_FLUX by up to 3.37e7). On the committed substrate v2
  RECOVERS trial A (P=5.12265, SDE 40.40) — verified
  identically on the pre-DF branch tip 483b76f (temp worktree,
  removed after) and on current code, so no DF commit changed
  the search. Pinning an alias would pin a falsehood. The
  7/12 headline stands as the sap_flux measurement; the
  substrate discrepancy is recorded in the module docstring +
  commit message + here. Parent decision: a SYS_RM_FLUX
  sensitivity re-run may give 8/12.
- FLOOR STATEMENT (brief ambiguity resolved): the floor
  applied is the hit bar, SDE ≥ 8.5 (hunter.HIT_SDE — the
  same bar the recovery criterion uses). The 2:1 alias at
  SDE 13.0 is 382069441 trial A (ratio 1.9999), NOT
  31852076's; it DOES count as a detection under the hit bar
  (13.0 > 8.5). No higher 'promotion floor' exists in the
  deep profile (hit_sde 8.5, acceptance_floor_sde 6.5; 13.0
  clears both). Detected ≠ recovered: the strict headline
  counts recoveries only.
- test_inject_deep_real_s96 3 PASS (trial-B pin intact).

### DF-4 — bitwise identity test (7a9830d)
- Where no newly-masked bit is present, deep_v1 and deep_v2
  must produce BITWISE-IDENTICAL search output. Two real
  substrates, read with `quality_bitmask="none"` so the
  fixture carries the full quality column: QLP TIC 149269965
  S1 (sap_flux, n=1,281: 0 bits 29/30, 15 default-masked, 288
  bit-12) and SPOC TIC 150428135 (TOI-700) S1 120 s
  (pdcsap_flux, n=19,261: 0 bits 29/30, 982 default-masked,
  0 bit-12). The VM's s0097/s0098 cache held 0 clean stars
  (every cached QLP star carries bit-29/30); s0001 held
  1,429 clean stars.
- tests/test_deep_identity.py (3 tests): a premise guard
  (zero 29/30 AND nonzero default-masked, so the test cannot
  be vacuous) plus per-product identity — Period/SDE/Depth/
  Duration_Days/T0/Total_Points/n_masked/flagged_fraction
  match EXACTLY (NaN-aware), while quality_mask_applied
  (17087 vs 1610629823) + calibration_version differ as
  expected.
- WIDEN CHECK (manual verification): temporarily widening
  ONLY deep_v2's effective mask by bit 12 makes the QLP test
  FAIL on Period (v1=24.625 vs v2=14.71) — the test bites
  when the mask changes. (Widening via the YAML is blocked by
  design: the calibration registry hash rejects a tampered
  frozen profile — the first widen attempt errored on the
  hash check, which is itself a passed guard.) Patch reverted;
  QLP test green again after revert.
- Tests: test_deep_identity 3 PASS (301 s).

### DF-16 — PROGRESS.md nits (this section's commit)
- 483b76f added to the deep_v2 commit list; stale
  placeholder "Results: (to be filled in when the run
  completes)" removed; gauntlet-sites claim in Design "Out
  of scope" corrected (desk.py DID filter on quality==0 —
  DF-1 fixed it; neighbour/tesscut did not filter at all —
  DF-3); trial-A pin line updated (DF-7).

### DF-17 — 810-star ledger audit: census (read-only)
- Ledger location RECORDED: the deep records live in 37
  `discoveries.csv` files under
  `~/workspace/goals/exoplanet-hunter/hidden_files/` —
  run2–run8b (7), batch3–batch9 runs (21), batch5/6 refires
  (6), trial-batch run44–46 (3). Excluded (not ledger stars):
  control-toi700, control2-toi700 (known-planet controls),
  science-vet/stamp-fix (a test run). `ledgers/` holds only
  the three sector ledgers + SUPERSEDED_v3.md, as the brief
  suspected.
- Census script + output:
  `hidden_files/science-vet/deepfix-vote/census_df17.py` +
  `census_df17.json` (read-only; every input hashed before
  and after — byte-identical: YES).
- Results: 1,644 rows (884 duplicates — hits are logged
  TWICE, nulls once; verified on run2: 12 hits x2 + 13 nulls
  = 37 rows), 760 UNIQUE TICs, 867 analyses
  (targets_analyzed sum across 36 result.json files; 1
  error total). The standing "810 stars" figure counts
  analyses incl. re-runs at an earlier snapshot, not unique
  TICs; the records hold 760 unique TICs. Hits (latest
  record SDE >= 8.5): 649; nulls: 111.
- Blind-search query: NaN/empty SDE: 0 rows — NO stored
  record has a degenerate SDE. Period within 0.1 d of the
  25 d ceiling: 4 TICs — 149499477 (P 24.934, SDE 4.56,
  null), 294754384 (P 25.012, SDE 30.18), 300442835
  (P 24.973, SDE 37.04), 370040864 (P 24.907, SDE 18.60).
  Three of the four are STRONG detections, not degenerate
  searches — the free census of blind searches is mostly
  NEGATIVE: the v1 blindness found in the sensitivity study
  (5/6 heavily-flagged S96 hosts) did not manifest as NaN
  rows in the ledger. Either typical ledger stars carry
  modest flagged fractions (the sensitivity hosts were
  selected FOR heavy flagging), or degenerate searches
  failed before logging — the errors sum (1 across all runs)
  rules out the latter at scale.
- REPLAY LIST (priority, blind-census): the 4 TICs above.
  Full replay list: all 760 unique TICs (in census_df17.json
  via the per-file records; the deduped TIC list is
  reproducible from census_df17.py).
- TIER 2 PARTITION (by masked-cadence count): NOT computable
  from the stored records — they carry no quality arrays and
  no sector lists. A full partition needs each star's quality
  arrays (810 MAST downloads), which is replay-scale work,
  not census-scale. DEFERRED to the post-merge replay, which
  SELF-PARTITIONS: every replay run stamps n_masked /
  flagged_fraction via DF-9, so the partition falls out of
  the replay itself. No ledger record was edited.
- REPLAY (post-merge, not this build): replay the affected
  stars under deep_v2 after the merge; ANNOTATE the v1
  records as superseded — do not edit them. The parent
  schedules this job.

### DF-18 — TIC 382069441 trial B triage (post-merge, recorded only)
- NOT run in this build. Triage steps (from the brief, for
  the post-merge job): an un-injected baseline; shifted
  injection epochs; the count of transits surviving the mask;
  a one-off run with masked blocks dilated (shoulders beside
  removed blocks are the classic residual); masked vs
  unmasked light curves; the time distribution of the removed
  cadences; the sampling window and periodogram peaks; folds
  at 3.317 d, 5.50 d and 10.864 d; behaviour across individual
  sectors rather than only the stitched curve.
- Log the result in SENSITIVITY_MAP either way — including
  if the triage is inconclusive. Do NOT pin 10.864 d as an
  expected answer in CI.

### DF-19 — historical RAW-REFUTED re-runs (post-merge, recorded only)
- LIST IDENTIFIED: 29 TICs with verdict RAW-REFUTED in
  `hidden_files/candidates-vetting/<TIC>/rawflux_results.json`:
  140599833, 141680194, 141708967, 141865558, 142087258,
  149060820, 149307626, 176959220, 207213492, 231852754,
  234510264, 237911080, 260004306, 272431317, 294665553,
  300384822, 307433122, 33836426, 344334378, 355401152,
  370220679, 370228465, 381951178, 382256433, 382571558,
  38635773, 389501533, 41361938, 55402407. (Includes all 18
  DF-15 controls; also the three S96 gauntlet finalists
  234510264 / 237911080 / 231852754. 22 verdict_stage12.json
  + 5 RAWFLUX_CHECK.md files corroborate.)
- RE-RUN PROCEDURE (post-merge job, needs the merged fix):
  for each TIC, re-run the raw-flux check
  (gauntlet/rawflux_check.py download_author + desk clean
  gate) at the filed ephemeris under the merged code (M-8 +
  DF-1 mask-consistent splits), and record the new verdict
  alongside the historical one — annotate, never edit the
  historical record. `quality == 0` could only produce false
  kills, so this list is where a real transit could have
  died. The parent schedules this job after the merge.

### DF-20 — NaN-SDE health check (SEARCH_INVALID; NOT this PR)
- NO code for it in this branch. Recorded durably as the TOP
  follow-up after this merge: a periodogram health check
  (finite SDE, peak off the grid edge) that records
  SEARCH_INVALID when the search itself is degenerate, so a
  blind search can never again pass as "no hit".
- Recorded here AND in the goal's
  `~/workspace/goals/exoplanet-hunter/GOAL.md` (appended to
  the Quality-mask fix section — the same home M-11 used).

### DF-13 — in-transit unmasked-flag fraction (commit below)
- hunter.py: new module-level `_intransit_unmasked_stats(t, q,
  period, t0, duration, quality_mask)` returning (fraction,
  per-bit counts with str keys, warn>0.5); returns
  (None, {}, False) when unmeasurable (no quality, no
  in-transit cadences, degenerate/NaN headline); uses
  quality_flags.tally_unmasked_bits. (t, q) captured as
  _bls_t/_bls_q right BEFORE `lc_raw =
  _ingest.normalise_lightcurve(lc_raw)` (normalise drops
  quality); object-dtype quality → None. Computed before the
  `full` dict (next to DF-9) at the FINAL headline (after
  pass-2/TLS adoption — pass 2 preserves rows; mask only
  excludes points from the trend fit).
- Definition: fraction of BLS-input in-transit cadences
  (post-mask curve) carrying any flag bit NOT in the mask,
  at the headline ephemeris; WARN above 50%.
- Fields in `full` + JSON metrics (via .get):
  `intransit_unmasked_flag_frac`,
  `intransit_unmasked_flag_bits`,
  `intransit_unmasked_flag_warn`.
- Tests (3, in TestDeepQualityMaskPipeline): bit-12 fixture
  → frac > 0.5, warn True, bits has "12" (hand-verified
  against a recomputation at the returned headline); custom
  25%-flagged fixture (seeded RNG 23, TIC 900000012) → frac <
  0.5, warn False; clean fixture → 0.0 / False / {}.
  test_deep_quality_mask 25 PASS (374.8 s).
- MULTI-SECTOR RULE DEFERRED: requiring the dip in sectors
  where bits 11/12 are clear ripples beyond a small change
  (per-sector in-transit flag accounting across the stitched
  curve + a new gate in the persistence path) — recorded as
  a follow-up, not silently dropped. The DF-13 fraction is
  the per-star input that rule would consume.

### DF-21 — live download-to-stitch-to-mask test (bd84204)
- tests/test_deep_mask_live.py downloads the real QLP S96 file
  for TIC 31852076 (the sensitivity substrate star) through
  the pipeline's own hunter._download_products under deep_v2,
  and asserts against a quality_bitmask="none" ground-truth
  read: reader drop == hand count (3,212/10,819), surviving
  times identical, 0 surviving rows carry a masked bit, meta
  QUALITY_MASK present (DF-9's counting input), stitch +
  post-download mask drops nothing further, and the
  post-download mask on the raw curve agrees with the reader
  exactly. Premise guarded: fails loudly if the live file
  ever stops carrying bit-29/30 cadences.
- Registered in DOWNLOAD_TESTS (tests/run_golden.py) — live
  tier only (live.yml, weekly + on merge, non-blocking); the
  offline suite gains no network dependency. Multi-sector
  stitching stays covered by the live golden stars.
- Test: 1 PASS (14.8 s). Lightkurve's own warning confirms
  the count: "30% (3212/10819) of the cadences will be
  ignored due to the quality mask
  (quality_bitmask=1610629823)".

### DF-14 — TIC 423498314 re-run under deep_v2 (BEFORE merge)
- Expected outcome written FIRST:
  `hidden_files/science-vet/deepfix-vote/df14_expected_outcome.md`
  (prediction: signal recovered, P 0.827047 d ±1% or the 2P
  harmonic, depth 0.5–1.1%, SDE well above 8.5; material
  change = absent from top-3, SDE < 8.5, depth < 0.3% or
  > 2%, non-harmonic period).
- Run: `run_df14_df15.py` (same dir), live MAST, QLP sectors
  [32, 98], star_radius 0.67343. Full records:
  `df14_df15_results.jsonl` lines 1–2.
- v1 (control): P 0.8270502 d, SDE 72.96, depth 1.061%,
  T0 2174.36589, Total_Points 27,710, n_masked 38,
  flagged_fraction 0.0014, in-transit unmasked-flag frac
  0.381 (bits 29: 325, 30: 98, 11: 13, 12: 8).
- v2: P 0.8270502 d (IDENTICAL), SDE 119.43, depth 0.862%,
  T0 2174.36589 (IDENTICAL), Total_Points 17,246, n_masked
  10,491, flagged_fraction 0.3778, in-transit unmasked-flag
  frac 0.016 (bit 12: 16 only). Headline under both.
- VERDICT: prediction CONFIRMED on every point; no
  material-change flag triggered. The SDE ROSE 64% (73 →
  119) — 37.8% of this star's cadences were flagged noise
  that v1's mask left in (n_masked 38); removing them cut
  the periodogram noise floor. The depth FELL 19% (1.061% →
  0.862%) because the flagged in-transit cadences were
  deeper than the clean ones — they were biasing the depth
  UP. Both moves are the mask working as intended. The
  candidate's photometric signal is STRONGER under v2, not
  weaker. (The planet interpretation is unchanged: still a
  candidate, grazing EB on the RUWE companion still the
  leading alternative — the re-run tests the signal, not
  the interpretation.)

### DF-15 — real-data controls (fixture form + live planet controls)
- METHOD CHANGE (measured, not assumed): the live all-sector
  batch (`run_df14_df15.py`) was KILLED at 4/42 runs — the
  artifact stars have up to 41 QLP sectors each (382571558 v1
  alone ran 10+ min), putting the full batch at ~7 h on this
  shared VM (rescore-gauntlet jobs share the CPUs). The
  artifacts are S96 phenomena, so the direct control is the
  S96 data alone, run through the deep pipeline exactly as
  the sensitivity harness does it
  (`bulk/inject_deep_real_s96.py`: download_host_qlp →
  write_fixture → _run_pipeline, NO injection) — script
  `run_df15_fixtures.py`, analysis `analyze_df15.py`,
  records `df15_fixture_results.jsonl` (all in
  `hidden_files/science-vet/deepfix-vote/`). The live
  all-sector version remains a POST-MERGE extension
  (`run_df14_df15.py --resume`; partial data kept: 355401152
  v1+v2 complete — live multi-sector v1 P=12.856 SDE 42.3
  depth 1.96%, v2 P=12.867 SDE 45.1 depth 0.37% — the depth
  collapse shows the flagged cadences carried most of the
  apparent depth; the filed 6.514 d period absent under both
  profiles).
- FIXTURE BATCH: 19 stars × v1/v2 = 38 runs, 35.4 min,
  0 errors. 18 artifacts (S96 QLP, sap_flux via lightkurve,
  star_radius=1.0 — radius scales Rp only, not the search)
  + WASP-29b. Median flagged fraction 0.288 (range
  0.098–0.328).
- RESULT — artifacts: **0/18 survive as hits under v2.**
  Filed period (or harmonic within 1%) found under v1 in
  4/18, under v2 in 3/18 — but ALL THREE v2 cases are
  SUB-THRESHOLD: 176959220 refined-only SDE 5.3, 381951178
  headline SDE 8.1, 382571558 refined-only 2:1 harmonic
  SDE 8.0. v1: 16/18 above the hit bar (median SDE 38.1)
  + 2 degenerate (355401152, 207213492 — P pinned at 25 d,
  SDE NaN). v2: 4/18 above the bar (median SDE 6.5).
- RESULT — DF-13 validates the artifact mechanism:
  **v1 in-transit unmasked-flag fraction = 1.0 on ALL 18
  artifacts** (min/median/max 1.0) — every in-transit
  cadence at the v1 headline carries an unmasked (29/30)
  flag. The v1 ~13 d systematic headlines (12/18 at
  P 12.9–13.3 d, SDE 21–57) are 100% flagged-cadence
  artifacts. **Under v2 the fraction is 0.0 on all 18.**
- v2 ABOVE-BAR HEADLINES AT NON-FILED PERIODS (4, unvetted
  byproducts — flagged, not vetted here): 355401152
  P 13.176 SDE 9.8 depth 1.08%; 382571558 P 11.731 SDE 9.3
  depth 0.21% (noisy periodogram, several ~8–9 peaks);
  33836426 P 2.294 SDE 10.3 depth 0.11% (shallow short-period
  signal, needs the gauntlet if chased); 294665553 P 24.625
  SDE 16.8 — GRID-EDGE RESIDUE (three identical-SDE peaks
  24.625/24.121/23.637 near the 25 d ceiling, same class as
  the bulk v3 rescore's grid-edge singles), not a lead.
- PLANET CONTROLS: WASP-29b (TIC 183537452, S96 fixture) —
  v1 DEGENERATE (P=25.0, SDE NaN), v2 RECOVERED P 3.92242 d
  (filed 3.9227), SDE 77.8, depth 0.91%. TOI-700 c — live
  golden test `test_toi700_c_headline_b_recovered` PASS
  (205 s) under deep_v2 (module default, no calibration
  switch in the module): c headline, b recovered.
- VERDICT: DF-15 PASSES. The mask kills the artifact class
  (0/18 as hits), un-blinds the search (2 degenerate v1
  artifacts + WASP-29b all functional under v2), and both
  known planets are recovered.

### Claims ledger (§7 format: claim, verifying command, result)
- DF-1: desk _flagged_fold splits on the mask, not q==0.
  `grep -n "q == 0\|q != 0" gauntlet/desk.py` → no matches
  (docstring reworded); `run_golden.py --only test_desk` →
  22 PASS (bit-12 transit n_in == 0, gate PASSes).
- DF-2: no raw quality==0 split in production code.
  `run_golden.py --only test_quality_guard` → 2 PASS
  (62 files scanned; 3 allowlisted diagnostics; desk.py
  re-introduction test failed the guard, naming the line).
- DF-3: neighbour_fold masked (QLP-first, line 56);
  tesscut 16-bit, unmasked by design. `run_golden.py --only
  test_neighbour_fold` → 4 PASS. tesscut_fetch.py:62
  `sector=sectortor` NameError confirmed on origin/main via
  `git show origin/main:gauntlet/tesscut_fetch.py`.
- DF-4: v1/v2 outputs bitwise-identical on clean stars.
  `run_golden.py --only test_deep_identity` → 3 PASS
  (301 s); widen check (bit 12 added to v2 only) → QLP test
  FAILED on Period (24.625 vs 14.71), reverted → PASS.
- DF-5: uint16 mask sites cast to int64; None column passes
  through; rawflux fail-loud. `test_deep_quality_mask`
  uint16/edge tests PASS; bare `uint16 & 1610629823`
  OverflowError reproduced before the tests were written.
- DF-6: calibration_context restores version+mask, incl. on
  exception. `test_calibration` (26→27 incl. DF-12) PASS;
  scratch leak test failed as expected pre-fix.
- DF-7: trial A recovers on the committed substrate
  (P=5.12265, SDE 40.40); the 3:2 alias row came from a
  sap_flux download, the substrate is SYS_RM_FLUX (max diff
  0 vs FITS SYS_RM_FLUX; differs from SAP_FLUX by ≤3.37e7).
  `test_inject_deep_real_s96` → 3 PASS.
- DF-8: bit-29-only artifact hit under v1, not v2.
  `test_deep_quality_mask` bit-29 case PASS (33 s).
- DF-9: records stamp mask + n_masked + flagged fraction.
  Fixture hand-count test PASS (v1 17087/0, v2 1610629823/
  hand count); JSON metrics carry the same stamp.
- DF-10: missing quality RAISES on the live SPOC path only.
  Unit + wiring tests 12/12 PASS; SPOC-reader synthesis
  limitation verified in lightkurve 2.6.0 source (zeros
  column synthesized → undetectable post-download).
- DF-11: explicit quality_bitmask at every download; reader
  drop == mask-alone drop. QLP 31852076 S96: 3,212 == 3,212,
  0 surviving rows carry a masked bit; SPOC TOI-700 S1:
  reader accepts the 32-bit mask, drop 982 == 982, 0
  bit-29/30 cadences in file. `test_desk` 22 PASS,
  `test_product_selection` 8 PASS, TestGauntletMaskGates
  4 PASS.
- DF-12: ONE shared mask definition, value unchanged.
  `grep -rn 1610629823 --include='*.py' .` (production) →
  only the quality_flags.py definition comment;
  TestSharedQualityMask PASS; `test_calibration` 27 PASS.
- DF-13: in-transit unmasked-flag fraction recorded, WARN
  above 50%. `test_deep_quality_mask` → 25 PASS (374.8 s);
  DF-14 v1 0.381 → v2 0.016; DF-15 v1 1.0 (all 18) → v2 0.0
  (all 18). Multi-sector rule deferred (recorded above).
- DF-14: 423498314 recovered under v2, SDE 73 → 119.
  Expected outcome written FIRST (df14_expected_outcome.md);
  actuals match every prediction; no material-change flag.
  Records: df14_df15_results.jsonl lines 1–2.
- DF-15: 0/18 artifacts as hits under v2; WASP-29b SDE 77.8;
  TOI-700c live golden test PASS. Records:
  df15_fixture_results.jsonl (38 runs, 0 errors) +
  analyze_df15.py. Live all-sector form deferred post-merge
  (measured ~7 h; runner + --resume kept).
- DF-16: PROGRESS.md nits done (483b76f listed, placeholder
  removed, gauntlet-sites claim corrected, trial-A line
  updated) — this section.
- DF-17: ledger census — 37 files, 1,644 rows, 760 unique
  TICs, 0 NaN-SDE rows, 4 near-ceiling periods (3 strong
  detections). `census_df17.py` + `census_df17.json`;
  inputs byte-identical before/after. Quality-array
  partition deferred to the post-merge replay (self-
  partitioning via DF-9 stamps).
- DF-18/DF-19/DF-20: recorded as post-merge follow-ups (no
  code). DF-19 list: 29 RAW-REFUTED TICs in
  candidates-vetting/*/rawflux_results.json. DF-20 in
  PROGRESS.md (above) AND GOAL.md (Quality-mask fix
  section, same home as M-11).
- DF-21: live download-to-stitch-to-mask test in the live
  tier. `python -m unittest tests.test_deep_mask_live` →
  1 PASS (14.8 s); lightkurve confirms 3,212/10,819 masked.
  In DOWNLOAD_TESTS; offline suite gains no network.

# Phase 3 vote follow-ups (P3-items) — 2026-11-15

Phase 3 as re-scoped by the unanimous 3/3 GO WITH CHANGES vote
(2026-11-15). Spec: `hidden_files/science-vet/phase3-vote/
FOLLOWUP_BRIEF.md` (P3-1…P3-22, the work order) +
`COMPARISON.md` (tie-breaks TB-1…TB-13, decided). Branch
`standardize/phase-3`, base origin/main `004f0c7`. Baseline
smoke at 004f0c7: 199 tests, OK (146 s).

Build order: 3E + DF-19 first (in parallel) → data hygiene
(DF-18, DF-17, close 3 inconclusives, claims corrections) →
3C-minimum + 3D(A) → injection campaign + 3B bulk_v4 → 3D
panel/spike → 3A experimental → S97 validation after freeze.
P3-20 checkpoint after P3-15: the post-3B queue size goes to
the parent, and the 3A work (P3-16–P3-19) + P3-21 pause for
the parent's decision.

WASP-29b standard (hard rule): Phase 3 is NOT measured by
candidates eliminated — known planets retained, contaminated
detections removed, demonstrated on unseen sectors.

## P3-1 — 3E health check (DF-20) — DONE 2026-11-15

New module `search_health.py`: the shared vocabulary
(SEARCH_INVALID / BOUNDARY_LIMITED / VALID_NO_DETECTION /
VALID_DETECTION; survivor dispositions PERIODIC_CANDIDATE /
SINGLE_EVENT / BELOW_THRESHOLD / SINGLE_TRANSIT_POOL /
GRID_EDGE_REJECT, shared with P3-14) and
`assess_periodogram()` — empty periodogram, non-finite
powers, non-finite SDE at peak, degenerate noise floor, peak
at grid edge, in that order. BOUNDARY_LIMITED is its own
disposition, not invalid (TB-10).

Key design correction during the build: the degenerate check
is ABSOLUTE (noise-floor scale <= 1e-12), not exact-zero
variance. BLS on constant flux does NOT produce exactly-zero
powers — the detrend leaves ~1e-13 floating-point residue,
BLS turns it into ~1e-27 powers, and the scale-invariant SDE
amplifies them to a max SDE of 44.4 (measured 2026-11-15),
above the deep HIT_SDE. An exact-zero check missed it (the
first bulk test came back "demoted", not "search_invalid").
Measured scale separation: pure noise 0.3% -> 1.6e-05; pure
noise 0.01% (quieter than any real TESS star) -> 1.7e-08;
WASP-29b-like -> 3.1e-05; constant flux -> 2.1e-27. 1e-12
sits 4+ orders below the quietest plausible real floor and
15 orders above the floating-point case. The threshold MUST
match the 1e-12 fallback scale in hunter._sde_scale and
bulk_screen._robust_sde.

Wiring:
- hunter.py: `_bls_best` returns health as a 9th element,
  assessed on the COARSE periodogram before the extraction
  loop mutates it; `full` + JSON metrics carry
  search_health / search_health_reason / pass1_search_health
  / pass2_search_health (adopted pass's health is the
  record's); classification is "Search Invalid" when health
  is SEARCH_INVALID; TLS rescue skipped on a degenerate
  search (a rescue on degenerate data is not evidence).
- api.py: both hit gates (analyze + sweep) also require
  health != SEARCH_INVALID — a degenerate search with a
  1e-12-fallback huge SDE can no longer record a discovery.
- bulk_screen.py: `_screen_one` assesses health right after
  the BLS argmax; SEARCH_INVALID returns early as status
  `search_invalid`, before the alt peaks and the record
  floor. BOUNDARY_LIMITED searches continue normally (P3-14
  dispositions them). `search_health` /
  `search_health_reason` added to _EMIT_KEYS.
- bulk/run_chunked.py: `search_invalid` added to
  SCREEN_STATUSES. schema/survivor-schema.json: status enum
  + `search_health` (enum) / `search_health_reason`
  properties; additive only, no version bump (M-4 pattern:
  absent on pre-P3-1 records). Verified by parsed-JSON
  diff: only the enum + 2 properties changed.
- log_candidate columns untouched (the DF-17 census reads
  discoveries.csv).

Tests: `tests/test_search_health.py`, 18 tests — 13
assess_periodogram unit tests (incl. Claude's 1e-12
fallback case: a systematic-family peak on a zero-variance
floor with SDE 4e12 is still SEARCH_INVALID; the
floating-point-scale case at SDE 44.4; the quiet-real-floor
guard at 1.7e-08), 2 bulk integration (constant flux ->
search_invalid; pure noise -> VALID_NO_DETECTION /
below_floor), 3 deep integration through the fixture seam
(constant flux -> SEARCH_INVALID + "Search Invalid"
classification; signal at P = max_p exactly -> BOUNDARY_
LIMITED; WASP-29b-equivalent -> VALID_DETECTION, SDE >= 8.5).

Evidence: `python -m unittest tests.test_search_health` ->
18 tests, OK (unit+bulk 0.9 s, deep 42 s). Smoke after the
item: 199 tests, OK (91 s).

## P3-6 — Claims corrections — DONE 2026-11-15

Five overstated claims corrected (Claude + ChatGPT catches;
Gemini's accounting catch). Grep-verified 2026-11-15.

1. **"Sensitivity proven" → the interval.** 7/12 is roughly a
   32–81% interval (Wilson). The literal phrase appears in NO
   record — the overstatement was the unqualified reading of
   7/12. Corrected in the repo PROGRESS.md sensitivity section
   (with the note that the bundle's "roughly 30–85%" estimate
   is superseded by 32–81%) and in GOAL.md's deep_v2 line.
   The bundle already carried the small-n caveat ("NOT a
   completeness claim"); the banner records the corrected
   interval.
2. **256-lead accounting: 244 refuted, not 253.** 36 EBs + 208
   other = 244. The 9 TOIs are recoveries, the 3 inconclusives
   unresolved; the bundle intro's breakdown (36 + 9 + 208)
   omits the inconclusives, and the batch summaries counted
   the 9 TOIs as REFUTED (the source of "253"). Corrected in
   the gauntlet LEDGER.md final tally (with the full
   breakdown 244 + 9 + 3 = 256 and the "256 gauntlet-killed
   leads" label marked invalid). Batch summaries are run data
   and were NOT edited — the ledger note supersedes them.
3. **Selection bias.** The 256 were NEW tier-A survivors
   (top-SDE, selected), not a random sample — 0 planets among
   them is not a pipeline FPR estimate and not a sensitivity
   statement. Caveat recorded in the LEDGER.md final tally
   and the bundle banner.
4. **Base-rate caveat.** ~1 planet per ~71k stars (RAVEN) is a
   contextual analogue, not an established base rate for this
   pipeline's target selection. The figure appears ONLY in the
   frozen vote artifacts (BUNDLE.md, claude_brief.md) — no
   living record cites it. Caveat recorded in both banners.
5. **Null-specificity caveat.** 0/12 synthetic null false
   alarms is not sufficient evidence of real-world
   specificity. Caveat recorded in bulk/SENSITIVITY_MAP.md
   under the Headline table. The PROGRESS.md /
   PHASE_1_2_PROGRESS.md 0/12 citations are grid
   measurements (pre-registered clip-grid criteria), not
   specificity claims — left as-is.

**Vote-artifact policy (judgment call, recorded):** BUNDLE.md
and claude_brief.md are frozen vote inputs — the three
verdicts quote and reference their wording, so rewriting the
voted text would falsify the vote record. They carry dated
P3-6 correction banners at the top instead (superseding the
labelled claims in place); the living records (repo, GOAL.md,
ledger) are corrected in place. MEMORY.md was checked: it
contains no instance of any of the five claims (its 7/12 and
256 lines are measurements).

Grep verification: repo has no "256 killed" / "71k" and no
"sensitivity proven" except this section's own correction
note; GOAL.md + LEDGER.md have no live instance (the ledger
hit is inside the correction note); the only remaining
"256 gauntlet-killed" instances are the frozen bundle/brief
text (banner-covered) and the verdicts/COMPARISON/brief
discussing the correction.

## P3-9 — 3D: record (A), panel, B spike, (D) — PARTIAL 2026-11-15

**(A) RECORDED (done).** Disposition (A) is recorded in the
new policy profile `calibration/external_tools_v2.yaml`
(registry-pinned, sha256
7fb57db2e4f16017e7c0f79b24b7e4fafea80492f4b240418e33466d8192caa6,
supersedes external_tools_v1) — v1 was NOT edited: it is
merged on main and used in runs (C-10), so the immutability
rule requires a successor (the brief's "or its successor
profile"). Bars UNCHANGED from v1 (FPP 0.015 / NFPP 0.001 /
refute 0.5); run settings, venv paths and tool versions
unchanged. The v2 `disposition` section records: VALIDATE =
FPP <= 0.015 AND NFPP <= 0.001; REFUTE = FPP >= 0.5; grey
zone = INCONCLUSIVE (never "validated", never Giacalone's
"likely planet"); without a contrast curve, intermediate
results read INCONCLUSIVE (STP unconstrained — WASP-29b:
STP 0.160 of FPP 0.169; Collier et al. 2026: curves remove
"almost entirely" the STP scenario); the STP-excluded
disposition is NOT adopted in Phase 3 (TB-2), with both
panel-outcome branches recorded (panel mostly below 0.015
-> revisit (C) per target; panel mostly STP-dominated ->
evidence base for revisiting the disposition in 3.1). Code
defaults moved v1 -> v2 (`EXTERNAL_TOOLS_POLICY_VERSION`,
`load_external_tool_configs`, docstrings). This is a
recording act — the mapping already behaved as (A), so no
disposition behaviour changed. Tests: 3 new tests pin v2
(bars unchanged, disposition (A), v2 is the default);
test_triceratops + test_desk_external_tools default-policy
assertions updated v1 -> v2 (documented, justified: the
default moved by design; behaviour assertions unchanged).
Evidence: test_triceratops + test_desk_external_tools +
test_registry -> 52 tests, OK. Smoke after the item: 199
tests, OK.

**B SPIKE (done).** Coverage finding recorded
(`phase3-vote/p3-9-b-spike.md`): contrast curves exist
essentially only for TOIs — ExoFOP-TESS is the single
aggregation point; ~3,000–4,000 of ~8,000 TOIs covered
(SOAR 2,982 targets the largest program); no blind
field-star coverage. **(B) is CLOSED as a general solution**
for new uncatalogued leads. No scraper built (per the
brief). WASP-29 (TOI-192) already has two curves on ExoFOP
(Gemini/Zorro 832 nm, SOAR/HRCam) — re-running WASP-29b
with the Zorro curve is the immediate 3D(A) calibration
test and is step 0 of the panel job.

**Known-planet panel (Mac job — commands READY, 2026-11-15).**
`phase3-vote/p3-9-panel-mac-commands.md` (1,412 lines, §§0–10):
10 targets (the 9 recovered TOIs + TOI-700 c), no-contrast
configuration, seed 20261114, N = 1,000,000 — per-target
FPP/NFPP/scenario split + disposition under (A). The panel
measures the false-refute rate that n=1 cannot. Step 0 is the
WASP-29b + Zorro 832 nm curve re-run (the immediate 3D(A)
test; the curve is fetched from ExoFOP-TESS and converted to
TRICERATOPS format — the raw file will not load). §5 extracts
the C-10 inputs/outputs to complete the P3-7 fixtures (true
hashes + splits). §7 adds the five-seed runs (seeds 20261114–
20261118, C-10 seed first; §7 total 9,510 s ≈ 2.6 h) and §8
the runtime + memory measurement (`/usr/bin/time -l` per run;
sets the P3-8 timeout budget — no timeout changes until the
measurements land). Session total ≈ 4.6–8.5 h (panel timing
dominates the range). The parent runs it; results return as
the panel verdicts + the P3-7 bands + the P3-8 measurements.

**(D) DATED REVISIT (recorded).** Trigger for the Gaia-path
re-run (WASP-29b verification): Gaia TAP back — the watch
hook polls every 15 min and wakes on 2 consecutive HTTP
200s. Revisit date: within 7 days of the known-planet panel
completing, and no later than 2026-12-09 (one week after
the Gaia DR4 release on 2026-12-02, when the archive is
stable). Note the planned DR4 shutdown window 2026-11-25
12:00 CET → 2026-12-02, during which Gaia-dependent work
is impossible. The revisit does not block Phase 3.

## P3-7 — 3C: golden fixtures + offline assertions — PARTIAL 2026-11-15

**Landed (offline, in CI):** fixtures
`tests/fixtures/triceratops/308851365.json` (EB) +
`183537452.json` (WASP-29b) + the generic runner
`tests/test_triceratops_golden.py` (10 tests, 8 pass + 2
visible skips). Fixture format: the TRICERATOPS output JSON
(schema shape) + a `scenario` split block + `seeds` +
`expected` TB-4 bands (tolerance bands, never exact
floats). Assertions: EB FAIL/refute (FPP >= 0.5); WASP-29b
INCONCLUSIVE + FPP < 0.5 + NFPP < 0.01 + STP dominance
(STP 0.160 = 95% of FPP 0.169); disposition re-derives
identically under v1 and v2 (P-4 — v2 is a recording act);
seed-stability check (`check_seed_stability`: same
disposition across seeds AND the FPP band clear of the
0.015/0.5 boundaries) unit-tested on synthetic seed sets.
The module is in SHARD_GOLDEN (the required check) by
TB-12 — the assertions are the merge gate, the nightly is
monitoring. Evidence: `python -m unittest
tests.test_triceratops_golden` -> 10 tests, OK
(skipped=2). Smoke after the item: 199 tests, OK.

**Reconstruction status (honest):** the fixtures are
RECONSTRUCTED from the recorded C-10 numbers (BUNDLE.md
§1.6 + merged PR #6 body / lockfile header) — the full Mac
outputs are not on the VM. Each fixture's `provenance`
block states exactly which fields are measured and which
are placeholders (input hashes, full per-scenario split,
artifact paths). The assertions depend only on measured
fields. The Mac extraction (prepared in
`phase3-vote/p3-9-panel-mac-commands.md`) verifies and
completes them; the fixtures gain their true hashes +
splits then, in a follow-up commit.

**Pending (Mac work, visible skips):** the >= 5-seed FPP /
STP-split bands (fixtures carry one seed each; band width
comes from the seed spread, never invented); TOI-700 c —
NO fixture until a measured run exists (panel, P3-9).
The fast Mac smoke test (N = 10,000 draws, P-16) lives in
the nightly (P3-8), not in CI.

## P3-8 — 3C: nightly readiness — PARTIAL 2026-11-15

**Landed (offline, tested):** the nightly driver
`scripts/triceratops_golden_nightly.py` — runs the golden
targets through the REAL tool on the Mac, checks each fresh
output against its fixture's TB-4 bands via the shared
module `gauntlet/triceratops_golden.py` (one definition of
"passes", shared with the CI assertions — the two can never
drift apart), writes a timestamped receipt, and opens a
GitHub issue on failure (deduplicated by title, live.yml's
pattern). The driver sets SSL_CERT_FILE to the venv's
certifi bundle (the TRILEGAL host omits a ZeroSSL
intermediate). Modes: full (N = 1,000,000, gate-eligible)
and `--fast` (N = 10,000, P-16 — plumbing only: a 10k-draw
FPP is too noisy for the bands, so a fast receipt is never
gate-eligible). The wrapper takes an `n_samples` input
override (`gauntlet/tools/run_triceratops.py`) and records
the count actually used, so a fast run can never masquerade
as a full one.

**RSS watchdog (P-3, scoped to this job):**
`run_external_tool` takes `rss_watchdog_mb` / `rss_poll_s`
— a daemon thread polls the child process group's RSS via
`ps` and SIGKILLs the group above the cap, returning status
`memory` (the desk driver maps it to UNMEASURED +
EXEC_ERROR, never a pass). The watchdog records peak RSS
even on a clean completion (the nightly's memory
measurement). macOS applies no RLIMIT_AS cap, so the
timeout was the only guard there; the general watchdog for
all tool runs rides with future tool infrastructure (3.1).
The default path is unchanged (no watchdog unless
requested). Tests: 3 new watchdog tests in
`tests/test_external_tool.py` (kill, peak recording, no
watchdog = no peak) + 15 tests in
`tests/test_triceratops_nightly.py` (green/red/crash/
missing-input/fast runs, issue opening, FAILURE marker when
`gh` is unavailable, and the receipt gate: hash tamper,
stale, fast, override, red, missing). Evidence: `python -m
unittest tests.test_triceratops_nightly
tests.test_external_tool tests.test_triceratops_golden` ->
OK (skipped=2, the P3-7 pending ones).

**Receipt + gate (TB-3/TB-12):** the receipt lives at
`vetting_results/triceratops-golden/receipt.json` on the
Mac (run data — NOT in `calibration/`, which is
registry-pinned code; a nightly artifact does not belong
there and would dirty the repo every night). "Signed"
means a `receipt_hash` (sha256 over the canonical receipt
body) — tamper-evident, not a cryptographic signature:
the project has no signing-key infrastructure, and the
hash chain (fixture shas + code SHA + policy sha +
results) is what makes the receipt verifiable from a copy.
The gate (`--check`) requires: hash verifies + overall
pass + full (not fast) run + no config override + < 7
days old. The nightly is MONITORING, not a merge check —
the offline fixture assertions in CI are the gate; the
receipt gates Phase 3 completion.

**CI macOS runner spike (research, 2026-11-15):** the
lockfile is platform-agnostic by construction —
`make_lockfile.py`'s `fetch_hashes` records the sha256 of
EVERY distribution file PyPI lists for each pinned version
(aiohttp carries ~20 hashes: macOS + Linux + Windows wheels
+ sdist), so a GitHub-hosted macOS runner's pip would find
its wheel hashes in the list; no hash work is needed and
no dependency verification is weakened. setup-python
supports exact patch versions (it downloads from
actions/python-versions, which aims to publish new
releases as soon as they ship); 3.11.15 is a real release
(the Mac venv runs it) — manifest presence is confirmed
by the live install test, not assumed here. Open questions
for that test (a 3.1-or-later decision, NOT a Phase 3
deliverable): whether every pinned package ships a macOS
arm64 wheel (notably pytransit), the run wall-time on a
hosted runner (C-10 timings on the M4: EB 349 s, WASP-29b
1,553 s), and cost — macOS runners bill at 10x the Linux
minute rate, so a ~35-min nightly costs ~350 Linux-minute
equivalents per run. The ZeroSSL cert-append step would
need to be a workflow step. The Mac nightly is the Phase 3
venue; the runner stays a recorded spike.

**Pending (Mac measurements — no timeout changes until
they land):** runtime percentiles + memory + largest-target
measurements ride the 5-seed runs + panel (prepared in
`phase3-vote/p3-9-panel-mac-commands.md` §7–§8). Gemini's
2,700 s is the candidate timeout value to test, not a
pre-commitment; re-binning 200 -> 120 is the alternative
lever, tested with the FPP ± 0.01 check (TB-9). The first
real nightly run (on the Mac, after the C-10 inputs are
extracted) is still owed, as is the scheduling itself
(cron/launchd + caffeinate; the job must be LOUD on
failure — non-zero exit + issue + FAILURE marker).

## P3-2 — DF-19: historical RAW-REFUTED re-runs — DONE 2026-11-15

**DF-19 COMPLETE 2026-11-15 ~19:35 IST: 29/29 measured, 5
revived (3 EB + 2 REFUTED), 24 not-revived, 0 UNMEASURED, 0
planets.** Overlap-4 CLOSED ~17:20 IST: 0 revived, 0
unmeasured — §3 batch (25 TICs) ran detached on the Mac
17:21–19:35 IST (2h14m, ~5.4 min/TIC).
`phase3-vote/df19-mac-commands.md`
(432 lines): the 29 TICs whose historical desk verdict is
RAW-REFUTED, re-run under the fixed gauntlet (mask-consistent
clean fold M-8 + DF-1) on `origin/main` 004f0c7 via
`scripts/desk_gauntlet.py --no-expensive` (the DF-19 question
is answered by the cheap stages). The doc carries the sync +
md5 gate (all 5 md5s verified against origin/main by the
coordinator: hunter.py 85771824…, bulk_screen.py 484dbea8…,
desk.py fc09cb99…, rawflux_check.py c7f8050d…,
desk_gauntlet.py 0766ccf0…), the filed ephemerides
(cross-checked against leads25.json), the verdict-extraction
script, and the reporting format. **The 4 overlap TICs ran
FIRST, one by one (41361938, 142087258, 294665553, 382256433):
if DF-19 revived ANY of the four, the job stopped and
reported immediately — Phase 3 would have become vetting
those (Claude's flip condition). None revived; §3 was
cleared to run.**

**Parent ruling 2026-11-15 (corrected revival rule — governs
the whole job):** REVIVED = `clean_refold` pass AND `raw_flux`
pass. The doc's §4 extraction script was BUGGY — it checked
`clean pass → REVIVED` first and never reached the raw_flux
branch; fixed in the doc the same day (raw_flux fail is now
checked BEFORE declaring REVIVED), with a dated correction
note in the Rules section. A clean pass alone is NOT a
revival: TIC 41361938 passed clean (0.4997% @ 16.9σ, 3
events) but failed raw flux (0.000126% @ 0.034σ, 74 events)
— an S96-only weak dip, not a persistent transit — and is
NOT REVIVED. (DF-19 seeks transits the quality==0 bug
killed; a killed transit would be persistent.) Revival is
read off the stages, NOT `final_verdict` (a revived TIC
reads INCONCLUSIVE under --no-expensive).

Overlap-4 outcomes (all `final_verdict` REFUTED; verdicts +
natives + logs copied to `phase3-vote/df19-results/`):

| TIC | clean_refold | raw_flux | DF-19 verdict |
|---|---|---|---|
| 41361938 | pass, 0.4997% @ 16.9σ, 3 ev | fail, 0.000126% @ 0.034σ, 74 ev | NOT REVIVED (parent ruling) |
| 142087258 | fail, 0.0508% @ 2.08σ, 3 ev | fail, 0.00314% @ 1.19σ white, 73 ev | NOT REVIVED |
| 294665553 | fail, n_in=0, n_ev=0 | pass, 0.0257% @ 3.26σ white, 36 ev | NOT REVIVED |
| 382256433 | fail, n_in=0, n_ev=0 | fail, −0.0109% @ −0.51σ, 37 ev | NOT REVIVED |

Per-TIC wall ~5–7 min (download-bound; MAST fetch of all
sectors × 4 authors dominates). §3 ran as the doc's
sanctioned detached batch (`df19_rest.sh`, 25 commands
verified byte-identical to the doc's §3 block, `nohup
caffeinate -s -i`, pid 29348, launched 17:21 IST).
`df19_rest.sh` is NOT gitignored on the Mac despite the
doc's claim — it showed as untracked; deleted from the Mac
repo root after the batch, with the two VM-side helper
scripts (`df19_extract.py`, `df19_revived_stages.py`).

**§3 outcomes (25 TICs): 5 REVIVED, 20 not-revived, 0
UNMEASURED.** The 5 revivals are revivals of the SIGNAL
(real persistent dips the quality==0 bug hid), NOT planets:

| TIC | clean | raw | final | what killed it / what it is |
|---|---|---|---|---|
| 231852754 | 1.639% @ 64.3σ, 6 ev | 3.055% @ 293σ | EB | shape (density) + odd/even 4.9σ; persistence PASS; refined P 5.7777852 d |
| 234510264 | 1.593% @ 21.1σ, 5 ev | 0.050% @ 3.6σ | REFUTED | persistence MIXED + odd/even 4.1σ; refined P 6.2965021 d |
| 237911080 | 0.303% @ 26.7σ, 31 ev | 1.026% @ 162σ | EB | blend FAIL — neighbour same dip at 281.2σ, 5.7× depth (photocopy of the known EB on TIC 237911081); shape + odd/even 21.5σ also fail |
| 272431317 | 0.866% @ 21.4σ, 13 ev | 0.612% @ 85.4σ | EB | shape (density); refined P 3.0113126 d matches the §5 prior P′ = 3.0113021 d — the known S98 EB, revived exactly as predicted |
| 307433122 | 8.669% @ 228σ, 3 ev | 0.106% @ 12.4σ | REFUTED | persistence MIXED + shape; the harmonic alias, as §5 predicted |

The 20 not-revived §3 TICs are all `final_verdict`
REFUTED, all clean_refold fail ("signal lives only in
flagged cadences"); 8 of them carry a raw_flux pass (a raw
dip with zero clean in-transit cadences — flagged-cadence
signal only). Full per-TIC table:
`phase3-vote/df19-results/df19-extraction-2026-11-15.txt`;
all 29 verdict records + natives + evidence packages +
logs + stage-0 censuses in `phase3-vote/df19-results/`
(29 dirs, 12 MB; the downloaded light-curve caches were
trimmed from the VM copies — the Mac retains the full
workdirs). **DF-19's answer: the bug hid 5 real persistent
signals, all EB or refuted; 0 planets. "0 planets" stands.**
Priors recorded in the doc: the 18 flagged-cadence
artifacts were expected not-revived; the 4 amplified weak
dips carry a small real clean dip (a pass there revives a
weak dip, not a planet); 272431317 was already superseded
(a period error, closed as an EB); 300384822's sector (1)
is inferred from its t0 epoch and its T0 differs between
the cluster matrix and rawflux_results.json (the commands
use the rawflux value).

## P3-3 — DF-18: TIC 382069441 trial B triage — DONE 2026-11-15

**RESOLVED — 10.864 d is the near-2:1 alias of the host's own
persistent ~5.50 d variability, not a mask failure and not the
injected signal.** Full record:
`phase3-vote/df18-triage.md`. Un-injected baseline under
deep_v2: P = 5.4856 d, SDE 41.9, depth 1.95% — the 5.50 d
signal is in the host with no injection at all. At shifted
injection epochs the headline returns to the 5.50 d
fundamental (5.5015 / 5.5128 d, SDE 36.7 / 35.6); 10.864 d
appears only at the original epoch and never reappears. The
injected 3.317 d signal survives the mask (6 of 8 events
fully intact, 323/430 in-transit cadences kept) and folds at
its full 0.95% depth (SNR 38.5) — it is present in the masked
data but outranked by the host signal (SDE ~36–42). The
10.864 d dip exists in un-injected, unmasked data (~2%, same
dip events as the 5.50 d fold, best-phase t0 within 0.04 d);
dilating the mask changes nothing (10.8726 d, SDE 19.4).
Per-sector: 5.497–5.498 d in S96/S97/S98 with halving depth
(1.91% → 0.97% → 1.07%) — persistent, evolving amplitude:
stellar variability, not a transit. Trial B v2 and v1
reproduce the committed summary bit-identically. Miss
accounting for the 7/12 headline: 2 harmonic-alias
detections (31852076 A, 382069441 A), 2 host-dominated
(231852754 A+B), 1 host-dominated via alias (382069441 B).
**Do NOT pin 10.864 d in CI** (epoch-dependent alias). Logged
in `bulk/SENSITIVITY_MAP.md` + the sensitivity section above.
Recommendation recorded for future sensitivity runs:
"host-dominated" as a miss category, and/or exclude hosts
whose un-injected baseline SDE exceeds the injected signal's
expected SDE. What the 5.50 d host signal IS (spotted rotator?
blended EB?) is vetting work, out of scope here.

## P3-4 — DF-17: Tier-2 ledger replay — MAC JOB READY 2026-11-15

**Prepared, NOT run.** `phase3-vote/df17-mac-commands.md`
(427 lines) + driver `df17_replay_driver.py` (stdlib only,
parses OK) + `df17_replay_tics.json` (760 TICs, latest v1
record per TIC; input hashes verified against the census
before and after — byte-identical) + generator
`df17_tic_list.py`. Tier 1 found 37 `discoveries.csv` files,
1,644 rows, 760 unique TICs, 867 analyses. Tier 2 replays
those stars under deep_v2; the stored records carry no
quality arrays or sector lists, so the replay self-partitions
(every run stamps the DF-9 fields). Order: priority-4 first
(149499477, 294754384, 300442835, 370040864 — the 4
blind-census TICs with periods near the 25 d ceiling),
verify the deep_v2 proof on those 4, then the full 760-TIC
replay as an overnight job (~2–4 GB free needed for 760
JSONs + PNGs). Annotation procedure (VM side, after results
return): v1 records are ANNOTATED as superseded, never
edited; byte-identical verification of the originals before
AND after annotation. The parent runs it (copies the driver
+ lists to the Mac, syncs to 004f0c7 with the hunter.py md5
check, runs priority-4, then the overnight full replay).

## P3-5 — Close the 3 INCONCLUSIVE gauntlet leads — DONE 2026-11-15

**All three REFUTED. The S96 v3 rescore gauntlet is closed:
256/256 refuted (247 refuted + 9 TOI recoveries), 0 survivors,
0 planets, 0 inconclusive remaining.** Full record:
`phase3-vote/p3-5-inconclusives.md`; verdicts folded into
`rescore-v3-gauntlet/LEDGER.md` (final tally + the 3 lead
rows + batch rows; the per-lead verdict files keep their
at-completion INCONCLUSIVE text as run records — the ledger
closure supersedes them). TIC 150246959 (rank 71): density —
rho_circ/rho_star = 0.0011 vs the 0.80 bar, T14 13.7 h vs
T14max 1.47 h, a/R★ ≈ 1.04; sine fits better than a
trapezoid; phase-0.5 brightening −0.14% @ −38σ. TIC 55387764
(rank 13): density (ratio 0.0006) AND phase incoherence —
the dip sits at phase 0.00 in s01–13 but 0.66 in s61–69 (both
pipelines), returning to 0.06 in s87–98; a planet cannot
wander in phase by 2/3 of a cycle and back. TIC 149445580
(rank 21): density, mass-independent (passing the bar would
need M★ < 0.0018–0.0057 M☉ at R★ = 0.72 R☉ — substellar, so
the missing TIC mass does not block the verdict; the TIC
genuinely has no mass/logg, confirmed live via MAST) + a
V-shape fail from the unbinned fit (T23/T14 = 0.185 ± 0.035,
1σ UB 0.220 < 0.30 bar). Root cause of the original
INCONCLUSIVE: all three dips are ~half their own period wide,
so the shape gate's pass-2 binning (T14/12) gave only 14 fine
bins against the 15-bin floor — a binning artefact, not a
weak signal (dips are 33–146σ in raw flux). **Gate-hardening
follow-up (recorded, not done):** a bin-width cap or
minimum-bin-count retry in the shape gate would have measured
all three in the gauntlet run — a 3B/3.1 item. The 3 leads are
now closed and eligible for the negative training pool as
labelled astrophysical FPs per the brief's "until closed"
rule; labelling is a P3-17 decision (circular-label rules
apply). No step failed on network; Gaia TAP was not attempted
(down) and not needed.

## P3-13 — 13.1–13.3 d family spike — DONE 2026-11-15

**COMPLETE. The family is a sector-wide scattered-light
systematic, characterised — not merely suspected. Claude's
flip condition 2 FIRES: 568/568 F13 members carry
`near_systematic=True` (100%).** Full record:
`phase3-vote/p3-13-spike.md`; scripts
`p3-13-scripts/p3-13-spike{,2,3,4}.py`. F13 count is 568 in
the full [13.1, 13.3] d window (the brief's 534 = the seven
BLS grid points 13.101–13.271; +34 at P = 13.2997). All 568
are tier B, 0 tier A; the whole [12.7, 14.3] d window is
1,055 survivors, all tier B, all flagged. Mechanism: BLS
pairs glitch epochs ~13.2 d apart (G0→G4, Δ = 13.16 d;
G2→G8, Δ = 13.32 d) — the sector start, the orbit 199/200
boundary/downlink gap, and the sector end; 318 stars share
T0 inside a single 3 h window; 559/568 (98.4%) in
SECTOR_EPOCH_CLUSTERs by shared event times. Cross-checks:
flagged_in_transit_frac median 0.509 vs 0.210 baseline; the
only unmasked bit in transit is bit 11 (predicted Earth/Moon
stray light, deliberately unmasked); F13 spans all four
cameras and the full sector footprint (no spatial
concentration). F9 (9.3–9.6 d, 111, 70 tier A): 0/111 flagged
— a G1→G5→G8 triple glitch at 9.46 d spacings, which is why
70 are 3-event tier-A hits. F6 (6.2–6.4 d, 64): 45/64
flagged; a five-epoch comb at ~6.3 d. **Disposition: DEMOTE,
never exclude** — (1) `near_systematic` window demotion
(3B(3), the one-line policy change: removes all 568 F13 +
33/40 tier-B F6, costs nothing from tier A) + (2)
SECTOR_EPOCH_CLUSTER veto (catches F13 + F9 + F6 = 743
stars, 15.8% of survivors, with no period exclusion at
all). No blanket period exclusion (a real 13.2 d planet
with ≥3 events would not share the glitch epochs); no
deletion from the ledger (demoted members keep a
disposition and remain queryable). Still owed: 13.2 d
injection pricing (P3-10); cross-sector repeat check
(S95/S97/S98 rescores); camera + momentum-dump tests (need
light-curve headers/QUALITY columns). **Two pipeline
findings routed to 3B/3C:** (a) t0 is a FITTED epoch, not
the first observed event — downstream code assuming
"events = t0 + kP, k < n_events" misplaces events (461
computed events past the sector end in the spike's first
pass); (b) n_events overstates the evidence at sector edges
— 114 of the 120-star G3 subgroup have only ONE fully
in-span event yet carry n_events = 2.
