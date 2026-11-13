"""Recalibrate sector-97 survivor tiers on the real S97 data (v1.3 FINAL).

Sector-97 first look (analyze_s0097_hits.py) vs S98:
  - 97% of survivors pile at 10-15 d (S98: 88%), peak bin 13.7 d
    (2,963) with shoulders 13.3-14.6 d -- the systematic peak MOVED
    (S98: 14.4 d), so the exclusion band moves to [13.2, 15.0].
  - MES shifted higher (median 12.3 vs S98 10.6); the MES cut is
    re-derived from the post-duration MES gap on S97 data, not copied.
  - Duration still pegs at the 6.048 h grid max for most survivors.
  - near_systematic caught 12,115/14,797 (S98: 241/8,450).

Why: the v1.1 MES/CDPP calibration (sector 1, 30-min cadence) does NOT
transfer to 200-s SYS_RM_FLUX data over 57 days. First look
(analyze_s0098_hits.py) showed:
  - 88% of survivors pile at 10-15 d, median period 14.4 d (bin 14.4 d
    alone = 3,848) -- an instrumental systematic the near_systematic
    flag missed (it caught only 241). 7.2 d (255) is the half-alias;
    1.0 d (277) is a sharp daily alias.
  - Median survivor depth 1.33%; 66% >= 1% (EB-like).
  - 33% fail odd/even consistency (<0.7).
  - MES_pink piles just above the Tier A cut of 9 (median 10.6).
  - Duration check (added after the first funnel): 48/62 post-shape
    candidates peg at the 6.048 h grid max, and 50/62 have transit
    durations >15% of the orbital period -- physically impossible for
    a planet (T/P ~ (R*/a)/pi, at most ~0.05-0.08 even for grazing
    ultra-short-period cases around small stars). Those are rotators,
    pulsators, long-eclipse EBs, or systematics -- not planets.

Rules (applied in order to the 14,732 final survivors in
run_s0097/survivors.jsonl, i.e. post TOI/VSX/Zooniverse filtering):
  1. Systematic-period exclusion: drop P in [13.2, 15.0] d (the 13.7 d
     family -- peak bin 13.7 d, shoulders 13.3-14.6 d -- + tail to
     15.0 d), [7.0, 7.4] d (half-alias), [0.98, 1.02] d (daily
     alias). A real planet in these bands cannot be told from the
     systematic in single-sector data.
  2. Planet-like shape: depth <= 1.0%, odd/even in [0.7, 1.43],
     secondary depth <= 0.3%.
  3. Physical duration: transit duration <= 8% of the period.
  4. Strength: MES_pink >= threshold re-derived from the S97
     post-duration MES gap (--stop-after-duration prints it; the
     threshold sits in the largest natural gap so the cut is robust,
     not tuned).

Output: run_s0098/recalibrated/survivors_v13.jsonl (MES descending)
+ summary_v13.json + rejected_audit.jsonl (every input survivor with
the stage that removed it, or 'kept').
"""
import json
import os

RUN = "/home/hatch/workspace/exoplanet-hunter/bulk/run_s0097"
OUT = f"{RUN}/recalibrated"

MES_MIN = 15.0  # default; re-derived from the S97 gap (see --mes-min)
SYS_BANDS = [(13.2, 15.0), (7.0, 7.4), (0.98, 1.02)]
DEPTH_MAX = 1.0
OE_LO, OE_HI = 0.7, 1.43
SEC_MAX = 0.3
DUR_FRAC_MAX = 0.08


def in_sys_band(p):
    return any(lo <= p <= hi for lo, hi in SYS_BANDS)


def shape_ok(r):
    oe = r.get("odd_even_ratio")
    sec = r.get("secondary_depth_percent")
    return (r["depth_percent"] <= DEPTH_MAX
            and oe is not None and OE_LO <= oe <= OE_HI
            and sec is not None and sec <= SEC_MAX)


def dur_frac(r):
    return r["duration_hours"] / 24.0 / r["period_days"]


def main():
    global MES_MIN
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--mes-min", type=float, default=MES_MIN)
    ap.add_argument("--stop-after-duration", action="store_true",
                    help="print post-duration MES values and exit")
    args = ap.parse_args()
    MES_MIN = args.mes_min
    os.makedirs(OUT, exist_ok=True)
    recs = [json.loads(l) for l in open(f"{RUN}/survivors.jsonl")]
    funnel = {"input_survivors": len(recs)}
    audit = []

    s1 = []
    for r in recs:
        if in_sys_band(r["period_days"]):
            audit.append((r["tic"], "period_systematic"))
        else:
            s1.append(r)
    funnel["after_period_exclusion"] = len(s1)

    s2 = []
    for r in s1:
        if not shape_ok(r):
            audit.append((r["tic"], "shape"))
        else:
            s2.append(r)
    funnel["after_shape_cuts"] = len(s2)

    s3 = []
    for r in s2:
        if dur_frac(r) > DUR_FRAC_MAX:
            audit.append((r["tic"], "duration"))
        else:
            s3.append(r)
    funnel["after_duration_cut"] = len(s3)
    if args.stop_after_duration:
        vals = sorted((r.get("mes_pink") or 0) for r in s3)
        print(f"post-duration survivors: {len(s3)}")
        print("MES values (sorted):",
              [round(v, 1) for v in vals])
        print("largest gaps:")
        gaps = sorted(((vals[i+1]-vals[i], vals[i], vals[i+1])
                       for i in range(len(vals)-1)), reverse=True)[:6]
        for g, lo, hi in gaps:
            print(f"  gap {g:.1f}: {lo:.1f} -> {hi:.1f}")
        return

    s4 = []
    for r in s3:
        if (r.get("mes_pink") or 0) < MES_MIN:
            audit.append((r["tic"], "mes"))
        else:
            s4.append(r)
    funnel["after_mes_cut"] = len(s4)

    for r in s4:
        r["tier_v13"] = "A"  # all are >=3 events by construction here
        audit.append((r["tic"], "kept"))
    s4.sort(key=lambda r: -(r.get("mes_pink") or 0))
    funnel["recalibrated"] = len(s4)
    funnel["rules"] = {
        "sys_bands_days": SYS_BANDS,
        "depth_max_percent": DEPTH_MAX,
        "odd_even_range": [OE_LO, OE_HI],
        "secondary_max_percent": SEC_MAX,
        "duration_frac_max": DUR_FRAC_MAX,
        "mes_min": MES_MIN,
        "mes_gap_note": "re-derived from the S97 post-duration MES gap; "
                        "see run_s0097/recalibrated/mes_gap.txt",
    }

    with open(f"{OUT}/survivors_v13.jsonl", "w") as fh:
        for r in s4:
            fh.write(json.dumps(r) + "\n")
    with open(f"{OUT}/rejected_audit.jsonl", "w") as fh:
        for tic, stage in audit:
            fh.write(json.dumps({"tic": tic, "stage": stage}) + "\n")
    with open(f"{OUT}/summary_v13.json", "w") as fh:
        json.dump(funnel, fh, indent=2)

    print("FUNNEL:", json.dumps(funnel, indent=2))
    print("\nFINAL LIST (MES descending):")
    for r in s4:
        print(f"  TIC {r['tic']} P={r['period_days']:.4f}d "
              f"dur={r['duration_hours']:.2f}h "
              f"frac={dur_frac(r):.3f} depth={r['depth_percent']:.3f}% "
              f"MES={r.get('mes_pink'):.1f} SDE={r['sde']:.1f} "
              f"nev={r.get('n_events')} oe={r.get('odd_even_ratio'):.2f} "
              f"Tmag={r['tmag']:.1f} R={r['radius_rsun']:.2f} "
              f"RA={r['ra']:.2f} Dec={r['dec']:.2f}")


if __name__ == "__main__":
    main()
