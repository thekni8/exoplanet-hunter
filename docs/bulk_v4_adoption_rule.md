# bulk_v4 adoption rule (P3-11) — PRE-REGISTERED

**Status: PRE-REGISTERED.** This rule was written and committed
**before** the P3-11 replay ran. It states, in advance, what loss
is acceptable and what is not, so the replay cannot be tuned to a
preferred answer (FOLLOWUP_BRIEF.md P3-11; Claude's rule). The
commit timestamp of this file is the pre-registration proof: any
replay result quoted against this rule must come from a run dated
after this commit.

**No threshold is chosen tonight.** The replay (P3-11) measures
reduction + per-class losses. The adoption decision waits for the
P3-10 injection campaign's loss measurement in the 1–2-event
regime. Nothing in this file adopts a gate, a bar, or a cut.

## 1. The WASP-29b standard (hard rule, all candidate classes)

**Any candidate gate that drops a known planet is REJECTED, not
tuned around.** The gate is not re-cut, re-scoped, or given an
exception list to rescue the planet — it fails the rule and is
recorded as RULE-REJECTED.

"Zero losses among the 11 known planets" is **necessary but NOT
sufficient** (Claude): all 11 are strong signals (the 10 present
in the S96 rescore survivors have SDE 16.7–59.2, ≥4 events each).
A gate can pass all 11 and still eat the weak-planet population
the pipeline exists to find. That is what §2 guards.

Known-planet class (11): the 9 recovered TOIs (TICs 382602147,
229111835, 389753172, 27966179, 349410350, 300604770, 209310912,
399571743, 12999193) + WASP-29b (TIC 183537452) + TOI-700 c
(TIC 150428135).

**Class coverage in the replay data (recorded in advance):** the
replay runs against the committed S96 bulk_v3 rescore
(`rescore_v3_s0096.jsonl`, 4,692 survivors). TOI-700 c
(P 16.05 d) is **not** a survivor in that single-sector rescore,
so the replay's known-planet class is the **10 present**; the
absence is recorded in the replay results, not hidden, and the
campaign (§2) must cover TOI-700-c-like cases (long period,
1–2 events) for the loss bar to mean anything. The 18 v2-subset
flagged-cadence artifacts are **gone under v3** (not among the
4,692 rows), so there is no artifact class to measure
per-class losses on — losses are measured on the classes present.

Per-class loss classes measured by the replay:

| Class | n in rescore survivors | Source |
|---|---|---|
| Known planets | 10 (of 11; TOI-700 c absent) | 9 TOI recoveries + WASP-29b |
| Gauntlet EBs | 36 | rescore-v3 gauntlet ledger: 35 "KILLED — eclipsing binary" + 1 "KILLED — EB blend" |
| Gauntlet refuted-other | 211 | 208 other refuted + 3 P3-5 closures (150246959, 55387764, 149445580) |

Limitation (recorded in advance): gauntlet labels cover only the
256 NEW tier-A leads. Tier-B rows carry no gauntlet labels, so
"refuted" losses are measured on tier-A rows only; a gate's
tier-B removals are reported as counts, never as labelled
false-positive removals. And the 256 were a selected top-SDE
sample, not a random sample (P3-6 selection-bias caveat) — the
replay's per-class numbers describe the replay, not the
pipeline's false-positive rate.

## 2. The injection-recovery loss bar (measured by P3-10)

**Maximum acceptable injection-recovery loss in the 1–2-event
regime: 5%.** A candidate gate is adoptable only if, on the
P3-10 campaign's tier-B-regime injections (sub-1% depths,
P ∼ LogUniform(0.5, 15) d, 1–2 observed events):

- the point-estimate loss is **≤ 5%** (recovery ≥ 95%), **and**
- the 95% Wilson-interval upper bound on the loss is **≤ 10%**,
- measured on **n ≥ 200** injections in the 1–2-event regime.

If n < 200, or the upper bound exceeds 10%, the measurement is
**inconclusive, not a pass** — the gate stays UNDECIDED and no
adoption follows from it.

The bar applies **per candidate gate individually and to the
adopted combination as a whole** (losses compound: two gates
each losing 4% can lose ~8% together). The combination's loss
is measured on the same campaign data, not assumed from the
parts.

### Why 5% (reasoning, recorded before the measurement)

1. **The 1–2-event regime is the discovery edge.** Single-sector
   data gives a long-period planet 1–2 events; tier B is where
   an undiscovered warm planet hides. A gate that eats more
   than 1 in 20 of those trades the pipeline's discovery edge
   for queue hygiene.
2. **The trade is favourable at 5%.** Tier B is ~92% low-SNR
   residue. A gate removing even 20–30% of tier B at ≤5%
   planet loss removes residue at ≥4:1 over planets. A 10%
   bar would let a gate lose 1 in 10 weak planets for the
   same hygiene gain — that fails the WASP-29b standard's
   spirit, since the 11 known planets cannot guard the weak
   regime (all 11 are strong).
3. **Measurability.** At n = 200, a 5% loss has a 95% Wilson
   interval of roughly 2.5–9.0% — the bar is resolvable
   without an impractically large campaign, and the
   upper-bound ≤10% condition keeps a small-n fluke from
   passing. The campaign's ~10³ positives should put several
   hundred injections in the 1–2-event regime (single-sector
   coverage makes most long-period injections 1–2-event).
4. **The bar is on the regime the gate acts on.** Gates that
   act only on tier B are measured on tier-B-regime
   injections (sub-1% depths, per the tier-B cap — the
   committed 2% trial signal is above the cap and does not
   price tier B). A gate measured on the wrong depth regime
   has not been measured.

## 3. Candidate gates (definitions fixed before the replay)

All constants are reused from the frozen bulk_v3 profile
(`calibration/bulk_v3.yaml`) — no new threshold is invented
for the replay. The replay reports each candidate's survivor
reduction (counts + % by tier) **and** its per-class losses
(§1 classes) — never reduction alone.

| # | Candidate | Definition (pass = kept) |
|---|---|---|
| SDE-8.0 | SDE bar 8.0 | `sde >= 8.0` |
| SDE-9.0 | SDE bar 9.0 | `sde >= 9.0` |
| SDE-10.0 | SDE bar 10.0 | `sde >= 10.0` |
| TWO-STRONG | Two-event strength | rows with `n_events == 2` must have `n_strong_events >= 2` (both events individually ≥3σ pink, the frozen `strong_event_snr`); rows with n_events ≠ 2 unaffected |
| TWO-COMBINED | Combined two-event significance | rows with `n_events == 2` must have `n_strong_events >= 2` **and** `mes_pink >= 9.0` (the frozen `tier_a_mes` bar, reused as the combined-significance bar); rows with n_events ≠ 2 unaffected |
| PHASE-DEPTH | Phase/depth consistency | rows with `n_events >= 2` must have `odd_even_ratio >= 0.5` (the pipeline's own ODD_EVEN_EB threshold, reused: alternating-event depths compatible). Rows with `n_events == 1` are **untestable** and pass through unchanged — P3-14 owns singles |
| DEMOTE-SYS | near_systematic tier-B demotion (3B(3)) | tier-B rows with `near_systematic == True` are demoted; tier-A rows untouched |
| EPOCH-CLUSTER | SECTOR_EPOCH_CLUSTER veto (P3-13) | per sector, cluster (P, T0) within 1% / 3 h (union-find, P3-13 criterion); clusters of >20 stars are SECTOR_EPOCH_CLUSTER — tier-B members demoted, tier-A members **flagged, never demoted** |
| DEMOTE-ALL | Combined demotions | union of DEMOTE-SYS + EPOCH-CLUSTER tier-B demotions; tier-A flagged members reported, not removed |

Notes on what the rows support:

- **Phase half of PHASE-DEPTH is untestable from these rows.**
  `odd_even_ratio` compares alternating-event depths (a depth
  test with a phase flavour: it catches alternating-depth
  EBs). True per-event phase residuals need per-event times,
  which the rescore rows do not carry — the phase half is
  measured by the P3-10 campaign on light curves, not by this
  replay. The replay's PHASE-DEPTH result is a depth-consistency
  result; it is labelled as such wherever quoted.
- **The secondary-depth check is already applied.** Every
  survivor passed the screen's SECONDARY_EB veto at 3σ, so no
  separate secondary candidate is replayed (a ratio-only
  secondary cut without the noise term would be a new invented
  threshold, and the veto's own threshold is frozen).
- **Demotion is never exclusion.** Demoted rows keep a
  disposition (`DEMOTED_SECTOR_EPOCH_CLUSTER` / window-demoted,
  in the P3-1 vocabulary) and remain queryable; the demotion
  is reversible if a member repeats in another sector (P3-13
  §7). The replay counts a demotion as a queue removal, never
  as a deletion.
- **The SDE candidates are replay-only.** The adopted bulk bar
  stays 7.0 unless the rule + campaign justify a change, and
  no change is adopted tonight (§4).

## 4. Adoption vs rejection, per candidate class

| Candidate class | ADOPT (in bulk_v4, P3-15) only if | REJECT if |
|---|---|---|
| SDE bars (8.0 / 9.0 / 10.0) | **Never in Phase 3.** The bars are fixed by the 3/3 vote (bulk 7.0, deep 8.5); the replay values are evidence for the 3.1 SDE decision (P3-22), not a Phase 3 adoption. Any bar change additionally needs a calibration bump + injection re-run (P0b). | A bar that drops a known planet is RULE-REJECTED as a future candidate too (recorded, not re-proposed). |
| Event-significance / phase-depth gates (TWO-STRONG, TWO-COMBINED, PHASE-DEPTH) | (i) zero known-planet losses in the replay, **and** (ii) campaign loss ≤ the §2 bar (point ≤5%, 95% upper ≤10%, n ≥ 200), **and** (iii) the gate's mechanism is stated (a characterised cut, not a tuned one). | (i) drops ≥1 known planet → RULE-REJECTED; (ii) campaign loss above the bar → REJECTED; (iii) campaign unmeasured → UNDECIDED, never adopted on replay numbers alone. |
| Demotions (DEMOTE-SYS, EPOCH-CLUSTER, DEMOTE-ALL) | (i) zero known-planet losses in the replay, **and** (ii) campaign loss ≤ the §2 bar in the priced regime (13.2 d injections for the window demotion; clustered-period injections for the epoch veto — P3-13 §7 "still owed"), **and** (iii) demoted rows keep a disposition and stay queryable, tier-A members flagged never demoted. | (i) drops ≥1 known planet → RULE-REJECTED; (ii) campaign loss above the bar → REJECTED; (iii) campaign unmeasured → UNDECIDED, never adopted on replay numbers alone. |

**Reduction is never sufficient for adoption** (hard rule: do
not measure Phase 3 success by candidates eliminated). A gate
that removes 90% of tier B but drops a known planet is a
failure, not a success — and a gate that removes 90% of tier B
with zero known-planet losses is still UNDECIDED until the
campaign prices its 1–2-event loss.

**No threshold is chosen until the campaign's loss measurement
exists.** Tonight's replay produces measurements; the adoption
decision is a later step (P3-15, on the campaign's numbers +
this rule), owned by the parent.

---

## Amendment A (2026-11-16, parent decision — the pre-registered text above is preserved verbatim)

**What changed:** the n ≥ 200 floor in §2. The campaign
(P3-10 v2, 2026-11-16) yielded **113 1–2-event planet trials /
16 recovered**, not the "several hundred" the rule's §2
reasoning (point 3) assumed. The floor's premise was wrong, so
the floor as written is unmeasurable: at n = 16 recovered, even
zero losses carry a 95% Wilson upper bound of 19.4%, and
**every** candidate would be UNDECIDED forever on the rule as
written — including gates with zero observed losses. That is a
broken measuring instrument, not a safety result.

**The amendment (parent decision 2026-11-16,
phase3-vote/p3-11-decision.md §9):** §2's bar is now judged on
the **full recovered-planet population (n = 412)** PLUS a hard
**1–2-event point check of 0 losses among the 16** recovered
1–2-event trials. The **5% / 10% bars are unchanged** — the
point estimate must be ≤ 5% and the 95% Wilson upper bound
≤ 10% on n = 412, and the 1–2-event check records **no
in-regime losses observed in 16** (0/16; 95% Wilson upper
bound 19.4%). CORRECTED 2026-11-17 (PM-6): 0/16 does NOT
establish the original Wilson-bound requirement (5% point
estimate / 10% upper bound on ≥200 recovered 1–2-event
planets) — the earlier wording overstated what n = 16 can
show. The amendment fixes an unmeasurable denominator;
the 1–2-event evidence is a point observation, not a bound.

**What was rejected instead:** (a) judging §2 on all 113
1–2-event trials (dilutes the loss by the 14.2% recovery
factor — the denominator would include trials the screen never
recovered, which no gate can lose); (b) a mixed-kind bin of
n = 260 (pads the denominator with 147 non-planet trials —
statistical padding). Both were considered and rejected in the
decision doc.

**Adoption under the amended rule (2026-11-16):** EPOCH-CLUSTER
+ TWO-COMBINED adopted (combined: 0/16 in-regime, 1/412
overall — 0.24%, W95 1.4% — 0/7 pricing, 0 replay planet/EB
losses; real 4,692 → 734, null floor 0.1085 → 0.0196).
PHASE-DEPTH HELD (degenerate oe=0.000 computation — 3.1
investigation). DEMOTE-SYS / DEMOTE-ALL REJECTED (DEMOTE-SYS
eats real 13.2 d planets, 6/7 pricing). TWO-STRONG subsumed by
TWO-COMBINED. SDE bars evidence-only (bulk 7.0 unchanged).

**Still owed (3.1 rigor):** a dedicated long-period campaign
to price the 1–2-event regime at n ≥ 200 recovered — the
amendment makes the Phase 3 adoption measurable, it does not
replace the large-n measurement the original rule wanted.
Recorded in the 3.1 register (P3-22).
