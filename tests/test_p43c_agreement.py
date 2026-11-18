"""Tests for the P4-3c agreement-only rule (bulk/p43_run.py).

Phase 4.1, item 4.1-4 (PHASE41_PREREG.md section 2.4): in
NON-ORIGINAL sectors, mask ONLY when the fresh peak agrees with
the frozen record (P4-3's rule: mask iff fresh depth > 1% OR
fresh status == survivor); mask NOTHING on disagreement. This
removes the frozen-seed mask path on disagreement -- the P4-3b
behavior that cost the 3 right165 trials (261107054 planet02,
374945463 planet01, 382573462 planet08), where the frozen seed
was the planet itself.

Agreement is pre-registered: period within 1% of the frozen
record AND epoch within one transit duration (section 0.4). The
frozen record carries no epoch, so the reference epoch is the
original sector's fresh pass-1 t0 (fresh == frozen there --
P43B_RECORD section 7), passed as frozen_epoch_ref.

Offline: synthetic arrays only, no downloads, no Mac, no BLS
screen (the _process_sector tests mock k3_run._screen; the Mac
smoke exercises the full path end to end, as P4-3b did).
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bulk import k2_prototype as k2  # noqa: E402
from bulk import oracle_run as orc  # noqa: E402
from bulk import p43_run  # noqa: E402

CADENCE_D = 1.0 / 48.0


def _synth_multi(t0, n, signals, sigma, rng):
    """t, f, q with several box signals.

    signals is a list of (period, epoch, depth, duration)."""
    t = t0 + CADENCE_D * np.arange(n)
    f = 1.0 + rng.normal(0.0, sigma, n)
    q = np.zeros(n, dtype=int)
    for (period, epoch, depth, duration) in signals:
        k_min = int(np.ceil((t[0] - epoch) / period))
        k_max = int(np.floor((t[-1] - epoch) / period))
        for k in range(k_min, k_max + 1):
            tc = epoch + k * period
            m = np.abs(t - tc) <= duration / 2.0
            f[m] -= depth
    return t, f, q


def _sector():
    # Planet P=1.3 d (short-period, deep -- the fresh peak on an
    # injected curve) + contaminant P=3.0 d (deep EB).
    # Non-harmonic periods (3.0/1.3 = 2.31), epochs offset so the
    # two signals' windows do not coincide by construction.
    rng = np.random.default_rng(11)
    t, f, q = _synth_multi(
        3800.0, 1300,
        [(1.3, 3801.0, 0.01, 0.08),
         (3.0, 3801.7, 0.02, 0.12)],
        0.003, rng)
    t_p, f_p = orc.preprocess_arrays(t, f, q)
    return t, f, q, t_p, f_p


def _p1(period, depth_pct, status, t0=None, duration_h=None):
    out = {"period_days": period, "depth_percent": depth_pct,
           "status": status}
    if t0 is not None:
        out["t0_btjd"] = t0
    if duration_h is not None:
        out["duration_hours"] = duration_h
    return out


class TestAgreementOnlyDisagreement(unittest.TestCase):
    def test_disagreement_masks_nothing(self):
        # The P4-3c rule: the fresh peak (the planet, 1.3 d)
        # disagrees with the frozen record (3.0 d) -- mask
        # NOTHING. No ephemeris is estimated (nothing to build
        # a mask from) and the sector joins the stitch unmasked.
        _t, _f, _q, t_p, f_p = _sector()
        trial = {"recorded": {"period_days": 3.0,
                              "depth_percent": 2.0}}
        p1 = _p1(1.3, 1.0, "survivor", t0=3801.0,
                 duration_h=0.08 * 24)
        out = p43_run._mask_seed_and_eligibility(
            t_p, f_p, trial, p1, "frozen", agreement_only=True,
            frozen_epoch_ref=3801.7)
        self.assertEqual(out["seed_source"], "agree-only-skip")
        self.assertEqual(out["seed_agreement"], "disagree")
        self.assertFalse(out["eligible"])
        self.assertEqual(out["reason"], "agree-only-disagree")
        self.assertIsNone(out["ephemeris"])
        self.assertIsNone(out["secondary"])
        # The spared peak is recorded as the seed period.
        self.assertAlmostEqual(out["seed_period"], 1.3)

    def test_disagreement_flag_off_still_frozen(self):
        # Flag off (default): the P4-3b behavior is unchanged --
        # disagreement takes the frozen-seed path. This pins the
        # flag's off-state; the P4-3b tests pin the rest.
        _t, _f, _q, t_p, f_p = _sector()
        trial = {"recorded": {"period_days": 3.0,
                              "depth_percent": 2.0}}
        p1 = _p1(1.3, 1.0, "survivor")
        out = p43_run._mask_seed_and_eligibility(
            t_p, f_p, trial, p1, "frozen")
        self.assertEqual(out["seed_source"], "frozen")
        self.assertEqual(out["seed_agreement"], "disagree")
        self.assertTrue(out["eligible"])

    def test_no_fresh_peak_masks_nothing(self):
        # No fresh peak: there is nothing to agree with the
        # frozen record, so nothing is masked (P4-3b would have
        # used the frozen seed here).
        _t, _f, _q, t_p, f_p = _sector()
        trial = {"recorded": {"period_days": 3.0,
                              "depth_percent": 2.0}}
        p1 = {"period_days": None}
        out = p43_run._mask_seed_and_eligibility(
            t_p, f_p, trial, p1, "frozen", agreement_only=True,
            frozen_epoch_ref=3801.7)
        self.assertEqual(out["seed_source"], "agree-only-skip")
        self.assertEqual(out["seed_agreement"], "no-fresh-peak")
        self.assertFalse(out["eligible"])
        self.assertEqual(out["reason"],
                         "agree-only-no-fresh-peak")
        self.assertIsNone(out["ephemeris"])

    def test_no_recorded_masks_nothing(self):
        # No recorded period: there is nothing to agree with, so
        # nothing is masked (the literal rule; unreachable in
        # both P4-3c manifests -- all trials carry a record).
        _t, _f, _q, t_p, f_p = _sector()
        trial = {}
        p1 = _p1(1.3, 1.0, "survivor", t0=3801.0,
                 duration_h=0.08 * 24)
        out = p43_run._mask_seed_and_eligibility(
            t_p, f_p, trial, p1, "frozen", agreement_only=True,
            frozen_epoch_ref=3801.7)
        self.assertEqual(out["seed_source"], "agree-only-skip")
        self.assertEqual(out["seed_agreement"], "n/a")
        self.assertFalse(out["eligible"])
        self.assertEqual(out["reason"], "agree-only-no-record")


class TestAgreementOnlyAgreement(unittest.TestCase):
    def _contaminant_sector(self, seed=18):
        rng = np.random.default_rng(seed)
        t, f, q = _synth_multi(
            3800.0, 1300, [(3.0, 3801.7, 0.02, 0.12)], 0.003, rng)
        t_p, f_p = orc.preprocess_arrays(t, f, q)
        return t, f, q, t_p, f_p

    def test_agree_deep_masked(self):
        # Period AND epoch agree, and the fresh peak is a
        # confirmed contaminant (deep, 2.0%) -- P4-3's fresh rule
        # masks it. The epoch delta is recorded (~0).
        _t, _f, _q, t_p, f_p = self._contaminant_sector()
        trial = {"recorded": {"period_days": 3.0,
                              "depth_percent": 2.0}}
        p1 = _p1(3.0, 2.0, "recorded", t0=3801.7,
                 duration_h=0.12 * 24)
        out = p43_run._mask_seed_and_eligibility(
            t_p, f_p, trial, p1, "frozen", agreement_only=True,
            frozen_epoch_ref=3801.7)
        self.assertEqual(out["seed_source"], "frozen-agree")
        self.assertEqual(out["seed_agreement"], "agree")
        self.assertTrue(out["eligible"])
        self.assertEqual(out["reason"], "confirmed-contaminant")
        self.assertIsNotNone(out["ephemeris"])
        self.assertAlmostEqual(out["epoch_delta_d"], 0.0, places=6)

    def test_agree_shallow_not_masked(self):
        # Period AND epoch agree, but the fresh peak is shallow
        # (0.5%) and not a survivor -- P4-3's fresh rule spares
        # it (it may be the planet below the tier gates).
        rng = np.random.default_rng(13)
        t, f, q = _synth_multi(
            3800.0, 1300, [(3.0, 3801.7, 0.005, 0.12)], 0.002, rng)
        t_p, f_p = orc.preprocess_arrays(t, f, q)
        trial = {"recorded": {"period_days": 3.0,
                              "depth_percent": 0.5}}
        p1 = _p1(3.0, 0.5, "recorded", t0=3801.7,
                 duration_h=0.12 * 24)
        out = p43_run._mask_seed_and_eligibility(
            t_p, f_p, trial, p1, "frozen", agreement_only=True,
            frozen_epoch_ref=3801.7)
        self.assertEqual(out["seed_source"], "frozen-agree")
        self.assertEqual(out["seed_agreement"], "agree")
        self.assertFalse(out["eligible"])
        self.assertEqual(out["reason"], "not-confirmed")

    def test_agree_epoch_wrapped(self):
        # The fresh epoch one full period after the reference is
        # the SAME ephemeris (wrapped comparison) -- agrees.
        _t, _f, _q, t_p, f_p = self._contaminant_sector()
        trial = {"recorded": {"period_days": 3.0,
                              "depth_percent": 2.0}}
        p1 = _p1(3.0, 2.0, "recorded", t0=3801.7 + 3.0,
                 duration_h=0.12 * 24)
        out = p43_run._mask_seed_and_eligibility(
            t_p, f_p, trial, p1, "frozen", agreement_only=True,
            frozen_epoch_ref=3801.7)
        self.assertEqual(out["seed_source"], "frozen-agree")
        self.assertEqual(out["seed_agreement"], "agree")
        self.assertTrue(out["eligible"])
        self.assertAlmostEqual(out["epoch_delta_d"], 0.0, places=6)

    def test_agree_epoch_within_duration(self):
        # Fresh epoch 0.10 d from the reference, duration 0.12 d
        # -- within one transit duration, agrees.
        _t, _f, _q, t_p, f_p = self._contaminant_sector()
        trial = {"recorded": {"period_days": 3.0,
                              "depth_percent": 2.0}}
        p1 = _p1(3.0, 2.0, "recorded", t0=3801.7 + 0.10,
                 duration_h=0.12 * 24)
        out = p43_run._mask_seed_and_eligibility(
            t_p, f_p, trial, p1, "frozen", agreement_only=True,
            frozen_epoch_ref=3801.7)
        self.assertEqual(out["seed_agreement"], "agree")
        self.assertTrue(out["eligible"])
        self.assertAlmostEqual(out["epoch_delta_d"], 0.10,
                               places=6)


class TestAgreementOnlyEpochDisagreement(unittest.TestCase):
    def _contaminant_sector(self):
        rng = np.random.default_rng(18)
        t, f, q = _synth_multi(
            3800.0, 1300, [(3.0, 3801.7, 0.02, 0.12)], 0.003, rng)
        t_p, f_p = orc.preprocess_arrays(t, f, q)
        return t, f, q, t_p, f_p

    def test_epoch_disagree_masks_nothing(self):
        # Same period (3.0 d) but a different epoch (0.5 d away,
        # duration 0.12 d) -- a different signal at the same
        # period. Mask NOTHING.
        _t, _f, _q, t_p, f_p = self._contaminant_sector()
        trial = {"recorded": {"period_days": 3.0,
                              "depth_percent": 2.0}}
        p1 = _p1(3.0, 2.0, "recorded", t0=3801.7 + 0.5,
                 duration_h=0.12 * 24)
        out = p43_run._mask_seed_and_eligibility(
            t_p, f_p, trial, p1, "frozen", agreement_only=True,
            frozen_epoch_ref=3801.7)
        self.assertEqual(out["seed_source"], "agree-only-skip")
        self.assertEqual(out["seed_agreement"], "disagree-epoch")
        self.assertFalse(out["eligible"])
        self.assertEqual(out["reason"],
                         "agree-only-epoch-disagree")
        self.assertIsNone(out["ephemeris"])
        self.assertAlmostEqual(out["epoch_delta_d"], 0.5,
                               places=6)

    def test_epoch_just_outside_duration(self):
        # 0.15 d from the reference with a 0.12 d duration --
        # outside one transit duration, disagrees.
        _t, _f, _q, t_p, f_p = self._contaminant_sector()
        trial = {"recorded": {"period_days": 3.0,
                              "depth_percent": 2.0}}
        p1 = _p1(3.0, 2.0, "recorded", t0=3801.7 + 0.15,
                 duration_h=0.12 * 24)
        out = p43_run._mask_seed_and_eligibility(
            t_p, f_p, trial, p1, "frozen", agreement_only=True,
            frozen_epoch_ref=3801.7)
        self.assertEqual(out["seed_agreement"], "disagree-epoch")
        self.assertFalse(out["eligible"])

    def test_epoch_unavailable_no_t0(self):
        # Fail closed: the fresh peak carries no epoch, so the
        # epoch clause cannot be tested -- not an agreement.
        _t, _f, _q, t_p, f_p = self._contaminant_sector()
        trial = {"recorded": {"period_days": 3.0,
                              "depth_percent": 2.0}}
        p1 = _p1(3.0, 2.0, "recorded",
                 duration_h=0.12 * 24)
        out = p43_run._mask_seed_and_eligibility(
            t_p, f_p, trial, p1, "frozen", agreement_only=True,
            frozen_epoch_ref=3801.7)
        self.assertEqual(out["seed_source"], "agree-only-skip")
        self.assertEqual(out["seed_agreement"], "disagree-epoch")
        self.assertFalse(out["eligible"])
        self.assertEqual(out["reason"],
                         "agree-only-epoch-unavailable")

    def test_epoch_unavailable_no_ref(self):
        # Fail closed: no reference epoch (the original sector
        # had no pass-1 peak) -- not an agreement.
        _t, _f, _q, t_p, f_p = self._contaminant_sector()
        trial = {"recorded": {"period_days": 3.0,
                              "depth_percent": 2.0}}
        p1 = _p1(3.0, 2.0, "recorded", t0=3801.7,
                 duration_h=0.12 * 24)
        out = p43_run._mask_seed_and_eligibility(
            t_p, f_p, trial, p1, "frozen", agreement_only=True,
            frozen_epoch_ref=None)
        self.assertEqual(out["seed_source"], "agree-only-skip")
        self.assertEqual(out["reason"],
                         "agree-only-epoch-unavailable")

    def test_epoch_unavailable_no_duration(self):
        # Fail closed: no duration to compare against.
        _t, _f, _q, t_p, f_p = self._contaminant_sector()
        trial = {"recorded": {"period_days": 3.0,
                              "depth_percent": 2.0}}
        p1 = _p1(3.0, 2.0, "recorded", t0=3801.7)
        out = p43_run._mask_seed_and_eligibility(
            t_p, f_p, trial, p1, "frozen", agreement_only=True,
            frozen_epoch_ref=3801.7)
        self.assertEqual(out["seed_source"], "agree-only-skip")
        self.assertEqual(out["reason"],
                         "agree-only-epoch-unavailable")


class TestAgreementOnlyOriginalSector(unittest.TestCase):
    def test_fresh_mode_unaffected_by_flag(self):
        # The original sector is UNCHANGED by the flag: the fresh
        # rule applies exactly as with the flag off.
        _t, _f, _q, t_p, f_p = _sector()
        trial = {"recorded": {"period_days": 3.0,
                              "depth_percent": 2.0}}
        p1 = _p1(1.3, 1.0, "survivor", t0=3801.0,
                 duration_h=0.08 * 24)
        out_on = p43_run._mask_seed_and_eligibility(
            t_p, f_p, trial, p1, "fresh", agreement_only=True,
            frozen_epoch_ref=3801.7)
        out_off = p43_run._mask_seed_and_eligibility(
            t_p, f_p, trial, p1, "fresh")
        self.assertEqual(out_on["seed_source"], "fresh")
        self.assertTrue(out_on["eligible"])
        self.assertEqual(out_on["seed_source"],
                         out_off["seed_source"])
        self.assertEqual(out_on["eligible"], out_off["eligible"])
        self.assertEqual(out_on["reason"], out_off["reason"])


class TestEpochAgrees(unittest.TestCase):
    def test_match(self):
        ok, why, delta = p43_run._epoch_agrees(
            {"t0_btjd": 3801.7, "duration_hours": 0.12 * 24},
            3801.7, 3.0)
        self.assertTrue(ok)
        self.assertIsNone(why)
        self.assertAlmostEqual(delta, 0.0, places=9)

    def test_mismatch(self):
        ok, why, delta = p43_run._epoch_agrees(
            {"t0_btjd": 3802.2, "duration_hours": 0.12 * 24},
            3801.7, 3.0)
        self.assertFalse(ok)
        self.assertEqual(why, "disagree")
        self.assertAlmostEqual(delta, 0.5, places=9)

    def test_unavailable(self):
        for p1, ref in (({}, 3801.7),
                        ({"t0_btjd": 3801.7}, 3801.7),
                        ({"duration_hours": 2.88}, 3801.7),
                        ({"t0_btjd": 3801.7,
                          "duration_hours": 2.88}, None)):
            ok, why, delta = p43_run._epoch_agrees(p1, ref, 3.0)
            self.assertFalse(ok)
            self.assertEqual(why, "unavailable")
            self.assertIsNone(delta)

    def test_one_duration_not_half(self):
        # The section 0.4 tolerance is ONE transit duration, not
        # the frozen 0.5x recovery rule: a 0.10 d offset against
        # a 0.12 d duration agrees (it would fail at 0.5x).
        ok, _why, _d = p43_run._epoch_agrees(
            {"t0_btjd": 3801.7 + 0.10,
             "duration_hours": 0.12 * 24},
            3801.7, 3.0)
        self.assertTrue(ok)
        self.assertFalse(k2.epoch_match(0.10, 0.12))


class TestProcessSectorAgreementOnly(unittest.TestCase):
    def _trial(self):
        return {"period_d": 1.3, "epoch_btjd": 3801.0,
                "duration_d": 0.08, "depth_frac": 0.01,
                "recorded": {"period_days": 3.0,
                             "depth_percent": 2.0}}

    def test_skip_keeps_all_cadences(self):
        # End-to-end through _process_sector (screen mocked): on
        # disagreement the sector is unmasked -- keep is all
        # True, k2_mask None, and the audit fields are recorded.
        t, f, q, _t_p, _f_p = _sector()
        p1 = _p1(1.3, 1.0, "survivor", t0=3801.0,
                 duration_h=0.08 * 24)
        with tempfile.TemporaryDirectory() as d:
            base = Path(d) / "1_planet01"
            with mock.patch("bulk.k3_run._screen",
                            return_value=p1):
                rec, (_t, _f2, _q2, keep, _sig) = (
                    p43_run._process_sector(
                        t, f, q, "SYS_RM_FLUX", self._trial(),
                        base, "1", 96, False, seed_mode="frozen",
                        agreement_only=True,
                        frozen_epoch_ref=3801.7))
        self.assertEqual(rec["seed_source"], "agree-only-skip")
        self.assertEqual(rec["seed_agreement"], "disagree")
        self.assertFalse(rec["eligible"])
        self.assertIsNone(rec["k2_mask"])
        self.assertTrue(bool(keep.all()))
        self.assertEqual(rec["frozen_epoch_ref_btjd"], 3801.7)
        self.assertIsNone(rec["seed_epoch_delta_d"])

    def test_agree_masks(self):
        # On agreement the mask is built (P4-3's fresh rule) and
        # the epoch delta is recorded.
        rng = np.random.default_rng(18)
        t, f, q = _synth_multi(
            3800.0, 1300, [(3.0, 3801.7, 0.02, 0.12)], 0.003, rng)
        trial = {"period_d": 1.3, "epoch_btjd": 3801.0,
                 "duration_d": 0.08, "depth_frac": 0.01,
                 "recorded": {"period_days": 3.0,
                              "depth_percent": 2.0}}
        p1 = _p1(3.0, 2.0, "recorded", t0=3801.7,
                 duration_h=0.12 * 24)
        with tempfile.TemporaryDirectory() as d:
            base = Path(d) / "1_planet01"
            with mock.patch("bulk.k3_run._screen",
                            return_value=p1):
                rec, (_t, _f2, _q2, keep, _sig) = (
                    p43_run._process_sector(
                        t, f, q, "SYS_RM_FLUX", trial, base, "1",
                        96, False, seed_mode="frozen",
                        agreement_only=True,
                        frozen_epoch_ref=3801.7))
        self.assertEqual(rec["seed_source"], "frozen-agree")
        self.assertTrue(rec["eligible"])
        self.assertIsNotNone(rec["k2_mask"])
        self.assertFalse(bool(keep.all()))
        self.assertAlmostEqual(rec["seed_epoch_delta_d"], 0.0,
                               places=6)


class TestSeedFixFor(unittest.TestCase):
    def test_markers(self):
        self.assertEqual(
            p43_run._seed_fix_for("frozen", False), "p43b")
        self.assertEqual(
            p43_run._seed_fix_for("frozen", True), "p43c")
        self.assertEqual(
            p43_run._seed_fix_for("fresh", False), "p43")

    def test_agreement_only_requires_frozen(self):
        with self.assertRaises(ValueError):
            p43_run._seed_fix_for("fresh", True)

    def test_unknown_seed_mode_raises(self):
        with self.assertRaises(ValueError):
            p43_run._seed_fix_for("bogus", False)


class TestBuildJobsFlag(unittest.TestCase):
    def _setup(self, tmp):
        cache = Path(tmp) / "cache"
        for sec in (95, 96, 97):
            (cache / f"s{sec:04d}").mkdir(parents=True)
            (cache / f"s{sec:04d}" / "123.fits").write_bytes(b"")
        manifest = {"_sha256": "x",
                    "trials": [{"tic": "123", "sector": 95,
                                "trial_id": "planet01"}]}
        return cache, manifest

    def test_flag_on_stitched_jobs(self):
        with tempfile.TemporaryDirectory() as d:
            cache, manifest = self._setup(d)
            _s, stitched, missing = p43_run._build_jobs(
                manifest, cache, Path(d) / "out",
                Path(d) / "w43", Path(d) / "w1", False, "bulk_v5",
                agreement_only=True)
            self.assertEqual(missing, [])
            self.assertEqual(len(stitched), 1)
            self.assertTrue(stitched[0]["agreement_only"])

    def test_flag_defaults_off(self):
        with tempfile.TemporaryDirectory() as d:
            cache, manifest = self._setup(d)
            _s, stitched, _m = p43_run._build_jobs(
                manifest, cache, Path(d) / "out",
                Path(d) / "w43", Path(d) / "w1", False, "bulk_v5")
            self.assertEqual(len(stitched), 1)
            self.assertFalse(stitched[0]["agreement_only"])

    def test_seed_mode_fresh(self):
        # The P4-3 rule arm: non-original sectors seed from the
        # fresh peak (no frozen seed anywhere).
        with tempfile.TemporaryDirectory() as d:
            cache, manifest = self._setup(d)
            _s, stitched, _m = p43_run._build_jobs(
                manifest, cache, Path(d) / "out",
                Path(d) / "w43", Path(d) / "w1", False, "bulk_v5",
                seed_mode="fresh")
            self.assertEqual(len(stitched), 1)
            self.assertEqual(stitched[0]["seed_mode"], "fresh")
            self.assertFalse(stitched[0]["agreement_only"])

    def test_seed_mode_defaults_frozen(self):
        with tempfile.TemporaryDirectory() as d:
            cache, manifest = self._setup(d)
            _s, stitched, _m = p43_run._build_jobs(
                manifest, cache, Path(d) / "out",
                Path(d) / "w43", Path(d) / "w1", False, "bulk_v5")
            self.assertEqual(stitched[0]["seed_mode"], "frozen")


if __name__ == "__main__":
    unittest.main()
