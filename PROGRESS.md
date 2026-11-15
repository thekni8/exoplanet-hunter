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
