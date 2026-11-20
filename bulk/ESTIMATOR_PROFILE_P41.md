# Estimator timing profile — Phase 4.1 item 4.1-8 (PB-41-4b)

**Status:** measurement only. No optimisation code was written or
changed for this artifact. This is the profile-first artifact
required by C41-10 (COMPARISON_PHASE41.md): the profile is committed
BEFORE any optimisation of the estimator.

**Date:** 2026-11-18. **Machine:** Dev's Mac (10-core M4),
venv `bulk/.venv-mac/bin/python` (Python 3.11.15).
**Code profiled:** Mac repo copy at `2aa3e8e` (Phase 4 merge).
`bulk/k2_prototype.py` is md5-identical to this worktree's tip
`a5a3724` (`7e76a571…`); `bulk/oracle_run.py` and
`bulk/inject_real_s96.py` also match. `bulk_screen.py` differs
between the two tips only by commit `93b38b4` (bulk_v5 veto
extension: `_apply_profile` + `apply_epoch_cluster_veto`), which
does not touch `_fold_depth` or anything on the estimator path —
the profile below describes the worktree code exactly. Line
numbers below are the worktree's (`a5a3724`); `_fold_depth` sits
at line 922 in the Mac copy, 928 here (the 6-line shift is the
`93b38b4` delta above it).

## Method

Mirrors the P4-1b timing probe (P41B_RECORD.md §6.2): real cached
light curve **TIC 441081631, sector 95**
(`bulk/cache/s0095/441081631.fits`, 10,626 raw cadences,
7,983 after `preprocess_arrays`), calibration **bulk_v4**
(`bs.set_calibration("bulk_v4")`, as the campaign does),
recorded period **13.593519882179676 d** (oracle manifest,
TIC 441081631 `planet01` trial `recorded.period_days`).
Call sequence per trial is the campaign's (k2_run.py):
`estimate_ephemeris(t_p, f_p, p_rec)` then `scan_secondary`
at the returned ephemeris. One warm-up trial, then wall timing
(best of 3 per function, `time.perf_counter`), then cProfile
over 5 trials.

## Headline

| Function | Wall, best of 3 | P41B §6.2 (prior) |
|---|---|---|
| `estimate_ephemeris` (k2_prototype.py:154) | **0.410 s/call** (0.417, 0.414, 0.410) | 0.483 s/call |
| `scan_secondary` (k2_prototype.py:242) | **0.009 s/call** (0.009 × 3) | 0.010 s/call |
| Pair (per trial) | **0.416 s** (0.420, 0.416, 0.417) | 0.493 s |

0.410 s/call is ~2.0× a BLS screen (P41B's pass-1 screen:
0.209 s; P41B reported 2.3×). The 0.410 vs 0.483 s gap (~15%)
is unexamined — same target, sector, method, and code path;
machine load at probe time (P4-8 was building in parallel on
the Mac during P4-1b) is a hypothesis, not a proven cause.
Either figure leaves the conclusion unchanged: the estimator
is ~0.4–0.5 s/call and dominates the K=3 incremental cost.

## Cost driver: `bs._fold_depth`, confirmed

cProfile over 5 trials: 1,154,471 function calls in 2.318 s
(0.464 s/trial under the profiler vs 0.416 s wall — ~12%
profiler overhead, modest).

| Function | ncalls (5 trials) | tottime | cumtime | Share of total |
|---|---|---|---|---|
| `bulk_screen._fold_depth` (:928) | **16,850** | 1.118 s | 2.302 s | **99.3%** |
| `k2_prototype.estimate_ephemeris` (:154) | 5 | 0.011 s | 2.266 s | 97.7% |
| `k2_prototype._best_phase_snr` (:128) | 45 | 0.004 s | 0.622 s | 26.8% |
| `k2_prototype.scan_secondary` (:242) | 5 | 0.000 s | 0.052 s | 2.2% |
| `numpy.median` (via `_median`/`partition`) | 13,995 | — | 0.868 s | 37.4% |
| `numpy.std` | 13,995 | — | 0.140 s | 6.0% |
| `numpy.mean` | 27,990 | — | 0.083 s | 3.6% |

**Call counts confirmed exactly:** 16,850 `_fold_depth` calls
over 5 trials = **3,370 per trial**, matching the constant-
derived expectation with zero slack:

| Step | Calls/trial | Share |
|---|---|---|
| Step 1 refinement: 9 periods × 100 phases | 900 | 26.7% |
| Step 2 duration×phase grid: 6 durations × 400 phases | 2,400 | 71.2% |
| `scan_secondary`: 70 phases | 70 | 2.1% |
| **Total** | **3,370** | |

Per-call `_fold_depth` cost: 2.302 s / 16,850 ≈ 0.137 ms
(profiler); wall-implied ≈ 0.124 ms.

## Where the time goes inside `_fold_depth`

`_fold_depth`'s own code (tottime 1.118 s, 48.6% of its
cumtime) is the full-length array arithmetic per call: phase
fold `((t - t0) / period + 0.5) % 1.0 - 0.5`, the circular
distance, the in/out boolean masks, and the fancy-indexed
`f[inwin]` / `f[outwin]` — each call allocates several
~8,000-element arrays. The rest is reductions over the
out-of-window subset:

| Inside `_fold_depth` (cumtime 2.302 s) | s | Share |
|---|---|---|
| Own array arithmetic + indexing (tottime) | 1.118 | 48.6% |
| `np.median` (out-of-window baseline; `ndarray.partition` tottime 0.707 s) | 0.868 | 37.7% |
| `np.std` (noise estimate) | 0.140 | 6.1% |
| `np.mean` (in-window depth) | 0.083 | 3.6% |
| Other (sums, ufunc reduce, guards) | ~0.09 | ~4% |

Only 13,995 of 16,850 calls (2,799/trial, 83%) reach the
median/std: 571 calls/trial (17%) early-return on the guard
(`inwin < 3` or `outwin < 20`), before any reduction.

## Per-step split (measured, from the profiler)

| Step | s/trial (profiler) | Share |
|---|---|---|
| Step 1 refinement (`_best_phase_snr`, 9 periods) | 0.124 | 26.8% |
| Step 2 duration×phase grid (inline loop in `estimate_ephemeris`) | ~0.327 | ~70.5% |
| `scan_secondary` | 0.010 | 2.2% |
| `estimate_ephemeris` own code | 0.002 | 0.5% |

The time split tracks the call-count split almost exactly
(71% / 27% / 2%), so per-call cost is roughly uniform across
steps — Step 2 dominates because it makes the most calls, not
because its calls are more expensive.

## What this means for 4.1-8

- The optimiser's target is `_fold_depth` call volume and
  per-call cost: 3,370 calls/trial, of which the median alone
  is ~37% of the time and the per-call array arithmetic ~49%.
  Any optimisation that does not reduce `_fold_depth` work
  cannot move the number — `estimate_ephemeris`'s own code is
  0.5% of the cost.
- The required bars (C41-10): profile (this artifact) +
  per-trial preservation + both legs ≤4×; aspirational ≤2.5×
  via Gemini's ≥2× per-call speedup (≤0.24 s/call).
  Optimisation runs AFTER BP-1 (C41-10 dependency rule), so
  this artifact is the frozen baseline the optimisation is
  measured against: **0.410 s/call wall, 3,370 `_fold_depth`
  calls/trial**.
- The probe script was scratch (piped to the Mac, not
  committed), matching the P41B precedent; the method above
  is sufficient to re-run it.

## Raw cProfile output (top 25, cumulative)

```
         1154471 function calls in 2.318 seconds

   Ordered by: cumulative time

   ncalls  tottime  percall  cumtime  percall filename:lineno(function)
        5    0.000    0.000    2.318    0.464 <stdin>:55(trial)
    16850    1.118    0.000    2.302    0.000 bulk_screen.py:922(_fold_depth)
        5    0.011    0.002    2.266    0.453 k2_prototype.py:154(estimate_ephemeris)
    13995    0.006    0.000    0.868    0.000 numpy/.../_function_base_impl.py:3902(median)
    13995    0.011    0.000    0.862    0.000 numpy/.../_function_base_impl.py:3815(_ureduce)
    13995    0.029    0.000    0.849    0.000 numpy/.../_function_base_impl.py:3991(_median)
    13995    0.005    0.000    0.726    0.000 numpy/.../fromnumeric.py:732(partition)
    13995    0.707    0.000    0.707    0.000 {method 'partition' of 'numpy.ndarray' objects}
       45    0.004    0.000    0.622    0.014 k2_prototype.py:128(_best_phase_snr)
   131685    0.176    0.000    0.176    0.000 {method 'reduce' of 'numpy.ufunc' objects}
    13995    0.008    0.000    0.140    0.000 numpy/.../fromnumeric.py:3833(std)
    13995    0.010    0.000    0.133    0.000 numpy/.../_methods.py:217(_std)
    61690    0.009    0.000    0.132    0.000 {method 'sum' of 'numpy.ndarray' objects}
    61690    0.007    0.000    0.123    0.000 numpy/.../_methods.py:47(_sum)
    13995    0.071    0.000    0.121    0.000 numpy/.../_methods.py:148(_var)
    27990    0.013    0.000    0.083    0.000 numpy/.../fromnumeric.py:3699(mean)
    27990    0.029    0.000    0.070    0.000 numpy/.../_methods.py:115(_mean)
        5    0.000    0.000    0.052    0.010 k2_prototype.py:242(scan_secondary)
```

(Full paths elided for the numpy rows; Mac-copy line number
shown for `_fold_depth` — 922 there, 928 in this worktree.)
