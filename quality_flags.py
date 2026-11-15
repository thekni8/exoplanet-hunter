"""TESS QUALITY flag constants, with sources (mask-fix follow-up M-1).

The bulk screen used to mask QUALITY with the bare integer 17087 and
the v3 fix added bits 29/30 as bare ``1 << 29 | 1 << 30``. This module
is the single named home for every flag the pipeline knows about, so
the mask is readable and its sources are checkable.

NUMBERING. All bit numbers here are ZERO-BASED (bit N = value 2**N),
matching numpy bit shifts and lightkurve. Beware: the TESS Data
Release Notes and the QLP release-notes page number bits ONE-BASED in
their tables -- "bit 12" there is value 2048, zero-based bit 11 here.
Every constant below cites its source; where no published definition
exists, that is said outright instead of inventing one.

SOURCES
  SPOC bits 0-15: TESS Science Data Products Description Document
    (EXP-TESS-ARC-ICD-0014), Table 28, as encoded by lightkurve's
    ``TessQualityFlags`` (lightkurve/utils.py). The table in this
    module was verified value-for-value against the installed
    lightkurve on 2026-11-15; lightkurve's DEFAULT_BITMASK is 17087.
  QLP bit 30: the QLP internal poor-quality flag -- cadences QLP
    flags as poor quality by its own metrics (Huang et al. 2020,
    RNAAS 4, 206; Kunimoto et al. 2021, RNAAS 5, 234), per the QLP
    data release notes (https://tess.mit.edu/qlp/, "New bit location
    for QLP flags"). lightkurve's QLP reader applies 2**30 only
    under its "hard"/"hardest" bitmasks, never under "default" --
    which is exactly the gap the bulk_v3 mask closes.
  QLP bit 12 (4096): the OLD location of the QLP poor-quality flag
    before QLP moved it to 2**30 ("We had previously used the
    unused-by-FFI bit 13 (2**12) for this"). The same value is
    SPOC's Straylight2 flag. It is deliberately NOT masked: the
    TOI-700 c lesson (a real transit lives on bit-12 cadences).
  Bit 29: NO PUBLISHED DEFINITION FOUND (checked 2026-11-15: QLP
    release notes, the SDPDD table via lightkurve, the TGLC paper
    Han & Brandt 2023, and a web search). It is NOT in SPOC's
    16-bit table. It IS present in real Sector 96 QLP QUALITY
    columns (6,074 of 64,914 cadences across six files checked;
    per-target -- absent in four of the six files) and it
    co-occurs with bit 30. It is masked on EMPIRICAL evidence
    only: the 2026-11-14 bulk_v2 rescore gauntlet found the
    flagged-cadence artifacts carried bits 29/30. If a definition
    surfaces, rename this constant and cite it.
  Bit 11 (2048, SPOC Straylight, set manually by MIT from visual
    inspection): deliberately NOT masked -- the 2026-11-15 vote
    went 2/3 against masking it without independent evidence, and
    stray-light flags are exactly the class where a real transit
    can survive (the TOI-700 c lesson is about bit 12, the
    sibling automatic stray-light flag). Empirically, in the six
    S96 files checked, bit 11 never appears without bit 29/30, so
    the v3 mask already excludes those cadences in practice; the
    unmasked-bit tally (M-4) will answer this sector-wide at
    rescore time.
"""

import numpy as np

# ---------------------------------------------------------------- SPOC
# TESS Science Data Products Description Document, Table 28, via
# lightkurve TessQualityFlags. Values verified against the installed
# lightkurve 2026-11-15.

SPOC_ATTITUDE_TWEAK = 1            # bit 0
SPOC_SAFE_MODE = 2                 # bit 1
SPOC_COARSE_POINT = 4              # bit 2
SPOC_EARTH_POINT = 8               # bit 3
SPOC_ARGABRIGHTENING = 16          # bit 4
SPOC_DESAT = 32                    # bit 5, reaction-wheel desaturation
SPOC_APERTURE_COSMIC = 64          # bit 6, cosmic ray in aperture
SPOC_MANUAL_EXCLUDE = 128          # bit 7
SPOC_DISCONTINUITY = 256           # bit 8
SPOC_IMPULSIVE_OUTLIER = 512       # bit 9
SPOC_COLLATERAL_COSMIC = 1024      # bit 10
SPOC_STRAYLIGHT = 2048             # bit 11, manual (MIT visual insp.)
SPOC_STRAYLIGHT2 = 4096            # bit 12, automatic (SPOC thresholds)
SPOC_PLANET_SEARCH_EXCLUDE = 8192  # bit 13
SPOC_BAD_CALIBRATION_EXCLUDE = 16384  # bit 14
SPOC_INSUFFICIENT_TARGETS = 32768  # bit 15

#: lightkurve's TESS DEFAULT_BITMASK: the cadences that are
#: "definitely useless". Bits 0,1,2,3,4,5,7,9,14.
SPOC_DEFAULT_MASK = (
    SPOC_ATTITUDE_TWEAK
    | SPOC_SAFE_MODE
    | SPOC_COARSE_POINT
    | SPOC_EARTH_POINT
    | SPOC_ARGABRIGHTENING
    | SPOC_DESAT
    | SPOC_MANUAL_EXCLUDE
    | SPOC_IMPULSIVE_OUTLIER
    | SPOC_BAD_CALIBRATION_EXCLUDE
)

# ----------------------------------------------------------------- QLP
# QLP-specific flags live outside SPOC's 16-bit table.

#: QLP internal poor-quality flag (Huang et al. 2020; Kunimoto et
#: al. 2021). Current location; see module docstring.
QLP_LOW_PRECISION = 1 << 30
#: Old location of the QLP poor-quality flag (pre-move); same value
#: as SPOC_STRAYLIGHT2. Deliberately NOT masked (TOI-700 c lesson).
QLP_LOW_PRECISION_OLD = 1 << 12
#: Bit 29: no published definition found (see module docstring).
#: Masked on empirical evidence only.
QLP_UNDOCUMENTED_29 = 1 << 29

# ------------------------------------------------------------ pipeline
#: The bulk_v1/v2 screen mask: lightkurve's TESS default.
BULK_V1_V2_MASK = SPOC_DEFAULT_MASK
#: The shared scattered-light mask (DF-12): lightkurve's TESS
#: default plus QLP bits 29/30. ONE definition site — both the
#: bulk_v3 screen and the deep_v2 pipeline reference this
#: constant, so a future change to either is a change to both
#: or an explicit, visible fork. Value 1610629823.
SHARED_QUALITY_MASK = (
    SPOC_DEFAULT_MASK | QLP_UNDOCUMENTED_29 | QLP_LOW_PRECISION
)
#: The bulk_v3 screen mask: the shared mask (DF-12).
BULK_V3_MASK = SHARED_QUALITY_MASK
#: The deep_v1 pipeline mask: lightkurve's TESS default (what
#: hunter.py's lightkurve downloads applied at read time).
DEEP_V1_MASK = SPOC_DEFAULT_MASK
#: The deep_v2 pipeline mask: the shared mask (DF-12). The two
#: names exist so each profile's drift test pins its own
#: constant, and so a reader of hunter.py sees the deep
#: profile's mask, not the bulk screen's.
DEEP_V2_MASK = SHARED_QUALITY_MASK

#: Short name per bit, for the unmasked-bit tally (M-4) and logs.
#: Bits not listed here are reported as "bit_<n>".
BIT_NAMES = {
    0: "attitude_tweak",
    1: "safe_mode",
    2: "coarse_point",
    3: "earth_point",
    4: "argabrightening",
    5: "desat",
    6: "aperture_cosmic",
    7: "manual_exclude",
    8: "discontinuity",
    9: "impulsive_outlier",
    10: "collateral_cosmic",
    11: "straylight",
    12: "straylight2",
    13: "planet_search_exclude",
    14: "bad_calibration_exclude",
    15: "insufficient_targets",
    29: "qlp_undocumented_29",
    30: "qlp_low_precision",
}


def flag_names(mask):
    """Names of the flags set in `mask`, in bit order.

    Unknown bits are reported as ``bit_<n>`` so a future flag never
    silently disappears from a log line.
    """
    names = []
    bit = 0
    m = int(mask)
    while m:
        if m & 1:
            names.append(BIT_NAMES.get(bit, f"bit_{bit}"))
        m >>= 1
        bit += 1
    return names


def tally_unmasked_bits(quality, mask):
    """Count, per bit, the cadences in `quality` carrying a bit that
    `mask` does NOT exclude.

    Returns {bit: count} for bits with a nonzero count, using
    zero-based bit numbers. Only bits 0..31 are tallied (the QUALITY
    column is int32). This is the M-4 diagnostic: it answers, for a
    survivor, which unmasked flags its in-transit cadences carry --
    in particular whether bit 11 (straylight) ever appears without
    bits 29/30.
    """
    q = np.asarray(quality, dtype=np.int64)
    unmasked = q & ~int(mask)
    tally = {}
    for bit in range(32):
        n = int(((unmasked >> bit) & 1).sum())
        if n:
            tally[bit] = n
    return tally
