# Teardown: Pavel Rabtsevich's TESS bulk screen (the TIC 4206066 search)

**Purpose.** A primary-source teardown of the bulk-screening method behind the two
transit-like signals reported in TIC 4206066, written as the design reference for our
own sister bulk-screen pipeline. Every factual claim names its source inline.
Anything not found in the primary sources is marked **UNVERIFIED** — in particular,
numbers that circulate only in Instagram/news summaries are *not* imported.

**Headline finding.** The real screen is much narrower and much more conventional
than the media narrative: it is a **single-sector** (Sector 98 only), **single-product**
(QLP FFI light curves) BLS search over a magnitude-limited star list, detrended with
`wotan`, scored with LEO-Vetter's pink-noise MES, and vetted with LEO-Vetter's
flux-level tests plus a mechanical MES-ladder shortlist rule. The bulk-search code
itself (`pipeline/run_search.py`, config `prejev_search.json` v1.1) was **explicitly
NOT deposited** — only an audit extract, a star-list recount script, and a single-star
LEO re-run are public. So the search *chain and thresholds* are verifiable from the
deposited audit trail, but the production *period/duration grids and bulk fetch
mechanism* are not.

---

## Sources

All primary sources were fetched and read directly on 2026-11-11.

| # | Source | Identifier / URL |
|---|--------|------------------|
| S1 | Research Note manuscript (preprint, "Draft version September 25, 2026") | doi [10.5281/zenodo.22967456](https://doi.org/10.5281/zenodo.22967456) — PDF: https://zenodo.org/api/records/22967456/files/manuscript.pdf/content |
| S2 | Supporting data & code record (README.md + 3 ZIPs: `part1_A_transits_archival_fpp.zip`, `part2_companion_pixels_B.zip`, `part3_figure_star_facts_pipelines.zip`) | doi [10.5281/zenodo.22967099](https://doi.org/10.5281/zenodo.22967099) — API: https://zenodo.org/api/records/22967099 |
| S3 | Pre-registered Sector 110 protocol record (README.md, `PREREG_S110_SHORT.pdf`, `PREREG_S110_FINAL.pdf` v1.1, frozen-code ZIP `tic4206066_S110_prereg_final.zip`, 13,824,518 bytes, 116 files) | doi [10.5281/zenodo.23175179](https://doi.org/10.5281/zenodo.23175179) — API: https://zenodo.org/api/records/23175179 |
| S4 | Gizmodo, "Did Claude Help an Amateur Astronomer Discover a New Planet?" (2026-10-09) — used **only** to look for a GitHub link to the search code | https://gizmodo.com/did-claude-help-an-amateur-astronomer-discover-a-new-planet-2000824393 |

Key files inside S2 cited below:

- `README.md` of S2 (the reproducibility-package readme; states what is/isn't deposited).
- `13_supporting_pipelines/U_10_novelty_protocol/search_protocol_extract.json` — deposited
  extract of the frozen search config (subset rule, detrend, search, detection statistic,
  vetting, shortlist rule, MES ladder, the two target-signal rows).
- `13_supporting_pipelines/U_10_novelty_protocol/REPORT.md` — Audit 10 report (independent
  recount of the search funnel, novelty check, environment).
- `13_supporting_pipelines/U_10_novelty_protocol/tic_recount.py` + `tic_recount.json` —
  independent recount of the 126,246 figure.
- `13_supporting_pipelines/U_10_novelty_protocol/leo_rerun.py` + `leo_rerun.json` —
  independent single-star re-derivation (own BLS + LEO-Vetter 1.2.0) for TIC 4206066.
- `13_supporting_pipelines/U_10_novelty_protocol/fresh_queries.py` +
  `novelty_summary.json` — the novelty (prior-report) cross-match code and results.
- `12_facts/FINAL_FACTS.csv` — reconciled fact table; rows `DATA.search.*`,
  `DATA.products.*`, `DATA.S98_*` cite the (undeposited) config `prejev_search.json`
  key-by-key.
- `01_inputs/INPUT_PRODUCTS.csv` and `01_inputs/from_U_00_data/README.md` — product
  inventory for the *follow-up* of TIC 4206066 (not the screen).
- `10_environment/VERSIONS.txt` — machine/OS/Python environments.

**Gizmodo / GitHub check (S4).** The Gizmodo article contains **no link to any GitHub
repo or gist** with the search code. Its outbound links are to tess.mit.edu (the
"narrow sliver" of TESS data), the Zenodo pre-registration (S3), X, NASA, and Reddit.
Consistent with S2's README, the bulk-search code is simply not public; only the
audit extract and re-run scripts in S2 describe it.

---

## 1 Star list

- **What was screened:** "I searched Sector 98 Quick-Look Pipeline (QLP) light curves
  … of 126,246 stars (T ≤ 11.5) with box least squares" (S1, §1). The pre-registration
  states the same set: "all 126,246 stars with TESS magnitude T ≤ 11.5" (S3,
  PREREG_S110_FINAL §2).
- **Exact origin of 126,246 — VERIFIED.** It is a *recountable intersection*, not a
  round claim:
  - Start from the **QLP Sector 98 target list**, `https://archive.stsci.edu/hlsps/qlp/target_lists/s0098.csv`
    — **628,730 unique TIC IDs** (`tic_recount.py` docstring + `tic_recount.json`:
    `n_unique_tic_in_list = 628730`, sha256 `b6c63e9a…`).
  - Look up **TIC 8.2 Tmag** for every ID via MAST Catalogs
    (`astroquery.mast.Catalogs.query_criteria`, `catalog="Tic"`, batches of 5,000;
    `tic_recount.py`).
  - Count **Tmag ≤ 11.5 → 126,246** (`tic_recount.json`: `n_tmag_le_11p5 = 126246`,
    `n_missing_in_tic = 0`, `n_tmag_nan = 0`; finished 2026-09-25T11:47Z).
  - The frozen config says the same: `subset_rule = {rule: "tmag_limited",
    tmag_max: 11.5, expected_count: 126246}` (`search_protocol_extract.json`;
    FINAL_FACTS row `DATA.search.n_stars` cites `config/prejev_search.json` subset).
- **Selection cuts:** the *only* documented cut is **T ≤ 11.5** (TIC 8.2 Tmag).
  No radius, Teff, or other stellar cut is documented anywhere in S1–S3. The screen
  covers **one sector only (Sector 98)** — there is no multi-sector star list.
- **Usable subset:** of the 126,246 input stars, **126,070 light curves were actually
  searchable**; 175 were `DATA_CORRUPT` (< 6,000 good cadences) and 1 was a
  `PROCESSING_ERROR` (S2, U_10 REPORT.md finding F6, citing
  `data/vetting/vetting_summary.json` counts; FINAL_FACTS `DATA.search.n_stars`).
- The target itself: TIC 4206066, Tmag 9.6817 (`tic_recount.json`), i.e. comfortably
  inside the cut.

**Design takeaway:** the "126k stars" headline = *one sector's QLP target list,
magnitude-limited*. Reproducing it needs only the sector target-list CSV + a TIC
Tmag lookup — no bespoke catalogue work.

---

## 2 Data products & bulk fetch

### 2.1 What the screen actually searched

- **Product: QLP FFI light curves, Sector 98 only**, 200 s cadence
  (S1 §1; S3 PREREG §2; FINAL_FACTS `DATA.products.S98`: QLP HLSP v01 LLC,
  `TIMEDEL = 200.0 s`, CALIB "TICA v1.4.0", TICVER 8.2, camera 1 CCD 2).
  Sector 98 is a double-length sector: 57.40 d span, 24,162 cadences
  (FINAL_FACTS `DATA.S98_span`).
- **Flux column: `SYS_RM_FLUX`** (systematics-removed), errors `DET_FLUX_ERR`;
  `DET_FLUX` was used only as a sensitivity variant (FINAL_FACTS
  `DATA.products.flux_columns`, citing `config/prejev_search.json`
  flux.base_column/error_column/rationale; `DATA.search.method`).
  Note S98 QLP photometry is TGLC-based (Han & Brandt 2023 method, adopted by QLP
  from Sector 94; S1 §1, FINAL_FACTS `DATA.products.S98`).
- **Quality mask (frozen):** mask value **1610619071** = bits 0,1,2,3,4,5,7,11,12,29,30.
  For TIC 4206066 this removes all 12,095 flagged cadences of 24,162, leaving 12,067
  good cadences with finite `SYS_RM_FLUX` (FINAL_FACTS `DATA.products.S98_quality`,
  citing `config/prejev_search.json` quality). The manuscript phrases this as
  "removing all flagged Sector 98 cadences" (S1 §1). The same constant
  `FROZEN_QLP_MASK = 1610619071` appears in the frozen S110 helper `deps/lcio.py`
  (S3 ZIP), labelled "QLP quality mask used for Sector 98 in the archival analysis".

### 2.2 How the light curves were fetched in bulk

- **UNVERIFIED for the production screen.** S2 README, "What is NOT deposited":
  *"the frozen Sector 98 search pipeline over 126,246 stars and its LEO-Vetter runs:
  only the recount (`tic_recount.py`) and the LEO-Vetter re-run for this star
  (`leo_rerun.py`) are included"*. The production entry point is named in
  FINAL_FACTS `DATA.search.method` as `pipeline/run_search.py` (config v1.1), but
  the script itself is not in any deposited record. No bulk-tarball / S3 / batch
  download mechanism for the 126k light curves is documented in S1–S3.
- **What the deposited audit code does** (the only fetch patterns actually visible):
  - Target list: plain HTTPS GET of the QLP target-list CSV (above) via `requests`
    (`tic_recount.py`).
  - TIC magnitudes: `astroquery.mast.Catalogs.query_criteria` in batches of 5,000,
    checkpointed per batch (`tic_recount.py`).
  - A single light curve: direct `requests.get` of the archive URL pattern
    `https://archive.stsci.edu/hlsps/qlp/s0098/0000/0000/0420/6066/hlsp_qlp_tess_ffi_s0098-0000000004206066_tess_v01_llc.fits`
    (`leo_rerun.py`). This is the standard per-star HLSP path layout, but whether the
    production run looped over it star-by-star is **not stated** — do not assume it.
- **Follow-up products for TIC 4206066 only** (not the screen; S1 §1,
  `01_inputs/INPUT_PRODUCTS.csv`, `01_inputs/from_U_00_data/README.md` §2):
  Sector 6 TESS-SPOC FFI 30-min (1800 s) PDCSAP; Sector 32 SPOC 2-min (120 s) PDCSAP;
  Sector 98 QLP 200 s. Retrieved per-file from MAST (Download API URLs, some
  redirecting to `stpubdata.s3.us-east-1.amazonaws.com`) with `astroquery`
  retrieval scripts; TESScut cutouts via `astroquery.mast.Tesscut.download_cutouts`.
  These are one-star downloads, not bulk infrastructure.

---

## 3 Search

The deposited config extract (`search_protocol_extract.json`) plus FINAL_FACTS
`DATA.search.method` give the chain verbatim:

1. **Input flux:** QLP S98 `SYS_RM_FLUX` (+ `DET_FLUX_ERR`), frozen quality mask
   (§2.1).
2. **Detrending:** *"wotan time-windowed biweight (Hippke et al. 2019)"*
   (`search_protocol_extract.json` `detrend` field). Parameters from FINAL_FACTS
   `DATA.search.method` (citing `config/prejev_search.json` detrend keys):
   **window 1.0 d, break tolerance 0.1 d, edge cutoff 0.25 d**, wotan 1.10.
   (The manuscript compresses this to "box least squares … after biweight
   detrending"; the wotan citation was cut for word budget — FINAL_FACTS note.)
3. **Search algorithm:** **astropy `BoxLeastSquares`** (Kovács et al. 2002),
   **`objective="likelihood"`, `method="fast"`** (`search_protocol_extract.json`
   `search` field; FINAL_FACTS `DATA.search.method`: "astropy BoxLeastSquares
   (objective=likelihood)"). It is BLS, **not TLS**, at screen stage. (TLS appears
   only in later single-star cross-checks of signal B's period — FINAL_FACTS
   `B.P_S98only` mentions "BLS/TLS grid peaks" in the follow-up context.)
4. **Detection statistic / re-scoring:** after BLS, signals are re-scored with
   **MES = signal-to-pink-noise ratio**, "identical definition to leo_vetter
   `get_SES_MES` (Hartman & Bakos 2016 red noise, Pont et al. 2006)"
   (`search_protocol_extract.json` `detection_statistic`; FINAL_FACTS
   `DATA.search.method`: "pink-noise MES re-scoring"). This is **LEO-Vetter MES,
   not SPOC TPS MES** (U_10 REPORT.md finding F5).
5. **Detection floor:** a signal had to reach **MES ≥ 9** to be returned at all
   (S3, PREREG_S110_FINAL §2: "A signal had to reach a multiple-event statistic
   (MES …) of at least 9. The search returned 23,949 signals on 16,300 stars.").
6. **Iterative multi-signal handling (partial evidence):** the audit re-run was
   written to mirror the pipeline's order — *"the pipeline searched each signal
   after masking the other signal's transits … B was signal 1 (searched on the
   unmasked light curve), A was signal 2 (searched after masking B)"*
   (`leo_rerun.py` comments). This indicates the production search iterated:
   find a signal, mask its transits, search again — at least for this star.
   How many iterations were run per star in general is **UNVERIFIED**.

### Period / duration grids — mostly NOT deposited

- **Production period grid (min/max/sampling) and duration grid: UNVERIFIED.**
  They live in the undeposited `prejev_search.json` `search` section /
  `run_search.py`; the deposited extract quotes the algorithm and objective but
  no grid numbers, and FINAL_FACTS records no grid row for the production search.
- The only production-grid trace: signal A's discovery period 3.182945 d is
  described as an "S98-only coarse-grid BLS peak" with **"grid step ~2e-4 d"**
  (FINAL_FACTS `A.P_discovery`, citing `candidates/tic4206066_p3.182945/candidate.json`).
- **Do not confuse with the audit re-run's grid** (independent code, one star):
  `leo_rerun.py` uses 60,000 log-spaced periods from **0.5 to 25.0 d**, durations
  **[0.75, 1.0, 1.5, 1.75, 2.0, 2.5, 3.0] h**, `objective="snr"`, then a fine
  refinement (±0.2 % in period, 4,001 points; durations 0.5–4.0 h in 0.25 h steps),
  two iterations with transit masking. This reproduces both signals (11.1334 d,
  then 3.18273 d) but is explicitly the auditor's own code, **not** the frozen
  production grid.
- The two target signals as recorded by the production pipeline
  (`search_protocol_extract.json` `target_signals`):
  - `tic4206066_p3.182945`: P = 3.182945 d, duration 1.8 h, depth 448 ppm,
    MES 10.597, white SNR 11.38, N_transit 8.
  - `tic4206066_p11.132976`: P = 11.132977 d, duration 1.6 h, depth 937 ppm,
    MES 10.982, white SNR 12.51, N_transit 3.

### Per-star runtime

- **No per-star runtime is stated** in the manuscript, the config extract, the
  audit report, or any deposited log. See §5 for the only timing evidence that
  exists (config-freeze / run-start timestamps); it does not support a clean
  per-star cost because the star processing order is not documented.

---

## 4 Screening thresholds & cheap vetoes

### 4.1 The funnel (all numbers from S3 PREREG §2 and S2 U_10 REPORT.md)

| Stage | Count | Source |
|---|---|---|
| Input stars (QLP S98, T ≤ 11.5) | 126,246 | S1 §1; `tic_recount.json` |
| Searchable light curves | 126,070 (175 corrupt, 1 error) | U_10 REPORT F6 |
| Signals returned (MES ≥ 9) | **23,949 signals on 16,300 stars** | S3 PREREG §2 |
| After hard rejects | **4,749 signals** | U_10 REPORT (Task B) |
| Tier A — pass all 13 LEO false-alarm tests | **141 signals on 140 stars** | S3 PREREG §2; U_10 REPORT |
| PRIMARY shortlist (MES ≥ 15) | 70 | S3 PREREG §2; extract ladder counts |
| EXPLORATORY (Tier A, MES < 15) | 71 | S3 PREREG §2 |

TIC 4206066 is "the only star with two signals among the 141" (S3 PREREG §2), and
**both of its signals are in the EXPLORATORY tier** — i.e. the discovery came from
the below-threshold residue the author examined post hoc, not from the primary
shortlist (S1 §1: MES 10.6 and 11.0 "fell below the shortlist threshold (15), so I
examined them post hoc").

### 4.2 Vetting at screen stage: LEO-Vetter flux-level tests

- **Tool:** `leo-vetter 1.2.0` (Kunimoto et al. 2025), **default thresholds**
  (`search_protocol_extract.json` `vetting` field).
- **13 false-alarm (signal-quality) tests** — these define Tier A:
  `weak, invalid_transits, bad_shape, non_unique, chases, dmm, single_event,
  bad_fit, sinusoidal, unphysical_duration, asymmetric, chi, data_gapped`
  (enumerated in `leo_rerun.py`, `FA = [...]`, from `leo_vetter.thresholds`).
- **4 flux-level false-positive tests** — also run and recorded, though Tier A
  membership required only the 13 FA tests (U_10 REPORT finding F4):
  **`odd_even, vshaped, large, secondary`** (`leo_rerun.py`, `FP = [...]`).
  So odd/even depth, V-shape, oversize-planet, and secondary-eclipse checks
  **do exist at screen stage**, inside LEO-Vetter — both TIC 4206066 signals
  passed all 17 tests at the pipeline ephemerides (FINAL_FACTS
  `DATA.search.LEO_flux_tests`).
- **Caveat (ephemeris sensitivity):** at the auditor's own BLS ephemeris, signal B
  **fails** the `chases` FA test (mean_chases 0.74–0.76 < 0.78); its Tier-A
  membership is fragile (U_10 REPORT F4; `leo_rerun.json` key `B_own_bls_iter1`).
- **Pixel-level test NOT run at screen stage:** LEO-Vetter's pixel `offset` test
  was not part of the screen — "The pixel-level test was not run, so neither
  signal is a LEO 'PC'" (U_10 REPORT F4; FINAL_FACTS `DATA.search.LEO_flux_tests`
  note). **No centroid / difference-image check exists in the screen.**
- **Context flags (non-rejecting):** the pipeline attached informational flags
  without rejecting: `COMMON_MODE_HOT_FRACTION_0.12` on signal A, and
  `GAIA_NEIGHBOR_BRIGHT_ENOUGH_FOR_DEPTH` on both signals (U_10 REPORT, Task B).
  So a Gaia-neighbour brightness sanity flag existed, but it did not veto — the
  flagged star is the discovery. (The audit notes the flag used a G-band estimate;
  in the TESS band that neighbour's maximum eclipse depth is ~417 ppm < the
  ~500 ppm signal — U_10 REPORT F10.)

### 4.3 Shortlist rule (the "threshold" is a ladder, not a constant)

From `search_protocol_extract.json` `shortlist_rule` (verbatim substance):

> "hard rejects always apply. Only if survivors > target_max: tier_A = keep signals
> passing all 13 LEO false-alarm (signal-quality) tests; then, if still >
> target_max, the lowest MES threshold from mes_ladder giving <= target_max.
> Never lowered when < target_min. No scientific-value or visual ranking."

- `mes_ladder = [10, 12, 15, 20, 25, 30, 40, 50, 75, 100]`, `target_max = 80`.
- Ladder counts on Tier A: MES ≥ 10 → 125; ≥ 12 → 95; **≥ 15 → 70** (first rung
  ≤ 80), so **T\* = 15** was *derived from the final data by the pre-specified
  rule*, not itself pre-registered (U_10 REPORT finding F1; FINAL_FACTS
  `DATA.search.shortlist`). The freeze was a local sha256 record, not a public
  registration.
- The EXPLORATORY tier (Tier A with MES < 15) was formalised in protocol
  amendment 01, frozen 2026-09-25T00:19:47Z — per S3 PREREG §2, "about two hours
  after signal B of this star had been found", i.e. after results for this star
  had been seen. Both signals' cohort reason: `SHORTLIST_MES_BELOW_15`.

### 4.4 The "38 catalogs / 340,505 TESS alerts" claim — NOT in the primary sources

- This claim appears **only in secondary social-media summaries** (e.g. Instagram
  reels summarising the story: "searching 38 catalogs and 340,505 TESS alerts" /
  "searched against 340,505 automated TESS alerts"). **No such numbers, and no
  such screen-stage cross-match, exist in S1, S2 or S3. Marked UNVERIFIED.**
- What actually exists is a **post-discovery, single-star novelty check** ("has
  anyone reported this before?"), run on 2026-09-25 for TIC 4206066 only — it is
  **not** a veto applied to the 126k-star screen. Implementation is deposited:
  `fresh_queries.py` (sections `exofop, tce, nea, simbad, vizier, arxiv,
  t16raven`) plus ADS via the web UI and an ExoFOP target-page query (U_10
  REPORT Task A; S1 §5 lists the sources as: ExoFOP, TCE tables, NASA Exoplanet
  Archive, candidate catalogs, SIMBAD, VizieR, ADS, arXiv).
- Documented sizes actually queried (`novelty_summary.json`): ExoFOP TOI 8,148
  rows + CTOI 5,137 rows; SPOC TCE bulk tables (S6, S32, S98 single-sector +
  s0001–s0036/s0039/s0069/s0096 multi-sector) totalling 57,865 rows; T16
  candidate tables 11,143 + 411 rows; RAVEN tables 17,335 rows across 4 tables;
  VizieR: 166 tables within 15″ of the target (cone query, not an alert list).
  **Sum of documented alert/candidate rows ≈ 100,039** — roughly a third of the
  circulating 340,505 figure, with no documented path to that number. Result in
  every source: no prior report of either signal (nearest TOI 43′ away; nearest
  CTOI 120′; 0 TCE rows for the target or any of the 49 TIC stars within 2′).

---

## 5 Compute & wall-clock

- **Machine (for the deposited follow-up/audit work):** the author's Mac —
  paths in the scripts are `/Users/paulsmith/space <3/tess-jev/…` (S2 README,
  "Running the scripts"); OS **macOS 26.3.1 (arm64)**, i.e. Apple Silicon
  (`10_environment/VERSIONS.txt`). The S110 frozen code likewise "refuses to
  start in another environment" than Python 3.12.13 on an Apple Silicon Mac
  (S3 README). No cloud compute is mentioned anywhere in S1–S3.
- **Software environments** (`10_environment/VERSIONS.txt`; S2 README):
  main env Python 3.12.13 (numpy 2.5.3, scipy 1.18.1, astropy 8.0.1, wotan 1.10,
  leo_vetter 1.2.0 in the main freeze); TRICERATOPS env Python 3.11.15
  (triceratops 1.1.0, lightkurve 2.5.1); audit env Python 3.12.13.
  AI assistance disclosed in S1: "Claude Code (Anthropic) assisted with code,
  computations, figures, references, and drafting under my direction; ChatGPT
  (OpenAI; GPT-5.6 Sol, GPT-6 Pro) was used for review." S3 adds Codex for
  editing/verification.
- **Wall-clock for the bulk screen: NOT STATED in any primary source.** No total
  hours, no per-star timing, no core count for the search run is given in S1–S3.
  The only timing traces in the audit trail (FINAL_FACTS `DATA.search.shortlist`
  notes): config v1.1 frozen 2026-09-24T20:28:11Z; production run 2 started
  20:28:20Z; TIC 4206066 was searched at 22:09Z (~1 h 41 min into run 2); and
  run 1 under config v1.0 (frozen 20:00:27Z) was aborted after 3,397 stars.
  Because the processing order is undocumented, these do **not** yield a
  defensible per-star cost — treat any per-star figure as **UNVERIFIED**.
- The only duration quote anywhere is media, not primary: Rabtsevich told
  Gizmodo (S4) "a search I planned went through 126,000 stars, and then dozens
  of tests ran on a single one, **in about two weeks**" (that fortnight covers
  the search *plus* the single-star follow-up campaign, per the article's own
  framing; Gizmodo also reports "seventy-four tests" on the one star — neither
  number appears in S1–S3).
- For scale only (different job, not the screen): re-running the *Sector 110
  protocol's* archival rebuild takes "25 to 40 min" on the author's Mac, and its
  false-alarm trials are "hours of CPU" (S3 README). Do not read these as
  screen costs.

---

## 6 What the screen does NOT do

Relative to a deep vetting gauntlet, the screen (as frozen in config v1.1 and
described in the extract/audit) has **none** of the following:

- **No pixel-level / centroid / difference-imaging check.** LEO-Vetter's pixel
  `offset` test was not run (§4.2); difference imaging appears only in the
  later single-star follow-up (§7).
- **No multi-sector persistence requirement.** The screen is Sector 98 alone.
  Persistence in Sectors 6/32 was checked afterwards, for this one star, by an
  epoch search at the S98-only period (§7).
- **No raw-flux fold gate.** Signals are scored on wotan-detrended
  `SYS_RM_FLUX`; there is no requirement that a candidate fold to a significant
  dip in unflattened flux before promotion. (The S110 protocol's box-depth
  statistic with fake-ephemeris noise pools is a *follow-up test design*, S3 §4,
  not a screen gate.)
- **No holdout / leave-one-sector-out test at screen stage.** The holdout-style
  checks were applied manually, afterwards, to the single candidate:
  (i) the archival recovery test — take the Sector-98-only period, search for
  the signal at that fixed ephemeris in Sectors 6 and 32 with identical null
  machinery (20,000 fake-period trials), giving FAP ≲ 1 % per sector,
  ≲ 0.1 % jointly for signal A (S1 §2; S2 folder `03_archival_test_A/`);
  (ii) for signal B the same idea was explicitly **post hoc** — the test was
  "defined after inspecting the archival data", an unanchored search had
  failed, and the result is ≈ 3σ / FAP ≈ 2×10⁻³ (S1 §3);
  (iii) the genuinely prospective holdout is the Sector 110 pre-registration
  itself (S3): fixed ephemerides/depths/decision rules deposited before the
  data existed. Gizmodo's (S4) "gave the agent two of the TESS datasets and
  asked it to predict when the dimming would occur in the third; correct in
  all three cases" is the media telling of (i)/(ii) — the primary sources
  frame it as the fixed-ephemeris archival FAP test above, not as a formal
  leave-one-out cross-validation, and no "74 tests" list is deposited.
- **No catalogue cross-match veto.** Known-candidate/alert catalogues were
  consulted only in the post-discovery novelty check for this star (§4.4);
  the screen itself did not filter against TOI/CTOI/TCE lists.
- **No statistical validation / FPP at screen stage.** TRICERATOPS etc. are
  follow-up only (§7). The screen also computed **no search-wide false-alarm
  rate or completeness** — stated plainly in S3 PREREG §2: "No false-alarm
  rate or completeness was computed for the search as a whole."
- **No visual/scientific ranking in the shortlist.** The rule is purely
  mechanical (hard rejects → Tier A → MES ladder); "No scientific-value or
  visual ranking" (`search_protocol_extract.json`).

In short: **screen = detrend → BLS → pink-noise MES ≥ 9 → LEO flux tests →
MES ladder.** Everything else in the paper is one-star follow-up.

---

## 7 Candidate vetting (separate from the screen)

Brief summary of the deep vetting applied to TIC 4206066 *after* the screen
(S1 §§2–4; S2 folders `02_transits_A/`–`07_signal_B/`). Star: late-K dwarf,
Gaia DR3 3220388198192519424, T = 9.68, 35.6 pc; Mann et al. relations give
R⋆ = 0.623 ± 0.019 R⊙, M⋆ = 0.606 ± 0.015 M⊙, ρ⋆ = 2.51 ρ⊙ (S1 §1).

- **Ephemeris & shape (signal A):** transit times from a fixed-shape `batman`
  template with injection-calibrated errors; 19 transits meeting ≥ 70 %
  coverage, S/N ≥ 2, ≥ 15 min post-egress → P = 3.182785 ± 0.000006 d. An
  exposure-integrated `emcee` fit of all 23 transits (circular, Claret limb
  darkening, Mann density prior): b = 0.35, T14 = 1.87 ± 0.05 h,
  Rp/R⋆ = 0.0204 ± 0.0010 → Rp = 1.4 ± 0.1 R⊕ at ~500 ppm (S1 §2).
- **EB-style flux checks (follow-up level):** per-sector and odd/even depths
  agree; phase-0.5 depth −20 ± 32 ppm (no secondary); V-shape disfavoured
  (Δχ² = 32; ≥ 21 with red noise) (S1 §2).
- **Localisation:** SPOC Sector 32 (pointing-decorrelated) and TESScut Sector 98
  difference images fitted with the TESS PRF (`TESS_PRF`) place signal A at
  (+5 ± 3, 0 ± 3)″ from the target (~2σ; ≤ 2.6σ across S98 reductions). Sector 6
  difference images unusable (transits 0.4–3.5 h from momentum dumps). All Gaia
  DR3 stars capable of producing the depth lie ≳ 43″ away (> 10σ) (S1 §4).
  Signal B offset (+1 ± 3, −1 ± 3)″ (S1 §3).
- **Gaia checks:** RUWE = 1.21 (below the 1.4 binarity threshold); RV scatter
  elevated (p = 4×10⁻⁵, gof 3.0 vs threshold 4) but RVs exclude an eclipsing
  stellar companion of the target (K < 1.2 km s⁻¹); no non-single-star solution
  or other source within 10″. XP overluminosity +0.003 mag (vs 0.05–0.07 mag
  scatter) disfavours Gaia-blended (≲ 0.2″) companions above ≈ 0.38 M⊙ (2σ);
  BP/RP flux excess normal, arguing against 0.2–2″ companions; a circular-orbit
  companion host would need ≳ 0.52 M⊙, so 0.15–0.38 M⊙ hosts would require
  e ≳ 0.2–0.6 (S1 §4; S2 folder `05_companion_limit_038/`).
- **TRICERATOPS 1.1.0:** Sectors
  32+98 folds (5–10 min bins), unresolved companions at 0.1–2.2″:
  **FPP = 0.03–0.04** (4–20 runs of 10⁶ draws), ~90 % of it from bound companions
  above 0.38 M⊙; NFPP < 10⁻⁶. Excluding those companions post hoc gives
  FPP ≈ 0.002–0.007. The default FPP **exceeds** the validation threshold
  (FPP < 0.015), so **no statistical validation is claimed** (S1 §4).
- **Signal B status:** two clean S98 transits; archival dips only at the
  S98-predicted times in a post hoc test (≈ 3σ, FAP ≈ 2×10⁻³); tentative
  ephemeris P = 11.13274 ± 0.00003 d, ~1000 ppm in S98, Rp ≈ 2.2 R⊕ if on the
  target (S1 §3). Its Sector 32 events abut signal-A transits.
- **Remaining false-positive channel** (author's own conclusion): a planet
  transiting an unresolved bound companion; needs high-resolution imaging and
  RVs. The prospective test is Sector 110 (2026-10-31 → 2026-11-26, SPOC 2-min,
  DDT 100), pre-registered in S3 with frozen outcomes
  recovered / inconsistent / excluded / insufficient-data, a timing rule, and
  a PRF pixel-localisation label for signal A.

---

## Unverified / gaps

1. **Production BLS period grid (range + sampling) and duration grid —
   UNVERIFIED.** Only the algorithm/objective (astropy BLS, likelihood, fast)
   and a ~2×10⁻⁴ d discovery-grid step for one signal are documented. The
   0.5–25 d / 60,000-period grid in `leo_rerun.py` is the auditor's re-run,
   not the production search.
2. **Bulk fetch mechanism for 126,246 light curves — UNVERIFIED.** The search
   pipeline (`pipeline/run_search.py`, config `prejev_search.json` v1.1,
   sha256 80e7ae48…) was explicitly not deposited (S2 README). Only the audit
   fetch patterns (target-list CSV via HTTPS; TIC via astroquery batches;
   single LCs via direct archive URLs) are visible.
3. **"38 catalogs / 340,505 TESS alerts" — UNVERIFIED.** Absent from all
   primary sources; the documented novelty check covers ~9 named source groups
   and ≈ 100,039 alert/candidate rows (§4.4), for one star, after discovery.
4. **Screen wall-clock and per-star cost — UNVERIFIED / NOT STATED.** No total
   runtime in S1–S3; only config-freeze (2026-09-24T20:28:11Z), run-2 start
   (20:28:20Z), an aborted v1.0 run (3,397 stars), and the target's search
   timestamp (22:09Z). Gizmodo's "about two weeks" covers search + follow-up
   and is a media quote, not a methods statement.
5. **Number of BLS iterations per star in production — partially verified.**
   Mask-and-research iteration is evidenced for TIC 4206066 (B first, then A
   after masking B; `leo_rerun.py`), but a general per-star iteration cap is
   not documented.
6. **Hard-reject definitions** that cut 23,949 → 4,749 signals are referenced
   ("hard rejects always apply") but not enumerated in the deposited extract;
   the LEO FA/FP test lists themselves are (§4.2).
7. **Sector coverage beyond 98 for the screen: none, by construction** — but
   note the follow-up "pool multisector" refinement mentioned in FINAL_FACTS
   (`DATA.pool_P_A`, an `addenda/pool_multisector/` pass over shortlisted
   candidates) is likewise undeposited; only its result rows are cited.
8. **No source was unreachable.** All three Zenodo records, all four files of
   the supporting record, both protocol PDFs and the full 13.8 MB frozen-code
   ZIP were downloaded and read. Gizmodo was fetched in full; it contains no
   GitHub link (checked, §Sources).
...[truncated 2085 chars]