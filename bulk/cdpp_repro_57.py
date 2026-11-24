"""5.7 CDPP baseline reproduction (VALIDATION_PROTOCOL_5_7.md §7).

For each of the 49 frozen 4.1-10 hosts, rebuild the stitched curve
exactly as the census did (census_cdpp_rescope.py run_star:
per-sector preprocess_sector -> stitch_weighted -> preprocess_arrays,
bulk_v4 calibration) and measure CDPP two ways on the SAME curve:

  census -- _cdpp_at_duration, verbatim from p45_phase0.py (masked at
            a nominal P=3.0 d ephemeris, epoch t_min+1.5; cadence-
            count chunking, trailing partials dropped).
  s3     -- bulk.detrend.measure_cdpp, the frozen §3 procedure (whole
            curve, time-window chunking, 50% trailing rule).

The manifest values came from the census procedure, so the CENSUS
replica must match within 0.1% per host (the harness proof). The §3
values measure a different quantity by construction (no masking,
different chunking) and are expected to differ at the percent level;
the protocol sanctions documenting a proven procedural difference
("fix the implementation (or document a proven difference in the
census procedure)"). The report records both, per host, so the gate
decision can be made from evidence rather than from a bare pass/fail.

Usage (on the Mac, where the S95-S98 caches live):
  python -m bulk.cdpp_repro_57 --manifest p4110_manifest.json \
      --cache /Volumes/NVME/pingu-jobs/exoplanet-hunter/bulk/cache \
      --out cdpp_repro_57.json [--calibration bulk_v4]

The test (tests/test_detrend_57.py::TestCdppRepro) drives run_repro
and asserts the census replica bar; it skips unless
EXHUNT_CDPP_REPRO_CACHE is set.
"""

import argparse
import json
import math
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent
                       / "tests"))

import numpy as np  # noqa: E402

import bulk_screen as bs  # noqa: E402
from bulk import detrend as _detrend  # noqa: E402
from bulk import oracle_run as orc  # noqa: E402
from bulk import p43_stitch as p43  # noqa: E402
from bulk.inject_real_s96 import load_real_fits  # noqa: E402

REF_DURATION_H = 2.39  # _duration_d(1.7 d), the P4-5 anchor duration
CENSUS_PERIOD_D = 3.0  # the census's nominal ephemeris period
CENSUS_EPOCH_OFFSET_D = 1.5  # epoch = t_min + 1.5
REPRO_TOL = 0.001  # 0.1% relative tolerance per host (protocol §7)


def _cdpp_at_duration_census(t, f, duration, period, epoch):
    """VERBATIM from p45_phase0.py via census_cdpp_rescope.py.

    Masked, gap-split chunk-std: in-transit cadences at the nominal
    ephemeris are excluded, |phase| >= 0.45 is excluded, the rest is
    chunked by cadence count (chunk = round(duration/dt), splitting
    where index gaps exceed chunk, trailing partials dropped), and
    CDPP is the std of the chunk means (ddof=0). Returns None when
    fewer than 20 out-of-window cadences or fewer than 5 chunks.
    Any change here must be mirrored against the census file; the
    point of this function is to BE the census procedure.
    """
    phase_t = t - epoch
    events = np.round(phase_t / period)
    centres = epoch + events * period
    inwin = np.abs(t - centres) <= 0.5 * duration
    phase = ((phase_t / period + 0.5) % 1.0) - 0.5
    outwin = (~inwin) & (np.abs(phase) < 0.45)
    if outwin.sum() < 20:
        return None
    dt = float(np.median(np.diff(t))) if len(t) > 1 else 0.0
    chunk = max(int(round(duration / dt)), 1) if dt > 0 else 1
    out_idx = np.where(outwin)[0]
    means = []
    for seg in np.split(out_idx,
                        np.where(np.diff(out_idx) > chunk)[0] + 1):
        for i in range(0, len(seg) - chunk + 1, chunk):
            means.append(np.mean(f[seg[i:i + chunk]]))
    if len(means) < 5:
        return None
    return float(np.std(means)) * 1e6


def run_host(tic, sectors, cache):
    """One host: rebuild the census stitched curve, measure both
    ways. Returns a dict with the census replica, the §3 value, and
    the §3 diagnostics. Raises on missing FITS (a missing sector is
    a hard error here, not a skip -- the manifest's hosts all have
    complete caches)."""
    masked, sigmas = [], {}
    for sec in sectors:
        p = cache / f"s{sec:04d}" / f"{tic}.fits"
        t, f, q, fcol, _meta = load_real_fits(str(p))
        _t_p, _f_p, sig = p43.preprocess_sector(t, f, q)
        sigmas[sec] = sig
        masked.append({"sector": sec, "t": t, "f": f, "q": q,
                       "fcol": fcol,
                       "crowdsap": p43.read_crowdsap(str(p))})
    t_s, f_s, q_s, _tr = p43.stitch_weighted(masked, sigmas)
    t_sp, f_sp = orc.preprocess_arrays(t_s, f_s, q_s)
    t_min = float(np.nanmin(t_sp))
    dur_d = REF_DURATION_H / 24.0
    census = _cdpp_at_duration_census(
        t_sp, f_sp, dur_d, CENSUS_PERIOD_D,
        t_min + CENSUS_EPOCH_OFFSET_D)
    s3 = _detrend.measure_cdpp(t_sp, f_sp, dur_d)
    return {"tic": str(tic), "sectors": list(sectors),
            "n_cadences": int(len(t_sp)),
            "census_cdpp_ppm": census,
            "s3_cdpp_ppm": s3["cdpp_ppm"],
            "s3_mad_ppm": s3["mad_ppm"],
            "s3_n_segments": s3["n_segments"],
            "s3_dt_d": s3["dt_d"]}


def run_repro(manifest_path, cache_dir, out_path=None,
              calibration="bulk_v4"):
    """Run the reproduction over the manifest's hosts. Returns the
    report dict (also written to out_path as JSON when given).
    manifest hosts carry stitched_cdpp_ppm_2p39h (rounded to 0.1
    ppm -- the rounding contributes at most ~0.03% at these
    values, inside the 0.1% tolerance)."""
    bs.set_calibration(calibration)
    manifest = json.loads(Path(manifest_path).read_text())
    cache = Path(cache_dir)
    hosts = manifest["hosts"]
    rows, t_start = [], time.time()
    for host in hosts:
        tic = host["tic"]
        try:
            row = run_host(tic, host["sectors"], cache)
        except Exception as exc:  # noqa: BLE001
            row = {"tic": str(tic), "sectors": host["sectors"],
                   "error": f"{type(exc).__name__}: {exc}"}
        row["manifest_cdpp_ppm"] = host["stitched_cdpp_ppm_2p39h"]
        man = host["stitched_cdpp_ppm_2p39h"]
        if row.get("census_cdpp_ppm") is not None and man:
            row["census_rel_diff"] = (
                row["census_cdpp_ppm"] - man) / man
        else:
            row["census_rel_diff"] = None
        if row.get("s3_cdpp_ppm") is not None and man:
            row["s3_rel_diff"] = (row["s3_cdpp_ppm"] - man) / man
        else:
            row["s3_rel_diff"] = None
        rows.append(row)
    ok = [r for r in rows if "error" not in r]
    census_diffs = [abs(r["census_rel_diff"]) for r in ok
                    if r["census_rel_diff"] is not None]
    s3_diffs = [r["s3_rel_diff"] for r in ok
                if r["s3_rel_diff"] is not None]
    report = {
        "manifest": str(manifest_path),
        "manifest_sha256": manifest.get("census_sha256"),
        "calibration": calibration,
        "tolerance": REPRO_TOL,
        "n_hosts": len(rows),
        "n_ok": len(ok),
        "n_errors": len(rows) - len(ok),
        "census_replica_within_tol": sum(
            1 for d in census_diffs if d <= REPRO_TOL),
        "census_replica_max_abs_rel_diff": (
            max(census_diffs) if census_diffs else None),
        "s3_median_rel_diff": (
            float(np.median(s3_diffs)) if s3_diffs else None),
        "s3_mean_rel_diff": (
            float(np.mean(s3_diffs)) if s3_diffs else None),
        "s3_within_tol": sum(
            1 for d in s3_diffs if abs(d) <= REPRO_TOL),
        "seconds": round(time.time() - t_start, 1),
        "hosts": rows,
    }
    if out_path is not None:
        out_path = Path(out_path)
        out_path.write_text(json.dumps(report, indent=1))
    return report


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="5.7 CDPP baseline reproduction (protocol §7).")
    ap.add_argument("--manifest", required=True,
                    help="4.1-10 manifest (p4110_manifest.json).")
    ap.add_argument("--cache", required=True,
                    help="bulk cache dir (s0095/..s0098 subdirs).")
    ap.add_argument("--out", default=None,
                    help="report JSON path (default: no file).")
    ap.add_argument("--calibration", default="bulk_v4",
                    help="calibration profile (default bulk_v4, "
                         "the census calibration).")
    args = ap.parse_args(argv)
    report = run_repro(args.manifest, args.cache, args.out,
                       calibration=args.calibration)
    print(f"[cdpp-repro] {report['n_ok']}/{report['n_hosts']} hosts "
          f"ok, {report['n_errors']} errors; "
          f"census replica within 0.1%: "
          f"{report['census_replica_within_tol']}/"
          f"{report['n_ok']} "
          f"(max |rel diff| "
          f"{report['census_replica_max_abs_rel_diff']}); "
          f"§3 median rel diff "
          f"{report['s3_median_rel_diff']}, "
          f"§3 within 0.1%: {report['s3_within_tol']}/"
          f"{report['n_ok']}; "
          f"{report['seconds']} s", flush=True)
    if args.out:
        print(f"[cdpp-repro] report: {args.out}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
