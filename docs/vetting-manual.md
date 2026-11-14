# Vetting manual — the desk checks that turn a hit into a candidate (or kill it)

A sweep hit (SDE ≥ 8.5) is a suspicion, not a candidate. This manual
is the desk procedure: run the stages in order, record every verdict
in the standard verdict record (`schema/verdict-schema.json`), and
stop at the first kill. Nothing here touches the detection pipeline
(`hunter.py`, `persistence.py`, `holdout_test.py`, `bulk_screen.py`
live in the repo root); these tools vet what the pipeline found.

Canonical tools (all standalone CLIs, run from the repo root with the
project venv: `.venv/bin/python gauntlet/<tool>.py ...`):

| Stage | Tool |
|---|---|
| Raw-flux desk check + trapezoid shape gate | `gauntlet/rawflux_check.py` |
| Refined-ephemeris verification folds | `gauntlet/desk_finish.py` |
| Holdout prediction test | `holdout_test.py` (repo root), drivers `gauntlet/holdout_supp.py`, `gauntlet/holdout_extended.py` |
| Difference imaging / host localisation | `gauntlet/tesscut_fetch.py`, `gauntlet/tesscut_extract.py`, `gauntlet/diffimg.py` |
| Neighbour folds | `gauntlet/neighbour_fold.py` |
| Formal transit fit | `gauntlet/transit_fit.py`, `gauntlet/transit_fit_report.py` |
| Clean-data re-fold gate (bulk survivors) | `bulk/clean_refold_gate.py` |

Shared helpers (folding, flattening, TIC lookups, pixel utilities)
live in `gauntlet/common.py`. House npz convention: light curves are
saved as `<prefix>_s<NNN>.npz` with `time`/`flux` keys.

## 0. Catalogue check — first, always

Before any vetting, check whether the star is already catalogued:
VSX (raw-XML cone), the TOI table, and Planet Hunters Talk. A known
variable with the same period is a blend until difference imaging
proves otherwise — and a catalogue hit ends the gauntlet before it
starts. (The sweep's `skip_known` filter does this automatically; a
bulk-screen survivor needs the check by hand.)

Also verify the TIC row's identity (Gaia ID / position) before any
position-dependent step: a corrupt MAST cone response once poisoned
a whole census.

## 1. Clean-data re-fold gate (bulk-screen survivors only)

A survivor whose signal lives only in flagged cadences is not a
survivor. Re-fold the signal using quality == 0 cadences only
(`bulk/clean_refold_gate.py`, runs after recalibration, before
handoff). A signal that vanishes in clean data is a flagged-cadence
phantom — kill it here, before the gauntlet spends any time on it.
(TIC 344334378, sector 97: the signal lived only in quality-bit-30
flagged cadences and was absent in clean raw flux at every
phase, era, and product.)

## 2. Persistence in raw flux at a fixed ephemeris

Fold the RAW (unflattened) flux at the fixed period and epoch in
every sector and in each era separately, and keep the per-sector
depth and significance.

- **Refine the period FIRST for a bulk-screen survivor** (T0 fixed,
  period only): single-sector bulk periods carry errors (+0.0004 to
  −0.0036 d) that wash out fixed-phase folds over multi-year
  baselines — at the bulk period every signal reads ~0 outside its
  discovery sector and looks refuted. Run a phase scan and refine
  the period before any cross-sector fold. The refined period
  restores real signals at 10–104σ. **The bulk period alone is
  never a valid fold anchor.**
- Treat a signal that appears only in early or middle eras and
  vanishes in late eras as spot activity or an era artifact, not a
  planet, even when the combined fold looks strong.
- Run a free search in the sectors where the signal is absent, and
  require the free search to stay far below the detection threshold
  before you call the signal gone.
- Demote any persistence score from a module that masks sectors to
  advisory only: a masked module can lock onto rotation and report
  persistence the raw flux does not support.
- Book a low-persistence hit as stamp-convicted, not hand-vetted,
  and do not queue it for full vetting unless the run owner reopens
  it.
- Clipping rule: MAD-sigma clips can eat deep transits on quiet
  stars. Every clip in the vetting chain carries a 10% floor
  (never clip more than 10% of points in transit). If you add a
  new clip, add the floor with it.

Verdicts: **RAW-CONFIRMED** (raw ≥ 50% of filed depth at ≥ 3σ),
**RAW-WEAK** (real but much shallower / marginal), **RAW-REFUTED**
(no dip — a pipeline artefact; the pass-2 transit-masked
re-flatten can manufacture a dip out of broad variability).

## 3. Measure the transit shape before you name it

Fit a symmetric trapezoid to the folded raw flux at the desk check
(the shape gate in `rawflux_check.py`) and record T14, T23, and
T23/T14 before you make any shape claim.

- T23/T14 ≤ 0.30 is V-shaped and grazing — treat it as an
  eclipsing-binary suspect, not a planet; ≥ 0.50 is U-shaped;
  between is ambiguous.
- Never call a transit "flat-bottomed" or "box-shaped" from a
  box-versus-sinusoid comparison alone — a V is not a wave, so
  that test cannot see it, and it is exactly how a grazing transit
  was once published as a clean box.
- Use the fitted T14 (first to fourth contact), never the BLS box
  width, for every duration check. The BLS width is about the full
  width at half depth, only 0.5–0.7× T14 for a V-shaped transit,
  and feeding it into duration checks makes impossible transits
  look possible.
- Check the circular-orbit stellar density implied by the period
  and the fitted T14 against the TIC density. A transit longer
  than the longest central transit on its star cannot be a
  circular-orbit planet on that star — flag it and send the
  candidate to a formal transit fit before any public claim.

## 4. Odd/even, double period, and type

- Check for period aliases before you name a period, and test
  whether the true period is a multiple of the search period.
- Compare odd and even minima and their depths: a large odd-even
  difference is evidence for an eclipsing binary at twice the
  period.
- Distinguish a generic eclipsing binary from a contact binary
  and from ellipsoidal variation and spotted rotation, and keep
  the strict subtype open when the light curve cannot decide it.
- State the minima depths and the quadrature brightening with
  their significance, and do not claim a subtype the numbers do
  not support.

## 5. Holdout prediction test

Leave-one-sector-out: refit the ephemeris without each fold of
sectors and require it to predict that fold's dips in RAW flux at
≥ 3σ in a majority of folds. Stamps **HOLDOUT-PASS**,
**HOLDOUT-FAIL**, **HOLDOUT-INSUFFICIENT-DATA**.

A holdout pass proves predictive periodicity ONLY — a clean
eclipsing binary passes (control TIC 308851365 does) — and never
replaces the raw-flux, shape, or imaging gates. A HOLDOUT-PASS is
not a planet, not a confirmation, and not a discovery claim.

## 6. Localise the source before any claim

Run difference imaging or centroid localisation in several sectors
and eras before you name a source star, and record the distance
from the target in every sector. **Centroid/difference imaging is
mandatory before any discovery claim or filing.**

- Never use the contamination ratio alone to clear a blend: it
  describes a small nominal aperture while the light-curve
  aperture can be multi-pixel and can swallow a brighter neighbour
  a few pixels away.
- Search for a known variable within **180 arcseconds** with the
  same period, and treat an identical period in a neighbour as a
  blend until difference imaging proves otherwise. A 60″ cone
  missed a blend host at 66.5″ (TIC 139526205 / TIC 139524628,
  sector 97) — do not stop at 60″.
- Compare the target fold with the neighbour fold, and treat a
  near-identical shape with a scaled depth as a photocopy of the
  neighbour signal.
- Require the target signal to be physically possible as its own
  eclipse, and reject the target as source when the depth it
  would need exceeds what its own light can produce.

## 7. Check the pixels before a long-period claim

For a period of 8 days or longer, inspect the raw pixel flux at
the fixed ephemeris before you accept the dip. Aperture flux
alone can hide a scattered-light artifact.

- Refute the candidate when the pixels brighten where a dip is
  claimed. One 11.52-day claim showed pixels brightening by 3–5%
  with no dip at all.
- Compare the dip duration with the longest physical transit for
  the period and star. Treat a smooth sinusoid about five times
  the transit width as pulsation or rotation, not a transit.

## 8. Formal transit fit

Fit a physical transit model (`gauntlet/transit_fit.py`) before
any public claim or paper draft. The fit — not the BLS box — sets
the radius, impact parameter, and duration. A grazing fit
(b ≳ 1, T23/T14 ≲ 0.30) with a density tension against the TIC
value is an eclipsing-binary suspect, most plausibly a grazing EB
on an unresolved companion when Gaia RUWE is high. Run the fit
BEFORE posting anywhere: the shape gate screens, the fit decides.

## 9. File only after the blend check

- File a new variable star only after the persistence test and
  the difference-imaging test both pass, and keep the filing
  packet (period, epoch, magnitudes, plot) together.
- Check the submission queue first: only one submission can await
  review at a time. Do not start a filing that must wait behind a
  pending one.
- Leave a saved draft untouched when the run owner says to leave
  it: drafts cannot be deleted or withdrawn and expire on their
  own after about sixty days.
- Treat a cross-check that finds a candidate absent from the
  catalogue as credible only when a positive control with a known
  entry returns correctly.

## Prioritisation

Vet the strongest contenders first and book weak hits as
stamp-convicted, so limited vetting time goes to candidates that
can survive the persistence and blend tests. Re-run the raw-flux
test at the fixed ephemeris whenever a new sector arrives: a
signal that was persistent can still turn out to be era-confined.
