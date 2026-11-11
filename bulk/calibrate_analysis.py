"""Calibration analysis (offline, proof-run cache only).

For every recorded hit in run_s0001_proof, refold its cached QLP light
curve at the recorded ephemeris and compute rescore metrics that v1 did
not store:
  mes_pink   - LEO-Vetter style MES with pink (duration-scale) noise:
               depth / CDPP_dur * sqrt(N_events), CDPP_dur = std of
               means of out-of-transit chunks of one duration each.
  n_events   - transit events whose centre falls in the data span
  event_snrs - per-event depth / CDPP_dur
  v_ratio    - edge depth / centre depth of the folded in-window
               profile (box ~1.0, V-shaped EB << 1)
  dur_ratio  - BLS duration / physical max central-transit duration
               (M* ~ R* in solar units for 0.2-0.8 Rsun dwarfs)
Preprocessing replicates bulk_screen._screen_one exactly (mask 17087,
5-sigma clip, 2 d savgol flatten).
"""
import json, math, sys
from pathlib import Path
import numpy as np
from astropy.io import fits
from scipy.signal import savgol_filter

ROOT = Path(__file__).resolve().parent
CACHE = ROOT / "cache" / "s0001"
HITS = ROOT / "run_s0001_proof" / "screen_hits.jsonl"
OUT = ROOT / "run_s0001_proof" / "rescore.jsonl"


def load_lc(tic):
    path = CACHE / f"{tic}.fits"
    with fits.open(path, memmap=True) as hdul:
        d = hdul[1].data
        t = np.asarray(d["TIME"], dtype=float)
        flux = np.asarray(d["KSPSAP_FLUX"], dtype=float)
        qual = np.asarray(d["QUALITY"], dtype=int)
    ok = np.isfinite(t) & np.isfinite(flux) & ((qual & 17087) == 0)
    t, f = t[ok], flux[ok]
    if len(t) < 200:
        return None, None
    f = f / np.median(f)
    sd = 1.4826 * np.median(np.abs(f - 1.0))
    if sd > 0:
        keep = np.abs(f - 1.0) < 5 * sd
        t, f = t[keep], f[keep]
    dt = float(np.median(np.diff(t)))
    win = int(round(2.0 / dt)) if dt > 0 else 97
    win += (win % 2 == 0)
    win = int(min(max(win, 31), len(t) // 2 * 2 - 1))
    if win >= 31:
        trend = savgol_filter(f, win, 2)
        trend[trend == 0] = 1.0
        f = f / trend
    return t, f - np.median(f) + 1.0


def analyse(t, f, period, t0, dur_d):
    phase_t = t - t0
    events = np.round(phase_t / period)
    centres = t0 + events * period
    inwin = np.abs(t - centres) <= 0.5 * dur_d
    # observed events: centre within span and >=3 in-window points
    ev_ids = np.unique(events[inwin]) if inwin.any() else np.array([])
    ev_list = []
    for e in ev_ids:
        m = inwin & (events == e)
        if m.sum() >= 1:  # FFI 30-min cadence: a 1-2 h transit is 2-4 pts
            ev_list.append(e)
    n_events = len(ev_list)
    if n_events == 0 or inwin.sum() < 3:
        return None
    outwin = (~inwin) & (np.abs(((phase_t / period + 0.5) % 1.0) - 0.5) < 0.45)
    base = np.median(f[outwin])
    depth = float(base - np.mean(f[inwin]))
    # CDPP at duration scale: non-overlapping out-of-transit chunks
    dt = float(np.median(np.diff(t)))
    chunk = max(int(round(dur_d / dt)), 1)
    out_idx = np.where(outwin)[0]
    means = []
    # chunk in time order over contiguous out segments
    seg = np.split(out_idx, np.where(np.diff(out_idx) > chunk)[0] + 1)
    for s in seg:
        for i in range(0, len(s) - chunk + 1, chunk):
            means.append(np.mean(f[s[i:i + chunk]]))
    if len(means) < 5:
        return None
    cdpp = float(np.std(means))
    mes = depth / cdpp * math.sqrt(n_events) if cdpp > 0 else 0.0
    # per-event SNR
    ev_snr = []
    for e in ev_list:
        m = inwin & (events == e)
        ev_snr.append(float(base - np.mean(f[m])) / cdpp if cdpp > 0 else 0.0)
    # V shape: centre third vs outer thirds of the window
    off = t - centres
    c_m = inwin & (np.abs(off) <= dur_d / 6)
    e_m = inwin & (np.abs(off) > dur_d / 6)
    d_c = float(base - np.mean(f[c_m])) if c_m.sum() >= 1 else 0.0
    d_e = float(base - np.mean(f[e_m])) if e_m.sum() >= 1 else 0.0
    v_ratio = (d_e / d_c) if d_c > 0 else 0.0
    return {"mes_pink": mes, "cdpp_pct": cdpp * 100.0,
            "n_events": n_events, "event_snrs": [round(x, 2) for x in ev_snr],
            "min_event_snr": min(ev_snr) if ev_snr else 0.0,
            "depth_refold_pct": depth * 100.0, "v_ratio": v_ratio}


def main():
    hits = [json.loads(l) for l in open(HITS)]
    rows, done = [], 0
    for h in hits:
        t, f = load_lc(h["tic"])
        if t is None:
            continue
        r = analyse(t, f, h["period_days"], h["t0_btjd"],
                    h["duration_hours"] / 24.0)
        if r is None:
            continue
        # physical max duration (central transit, M~R solar)
        P, R = h["period_days"], (h.get("radius_rsun") or 0.5)
        a_au = (R * (P / 365.25) ** 2) ** (1 / 3)
        r_au = R * 0.00465
        tmax_h = (P * 24 / math.pi) * math.asin(min(r_au / a_au, 1.0))
        r.update({"tic": h["tic"], "status": h["status"], "sde": h["sde"],
                  "period_days": P, "depth_percent": h["depth_percent"],
                  "duration_hours": h["duration_hours"],
                  "dur_ratio": h["duration_hours"] / tmax_h if tmax_h else None,
                  "tmax_hours": tmax_h,
                  "odd_even_ratio": h.get("odd_even_ratio"),
                  "secondary_depth_percent": h.get("secondary_depth_percent"),
                  "near_systematic": h.get("near_systematic"),
                  "control": bool(h.get("control"))})
        rows.append(r)
        done += 1
        if done % 200 == 0:
            print(f"{done}/{len(hits)}", flush=True)
    with open(OUT, "w") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    print(f"wrote {len(rows)} rows -> {OUT}")


if __name__ == "__main__":
    main()
