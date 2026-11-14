# Labelled-population TOI run — live extension (F-8)

The offline population (`scripts/toi_population.py`, default) is
the three golden fixtures: TOI-700 c + WASP-126 b (confirmed
planets) and TIC 308851365 (VSX eclipsing binary). The live
extension runs the same harness against MAST downloads, with a
wider labelled population. This doc is the operator's guide.

## Running it live

```bash
.venv/bin/python scripts/toi_population.py --live --out /tmp/toi_population_live.json
```

Live runs download real TESS light curves (tens of MB per star,
cached under lightkurve's cache) and need network. Do NOT run
`--live` in CI — the offline run is the PR gate; the live run is
an operator check (weekly, or before a Phase 2A acceptance).

## The live population

Confirmed planets and dispositioned false positives, from repo
records only (no new labels invented here):

| TIC | Label | Why it is in the population |
|-----|-------|------------------------------|
| 150428135 (TOI-700) | planet | Confirmed multi-planet system; golden fixture |
| 25155310 (WASP-126) | planet | Confirmed hot Jupiter; golden fixture |
| 4206066 (TOI-7930) | planet | Confirmed planet (Pavel Rabtsevich's TOI-7930) |
| 308851365 | fp_eb | VSX eclipsing binary (resolved 2026-11-03); golden fixture |
| 139526205 | fp_blend | S97 blend of the EB on TIC 139524628 at 66.5″ |
| 237911080 | fp_blend | S96 blend of the EB on TIC 237911081 at 63.5″ |
| 344334378 | fp_raw | S97 raw-refuted: signal only in flagged cadences |

**Excluded:** TIC 423498314 (the first live candidate) — it is
UNLABELLED (candidate, not confirmed; leading alternative is a
grazing EB on the RUWE companion). It must never enter a
labelled population until it is dispositioned.

## What changes live

* **Ephemeris:** `--live` runs `hunter._run_pipeline` without
  the fixture seam (real MAST downloads). The star_radius /
  max_sectors per star mirror the offline entries; new stars
  need their own entries in `POPULATION` (star_radius from the
  TIC, max_sectors from the available coverage).
* **rho_star:** the offline entries carry `rho_star_solar` only
  where the fixture meta has it (the EB). Live, query the TIC
  for each star's density (the live golden test does this) and
  fill it in — without it the shape gate runs with no density
  flag, and the EB kill rests on shape + catalogue alone.
* **diffimg / transit_fit / pixel_check:** offline these are
  known gaps (no TESSCut/TPF/per-sector npz). Live, the
  operator supplies natives from the gauntlet tools
  (difference imaging via `gauntlet/diffimg.py`, the formal fit
  via `gauntlet/transit_fit.py`, the pixel check from the TPF)
  — the harness's `run_star` takes natives as built, so wire
  the live natives in there rather than fabricating them.
* **blend:** offline the neighbour is the dip-free control
  (the target flux with in-transit points replaced). Live, use
  the real neighbour light curve (`gauntlet/neighbour_fold.py`)
  — the blend FPs (139526205, 237911080) are in the population
  precisely to prove the blend check kills them.
* **catalogue:** offline the EB's catalogue native is
  hand-set (VSX, period match). Live, query VSX/TOI/PHT for
  each star (the catalogue check in the vetting manual §0).

## Reading the artifact

The artifact JSON (`--out`) has per-star stage statuses and a
`counts` block: planets all-measured-pass, FPs killed, and the
per-stage confusion (`counts.stages`). 2A consumes this shape.
A live run's counts are NOT diffed against the offline baseline
(the populations differ) — compare live runs against each other
over time, and keep the offline baseline for the PR gate.
