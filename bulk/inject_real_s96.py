#!/usr/bin/env python
"""Injection-recovery into REAL S96 light curves (M-6, 2026-11-15).

Claude's minimal scope (2026-11-15 vote, item (d)): one
injection-recovery into real S96 light curves carrying bits
29/30 flags, v2 vs v3, committed with seeds. The synthetic
flag-fraction sweep (bulk/flag_fraction_sweep.py) approximates
real flag patterns; this script tests them for real -- the hosts'
actual QUALITY columns, real noise, real systematics -- and
asks whether v3 loses any injected transit v2 finds.

Method: for each cached S96 FITS, inject a trapezoid transit
(the repo's shared model, injection_harness.inject_transit)
into the real flux, keeping TIME and QUALITY untouched, write
an injected FITS to the work dir, and screen it through the
REAL screen (bulk_screen._screen_one) under bulk_v2 and
bulk_v3. Recovery = status survivor AND the found period
within 1% of the injected period.

Trials (fixed, recorded in summary.json -- these ARE the seeds;
the injection itself is deterministic given them):
  A: 2.0% depth @ 5.123 d, first transit t_min + 2.0 d
  B: 1.0% depth @ 3.317 d, first transit t_min + 1.0 d
Two depths and two periods vary the overlap with the real flag
blocks; trial A is strong enough to dominate the hosts'
pre-existing signals (several hosts are v1 finalists with weak
real signals in them), trial B probes a shallower transit.

Hosts: every .fits in <cache>/s<sector>/ by default (the VM run
used the 6 S96 files on disk), or --tics for a subset. The
hosts' flag coverage (bit 29 / bit 30 / any-flag fractions)
is recorded per star, so the run shows its hosts do carry the
flags under test.

Outputs (in --out-dir, default /tmp/inject_real_s96):
  injections.jsonl   one record per (star, trial, calibration)
  summary.json       the trials + per-star v2/v3 recovery table
  (stdout)           the recovery table
The run's summary is ALSO committed as
bulk/inject_real_s96_summary.json (the clip_grid_summary.json
precedent: small analysis evidence lives in the repo).

Usage:
  python bulk/inject_real_s96.py --cache bulk/cache [--sector 96]
      [--tics 231852754 382069441] [--out-dir DIR]
"""
import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
from astropy.io import fits

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import bulk_screen as bs  # noqa: E402
import injection_harness as ih  # noqa: E402
import provenance as _prov  # noqa: E402
from synth_fits import screen_job  # noqa: E402

FLUX_COLUMNS = ("KSPSAP_FLUX", "SYS_RM_FLUX", "DET_FLUX")
# (label, depth_frac, period_d, epoch_offset_d from t_min)
TRIALS = [
    ("A", 0.020, 5.123, 2.0),
    ("B", 0.010, 3.317, 1.0),
]
CALIBRATIONS = ("bulk_v2", "bulk_v3")
RECOVERY_TOL = 0.01  # found period within 1% of injected


def load_real_fits(path):
    """(t, flux, quality, flux_col, meta) from a cached QLP FITS.
    Same flux-column fallback as _screen_one."""
    with fits.open(path, memmap=True) as hdul:
        data = hdul[1].data
        cols = data.columns.names
        fcol = next((c for c in FLUX_COLUMNS if c in cols), None)
        if fcol is None:
            raise KeyError(f"no known flux column in {cols}")
        t = np.asarray(data["TIME"], dtype=float)
        f = np.asarray(data[fcol], dtype=float)
        q = np.asarray(data["QUALITY"], dtype=np.int64)
        hdr = hdul[0].header
    meta = {"ra": _hdr_float(hdr, "RA_OBJ"),
            "dec": _hdr_float(hdr, "DEC_OBJ"),
            "tmag": _hdr_float(hdr, "TESSMAG"),
            "radius": None}
    return t, f, q, fcol, meta


def _hdr_float(hdr, key):
    try:
        v = hdr.get(key)
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def write_injected_fits(path, t, f_inj, q, fcol):
    """Minimal QLP-like FITS: the injected flux, the real TIME
    and QUALITY columns, the original flux column name."""
    cols = [
        fits.Column(name="TIME", format="D", array=np.asarray(t)),
        fits.Column(name=fcol, format="D",
                    array=np.asarray(f_inj, dtype=float)),
        fits.Column(name="QUALITY", format="J",
                    array=np.asarray(q, dtype=np.int32)),
    ]
    hdul = fits.HDUList([fits.PrimaryHDU(),
                         fits.BinTableHDU.from_columns(cols)])
    hdul.writeto(path, overwrite=True)
    return path


def flag_stats(q):
    """Host flag coverage: fractions carrying bit 29, bit 30,
    and any flag at all."""
    n = len(q)
    return {
        "n_cadences": int(n),
        "frac_bit29": float((((q >> 29) & 1).sum()) / n) if n else 0.0,
        "frac_bit30": float((((q >> 30) & 1).sum()) / n) if n else 0.0,
        "frac_any_flag": float(((q != 0).sum()) / n) if n else 0.0,
    }


def run_star(path, sector, workdir):
    """Inject both trials into one real file; screen each under
    v2 and v3. Returns the star's record (host stats + trials)."""
    tic = Path(path).stem
    t, f, q, fcol, meta = load_real_fits(path)
    rec = {"tic": tic, "source_file": Path(path).name,
           "source_sha256": _prov.file_sha256(path),
           "flux_col": fcol, "flags": flag_stats(q),
           "trials": {}}
    for label, depth, period, epoch_off in TRIALS:
        epoch = float(np.nanmin(t)) + epoch_off
        f_inj, duration_d = ih.inject_transit(t, f, depth, period,
                                              epoch)
        inj_path = Path(workdir) / f"{tic}_inj{label}.fits"
        write_injected_fits(inj_path, t, f_inj, q, fcol)
        trial = {"depth_frac": depth, "period_d": period,
                 "epoch_btjd": epoch, "duration_d": duration_d}
        for cal in CALIBRATIONS:
            bs.set_calibration(cal)
            r = bs._screen_one(screen_job(inj_path, tic=tic,
                                          sector=sector, meta=meta))
            found = r.get("period_days")
            recovered = (
                r.get("status") == "survivor"
                and found is not None
                and abs(found - period) / period < RECOVERY_TOL)
            trial[cal] = {"sde": r.get("sde"),
                          "mes_pink": r.get("mes_pink"),
                          "status": r.get("status"),
                          "tier": r.get("tier"),
                          "period_days": found,
                          "depth_percent": r.get("depth_percent"),
                          "flags": r.get("flags", []),
                          "odd_even_ratio": r.get("odd_even_ratio"),
                          "recovered": bool(recovered)}
        rec["trials"][label] = trial
    return rec


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Inject transits into real S96 light curves; "
                    "screen under v2 vs v3 (see module docstring).")
    ap.add_argument("--cache", required=True,
                    help="cache root holding s<NNNN>/<tic>.fits")
    ap.add_argument("--sector", type=int, default=96)
    ap.add_argument("--tics", nargs="*", default=None,
                    help="subset of TICs (default: every .fits in "
                         "the sector dir)")
    ap.add_argument("--out-dir", default="/tmp/inject_real_s96",
                    help="output directory (injections.jsonl + "
                         "summary.json)")
    args = ap.parse_args(argv)
    sector_dir = Path(args.cache) / f"s{int(args.sector):04d}"
    if args.tics:
        paths = [sector_dir / f"{tic}.fits" for tic in args.tics]
    else:
        paths = sorted(sector_dir.glob("*.fits"))
    missing = [str(p) for p in paths if not p.exists()]
    if missing:
        raise SystemExit(f"[inject] missing files: {missing}")
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    workdir = out_dir / "injected"
    workdir.mkdir(exist_ok=True)
    t0 = time.time()
    records = []
    previous = bs.CALIBRATION_VERSION
    try:
        with open(out_dir / "injections.jsonl", "w") as fh:
            for i, path in enumerate(paths):
                rec = run_star(path, args.sector, workdir)
                records.append(rec)
                fh.write(json.dumps(rec) + "\n")
                fh.flush()
                fs = rec["flags"]
                print(f"[inject] {i + 1}/{len(paths)} TIC {rec['tic']}: "
                      f"bit29 {fs['frac_bit29']:.1%} bit30 "
                      f"{fs['frac_bit30']:.1%} any-flag "
                      f"{fs['frac_any_flag']:.1%}", flush=True)
                for label, trial in rec["trials"].items():
                    print(f"    trial {label} "
                          f"({trial['depth_frac']:.1%} @ "
                          f"{trial['period_d']} d): v2 "
                          f"{trial['bulk_v2']['status']} "
                          f"SDE {trial['bulk_v2']['sde']:.1f} "
                          f"recovered={trial['bulk_v2']['recovered']} | "
                          f"v3 {trial['bulk_v3']['status']} "
                          f"SDE {trial['bulk_v3']['sde']:.1f} "
                          f"recovered={trial['bulk_v3']['recovered']}",
                          flush=True)
    finally:
        bs.set_calibration(previous)
    n_trials = len(records) * len(TRIALS)
    summary = {
        "tool": "inject_real_s96",
        "sector": args.sector,
        "trials": [{"label": label, "depth_frac": depth,
                    "period_d": period, "epoch_offset_d": epoch_off}
                   for label, depth, period, epoch_off in TRIALS],
        "calibrations": list(CALIBRATIONS),
        "recovery_tol": RECOVERY_TOL,
        "n_stars": len(records),
        "n_trials": n_trials,
        "recovered_v2": sum(
            1 for r in records for tr in r["trials"].values()
            if tr["bulk_v2"]["recovered"]),
        "recovered_v3": sum(
            1 for r in records for tr in r["trials"].values()
            if tr["bulk_v3"]["recovered"]),
        "stars": records,
        "wall_seconds": time.time() - t0,
    }
    (out_dir / "summary.json").write_text(
        json.dumps(summary, indent=2))
    print(f"[inject] done: {len(records)} stars x {len(TRIALS)} "
          f"trials in {summary['wall_seconds']:.0f}s; recovered "
          f"v2 {summary['recovered_v2']}/{n_trials}, v3 "
          f"{summary['recovered_v3']}/{n_trials}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
