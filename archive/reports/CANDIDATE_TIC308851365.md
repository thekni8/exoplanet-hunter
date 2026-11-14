# Candidate Dossier — TIC 308851365

**Signal found by:** Debashish Sarangi, using Exoplanet Hunter (TESS/BLS pipeline)
**First detected:** 2026-11-02 · **Dossier compiled:** 2026-11-03
**Status:** RESOLVED 2026-11-03 — **eclipsing binary** (double-period fold
test, §8). Not a planet. Still a genuine discovery: no prior record in any
archive checked (ExoFOP, Exoplanet Archive, Villanova TESS EB catalog).

---

## 1. Target

| | |
|---|---|
| TIC ID | 308851365 |
| Also known as | 2MASS J08101571-6333293 · Gaia DR3 5277232093330484096 · UCAC4 133-013725 · WISE J081015.69-633329.2 |
| RA / Dec (ICRS) | 122.5655° / −63.5582° (08:10:15.7, −63:33:29) |
| TESS magnitude | 14.94 |
| Star (TIC catalog) | Radius 0.931 R☉ · Mass 0.62 M☉ · Teff 3959 K · logg 4.29 — a cool K/M dwarf |

## 2. The signal (all values from real TESS data, BLS period search)

| Quantity | Value | Source run |
|---|---|---|
| Period | **0.75677 d** (fits across runs: 0.75638 – 0.75873 d) | 2-sector, 12-sector, odd/even fits — mutually consistent |
| Epoch T0 | 1325.483 BTJD (= BJD 2458325.483) | 12-sector BLS fit |
| Depth | **≈ 1.2 %** (12-sector fit: 1.218 %) | BLS |
| Duration | 5.98 h (0.249 d) | BLS — see caveats |
| Detection strength (SDE) | 16.1 (2 sectors) → 46.6 (12-sector cap, 7 usable) → **66.2** (full 12-sector run) | grows with data, as a real signal should |
| Planet radius (if planet) | ≈ **11 R⊕** (depth × true stellar radius 0.931 R☉); pipeline plate values 9.4 – 12.0 R⊕ depending on assumed host radius | see caveats |

## 3. Evidence log

| Run | Data | Result |
|---|---|---|
| 2-sector analysis | 2 sectors | P = 0.75677 d, SDE 16.1, Rp ≈ 10.4 R⊕ |
| 12-sector analysis (Pingu, fixed engine) | 12 requested, 7 usable* | P = 0.75873 d, SDE 46.6, depth 1.218 %, 7,181 points |
| 12-sector analysis (discoverer) | 12 sectors | P = 0.75677 d, **SDE 66.2**, Rp ≈ 9.4 R⊕ |
| Odd/even test, 12 sectors | fold at 2 × P | odd dips 1.312 % vs even dips 1.260 % — 4 % apart → **planet-like** |
| Odd/even test, 2 sectors | fold at 2 × P | 0.756 % vs 0.886 % → **planet-like** |

\* Five HLSP t16 FFI products for this target are truncated at the archive
itself (every fresh download is exactly 322,560 bytes and unreadable, verified
from two independent machines). The engine skipped them and completed on the
remaining sectors. SPOC products are unaffected.

## 4. Vetting already done (2026-11-03)

- **Odd/even eclipsing-binary check:** PASS (planet-like) at two data depths.
- **ExoFOP:** TOIs 0 · Community Planet Candidates 0 · Confirmed planets: none.
- **NASA Exoplanet Archive (TOI table):** no entry for this TIC.
- **TESS Eclipsing Binary Catalog (Villanova):** not in the catalog.
- **Zooniverse / Planet Hunters Talk:** no discussion found (scanner's
  already-known check returns nothing for this TIC).

## 5. Honest caveats — read before citing

1. **Fold shape.** The phase-folded dip is a smooth, wide bowl rather than the
   flat-bottomed, steep-sided profile of a textbook planetary transit.
2. **Duration is long.** Measured ≈ 6 h is ~33 % of the orbital period; a
   central planetary transit of this star at this period should last ≈ 1.8 h.
   A grazing geometry, an eclipsing binary, or rotational/variable-star
   modulation remain possible.
3. **Odd/even has a blind spot.** A binary of two near-identical stars
   produces near-equal alternate eclipses and can pass the odd/even test.
4. **Pipeline calibration.** This pipeline under-recovers transit depth on
   its WASP-126 b benchmark (0.204 % vs 0.940 % catalog), so depths and radii
   here may be biased low; the period recovery, by contrast, is verified
   accurate to ~0.25 % on the same benchmark.
5. Nothing here is a confirmed planet. This dossier is a *candidate* record:
   a strong, repeating, unflagged signal that merits community vetting.

## 6. Where this goes next

- **Planet Hunters TESS (Zooniverse Talk, project 5733):** post the TIC ID,
  period and this dossier's summary — the community vets unflagged signals
  exactly like this one. (Suggested post text in §7.)
- **ExoFOP Community TOI (CTOI):** with an ExoFOP account, the target page
  (exofop.ipac.caltech.edu/tess/target.php?id=308851365) accepts community
  candidate submissions and follow-up observations; the §2 table maps 1-to-1
  onto the requested fields (period, epoch, duration, depth).

## 7. Planet Hunters Talk post (as filed)

> **New unflagged eclipsing binary: TIC 308851365 (P = 1.513 d)**
>
> Found with a custom TESS/BLS pipeline, where it first appeared as a
> planet candidate at the half-period alias 0.75677 d (SDE up to 66).
> Odd/even test passed it as "planet-like" — but our own double-period fold
> killed it: at the true period 1.51277 d there are two equal eclipses
> (1.13 % / 1.08 %) plus a +1.1 % ellipsoidal brightening at both
> quadratures (37σ) — twin stars, tidally distorted. No TOI, no CTOI, not
> in the TESS EB catalog, nothing on ExoFOP. Posting for the record, and
> filing with VSX as a new variable star. Full dossier:
> github.com/thekni8/exoplanet-hunter (CANDIDATE_TIC308851365.md)

## 8. Resolution — the double-period fold test (2026-11-03)

The odd/even test cannot distinguish a planet at P from twin stars at 2P.
So the raw (unflattened) light curve was folded at 2P and the out-of-eclipse
light measured in windows:

| Quantity (fold at 1.51277 d) | Value |
|---|---|
| Refined orbital period | **1.51277 d** |
| Primary eclipse epoch | 1326.279 BTJD (BJD 2458326.279) |
| Eclipse I median flux | 0.9887 (depth ≈ 1.13 %) |
| Eclipse II median flux | 0.9892 (depth ≈ 1.08 %) |
| Quadrature median flux (phases 0.25 / 0.75) | **1.0114** |
| Shoulder median flux | 1.0005 |
| **Ellipsoidal amplitude (quad − shoulder)** | **+1.09 %, at 37σ** |

Verdict: the star brightens by ~1 % twice per orbit, in step with the
eclipses — the signature of two tidally distorted stars presenting their
long sides at quadrature. The smooth "bowl" in the 0.757 d fold was this
wave all along. Classification: **eclipsing binary, P = 1.51277 d**, most
likely a close EB/EW-type system of two similar stars. The SDE 66 signal
was real — it was just two suns, not a planet.

## 9. VSX submission packet (AAVSO International Variable Star Index)

| Field | Value |
|---|---|
| Discoverer | Debashish Sarangi |
| Identifiers | TIC 308851365 · 2MASS J08101571-6333293 · Gaia DR3 5277232093330484096 · UCAC4 133-013725 |
| RA / Dec | 08 10 15.69 / −63 33 29.3 |
| Type | E (eclipsing binary; EB/EW-like morphology — equal minima, continuous ellipsoidal variation) |
| Period | 1.51277 d |
| Epoch of primary minimum | BJD 2458326.279 |
| Max magnitude | 14.94 (TESS) |
| Min I / Min II | ≈ 14.95 / ≈ 14.95 (TESS; Δ ≈ 0.012 mag) |
| Remarks | Discovered in TESS data (sectors incl. 1, 11–13) with a custom BLS pipeline; first detected at the 0.75677 d half-period alias (SDE 66.2); double-period fold shows equal minima + 1.1 % ellipsoidal modulation (37σ). Not in the Villanova TESS EB catalog, ExoFOP, or the NASA Exoplanet Archive as of 2026-11-03. Dossier: github.com/thekni8/exoplanet-hunter |

## 10. Outcome (2026-11-03)

- **Planet Hunters Talk:** discovery posted and live —
  https://www.zooniverse.org/projects/nora-dot-eisner/planet-hunters-tess/talk/2110/4170913
  — with a correction comment noting the pre-existing VSX ROT entry.
- **VSX:** a spot check before filing found the star already in VSX as
  **Gaia DR3 5277232093330484096** (OID 3714428), classified ROT at
  0.75629 d by the Gaia collaboration. Instead of a duplicate new-star
  entry, a **revision** was filed by Debashish Sarangi: ROT → EB, period
  1.51277 d, epoch 2458326.279, TIC/2MASS/UCAC4 identifiers added, TESS
  photometry in remarks, Gaia G magnitudes retained, and the double-period
  fold plot (`double_period_fold_308851365.png`) attached as supporting
  evidence. **Submitted 2026-11-03 00:12 UTC — staged pending moderator
  review (confirmation revid 853367).** The live entry remains ROT until
  the moderators promote the revision.
