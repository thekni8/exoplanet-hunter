"""First-look distributions of the merged sector-98 screen hits.

Reads bulk/run_s0098/screen_hits.jsonl (39,906 records) and reports
distributions by status (survivor / recorded / demoted) plus the
period/depth/odd-even structure of the survivor list. This is the
evidence base for the v1.2 -> recalibrated tier rules (the v1.1
MES/CDPP calibration does NOT transfer to 200-s SYS_RM_FLUX data:
survivor rate ~21% vs 1.61% on sector 1).
"""
import json
import numpy as np
from collections import Counter

RUN = "/home/hatch/workspace/exoplanet-hunter/bulk/run_s0098"

recs = [json.loads(l) for l in open(f"{RUN}/screen_hits.jsonl")]
print(f"records: {len(recs)}")
print("status counts:", Counter(r["status"] for r in recs))
print("tier counts (survivors):",
      Counter(r.get("tier") for r in recs if r["status"] == "survivor"))
print("near_systematic counts:",
      Counter(r["near_systematic"] for r in recs))

def q(name, vals):
    v = np.array([x for x in vals if x is not None], dtype=float)
    if len(v) == 0:
        print(f"  {name}: n=0")
        return
    qs = np.percentile(v, [1, 5, 25, 50, 75, 95, 99])
    print(f"  {name}: n={len(v)} "
          f"p1={qs[0]:.3g} p5={qs[1]:.3g} p25={qs[2]:.3g} "
          f"med={qs[3]:.3g} p75={qs[4]:.3g} p95={qs[5]:.3g} "
          f"p99={qs[6]:.3g} max={v.max():.3g}")

for status in ("survivor", "recorded", "demoted"):
    sub = [r for r in recs if r["status"] == status]
    print(f"\n== {status} (n={len(sub)}) ==")
    q("sde", [r["sde"] for r in sub])
    q("mes_pink", [r.get("mes_pink") for r in sub])
    q("depth_percent", [r["depth_percent"] for r in sub])
    q("period_days", [r["period_days"] for r in sub])
    q("n_events", [r.get("n_events") for r in sub])
    q("n_strong_events", [r.get("n_strong_events") for r in sub])
    q("odd_even_ratio", [r.get("odd_even_ratio") for r in sub])
    q("secondary_depth_percent",
      [r.get("secondary_depth_percent") for r in sub])
    q("v_ratio", [r.get("v_ratio") for r in sub])
    q("duration_hours", [r["duration_hours"] for r in sub])

surv = [r for r in recs if r["status"] == "survivor"]
print("\n== survivor structure ==")
print("depth <0.5%:", sum(1 for r in surv if r["depth_percent"] < 0.5))
print("depth 0.5-1%:", sum(1 for r in surv
                           if 0.5 <= r["depth_percent"] < 1.0))
print("depth 1-2%:", sum(1 for r in surv
                         if 1.0 <= r["depth_percent"] < 2.0))
print("depth >=2%:", sum(1 for r in surv if r["depth_percent"] >= 2.0))
print("period <1d:", sum(1 for r in surv if r["period_days"] < 1.0))
print("period 1-2d:", sum(1 for r in surv
                          if 1.0 <= r["period_days"] < 2.0))
print("period 2-5d:", sum(1 for r in surv
                          if 2.0 <= r["period_days"] < 5.0))
print("period 5-10d:", sum(1 for r in surv
                           if 5.0 <= r["period_days"] < 10.0))
print("period 10-15d:", sum(1 for r in surv
                            if 10.0 <= r["period_days"] < 15.0))
print("period >=15d:", sum(1 for r in surv if r["period_days"] >= 15.0))
print("near 13.7d family (12.7-14.3d):",
      sum(1 for r in surv if 12.7 <= r["period_days"] <= 14.3))
print("odd_even <0.7 or >1.43:",
      sum(1 for r in surv
          if r.get("odd_even_ratio") is not None
          and (r["odd_even_ratio"] < 0.7 or r["odd_even_ratio"] > 1.43)))
print("secondary depth >0.3% (EB-like):",
      sum(1 for r in surv
          if r.get("secondary_depth_percent") is not None
          and r["secondary_depth_percent"] > 0.3))
print("near_systematic true:",
      sum(1 for r in surv if r["near_systematic"]))
print("mes_pink >= 20:", sum(1 for r in surv
                             if (r.get("mes_pink") or 0) >= 20))
print("mes_pink >= 30:", sum(1 for r in surv
                             if (r.get("mes_pink") or 0) >= 30))
print("mes_pink >= 50:", sum(1 for r in surv
                             if (r.get("mes_pink") or 0) >= 50))
print("sde >= 20:", sum(1 for r in surv if r["sde"] >= 20))
print("sde >= 50:", sum(1 for r in surv if r["sde"] >= 50))
print("sde >= 100:", sum(1 for r in surv if r["sde"] >= 100))

# Period pile-up: 0.1d bins, top 15
print("\n== top period bins (0.1d, survivors) ==")
bins = Counter(round(r["period_days"], 1) for r in surv)
for p, c in bins.most_common(15):
    print(f"  P~{p:.1f}d: {c}")

# What would a planet-like cut leave? shallow + odd/even consistent +
# no strong secondary + not near systematic
planet_like = [r for r in surv
               if r["depth_percent"] <= 1.0
               and r.get("odd_even_ratio") is not None
               and 0.7 <= r["odd_even_ratio"] <= 1.43
               and (r.get("secondary_depth_percent") or 0) <= 0.3
               and not r["near_systematic"]]
print(f"\nplanet-like cut (depth<=1%, odd/even 0.7-1.43, "
      f"secondary<=0.3%, not near-systematic): {len(planet_like)}")
print("  of those, mes_pink>=15:",
      sum(1 for r in planet_like if (r.get("mes_pink") or 0) >= 15))
print("  of those, mes_pink>=20:",
      sum(1 for r in planet_like if (r.get("mes_pink") or 0) >= 20))
print("  of those, period>=2d:",
      sum(1 for r in planet_like if r["period_days"] >= 2.0))
