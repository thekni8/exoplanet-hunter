#!/usr/bin/env python
"""Retry the NASA Archive TOI TAP counts that errored with
IncompleteRead during the sweep-5 catalog pass, then patch the counts
into sweep5_logs/catalog_rows.json and each star's vetting JSON."""
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

BASE = Path(__file__).resolve().parent
LOGDIR = BASE / "sweep5_logs"
OUTDIR = BASE / "vetting_results"

STARS = ["349408892", "349477874", "349370417", "349309779", "349309664",
         "349268505", "349481800", "349478154", "349519662", "349193749",
         "349370722", "349370477", "349370907", "349273239", "349268662",
         "349193983"]


def toi_rows(tic, tries=5):
    q = f"SELECT tid FROM toi WHERE tid={tic}"
    url = ("https://exoplanetarchive.ipac.caltech.edu/TAP/sync?"
           + urllib.parse.urlencode({"query": q, "format": "csv"}))
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=90) as r:
                txt = r.read().decode()
            lines = [ln for ln in txt.strip().splitlines() if ln.strip()]
            return max(0, len(lines) - 1)
        except Exception as exc:
            last = f"{type(exc).__name__}: {exc}"
            time.sleep(5 * (i + 1))
    return f"error: {last}"


def main():
    cat_path = LOGDIR / "catalog_rows.json"
    cat = json.loads(cat_path.read_text())
    for tic in STARS:
        n = toi_rows(tic)
        print(f"TIC {tic}: TOI rows = {n}", flush=True)
        if isinstance(n, int):
            cat["rows"][tic]["archive_toi_rows"] = n
            jp = OUTDIR / f"{tic}.json"
            if jp.exists():
                d = json.loads(jp.read_text())
                if "catalogue" in d:
                    d["catalogue"]["archive_toi_rows"] = n
                else:
                    d["archive_toi_rows"] = n
                jp.write_text(json.dumps(d, indent=2, default=str))
    cat_path.write_text(json.dumps(cat, indent=2, default=str))
    print("done", flush=True)


if __name__ == "__main__":
    main()
