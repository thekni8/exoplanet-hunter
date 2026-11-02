# How Gemini's app.py (v2.1, Streamlit) actually worked — read 2026-11-02 from git history (commit fceaf7e, pre-deletion)

Dev asked Pingu to study it ("the very fast app Gemini build") after finding the
React UI overwhelming. Findings:

## The interaction model (why it felt simple)
- One page, 3 modes in a sidebar radio. No separate screens to learn.
- **Progressive disclosure everywhere:**
  - "Download ALL sectors" checkbox default ON; the sector-cap slider only
    EXISTS if you untick it.
  - Min/max period hidden inside a collapsed expander ("Orbital Period
    Exploration Window", starts closed).
  - BLS grid = 4-preset select-slider (5k/10k/25k/50k), default 25k. No free numbers.
- Observatory main area = **2 inputs only**: TIC ID (pre-filled 322307342 =
  TOI-114) and host radius (pre-filled 1.20), plus ONE primary button.
- QA tab = one-click cards: "Load TIC" writes TIC **and the correct star radius**
  into session state; user switches tab and presses Run. Cards carry plain-text
  name/class/known period/size/description.
- Sweeper: RA/Dec pre-filled (83.82, -5.39 — Orion), all filters pre-set to
  sensible ranges, max 8 stars default, one Launch button. "Route to
  Observatory" carried TIC + real star radius across.
- Feedback: ONE progress bar (10/25/50/65/80/100) with plain-English status
  lines, then 5 big metric cards (SDE card carries a verdict delta:
  "Strong Transit" / "Marginal / Noise"), 4 charts, 300-DPI plate download.

## Why it FELT fast (honest)
- The math is the same engine family (lightkurve + astropy BLS); our build
  measured ~25–36 s for a 2-sector target. Gemini's was NOT faster at computing.
- It felt fast because: zero decisions before the button; progress narrated in
  big friendly steps; results render progressively on the SAME page (no
  navigation, no job polling UI, no raw engine log).
- It was actually SLOWER on repeats: it purged the lightkurve cache before
  every run, so every run re-downloaded from MAST.
- Its real limits: Streamlit Cloud 1 GB RAM (why it died), no job queue, no
  history, sweep BLS fixed at 8k grid / 0.5–15 d, logs every sweep target.

## What Stage 4 should import (keeping our stronger backend)
1. Simple mode = TIC box (pre-filled) + Run button. Nothing else visible.
2. All knobs behind one Advanced switch; sector cap only when "All" is off;
   period window collapsed; BLS as 4 presets, not a free slider.
3. Famous-target cards that LOAD (TIC + correct radius) into Observatory —
   our QA cards currently only display; Sweeper routing already works.
4. Friendly progress: bar + plain-English steps in simple mode; raw log only
   in Advanced.
5. Results with verdicts in words ("Strong signal" / "Probably noise") next
   to the numbers.
6. Sweeper pre-filled with the Orion field + sane filters, one Launch button.
