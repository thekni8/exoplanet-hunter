# Desk automation (Phase 2, 2A)

The vetting-manual desk checks (§0–§9), automated into the A-5
stage runner. The manual gauntlet ran by hand — census25.py,
rawflux_check.py + a phase scan, flagcheck.py, tesscut_fetch +
diffimg, transit_fit, and a human verdict. The desk driver
(`gauntlet/desk.py`) is the layer the runner was built for: it
produces the runner's natives by invoking the existing gauntlet
tools, in manual order, then runs the runner and builds the
verdict record.

## Running it

```bash
.venv/bin/python scripts/desk_gauntlet.py TIC --period P --t0 T0 \
    --duration DUR_H --depth DEPTH_PCT [--sde SDE] [--sector SEC] \
    [--workdir DIR] [--no-expensive] [--no-bulk] \
    [--waive STAGE:REASON ...]
```

Outputs in the workdir (default `vetting_results/desk-<TIC>`):

- `stage0_census.json` — the §0 census (TIC row, 180″ cone,
  Gaia RUWE, VSX, TOI, PHT).
- `data/` — downloaded per-sector npz light curves (all
  authors; the pipeline set is selected by the F-14 rule).
- `verdict_record.json` — the verdict record (schema 1.2).
- `desk_natives.json` — every native the driver built
  (arrays summarised as shape + sha256) plus extra evidence
  (P/2 alias fold, phase-0.5 secondary fold, transit-fit
  chi2, dropped waivers).
- `tesscut/`, `diffimg/`, `transit_fit/` — the expensive
  stages' working files (cheap-pass survivors only).

Nothing is filed anywhere: a CANDIDATE verdict means "ready
for human filing review" (2E), not a discovery.

## Two passes

Cheap stages first (catalogue, clean_refold, refine, raw_flux,
persistence, shape, odd_even, blend, pixel_check). A FAIL at
any cheap stage ends the run — the expensive natives (holdout,
diffimg, transit_fit) are never produced, exactly as the
manual gauntlet stopped at the first kill. Only a cheap-pass
survivor pays for the expensive stages.

## Stage → tool map

| Stage | Tool | Notes |
|---|---|---|
| catalogue | `gauntlet/census.py` | TIC row + 180″ cone (MAST), Gaia DR3 (RUWE, advisory), VSX 3′ cone (raw XML), targeted TOI TAP query with periods, PHT search. Fail-closed: a failed TOI/VSX/PHT sub-check produces NO native (UNMEASURED). VSX kills only within 30″ with P/2P/P/2 within 1%. |
| clean_refold | `bulk/clean_refold_gate` + flagcheck | The three-way fold: clean (quality==0) decides PASS/FAIL when it has enough cadences; when it does not, the flagged-only fold is tested — flagged cadences alone carrying a significant dip means FAIL. The decisive test for the flagged-cadence artifact class. |
| refine | `gauntlet/refine.py` | Narrow-grid BLS refit (promoted verbatim from holdout_test). The refined ephemeris is the fold anchor from here on. |
| raw_flux | `gauntlet/common.fold_depth` | On unflattened flux at the refined ephemeris, + the event count. |
| persistence | `desk.persistence_native` | Per-time-gap-segment folds (generalised from F-8). CONSISTENT only when every usable segment shows the dip at ≥1.5σ. |
| shape | `rawflux_check.trapezoid_shape_gate` | rho_star in SOLAR units from the census TIC row. |
| odd_even | `common.event_parity_depths` | Plus the P/2 alias fold and the phase-0.5 secondary fold as evidence (not stage criteria — see open questions). |
| holdout | `holdout_test.holdout_test` | The sector count decides the native without a run (1 sector → NOT_APPLICABLE, 2 → INSUFFICIENT-DATA). Re-runs the pipeline internally (known inefficiency — see below). |
| diffimg | `tesscut_fetch` + `diffimg` CLIs | The native is derived from the WCS-aligned stack centroid: on-target within 1 px (21″) and closer to the target than the neighbour. |
| blend | `gauntlet/blend.check_blend` | Brightest 180″ neighbour folded for real; the dip-free control only when the cone is empty. |
| pixel_check | `gauntlet/pixel_check.py` | New in 2A. The 3×3 aperture only; FAIL when a pixel brightens at ≥3σ in transit. P ≥ 8 d only (runner rule). |
| transit_fit | `transit_fit` CLI (ls stage) | QLP sectors only. b/Rp/T14/density-flag derived from ls_fit.json. |

## Waivers

Waivers are filtered, never blindly forwarded. Pass 1 runs
without waivers (the cheap-kill decision is about FAILs).
Pass 2 and the verdict get only waivers that apply — a stage
reading inconclusive or not_applicable. Dropped waivers are
recorded in `desk_natives.json` under
`extra_evidence.waivers_dropped`. A waiver for a stage that
reads unmeasured is operator error, not a run kill.

## Known gaps and open questions (for the Phase 2 vote)

1. **Holdout re-runs the pipeline.** `holdout_test` calls
   `hunter._run_pipeline` internally instead of reusing the
   driver's fetched arrays. An array-based holdout is a
   follow-up, not a 2A blocker.
2. **P/2 alias kill threshold.** The P/2 fold and the
   phase-0.5 secondary fold are recorded as evidence, not
   stage criteria — the manual gives no numeric bar for
   "two comparable minima". Needs a threshold decision.
3. **Diffimg on-target bar (1 px)** and the **pixel-check
   bars (3σ, 3×3 aperture)** are judgment calls — the manual
   gives no numbers. See PHASE_2_PROGRESS.md.
4. **Transit fit is QLP-only** (its loader reads
   `qlp_sNNN.npz`); TESSCut-sector fits need tesscut_extract
   wired in. The MCMC stage is not run — the LS fit decides.
5. **The F-8 TOI-700 c shape false-kill stands.** The shape
   gate still reads the shallow (0.32%) TOI-700 c transit as
   V-shaped (T23/T14 0.2925 vs the 0.30 bar). A shape-gate
   review (depth-dependent bar? fit-uncertainty-aware bar?)
   is a Phase 2 vote item, not a 2A change — the threshold
   is calibration, and changing it needs a version bump +
   injection re-run.

## External tools (LATTE / TRICERATOPS) — Phase 2, 2B/2C

`run_desk_gauntlet(..., external_tools={tool: ToolConfig})`
runs the configured tools as **post-runner evidence stages**
after pass 2, only on a survivor no stage failed (a dead
candidate is not worth 5–15 min of Mac time per tool).
Enable from the CLI with `--external-tools` (loads
`calibration/external_tools_v1.yaml`).

The tools are **evidence only**: their StageResults land in
`desk_natives.json` under
`extra_evidence.external_tools` (raw outputs under
`external_tools_raw`) and never feed `aggregate_verdict` —
LATTE can never PASS (it emits a PDF report, no
machine-readable dispositions), and TRICERATOPS's policy
bars are PROVISIONAL until the Phase 2 vote ratifies them.
A missing venv, a crash, or a timeout reads UNMEASURED +
EXEC_ERROR; a missing census field skips the tool with the
error recorded. Neither failure touches the verdict.

The driver builds each tool's C-10 input from its own data
(`external_tool_sections`): the stitched light curve is
written to `tool_lc.npz`, the census to
`stage0_census.json` when it is not already there, both
hashed. LATTE runs in FFI mode unless the light curve is
SPOC 2-minute data. Mac setup (venvs, first-run downloads,
verification targets): `docs/external-tools-mac-setup.md`.

## Evidence package + filing review (Phase 2, 2D/2E)

Every desk run writes `evidence_package.json` last (it
hashes `verdict_record.json` + `desk_natives.json`): the
verdict, the waiver-stamped stages, the external-tool
evidence (which the verdict record has no slot for), a
scores summary (FPP/NFPP + the LATTE report path),
provenance (schema 1.2 fields, calibration map + hash, code
fingerprint), and a completeness checklist (per-status
counts, missing required stages, the check_report_ready
filing precondition). Builder: `gauntlet/evidence.py`,
schema `schema/evidence-schema.json`.

The filing review (`gauntlet/review.py`,
`schema/review-schema.json`) is the human gate on top of
the package: `prepare_filing_review` builds a review record
(status `awaiting_review`, eligibility + blockers + a human
checklist) for any package, and `record_review_decision`
records approve/reject with reviewer + reason + timestamp.
The gate is enforced at decision time — an ineligible
record can be prepared and rejected, never approved. A
candidate is eligible when the verdict is CANDIDATE, every
required stage is pass-or-waived, and persistence + diffimg
+ blend pass. An approved review IS the F-5 second-eyes
marker: its reviewer satisfies check_report_ready's
review_2e requirement for a waived candidate
(`review_2e_marker`). No filing action is ever taken — the
gate prepares the review, a human decides.

## Tests

- `tests/test_desk.py` (18, offline): 12 end-to-end driver
  scenarios on synthetic light curves through a fake data
  source, extending the F-7 pattern, + 6 native-builder unit
  tests.
- `tests/test_desk_external_tools.py` (11, offline): the
  external-tools wiring — clean planet + tool result(s),
  cheap-kill and pass-2-FAIL gating, missing venv, missing
  census field, input-section units, policy loader, + the
  2D evidence-package assertions.
- `tests/test_evidence.py` (7, offline): the 2D builder —
  complete candidate, tool scores, missing source files,
  missing required stage, waived candidate, failed stage,
  schema validation.
- `tests/test_review.py` (14, offline): the 2E gate —
  eligible/ineligible preparation, checklist derivation,
  approve/reject rules, double-decision refusal, and the
  proof that an approved review unblocks check_report_ready
  for a waived candidate.
- `tests/test_desk_live.py` (1, download-backed): the clean
  gate on real S96 QLP light curves — the artifacts
  TIC 355401152 and 382571558 must FAIL, the known planet
  TIC 183537452 must PASS. Live CI only (DOWNLOAD_TESTS).
- `tests/test_refine.py` (4), `tests/test_pixel_check.py`
  (5), `tests/test_census.py` §2A (10): the new tools.
