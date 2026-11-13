# Archive — one-off work, preserved not deleted

Everything here ran once for a specific star, sweep, or sector. It is
kept for provenance (what was tried, what the evidence was) but is NOT
part of the live pipeline. Nothing in `archive/` is imported by, or
required for, the current code. Do not add new work here — new
one-off scripts go through the same review as any other change, and
live tools belong in `gauntlet/`, `bulk/`, or the repo root.

## Layout

- `reports/` — one-off build/vetting reports (`*_REPORT.md`,
  `*_VETTING.md`, candidate notes, VSX packets). The per-stage build
  reports (`STAGE1_REPORT.md` … `STAGE4_REPORT.md`) hold the test
  evidence for the early pipeline versions.
- `scripts/` — one-off per-star / per-sweep scripts (`bf851_*`,
  `pair_stage*`, `blend_stage*`, `ra100_*`, `sweep4_*`, `sweep5_*`,
  `closing_test_*`, `vet_star*`, VSX helpers). Each script's inputs
  and outputs live in `data/` under matching names where they exist.
- `data/` — evidence files for the archived scripts: fold plots,
  persistence JSONs, blend-check JSONs, VSX cross-check output.
- `bulk-screens/` — completed sector screens, one directory per
  sector: the sector-specific driver/analysis/recalibration scripts,
  the run summaries, and the recalibrated survivor lists.
  - `s0097/`, `s0098/` — closed screens (0 planets each).
  - `s0001-proof/` — the original proof-of-concept run.
  - Sector 96 is NOT here: its screen is live, so
    `bulk/fire_s0096_mac.sh` and `bulk/s96_smoke/` stay in `bulk/`
    until the screen completes.

## Warnings — read before reusing anything here

- `reports/VSX_FILING_PACKET_167367406.md` and
  `data/vsx_167367406_draft.png` are the packet for a VSX draft that
  must NEVER be submitted (TIC 167367406 is a BLEND of TIC 167367400;
  the draft auto-deletes ~2027-01-05). Do not contact VSX about it.
- `reports/CANDIDATE_TIC308851365.md` and the `STAGE*_REPORT.md`
  files describe pipeline versions that have since been fixed
  (notably the coarse-BLS-grid bug and the chi² veto). Do not treat
  their numbers as current.
- Archived scripts may import modules by their old root-level paths
  and may not run as-is from this directory. They are records, not
  maintained tools. If a script needs to run again, promote it to
  `gauntlet/` or `bulk/` first and fix its imports.
