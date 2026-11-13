# Injection–Recovery Test — Exoplanet Hunter Scanner Completeness

**What this is:** synthetic transits of known depth and period were planted
into real light curves of real stars the app itself measured as quiet, then
run through the production pipeline machinery. The recovery rate as a
function of depth × period is the Scanner's "hunting map."

**Headline result: 5 of 48 injected signals recovered clean (10.4%), 0
aliased, 0 of 8 control false alarms.** Recovery is real but narrow, and it
is dominated by *which star the signal sits on*, not just by the signal:
every recovery happened on just 2 of the 8 substrates. At super-Earth
depths (0.25–0.35%) the recovery rate was **0 of 16 at every period** —
with the Scanner's 2-sector recipe on faint FFI targets, signals that
shallow never reach the app's discovery threshold (best SDE in those rows:
4.2, against a threshold of 8.5).

Files: `injection_harness.py` (harness), `injection_report.py`
(aggregation + heatmap), `injection_results.json` (every trial's raw
record), `injection_heatmap.png` (the map). Nothing was pushed; no
production code was changed; the production server was not touched.

---

## Method

### Star sample (fixed up front, no substitutions)

The 5 targets of the completed sweep at RA 345.992 / Dec −22.568 (job
`bf3e0cb5938a473f`, "0 hit(s) out of 5 target(s)") plus the first 3
targets of the Stage-4 default-patch scan (job `fbadf15236df4533`,
RA 124.456 / Dec −67.568, "0 hit(s) out of 20 target(s)").

| TIC | Patch | Tmag | R★ (R☉) | Products fetched | Points | Cadence | Baseline | Raw flux scatter |
|---|---|---|---|---|---|---|---|---|
| 204317981 | 345.992 / −22.568 | 15.4 | 1.30 | 1 of 2* | 1,028 | 30 min | 27.4 d | 1.70% |
| 204316124 | 345.992 / −22.568 | 14.8 | 0.82 | 1 of 2* | 1,028 | 30 min | 27.4 d | 0.93% |
| 204317973 | 345.992 / −22.568 | 14.0 | 0.73 | 1 of 2* | 1,028 | 30 min | 27.4 d | 2.08% |
| 204316103 | 345.992 / −22.568 | 15.4 | 0.71 | 1 of 2* | 1,028 | 30 min | 27.4 d | 3.97% |
| 204317967 | 345.992 / −22.568 | 15.1 | 1.37 | 1 of 2* | 1,028 | 30 min | 27.4 d | 1.68% |
| 307164903 | 124.456 / −67.568 | 15.1 | 0.88 | 2 of 2 | 2,090 | 30 min | 56.2 d | 2.97% |
| 307164915 | 124.456 / −67.568 | 15.1 | 1.20 | 2 of 2 | 2,090 | 30 min | 56.2 d | **10.09%** |
| 307164924 | 124.456 / −67.568 | 15.1 | 1.40 | 2 of 2 | 2,090 | 30 min | 56.2 d | **11.33%** |

\* For all five stars of the 345.992 patch, the second requested product is
the corrupt-at-source file the healed fetch path skips — the *same*
outcome the production sweep itself got for these stars (its log shows
"Continuing with 1 of 2 product(s)"). The substrate is what production
actually analyzes, not an idealization of it.

Notes the numbers force on us:

- **Every substrate is 30-minute-cadence FFI data** (1,028–2,090 points).
  The Scanner's screened population (Tmag ≈ 14–15.4) lives on this data
  class; there is no 2-minute SPOC data in the sample.
- **Two substrates are photometrically loud**: TIC 307164915 and
  TIC 307164924 have raw scatter of 10–11% (large-amplitude variability
  and/or systematics). The app calls them "quiet" only in the sense of
  *no BLS hit*. They were kept in the sample, as fixed up front; their
  effect is broken out per-star below rather than hidden.

### Injection

Trapezoid transits (flat bottom = central 70% of duration, linear
ingress/egress = 15% of duration each side), multiplied into the raw
flux. Duration set by the prescribed rule `duration_hours = 2.0 ×
P_days^(1/3)` (2.29 h at P = 1.5 d … 4.70 h at P = 13 d). Epochs drawn
from `numpy.random.default_rng(seed = 20261103)` in fixed plan order and
recorded per trial in `injection_results.json`.

Grid: depths **[1.2, 0.8, 0.5, 0.35, 0.25, 0.15]% × periods [1.5, 4, 8,
13] d**, 2 trials per cell = 48 injection trials, plus **8 control
trials** (one per star, no injection). Trials rotated across the 8 stars
by global trial index (see the confound note under Results — it matters).

### Pipeline: what "production" means here

`hunter._run_pipeline` cannot be fed an in-memory curve without
refactoring production code (forbidden), and calling it would also
render a diagnostic PNG and append to `discoveries.csv` per call. The
harness therefore **mirrors** it, using production's own machinery
wherever a callable exists:

- *Fetch*: `hunter._with_download_self_heal` + `hunter._download_products`
  (the production healed path), first 2 sectors (Scanner `sector_cap=2`),
  stitched with the production corrector (`per-sector normalize`) and
  NaN-cleaned — byte-for-byte the construction of
  `hunter._fetch_stitched`, stopping before its outlier step.
- *Injection point*: the synthetic transit is multiplied in at that
  point, so the outlier clip sees the signal — exactly production's
  ordering for a real transit.
- *Processing* (copied step-for-step from `_run_pipeline`, Scanner
  settings): `remove_outliers(sigma=5.0)` → `flatten(window_length=101)`
  → BLS with `periods = linspace(0.5, 25, 10000)`, `durations =
  linspace(0.03, 0.25, 14)`, SDE by the production formula copied
  verbatim from the `_bls_best` closure, `(peak − median) / (std +
  1e-12)` → if the pass-1 transit mask covers ≤ 50% of the curve,
  re-flatten with the mask (the 2026-11-03 depth-recovery pass) and
  re-run the identical BLS; all metrics from pass 2.
- *Scoring*: **recovered** = best period within 1% of injected **and**
  SDE ≥ 8.5 (the app's discovery threshold); **aliased** = best period
  within 1% of P/2 or 2P at SDE ≥ 8.5 without a clean match.

**Mirror validation.** Before trusting the map, the mirrored pipeline
was run *uninjected* on WASP-126 b (TIC 25155310, first 2 sectors) and
compared against the production analyze job `43e0ab5fbba94772` on the
same data:

| | Period | Depth | SDE |
|---|---|---|---|
| Production job | 3.28919 d | 0.633% | 22.21 |
| This harness (mirror) | 3.28838 d | 0.633% | 22.23 |

Depth identical, SDE within 0.02, period within one BLS grid cell
(0.00245 d). The mirror measures what production measures.

---

## Results

### The grid (clean recovery; cell entries are the two trials' SDEs)

| Depth ↓ / Period → | 1.5 d | 4 d | 8 d | 13 d |
|---|---|---|---|---|
| **1.2%** | **50%** (16.0, 7.6) | 0% (2.8, 4.4) | **50%** (3.0, 11.2) | 0% (2.8, 4.3) |
| **0.8%** | **50%** (8.9, 4.3) | 0% (2.5, 2.5) | **50%** (2.9, 12.0) | 0% (2.9, 5.1) |
| **0.5%** | 0% (3.5, 3.4) | 0% (2.6, 2.5) | **50%** (3.0, 10.2) | 0% (2.8, 4.0) |
| **0.35%** | 0% (2.4, 3.5) | 0% (2.5, 2.3) | 0% (3.1, 4.2) | 0% (2.9, 3.9) |
| **0.25%** | 0% (3.5, 3.5) | 0% (2.6, 2.7) | 0% (3.0, 4.0) | 0% (2.9, 4.0) |
| **0.15%** | 0% (2.9, 3.4) | 0% (2.6, 2.3) | 0% (3.0, 4.9) | 0% (2.9, 4.0) |

Aliased recoveries: **0 in all 48 trials** — whenever BLS found a signal
it found the *right* period (recovered periods were within 0.03% of
injected: 1.4997 vs 1.5 d, 7.9977 vs 8.0 d). The failure mode is never
"wrong period"; it is "signal never rises above the periodogram noise."

With n = 2 trials per cell, percentages are coarse by construction
(0 / 50 / 100 only). No cell reached 100%.

### ⚠ Read the columns carefully — a design confound

The fixed rotation assigned each period column to the **same pair of
stars in every depth row** (P = 1.5 d → TIC 204317981 + 204316124;
P = 4 d → 204317973 + 204316103; P = 8 d → 204317967 + 307164903;
P = 13 d → 307164915 + 307164924). Depth is fully crossed with stars
(every star saw every depth), but **period is confounded with substrate
pair**: column differences partly measure which stars drew that period.
In particular, the all-zero P = 4 d column sat on two single-sector
stars that recovered nothing at any depth, and the P = 13 d column sat
on the two photometrically loud stars. The grid above is reported as
measured; the per-star table below is the honest lens for the period
axis. A crossed follow-up (every star × every period) would be needed
for a clean period axis — this run does not silently pretend to be one.

### Per-star breakout (6 injection trials each: all depths at one period)

| TIC | Period drawn | Recovered | Trial SDEs | Comment |
|---|---|---|---|---|
| 204317981 | 1.5 d | **2/6** | 16.0, 8.9, 3.5, 2.4, 3.5, 2.9 | Recovers 1.2% and 0.8%; 0.5% period-locked but SDE 3.5 |
| 204316124 | 1.5 d | 0/6 | 7.6, 4.3, 3.4, 3.5, 3.5, 3.4 | Closest miss of the run: 1.2% period-locked at SDE 7.6 |
| 204317973 | 4 d | 0/6 | 2.8, 2.5, 2.6, 2.5, 2.6, 2.6 | SDE never leaves the control band, even at 1.2% |
| 204316103 | 4 d | 0/6 | 4.4, 2.5, 2.5, 2.3, 2.7, 2.3 | Same |
| 204317967 | 8 d | 0/6 | 3.0, 2.9, 3.0, 3.1, 3.0, 2.9 | Flat ~3.0 regardless of injection |
| 307164903 | 8 d | **3/6** | 11.2, 12.0, 10.2, 4.2, 4.0, 4.9 | Best substrate: recovers down to 0.5% |
| 307164915 | 13 d | 0/6 | 2.8, 2.9, 2.8, 2.9, 2.9, 2.9 | BLS locks onto the star's own ~14.7 d variability in every trial, injected or not |
| 307164924 | 13 d | 0/6 | 4.3, 5.1, 4.0, 3.9, 4.0, 4.0 | BLS locks onto a ~1.2 d feature of the star itself in every trial |

Only 8 of 48 trials even *period-locked* onto the injection (at any
SDE); 5 of those 8 cleared SDE 8.5. On six of eight substrates, the
injected transit — even at 1.2%, the deepest in the grid — does not
move the BLS periodogram out of the range the same star produces with
nothing injected at all.

### Controls (no injection)

**0 of 8 false alarms.** Control SDEs: 2.29 – 4.91 (median ≈ 2.9). The
discovery threshold at 8.5 sits comfortably above this sample's noise
ceiling: on these targets the pipeline does not cry wolf. The problem
is the opposite — real signals mostly don't reach the line either.

### Depth calibration (bonus)

Median BLS depth error on period-locked trials, by injected depth
(small n — only locked trials can be scored):

| Injected depth | Locked trials | Median depth error |
|---|---|---|
| 1.2% | 2 | −7.9% |
| 0.8% | 2 | −9.5% |
| 0.5% | 1 | +3.2% |
| 0.35% / 0.25% / 0.15% | 0 | — (nothing locked to measure) |

Where the pipeline does lock on, it sizes the signal well: depths read
within ~10% (slightly low at the deep end, consistent with a box model
measuring a trapezoid), and periods within 0.03%. Measurement accuracy
is not the bottleneck; detection is.

---

## Plain-language readout

**Where hunting is worth it (≥ 50% recovery):** nowhere unconditionally.
Five cells reach 50% — (1.2%, 1.5 d), (1.2%, 8 d), (0.8%, 1.5 d),
(0.8%, 8 d), (0.5%, 8 d) — and in every one of them, "50%" means *the
one favorable substrate in the pair delivered and the other didn't*.
Translated: for deep signals (≳ 0.8%), the Scanner is a coin flip whose
outcome is decided mostly by the photometric quality of the star it
lands on. TIC 307164903-class substrates (two sectors, moderate
scatter) recover down to 0.5%; TIC 204317981-class (single sector,
quiet) recovers the two deepest rows at short period.

**Where it falls off:** below 0.5% depth, recovery is zero everywhere —
0 of 24 trials at ≤ 0.35%, on good substrates and bad, at short periods
and long. The falloff is a cliff, not a slope, and it sits between 0.5%
and 0.35% on the best substrate we have. Underneath the cliff, injected
signals typically produce SDE ≈ 3–4 — indistinguishable from what the
same stars produce with nothing injected (controls: 2.3–4.9).

**Super-Earth-class signals (0.25–0.35%):** not recoverable with this
recipe on this target class — 0 of 16, no near misses (best SDE 4.2 vs
the 8.5 line). This holds at P = 1.5 d (many transits, best case for
stacking) just as at 8–13 d. The depth-recovery fix of 2026-11-03 did
its job — where signals lock, depths now read true — but on faint
30-minute FFI curves with ≤ 2 sectors, a 0.25–0.35% transit simply does
not generate BLS significance ≥ 8.5 under the production SDE
normalization, whose denominator is inflated by the periodogram's own
red-noise scatter. What would move this line (implications, not tested
here): stacking more sectors per star, brighter targets with
2-minute-cadence data, and pre-screening out photometrically loud stars
like TIC 307164915/924, which consumed 12 of 48 trials without any
possibility of a recovery.

**What the map is really a map of:** less the sky than the substrate.
Given a quiet, multi-sector star, the Scanner certifies giant-planet
depths (≥ 0.8%) about half the time and Neptune depths (0.5%) on its
best behavior. Given a typical faint FFI target from its own screening
cone, it certifies almost nothing — while also, to its credit,
*claiming* almost nothing (0 false alarms). Any future completeness
claim for this app should be quoted per substrate class, not as a
single number; and a crossed-design rerun (every star × every period,
more trials per cell) is the honest way to sharpen the period axis
this run leaves confounded.
