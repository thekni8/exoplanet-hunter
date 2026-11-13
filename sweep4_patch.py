#!/usr/bin/env python
"""Final patch pass: catalogue + contamination blocks into all 11
sweep-4 vetting JSONs, from sweep4_logs/catalog_rows.json (no
re-harvest). Retries the TOI TAP count for every hit (the first pass
errored on 5 of 11) and refreshes archive_toi_rows wherever the
retry succeeds.
"""
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

BASE = Path(__file__).resolve().parent
HITS = ["404931136", "404924199", "389367432", "277313805", "277106730",
        "389564031", "276792620", "425082819", "389672553", "425082078",
        "276791802"]


def toi_rows(tic, tries=3):
    q = f"SELECT tid FROM toi WHERE tid={tic}"
    url = ("https://exoplanetarchive.ipac.caltech.edu/TAP/sync?"
           + urllib.parse.urlencode({"query": q, "format": "csv"}))
    last = None
    for i in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                txt = r.read().decode()
            lines = [ln for ln in txt.strip().splitlines() if ln.strip()]
            return max(0, len(lines) - 1)
        except Exception as exc:
            last = f"error: {exc}"
            time.sleep(5 * (i + 1))
    return last


def main():
    cat = json.loads((BASE / "sweep4_logs" / "catalog_rows.json").read_text())
    rows = cat["rows"]
    for tic in HITS:
        jp = BASE / "vetting_results" / f"{tic}.json"
        d = json.loads(jp.read_text())
        row = rows[tic]
        n = toi_rows(tic)
        old = row.get("archive_toi_rows")
        if isinstance(n, int):
            row["archive_toi_rows"] = n
        print(f"TIC {tic}: TOI retry -> {n} (was {old})")
        contra = row.get("contratio")
        d["catalogue"] = {
            "ra_deg": row.get("ra_deg"), "dec_deg": row.get("dec_deg"),
            "offset_from_centre_deg": row.get("offset_from_centre_deg"),
            "tmag": row.get("tmag"), "rad_rsun_tic": row.get("rad_rsun_tic"),
            "mass_msun": row.get("mass_msun"), "teff_k": row.get("teff_k"),
            "dist_pc": row.get("dist_pc"), "gaia_dr3": row.get("gaia_dr3"),
            "twomass": row.get("twomass"),
            "archive_toi_rows": row.get("archive_toi_rows"),
        }
        d["contamination"] = {
            "tic_contratio": contra,
            "source": "TIC catalog via MAST (the value ExoFOP displays)",
            "flag_line": 0.1,
            "flagged": bool(contra is not None and contra >= 0.1),
        }
        jp.write_text(json.dumps(d, indent=2, default=str))
        print(f"TIC {tic}: catalogue+contamination patched "
              f"(contratio={contra})")
    (BASE / "sweep4_logs" / "catalog_rows.json").write_text(
        json.dumps(cat, indent=2, default=str))
    print("done")


if __name__ == "__main__":
    main()
