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
  not a harmonic of the injected 3.317 d; likely the star's own
  variability or a window-function alias after 29.5% of
  cadences are masked. Unresolved — a vote question if the
  reviewers want it chased (it is a 29%-flagged host, not a
  typical one).
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
