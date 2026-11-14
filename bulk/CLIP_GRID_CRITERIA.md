# Clip-option selection — PRE-REGISTERED criteria (Phase 1.2, B-2)

**Written and committed BEFORE the grid ran.** The clip option for
`bulk_v2` is chosen by these criteria, not by eyeballing the
results afterwards. If the grid contradicts these criteria, the
criteria win and the contradiction is reported, not resolved by
re-picking.

## The defect (settled, brief §B-2)

The bulk screen's 5σ MAD clip has no depth floor. On a quiet
0.3%-noise star, a 1.5% transit scores LOWER (SDE 62.6, depth
biased to 1.31%) than a 1.0% one (SDE 69.8) — verified on
synthetic FITS 2026-11-14. A detector whose score falls as the
signal grows is broken under any calibration.

## Candidate clip options

All four run through the REAL screen (`bulk_screen._screen_one`
on synthetic QLP FITS) — no mirrors, no re-implemented BLS.
The clip itself is the one shared function (`mad_clip.py`).

| Option | Rule |
|---|---|
| `symmetric` (v1) | keep \|f − med\| < 5σ, both sides |
| `upward_only` | clip only positive outliers (f > med + 5σ); every dip survives |
| `isolated_low_only` | clip a low point only when neither neighbour is also low (transits come in runs; isolated dips are glitches) |
| `floor_10pct` (gauntlet) | lower cut floored at 10% below the median: keep f > med − max(5σ, 0.10) |

A fifth option, `none` (no clipping), runs in the grid ONLY as
the unclipped reference for the "SDE before/after preprocessing"
column. It is never a profile option.

## The grid (fixed before running)

Synthetic one-sector stars (30-min cadence, 1296 points, 27 d),
box transits, duration 0.1 d, via `tests/synth_fits.py`:

- Depths: 0.5%, 1.0%, 1.5%, 3.0%
- Noise (per-point σ): 0.1%, 0.3%, 1.0%
- Periods: 2.17 d, 7.31 d
- Reps: 2 seeds (42, 43)
- Nulls (no injection): 4 seeds (42–45) per noise level

60 cells × 5 clip settings (4 options + `none` reference) = 300
screen runs, each ~0.5 s — a few minutes, checkpointed to JSONL
so an interrupted run resumes (`bulk/clip_grid.py --resume`).

Per cell the grid records: recovered period (within ±1% of
injected), SDE, measured depth, status/tier, transit samples
surviving the clip (fraction of in-transit points the clip
keeps), and SDE with the clip bypassed (`none`).

## Selection criteria (in order)

1. **Maximum deep-transit recovery (primary).** Recovery =
   correct period (±1%) AND SDE ≥ 7.0 (the screen bar) AND
   status survivor, on the deep cells: depths ≥ 1.5% on quiet
   stars (noise ≤ 0.3%). The option with the highest recovery
   fraction on those cells wins.
2. **Goldens unchanged (guardrail).** The full offline suite
   (99 tests) passes with the chosen option wired in as
   `bulk_v2`. An option that breaks a golden is disqualified,
   however it scores on criterion 1.
3. **No worse false-alarm rate (guardrail).** Null-trial
   false-alarm rate = fraction of noise-only cells reaching
   status survivor. The chosen option's null rate must not
   exceed v1's null rate on the same seeds. (Both are expected
   to be 0; the guardrail bites if an option lets noise through.)
4. **Monotonicity (guardrail).** On every (noise, period, seed)
   slice, the deeper transit must not score below the shallower
   one: SDE(1.5%) ≥ SDE(1.0%) and SDE(3.0%) ≥ SDE(1.5%). The
   chosen option must satisfy this on all slices; v1 is
   expected to fail it (strict xfail in the suite).

**Tiebreak:** if two options tie on criterion 1 and pass all
guardrails, prefer the one already in production use
(`floor_10pct` — the gauntlet's clip) over a new behaviour;
prefer the simpler rule over the cleverer one.

## What the grid does NOT decide

- The survivor bar, tiers, or any other threshold: all carried
  over from v1 unchanged.
- The systematic windows: hard-coded from the RECALIBRATION
  reports (brief §1), not derived from the grid.
- Whether v2 becomes the default: v1 stays default; v2 is
  selected explicitly (`--calibration bulk_v2`).
