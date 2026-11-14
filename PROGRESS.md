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

- [ ] C-1: Under bulk_v3, flagged-only dips at the artifact
  periods/depths (12.64 d, 6.27 d; screen depths 0.5–2.9%;
  bits 29 and 30; flagged fractions 0.7 and 1.0) do NOT reach
  survivor status; under bulk_v2 the same fixtures DO (the
  failure reproduction).
- [ ] C-2: A clean WASP-29b-equivalent transit (P 3.9227 d,
  1.14%) still survives under bulk_v3.
- [ ] C-3: A real transit with scattered-light flags on
  non-transit cadences (10% flagged) still survives under v3.
- [ ] C-4: A transit on bit-12 (4096) cadences still survives
  under v3 (the mask must not include bit 12).
- [ ] C-5: The full clip grid under bulk_v3 reproduces the v2
  numbers (deep-quiet 16/16, null FA 0/12, 0 monotonicity
  violations) — the mask is a no-op on clean data.
- [ ] C-6: Flag-fraction sweep bounds the cadence-loss cost
  (recovery with realistic bits 29/30 fractions on
  non-transit cadences, mask on vs off).
- [ ] C-7: Frozen v1 calibration files byte-identical at the end
  (bulk_v1/deep_v1/gauntlet_v1); registry append-only (existing
  entries untouched); full golden suite green.
- [ ] C-8: `test_flagged_cadence_signal_gate_fails` updated to
  the new pinned behavior (v2 promotes + gate FAILs; v3 does
  not promote) with the behavior change stated in the commit.

## Commits

- (log appended as work lands)
