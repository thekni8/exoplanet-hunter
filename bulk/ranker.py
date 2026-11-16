"""3A experimental ranker — Stage 1 pre-desk bulk ranker (Phase 3, P3-16–P3-19).

OFFLINE EXPERIMENT ONLY. The ranker ranks; it never filters, never
vetoes, and has NO production influence in Phase 3 (P3-19). Its
promotion to production is a 3.1 decision gated on independent
validation (see PROGRESS.md, "3.1 promotion gate (3A)").

Feature contract (P3-16) — see docs/ranker-feature-contract.md for
the full written contract. Summary:

* Stage 1 is the pre-gauntlet bulk ranker: 1D light-curve + BLS
  features ONLY, computed from screen records. Desk natives are
  EXCLUDED (they do not exist for bulk survivors or injections).
* Feature symmetry (mandatory): every feature is computed by the
  exact same code path on positives and negatives — one extractor
  (``extract_features``) over the intersection of fields present in
  both the campaign screen dicts and the full rescore/null rows.
  Missing values are imputed with FIXED sentinels (never NaN), the
  same for every class; ``check_feature_symmetry`` reports the
  per-class imputation rate so a class-correlated NaN would show.
* Raw period and raw T0 are PROHIBITED as tree features. No feature
  here reads period or T0 at all: without a found duration (the
  campaign's reduced screen dict does not persist ``duration_hours``)
  there is no dimensionless period ratio to build, so period is
  entirely absent from the feature list. The implied-density ratio
  (duration / period^(1/3)) and the fold sigmas (odd_even_sigma,
  phase_05_secondary_sigma, v_shape_metric) are NOT available in
  this offline experiment — recorded in the contract as a 3.1 item
  (persist the full screen record in future campaigns).
* Tier is EXCLUDED from the features: the tier-B gates are a
  baseline the ranker is measured against (P3-18), so feeding tier
  to the model would make that comparison circular.
* No new survivor-record field is introduced: every feature is
  derived from fields already in the schema, so no schema change
  is needed (bundle rule satisfied by construction).

The model (P3-18) is a 3-class HistGradientBoostingClassifier
(planet-like / astrophysical FP / instrumental FP), ranked by
P(planet-like). Baselines: SDE-only, the tier-B gates as a ranker,
and a 5-feature logistic regression.
"""

import math

import numpy as np

# ---------------------------------------------------------------------------
# Feature contract (P3-16)
# ---------------------------------------------------------------------------

# The ten Stage 1 features, in fixed order. Every one is computable
# from the intersection of the campaign screen dict and the full
# rescore/null row — see extract_features.
FEATURE_NAMES = (
    "log_sde",
    "log_mes",
    "log_depth",
    "odd_even_ratio",
    "n_events",
    "n_strong_events",
    "log_max_event_snr",
    "mes_sde_ratio",
    "strong_fraction",
    "single_vs_combined",
)

# Fields the extractor must never read (P3-16 prohibitions + the
# baseline-fairness exclusion). The test pins this: records with
# absurd values in these fields must produce identical features.
PROHIBITED_FIELDS = (
    "period_days",  # raw period — tree must not memorise grid periods
    "t0_btjd",      # raw T0 — same reason
    "tier",         # tier gates are a baseline (P3-18), not a feature
)

# Fixed imputation sentinels (same for every class — symmetry by
# construction). Log features floor at 1.0 (log10 = 0.0) except
# depth, floored at 0.01% (log10 = -2.0). Ratios fall back to 0.0;
# odd_even_ratio falls back to -1.0 (below its valid [0, ~1.5]).
_SENTINEL = {
    "log_sde": 0.0,
    "log_mes": 0.0,
    "log_depth": -2.0,
    "odd_even_ratio": -1.0,
    "n_events": 0.0,
    "n_strong_events": 0.0,
    "log_max_event_snr": 0.0,
    "mes_sde_ratio": 0.0,
    "strong_fraction": 0.0,
    "single_vs_combined": 0.0,
}


def _num(value, default=None):
    """A finite float, or `default` when the value is missing/non-finite."""
    if value is None:
        return default
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(out):
        return default
    return out


def _log10(value, floor):
    """log10 of `value` floored at `floor`; None when unusable."""
    v = _num(value)
    if v is None or v <= 0:
        return None
    return math.log10(max(v, floor))


def extract_features(record):
    """Extract the ten Stage 1 features from one screen record.

    `record` is a campaign screen dict (P3-10) or a full rescore /
    null row — ONE code path for every population (P3-16 symmetry).
    The only normalisation is the event-count key: the campaign
    persists ``n_events_found`` where the screen emits ``n_events``.

    Returns a dict {feature_name: float} — never NaN. Missing or
    non-finite inputs are imputed with the fixed sentinels in
    ``_SENTINEL`` (same for every class). Which features were
    imputed for a record is reported by ``feature_imputation``.
    """
    sde = _num(record.get("sde"))
    mes = _num(record.get("mes_pink"))
    depth = _num(record.get("depth_percent"))
    oe = _num(record.get("odd_even_ratio"))
    n_ev = _num(record.get("n_events", record.get("n_events_found")))
    n_strong = _num(record.get("n_strong_events"))
    max_snr = _num(record.get("max_event_snr"))

    feats = {}
    feats["log_sde"] = _log10(sde, 1.0)
    feats["log_mes"] = _log10(mes, 1.0)
    feats["log_depth"] = _log10(depth, 0.01)
    feats["odd_even_ratio"] = oe
    feats["n_events"] = n_ev
    feats["n_strong_events"] = n_strong
    feats["log_max_event_snr"] = _log10(max_snr, 1.0)
    feats["mes_sde_ratio"] = (
        mes / sde if (mes is not None and sde not in (None, 0.0)) else None
    )
    feats["strong_fraction"] = (
        n_strong / n_ev
        if (n_strong is not None and n_ev not in (None, 0.0))
        else None
    )
    feats["single_vs_combined"] = (
        max_snr / mes
        if (max_snr is not None and mes not in (None, 0.0))
        else None
    )
    for name in FEATURE_NAMES:
        if feats[name] is None:
            feats[name] = _SENTINEL[name]
    return feats


def feature_imputation(record):
    """Feature names that needed sentinel imputation for `record`.

    Used by the symmetry check: a feature whose imputation rate
    differs by class is a class-correlated NaN (a leak signal).
    """
    feats = extract_features(record)
    sde = _num(record.get("sde"))
    mes = _num(record.get("mes_pink"))
    depth = _num(record.get("depth_percent"))
    oe = _num(record.get("odd_even_ratio"))
    n_ev = _num(record.get("n_events", record.get("n_events_found")))
    n_strong = _num(record.get("n_strong_events"))
    max_snr = _num(record.get("max_event_snr"))
    imputed = set()
    if sde is None or sde <= 0:
        imputed.add("log_sde")
    if mes is None or mes <= 0:
        imputed.add("log_mes")
    if depth is None or depth <= 0:
        imputed.add("log_depth")
    if oe is None:
        imputed.add("odd_even_ratio")
    if n_ev is None:
        imputed.add("n_events")
    if n_strong is None:
        imputed.add("n_strong_events")
    if max_snr is None or max_snr <= 0:
        imputed.add("log_max_event_snr")
    if mes is None or sde in (None, 0.0):
        imputed.add("mes_sde_ratio")
    if n_strong is None or n_ev in (None, 0.0):
        imputed.add("strong_fraction")
    if max_snr is None or mes in (None, 0.0):
        imputed.add("single_vs_combined")
    # The returned features must be exactly the imputed set's
    # complement of sentinel values — a self-consistency guard.
    for name in imputed:
        assert feats[name] == _SENTINEL[name], name
    return imputed


def check_feature_symmetry(records_by_class):
    """Per-feature imputation rate by class.

    `records_by_class` maps a class label to a list of screen
    records. Returns {feature: {class: imputation_rate}} plus the
    worst cross-class gap per feature under key ``"_max_gap"``.
    A large gap is a class-correlated NaN — the experiment reports
    it and the feature is re-examined before any 3.1 use.
    """
    rates = {name: {} for name in FEATURE_NAMES}
    for label, records in records_by_class.items():
        n = len(records)
        counts = {name: 0 for name in FEATURE_NAMES}
        for rec in records:
            for name in feature_imputation(rec):
                counts[name] += 1
        for name in FEATURE_NAMES:
            rates[name][label] = counts[name] / n if n else 0.0
    gaps = {}
    for name in FEATURE_NAMES:
        vals = list(rates[name].values())
        gaps[name] = (max(vals) - min(vals)) if vals else 0.0
    rates["_max_gap"] = gaps
    return rates


def features_to_array(records):
    """Feature matrix (n_rows x 10) for a list of screen records."""
    return np.array(
        [[extract_features(r)[name] for name in FEATURE_NAMES]
         for r in records],
        dtype=float,
    )
