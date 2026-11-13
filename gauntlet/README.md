# The vetting gauntlet

A sweep hit (SDE ≥ 8.5) is a suspicion, not a candidate. The gauntlet
is the desk-check pipeline that turns a hit into a candidate — or
kills it. A kill at any stage ends the run. Nothing here touches the
detection pipeline (`hunter.py`, `persistence.py`, `holdout_test.py`,
`bulk_screen.py` all live in the repo root); these tools vet what the
pipeline already found.

Every tool is a standalone CLI (`--help` on each). Run from the repo
root with the project venv:

```bash
.venv/bin/python gauntlet/<tool>.py ...
```

Shared helpers (folding, flattening, TIC lookups, pixel utilities)
live in `common.py`. House npz convention: light curves are saved as
`<prefix>_s<NNN>.npz` with `time`/`flux` keys (TESSCut files also
carry `flux_bgreg`, `flux_detrended`, `bg`).

## The gauntlet in order

### 0. Catalogue check — first, always

Before any vetting, check whether the star is already catalogued:
VSX (raw-XML cone, ≤ 60″), the TOI table, and Planet Hunters Talk.
A known variable with the same period is a blend until difference
imaging proves otherwise — and a catalogue hit ends the gauntlet
before it starts. (The sweep's `skip_known` filter does this
automatically; a bulk-screen survivor needs the check by hand.)

Also verify the TIC row's identity (Gaia ID / position) before any
position-dependent step: a corrupt MAST cone response once poisoned
a whole census.

### 1. Raw-flux desk check + trapezoid shape gate — `rawflux_check.py`

Folds the UNFLATTENED flux at the filed ephemeris in every product
family (ELEANOR-lite / QLP / SPOC / TESS-SPOC) and every sector, and
measures the dip against the filed depth:

- **RAW-CONFIRMED** — raw ≥ 50% of filed at ≥ 3σ (chunked red-noise
  significance, persistence.py style)
- **RAW-WEAK** — real but much shallower / marginal
- **RAW-REFUTED** — no dip: a pipeline artefact (the pass-2
  transit-masked re-flatten can manufacture a dip out of broad
  variability — TIC 294873918)

The sweep chain is replicated first (SG flatten ~2.0 d + BLS v2 +
pass-2) to recover the filed ephemeris (t0, duration at the filed
period). For a bulk-screen survivor, pass the ephemeris directly
(`--period/--depth/--t0/--duration --skip-replication`).

**The shape gate is mandatory before any shape claim.** A symmetric
trapezoid fit to the folded raw flux records T14, T23 and T23/T14:

| T23/T14 | verdict |
|---|---|
| ≤ 0.30 | V-shaped — grazing, an eclipsing-binary suspect, not a planet |
| 0.30–0.50 | ambiguous |
| ≥ 0.50 | U-shaped |

Never call a transit "flat-bottomed" or "box-shaped" from a
box-versus-sinusoid comparison alone — a V is not a wave, so that
test cannot see it, and it is exactly how a grazing transit was once
published as a clean box. Use the fitted T14 (first to fourth
contact), never the BLS box width, for every duration check: the BLS
width is about the full width at half depth, only 0.5–0.7× T14 for a
V-shaped transit. The gate also checks the circular-orbit stellar
density implied by (P, T14) against the TIC density — a transit
longer than the longest central transit on its star cannot be a
circular-orbit planet on that star.

```bash
# sweep hit (filed ephemeris recovered by replication)
.venv/bin/python gauntlet/rawflux_check.py 423498314 \
    --result-json result.json --workdir work/423498314
# bulk survivor / ad-hoc (explicit ephemeris)
.venv/bin/python gauntlet/rawflux_check.py 423498314 \
    --period 0.827048 --depth 1.03 --t0 3988.91522 --duration 0.04 \
    --skip-replication --workdir work/423498314
```

Writes `work/423498314/data/*.npz`, `rawflux_results.json`, `folds.png`.
`RAWF_RHO_STAR` overrides the TIC stellar density used by the gate.

### 2. Refined-ephemeris verification folds — `desk_finish.py`

For a bulk-screen survivor, run a phase scan and refine the period
FIRST (T0 fixed, period only): single-sector bulk periods carry
errors (+0.0004 to −0.0036 d) that wash out fixed-phase folds over
multi-year baselines — at the bulk period every signal reads ~0
outside its discovery sector and looks refuted. The refined period
restores real signals at 10–104σ. The bulk period alone is never a
valid fold anchor.

Then verify at the refined ephemeris: per-product and per-sector raw
depths, the secondary-eclipse fold at phase 0.5, odd/even split by
NEAREST event (floor parity mixes the halves of every eclipse and
erases a real difference), the optional P/2 alias test (`--half`:
two comparable minima mean the filed period is the P/2 alias of an
EB), and the optional free BLS + Lomb-Scargle sub-floor check
(`--bls`: looks for an independent sub-0.5 d fundamental the
pipeline's 0.5 d floor could not see).

```bash
.venv/bin/python gauntlet/desk_finish.py 423498314 \
    --period 0.827048 --t0 3988.91522 --duration 0.04 \
    --bulk-period 0.8269868 --data-dir work/423498314/data \
    --out finish_results.json --bls --half
```

A signal that appears only in early or middle eras and vanishes in
late eras is spot activity or an era artifact, not a planet, even
when the combined fold looks strong.

### 3. Holdout prediction — `holdout_test.py` + `holdout_supp.py` + `holdout_extended.py`

Leave-one-sector-out: refit the ephemeris without one sector group
and require the refined ephemeris to predict that group's dips in
raw flux at ≥ 3σ in a strict majority of folds, combined ≥ 3σ, with
no fold showing a significant opposite signal. Stamps:
`HOLDOUT-PASS` / `HOLDOUT-FAIL` / `HOLDOUT-INSUFFICIENT-DATA`.

**A pass proves predictive periodicity only — a clean eclipsing
binary passes this test.** It complements the raw-flux, shape and
imaging gates and never replaces them.

- `holdout_test.py` (repo root) — the canonical test; fetches data
  via the production pipeline. Needs ≥ 3 sectors.
- `holdout_supp.py` — for stars with too few sectors: independent
  single-sector BLS, within-sector split-half holdout (odd/even
  transit parity), and the cross-era phase-coherence budget.
- `holdout_extended.py` — the canonical fold loop verbatim over an
  extended sector set mixing pipeline and TESSCut sectors. Runs both
  flux variants and reports both stamps: plain raw and bg-regressed
  raw (the stage-5c common-mode recipe; QLP raw flux is already
  systematics-corrected, TESSCut raw pixels are not).

```bash
.venv/bin/python holdout_test.py 423498314 0.827048 3988.91522 0.96
.venv/bin/python gauntlet/holdout_supp.py 423498314 \
    --period 0.827048 --t0 3988.91522 --duration 0.04 \
    --data-dir work/423498314/data --prefix qlp --sectors 32 98
.venv/bin/python gauntlet/holdout_extended.py 423498314 \
    --period 0.827048 --t0 3988.91522 --duration 0.04 \
    --data-dir work/423498314/data \
    --sectors qlp:32 qlp:98 tesscut:107 tesscut:108
```

### 4. Difference imaging / host localisation — `tesscut_fetch.py`, `tesscut_extract.py`, `diffimg.py`, `neighbour_fold.py`

Mandatory before any discovery claim or filing: a dip that doesn't
come from the target's pixels is a blend, whatever the folds say.

- `tesscut_fetch.py` — downloads TESSCut FFI cutouts for given
  sectors (the imaging substrate for stars with no 2-minute data)
  and records the WCS identity (target/neighbour pixel positions +
  flux-centroid cross-check). Off-CCD / missing sectors are recorded
  as NO-DATA, never silently skipped.
- `tesscut_extract.py` — extracts aperture light curves from the
  cutouts (Gaussian σ 1.2/0.8 + 3×3), three flux variants per
  aperture (raw / bg-regressed / detrended), folds all of them, and
  runs a full-period phase scan. Degenerate (all-zero) cutouts are
  NO-DATA, not non-detections.
- `diffimg.py` — per-pixel transit regression (with per-cadence
  background subtraction + a background regressor), null-phase
  controls, centroid + split-half jackknife, two-source PSF fits,
  single-source PSF comparison, aperture test, and
  neighbour-exclusion arithmetic. Sector maps are stacked by WCS
  resampling onto the reference sector's frame (the old integer
  `np.roll` ignored roll-angle differences between sectors).
- `neighbour_fold.py` — folds a neighbour's own light curve at the
  target's ephemeris. A near-identical shape with a scaled depth is
  a photocopy of the neighbour's signal.

Search the full arcminute for a known variable with the same period
— one blend sat 31.3″ from its target and a 30″ search missed it.
Never use the contamination ratio alone to clear a blend: it
describes a small nominal aperture while the light-curve aperture
can swallow a brighter neighbour a few pixels away.

```bash
.venv/bin/python gauntlet/tesscut_fetch.py 423498314 \
    --ra 71.4672736 --dec -23.5535525 --sectors 32 98 107 108 \
    --neighbour-ra 71.4637459 --neighbour-dec -23.5496113 \
    --outdir work/423498314/tesscut --identity-out work/423498314/identity.json
.venv/bin/python gauntlet/tesscut_extract.py 423498314 \
    --period 0.827048 --t0 3988.91522 --duration 0.04 \
    --identity work/423498314/identity.json \
    --tesscut-dir work/423498314/tesscut --data-dir work/423498314/data \
    --sectors 107 108
.venv/bin/python gauntlet/diffimg.py 423498314 \
    --period 0.827048 --t0 3988.91522 --duration 0.04 \
    --identity work/423498314/identity.json \
    --tesscut-dir work/423498314/tesscut --sectors 32 98 \
    --outdir work/423498314 --exclude-xy 14,5.5 --depth-pct 1.03
.venv/bin/python gauntlet/neighbour_fold.py 423498314 423498311 \
    --period 0.827048 --t0 3988.91522 --duration 0.04 \
    --workdir work/423498314
```

For a period of 8 days or longer, inspect the raw pixel flux at the
fixed ephemeris before accepting the dip — aperture flux alone can
hide a scattered-light artifact (one 11.52 d claim showed pixels
brightening by 3–5% with no dip at all).

### 5. Formal transit fit — `transit_fit.py`, `transit_fit_report.py`

batman (quadratic limb darkening, circular orbit) + emcee. The `ls`
stage fits with free limb darkening (Kipping q1, q2); the `mcmc`
stage runs from the fixed-LD least-squares solution (free LD runs to
unphysical values for a grazing transit). Per-sector sigmas are
rescaled by the LS chi²_red. `transit_fit_report.py` derives Rp, a,
Teq and the circular-orbit stellar density per-sample from the chain
(Monte-Carlo stellar parameters), plus a model-dependent mass / RV
amplitude from Chen & Kipping (2017), and makes the fit plots.

Requires `batman` and `emcee` (in the project venv). The MCMC is
slow (~15 min on a laptop, longer on a weak VM — run it in the
background).

```bash
.venv/bin/python gauntlet/transit_fit.py 423498314 ls \
    --period 0.827048 --t0 3988.91522 --duration 0.04 \
    --data-dir work/423498314/data --qlp-sectors 32 98 \
    --tesscut-sectors 107 108 --depth-pct 1.03 \
    --r-star 0.673 --r-star-err 0.04 --m-star 0.81 --m-star-err 0.08 \
    --supersample 32:3 --outdir work/423498314
.venv/bin/python gauntlet/transit_fit.py 423498314 mcmc \
    ... (same arguments) --mcmc-start 0.827047,3988.91410,0.1912,3.003,1.012
.venv/bin/python gauntlet/transit_fit_report.py 423498314 \
    --chain work/423498314/mcmc_chain.npz --data-dir work/423498314/data \
    --qlp-sectors 32 98 --tesscut-sectors 107 108 \
    --period 0.827048 --t0 3988.91522 --duration 0.04 \
    --r-star 0.673 --r-star-err 0.04 --m-star 0.81 --m-star-err 0.08 \
    --teff 4917 --teff-err 122 --supersample 32:3 \
    --desk-rp 0.1015 --desk-a 5.1 --desk-b 0.3 \
    --stellar-errors-adopted --outdir work/423498314
```

## Worked example — TIC 423498314

The gauntlet was consolidated by generalising the per-star scripts
written for TIC 423498314 (0.827 d, ~1% transit on a 0.673 R☉ K
dwarf), and validated by reproducing its recorded numbers. Expected
results for the commands above:

| Check | Recorded value |
|---|---|
| Desk check | RAW-CONFIRMED, QLP 0.848% @ 17.0σ |
| Shape gate | V-shaped, T23/T14 = 0.247, density-flagged |
| Refined folds | 1.029% @ 41.5σ white (s32 0.986%, s98 1.041%), secondary −0.073% |
| Odd/even | 0.957% vs 1.085% (agree) |
| Holdout (bgreg) | HOLDOUT-PASS, +0.712% @ 18.8σ, 4/4 folds ≥ 3σ |
| Holdout (plain raw) | HOLDOUT-FAIL (2/4) — scattered-light red noise |
| Imaging | centroid 0.06 px from target; PSF target +1.3 (+23σ), neighbour ~0 |
| Formal fit | grazing: b = 1.06 ± 0.12, Rp/R★ = 0.226, T14 = 1.41 h |

The fit overturned the desk's "clean box" reading: the transit is
V-shaped and grazing, Rp is 9–28 R⊕ (not a hot Neptune), and the
leading alternative is a grazing EB on the unresolved companion
implied by the star's Gaia RUWE 3.80. That is the gauntlet working
as intended — the shape gate (step 1) now catches this at the desk
instead of after publication.

## Known limitations — stated plainly

- **The raw-flux gate passes rotation waves.** A wave is really
  there in the raw flux; only the fold-shape test (and the trapezoid
  gate) kills waves. A RAW-CONFIRMED verdict is not a planet.
- **The persistence stamp's raw test applies only to CONSISTENT
  verdicts.** Patchy / fails-persistence hits are not raw-graded.
- **"N/20 sectors persistent" can be era-partial two ways:** the
  sector cap samples a subset of eras (a stamp built on sectors
  2–35 never saw the late eras), and product coverage itself can
  start late (QLP starting at sector 31 is structurally blind to
  Cycle 1). Re-run the raw-flux test whenever a new sector arrives.
- **Imaging cannot separate sub-arcsecond companions.** A neighbour
  0.34 px away is one TESS pixel; a bound companion within ~1″
  (the Gaia RUWE case) needs high-resolution imaging or RV, not
  more photometry. Difference imaging localises to the pixel, not
  to the star.
- **The holdout proves predictive periodicity only.** A clean EB
  passes. It never replaces imaging.
- **The formal fit's mass is model-dependent.** The Chen & Kipping
  mass at Rp ~ 14 R⊕ sits at the Neptunian/Jovian transition; the
  quoted error covers only Rp + hyperparameter uncertainty, not the
  intrinsic scatter of the relation or the regime ambiguity.
- **Stellar errors are often adopted, not catalogued.** TIC
  publishes no radius/mass errors for many stars; the fit's
  density prior and derived Rp inherit the adopted errors — say so
  in any report.
- **Bulk-screen periods are not fold anchors.** See step 2: always
  phase-scan + refine before folding a bulk survivor across years.
- **Only SPOC / TESS-SPOC / QLP / ELEANOR-lite products are
  considered by the desk check.** An ELEANOR-only star needs
  hand-folding at the production ephemeris.

## Filing

File a new variable star (VSX) only after the persistence test and
the difference imaging test both pass, and keep the filing packet
(period, epoch, magnitudes, plot) together. Check the submission
queue first: only one submission can await review at a time. Leave a
saved draft untouched when told to — drafts cannot be deleted or
withdrawn and expire on their own after about sixty days.
