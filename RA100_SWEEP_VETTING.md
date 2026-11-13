# RA 100 Sweep — Vetting Report

Field: RA 100.0, Dec −68.0, cone 0.5° (Mac-hosted sweep, still running when this hit was flagged at 02:10 IST, 2026-11-06; vetting requested by Dev 02:38 IST). One hit vetted. All measurements VM-local; the Mac was not touched and nothing was pushed. `data/hunter.db` and `discoveries.csv` md5-verified byte-identical before/after (history logging suppressed in every driver process).

---

## TIC 167367406 — EB (contact / near-contact twin eclipsing binary)

**Sweep hit:** P = 0.6519 d, SDE = 94.7 (project-record SDE), high-contamination flag, persistence stamp 18/18 sectors, mean persistence depth 12.43% ("patchy").

**Star (ID-verified TIC row — the query returned exactly one row and its ID matches):** R* = 0.389 R☉, M* = 0.379 M☉, Teff = 3542 K (M dwarf), Tmag = 14.205, Gaia G = 15.369, contratio = **0.197**. TIC distance/parallax are NaN for this row — no distance on record here. Not previously flagged as known (Zooniverse Talk check: false).

### Reproduction (stage a) — exact
P = 0.65191519 d (rel. diff 2.3×10⁻⁵ vs sweep), SDE = **94.72**, depth = **20.740%**, Rp-if-planet = 19.32 R⊕, duration 2.376 h, 18 sectors / 181,204 points. The signal is overwhelmingly real in the target's aperture. (A 19.3 R⊕ "planet" at 0.65 d around a 0.389 R☉ dwarf was never a sane reading; the question was always which kind of binary and on which star.)

### The fold profile — the decisive evidence
The binned raw fold (25 bins, medians) does not show a planet-like transit or a clean two-eclipse 2P fold. It shows a **continuous dip train**: minima every **0.21731 d** with no flat out-of-eclipse stretch — contact-binary (EW) morphology at ~20–25% peak-to-dip amplitude. In the P fold the minima sit at phases 0, 1/3, 2/3 (medians 0.766 / 0.723 / 0.739 vs maxima ≈ 1.08); in the 2P fold at every 1/6 phase (medians 0.78–0.88). Lomb–Scargle on the raw curve agrees: dominant peak **0.21731 d, power 0.617**, nothing at P or 2P themselves.

So the sweep's period is an alias: **0.651915 d = 3 × 0.21731 d exactly.** The orbital period is **0.43461 d** on the standard twin-eclipse reading (near-equal minima), or 0.21731 d if the system sits at the contact-binary period cutoff; the data leave that one ambiguity open and it does not affect the species.

### Machine stamp (stages b, c) — and its reconciliation
- Odd/even (machine): odd 9.095% vs even 9.045% → "planet-like". Hand odd/even at P confirms equality: 5.304% ± 0.087 vs 5.180% ± 0.085, difference **+0.124% = 1.03σ**. Both are the known twin-eclipse blind spot (the TIC 308851365 configuration): near-equal minima cannot split.
- Double-period (machine): **likely-binary**, wave +3.340% at 49.8σ. The statistic is arithmetically real — recomputed independently on this fold it returns +3.347% at 49.7σ (medians) — but the *interpretation* as an ellipsoidal wave of a 1.3038 d binary is a misread of the structure. The quadrature windows fall between the dips of the 0.21731 d train (its local maxima) while two of the four shoulder windows fall on train dips. With narrower hand shoulder windows the same statistic returns −2.147% at −46.7σ. Both are hostage to window placement on a structured curve; the binned profile above is the arbiter, and the binary conviction does not need the wave.
- Driver's mechanical verdict (preserved verbatim in the JSON): **LIKELY BINARY (stage-gate kill at c)** — upgraded here to **EB** on the profile evidence, per the documented reclassification pattern.

### Orbit phase (stage d) — acquitted
On-data centres n = 767; boundary fraction 0.203, circular R = 0.053 — no pile-up. The signal is not a spacecraft-orbit systematic.

### Persistence (stage e) + raw-flux tiebreaker — present everywhere, both eras
Module at the fixed ephemeris (cap 20 = all 18 sectors; uncapped run identical — only 18 products exist): 18/18 usable, 18/18 positive, weighted mean **+12.431% ± 0.111% (111.8σ)**, verdict MIXED on a χ² of 3963/17 dof — the per-sector depths genuinely vary by sector group (flattened depths 14.4–20.1% in sectors 31–39, 26.1–30.2% in 61–69, 7.5–22.4% in 87–98; all 18 products are QLP, whose aperture choices differ by era). The honest raw-flux tiebreaker (first product per distinct sector, sector's own out-of-transit mean): **+15.398% ± 0.327% (47.0σ)** over sectors 31–39 and **+8.522% ± 0.066% (128.9σ)** over the 14 sectors ≥ 60; overall +8.791% at 135.7σ. No era confinement, no switch-off — the opposite failure mode from TIC 374912514 earlier tonight. (The two depth scales differ by normalization convention; both are ≫100σ detections of the same train.)

### Duration sanity
At the sweep period, a/R* = 5.89 and the maximum central-transit duration is 0.85 h (1.24 h even granting the BLS depth's k = 0.455) vs the 2.376 h BLS box — a 2.8× overshoot, as expected when a box fit stacks a dip train at an alias period. Inside a physical-width window the fold still carries a 13.16% ± 0.10% core: the dips are deep and real; only the planet geometry fails.

### Blend geometry
77 TIC rows within 2′ — a crowded field, hence the flag and contratio 0.197. The only neighbour that matters is **TIC 167367404** (26.9″, Tmag 13.652, 0.55 mag *brighter* than the target). At the TIC contratio-implied dilution it would need an intrinsic eclipse depth of ~128% to fake a 20.7% dip — unphysical; even at full aperture inclusion it would need ~34% eclipses on top of near-total geometry. The QLP-aperture caveat (all sectors QLP; apertures larger than the SPOC-based contratio assumes) keeps the neighbour route from being *pixel*-excluded, but the on-target reading needs no extremes. Centroid/difference imaging was not demanded and remains untested; the species is binary either way.

### Verdict
**EB — a contact / near-contact twin eclipsing binary**, photometric cycle 0.21731 d (orbital period 0.43461 d on the twin reading). Decisive: the fold profile / periodogram (alias structure + EW morphology), the exact reproduction at SDE 94.72 with eclipses in all 18 sectors, and the depth budget against the neighbour. The project-record SDE was real; it was measuring how deep and how regular a contact binary's dip train is, not how planet-like anything is. Untested: centroid/difference imaging; the 0.21731 vs 0.43461 d orbital ambiguity; the weak ~14.4–15.2 d periodogram complex (possible spot modulation of the binary — context only).

Evidence: `vetting_results/167367406.json` (+ `167367406_persistence_cap20.json`, `167367406_persistence_uncapped.json`, `167367406_catalog.json`, `167367406_hand.json`, `167367406_profile.json`). Drivers: `ra100_vet.py`, `ra100_catalog.py`, `ra100_hand.py`, `ra100_profile.py`, `ra100_merge.py`.
