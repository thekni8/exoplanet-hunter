"""3A training dataset builder (Phase 3, P3-17).

Builds the labelled, TIC-grouped training/test dataset for the
offline ranker experiment from the committed data files. All
inputs are READ-ONLY — this module never writes run data.

Classes (three-class, ChatGPT):
  planet    — planet-like (injected planets + pricing trials).
  astro_fp  — astrophysical false positives (confirmed EBs,
              injected EBs/sinusoids, persistence-MIXED, blends,
              P3-5 refuted).
  instr_fp  — instrumental false positives (inverted-null
              survivors, random-survivor residue, no-dip-in-raw-
              flux, flagged-cadence artifacts, raw-fold-brightens).

Design (P3-17):
* Random-survivor negatives: the queue is 92% low-SNR residue,
  so the negative set includes a random sample of rescore
  survivors — not only the 256 strongest (labelled) leads.
  Random survivors are WEAK labels (assumed instrumental FP;
  the true planet rate among survivors is ~1/71k stars, so
  contamination is negligible — recorded, not hidden).
* TIC-grouped splits: the campaign's host split (train 82 /
  test 38) anchors the campaign populations; every other TIC
  gets a seeded random assignment, with campaign-host TICs
  inheriting their host assignment. No TIC straddles train/test
  across ANY population (asserted).
* INCONCLUSIVE is unlabelled, not negative: none remain (the 3
  P3-5 closures were refuted) — asserted on the labels file.
* No 3B-removed populations as negatives: P = 20.0 singles and
  epoch-cluster members (P3-13 criterion, via replay_matrix)
  are excluded from the random/null negative samples.
* No circular labels: campaign labels are injection truth
  (not a screen output); gauntlet labels come from desk stages
  (centroid, persistence, holdout, shape) — none of which are
  Stage 1 features. Recorded per class in CLASSES below.
* Held out (never trained): the 10 known planets present in
  the rescore (9 recovered TOIs + WASP-29b). TOI-700 c is not a
  rescore survivor, so it cannot be scored here (recorded).
* Class weights: balanced (total / (n_classes * n_class)) on
  the TRAIN split, so the EB subclass is not swamped.

Effective-n accounting: the independent unit is the TIC (star),
not the row. ``Dataset.stats`` reports rows AND TICs per split
per class.
"""

import json
import random
import re
from collections import Counter

from bulk import replay_matrix as rm

# The three classes + their provenance (circular-label handling).
CLASSES = ("planet", "astro_fp", "instr_fp")

# Gauntlet LEDGER verdict -> (class, sub-label). The labels file
# (p3-11-labels.json) is the authoritative coarse source; the
# LEDGER refines refuted_other into astro/instrumental by verdict.
# Cross-checked against the labels file on every build (a mismatch
# fails loudly — the two sources must agree).
LEDGER_VERDICTS = {
    "KILLED — eclipsing binary": ("astro_fp", "confirmed_eb"),
    "KILLED — EB blend": ("astro_fp", "eb_blend"),
    "KILLED — persistence MIXED": ("astro_fp", "persistence_mixed"),
    "KILLED — blend photocopy": ("astro_fp", "blend_photocopy"),
    "REFUTED (P3-5) — density + phase incoherence": (
        "astro_fp", "p3_5_refuted"),
    "REFUTED (P3-5) — density (mass-independent) + V-shape": (
        "astro_fp", "p3_5_refuted"),
    "REFUTED (P3-5) — density": ("astro_fp", "p3_5_refuted"),
    "KILLED — no dip in raw flux": ("instr_fp", "no_dip_raw_flux"),
    "KILLED — flagged-cadence artifact": (
        "instr_fp", "flagged_cadence_artifact"),
    "KILLED — raw fold brightens": ("instr_fp", "raw_fold_brightens"),
    "KILLED — catalogued": ("planet", "known_planet"),
}

# Campaign label_class values map 1:1 onto the three classes.
CAMPAIGN_CLASSES = {
    "planet_like": "planet",
    "astrophysical_fp": "astro_fp",
    "instrumental_fp": "instr_fp",
}

# Known planets held out of training (the P3-18 held-out set).
# TOI-700 c (150428135) is not a rescore survivor — absent here
# by construction, recorded in the experiment report.
HELD_OUT_PLANETS = {
    "12999193", "183537452", "209310912", "229111835", "27966179",
    "300604770", "349410350", "382602147", "389753172", "399571743",
}

# Batch-01 EBs (gauntlet ranks 1–25) — Gemini's requirement
# population (P3-18). Ranks come from the LEDGER order.
BATCH_01_EBS = {
    "260540128", "31109583", "373432787", "260265964", "31533156",
    "150272965", "364589441", "137730719", "12422260", "142082942",
    "175298549",
}

_LEDGER_ROW = re.compile(
    r"\| (\d+) \| (\d+) \| ([\d.]+) \| ([\d.]+) \| ([\d.]+) "
    r"\| ([^|]+) \| ([^|]*) \|")
_PHASE05 = re.compile(
    r"phase-0\.5 brightening ([^@]+) @ ([−+\-]?[\d.]+)σ")


def parse_ledger(path):
    """Parse the gauntlet LEDGER.md verdict table.

    Returns {tic: {"rank": int, "verdict": str, "phase05_sigma":
    float | None}}. The phase-0.5 sigma is recorded only where it
    was decisive evidence — its absence is NOT a small sigma.
    """
    out = {}
    with open(path) as fh:
        for line in fh:
            m = _LEDGER_ROW.match(line)
            if not m:
                continue
            rank, tic = int(m.group(1)), m.group(2)
            verdict = m.group(6).strip()
            evidence = m.group(7)
            sigma = None
            pm = _PHASE05.search(evidence)
            if pm:
                sigma = float(pm.group(2).replace("−", "-"))
            out[tic] = {
                "rank": rank, "verdict": verdict,
                "phase05_sigma": sigma,
            }
    return out


def _load_jsonl(path):
    with open(path) as fh:
        return [json.loads(line) for line in fh if line.strip()]


def _load_json(path):
    with open(path) as fh:
        return json.load(fh)


def _tic_split(rng, tic, host_split, test_fraction, cache):
    """Train/test assignment for one TIC (TIC-grouped).

    Campaign-host TICs inherit their host assignment; every other
    TIC gets a seeded random draw, MEMOISED in `cache` — a TIC
    appears in several populations (rescore + null overlap), and
    each must draw once or the TIC straddles train/test.
    Deterministic for a fixed seed.
    """
    if tic in cache:
        return cache[tic]
    if tic in host_split:
        split = host_split[tic]
    else:
        split = "test" if rng.random() < test_fraction else "train"
    cache[tic] = split
    return split


def build_dataset(paths, seed=20261116, n_null_sample=1000,
                  n_random_sample=1000, test_fraction=0.30):
    """Build the labelled dataset. `paths` maps:

      campaign: P3-10 v2 injections.jsonl
      rescore:  rescore_v3_s0096.jsonl (4,692 survivors)
      null:     inverted-null null_survivors.jsonl (3,915)
      labels:   p3-11-labels.json (258 TICs)
      ledger:   rescore-v3-gauntlet LEDGER.md (finer verdicts)

    Returns a dict with keys: rows (list of row dicts), heldout
    (the 10 known-planet rows), stats (effective-n accounting),
    class_weights (balanced, on the train split), exclusions
    (counts of what was kept out and why).
    """
    rng = random.Random(seed)
    split_cache = {}
    labels = _load_json(paths["labels"])
    ledger = parse_ledger(paths["ledger"])

    # INCONCLUSIVE is unlabelled, not negative — none may remain.
    bad = [t for t, v in labels.items() if v == "inconclusive"]
    assert not bad, f"INCONCLUSIVE labels present: {bad}"

    # --- Campaign populations (injection truth labels) ---
    host_split = {}
    rows = []
    with open(paths["campaign"]) as fh:
        for line in fh:
            host = json.loads(line)
            tic = str(host["tic"])
            host_split[tic] = host.get("split", "train")
            for trial in host.get("trials", []):
                if not trial.get("recovered"):
                    continue
                cls = CAMPAIGN_CLASSES[trial["label_class"]]
                rows.append({
                    "tic": tic,
                    "sector": host.get("sector"),
                    "record": trial["screen"],
                    "label": cls,
                    "sublabel": trial.get("label_fine", cls),
                    "split": host_split[tic],
                    "source": "campaign",
                    "trial_id": trial.get("trial_id"),
                })

    # --- Rescore + null rows (full records) ---
    rescore = _load_jsonl(paths["rescore"])
    null_rows = _load_jsonl(paths["null"])
    rescore_by_tic = {str(r["tic"]): r for r in rescore}

    # 3B-removed exclusions: P = 20.0 singles + epoch-cluster
    # members (P3-13 criterion, same code as the replay).
    res_cluster, _ = rm.sector_epoch_cluster_tics(rescore)
    null_cluster, _ = rm.sector_epoch_cluster_tics(null_rows)
    exclusions = Counter()
    for r in rescore:
        if r.get("period_days") == 20.0:
            exclusions["rescore_p20"] += 1
    for r in null_rows:
        if r.get("period_days") == 20.0:
            exclusions["null_p20"] += 1
    exclusions["rescore_cluster"] = len(res_cluster)
    exclusions["null_cluster"] = len(null_cluster)

    # --- Labelled gauntlet leads (finer classes from the LEDGER) ---
    for tic, coarse in labels.items():
        if tic in HELD_OUT_PLANETS:
            continue  # held out — never trained (P3-18 validation)
        rec = rescore_by_tic.get(tic)
        if rec is None:
            continue  # TOI-700 c: not a rescore survivor
        entry = ledger.get(tic)
        if entry is None:
            raise ValueError(f"labelled TIC {tic} has no LEDGER row")
        verdict = entry["verdict"]
        if verdict not in LEDGER_VERDICTS:
            raise ValueError(f"unmapped LEDGER verdict: {verdict!r}")
        cls, sub = LEDGER_VERDICTS[verdict]
        # Cross-check against the coarse labels file.
        expect = {"planet": "planet", "eb": "astro_fp"}.get(
            coarse, ("astro_fp", "instr_fp"))
        if isinstance(expect, str):
            assert cls == expect, (tic, coarse, verdict, cls)
        else:
            assert cls in expect, (tic, coarse, verdict, cls)
        rows.append({
            "tic": tic,
            "sector": rec.get("sector"),
            "record": rec,
            "label": cls,
            "sublabel": sub,
            "split": _tic_split(rng, tic, host_split, test_fraction, split_cache),
            "source": "gauntlet",
            "ledger_rank": entry["rank"],
            "phase05_sigma": entry["phase05_sigma"],
        })

    # --- Random-survivor negatives (weak labels) ---
    labelled = set(labels)
    pool = [
        r for r in rescore
        if str(r["tic"]) not in labelled
        and str(r["tic"]) not in HELD_OUT_PLANETS
        and r.get("period_days") != 20.0
        and str(r["tic"]) not in res_cluster
    ]
    rng.shuffle(pool)
    for rec in pool[:n_random_sample]:
        tic = str(rec["tic"])
        rows.append({
            "tic": tic,
            "sector": rec.get("sector"),
            "record": rec,
            "label": "instr_fp",
            "sublabel": "random_survivor",
            "split": _tic_split(rng, tic, host_split, test_fraction, split_cache),
            "source": "random_survivor",
        })
    exclusions["random_pool"] = len(pool)

    # --- Inverted-null negatives (instrumental by construction) ---
    null_pool = [
        r for r in null_rows
        if r.get("period_days") != 20.0
        and str(r["tic"]) not in null_cluster
    ]
    rng.shuffle(null_pool)
    for rec in null_pool[:n_null_sample]:
        tic = str(rec["tic"])
        rows.append({
            "tic": tic,
            "sector": rec.get("sector"),
            "record": rec,
            "label": "instr_fp",
            "sublabel": "inverted_null",
            "split": _tic_split(rng, tic, host_split, test_fraction, split_cache),
            "source": "inverted_null",
        })
    exclusions["null_pool"] = len(null_pool)

    # --- Held-out known planets (scored, never trained) ---
    heldout = []
    for tic in sorted(HELD_OUT_PLANETS):
        rec = rescore_by_tic.get(tic)
        if rec is None:
            continue
        heldout.append({
            "tic": tic, "sector": rec.get("sector"), "record": rec,
            "label": "planet", "sublabel": "known_planet",
            "split": "heldout", "source": "known_planet",
        })

    # --- TIC-grouped split assertion (no TIC straddles) ---
    seen = {}
    for row in rows:
        prev = seen.setdefault(row["tic"], row["split"])
        assert prev == row["split"], (
            f"TIC {row['tic']} straddles train/test")

    # --- Effective-n accounting + class weights (train split) ---
    stats = {"rows": Counter(), "tics": Counter()}
    for row in rows:
        stats["rows"][(row["split"], row["label"])] += 1
    for (split, label), n in list(stats["rows"].items()):
        tics = {r["tic"] for r in rows
                if r["split"] == split and r["label"] == label}
        stats["tics"][(split, label)] = len(tics)
    train_total = sum(
        n for (s, _), n in stats["rows"].items() if s == "train")
    class_weights = {}
    for cls in CLASSES:
        n_cls = stats["rows"].get(("train", cls), 0)
        class_weights[cls] = (
            train_total / (len(CLASSES) * n_cls) if n_cls else 0.0)

    return {
        "rows": rows,
        "heldout": heldout,
        "stats": {
            "rows": dict(stats["rows"]),
            "tics": dict(stats["tics"]),
        },
        "class_weights": class_weights,
        "exclusions": dict(exclusions),
        "seed": seed,
    }
