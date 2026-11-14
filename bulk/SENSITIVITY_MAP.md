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
