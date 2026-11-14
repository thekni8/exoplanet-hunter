#!/usr/bin/env python
"""Diagnosis ONLY for TIC 349272923 (sweep-5 target 11), which failed
in Dev's Codespace sweep with:
    '%' (dimensionless) and 'electron / s' are not convertible
after all 19 sectors downloaded, before the BLS stage.

This script does NOT analyze the star (no BLS, no folds). It:
  1. repeats the pipeline's own lightkurve search (authors filter),
  2. downloads the products via hunter._download_products (the same
     code path the sweep used),
  3. inventories each product: author / sector / flux unit / file,
  4. attempts the pipeline's exact stitch expression and captures the
     full traceback, plus per-product normalize() unit outcomes to
     isolate which operand carries which unit into the failure.
Writes sweep5_logs/diag_349272923.json.
"""
import json
import sys
import time
import traceback
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
LOGDIR = BASE / "sweep5_logs"
LOGDIR.mkdir(exist_ok=True)

import hunter  # noqa: E402
import lightkurve as lk  # noqa: E402

TIC = "349272923"
hunter.log_candidate = lambda *a, **k: None  # the star gets no CSV row


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def main():
    out = {"tic": TIC, "sweep_error": "'%' (dimensionless) and "
                                     "'electron / s' are not convertible"}

    log("search (pipeline authors filter) ...")
    search = lk.search_lightcurve(f"TIC {TIC}",
                                  author=["SPOC", "TESS-SPOC", "QLP"])
    out["n_products_authors_filter"] = len(search)
    if len(search) == 0:
        log("  filtered search empty -> pipeline fallback (unfiltered)")
        search = lk.search_lightcurve(f"TIC {TIC}")
        out["n_products_unfiltered_fallback"] = len(search)
        out["search_path"] = "fallback (authors filter returned 0)"
    else:
        out["search_path"] = "authors filter"
    try:
        tab = search.table
        cols = [c for c in ("mission", "author", "year", "exptime",
                            "target_name", "targetid", "description",
                            "provenance_name", "sequence_number")
                if c in tab.colnames]
        out["search_table"] = [
            {c: (str(r[c]) if r[c] is not None else None) for c in cols}
            for r in tab]
    except Exception as exc:
        out["search_table_error"] = f"{type(exc).__name__}: {exc}"
    for row in out.get("search_table", []):
        log(f"  search: {row}")

    log("downloading products via hunter._download_products ...")
    coll = hunter._download_products(search, TIC,
                                     lambda m: log(f"  dl: {m}"))
    out["n_downloaded"] = len(coll)

    inv = []
    for lc in coll:
        meta = lc.meta or {}
        entry = {
            "sector": meta.get("SECTOR"),
            "author": meta.get("AUTHOR") or meta.get("ORIGIN"),
            "creator": meta.get("CREATOR"),
            "filename": meta.get("FILENAME") or meta.get("FILE"),
            "object": meta.get("OBJECT"),
            "n_points": int(len(lc)),
            "flux_unit": str(lc.flux.unit) if hasattr(lc.flux, "unit") else None,
            "flux_err_unit": (str(lc.flux_err.unit)
                              if getattr(lc, "flux_err", None) is not None
                              and hasattr(lc.flux_err, "unit") else None),
            "flux_column_unit": None,
        }
        try:
            col = lc["flux"]
            entry["flux_column_unit"] = str(getattr(col, "unit", None))
        except Exception as exc:
            entry["flux_column_unit"] = f"error: {exc}"
        # what does the pipeline's corrector do to this product's unit?
        try:
            nlc = lc.normalize()
            entry["flux_unit_after_normalize"] = str(nlc.flux.unit)
        except Exception as exc:
            entry["flux_unit_after_normalize"] = (
                f"RAISED {type(exc).__name__}: {exc}")
        inv.append(entry)
        log(f"  product: sector={entry['sector']} author={entry['author']} "
            f"flux_unit={entry['flux_unit']} "
            f"after_normalize={entry['flux_unit_after_normalize']} "
            f"file={entry['filename']}")
    out["products"] = inv

    # the pipeline's exact stitch expression (hunter._run_pipeline and
    # hunter._fetch_stitched both use it)
    log("attempting pipeline stitch expression ...")
    try:
        stitched = coll.stitch(corrector_func=lambda x: x.normalize())
        out["stitch"] = {"ok": True, "n_points": int(len(stitched)),
                         "flux_unit": str(stitched.flux.unit)}
        log("  stitch SUCCEEDED locally (environment difference?)")
    except Exception:
        out["stitch"] = {"ok": False, "traceback": traceback.format_exc()}
        log("  stitch raised — traceback captured")

    # control: stitch with NO corrector (raw units meet head-on)
    try:
        raw = coll.stitch(corrector_func=lambda x: x)
        out["stitch_no_corrector"] = {"ok": True,
                                      "flux_unit": str(raw.flux.unit)}
    except Exception:
        out["stitch_no_corrector"] = {"ok": False,
                                      "traceback": traceback.format_exc()}

    (LOGDIR / "diag_349272923.json").write_text(
        json.dumps(out, indent=2, default=str))
    log("wrote sweep5_logs/diag_349272923.json")


if __name__ == "__main__":
    main()
