# The FIRST Gemini app — commit 1e3c6a97 "Create app.py", 2026-11-01 20:20 IST
## (the one Dev means by "the very fast app Gemini build, when QA was added")
Read in full 2026-11-02 from git history. 8,307 bytes, ~230 lines, Streamlit.
Supersedes the focus of GEMINI_APP_ANALYSIS.md (that covered v2.1).

## What it was: a metal detector, not a workstation
TWO tabs only:

### Tab 1 — Deep Space Scanner (the whole point)
- 4 inputs, one row, all pre-filled: RA 124.456, Dec -67.568, radius 0.10°,
  max stars 20. ONE button: "Initialize Scan".
- Scan logic (all expert choices HARDCODED — zero knobs):
  - TIC catalog cone query → filter to faint dwarfs (Tmag 13.5–15.4, rad 0.2–1.5).
  - **Zooniverse check first**: is_already_known_online() queries
    talk.zooniverse.org (Planet Hunters TESS, project-5733) for the TIC;
    already-discussed stars are SKIPPED before any download ("Already known
    on Zooniverse, skipping").
  - One preferred pipeline with >=2 sectors (TESS-SPOC → QLP → SPOC → TGLC);
    fewer = skip. Download, stitch, flatten window 71 (fixed).
  - BLS fixed recipe: 0.5–15 d, 20,000 grid, 10 durations.
  - **Alarm bar SDE >= 11.0** (strict). Hit → red "NEW UNFLAGGED SIGNAL"
    banner (period, ~planet size) + ONE phase-fold zoom plot.
  - Everything else silently skipped; one progress bar + "[n/N] Querying TIC…"
    status line; ends with st.balloons().
- No charts for non-hits, no metrics grid, no history, no plate download.

### Tab 2 — QA Validation Lab (a DIFFERENT QA than v2.1/ours)
- Odd/Even test: enter TIC + a discovered period → fold at 2x period, plot
  odd vs even transit dips side by side to rule out eclipsing binaries.
- 2 inputs, 1 button, 1 chart. It's a candidate-fakery check, not a
  pipeline benchmark.

## Why it was genuinely fast (not just felt fast)
1. It did LESS work per star: one pipeline, >=2 sectors, small fixed BLS grid.
2. It skipped aggressively BEFORE spending downloads (Zooniverse check,
   sector-count check), and skipped silently.
3. High alarm bar (SDE 11) + hits-only display = the screen only ever shows
   surprises; no rendering cost for noise.
4. Single-purpose loop: point → scan → surface. No modes-within-modes.

## Contrast
- v2.1 (and our current build): diagnostic workstation — analyze ANY star in
  depth, all sectors, 4 charts, full knobs. Powerful, but a cockpit (Dev's
  2026-11-02 complaint).
- v1: discovery machine with opinions. The backend we built (job queue,
  hits-only logging SDE>=8.5, sweep→Observatory routing) already rhymes with
  v1; missing pieces worth importing: (a) v1 Scanner as the SIMPLE front door,
  (b) Zooniverse already-known check in sweeps, (c) Odd/Even QA test as a
  fourth tool, (d) hardcoded sane recipes behind the simple door.
