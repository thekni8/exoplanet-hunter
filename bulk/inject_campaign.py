#!/usr/bin/env python
"""Injection campaign at scale (Phase 3, P3-10).

Injects ~10^3 planet-like transits plus injected EBs, sinusoidal
variables and flagged-cadence-only dips into REAL cached QLP light
curves and screens them through the REAL bulk screen under bulk_v3.
Serves 3B's injection-recovery loss measurement in the 1-2-event
regime (P3-11's pre-registered adoption rule needs it) and 3A's
training set (P3-16/P3-17).

Method (the M-6 pattern, bulk/inject_real_s96.py): inject a
trapezoid transit (injection_harness.inject_transit) into a real
cached QLP FITS, keeping TIME and QUALITY untouched, write an
injected FITS to the work dir, screen through bulk_screen.
_screen_one under bulk_v3. Recovery = status survivor AND the
found period within 1% of the injected period. The FITS helpers
are REUSED from bulk/inject_real_s96.py by import, not duplicated.

Scale (bulk/inject_campaign_definition.json, the committed
definition -- the definition governs the run): 120 hosts (S96: 80,
S95: 40), 13 trials/host, 1,560 trials, 1,080 planet-like
positives. Periods are continuous LogUniform(0.5, 15) d from a
seeded RNG -- never the discrete grid periods, which a tree would
memorise. A dedicated 13.1-13.3 d subset prices the P3-13
demotion. S97 is the held-out validation sector (never injected);
S98 is LOCKED (TB-8/P3-21) and the runner refuses it outright.

Parallel + resumable (Dev ordered parallel execution): one host =
one unit of work, all its trials in one worker call; a
multiprocessing Pool (default 8 workers, Mac M4) over hosts; no
shared mutable state between workers; each worker writes its own
per-host output file (atomic write), the parent merges at the end
into injections.jsonl + summary.json. A re-launch SKIPS hosts
whose per-host output already exists and matches the definition
sha -- it continues, never restarts.

Host selection WITHOUT the Mac: the definition commits the
SELECTION RULE + seed, not a literal host list (the VM cannot
verify the Mac's window files). The runner resolves the list
deterministically at run time from the cached window files
(same rule + same file = same list) and records each window
file's sha256 in the run summary. --resolve-only prints/writes
the resolved list without screening.

Outputs (in --out-dir, a run-data dir -- never git):
  hosts/<tic>_s<sector>.json   one record per host (all trials +
                               labels + split assignment)
  injections.jsonl             merged host records, sorted
  summary.json                 counts, recovery by kind/depth/
                               period-bin, effective-n, splits
  injected/<tic>_s<sector>_<trial>.fits   injected FITS files
Labels: three-class (planet_like / astrophysical_fp /
instrumental_fp) with finer negative classes; INCONCLUSIVE is
never a label. Splits are TIC-grouped by hash, so the same star's
sectors never straddle train/test. Effective-n counts unique host
TICs as the independent unit, not rows.

Usage (Mac):
  python bulk/inject_campaign.py --definition bulk/inject_campaign_definition.json \
      --cache bulk/cache --out-dir bulk/run_inject_campaign_v1 --workers 8
  python bulk/inject_campaign.py --definition ... --cache ... \
      --out-dir ... --resolve-only   # host-list resolution only
"""
import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import bulk_screen as bs  # noqa: E402
import injection_harness as ih  # noqa: E402
from bulk.inject_real_s96 import (flag_stats, load_real_fits,  # noqa: E402
                                  write_injected_fits)
from synth_fits import screen_job  # noqa: E402

DEFAULT_DEFINITION = ROOT / "bulk" / "inject_campaign_definition.json"
CALIBRATION = "bulk_v3"
RECOVERY_TOL = 0.01  # found period within 1% of injected
GRID_PERIODS = (5.123, 3.317, 2.17, 7.31)  # discrete grid: never used
FORBIDDEN_LABEL = "inconclusive"

# Period-spec -> (sampler, lo_d, hi_d). "loguniform" is the campaign
# default; the 13.2 d pricing subset and the sinusoid range are the
# only deviations, and both are named in the definition.
PERIOD_SPECS = {
    "loguniform": ("loguniform", 0.5, 15.0),
    "uniform_13p1_13p3": ("uniform", 13.1, 13.3),
    "loguniform_0p5_10": ("loguniform", 0.5, 10.0),
}


# ---------------------------------------------------------------------------
# Definition: load + validate
# ---------------------------------------------------------------------------

def definition_sha(definition):
    """Canonical sha256 of the definition dict (resume gate: a host
    output is reusable only if it was produced under this sha)."""
    blob = json.dumps(definition, sort_keys=True).encode()
    return hashlib.sha256(blob).hexdigest()


def load_definition(path):
    with open(path) as fh:
        definition = json.load(fh)
    validate_definition(definition)
    return definition


def validate_definition(d):
    """The definition is the run's contract: refuse a bad one loudly
    rather than running a campaign nobody can interpret."""
    if d.get("calibration") != CALIBRATION:
        raise ValueError(
            f"campaign screens under {CALIBRATION}; definition says "
            f"{d.get('calibration')!r}")
    inject = {int(s) for s in d.get("inject_sectors", {})}
    if not inject:
        raise ValueError("inject_sectors is empty")
    for forbidden, name in ((d.get("holdout_sector"), "holdout"),
                            (d.get("locked_sector"), "locked")):
        if forbidden is not None and int(forbidden) in inject:
            raise ValueError(
                f"sector {forbidden} is the {name} sector and must "
                f"never be an inject sector")
    if not isinstance(d.get("master_seed"), int):
        raise ValueError("master_seed must be an int")
    templates = d.get("trial_templates")
    if not templates:
        raise ValueError("trial_templates is empty")
    labels = d.get("labels", {}).get("by_kind", {})
    for i, tpl in enumerate(templates):
        kind = tpl.get("kind")
        if kind is None or kind.lower() == FORBIDDEN_LABEL:
            raise ValueError(f"template {i}: bad kind {kind!r}")
        if tpl.get("period") not in PERIOD_SPECS:
            raise ValueError(
                f"template {i} ({kind}): unknown period spec "
                f"{tpl.get('period')!r}")
        lab = labels.get(kind)
        if lab is None:
            raise ValueError(
                f"template {i}: kind {kind!r} has no label entry")
        for field in ("class", "fine"):
            if str(lab.get(field, "")).lower() == FORBIDDEN_LABEL:
                raise ValueError(
                    f"template {i} ({kind}): INCONCLUSIVE is never "
                    f"a label")
    grid = d.get("depth_grid_frac", [])
    if not any(0 < g < 0.01 for g in grid):
        raise ValueError(
            "depth grid must cover sub-1% depths (tier-B regime)")
    if 0.01 not in grid:
        raise ValueError("depth grid must include the 1% tier-B cap")
    splits = d.get("splits", {})
    tf = splits.get("train_frac")
    if not (isinstance(tf, (int, float)) and 0 < tf < 1):
        raise ValueError("splits.train_frac must be in (0, 1)")
    return True


# ---------------------------------------------------------------------------
# Sampling: periods, splits, hosts
# ---------------------------------------------------------------------------

def sample_period_loguniform(rng, lo=0.5, hi=15.0):
    """One LogUniform(lo, hi) draw from `rng`."""
    return float(np.exp(rng.uniform(np.log(lo), np.log(hi))))


def sample_period(rng, spec):
    kind, lo, hi = PERIOD_SPECS[spec]
    if kind == "loguniform":
        return sample_period_loguniform(rng, lo, hi)
    return float(rng.uniform(lo, hi))


def host_rng(master_seed, tic, sector):
    """Per-host RNG: deterministic from (master_seed, TIC, sector)
    alone, so a host's trials do not depend on host-list order or
    on any other host -- parallel-safe and resume-safe."""
    return np.random.default_rng(
        np.random.SeedSequence([int(master_seed), int(tic),
                                int(sector)]))


def assign_split(tic, master_seed, train_frac):
    """TIC-grouped split by hash: the assignment depends on the TIC
    alone, so the same star's sectors never straddle train/test and
    the split survives host-list reordering."""
    h = hashlib.sha256(f"{int(master_seed)}:{int(tic)}".encode())
    frac = int(h.hexdigest()[:8], 16) / 2 ** 32
    return "train" if frac < train_frac else "test"


def resolve_hosts(definition, cache_dir, sectors=None):
    """Resolve the host list deterministically from the cached
    window files. Returns (hosts, missing, window_info) where hosts
    is a list of {tic, sector, path} sorted by (sector, tic).
    A host whose FITS file is absent from the cache is EXCLUDED
    (recorded in `missing`), never silently invented; if fewer than
    min_hosts remain, the run refuses to start."""
    cache = Path(cache_dir)
    wanted = {int(s): int(n) for s, n in
              definition["inject_sectors"].items()}
    if sectors is not None:
        keep = {int(s) for s in sectors}
        if not keep <= set(wanted):
            raise ValueError(
                f"--sectors may only narrow the definition's inject "
                f"sectors {sorted(wanted)}; got {sorted(keep)}")
        wanted = {s: n for s, n in wanted.items() if s in keep}
    hosts, missing, window_info = [], [], {}
    for sector in sorted(wanted):
        wpath = (cache / "target_lists" /
                 f"s{sector:04d}_window_default.json")
        if not wpath.exists():
            raise SystemExit(
                f"[inject-campaign] window file missing: {wpath} "
                f"(the Mac-side cache must hold the sector window "
                f"files; see p3-10-mac-commands.md)")
        blob = wpath.read_bytes()
        window_info[sector] = {
            "file": str(wpath),
            "sha256": hashlib.sha256(blob).hexdigest(),
        }
        tics = sorted({int(t) for t in json.loads(blob)["tics"]})
        n = wanted[sector]
        if n > len(tics):
            raise SystemExit(
                f"[inject-campaign] sector {sector}: definition "
                f"wants {n} hosts but the window file holds only "
                f"{len(tics)} TICs")
        rng = np.random.default_rng(
            np.random.SeedSequence([int(definition["master_seed"]),
                                    sector]))
        chosen = sorted(rng.choice(np.array(tics), size=n,
                                   replace=False).tolist())
        for tic in chosen:
            fpath = cache / f"s{sector:04d}" / f"{tic}.fits"
            if fpath.exists():
                hosts.append({"tic": str(tic), "sector": sector,
                              "path": str(fpath)})
            else:
                missing.append({"tic": str(tic), "sector": sector,
                                "path": str(fpath),
                                "reason": "cached FITS absent"})
    hosts.sort(key=lambda h: (h["sector"], int(h["tic"])))
    min_hosts = int(definition.get("host_selection", {})
                    .get("min_hosts", 100))
    if len(hosts) < min_hosts:
        raise SystemExit(
            f"[inject-campaign] only {len(hosts)} hosts resolved "
            f"(< min_hosts {min_hosts}); {len(missing)} chosen hosts "
            f"lack cached FITS files -- see the run summary")
    return hosts, missing, window_info


# ---------------------------------------------------------------------------
# Trial planning + injection
# ---------------------------------------------------------------------------

def plan_trials(definition, rng):
    """Expand the definition's trial templates into per-host trial
    specs using the host RNG (fixed draw order: period, epoch
    offset, then kind-specific draws). Returns a list of specs with
    trial ids, kinds, depths, periods, labels."""
    labels = definition["labels"]["by_kind"]
    specs, counters = [], {}
    for tpl in definition["trial_templates"]:
        kind = tpl["kind"]
        counters[kind] = counters.get(kind, 0) + 1
        period = sample_period(rng, tpl["period"])
        spec = {
            "trial_id": f"{kind}{counters[kind]:02d}",
            "kind": kind,
            "period_d": period,
            # Epoch: first transit centre t_min + U(0, P) -- a random
            # phase, drawn per trial (the M-6 fixed offsets would
            # correlate every host's transit phases).
            "epoch_offset_d": float(rng.uniform(0.0, period)),
            "label_class": labels[kind]["class"],
            "label_fine": labels[kind]["fine"],
        }
        if kind == "sinusoid":
            spec["amplitude_frac"] = float(tpl["amplitude_frac"])
            spec["phase_rad"] = float(rng.uniform(0.0, 2 * np.pi))
        else:
            spec["depth_frac"] = float(tpl["depth_frac"])
        if kind == "eb":
            spec["odd_even_ratio"] = float(tpl["odd_even_ratio"])
            spec["secondary_frac"] = float(tpl["secondary_frac"])
        if kind == "flagged_dip":
            spec["flag_bits"] = list(tpl["flag_bits"])
        specs.append(spec)
    return specs


def _transit_duration_d(period_d):
    """Same duration law as injection_harness.inject_transit:
    2.0 * P^(1/3) hours."""
    return (2.0 * period_d ** (1.0 / 3.0)) / 24.0


def inject_eb(t, f, depth_frac, period_d, epoch_abs,
              odd_even_ratio=0.6, secondary_frac=0.3):
    """V-shaped EB train: a triangular (grazing) profile, alternate
    events scaled by odd_even_ratio, and a secondary eclipse at
    phase 0.5 of depth_frac * secondary_frac. Returns
    (injected_flux, duration_days)."""
    duration_d = _transit_duration_d(period_d)
    half_tot = duration_d / 2.0
    phase = ((t - epoch_abs + 0.5 * period_d) % period_d) - 0.5 * period_d
    event = np.round((t - epoch_abs) / period_d).astype(int)
    depth = np.where(event % 2 == 0, depth_frac,
                     depth_frac * odd_even_ratio)
    mult = np.ones_like(f)
    in_transit = np.abs(phase) < half_tot
    mult[in_transit] = (1.0 - depth[in_transit]
                        * (1.0 - np.abs(phase[in_transit]) / half_tot))
    # Secondary eclipse at phase 0.5, same triangular shape.
    phase2 = ((t - epoch_abs - 0.5 * period_d + 0.5 * period_d)
              % period_d) - 0.5 * period_d
    in_sec = np.abs(phase2) < half_tot
    mult[in_sec] *= (1.0 - depth_frac * secondary_frac
                     * (1.0 - np.abs(phase2[in_sec]) / half_tot))
    return f * mult, duration_d


def inject_sinusoid(t, f, amplitude_frac, period_d, phase_rad=0.0):
    """Sinusoidal variable (rotating / pulsating star). No transit
    duration -- returns (injected_flux, None)."""
    t0 = float(np.nanmin(t))
    mult = 1.0 + amplitude_frac * np.sin(
        2 * np.pi * (t - t0) / period_d + phase_rad)
    return f * mult, None


def inject_flagged_dip(t, f, q, depth_frac, period_d, epoch_abs,
                       flag_bits=(29, 30)):
    """Instrumental artifact: the trapezoid dip exists ONLY on
    cadences already carrying one of `flag_bits` in the host's real
    QUALITY column. TIME and QUALITY are untouched; flux is modified
    on flagged cadences only. The 18-artifact class from the S96 v2
    gauntlet, injected. Returns (injected_flux, duration_days)."""
    mult, duration_d = ih.inject_transit(
        t, np.ones_like(f), depth_frac, period_d, epoch_abs)
    flagged = np.zeros(len(q), dtype=bool)
    for bit in flag_bits:
        flagged |= ((np.asarray(q) >> int(bit)) & 1).astype(bool)
    return f * np.where(flagged, mult, 1.0), duration_d


def inject_trial(t, f, q, spec, t_min):
    """Dispatch one trial spec to its injector. Returns
    (injected_flux, duration_days_or_None, epoch_btjd)."""
    epoch = float(t_min) + spec["epoch_offset_d"]
    kind = spec["kind"]
    if kind in ("planet", "pricing_13p2"):
        f_inj, dur = ih.inject_transit(t, f, spec["depth_frac"],
                                       spec["period_d"], epoch)
    elif kind == "eb":
        f_inj, dur = inject_eb(t, f, spec["depth_frac"],
                               spec["period_d"], epoch,
                               spec["odd_even_ratio"],
                               spec["secondary_frac"])
    elif kind == "sinusoid":
        f_inj, dur = inject_sinusoid(t, f, spec["amplitude_frac"],
                                     spec["period_d"],
                                     spec["phase_rad"])
    elif kind == "flagged_dip":
        f_inj, dur = inject_flagged_dip(t, f, q, spec["depth_frac"],
                                        spec["period_d"], epoch,
                                        spec["flag_bits"])
    else:  # pragma: no cover - validate_definition guards this
        raise ValueError(f"unknown trial kind {kind!r}")
    return f_inj, dur, epoch


def expected_n_events(epoch, period_d, t_min, t_max):
    """Transit centres of the injected train inside [t_min, t_max]
    -- the event count 3B's 1-2-event loss measurement bins on."""
    if period_d <= 0:
        return 0
    first = epoch
    while first - period_d >= t_min:
        first -= period_d
    n = 0
    c = first
    while c <= t_max:
        if c >= t_min:
            n += 1
        c += period_d
    return n


def check_recovery(screen_rec, period_d):
    """M-6 recovery rule: status survivor AND found period within
    1% of injected."""
    found = screen_rec.get("period_days")
    return bool(screen_rec.get("status") == "survivor"
                and found is not None
                and abs(found - period_d) / period_d < RECOVERY_TOL)


# ---------------------------------------------------------------------------
# Per-host run (the parallel unit of work)
# ---------------------------------------------------------------------------

def host_out_path(out_dir, tic, sector):
    return Path(out_dir) / "hosts" / f"{tic}_s{int(sector):04d}.json"


def _atomic_write_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, indent=1))
    os.replace(tmp, path)


def _init_worker(calibration):
    """Pool initializer: each worker sets its own calibration (no
    shared mutable state between workers)."""
    bs.set_calibration(calibration)


def run_host(job):
    """Screen one host's full trial set. `job` is a plain dict
    (picklable for spawn workers): {tic, sector, path, definition,
    definition_sha, out_dir, workdir}. Returns a small status dict;
    the host record goes to its per-host file. A host whose output
    already exists under the same definition sha is SKIPPED
    (resume) -- its file is left untouched."""
    tic, sector = job["tic"], int(job["sector"])
    out_dir, workdir = Path(job["out_dir"]), Path(job["workdir"])
    out_path = host_out_path(out_dir, tic, sector)
    if out_path.exists():
        try:
            existing = json.loads(out_path.read_text())
            if (existing.get("complete") is True
                    and existing.get("definition_sha256")
                    == job["definition_sha"]):
                return {"tic": tic, "sector": sector,
                        "status": "skipped"}
        except (ValueError, OSError):
            pass  # corrupt/partial file: re-run the host
    definition = job["definition"]
    try:
        t, f, q, fcol, meta = load_real_fits(job["path"])
        t_min = float(np.nanmin(t))
        t_max = float(np.nanmax(t))
        rng = host_rng(definition["master_seed"], tic, sector)
        specs = plan_trials(definition, rng)
        rec = {"tic": tic, "sector": sector,
               "split": assign_split(
                   tic, definition["master_seed"],
                   definition["splits"]["train_frac"]),
               "source_file": Path(job["path"]).name,
               "flux_col": fcol,
               "flags": flag_stats(q),
               "definition_sha256": job["definition_sha"],
               "trials": []}
        workdir.mkdir(parents=True, exist_ok=True)
        for spec in specs:
            f_inj, dur, epoch = inject_trial(t, f, q, spec, t_min)
            inj_path = (workdir /
                        f"{tic}_s{sector:04d}_{spec['trial_id']}.fits")
            write_injected_fits(inj_path, t, f_inj, q, fcol)
            r = bs._screen_one(screen_job(inj_path, tic=tic,
                                          sector=sector, meta=meta))
            trial = dict(spec)
            trial.update({
                "epoch_btjd": epoch,
                "duration_d": dur,
                "n_events_expected": (
                    expected_n_events(epoch, spec["period_d"],
                                      t_min, t_max)
                    if spec["kind"] != "sinusoid" else None),
                "screen": {
                    "sde": r.get("sde"),
                    "mes_pink": r.get("mes_pink"),
                    "status": r.get("status"),
                    "tier": r.get("tier"),
                    "period_days": r.get("period_days"),
                    "depth_percent": r.get("depth_percent"),
                    "flags": r.get("flags", []),
                    "odd_even_ratio": r.get("odd_even_ratio"),
                    "search_health": r.get("search_health"),
                },
                "recovered": check_recovery(r, spec["period_d"]),
            })
            rec["trials"].append(trial)
        rec["complete"] = True
        _atomic_write_json(out_path, rec)
        return {"tic": tic, "sector": sector, "status": "done",
                "n_trials": len(specs),
                "n_recovered": sum(1 for tr in rec["trials"]
                                   if tr["recovered"])}
    except Exception as exc:  # noqa: BLE001 - one bad host must not
        # kill the campaign; the failure is recorded in the summary
        # and a re-launch retries the host (no output file exists).
        return {"tic": tic, "sector": sector, "status": "error",
                "error": f"{type(exc).__name__}: {exc}"}


# ---------------------------------------------------------------------------
# Effective-n + merge
# ---------------------------------------------------------------------------

def effective_n_summary(records):
    """Effective-n accounting: rows are correlated observations of
    their host, so the independent unit is the host star (unique
    TIC), not the row. A TIC injected in two sectors counts once."""
    n_rows = sum(len(r.get("trials", [])) for r in records)
    n_hosts = len({r["tic"] for r in records})
    return {
        "n_rows": n_rows,
        "n_host_sectors": len(records),
        "n_hosts": n_hosts,
        "effective_n": n_hosts,
        "note": ("multiple injections into the same host are "
                 "correlated observations; n_hosts is the "
                 "independent unit"),
    }


def merge_outputs(out_dir, definition, window_info, missing,
                  wall_seconds, failures):
    """Merge per-host files into injections.jsonl + summary.json.
    Returns the summary dict."""
    out_dir = Path(out_dir)
    host_files = sorted((out_dir / "hosts").glob("*.json"))
    records = []
    for p in host_files:
        try:
            rec = json.loads(p.read_text())
        except ValueError:
            continue
        if rec.get("complete") is True:
            records.append(rec)
    records.sort(key=lambda r: (r["sector"], int(r["tic"])))
    with open(out_dir / "injections.jsonl", "w") as fh:
        for rec in records:
            fh.write(json.dumps(rec) + "\n")

    def _bin_counts(key_fn):
        bins = {}
        for rec in records:
            for tr in rec["trials"]:
                b = key_fn(tr)
                tot, recov = bins.get(b, (0, 0))
                bins[b] = (tot + 1, recov + int(tr["recovered"]))
        return {b: {"n": tot, "recovered": recov,
                    "rate": (recov / tot if tot else None)}
                for b, (tot, recov) in sorted(bins.items())}

    summary = {
        "tool": "inject_campaign",
        "campaign": definition.get("campaign"),
        "definition_sha256": definition_sha(definition),
        "calibration": CALIBRATION,
        "recovery_tol": RECOVERY_TOL,
        "window_files": window_info,
        "hosts_missing_fits": missing,
        "failures": failures,
        "n_hosts_completed": len(records),
        "effective_n": effective_n_summary(records),
        "splits": {
            s: sum(1 for r in records if r["split"] == s)
            for s in ("train", "test")},
        "recovery_by_kind": _bin_counts(lambda tr: tr["kind"]),
        "recovery_by_class": _bin_counts(lambda tr: tr["label_class"]),
        "recovery_by_depth": _bin_counts(
            lambda tr: str(tr.get("depth_frac",
                                 tr.get("amplitude_frac")))),
        "recovery_by_period_bin": _bin_counts(
            lambda tr: ("13.1-13.3d" if 13.1 <= tr["period_d"] <= 13.3
                        else ("<2d" if tr["period_d"] < 2
                              else ("2-7d" if tr["period_d"] < 7
                                    else ("7-13.1d"
                                          if tr["period_d"] < 13.1
                                          else ">13.3d"))))),
        "recovery_by_n_events": _bin_counts(
            lambda tr: (str(tr["n_events_expected"])
                        if tr["n_events_expected"] is not None
                        else "sinusoid")),
        "wall_seconds": wall_seconds,
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    return summary


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Injection campaign at scale (P3-10): inject "
                    "into real cached QLP curves, screen under "
                    "bulk_v3. See module docstring.")
    ap.add_argument("--definition", default=str(DEFAULT_DEFINITION))
    ap.add_argument("--cache", required=True,
                    help="cache root holding s<NNNN>/<tic>.fits and "
                         "target_lists/s<NNNN>_window_default.json")
    ap.add_argument("--out-dir", default="/tmp/inject_campaign_v1")
    ap.add_argument("--workers", type=int, default=8,
                    help="parallel workers over hosts (default 8, "
                         "for the Mac M4's 10 cores)")
    ap.add_argument("--sectors", nargs="*", type=int, default=None,
                    help="narrow to a subset of the definition's "
                         "inject sectors (never 97/98)")
    ap.add_argument("--tics", nargs="*", default=None,
                    help="restrict to these TICs (smoke runs)")
    ap.add_argument("--limit-hosts", type=int, default=None,
                    help="cap the resolved host list (smoke runs)")
    ap.add_argument("--resolve-only", action="store_true",
                    help="resolve + record the host list, then exit "
                         "without screening")
    ap.add_argument("--merge-only", action="store_true",
                    help="merge existing per-host files into "
                         "injections.jsonl + summary.json, then exit")
    args = ap.parse_args(argv)

    definition = load_definition(args.definition)
    def_sha = definition_sha(definition)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "hosts").mkdir(exist_ok=True)

    if args.merge_only:
        summary = merge_outputs(out_dir, definition, {}, [], 0.0, [])
        print(f"[inject-campaign] merged "
              f"{summary['n_hosts_completed']} hosts")
        return 0

    hosts, missing, window_info = resolve_hosts(
        definition, args.cache, sectors=args.sectors)
    if args.tics:
        keep = {str(t) for t in args.tics}
        hosts = [h for h in hosts if h["tic"] in keep]
    hosts.sort(key=lambda h: (h["sector"], int(h["tic"])))
    if args.limit_hosts is not None:
        hosts = hosts[:args.limit_hosts]
    (out_dir / "hosts.json").write_text(json.dumps(
        {"definition_sha256": def_sha, "window_files": window_info,
         "hosts": hosts, "missing": missing}, indent=1))
    print(f"[inject-campaign] {len(hosts)} hosts resolved "
          f"({len(missing)} chosen hosts lack cached FITS); "
          f"list in {out_dir / 'hosts.json'}", flush=True)
    if args.resolve_only:
        return 0
    if not hosts:
        raise SystemExit("[inject-campaign] no hosts to run "
                         "(--tics/--limit-hosts filtered all out)")

    workdir = out_dir / "injected"
    workdir.mkdir(exist_ok=True)
    jobs = [{"tic": h["tic"], "sector": h["sector"],
             "path": h["path"], "definition": definition,
             "definition_sha": def_sha,
             "out_dir": str(out_dir), "workdir": str(workdir)}
            for h in hosts]
    t0 = time.time()
    failures, done, skipped = [], 0, 0
    if args.workers <= 1:
        bs.set_calibration(CALIBRATION)
        results = [run_host(j) for j in jobs]
    else:
        from multiprocessing import Pool
        with Pool(args.workers, initializer=_init_worker,
                  initargs=(CALIBRATION,)) as pool:
            results = pool.map(run_host, jobs)
    for i, res in enumerate(results):
        if res["status"] == "done":
            done += 1
            print(f"[inject-campaign] {i + 1}/{len(jobs)} TIC "
                  f"{res['tic']} s{res['sector']:04d}: "
                  f"{res['n_recovered']}/{res['n_trials']} "
                  f"recovered", flush=True)
        elif res["status"] == "skipped":
            skipped += 1
            print(f"[inject-campaign] {i + 1}/{len(jobs)} TIC "
                  f"{res['tic']} s{res['sector']:04d}: skipped "
                  f"(already complete)", flush=True)
        else:
            failures.append(res)
            print(f"[inject-campaign] {i + 1}/{len(jobs)} TIC "
                  f"{res['tic']} s{res['sector']:04d}: ERROR "
                  f"{res.get('error')}", flush=True)
    summary = merge_outputs(out_dir, definition, window_info,
                            missing, time.time() - t0, failures)
    eff = summary["effective_n"]
    print(f"[inject-campaign] done: {done} hosts run, {skipped} "
          f"skipped, {len(failures)} failed, "
          f"{summary['n_hosts_completed']} hosts merged; "
          f"{eff['n_rows']} trials, effective-n "
          f"{eff['effective_n']} hosts; "
          f"{summary['wall_seconds']:.0f}s wall")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
