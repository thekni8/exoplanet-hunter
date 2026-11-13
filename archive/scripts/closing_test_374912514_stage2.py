#!/usr/bin/env python
"""Closing test for TIC 374912514 — stage 2: candidate-masked flatten.

Stage 1 replicated hunter._run_pipeline per era (each era's own
pass-1 BLS chose the re-flatten mask). In the middle era that mask
locked onto 15.41 d, leaving the 18.822932 d dips UNPROTECTED, and
the production depth-fix autopsy (DEPTH_FIX_REPORT) documents that
an unmasked flatten(window=101) absorbs ~2/3 of a transit's depth
into the trend. The vet's own fold numbers came from a curve whose
re-flatten masked the candidate. So the fold/control tests are
re-run here on a candidate-masked flatten: the re-flatten mask is
built at the FIXED candidate ephemeris (P_FIX, T0, DUR + the
production 0.02 d padding) — the depth-recovery pass aimed at the
candidate under test, identical for both eras. Stage 1's strict
production replication stands as the primary Test-1 (free BLS)
result; this stage supplies the primary fold/control numbers and
a robustness BLS on the candidate-masked late-era curve.

Everything else (search, download, first-product-per-distinct-
sector de-duplication, stitch corrector, outlier rejection,
fold estimator, scan grid) is identical to stage 1.
"""
import gc
import json
import sys
import time
import warnings
from pathlib import Path

import numpy as np

warnings.filterwarnings("ignore")

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
OUTDIR = BASE / "vetting_results"

sys.path.insert(0, str(BASE))
import closing_test_374912514 as s1  # noqa: E402  (constants + helpers)
import hunter  # noqa: E402
import lightkurve as lk  # noqa: E402

hunter.log_candidate = lambda *a, **k: None

P_FIX, T0, DUR = s1.P_FIX, s1.T0, s1.DUR


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def build_era_candidate_masked(by_sector, sector_list):
    """Stitch era products (production corrector), then flatten with
    the transit mask fixed at the candidate ephemeris (production
    mask formula: |phase| <= duration/2 + 0.02 d). Returns the
    flattened (t, f), per-sector ranges, and the free-BLS result on
    this curve."""
    lcs = [by_sector[s]["lc"] for s in sector_list]
    ranges = {s: (by_sector[s]["tmin"], by_sector[s]["tmax"])
              for s in sector_list}
    coll = lk.LightCurveCollection(lcs)
    lc_raw = (coll.stitch(corrector_func=hunter._stitch_corrector)
              .remove_nans().remove_outliers(sigma=5.0))
    del coll
    gc.collect()
    t_raw = np.asarray(lc_raw.time.value, dtype=float)
    phase = ((t_raw - T0 + 0.5 * P_FIX) % P_FIX) - 0.5 * P_FIX
    mask = np.abs(phase) <= (DUR / 2.0 + 0.02)
    log(f"  candidate mask fraction: {mask.mean():.4f}")
    lc_flat, _tr = lc_raw.flatten(window_length=101, return_trend=True,
                                  mask=mask)
    t = np.asarray(lc_flat.time.value, dtype=float)
    f = np.asarray(lc_flat.flux.value, dtype=float)
    del lc_flat, _tr, lc_raw, phase, mask, t_raw
    gc.collect()
    b = s1.bls_best(t, f)
    bls = {k: v for k, v in b.items() if not k.startswith("_")}
    bls["local_peak_near_pfix"] = s1.bls_local_peak(b, P_FIX)
    log(f"  cand-masked BLS: P={b['period_days']:.5f} SDE={b['sde']:.2f} "
        f"depth={b['depth']*100:.3f}% dur={b['duration_days']*24:.2f}h | "
        f"near {P_FIX:.4f}: P={bls['local_peak_near_pfix']['period_days']:.5f} "
        f"SDE={bls['local_peak_near_pfix']['sde']:.2f}")
    del b
    gc.collect()
    return t, f, ranges, {"n_points_final": int(len(t)),
                          "bls_candidate_masked": bls}


def main():
    t_start = time.time()
    results = {"stage": 2, "flatten_variant": "candidate-masked re-flatten "
               "(mask at fixed ephemeris P=18.82293229322932, T0=1334.4213516145987, "
               "|phase| <= 0.72h/2 + 0.02 d), window_length=101"}
    by_sector = s1.fetch_first_per_sector()
    for era_name, sector_list in (("late_ge60", s1.LATE_SECTORS),
                                  ("middle_27_59", s1.MID_SECTORS)):
        log(f"=== era {era_name} (candidate-masked) ===")
        t, f, ranges, info = build_era_candidate_masked(by_sector, sector_list)
        slices = s1.sector_slices(t, f, ranges, sector_list)
        info["n_sector_slices_used"] = len(slices)
        scan = s1.fold_scan(slices)
        info["fold_scan_summary"] = {k: scan[k] for k in
                                     ("step_days", "n_offsets", "at_phi0",
                                      "best_by_signif", "best_by_depth")}
        results[era_name] = info
        (OUTDIR / f"{s1.TIC}_latefold_scan_{era_name}_candmask.json").write_text(
            json.dumps(scan["scan"], indent=1, default=str))
        a0, bs = scan["at_phi0"], scan["best_by_signif"]
        log(f"  fold phi0: depth={a0['depth_pct']:.3f}% se={a0['se_pct']:.3f}% "
            f"n={a0['n_events']} | best-sig phi={bs['phi_days']:.2f} d "
            f"depth={bs['depth_pct']:.3f}% +- {bs['se_pct']:.3f}% "
            f"({bs['signif']:.1f} sigma, n={bs['n_events']})")
        del t, f, slices, scan
        gc.collect()
    results["elapsed_s"] = round(time.time() - t_start, 1)
    (OUTDIR / f"{s1.TIC}_closing_test_stage2.json").write_text(
        json.dumps(results, indent=2, default=str))
    log(f"DONE in {results['elapsed_s']}s")


if __name__ == "__main__":
    main()
