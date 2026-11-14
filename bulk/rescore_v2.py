#!/usr/bin/env python
"""Rescore a v1-screened sector's cache under a chosen profile
(Phase 1.2, B-2; profile-configurable since M-3, 2026-11-15).

v1's symmetric 5-sigma MAD clip ate deep transits on quiet stars
(see bulk/SENSITIVITY_MAP.md: a 3.0% transit on 0.3% noise scored
SDE 5.4, below the floor). The S96-S98 survivor lists carry that
blind spot. This tool re-screens the affected stars — the ones
whose v1 clip level sat below the depths of interest — under the
chosen profile (default bulk_v2), from the sector's
already-downloaded cache. No downloads, no new data: the cache
is the input.

The profile is explicit, never a silent default: --profile names
it, set_calibration applies it, and the run FAILS LOUDLY if the
screen's live QUALITY_MASK differs from the profile's declared
quality_mask. The mask used is recorded in summary.json. A
bulk_v3 rescore is `--profile bulk_v3` (it writes
rescore_v3_s<NNNN>.jsonl; NOTE: bulk/build_ledger.py --rescore
currently looks for rescore_v2_s<NNNN>.jsonl only, so merging a
v3 rescore needs a build_ledger update first -- follow-up for the
post-merge acceptance test, not this branch).

A star needs rescoring when its 5-sigma clip level (5 x MAD-sigma
of its normalised light curve, the level v1's clip cut at) sits
below the maximum depth of interest (depth_eb_pct = 3% from the
v2 profile): any transit up to 3% deep could have been clipped
away under v1.

Usage (run on the Mac, where the cache lives — Dev-only step):
  python bulk/rescore_v2.py --sector 96 --cache bulk/cache \
      --out bulk/rescore/s96_v2 [--dry-run]

--dry-run lists the candidate TICs (+ clip levels) to stdout and
writes candidates.json in --out, and runs no BLS.

A full run re-screens the candidates via bulk_screen._screen_one
under the chosen profile and writes:
  rescore_<tag>_s<NNNN>.jsonl  survivors only, same shape as the
      screen's survivors.jsonl (emit_survivor_record + a
      provenance header), each record carrying superseded_by:
      "<profile>" — the v1 record for this star, if any, is
      superseded by this rescore. <tag> is the profile name
      without the "bulk_" prefix (v2 by default).
  candidates.json           the candidate list (+ clip levels)
  summary.json              counts: scanned / candidates /
      re-screened / survivors / errors, with the profile
      provenance + the quality_mask used.

BOUNDARY (brief section 6, D-2): this tool only re-screens and
writes its own outputs under --out. Merging rescore records into
the sector ledger / survivors list is Release C's job (C-3) —
this tool never writes into a run directory.
"""
import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import bulk_screen as bs  # noqa: E402
import provenance as _prov  # noqa: E402
from calibration import load_profile  # noqa: E402
from mad_clip import mad_sigma  # noqa: E402
from quality_flags import SPOC_DEFAULT_MASK  # noqa: E402

FLUX_COLUMNS = ("KSPSAP_FLUX", "SYS_RM_FLUX", "DET_FLUX")
# No local quality-mask constant: _load_flux uses
# bulk_screen.QUALITY_MASK, the profile-driven value _screen_one
# uses — main() pins it explicitly against the profile's declared
# quality_mask (M-3), so the two tools can no longer drift apart
# on which cadences count.
CLIP_SIGMA = 5.0  # the v1 clip cut: 5 x MAD-sigma


def _load_flux(path):
    """The normalised, quality-masked flux _screen_one sees, plus
    the star meta the FITS header carries (ra/dec/tmag when
    present; radius is not in the header). Same flux-column
    fallback and quality mask as _screen_one, so the clip level
    measured here is the level v1's clip cut at."""
    from astropy.io import fits
    with fits.open(path, memmap=True) as hdul:
        data = hdul[1].data
        t = np.asarray(data["TIME"], dtype=float)
        cols = data.columns.names
        fcol = next((c for c in FLUX_COLUMNS if c in cols), None)
        if fcol is None:
            raise KeyError(f"no known flux column in {cols}")
        flux = np.asarray(data[fcol], dtype=float)
        qual = np.asarray(data["QUALITY"], dtype=int)
        hdr = hdul[0].header
        meta = {"ra": _hdr_float(hdr, "RA_OBJ"),
                "dec": _hdr_float(hdr, "DEC_OBJ"),
                "tmag": _hdr_float(hdr, "TESSMAG"),
                "radius": None}
    ok = np.isfinite(t) & np.isfinite(flux) & ((qual & bs.QUALITY_MASK) == 0)
    f = flux[ok]
    if len(f) < 200:
        return None, meta
    return f / np.median(f), meta


def _hdr_float(hdr, key):
    try:
        v = hdr.get(key)
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def clip_level(path):
    """The v1 clip level for one cached star: 5 x MAD-sigma of its
    normalised flux, as a fraction (0.03 = 3%). None when the file
    cannot be read or has too few usable points."""
    try:
        f, _ = _load_flux(path)
    except Exception:
        return None
    if f is None:
        return None
    _, sig = mad_sigma(f)
    return CLIP_SIGMA * sig


def find_candidates(cache_dir, sector, max_depth_frac):
    """(tic, path, level) for every cached star whose clip level
    sits below max_depth_frac. Sorted by TIC for determinism."""
    sector_dir = Path(cache_dir) / f"s{int(sector):04d}"
    out = []
    for path in sorted(sector_dir.glob("*.fits")):
        level = clip_level(path)
        if level is not None and level < max_depth_frac:
            out.append((path.stem, str(path), level))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Rescore a v1 sector cache under a chosen "
                    "bulk profile (default bulk_v2).")
    ap.add_argument("--sector", type=int, required=True)
    ap.add_argument("--cache", required=True,
                    help="cache root holding s<NNNN>/<tic>.fits")
    ap.add_argument("--out", required=True,
                    help="output directory (created if needed)")
    ap.add_argument("--profile", default="bulk_v2",
                    help="calibration profile to rescore under "
                         "(default bulk_v2; bulk_v3 for the "
                         "post-merge acceptance rescore)")
    ap.add_argument("--dry-run", action="store_true",
                    help="list candidates only, no BLS")
    args = ap.parse_args(argv)

    # M-3: the profile -- and therefore the quality mask -- is
    # explicit. set_calibration applies it to the screen; the
    # check below fails loudly if the screen's live mask ever
    # differs from the profile's declared mask (a drift that
    # would silently rescore under the wrong mask).
    bs.set_calibration(args.profile)
    prof = load_profile(args.profile)
    quality_mask = prof.get("quality_mask", SPOC_DEFAULT_MASK)
    if bs.QUALITY_MASK != quality_mask:
        raise SystemExit(
            f"[rescore] ABORT: screen QUALITY_MASK "
            f"{bs.QUALITY_MASK} != profile {args.profile} "
            f"quality_mask {quality_mask} -- refusing to rescore "
            f"under a mask the profile did not declare")
    tag = args.profile.removeprefix("bulk_")
    print(f"[rescore] profile {args.profile}, quality_mask "
          f"{quality_mask}", flush=True)
    max_depth_frac = prof["depth_eb_pct"] / 100.0

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    sector_dir = Path(args.cache) / f"s{int(args.sector):04d}"
    n_scanned = len(list(sector_dir.glob("*.fits"))) \
        if sector_dir.is_dir() else 0
    t0 = time.time()
    candidates = find_candidates(args.cache, args.sector,
                                 max_depth_frac)
    print(f"[rescore] sector {args.sector}: {n_scanned} cached, "
          f"{len(candidates)} below the {max_depth_frac:.0%} clip "
          f"level", flush=True)
    cand_records = [{"tic": tic, "clip_level_frac": level,
                     "clip_level_pct": level * 100.0}
                    for tic, _, level in candidates]
    (out_dir / "candidates.json").write_text(
        json.dumps(cand_records, indent=2))
    for tic, _, level in candidates:
        print(f"  {tic}  clip level {level * 100:.2f}%", flush=True)
    summary = {"tool": "rescore_v2", "sector": args.sector,
               "calibration_version": args.profile,
               "quality_mask": quality_mask,
               "max_depth_pct": prof["depth_eb_pct"],
               "n_cached": n_scanned,
               "n_candidates": len(candidates),
               "scan_seconds": time.time() - t0,
               "dry_run": bool(args.dry_run)}
    if args.dry_run:
        (out_dir / "summary.json").write_text(
            json.dumps(summary, indent=2))
        return 0

    run_id = _prov.new_run_id(f"rescore_{tag}_s{int(args.sector):04d}")
    started_at = _prov.utc_now_iso()
    prov = _prov.provenance_header(run_id, bs.CALIBRATION_MAP,
                                   timestamp_utc=started_at)
    jsonl_path = (out_dir
                  / f"rescore_{tag}_s{int(args.sector):04d}.jsonl")
    n_survivors = n_errors = 0
    with open(jsonl_path, "w") as fh:
        for i, (tic, path, _) in enumerate(candidates):
            _, meta = _load_flux(path)
            rec = bs._screen_one((tic, path, args.sector, meta))
            if rec.get("status") == "error":
                n_errors += 1
            if rec.get("status") == "survivor":
                out = bs.emit_survivor_record(rec, prov)
                out["superseded_by"] = args.profile
                fh.write(json.dumps(out) + "\n")
                n_survivors += 1
            if (i + 1) % 500 == 0:
                print(f"[rescore] {i + 1}/{len(candidates)} "
                      f"re-screened, {n_survivors} survivors",
                      flush=True)
    summary.update({"run_id": run_id,
                    "provenance": prov,
                    "n_rescreened": len(candidates),
                    "n_survivors": n_survivors,
                    "n_errors": n_errors,
                    "wall_seconds": time.time() - t0})
    (out_dir / "summary.json").write_text(
        json.dumps(summary, indent=2))
    print(f"[rescore] done: {len(candidates)} re-screened, "
          f"{n_survivors} survivors, {n_errors} errors in "
          f"{summary['wall_seconds']:.0f}s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
