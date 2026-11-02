# Candidate Dossier — TIC 308851365

**Signal found by:** Debashish Sarangi, using Exoplanet Hunter (TESS/BLS pipeline)
**First detected:** 2026-11-02 · **Dossier compiled:** 2026-11-03
**Status:** Unconfirmed candidate. Not a TOI, not a community candidate, not a
catalogued eclipsing binary — no prior record in any archive checked (below).

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

## 7. Suggested Planet Hunters Talk post

> **TIC 308851365 — strong unflagged 0.757 d signal, SDE up to 66**
>
> Found with a custom TESS/BLS pipeline. The signal repeats at P = 0.75677 d
> (T0 = 1325.483 BTJD), depth ≈ 1.2 %, and strengthens with data
> (SDE 16 → 47 → 66 across 2 → 12 sectors). Odd/even test: odd 1.31 % vs even
> 1.26 % — planet-like. No TOI, no CTOI, not in the TESS EB catalog, nothing
> on ExoFOP. Caveat: the fold is a smooth wide bowl and the duration (~6 h)
> is long for the period, so EB/variability is very much on the table.
> Host is a 0.93 R☉, 3959 K dwarf, Tmag 14.94. Would value the community's
> eyes — candidate or convincing fake?
