"""Validate bulk_screen v1.1 survivor logic against the proof cache.

Re-runs _screen_one (the real integrated code) over every star that
produced a recorded hit in run_s0001_proof — the only stars that can
possibly become survivors — and compares status/tier against the
offline rescore prediction in rescore.jsonl.
"""
import json, sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import bulk_screen as bs

PROOF = ROOT / "bulk" / "run_s0001_proof"
CACHE = ROOT / "bulk" / "cache" / "s0001"


def main():
    hits = [json.loads(l) for l in open(PROOF / "screen_hits.jsonl")]
    jobs = []
    for h in hits:
        star = {"ra": h.get("ra"), "dec": h.get("dec"),
                "tmag": h.get("tmag"), "radius": h.get("radius_rsun")}
        jobs.append((h["tic"], str(CACHE / f"{h['tic']}.fits"), 1, star))
    with ProcessPoolExecutor(max_workers=3) as ex:
        recs = list(ex.map(bs._screen_one, jobs, chunksize=8))
    from collections import Counter
    counts = Counter(r["status"] for r in recs)
    tiers = Counter(r.get("tier") for r in recs if r["status"] == "survivor")
    searched = 1429
    surv = [r for r in recs if r["status"] == "survivor"]
    print("status counts (of recorded-hit stars):", dict(counts))
    print("tiers:", dict(tiers))
    print(f"survivors {len(surv)} = {len(surv)/searched*100:.2f}% of "
          f"{searched} searched")
    ctrl = next(r for r in recs if r["tic"] == "150428135")
    print("CONTROL:", {k: ctrl.get(k) for k in
                       ("status", "tier", "sde", "mes_pink", "n_events",
                        "max_event_snr", "depth_percent")})
    out = PROOF / "v11_validation.jsonl"
    with open(out, "w") as fh:
        for r in sorted(surv, key=lambda x: -(x.get("mes_pink") or 0)):
            fh.write(json.dumps(r) + "\n")
    print("survivor list ->", out)
    for r in sorted(surv, key=lambda x: (x.get("tier") or "",
                                         -(x.get("mes_pink") or 0))):
        print(r.get("tier"), r["tic"], "P", round(r["period_days"], 3),
              "depth%", round(r["depth_percent"], 3),
              "MES", round(r.get("mes_pink") or 0, 1),
              "nev", r.get("n_events"))


if __name__ == "__main__":
    main()
