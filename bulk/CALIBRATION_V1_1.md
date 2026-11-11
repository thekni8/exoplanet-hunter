# Bulk screen v1.1 — survivor calibration

**Date:** 2026-11-11. **Scope:** bulk_screen.py only (hunter.py untouched).
**Tuning data:** the sector-1 proof run ONLY (run_s0001_proof: 2,210 in →
558 VSX-skipped → 1,429 searched → v1: 451 survivors = 31.6%).
**Goal (Dev's, 2026-11-11):** ≤1–2% pass rate before any large run, with
the TOI-700 positive control still caught. No large run was fired.

## Why the flat SDE bar cannot work (measured, not argued)

| Rule (on proof survivors) | Pass rate | Control (SDE 10.26) |
|---|---|---|
| v1: SDE ≥ 7 | 31.6% (451) | ✓ |
| SDE ≥ 12 | 9.1% of searched | ✓ |
| SDE ≥ 20 | 4.3% of searched | ✗ killed |
| depth ≤ 0.5% alone | 22.6% of searched | ✓ |
| depth ≤ 0.5% + flat duration 0.8–4 h | 3.9% of searched | ✗ killed (6.05 h) |

Single-sector QLP SDE runs hot and does not rank like multi-sector SDE.
Any single-knob fix either stays too fat or kills a shallow, real,
single-transit planet — which is exactly the quarry.

## The v1.1 rule

Every hit ≥ the record floor is rescored by refolding at the BLS
ephemeris and pricing noise at the transit timescale (LEO-Vetter
style, the same construction Rabtsevich's screen used):

- **CDPP_dur** = std of means of out-of-transit chunks one duration
  long (red noise on the transit timescale is priced in).
- **MES_pink** = refold depth / CDPP_dur × √(N events).
- Per-event SNRs (FFI 30-min cadence: an "event" needs ≥1 in-window
  cadence — a 1–2 h transit is only 2–4 points).

Survivor = no demote flags (v1 vetoes unchanged) AND SDE ≥ 7 AND:

- **Tier A (periodic):** ≥3 events, MES_pink ≥ 9 (Rabtsevich's floor),
  ≥2 events individually ≥3σ.
- **Tier B (few-transit):** 1–2 events, best event ≥8σ pink,
  depth ≤1.0% (deeper lone dips are EB/artifact country at screen
  level; they stay in screen_hits, not survivors).

A hit whose rescore cannot be measured (<5 noise chunks) cannot be a
survivor — it stays recorded. On the proof hits the rescore covered
1,059/1,081 (98%); the 22 misses are very short-period hits whose
windows leave too few clean chunks.

## Proof-run result (offline rescore of the recorded hits)

- **23 survivors = 1.61% of 1,429 searched** (7 Tier A + 16 Tier B).
- **Control TIC 150428135 (TOI-700): Tier B** — MES 8.44, single event
  at 8.44σ, depth 0.140%. Sector 1 holds exactly one c transit, so it
  can never be Tier A in-sector; periodicity for Tier B is the
  gauntlet's persistence test, as designed.
- Integrated-code validation: see "Validation" below.

## Honest caveats

- **Tier A is top-heavy with sub-day cyclers** (5 of 7 at P < 1 d,
  28–43 events): likely rotators/pulsators/contact EBs that survived
  because their folds are boxy at 30-min cadence. They are cheap desk
  kills in the gauntlet, and the tier order sends them first precisely
  so they die first. The one mid-period Tier A, TIC 149445580
  (P 8.21 d, depth 0.141%, MES 10.7, 3 events, 2 strong), is the most
  planet-shaped object in the whole proof output.
- **Tier B is mostly P = 20 d grid-edge single dips.** In-sector they
  are unverifiable by construction; multi-sector persistence is their
  only test. The ≤1% depth cap kept the 1.1–1.8% lone dips out.
- **TIC 349094956 ranks Tier A #1** (MES 23.8) despite depth 2.29% and
  a 40%-of-primary secondary — the existing secondary veto (≥80%)
  does not fire. Tiering ranks; it does not endorse. Desk-check fodder.
- **Scale honesty:** 1.61% of 126,246 ≈ ~2,030 survivors. That is the
  right size for bulk desk checks in tier order, NOT for the full
  gauntlet per star. The screen's job at scale is a ranked queue.
- Thresholds are round, physically motivated numbers chosen on ONE
  sector-1 cone. They are a starting calibration, not a truth machine;
  re-derive them if a future sector's rescore distribution shifts
  wildly (watch the summary's survivor_tiers and the control).

## Validation

Integrated code (bulk_screen._screen_one, v1.1) re-run over all 1,081
recorded-hit stars from the proof cache (bulk/validate_v11.py):

- **23 survivors (7 Tier A + 16 Tier B) = 1.61% of 1,429 searched** —
  exactly the offline prediction, star for star.
- **Control: survivor, Tier B** — SDE 10.257971090628807 (bit-identical
  to v1), MES_pink 8.437, 1 event at 8.44σ, depth 0.140%.
- Accounting closes: 362 demoted (same as v1) + 696 recorded +
  23 survivors = 1,081 recorded hits. v1's 451 survivors → 23.
- Survivor list: bulk/run_s0001_proof/v11_validation.jsonl;
  full rescore table: bulk/run_s0001_proof/rescore.jsonl.
