"""Fetch QLP light curves directly from STScI's AWS S3 public dataset.

Fallback for a MAST search outage: the MAST CAOM search backend
(lightkurve search_lightcurve) can be down while the data itself
is mirrored on S3 (s3://stpubdata, anonymous HTTPS, no AWS
account needed). QLP HLSP files are addressable by TIC + sector,
so no search is needed.

URL pattern (verified 2026-11-16 with real files):
  https://stpubdata.s3.us-east-1.amazonaws.com/mast/hlsp/qlp/
    s<sector:04d>/<tic16 split into 4 groups of 4 digits>/
    hlsp_qlp_tess_ffi_s<sector:04d>-<tic16>_tess_v01_llc.fits

The fetch writes the same per-sector npz files as
gauntlet.rawflux_check.download_author (qlp_s{sec:03d}.npz,
time/flux, float32 flux, deep_v2 quality mask, >=100 good
points), so rawflux_check.load_stitched and
select_pipeline_set work unchanged downstream. The downloaded
FITS files are kept alongside the npz files for auditability.

Built for the P3-9 panel retry (2026-11-16): MAST's search
backend went down ~22:00 IST 2026-11-15 with no announcement,
leaving 6 of 10 panel targets unmeasured. The panel's 4
measured targets already ran on QLP, so a QLP-via-S3 retry
keeps the panel homogeneous (10/10 QLP) — the fetch path is
recorded per target as product_source=QLP-via-S3.
"""

import concurrent.futures
import os
import urllib.error
import urllib.request

import numpy as np

S3_BASE = ("https://stpubdata.s3.us-east-1.amazonaws.com"
           "/mast/hlsp/qlp")

# Sectors to probe when no explicit list is given. TESS sectors
# run past S100 (the panel's SPOC stitch saw S107); 110 covers
# the released range with headroom.
PROBE_SECTORS = range(1, 111)

# Same floor as rawflux_check.download_author: a sector with
# fewer good points than this is not a usable light curve.
MIN_GOOD_POINTS = 100


def qlp_s3_url(tic, sector):
    """The S3 URL of one TIC's QLP light curve for one sector."""
    t16 = f"{int(tic):016d}"
    shard = "/".join(t16[i:i + 4] for i in range(0, 16, 4))
    return (f"{S3_BASE}/s{int(sector):04d}/{shard}/"
            f"hlsp_qlp_tess_ffi_s{int(sector):04d}-{t16}"
            f"_tess_v01_llc.fits")


def qlp_s3_exists(tic, sector, timeout=15):
    """HEAD-probe one QLP file. True/False, or None when the
    probe itself failed (network error — not a 404)."""
    req = urllib.request.Request(qlp_s3_url(tic, sector),
                                 method="HEAD")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status == 200
    except urllib.error.HTTPError as e:
        return e.code == 200
    except Exception:
        return None


def probe_qlp_sectors(tic, sectors=PROBE_SECTORS, workers=20):
    """Which sectors have a QLP file for this TIC.

    Returns (found, unknown): found is the sorted sector list,
    unknown is the sorted list of sectors whose probe failed
    (network error, not a 404 — re-probe those)."""
    jobs = list(sectors)
    found, unknown = [], []
    with concurrent.futures.ThreadPoolExecutor(
            max_workers=workers) as ex:
        fut = {ex.submit(qlp_s3_exists, tic, s): s for s in jobs}
        for f in concurrent.futures.as_completed(fut):
            s = fut[f]
            r = f.result()
            if r is True:
                found.append(s)
            elif r is None:
                unknown.append(s)
    return sorted(found), sorted(unknown)


def qlp_fits_to_npz(fits_path, npz_path, quality_mask=None):
    """Convert one QLP FITS file to a rawflux_check npz.

    Reads with bulk.clean_refold_gate.load_fits (the canonical
    QLP reader: KSPSAP_FLUX -> SYS_RM_FLUX -> DET_FLUX), applies
    the deep_v2 quality mask exactly as
    rawflux_check.download_author does, and writes the same
    npz format (time float64, flux float32, compressed).

    Returns the number of good points. Raises ValueError when
    fewer than MIN_GOOD_POINTS survive (same rule as
    download_author, which skips such a sector).
    """
    from bulk.clean_refold_gate import load_fits
    from quality_flags import DEEP_V2_MASK
    if quality_mask is None:
        quality_mask = DEEP_V2_MASK
    t, f, q, _col = load_fits(fits_path)
    m = np.isfinite(t) & np.isfinite(f)
    m &= (np.asarray(q, dtype=np.int64)
          & int(quality_mask)) == 0
    if int(m.sum()) < MIN_GOOD_POINTS:
        raise ValueError(
            f"{fits_path}: only {int(m.sum())} good points "
            f"(floor {MIN_GOOD_POINTS})")
    np.savez_compressed(npz_path, time=t[m],
                        flux=f[m].astype(np.float32))
    return int(m.sum())


def _download(url, dest, timeout=120):
    """Download one URL to dest (chunked). Raises on failure."""
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        if r.status != 200:
            raise urllib.error.HTTPError(
                url, r.status, "non-200", r.headers, None)
        with open(dest, "wb") as fh:
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                fh.write(chunk)


def fetch_qlp_s3(tic, sectors, data_dir, quality_mask=None,
                 timeout=120, attempts=3):
    """Fetch QLP light curves for TIC + sectors from S3.

    For each sector: download the FITS to
    data_dir/qlp_s{sec:03d}.fits (kept for audit), convert to
    data_dir/qlp_s{sec:03d}.npz via qlp_fits_to_npz. Sectors
    whose npz already exists are skipped (resume support, same
    as download_author). A 404 means no QLP file for that
    sector (not an error — the sector is skipped); other
    failures retry `attempts` times.

    Returns the sorted list of sectors with a usable npz.
    """
    os.makedirs(data_dir, exist_ok=True)
    got = []
    for sec in sorted(int(s) for s in sectors):
        npz_path = os.path.join(data_dir, f"qlp_s{sec:03d}.npz")
        if os.path.exists(npz_path):
            got.append(sec)
            print(f"QLP-S3 s{sec}: cached npz", flush=True)
            continue
        fits_path = os.path.join(data_dir, f"qlp_s{sec:03d}.fits")
        if not os.path.exists(fits_path):
            url = qlp_s3_url(tic, sec)
            ok = False
            for attempt in range(attempts):
                try:
                    _download(url, fits_path, timeout=timeout)
                    ok = True
                    break
                except urllib.error.HTTPError as e:
                    if e.code == 404:
                        print(f"QLP-S3 s{sec}: no file (404)",
                              flush=True)
                        break
                    print(f"QLP-S3 s{sec}: download attempt "
                          f"{attempt} failed HTTP {e.code}",
                          flush=True)
                except Exception as e:  # noqa: BLE001 - retry
                    print(f"QLP-S3 s{sec}: download attempt "
                          f"{attempt} failed {type(e).__name__}: "
                          f"{e}", flush=True)
                if os.path.exists(fits_path):
                    os.remove(fits_path)
            if not ok:
                continue
        try:
            n = qlp_fits_to_npz(fits_path, npz_path,
                                quality_mask=quality_mask)
        except ValueError as e:
            print(f"QLP-S3 s{sec}: {e}", flush=True)
            continue
        got.append(sec)
        print(f"QLP-S3 s{sec}: ok {n} pts", flush=True)
    print(f"QLP-S3: sectors {got}", flush=True)
    return got
