# Depth Under-Recovery Fix — Report (2026-11-03)

**Status: built and fully tested on this server. NOT pushed to GitHub** —
ready for the user's push on waking, per his instruction.

## TL;DR

The analyze pipeline was reporting WASP-126 b's transit depth as **0.217%**
where the data itself carries a **0.63%** signal — a ~2.9× squash that made
small planets (super-Earths at ~0.3%) undetectable. The guilty stage is the
**flatten (detrend) step**: the trend it removes sags **~0.43% in-transit at
every window length**, i.e. the "trend" was eating the transit. The fix is a
**transit-masked second detrend pass** inside `_run_pipeline`: after the
unchanged first BLS finds the signal, the light curve is re-flattened with
the detected transits masked out of the trend fit (lightkurve's `mask=`
exists for exactly this), and the identical BLS is re-run. All reported
metrics now come from the second pass.

Result (API, WASP-126 b, 2 sectors, R★ = 1.30 R☉): **depth 0.204–0.217% →
0.633%**, **radius 6.41 → 11.28 R⊕** (catalog 10.7), period unchanged
(3.28919 d), SDE 22.2 (historical range 21.9–24.8).

**One number needs the user's attention** — the ≥ 0.70% depth bar was NOT
met, and the autopsy shows it cannot be met on this data by any detrending
choice: BLS on the completely *unflattened* curve reports 0.628%, and the
deepest fold bin reads 0.654%. The sectors 1–2 data simply does not contain
a 0.94% signal (see "The 0.94% question" below). The fix recovers
essentially 100% of the depth that is actually in the data.

---

## Phase 1 — Autopsy (WASP-126 b, first 2 SPOC sectors, 2-min cadence)

Fold depth = (median out-of-transit − median in-transit) / median out, at
P = 3.2822 d, full duration window 0.132 d, epoch derived from the raw data
itself by a full-period scan (t0\* = 1327.57463 BTJD; an early pass anchored
on the production BLS epoch read ~25% low at *every* stage due to epoch
smearing, so all numbers below use the data-derived anchor consistently).

| Stage | Fold depth | Notes |
|---|---|---|
| (a) Raw stitched + normalized (+ remove_nans) | **0.6106%** | the signal as it arrives |
| (b) After `remove_outliers(sigma=5)` | **0.6016%** | 43 pts dropped, only 27 of 1,492 in-transit — **acquitted** |
| (c) After flatten, window 101 (production) | **0.1699%** | trend sags **0.4214%** in-transit |
| (d) After flatten, window 501 | **0.1876%** | trend sags **0.4285%** in-transit |
| (e) After flatten, window 1001 | **0.1927%** | trend sags **0.4264%** in-transit |
| (f) BLS-reported depth, production curve | **0.2173%** | what analyze reported (P = 3.28919 d, SDE 24.82) |
| Catalog "truth" (benchmark tables) | 0.9400% | see below — not present in this data |

### What convicts flatten — and refines the original hypothesis

The parent's hypothesis (window 101 ≈ 3.37 h ≈ the 3.17 h transit, so the
Savitzky-Golay trend follows the dip) is **true but only half the story**:

- Plain scipy savgol on the same curve (no lightkurve machinery):
  window 101 → **0.003%** survives (total annihilation — the window effect
  is real), 501 → 0.365%, 1001 → 0.494%. A bigger window alone would have
  helped substantially.
- But lightkurve's `flatten` at window 1001 still reads **0.193%** — its
  iterative sigma-mask + trend-interpolation machinery caps recovery at
  ~0.19% regardless of window (variants: niters=1 → 0.204% @501;
  sigma=10 → 0.338% @501, approaching plain-savgol behaviour). The measured
  trend sag is window-independent (~0.43%), which no linear filter can
  produce at a 33 h window; it comes from the mask/interpolate interaction
  around the masked-out transit cores.
- **Explicitly masking the transits** out of the trend fit breaks the cap:
  fold depth 0.482% (w=101) / 0.516% (w=501) on the median metric, and —
  the metric analyze actually reports — **BLS depth 0.628–0.633%**, vs
  0.628% for BLS on the raw unflattened curve and 0.217% for production.

### The 0.94% question (honest flag)

Every method applied to sectors 1–2 — raw fold (0.611% median / 0.654%
central bins), raw BLS (0.628%), masked-detrend BLS (0.633%) — converges on
**~0.60–0.65%**, and both sectors independently read 0.602%. The benchmark
tables' pair (depth 0.940%, radius 10.7 R⊕ at R★ = 1.30 R☉) is also
internally inconsistent: 0.940% at 1.30 R☉ implies Rp = 13.7 R⊕, while
10.7 R⊕ at 1.30 R☉ implies depth 0.569%. (10.7 R⊕ + 0.94% are consistent
with each other only at R★ ≈ 1.02 R☉.) So the "4.6× squash" was really
~2.9× against the in-data truth — still the difference between detecting
and missing a super-Earth, and now fixed. If the user wants the 0.94%
figure itself adjudicated, that is a literature/photometry question
(different bandpass/epoch), not a pipeline one.

---

## Phase 2 — The fix (hunter.py, `_run_pipeline` only)

Exact change (single hunk + one cleanup line; BLS grid, SDE formula,
thresholds and verdict logic untouched):

1. The production BLS block is factored into a local `_bls_best(tt, ff)`
   helper — byte-identical grid (`linspace` periods/durations) and SDE
   formula — returning the periodogram + best-fit scalars.
2. Pass 1 runs exactly as before (default flatten, `detrend_window`).
3. **Depth-recovery pass:** phase-fold the pass-1 solution; build a mask
   over |phase| ≤ duration/2 + 0.02 d; if the mask covers ≤ 50% of the
   curve, re-flatten `lc_raw` with `mask=_transit_mask` (same
   `detrend_window`) and re-run `_bls_best`. All reported scalars, the
   fold arrays, the diagnostic PNG and the discoveries log entry come
   from pass 2. A progress line ("Refining depth: re-detrending with
   transits masked out of the trend fit...") marks the step.
4. Guard rationale: above 50% masked there is too little unmasked curve
   to anchor a trend. The line was initially 35% and was raised after
   TIC 308851365 (38% masked: 0.249 d eclipses on a 0.759 d period) was
   shown to be silently skipped by it — its depth now recovers too.

The odd/even path (`_fetch_flattened`) was deliberately **not** changed:
its verdict is a depth *ratio* (insensitive to the squash), and scoping
the fix to the analyze path kept the change minimal. Its absolute depths
remain under-recovered (see regressions) — a possible follow-up.

## Before / after — analyze via the API

| Target | Metric | Before | After | Job (after) |
|---|---|---|---|---|
| WASP-126 b, cap 2, R★ 1.30 | Period | 3.28919 d | 3.28919 d | `43e0ab5fbba94772` |
| | Depth | 0.2173% (0.204% in Stage 1) | **0.6328%** | |
| | SDE | 24.82 | 22.21 | |
| | Radius | 6.41 R⊕ | **11.28 R⊕** | |
| TIC 308851365, cap 12, R★ 1.0 | Period | 0.75873 d | 0.75677 d | `3e8083d99734476c` |
| | Depth | 1.2175% | **1.2570%** | |
| | SDE | 46.60 | 44.43 | |
| | Radius | 12.04 R⊕ | 12.23 R⊕ | |

WASP-126 b round-1 and round-2 analyze jobs (`68cf34f5ef3f48d7`,
`43e0ab5fbba94772`) returned bit-identical metrics — the fix is
deterministic.

## Regressions (all real, through the API, final code)

1. **QA benchmarks** (job `be05f4b677cc43f5`): **WASP-126 b PASS**
   (recovered 3.28838 d, Δ = 0.0084 d, Rp 11.31 R⊕, SDE 14.12).
   **TOI-114 DRIFT** (11.91 d, SDE 2.11) and **Pi Mensae c DRIFT**
   (16.51 d, SDE 4.27) — **loudly noted, and proven NOT to be caused by
   this fix**: an A/B run of `run_qa` under the *original pre-fix*
   hunter.py (fetched read-only from GitHub main) in the identical
   harness tonight gives TOI-114 → 8.88 d (SDE 6.43, DRIFT) and
   Pi Mensae c → 24.60 d (SDE 4.35, DRIFT), WASP-126 b PASS (SDE 14.61).
   Both weak benchmarks currently fail under *both* code versions — at
   SDE 2–6 their "recovered periods" are noise-peak argmaxes that land
   differently on any curve perturbation. This is a pre-existing
   condition of tonight's product selection/data, not a regression of
   the depth fix; it deserves its own investigation (first-sector
   product mix for these two TICs is the first place to look).
2. **Odd/even, WASP-126 b, cap 2** (job `e31e9ae5c4194f7d`):
   **planet-like** ✓ — depths 0.0852% / 0.0813%, ratio **0.9552**
   (was 0.955). Absolute depths unchanged, as expected: that path was
   not modified.
3. **Double-period, TIC 308851365 @ 0.75677, cap 2**
   (job `4736ae7f8b50421a`): **likely-binary** ✓ (+0.533% at 10.8σ —
   identical to the double-period build's own validation numbers; raw
   data path untouched).
4. **Analyze TIC 308851365, cap 12**: DONE — depth rose 1.2175% →
   1.2570% (table above).
5. **Sweep smoke** (RA 345.992, Dec −22.568, cone 0.10, limit 5,
   scanner=true; jobs `6e7d3f49909c4d1c` and `2762f7d2b68945dc`):
   **DONE** — 5/5 targets analyzed, 0 hits, no false positives from the
   masked second pass on noise targets.

## Caveats

- **SDE cost ~10% on strong signals** (24.8 → 22.2 WASP 2-sector;
  46.6 → 44.4 for the EB): pass-2 metrics come from the re-detrended
  curve, whose noise properties differ slightly. All values remain far
  above detection thresholds and inside the historical run-to-run range
  (21.9–24.8 for WASP-126 b).
- **Runtime:** analyze now runs BLS twice (≈1.5–2× analyze wall time;
  WASP-126 b job: 40 s with warm cache).
- **Long-duration / high-duty-cycle signals:** masking protects long
  transits *better* than the old code (the trend can no longer follow
  them), but signals whose transits would mask > 50% of the curve skip
  the refinement and keep pass-1 (under-recovered) depths.
- **Variable stars:** detrending quality for slow variability is
  unchanged in pass 1; pass 2's mask is anchored on the pass-1 peak, so
  for a genuinely variable star the mask may cover a spurious phase
  window — in the sweep smoke test this produced no false hits and no
  failures.
- **Detrend window semantics unchanged:** `detrend_window` (default 101)
  now applies to both passes; the fix does not depend on enlarging it.

## State left behind

- Server **running** on the final code (uvicorn, port 8000, `/health`
  OK at the end of testing).
- Only `hunter.py` changed (plus this report). Frontend untouched.
- **Nothing pushed to GitHub** — the change is ready for the user's
  push (`hunter.py` + this report) when he wakes.
