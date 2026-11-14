# Patch Study — RA 70, Dec −70 (1.0° cone): how picked-over is it?

Measured 2026-11-04 (early hours IST), reproducing the exact sweep configuration:
cone 1.0° on (70, −70), screen Tmag 11.5–15, star radius 0.2–0.5 R☉ (finite radii only),
sector cap 20. All counts below are per-source and distinguish *observed* (data exists)
from *searched/flagged* (someone or some pipeline actually marked the star).

## His screened layer

- **32 stars** pass the screen (the sweep's Max Stars = 25 means the run works through
  the first 25 of these; 7 more sit behind them in the same cone).
- Full list (TIC, Tmag, R☉): 29926460 (14.66, 0.437), 29983149 (13.52, 0.490),
  139370922 (14.77, 0.274), 139371053 (12.29, 0.478), 231073112 (13.38, 0.370),
  231077400 (14.19, 0.359), 231077422 (13.20, 0.333), 231079599 (14.20, 0.389),
  231079694 (14.92, 0.414), 231079765 (14.66, 0.490), 231087046 (13.09, 0.457),
  231092486 (14.38, 0.484), 231095842 (14.16, 0.495), 231096112 (14.96, 0.444),
  231096116 (14.11, 0.242), 231124169 (13.42, 0.414), 231124440 (14.79, 0.447),
  294626348 (14.65, 0.487), 294626668 (13.44, 0.272), 294665246 (14.04, 0.429),
  294671352 (14.29, 0.383), 294671640 (12.40, 0.284), 294747564 (14.21, 0.356),
  294750075 (13.99, 0.292), 294751386 (14.77, 0.310), 294751586 (14.38, 0.498),
  294782870 (13.86, 0.392), 294923560 (14.70, 0.418), 295071580 (13.60, 0.418),
  370103015 (14.30, 0.298), 370114901 (13.68, 0.459), 370116215 (14.75, 0.446).

## Professionals — NASA Exoplanet Archive (TAP)

- **Of his 32 screened TICs: 0 appear in the TOI table; 0 appear in the
  confirmed-planets (PS) table.** Not one of his dwarfs has ever been flagged as a
  threshold-crossing event by the professional pipelines, let alone confirmed.
- **Patch-wide context (any brightness, same 1.0° cone): exactly 1 TOI and 1 confirmed
  planet** — TOI 2238.01 around TIC 231077395 (TFOPWG disposition CP), planet
  **TOI-2238 b**. That host is **not** among his 32: the one star in this patch the
  professional system ever picked up sits outside his faint-small-dwarf screen.
  In other words, the professionals' entire footprint in this cone is a single
  brighter system; his layer underneath it is untouched by them.

## Known variables — AAVSO VSX (positional cone, tiled census)

- **472 catalogued variable stars** sit inside the same 1° cone (a dense field — the
  LMC shoulder; mostly Gaia-collaboration classifications: RR Lyrae, eclipsing
  binaries, long-period and rotating variables). The patch is *catalogued*, heavily —
  for bright variable-star science.
- **Overlap with his 32: zero.** No match by Gaia DR3 ID, and no VSX entry within
  10″ of any screened star (nearest neighbour: 54.8″ from TIC 294626668).
  None of his dwarfs is a known variable.

## Amateurs — Planet Hunters / Zooniverse already-known check

- Sample of **8 of the 32** screened TICs, spread across the list
  (370103015, 231096112, 294782870, 231079599, 295071580, 370114901, 294747564,
  29983149), run through the app's Zooniverse already-known check:
  **0 flagged, 8 clean.** (Sample, not the full 32 — but a unanimous one.)
  Consistent with how Planet Hunters works: its subject stream is built from
  pre-selected target lists that barely reach this faint FFI dwarf layer at all.

## Observed vs studied

- **Observed: richly.** Distinct TESS sectors of light-curve data available per star
  (app's own search route, 5-star sample across the list): **21, 22, 36, 42, 43**
  sectors (median ≈ 36; up to 96 product files counting cadences/authors). This is
  the southern continuous-viewing zone doing its job — the satellite has stared at
  these stars for years, which is exactly why the sweep can cap at 20 sectors and
  still leave data in reserve.
- **Studied: barely.** All that photometry exists, but at *his* layer — faint
  (Tmag 11.5–15) small dwarfs (0.2–0.5 R☉) — nobody has flagged, catalogued, or
  claimed any of the 32: no TOIs, no confirmed planets, no variable-star entries,
  no citizen-science flags in the sample.

## Bottom line

- **By professionals:** the patch has been *processed* (the data products exist and
  the TOI search nominally covers the field), but its yield here is exactly one
  brighter system, TOI-2238 b. His 32 faint dwarfs: **0% flagged**.
- **By amateurs:** effectively **unstudied** — 0/8 sampled flags, and the
  citizen-science pipeline largely never shows volunteers stars like these.
- The honest one-liner: **this layer of this patch is observed but unexamined** —
  deep data, no pickers. Whatever his sweep finds here, the prior claim rate on
  these exact stars is, by every catalog checked, zero.
