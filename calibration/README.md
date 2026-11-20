# Calibration profiles

Thresholds live in code, not in recipes (Phase 1 decision: per-run
thresholds would make screens incomparable). These files are the
versioned record of those thresholds — one profile per pipeline,
immutable once used in a run.

## Files

| Profile | Pipeline | Loaded by |
|---|---|---|
| `bulk_v1.yaml` | bulk screen | `bulk_screen.py` reads it at import; the module constants (`RECORD_FLOOR_SDE`, …) are derived from it |
| `bulk_v2.yaml` | bulk screen | same loader, selected with `--calibration bulk_v2` (or `EXHUNT_BULK_CALIBRATION=bulk_v2`); clip option `floor_10pct` + per-sector systematic windows (see `bulk/SENSITIVITY_MAP.md`) |
| `bulk_v3.yaml` | bulk screen | same loader, selected with `--calibration bulk_v3` (or `EXHUNT_BULK_CALIBRATION=bulk_v3`); v2 thresholds unchanged + `quality_mask` 1610629823 (lightkurve default 17087 + TESS scattered-light bits 29/30) — the 2026-11-15 flagged-cadence artifact fix (see `bulk/SENSITIVITY_MAP.md` §v3) |
| `bulk_v4.yaml` | bulk screen | same loader, selected with `--calibration bulk_v4`; v3 gates verbatim + P3-14 grid-edge floor + the two tier-B gates adopted by the P3-11 decision (parent 2026-11-16, Amendment A): EPOCH-CLUSTER veto (P3-13 criterion, applied at merge) and TWO-COMBINED (2-event rows need both events strong AND mes_pink ≥ 9.0). SDE bars unchanged (bulk 7.0). PHASE-DEPTH held, DEMOTE-SYS/DEMOTE-ALL rejected. Superseded by bulk_v5 for new screens (still loadable for old records). |
| `bulk_v5.yaml` | bulk screen | same loader, selected with `--calibration bulk_v5`; v4 gates verbatim + the EPOCH-CLUSTER veto extended to tier-A members (`epoch_cluster_veto_tier_a: true`, P3-13 criterion unchanged). Fixes round 1 (2026-11-18): the S98 one-shot showed v4's flag-only treatment leaves 42.2% of the queue in the 13.7 d band; measured effect on the frozen S98 run: queue 498 → 314, M6 42.2% → 8.3%, 0/11 recovered TOIs lost. systematic_windows unchanged. Superseded by bulk_v6 for new screens (still loadable for old records). |
| `bulk_v6.yaml` | bulk screen | same loader, selected with `--calibration bulk_v6`; v5 gates verbatim + F-1 merge-time T0-cluster veto (few-event rows, T0-only union-find linkage, 3 h, clusters >20 stars; disposition `DEMOTED_T0_CLUSTER`) + B-1 K=3 join after the (P, T0) veto + mask gating (mask only when pass-1 is contaminant-like: EB flag or depth > 1.0%) + stitched pass-1 recording default-on. PIPE50 vote ref PIPE50-20261119 (2026-11-19). F-1 evidence (NULL_DIAGNOSIS, PROVEN): 158/213 null finals T0-clustered. The 8.33/1,000 bound is KEPT. ACTIVE — supersedes bulk_v5 for new screens. |
| `deep_v1.yaml` | deep pipeline (`hunter.py`) | drift-tested: `tests/test_calibration.py` asserts the profile matches `hunter.py`'s named constants |
| `deep_v2.yaml` | deep pipeline (`hunter.py`) | same drift test, against the new constants; `quality_mask` 1610629823 (lightkurve default 17087 + TESS scattered-light bits 29/30) — the 2026-11-15 flagged-cadence artifact fix for the deep pipeline (M-11: hunter.py's lightkurve downloads kept bits 29/30 on QLP targets) |
| `gauntlet_v1.yaml` | vetting gauntlet | drift-tested against `gauntlet/` + `persistence.py` constants |
| `external_tools_v1.yaml` | external tools (LATTE/TRICERATOPS) | `gauntlet/external_tool.py:load_external_tool_configs` + `gauntlet/stage_result.py:load_external_tools_policy`; shared run settings (seed 20261114, timeout 1800 s, memory 2048 MB) + per-tool venv paths/versions + the Giacalone et al. 2021 TRICERATOPS bars (FPP < 0.015, NFPP < 0.001 validate; FPP ≥ 0.5 refutes) — PROVISIONAL until the Phase 3 vote ratified them |
| `external_tools_v2.yaml` | external tools (LATTE/TRICERATOPS) | same loaders, now the default; v1's settings, paths, versions and bars carried over UNCHANGED + the disposition policy (A) ratified by the unanimous Phase 3 vote (2026-11-15, TB-2) recorded explicitly — FPP ≤ 0.015 and NFPP ≤ 0.001 validate, FPP ≥ 0.5 refutes, the grey zone reads INCONCLUSIVE (never "validated", never "likely planet"), and without a contrast curve intermediate results read INCONCLUSIVE |
| `external_tools_v3.yaml` | external tools (LATTE/TRICERATOPS) | same loaders, now the default (P4-8, 2026-11-17); v2's settings, paths, versions, bars and disposition (A) carried over UNCHANGED, only `timeout_s` 1800 → 3600 — re-derived from the healthy-run tail (a healthy run can exceed 1800 s: outage-era init 1714.3 s + calc ~300 s) |

## Rules

1. **A profile is immutable once used in a run.** Never edit a
   profile version that has stamped records — those records' meaning
   would silently change.
2. **To change a threshold:** copy the file to the next version
   (`bulk_v2.yaml`), bump its `version` field (it must match the
   filename — the loader refuses a mismatch), update the code to
   load the new version, and update the golden suite in the same
   change. Then re-run the injection harness: a threshold change
   without a completeness re-measurement is flying blind.
3. **Every output record stamps its calibration version**
   (`provenance.py`). Records from different calibrations are never
   silently mixed — a Sector 98 screen before recalibration and
   after recalibration are distinguishable in the data.
4. **The bulk profile is the source of truth for the bulk screen.**
   The deep/gauntlet profiles are drift-tested snapshots: the code
   keeps its named constants, and the suite fails if code and
   profile disagree. Either way, a threshold change is a deliberate,
   reviewed change — never a quiet edit.

## Pre-merge exception (F-1, 2026-11-14)

Rule 1 binds a profile **once it has stamped records or reached
main**. A profile version that exists only on an unmerged branch
— never on main, never stamped on a run — may be corrected
pre-merge in ONE commit that updates the profile AND its registry
entry (new sha256 + a rationale noting the correction), with the
golden suite green. This happened once: `gauntlet_v2` gained
`neighbour_search_radius_arcsec: 180.0` before merge, because
the code census defaulted to 60″ while the manual required 180″.
It is an exception for unmerged profiles, not a way around
immutability — after merge, rule 2 (copy to a new version) is
the only path.
