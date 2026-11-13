# VSX Cross-Check Batch — 2026-11-06

Read-only checks (no forms, no submissions, no edits anywhere). Dev approved
2026-11-06 05:19 IST. Structured data: `vsx_crosscheck_2026-11-06.json`.
Drivers: `vsx_crosscheck.py` (pass 1) + `vsx_crosscheck_fix.py` (repair pass).

**Routes.** Identity: astroquery MAST `Catalogs.query_criteria(catalog="TIC",
ID=…)`, returned row's ID verified against the target for all 7 stars.
VSX: VizieR B/vsx was attempted first and **failed from this VM** (proxy drop,
both the votable endpoint and TAPVizieR — the same inaccessibility Jiashuo
mentioned). The check was therefore run on the **VSX website's own
query.votable cone service** (vsx.aavso.org, 30″ cone, separations recomputed
locally). Route validated on a positive control before the batch: a cone on
TIC 308851365 returned exactly its known VSX entry (Gaia DR3
5277232093330484096, ROT, P 0.75629, 15.83–15.91 G), and the service went on
to return real entries at 0.01″, 14.8″ and ~26″ in this batch, so empty cones
are credible. Secondary (only where VSX showed no same-star entry): **Gaia
DR3** — gaia_source cone (counterpart ≤1″ for every star; in all six cases the
DR3 source_id equals the TIC row's GAIA identifier), then
`vari_classifier_result` and `vari_eclipsing_binary`. The Gaia archive was
reached via its TAP sync endpoint over plain HTTPS (astroquery's session
failed SSL through this VM's proxy). A first EB-table pass was discarded and
re-run after a parser heuristic misfire — the re-run confirms every EB-table
result below on clean, empty responses.

**Headline: 6 of 7 stars are absent from VSX — 5 clean new-filing candidates,
plus 1 revision candidate (TIC 149914431, sitting in VSX as ROT with no
period, the exact TIC 308851365 pattern). Zero check failures.**

---

## 1. TIC 167367406 — ABSENT EVERYWHERE CHECKED → new-filing candidate

- **Identity (ID-verified):** RA 99.432026, Dec −67.743881; Tmag 14.205;
  R* 0.389 R☉, Teff 3542 K, contratio 0.197; Gaia G 15.369.
- **Ours:** EW contact binary, orbital P 0.43461 d (photometric cycle
  0.21731 d) — RA100_SWEEP_VETTING.md.
- **VSX:** 0 entries within 30″.
- **Secondary (Gaia DR3):** counterpart 5280333334596470400 @ 0.04″
  (G 15.353). No `vari_classifier_result` row; no `vari_eclipsing_binary` row.
- **Classification:** ABSENT EVERYWHERE CHECKED — new-filing candidate (EW).

## 2. TIC 231124169 — ABSENT EVERYWHERE CHECKED → new-filing candidate

- **Identity (ID-verified):** RA 69.633193, Dec −70.622886; Tmag 13.407;
  R* 0.442 R☉, Teff 3494 K, contratio 0.056; Gaia G 14.572.
- **Ours:** twin EB, true P 2.91396 d, ellipsoidal +0.871% @ 92σ —
  SWEEP2_VETTING_REPORT.md §1.
- **VSX:** 0 entries within 30″.
- **Secondary (Gaia DR3):** counterpart 4654856560096208512 @ 0.56″
  (G 14.552). No classifier row; no EB-table row.
- **Classification:** ABSENT EVERYWHERE CHECKED — new-filing candidate.

## 3. TIC 149975388 — ABSENT EVERYWHERE CHECKED → new-filing candidate

- **Identity (ID-verified):** RA 90.365754, Dec −64.775012; Tmag 14.848;
  R* 0.410 R☉, Teff 3556 K, contratio 0.038; Gaia G 15.983.
- **Ours:** EB, true P 28.38 d (double-period fold; BLS half-period 14.0768 d),
  wave +0.53% @ 17σ — SWEEP_VETTING_REPORT.md §4 (whose stage (e) read
  "Not known. VSX not run" until today).
- **VSX:** 0 entries within 30″.
- **Secondary (Gaia DR3):** counterpart 5477506418344494976 @ 0.92″
  (G 15.962). No classifier row; no EB-table row.
- **Classification:** ABSENT EVERYWHERE CHECKED — new-filing candidate.

## 4. TIC 149914431 — IN VSX, DISAGREES → revision candidate

- **Identity (ID-verified):** RA 88.177372, Dec −65.300448; Tmag 14.636;
  R* 0.498 R☉, Teff 3551 K, contratio 0.119; Gaia G (TIC) 15.73.
- **Ours:** EB, true P 27.45 d (double-period fold; BLS half-period 13.7264 d),
  wave +0.58% @ 23σ — SWEEP_VETTING_REPORT.md §6.
- **VSX: SAME-STAR ENTRY @ 0.01″** — **Gaia DR3 4755920984553548800** (the
  entry's name is the star's own Gaia DR3 ID, identical to the TIC row's GAIA
  identifier; AUID blank on this Gaia-imported entry, numeric OID not exposed
  by the query service). Filed type **ROT**, filed period **none (0.0)**,
  mag range **15.73–15.76 G**, spectral type M, discoverer "Gaia
  collaboration". No other entries within 30″.
- **Secondary:** not run (per protocol — VSX has the star).
- **Classification:** IN VSX, DISAGREES — filed ROT with no period vs ours EB
  @ 27.45 d → **revision candidate**, the same shape as the TIC 308851365
  ROT→EB revision (revid 853367).

## 5. TIC 294671352 — ABSENT EVERYWHERE CHECKED → new-filing candidate

- **Identity (ID-verified):** RA 70.697956, Dec −69.554216; Tmag 14.677;
  R* 0.365 R☉, Teff 3498 K, contratio 0.272; Gaia DR3 4655030622248269696
  (matches the sweep-2 report's pair-check value).
- **Ours:** EB, true P ≈26.25 d (odd/even fold at 26.25450 d; sweep's
  13.1286 d is the half-period alias) — SWEEP2_VETTING_REPORT.md §2.
- **VSX:** 0 entries within 30″.
- **Secondary (Gaia DR3):** counterpart 4655030622248269696 @ 0.97″.
  No classifier row; no EB-table row.
- **Classification:** ABSENT EVERYWHERE CHECKED — new-filing candidate.

## 6. TIC 294782870 — ABSENT EVERYWHERE CHECKED → new-filing candidate

- **Identity (ID-verified):** RA 71.331879, Dec −69.721199; Tmag 14.440;
  R* 0.368 R☉, Teff 3499 K, contratio 0.187.
- **Ours:** EB, true P ≈49.04 d (present/absent alternation at the 49.04 d
  fold; fold-depth caveat on record) — SWEEP2_VETTING_REPORT.md §4.
- **VSX:** no same-star entry. One neighbour within 30″: Gaia DR3
  4655014752334420992 @ 14.82″, type E, P 1.44199 d, 17.72–18.08 G — a
  different star, not a match.
- **Secondary (Gaia DR3):** counterpart 4655013274865673984 @ 0.56″.
  No classifier row; no EB-table row.
- **Classification:** ABSENT EVERYWHERE CHECKED — new-filing candidate.

## 7. TIC 276791802 — ABSENT EVERYWHERE CHECKED → new-filing candidate

- **Identity (ID-verified):** RA 83.159652, Dec −68.331191; Tmag 14.626;
  R* 0.479 R☉, Teff 3529 K, contratio 0.232.
- **Ours:** LIKELY BINARY, true P 27.4587 d, wave +0.211% @ 10.0σ —
  SWEEP4_VETTING_REPORT.md (target 20).
- **VSX:** no same-star entry. Two neighbours within 30″, both type E and
  both different stars: Gaia DR3 4658560333718885376 @ 26.21″ (P 39.65 d,
  19.13–19.49 G) and Gaia DR3 4658560260708534528 @ 26.84″ (P 1.67352 d,
  17.83–18.14 G).
- **Secondary (Gaia DR3):** counterpart 4658560333740278656 @ 0.83″.
  No classifier row; no EB-table row.
- **Classification:** ABSENT EVERYWHERE CHECKED — new-filing candidate
  (with the standing grade caveat: this one is LIKELY BINARY, one notch
  below the firmest verdicts).

---

## Brief-vs-report reconciliation

- All seven periods/figures in the brief were confirmed verbatim against the
  local reports (2.91396 d / +0.871% @ 92σ; 26.25450 d fold; 49.04 d
  alternation + caveat; 28.38 d / 27.45 d + waves; 27.4587 d / +0.211%
  @ 10.0σ; 0.43461 d orbital for 167367406). No numeric discrepancies.
- One wording nuance: the brief labels targets 2–6 "EB", while their reports
  carry the project verdict stamp **LIKELY BINARY** (the sweep-2 summary
  counts them among its "4 eclipsing binaries", so the species agrees; only
  the grade word differs). Target 7's brief grade (LIKELY BINARY, "one grade
  below firm") matches its report.

## Safety

Standalone scripts only; `hunter.py` never imported; no server started;
nothing submitted or edited anywhere. `data/hunter.db` and `discoveries.csv`
md5-verified unchanged at the end of the batch (see JSON header /
run log): db `33b70438b3669f9c313b510488d20d48`, csv
`2c8abaae5be0456af6a7effa8a22b6ff`.
