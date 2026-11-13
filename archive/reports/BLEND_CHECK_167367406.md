# BLEND CHECK — TIC 167367406 vs ASASSN-V J063735.95-674407.3

**Question:** which star owns the EW signal at P = 0.43461343 d — TIC 167367406
(the RA100 "discovery", VSX new-star draft saved) or the known ASAS-SN variable
53.6″ away whose VSX period matches to all six digits?

## VERDICT: BLEND

**The signal belongs to TIC 167367400 = ASASSN-V J063735.95-674407.3.**
TIC 167367406's light curve is that star's eclipses diluted inside the large
QLP aperture. Decisive stages: **3 (difference imaging)** and **4 (aperture
test)**, corroborated by 2 and 5. Consequences: the saved VSX draft for
TIC 167367406 must be **withdrawn, not submitted**; the "discovery" reduces to
a re-detection of a known variable in a blended aperture. (The RA100 vetting
classified the *signal* correctly — EW contact binary — but attributed it to
the wrong star, because its blend test used the TIC contratio, which describes
a small nominal aperture, not the QLP aperture the light curve came from, and
centroid imaging was deferred.)

## Stage 1 — Identify the ASASSN-V star

Cone search (≤10″) on the VSX position (RA 06 37 35.95, Dec −67 44 07.3)
returns exactly one TIC star, **0.16″** from the filed position:

| | TIC 167367406 (target) | TIC 167367400 (ASASSN-V) |
|---|---|---|
| Gaia DR3 | 5280333334596470400 | 5280333540754898304 |
| RA / Dec (deg) | 99.4320261, −67.7438807 | 99.3997400, −67.7353198 |
| Tmag | 14.2054 | 13.4671 |
| V (TIC) | 16.235 | 14.416 |
| Gaia G | 15.3689 | 13.9315 |
| Teff / R* | 3542 K / 0.389 R☉ | 5775 K / 1.568 R☉ |
| 2MASS | 06374379-6744390 | 06373595-6744070 |

Separation 53.74″, PA 305° (WNW), = 2.55 TESS pixels. ASASSN-V's filed V range
(13.89–14.61) brackets TIC 167367400's V = 14.416; the target's V = 16.235 is
1.6–2.3 mag fainter than the entire ASAS-SN range — ASAS-SN's photometry
cannot have been measuring the target. Within 65″ of the target there are 26
TIC stars; only two besides the target are brighter than Tmag 14.3:
TIC 167367404 (26.9″, Tmag 13.652 — the neighbour the original vetting
cleared) and TIC 167367400 itself. (Gaia TAP cones failed from this VM —
SSL/503; identification rests on the TIC rows' GAIA cross-ID fields.)

## Stage 2 — Per-star QLP folds (same 18 sectors, packet estimator)

| | TIC 167367406 | TIC 167367400 |
|---|---|---|
| Window depths I / II | 27.85% / 27.63% | **42.02% / 42.05%** |
| Vertex depths I / II | 33.27% / 32.80% | **50.07% / 49.94%** |
| Binned amplitude | 0.448 mag | **0.768 mag** |

The neighbour's own aperture shows the EW at ~1.5× the target's depth, and its
0.768 mag TESS amplitude matches ASAS-SN's catalogued 0.72 mag V amplitude.
Per-sector Min-I depths of the two stars correlate at **r = 0.93** with a
constant ratio 0.68 — the target's signal is a scaled copy of the neighbour's,
sector by sector.

## Stage 3 — Difference imaging (TESSCut, decisive)

No SPOC TPFs exist for this target; TESSCut FFI cutouts (13×13 px, centred on
the target) were used instead — same pixel test. Median out-of-eclipse minus
in-eclipse (Min I) images, flux-weighted centroid of the difference:

| Sector | Centroid → target | Centroid → neighbour | Peak → target / neighbour |
|---|---|---|---|
| 31 | 54.7″ | **1.2″** | 52.3″ / 3.7″ |
| 39 | 49.5″ | **4.3″** | 64.4″ / 11.9″ |
| 63 | 53.8″ | **2.7″** | 61.5″ / 7.9″ |
| 67 | 52.6″ | **6.8″** | 54.5″ / 7.4″ |
| 88 | 56.2″ | **2.9″** | 58.7″ / 5.0″ |
| 96 | 52.1″ | **4.4″** | 52.3″ / 9.3″ |

In all six sectors (three observing eras) the variable source sits **on
TIC 167367400** (mean offset 3.7″, vs 53.2″ from the target). The total-image
in/out centroid shift is small (0.4–1.2″) because constant field stars
dominate the 13×13 frame — the difference image, which cancels them, is the
localiser, and it is unanimous.

## Stage 4 — Aperture test (same cutouts)

Window depths (Min I / Min II) by aperture around the **target**:

| Sector | Tight r≤0.75 px | Standard r≤2.0 px | Neighbour-centred r≤1.5 px |
|---|---|---|---|
| 31 | 1.20 / 1.12% | 6.47 / 6.15% | 45.2 / 43.1% |
| 39 | 2.35 / 2.26% | 9.36 / 9.01% | 38.0 / 36.7% |
| 63 | 1.33 / 1.15% | 6.30 / 6.11% | 37.1 / 36.0% |
| 67 | 2.70 / 2.81% | 8.64 / 8.59% | 39.6 / 39.3% |
| 88 | 0.22 / 0.27% | 8.11 / 8.74% | 44.0 / 46.9% |
| 96 | 1.49 / 1.30% | 4.66 / 4.19% | 35.3 / 34.8% |

On the target's own central pixel the "32% eclipse" collapses to **0.2–2.8%**
(residual = the neighbour's PSF wings at 2.55 px). Depth grows monotonically
as the aperture reaches toward the neighbour, and a neighbour-centred
aperture recovers the full EW. QLP's 27.9% sits on the same sequence — its
aperture is simply the largest of the set.

## Stage 5 — Dilution arithmetic

- TESS flux ratio F(167367400)/F(167367406) = 10^0.4·(14.2054−13.4671) = **1.97**.
- Neighbour-as-source: to produce the target's 27.85% window depth from a
  42.02% intrinsic signal, the neighbour must supply **66.3%** of the target's
  QLP-aperture flux (vertex basis gives the identical 33.27/50.07 = 0.664).
  That requires essentially all of the neighbour's light inside the aperture —
  true for QLP's multi-pixel aperture with the neighbour 2.55 px away, and
  exactly what stages 3–4 show geometrically. **Consistent.**
- Target-as-source: the neighbour's aperture would need the target's eclipses
  at 42% despite the target contributing at most F_T/(F_N+F_T) = 33.6% of that
  aperture's light even at 100% capture → required intrinsic depth **≥125%**,
  physically impossible (the same wall the original vetting correctly derived
  for the 26.9″ neighbour). **Ruled out.**
- The TIC contratio of 0.197 for the target describes a small nominal
  aperture; it never described the QLP photometry that produced the sweep hit,
  the vetting depths, or the filing packet. That mismatch is the root cause of
  the misattribution.

## Failed / substituted items

- Gaia DR3 cone queries: failed from this VM (astroquery TAP SSL error;
  direct TAP sync HTTP 503). Identification used the TIC GAIA cross-IDs.
- SPOC TPFs: none exist for TIC 167367406 → TESSCut FFI cutouts substituted
  for stages 3–4 (same difference-imaging test).
- hunter.py never imported; `data/hunter.db` md5
  33b70438b3669f9c313b510488d20d48 and `discoveries.csv` md5
  2c8abaae5be0456af6a7effa8a22b6ff verified byte-identical after the run.
  Nothing on VSX was touched; the saved draft is exactly as it was.

Evidence: `blend_check_167367406.json` (merged stages 1–5),
`blend_check_stage1.json`, `blend_check_stage2.json`,
`blend_check_stage3.json`; drivers `blend_stage1_identify.py`,
`blend_stage1_gaia_fix.py` (unused, Gaia route failed), `blend_stage2_folds.py`,
`blend_stage3_diffimg.py`.
