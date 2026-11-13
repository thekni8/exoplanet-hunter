#!/usr/bin/env python3
"""Fold a NEIGHBOUR star's light curve at a target's refined ephemeris
(the desk-level photocopy/blend test). Tries QLP first, then an
unfiltered search (eleanor-lite/TASOC HLSP) for faint neighbours.

Usage: neighbour_fold_s98.py <target_tic> <neighbour_tic>
Refined ephemeris taken from desk_finish_s98.REFINED.
"""
import json, os, sys, time
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from desk_finish_s98 import REFINED, fold_depth

BASE = os.path.expanduser("~/workspace/goals/exoplanet-hunter/hidden_files/candidates-vetting")


def fetch_neighbour(tic, outdir, max_sectors=6):
    import lightkurve as lk
    os.makedirs(outdir, exist_ok=True)
    lcs = {}
    for author in ("QLP", None):
        try:
            if author:
                sr = lk.search_lightcurve(f"TIC {tic}", author=author)
            else:
                sr = lk.search_lightcurve(f"TIC {tic}")
        except Exception as e:
            print(f"  search {author or 'all'} failed: {e}", flush=True)
            continue
        if len(sr) == 0:
            print(f"  search {author or 'all'}: no products", flush=True)
            continue
        print(f"  search {author or 'all'}: {len(sr)} rows", flush=True)
        try:
            tbl = sr.table
            by_sec = {}
            for i in range(len(tbl)):
                s = int(tbl["sequence_number"][i])
                by_sec.setdefault(s, i)
            rows = [by_sec[s] for s in sorted(by_sec)][:max_sectors]
            sr = sr[rows]
        except Exception:
            sr = sr[:max_sectors]
        for i in range(len(sr)):
            row = sr[i]
            sec = None
            try:
                sec = int(row.table["sequence_number"][0])
            except Exception:
                pass
            for attempt in range(3):
                try:
                    lc = row.download()
                    break
                except Exception as e:
                    print(f"    download s{sec} attempt {attempt+1} failed: {e}", flush=True)
                    time.sleep(5 * (attempt + 1))
                    lc = None
            if lc is None:
                continue
            try:
                col = None
                for c in ("sap_flux", "kspsap_flux", "pca_flux", "raw_flux", "flux"):
                    if c in lc.colnames:
                        col = c
                        break
                t = np.asarray(lc.time.value, float)
                f = np.asarray(lc[col].value, float)
                m = np.isfinite(t) & np.isfinite(f) & (f > 0)
                t, f = t[m], f[m]
                if sec is None:
                    sec = int(round(np.median(t) // 27))  # fallback, unused
                lcs[sec] = (t, f)
                np.savez(os.path.join(outdir, f"nb_s{sec:03d}.npz"), time=t, flux=f)
                print(f"    s{sec}: {len(t)} pts ({col})", flush=True)
            except Exception as e:
                print(f"    s{sec} process failed: {e}", flush=True)
        if lcs:
            return lcs
    return lcs


def main():
    target, nb = sys.argv[1], sys.argv[2]
    R = REFINED[target]
    outdir = os.path.join(BASE, target, f"neighbour_{nb}")
    print(f"== neighbour {nb} of target {target} (P={R['P']}, T0={R['T0']}, DUR={R['DUR']})", flush=True)
    lcs = fetch_neighbour(nb, outdir)
    if not lcs:
        print("  NO LIGHT CURVE AVAILABLE for neighbour", flush=True)
        with open(os.path.join(BASE, target, f"neighbour_{nb}_fold.json"), "w") as fh:
            json.dump({"target": target, "neighbour": nb, "available": False}, fh, indent=1)
        return
    res = {"target": target, "neighbour": nb, "available": True,
           "ephemeris": R, "per_sector": {}}
    ts, fs = [], []
    for s in sorted(lcs):
        t, f = lcs[s]
        f = f / np.median(f)
        r = fold_depth(t, f, R["P"], R["T0"], R["DUR"])
        res["per_sector"][s] = r
        print(f"  s{s}: depth {r['depth_pct']:.3f}% (white {r['signif_white']:.1f}σ, red {r['signif_red'] if r['signif_red'] is None else round(r['signif_red'],1)}σ)", flush=True)
        ts.append(t)
        fs.append(f)
    t = np.concatenate(ts)
    f = np.concatenate(fs)
    res["combined"] = fold_depth(t, f, R["P"], R["T0"], R["DUR"])
    c = res["combined"]
    print(f"  COMBINED: depth {c['depth_pct']:.3f}% (white {c['signif_white']:.1f}σ, red {c['signif_red'] if c['signif_red'] is None else round(c['signif_red'],1)}σ, n_in={c['n_in']})", flush=True)
    with open(os.path.join(BASE, target, f"neighbour_{nb}_fold.json"), "w") as fh:
        json.dump(res, fh, indent=1)


if __name__ == "__main__":
    main()
