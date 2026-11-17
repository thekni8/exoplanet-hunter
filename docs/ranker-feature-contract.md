# 3A ranker — feature contract (P3-16)

**Status:** Stage 1 defined and implemented (`bulk/ranker.py`).
Stage 2 defined in writing only — NOT built in Phase 3.

## The two ranking stages

### Stage 1 — pre-desk (pre-gauntlet) bulk ranker: BUILT

Ranks bulk survivors before any desk work, from 1D light-curve +
BLS features only. The features are computed from screen records
(campaign screen dicts and full rescore/null rows) — no light
curve, no pixels, no desk stage is involved.

| # | Feature | Source field(s) | Notes |
|---|---|---|---|
| 1 | `log_sde` | `sde` | log10, floored at 1.0 |
| 2 | `log_mes` | `mes_pink` | log10, floored at 1.0 |
| 3 | `log_depth` | `depth_percent` | log10, floored at 0.01% |
| 4 | `odd_even_ratio` | `odd_even_ratio` | as recorded; see degeneracy note |
| 5 | `n_events` | `n_events` / `n_events_found` | the one key normalisation |
| 6 | `n_strong_events` | `n_strong_events` | |
| 7 | `log_max_event_snr` | `max_event_snr` | log10, floored at 1.0 |
| 8 | `mes_sde_ratio` | `mes_pink / sde` | pink-noise penalty |
| 9 | `strong_fraction` | `n_strong_events / n_events` | |
| 10 | `single_vs_combined` | `max_event_snr / mes_pink` | single-event vs combined |

**Feature symmetry (mandatory, enforced by construction):** one
extractor (`bulk.ranker.extract_features`) runs the exact same
code path on every population. Missing or non-finite inputs are
imputed with FIXED sentinels (same for every class — never NaN).
`bulk.ranker.check_feature_symmetry` reports the per-feature
imputation rate by class; a class-correlated NaN shows as a large
cross-class gap and is reported by the experiment (P3-18).

**Prohibited / excluded:**
- **Raw period and raw T0** — prohibited as tree features (the
  tree must not memorise grid periods). No feature here reads
  period or T0 at all (pinned by test).
- **Tier** — excluded: the tier-B gates are a baseline the ranker
  is measured against (P3-18), so feeding tier to the model would
  make that comparison circular.
- **Flags** — excluded: demotion flags are empty for survivors
  (both populations), so they carry no ranking signal.
- **Desk natives** — excluded from Stage 1: they do not exist for
  bulk survivors or injected rows ("has pixel data = negative").

**Odd/even degeneracy note:** the P3-11 decision found 13
recovered planets with `odd_even_ratio = 0.000` exactly — the
screen found 2 events where 3–4 were injected, so one parity
class measures zero depth. The ratio is a noisy feature for
2-found-event rows (it punishes the screen losing events, not
alternating depths). It stays in the feature list (the model
learns what the data says), but it is NOT a gate here, and the
degeneracy is a 3.1 characterisation item.

### Stage 2 — post-desk ranker: DEFINED, NOT BUILT

Ranks survivors AFTER desk work, from the full native evidence:
centroid offset, persistence stamp, holdout result, difference-
imaging verdict, transit-fit shape (T23/T14, density ratio),
TRICERATOPS FPP. Stage 2 is defined in writing only. It is NOT
built in Phase 3 because no desk natives exist for bulk survivors
or injected rows — building it would require running every
positive injection through the full desk native extractor (the
expensive alternative), and the desk runs on MAST data the VM
experiment cannot reach. Cost recorded; the alternative was
rejected for Phase 3. Stage 2 is a 3.1 item.

## Features NOT available in this offline experiment (recorded gap)

The P3-10 campaign persists a REDUCED screen dict
(`bulk/inject_campaign.py`: sde, mes_pink, status, tier,
period_days, depth_percent, flags, odd_even_ratio,
search_health, n_events_found, n_strong_events, max_event_snr,
alts). It does NOT persist `duration_hours`,
`secondary_depth_percent`, `v_ratio`, `cdpp_pct`, `t0_btjd`, or
`near_systematic`. The VM has no light-curve cache, so the
missing fields cannot be recomputed here. Consequences:

- **Duration features are unavailable** — no `duration`, no
  `duration / period`, and no implied-density ratio
  (duration / period^(1/3)). The brief's dimensionless-ratio
  guidance is satisfied vacuously: period is entirely absent
  from the feature list.
- **Fold sigmas are unavailable** — `odd_even_sigma`,
  `phase_05_secondary_sigma`, and `v_shape_metric` need the fold
  + noise, which the campaign did not persist. `odd_even_ratio`
  (the recorded ratio, not a sigma) is the closest available
  feature and is used instead.
- **3.1 item:** future campaigns should persist the FULL screen
  record (or at least duration_hours, secondary_depth_percent,
  v_ratio) so these features become available symmetrically.

## Schema

No new survivor-record field is introduced: every Stage 1
feature is derived from fields already in
`schema/survivor-schema.json` (49 properties), so no schema
change is needed. The bundle rule ("any feature not in the
schema must be added first") is satisfied by construction —
the ranker reads schema fields, it adds none.
