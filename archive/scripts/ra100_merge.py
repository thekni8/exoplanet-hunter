#!/usr/bin/env python
"""RA100 vet: merge catalog + hand + profile stages into the final
vetting_results/167367406.json (driver record preserved, incl.
driver_verdict_raw), apply the documented reclassification, and
record the reconciliation of the wave statistics."""
import json
from pathlib import Path

BASE = Path(__file__).resolve().parent
OUT = BASE / "vetting_results"

d = json.loads((OUT / "167367406.json").read_text())
cat = json.loads((OUT / "167367406_catalog.json").read_text())
hand = json.loads((OUT / "167367406_hand.json").read_text())
prof = json.loads((OUT / "167367406_profile.json").read_text())

d["tic_row_id_verified"] = cat["tic_row"]
d["tic_row_id_verified"]["distance_pc"] = None
d["tic_row_note"] = ("TIC 'd' and 'plx' are NaN for this row; distance "
                     "not available from the TIC record.")
d["neighbour_census_within_2arcmin"] = {
    "n_incl_target": cat["n_neighbours_within_2arcmin_incl_target"],
    "bright_or_close": [n for n in cat["neighbours_within_2arcmin"]
                        if n["sep_arcsec"] <= 63 and (n["Tmag"] or 99) <= 16.5],
    "dilution_arithmetic": (
        "Brightest neighbour TIC 167367404 (26.9 arcsec, Tmag 13.6518, "
        "0.55 mag brighter than target, flux ratio 1.67x). At the TIC "
        "contratio-implied dilution (contaminant fraction 0.197 of "
        "target flux), supplying the observed ~20.7% apparent depth "
        "would require an intrinsic eclipse depth of ~128% on the "
        "neighbour - unphysical. Even at full aperture inclusion of "
        "the neighbour it would require ~34% eclipses. All 18 sectors "
        "are QLP products (larger apertures than the SPOC-based "
        "contratio assumes), so the neighbour route is disfavoured "
        "but not pixel-tested; the on-target reading needs no such "
        "extremes.")}

d["hand_checks"] = {k: hand[k] for k in (
    "hand_odd_even_at_P", "hand_double_period_raw",
    "ellipsoidal_sine_fit_at_P", "duration_sanity",
    "lomb_scargle_raw_top_peaks", "lomb_scargle_power_near_P",
    "lomb_scargle_power_near_2P", "harmonic_fit_base_2P",
    "raw_flux_era_split", "raw_flux_overall")}
d["hand_checks"]["raw_flux_per_sector"] = hand["raw_flux_per_sector"]
d["hand_checks"]["note"] = (
    "Hand odd/even depths at P (~5.3%) are on the production "
    "flattened curve (flatten window 101 partially absorbs the "
    "wide events); the TEST quantity is the odd-even difference "
    "(+0.124% = 1.03 sigma -> equal), which is "
    "normalization-independent. Hand Q-S used narrower shoulder "
    "windows than the machine (see reconciliation).")

d["fold_profile_arbitration"] = {
    "profile_2P_medians": prof["profile_2P_25bins"],
    "profile_P_medians": prof["profile_P_25bins"],
    "machine_windows_median_on_this_fold": prof["machine_windows_on_this_fold_median"],
    "machine_windows_mean_on_this_fold": prof["machine_windows_on_this_fold_mean"],
    "sine_fit_P": prof["sine_fit_P"],
    "sine_fit_2P": prof["sine_fit_2P"],
    "reading": (
        "The binned profiles are the ground truth: the raw curve is "
        "a CONTINUOUS dip train with minima every 0.21731 d (the "
        "Lomb-Scargle dominant peak, power 0.617) and no flat "
        "out-of-eclipse stretch - contact-binary (EW) morphology, "
        "~20-25% peak-to-dip amplitude. In the P fold the minima sit "
        "at phases 0, 1/3, 2/3; in the 2P fold at 0, 1/6, ..., 5/6, "
        "all of comparable depth (medians 0.78-0.88 vs maxima "
        "1.02-1.08). The sweep period 0.651915 d is exactly 3x the "
        "photometric cycle (an alias of the train); the orbital "
        "period is 0.43461 d if the train is twin eclipses (near-"
        "equal minima - the standard reading), or 0.21731 d at the "
        "contact-binary period cutoff.")}

d["reconciliation_note"] = (
    "The machine double-period stamp (+3.340% at 49.8 sigma) is "
    "arithmetically real on its own windows - recomputed here on an "
    "independent fold: +3.347% at 49.7 sigma (medians), +6.728% at "
    "96.4 sigma (means). But its INTERPRETATION as the ellipsoidal "
    "wave of a 1.3038 d binary is a misread: the quadrature windows "
    "fall between the dips of the 0.21731 d train (local maxima) "
    "while two of the four shoulder windows fall ON train dips. "
    "The narrower hand shoulder windows (0.058-0.138 in phase from "
    "each eclipse) sample the train's inter-dip maxima instead and "
    "return -2.147% at -46.7 sigma. Both statistics are hostage to "
    "window placement on a structured curve; the binned profile "
    "settles the morphology. The binary conviction itself does not "
    "depend on the wave: it rests on the dip train's depth, "
    "persistence and contact-binary shape.")

d["driver_verdict_preserved"] = d.get("driver_verdict_raw")
d["verdict"] = "EB"
d["reclassification_note"] = (
    "Driver's mechanical LIKELY BINARY (stage-gate kill at (c) via "
    "the ellipsoidal wave) is upgraded to EB on the hand evidence: "
    "the eclipses are directly visible at 20.7% depth in every one "
    "of 18 sectors (per-sector significances 10-49 sigma), the fold "
    "profile shows contact-binary morphology, and the depth budget "
    "disfavours a neighbour host. Species: eclipsing (contact / "
    "near-contact twin) binary. True photometric cycle 0.21731 d; "
    "orbital period 0.43461 d on the twin-eclipse reading (the "
    "sweep's 0.651915 d is its 3x alias, 1.5x P_orb). The machine "
    "odd/even 'planet-like' call and the hand odd/even equality "
    "(1.03 sigma) are both expected for near-twin eclipses and do "
    "not acquit - the 308851365 blind spot, in its purest form.")
d["decisive_tests"] = [
    "Binned fold profile + Lomb-Scargle: continuous 0.21731 d dip train, ~20-25% amplitude, no flat out-of-eclipse (contact-binary morphology); sweep P is the 3x alias",
    "Reproduction exact at SDE 94.72 with 20.74% eclipses present in all 18 sectors (persistence raw tiebreaker: +15.40% @ 47 sigma in era 27-59, +8.52% @ 129 sigma in era >=60 - present in both eras, no switch-off)",
    "Depth budget vs ID-verified contratio 0.197: a neighbour host would need unphysical (>100%) eclipses at TIC-implied dilution",
]
d["untested"] = [
    "Centroid / difference imaging (pixel-level host attribution) - not demanded: depth budget already disfavours the neighbour, and the species is binary either way",
    "0.21731 d vs 0.43461 d orbital-period ambiguity (near-equal minima) - immaterial to the verdict",
    "The ~14.4-15.2 d low-power Lomb-Scargle complex (possible spot modulation of the binary) - context only",
]
(OUT / "167367406.json").write_text(json.dumps(d, indent=2, default=str))
print("merged; verdict:", d["verdict"])
print("driver raw preserved:", d["driver_verdict_preserved"])
