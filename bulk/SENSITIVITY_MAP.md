# Bulk-screen sensitivity map: v1 vs v2 (2026-11-14)

The Phase 1.2 B-2 grid: 60 synthetic one-sector stars (depths
0.5/1.0/1.5/3.0%, per-point noise 0.1/0.3/1.0%, periods 2.17/7.31 d,
seeds 42/43, plus 12 noise-only nulls), each screened through the
REAL screen (`bulk_screen._screen_one` on synthetic QLP FITS)
under five clip settings — 300 runs, 135 s. Grid: `bulk/clip_grid.py`.
Criteria pre-registered in `bulk/CLIP_GRID_CRITERIA.md` before the
grid ran. Aggregates: `bulk/clip_grid_summary.json`. Per-cell
records: the grid's checkpoint JSONL (default `/tmp/clip_grid/`,
reproducible by re-running the grid).

"Recovered" = correct period (±1%) + SDE ≥ 7.0 + survivor status.
"SDE before/after preprocessing" = SDE with the clip bypassed
(`none`, the unclipped reference) vs SDE with the clip applied;
the flatten step is applied in both.

## Headline

| | v1 (`symmetric`) | v2 (`floor_10pct`) | unclipped ref |
|---|---|---|---|
| Deep-quiet recovery (depth ≥ 1.5%, noise ≤ 0.3%) | **4/16** | **16/16** | 16/16 |
| Overall recovery (48 inject cells) | 19/48 | 35/48 | 35/48 |
| Median deep-quiet SDE | 7.1 (min 5.4) | 79.8 (min 37.0) | 79.8 (min 37.0) |
| Mean transit samples surviving the clip | 58% | 100% | 100% |
| Monotonicity violations (deeper must score ≥ shallower) | 5 | 0 | 0 |
| Null false alarms (12 noise-only cells) | 0/12 | 0/12 | 0/12 |
| Max null SDE | 7.3 | 7.3 | 7.3 |

v2's numbers are identical to the unclipped reference on every
aggregate: the 10% floor never binds at depths ≤ 3%, so v2 clips
outliers without touching any transit in the grid. The clip choice
was a three-way tie between `upward_only`, `isolated_low_only`
and `floor_10pct` on every pre-registered criterion; the
pre-registered tiebreak picked `floor_10pct` (already in
production use in the gauntlet).

## Recovery by injected depth

| Depth | v1 recovered | v1 transit kept | v2 recovered | v2 transit kept |
|---|---|---|---|---|
| 0.5% | 6/12 | 85% | 6/12 | 100% |
| 1.0% | 4/12 | 65% | 8/12 | 100% |
| 1.5% | 6/12 | 51% | 10/12 | 100% |
| 3.0% | 3/12 | 33% | 11/12 | 100% |

v1's recovery is non-monotonic in depth — a 1.0% transit
recovers worse than a 0.5% one, and a 3.0% transit worse still.
The defect is worst on the quietest stars, exactly backwards
from a sensitivity standpoint: a 3.0% transit under v1 scores
SDE 5.4–7.2 on 0.1% and 0.3% noise (0/8 recovered, below the
survivor bar) but SDE 22.6–68.9 on 1.0% noise (3/4 recovered),
because the noisy star's MAD-sigma is large enough that the dip
survives the clip. The 0.5%-depth cells v2 still misses are
genuinely below the bar, not clip artifacts: 0/4 at 1.0% noise
(SDE 4.4–6.8) and 2/4 at 0.3% noise (the 7.31 d cells).

## The headline pair (0.3% noise, P 2.17 d, seed 42)

| Depth | v1 SDE | v1 status | v2 SDE | v2 status |
|---|---|---|---|---|
| 0.5% | 31.1 | survivor A | 31.1 | survivor A |
| 1.0% | 69.8 | survivor A | 72.6 | survivor A |
| 1.5% | 62.6 | survivor A | 101.7 | survivor A |
| 3.0% | 5.4 | below_floor | 140.5 | survivor A |

This pair (1.0% vs 1.5%) is the CI clip-grid test
(`tests/test_clip_grid.py`): monotonicity holds under v2 and is
a strict expected-failure under v1.

## EB handling changes with the clip

The clip fix also changes which period BLS prefers for deep
eclipsing binaries — and the screen's odd/even veto is a
half-period check, so it only fires when BLS finds the
half-period. The probe case (alternating 2% / 0.8% dips every
3 d, 0.5% noise, seed 42):

| | v1 | v2 |
|---|---|---|
| BLS period | 3.001 d (half-period) | 5.999 d (true EB period) |
| Depth | 1.24% (families folded together, deep one clipped) | 2.03% (deep family alone) |
| Odd/even ratio | 0.426 → ODD_EVEN_EB, demoted | 0.96 → no flag, survivor (tier A) |
| Secondary | 0.01% | 0.78% (recorded, below the 80%-of-primary bar) |

Under v1 the clip degraded the deep family enough that the
half-period won and the veto fired; under v2 the clean signal
finds the true period and the veto never applies. This is a
real behaviour change, not a bug: all three fix options share
it (they all preserve the deep dips), and the screen is a net,
not a verdict — the gauntlet's secondary/parity checks are the
defence for true-period EBs that survive it. It is pinned in
the suite (`test_deep_eb_found_at_true_period_under_v2`), and
the odd/even veto test now uses a 12 d-spacing EB (true period
24 d, outside the 20 d search range, so the half-period veto
fires under both calibrations).

## What this means for S96–S98

The v1 screens systematically missed deep transits on quiet
stars — the S96–S98 survivor lists carry that blind spot, and
the "~111,000 stars, 0 planets" ledger line carries its
asterisk until the rescore. `bulk/rescore_v2.py` re-screens the
affected stars (those whose 5σ clip level sits below 3%) under
v2; the ledger integration is Release C's job (C-3).

## What the grid did NOT decide

Thresholds (all v1 values carried over unchanged into v2),
systematic windows (hard-coded from the S96–S98 recalibration
notes, not from the grid), and the default (v1 stays the default
until a run opts into v2 — new sectors screen under v2, and the
v1 gate refuses v1 on any sector outside 96–98).

## v3: the quality mask (2026-11-15)

The v2 rescore gauntlet (S96, 25 NEW tier-A leads, 0 planets)
found 18/25 were flagged-cadence artifacts — dips of 1.5–9.3%
present ONLY on quality bit-29/30 cadences (TESS scattered
light), with zero clean cadences in transit. v2's 10% clip floor
preserves those deep flagged dropouts, so the screen promoted
them. v3 (`calibration/bulk_v3.yaml`) masks bits 29/30 at screen
input: `quality_mask` 1610629823 = lightkurve default 17087 +
bits 29/30. All v2 thresholds carried over unchanged.

Grid re-run under v3 (`EXHUNT_BULK_CALIBRATION=bulk_v3`, the
`floor_10pct` option, 60 runs): the grid fixtures have
quality==0 everywhere, so the mask is a no-op and v3 reproduces
v2's numbers EXACTLY — deep-quiet 16/16, overall 35/48, null
false alarms 0/12, 0 monotonicity violations. The mask changes
nothing on clean data (also pinned in CI by
`test_monotonicity_under_v3`, which asserts v3's headline-pair
SDEs equal v2's).

Sensitivity cost of the mask, measured by a flag-fraction sweep
(WASP-29b-equivalent transit, P 3.9227 d, 1.14%, 0.3% noise;
bit-29 flags on 5/10/20% of cadences). Script:
`bulk/flag_fraction_sweep.py` (committed, seeded, re-runnable;
`--quick` runs the 3-cell CI subset). The first version lived
in /tmp and was lost to a VM replacement; this table is from
the committed rewrite (M-5, 2026-11-15), whose numbers are
close to the original's (clean cell identical; random cells
within ~2 SDE) but not bit-identical — the original flag seeds
are unrecoverable. Conclusions unchanged.

| Cell | v2 SDE / MES | v3 SDE / MES | v3 status |
|---|---|---|---|
| clean | 50.0 / 17.5 | 50.0 / 17.5 | survivor A |
| random 5% all | 50.0 / 17.5 | 45.8 / 17.6 | survivor A |
| random 10% all | 50.0 / 17.5 | 42.9 / 18.0 | survivor A |
| random 20% all | 50.0 / 17.5 | 41.6 / 18.6 | survivor A |
| random 10% off-transit | 50.0 / 17.5 | 46.5 / 18.7 | survivor A |
| random 20% off-transit | 50.0 / 17.5 | 40.6 / 18.3 | survivor A |
| blocks 10% all | 50.0 / 17.5 | 40.4 / 16.2 | survivor A |
| blocks 20% all | 50.0 / 17.5 | 28.7 / 13.8 | survivor A |
| blocks 10% off-transit | 50.0 / 17.5 | 45.5 / 17.5 | survivor A |
| blocks 20% off-transit | 50.0 / 17.5 | 42.6 / 17.7 | survivor A |
| marginal 0.5% clean | 18.9 / 8.5 | 18.9 / 8.5 | recorded |
| marginal 0.5% random 10% all | 18.9 / 8.5 | 16.3 / 9.2 | survivor A |
| marginal 0.5% random 20% all | 18.9 / 8.5 | 16.6 / 9.1 | survivor A |

Random flags: the mask costs SDE (up to ~20% at 20% flagging —
fewer cadences in the fold) but MES is preserved or slightly
improved in every cell, and no real transit was lost at any
flag fraction tested. One marginal shallow cell (0.5% depth,
MES 8.5 under v2, just below the tier-A bar of 9.0) crossed the
OTHER way under v3 at 10–20% flagging (MES 9.2, survivor A) —
at the boundary the mask's effect on MES can go either way;
the sweep does not claim a systematic sensitivity gain.

Contiguous blocks (Gemini's topology critique, 2026-11-15 vote:
real bits 29/30 come in 0.5–2.5-day blocks, not random
sprinkles) cost MORE than random flags at the same fraction: at
20% block flagging the v3 SDE falls 43% (50.0 → 28.7) and MES
21% (17.5 → 13.8) — a 2-day block can swallow whole transits.
The transit still survives as tier A (MES 13.8 vs the 9.0 bar)
with margin, and blocks that avoid the transit cost no more
than random flags. The block variant is the harsher, more
realistic bound on the mask's cost.

Injection into REAL S96 light curves (M-6, 2026-11-15; Claude's
item (d)): trapezoid transits injected into the six S96 files
on the VM — all carrying bit 30 (9–13%), two carrying bit 29
(~28%) — and screened under v2 vs v3. Script:
`bulk/inject_real_s96.py`; summary:
`bulk/inject_real_s96_summary.json`. Trials: A = 2.0% @ 5.123 d,
B = 1.0% @ 3.317 d. Recovery = survivor + period within 1%.

| TIC | bit29 / bit30 | v2 recovered | v3 recovered |
|---|---|---|---|
| 231011325 | 0% / 9.4% | 0/2 (demoted) | 2/2 |
| 231852754 | 0% / 10.1% | 0/2 (demoted) | 0/2 (demoted) |
| 234510264 | 0% / 10.1% | 1/2 | 2/2 |
| 237911080 | 0% / 10.1% | 1/2 | 2/2 |
| 31852076 | 28.0% / 9.9% | 0/2 (demoted) | 2/2 |
| 382069441 | 28.2% / 12.8% | 0/2 (recorded) | 0/2 (survivor, wrong P) |
| **total** | | **2/12** | **8/12** |

**v3 lost 0/12 relative to v2** — it recovered everything v2
recovered, plus six more. The v2 failures are instructive: on
231011325, 237911080 (trial B) and 31852076, v2's BLS finds a
deep (>3%) ~13.1 d systematic — the flagged-cadence dropouts
themselves — and the DEPTH_EB veto demotes the star. Masking
the flagged cadences removes the systematic and the injected
transit recovers (31852076: v2 SDE 15–16 demoted → v3 SDE
33–44 recovered). The four v3 non-recoveries are host-confusion,
not mask losses: on 231852754 BLS finds the host's own 5.78 d
5.8% dipper signal (DEPTH_EB, identical under v2 and v3), and
on 382069441 it finds the host's own 5.50 d 1.3% persistent
signal (same period in both trials, both calibrations — the
injection never wins on those hosts). Pinned in CI by
`tests/test_inject_real_s96.py` on the committed 31852076
substrate (v2 demoted, v3 recovered, both trials).

Artifact rejection is pinned in `tests/test_quality_mask.py`:
five synthetic cells at real gauntlet periods/depths (bits 29/30,
flag fractions 0.7/1.0) promote under v2 and fall below the
record floor under v3. The clean-data re-fold gate is unchanged
and remains the second line of defence (still pinned in
`test_flagged_cadence_signal_gate_fails` on the v2-promoted
signal).
