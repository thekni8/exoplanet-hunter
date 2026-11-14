"""Blend test (Phase 1.2, item A-6) — a pure function.

check_blend folds the TARGET and a NEIGHBOUR light curve at the
target's refined ephemeris and asks whether the signal lives on
the neighbour. Both folds use gauntlet/common.py:fold_depth —
the same fold the desk gauntlet runs — so the blend verdict and
the desk verdict cannot disagree about the depth.

Verdicts:
  blend        — the neighbour shows the same dip at >= the
                 policy significance AND >= the policy depth
                 ratio: the target's dip is a photocopy.
  on_target    — the neighbour shows no significant dip, or a
                 shallower one than the target's (dilution only
                 makes a photocopy shallower, so a shallower
                 neighbour signal cannot be the source).
  inconclusive — the target shows no significant dip at the
                 ephemeris (nothing to attribute), or the
                 neighbour's dip is significant but below the
                 depth-ratio bar.
  unmeasured   — either fold has too few in- or out-of-transit
                 cadences to measure.

Significance is the RED-noise one when fold_depth could measure
it (FFI data has correlated noise; the white sigma overstates
significance) and falls back to white when the red sigma is
unavailable. Thresholds come from the decision policy
(gauntlet_v2: blend_min_signif, blend_min_depth_ratio).

Pure: arrays + ephemeris in, verdict out. No downloads — the
neighbour light curve is fetched by neighbour_fold.py
(fetch_neighbour) and the target's by the pipeline; the runner
hands both in as the blend.native artifact.
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
try:
    from gauntlet.common import fold_depth  # type: ignore
except ImportError:  # run as a plain script from the gauntlet dir
    from common import fold_depth  # type: ignore

DEFAULT_POLICY_VERSION = "gauntlet_v2"


def _thresholds(policy):
    """(min_signif, min_depth_ratio) from an explicit policy
    dict or the default decision policy. A dict overrides only
    the keys it carries."""
    from calibration import load_profile
    defaults = load_profile(DEFAULT_POLICY_VERSION)
    if policy is None:
        policy = {}
    return (policy.get("blend_min_signif",
                       defaults["blend_min_signif"]),
            policy.get("blend_min_depth_ratio",
                       defaults["blend_min_depth_ratio"]))


def _signif(fold):
    """The honest significance: red-noise when measured, else
    white."""
    red = fold.get("signif_red")
    if red is not None and math.isfinite(red):
        return red
    return fold["signif_white"]


def check_blend(target_t, target_f, neighbour_t, neighbour_f,
                period_d, t0, duration_d, neighbour_tic=None,
                separation_arcsec=None, policy=None):
    """Fold both light curves at the ephemeris and decide.

    Returns a dict with the verdict, both folds, the depth
    ratio, the significances, and a human-readable reason.
    Fluxes are assumed median-normalised (fold_depth measures
    depth in percent of the out-of-transit median).
    """
    min_signif, min_ratio = _thresholds(policy)
    target_fold = fold_depth(target_t, target_f, period_d, t0,
                             duration_d)
    neighbour_fold = fold_depth(neighbour_t, neighbour_f,
                                period_d, t0, duration_d)
    base = {"target_fold": target_fold,
            "neighbour_fold": neighbour_fold,
            "neighbour_tic": neighbour_tic,
            "separation_arcsec": separation_arcsec,
            "period_d": period_d, "t0": t0,
            "duration_d": duration_d,
            "min_signif": min_signif,
            "min_depth_ratio": min_ratio}
    if target_fold is None or neighbour_fold is None:
        missing = ("target" if target_fold is None
                   else "neighbour")
        return dict(base, verdict="unmeasured", depth_ratio=None,
                    target_signif=None, neighbour_signif=None,
                    reason=f"{missing} fold has too few "
                           f"in- or out-of-transit cadences")
    target_signif = _signif(target_fold)
    neighbour_signif = _signif(neighbour_fold)
    target_depth = target_fold["depth_pct"]
    neighbour_depth = neighbour_fold["depth_pct"]
    base = dict(base, target_signif=target_signif,
                neighbour_signif=neighbour_signif)
    if target_signif < min_signif or target_depth <= 0:
        return dict(base, verdict="inconclusive",
                    depth_ratio=None,
                    reason=f"target shows no significant dip at "
                           f"the ephemeris ({target_signif:.1f}σ "
                           f"< {min_signif:.0f}σ) — nothing to "
                           f"attribute")
    ratio = neighbour_depth / target_depth
    base = dict(base, depth_ratio=ratio)
    if (neighbour_signif >= min_signif
            and ratio >= min_ratio):
        return dict(base, verdict="blend",
                    reason=f"neighbour shows the same dip at "
                           f"{neighbour_signif:.1f}σ and "
                           f"{ratio:.1f}x the target depth — "
                           f"the target dip is a photocopy")
    if neighbour_signif >= min_signif and ratio >= 1.0:
        return dict(base, verdict="inconclusive",
                    reason=f"neighbour shows a significant dip "
                           f"({neighbour_signif:.1f}σ) but only "
                           f"{ratio:.1f}x the target depth "
                           f"(blend bar: {min_ratio:.0f}x)")
    return dict(base, verdict="on_target",
                reason=f"neighbour shows no dip that could "
                       f"explain the target "
                       f"({neighbour_signif:.1f}σ, "
                       f"{ratio:.2f}x depth)")
