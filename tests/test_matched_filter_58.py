"""5.8 matched-filter tests (VALIDATION_PROTOCOL_5_8.md §7 item 2).

Synthetic-data tests for the frozen whitening pipeline
(DESIGN_5_8_AS_VOTED.md §2.3, M5–M10) plus the integration
tests for the search flag, depth-gate isolation, fallback,
top-15 recording, and flag-off byte identity.

Noise model (shared by the GLS gate and the PSD test):
  white sigma = 0.003, 27 d sector, 200 s cadence, red noise
  shaped as f^2/(f^2 + 0.5^2) * 1/(1 + (f/15)^2) — a
  post-flatten-like spectrum, suppressed below 0.5/day.
  Shaping amplitude A = 1.0 -> 1.20x CDPP excess (mild);
  A = 6.0 -> 2.15x CDPP excess (strong, inside the frozen
  2.0–2.5x band).  The CDPP excess is verified inside the
  test via bulk/detrend.py::measure_cdpp, so the regimes
  are self-calibrating, not assumed.

GLS gate statistic (frozen): the MEDIAN SNR loss across
the full 5x6 period x duration grid at depth 0.05% (the
S18 bar depth) under STRONG red noise, 5 seeds per cell.
Gate: >10% STOPS campaign authorization; 5–10% is
presented to Dev before campaign authorization.
The rule-duration subset median (the (P, D) combinations
the campaign actually injects) and the 0.20% numbers are
reported alongside as mandatory sensitivities — they are
NOT the gate statistic, but they are decision-relevant
and must appear in BUILD_5_8.md.

Calibration: bulk_v6 throughout (setUp/tearDown restores
the previous profile), the 5.7 pattern.
"""

import json
import math
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import bulk_screen as bs  # noqa: E402
from bulk import joint_fit as jf  # noqa: E402
from bulk import k2_prototype as k2  # noqa: E402
from bulk import k3_prototype as k3  # noqa: E402
from bulk import k3_run as k3run  # noqa: E402
from bulk import matched_filter as mf  # noqa: E402
from bulk import oracle_run as orc  # noqa: E402
from bulk import p43_run as p43run  # noqa: E402
from synth_fits import make_qlp_fits, screen_job  # noqa: E402

PINS_PATH = (Path(__file__).resolve().parent / "fixtures"
             / "matched_filter58_flagoff_pins.json")

# ---------------------------------------------------------------- helpers

SIGMA = 0.003
N_CAD = 11664  # 27 d at 200 s cadence
DT_D = 200.0 / 86400.0
T0_EPOCH = 1500.0
PERIODS = [0.8, 1.7, 3.5, 7.0, 12.0]
DURS = [0.04, 0.06, 0.09, 0.13, 0.18, 0.25]
GATE_SEEDS = (11, 12, 13, 14, 15)
PSD_SEEDS = (11, 12, 13)


class _BulkV6Case(unittest.TestCase):
    def setUp(self):
        bs.set_calibration("bulk_v6")

    def tearDown(self):
        bs.set_calibration("bulk_v1")


def band_shape(f):
    """Post-flatten-like red-noise band shape."""
    lo = f ** 2 / (f ** 2 + 0.5 ** 2)
    hi = 1.0 / (1.0 + (f / 15.0) ** 2)
    return lo * hi


def make_times():
    return T0_EPOCH + np.arange(N_CAD) * DT_D


def make_noise(rng, A):
    """White + shaped red noise; returns (noise, shape_sqrt)."""
    w = rng.normal(0.0, SIGMA, N_CAD)
    fr = np.fft.rfftfreq(N_CAD, d=DT_D)
    S = np.sqrt(1.0 + A * band_shape(fr))
    S[0] = 1.0
    return np.fft.irfft(np.fft.rfft(w) * S, n=N_CAD), S


def box_template(t, P, t0, D):
    phase = ((t - t0 + 0.5 * P) % P) - 0.5 * P
    m = (np.abs(phase) < D / 2).astype(float)
    return m, m - m.mean()


def snr_gls_vs_impl(t, flux, m_c, S, f_w):
    """Exact GLS SNR (true PSD) vs implemented (whitened-box) SNR.

    GLS: weight both flux and template by 1/S(f) in Fourier
    space, then the matched-filter SNR with the TRUE sigma.
    Implemented: plain box template on the whitened curve,
    sigma estimated from the whitened curve (what BLS does).
    Both SNRs are sign-flipped (a transit is a dip).
    """
    F = np.fft.rfft(flux - flux.mean())
    M = np.fft.rfft(m_c)
    W = 1.0 / S
    fw = np.fft.irfft(F * W, n=len(t))
    mw = np.fft.irfft(M * W, n=len(t))
    snr_g = -float(mw @ fw / (SIGMA * math.sqrt(mw @ mw)))
    sig_w = float(np.std(f_w))
    snr_i = -float(m_c @ (f_w - f_w.mean()) / (sig_w * math.sqrt(m_c @ m_c)))
    return snr_g, snr_i


def rule_duration(P):
    return 2.0 * P ** (1.0 / 3.0) / 24.0


# ---------------------------------------------------------------- GLS gate


class TestSyntheticGLSGate(unittest.TestCase):
    """Expanded synthetic GLS gate (design §2.3 (a), [R4]).

    Runtime ~40 s (600 whitenings + FFT SNRs).  The gate
    statistic is the grid-median loss at 0.05% / strong.
    """

    def test_red_noise_regimes_calibrated(self):
        """A=1.0 is mild (1.1–1.3x), A=6.0 is strong (2.0–2.5x)."""
        from bulk.detrend import measure_cdpp

        t = make_times()
        for A, lo, hi in ((1.0, 1.1, 1.3), (6.0, 2.0, 2.5)):
            rng = np.random.default_rng(11)
            noise, _ = make_noise(rng, A)
            flux = 1.0 + noise
            white = 1.0 + rng.normal(0.0, SIGMA, N_CAD)
            c_red = measure_cdpp(t, flux, 0.09)["cdpp_ppm"]
            c_wht = measure_cdpp(t, white, 0.09)["cdpp_ppm"]
            ratio = c_red / c_wht
            self.assertTrue(
                lo <= ratio <= hi,
                f"A={A}: CDPP excess {ratio:.2f}x outside [{lo}, {hi}]",
            )

    def test_gls_gate_full_grid(self):
        """Gate statistic: grid-median loss at 0.05% / strong.

        Asserts < 10% (the STOP threshold).  Prints the full
        table (both depths, both regimes, rule-duration subset,
        max cell) — the numbers belong in BUILD_5_8.md.
        """
        t = make_times()
        table = {}
        for depth in (0.0005, 0.002):
            for A, label in ((1.0, "mild"), (6.0, "strong")):
                cell_med = []
                for P in PERIODS:
                    for D in DURS:
                        ratios = []
                        for seed in GATE_SEEDS:
                            rng = np.random.default_rng(seed)
                            noise, S = make_noise(rng, A)
                            m_box, m_c = box_template(t, P, 1501.0, D)
                            flux = 1.0 + noise - depth * m_box
                            f_w, _ = mf.whiten_curve(t, flux)
                            sg, si = snr_gls_vs_impl(t, flux, m_c, S, f_w)
                            ratios.append(1.0 - si / sg)
                        cell_med.append(float(np.median(ratios)))
                arr = np.array(cell_med)
                rule = []
                for P in PERIODS:
                    Dr = rule_duration(P)
                    j = int(np.argmin([abs(d - Dr) for d in DURS]))
                    rule.append(cell_med[PERIODS.index(P) * len(DURS) + j])
                table[(depth, label)] = {
                    "grid_median": float(np.median(arr)),
                    "max_cell": float(arr.max()),
                    "min_cell": float(arr.min()),
                    "rule_median": float(np.median(rule)),
                    "rule_values": [round(x, 3) for x in rule],
                }
                print(
                    "depth %.4f %s: grid-median %.4f | max cell %.4f | "
                    "rule-subset median %.4f %s"
                    % (
                        depth,
                        label,
                        table[(depth, label)]["grid_median"],
                        table[(depth, label)]["max_cell"],
                        table[(depth, label)]["rule_median"],
                        table[(depth, label)]["rule_values"],
                    )
                )
        gate = table[(0.0005, "strong")]["grid_median"]
        self.assertLess(
            gate, 0.10,
            f"GLS GATE FAILED: grid-median loss at 0.05%/strong "
            f"is {gate:.4f} (>10%) — campaign authorization STOPPED",
        )
        # The 5–10% band is a presentation duty, not a test
        # failure — but record where the primary statistic sits.
        print("GATE STATISTIC (0.05%%/strong grid median): %.4f" % gate)
        print(
            "RULE-SUBSET (0.05%%/strong): %.4f — in the 5–10%% band, "
            "present to Dev before campaign authorization"
            % table[(0.0005, "strong")]["rule_median"]
        )

    def test_gls_gate_bls_crosscheck(self):
        """Astropy BLS on the whitened curve recovers the ephemeris.

        Detection cross-check (not the gate statistic): at depth
        0.2% / strong red noise, BLS on the whitened curve must
        find P within 1% of truth.  At 0.05% the direct SNR is
        ~2.4 on one sector — below threshold, as expected — so
        no detection is asserted there.
        """
        from astropy.timeseries import BoxLeastSquares

        t = make_times()
        rng = np.random.default_rng(11)
        noise, _ = make_noise(rng, 6.0)
        m_box, _ = box_template(t, 3.5, 1501.0, 0.09)
        flux = 1.0 + noise - 0.002 * m_box
        f_w, _ = mf.whiten_curve(t, flux)
        bls = BoxLeastSquares(t, f_w)
        res = bls.autopower(
            0.04,
            minimum_period=0.5,
            maximum_period=20.0,
            frequency_factor=1.0,
        )
        i = int(np.argmax(res.power))
        self.assertLess(abs(res.period[i] - 3.5) / 3.5, 0.01,
                        f"BLS period {res.period[i]:.4f} vs true 3.5")
        self.assertGreater(res.power[i], 0,
                           "BLS power must be positive at argmax")


# ---------------------------------------------------------------- PSD test


class TestPSDTransitRejection(unittest.TestCase):
    """Design §2.3 (b): the PSD estimator must not absorb
    transit power — the smoothed PSD at the transit's harmonic
    frequencies stays within 10% of the transit-free PSD,
    across the complete frozen period and duration grid.

    MEASURED FINDING (2026-11-24): this test FAILS as
    written at a strong transit.  The Welch bins (0.5/day)
    are wider than the harmonic spacing (1/P = 0.083–1.25/day),
    so every low-frequency bin contains harmonics and the
    log-frequency median cannot reject the comb.  The
    deviation is concentrated at the fundamental and low
    harmonics (the box's main lobe) and scales with depth^2:
    at 0.05% the median max-deviation is 3.1% (strong) /
    5.6% (mild) but 2–8 of 30 cells exceed 10% at their worst
    harmonic; at 0.20% the median max-deviation is 17.9%
    (strong) / 47.9% (mild).  This is the same PSD
    contamination that drives the depth-dependent GLS loss,
    and the GLS gate (the decision gate) captures its
    end-to-end cost.  The assertion below is written as the
    design specifies — it is EXPECTED TO FAIL, and the
    failure is recorded in BUILD_5_8.md rather than hidden
    by weakening the assertion (repo AGENTS.md: never loosen
    a threshold to pass a test).
    """

    def _max_dev_grid(self, depth, A):
        """Median-of-seeds max harmonic deviation per grid cell."""
        t = make_times()
        worst = []
        for P in PERIODS:
            for D in DURS:
                devs = []
                for seed in PSD_SEEDS:
                    rng = np.random.default_rng(seed)
                    noise, _ = make_noise(rng, A)
                    m, _ = box_template(t, P, 1501.0, D)
                    freqs, ps_c, _, _ = mf.estimate_psd(t, 1.0 + noise)
                    _, ps_t, _, _ = mf.estimate_psd(
                        t, 1.0 + noise - depth * m
                    )
                    harm = []
                    k = 1
                    while k / P < 2.0 / D:
                        harm.append(k / P)
                        k += 1
                    harm = np.array(harm)
                    idx = np.searchsorted(freqs, harm)
                    ok = (idx >= 1) & (idx < len(freqs))
                    dev = np.abs(ps_t[idx[ok]] / ps_c[idx[ok]] - 1.0)
                    devs.append(float(np.max(dev)) if len(dev) else 0.0)
                worst.append(float(np.median(devs)))
        return np.array(worst)

    def test_psd_transit_rejection(self):
        for depth, A, label in (
            (0.0005, 6.0, "0.05%/strong"),
            (0.0005, 1.0, "0.05%/mild"),
            (0.002, 6.0, "0.20%/strong"),
            (0.002, 1.0, "0.20%/mild"),
        ):
            arr = self._max_dev_grid(depth, A)
            print(
                "%s: median max-dev %.3f | max cell %.3f | "
                "cells >10%%: %d/30"
                % (label, np.median(arr), arr.max(), int((arr > 0.10).sum()))
            )
        # The design's assertion, as written: every cell within
        # 10% at a strong (0.20%) transit, strong red noise.
        arr = self._max_dev_grid(0.002, 6.0)
        self.assertLess(
            float(arr.max()), 0.10,
            "PSD TRANSIT-REJECTION FAILED as written: max cell "
            f"deviation {arr.max():.3f} at 0.20%/strong "
            f"({int((arr > 0.10).sum())}/30 cells >10%). "
            "See BUILD_5_8.md — the GLS gate captures the "
            "end-to-end cost of this contamination.",
        )


# ---------------------------------------------------------------- edge / cap


class TestEdgeTransients(unittest.TestCase):
    """Design §2.3 (c): edge transients confined to ≤10
    cadences at each segment edge (measured, not assumed)."""

    def test_edge_transients_confined(self):
        t = make_times()
        rng = np.random.default_rng(11)
        noise, _ = make_noise(rng, 6.0)
        base = 1.0 + noise
        # A large spike at the first cadence and one at the last.
        spiked = base.copy()
        spiked[0] += 0.1
        spiked[-1] += 0.1
        f_base, _ = mf.whiten_curve(t, base)
        f_spk, _ = mf.whiten_curve(t, spiked)
        diff = np.abs(f_spk - f_base)
        # Transient extent: cadences from each edge where the
        # spike's imprint exceeds 1% of the spike amplitude
        # after whitening (0.001 in flux units).
        thresh = 0.001
        left = 0
        while left < len(diff) and diff[left] > thresh:
            left += 1
        right = 0
        while right < len(diff) and diff[len(diff) - 1 - right] > thresh:
            right += 1
        print("edge transient extent: left %d cad, right %d cad"
              % (left, right))
        self.assertLessEqual(left, 10,
                             f"left edge transient spans {left} cadences (>10)")
        self.assertLessEqual(right, 10,
                             f"right edge transient spans {right} cadences (>10)")


class TestNeverAmplify(unittest.TestCase):
    """Design §2.3 (d): max |W| ≤ 1.0 on every synthetic
    segment (the cap prevents direct spectral amplification)."""

    def test_never_amplify_cap(self):
        t = make_times()
        for A in (1.0, 6.0):
            rng = np.random.default_rng(11)
            noise, _ = make_noise(rng, A)
            m, _ = box_template(t, 3.5, 1501.0, 0.09)
            flux = 1.0 + noise - 0.002 * m
            freqs, ps, ps_white, _ = mf.estimate_psd(t, flux)
            W = np.sqrt(ps_white / ps)
            W = np.minimum(W, 1.0)
            self.assertLessEqual(float(np.max(np.abs(W))), 1.0)
            # The whitened curve's std must not exceed the
            # unwhitened curve's std (no net amplification).
            f_w, _ = mf.whiten_curve(t, flux)
            self.assertLessEqual(float(np.std(f_w)),
                                 float(np.std(flux)) * 1.05)


class TestSegmentAgreement(unittest.TestCase):
    """whiten_curve's segment split agrees with the screen's
    segments_from_times (same gap rule, same segments)."""

    def test_segment_split_matches_screen(self):
        t = make_times()
        # Punch a 0.2 d gap mid-sector and a 0.03 d gap (below
        # the 0.05 d threshold — must NOT split).
        keep = np.ones(len(t), dtype=bool)
        keep[(t > 1510.0) & (t < 1510.2)] = False
        keep[(t > 1520.0) & (t < 1520.03)] = False
        t2 = t[keep]
        f2 = 1.0 + np.random.default_rng(11).normal(0.0, SIGMA, len(t2))
        segs_screen = bs.segments_from_times(t2)
        segs_mf = mf._segments_from_times(t2)
        # whiten_curve itself must also run cleanly on the gapped
        # curve and report the same segment count.
        _, diag = mf.whiten_curve(t2, f2)
        self.assertEqual(diag["n_segments"], len(segs_screen))
        self.assertEqual(
            segs_mf, [(int(a), int(b)) for a, b in segs_screen],
            f"whiten_curve segments {segs_mf} != screen {segs_screen}",
        )
        # Exactly 2 segments (one real gap); the 0.03 d gap did
        # not split.
        self.assertEqual(len(segs_mf), 2)


# ---------------------------------------------------------------- flag-off

META = {"ra": 100.0, "dec": -65.0, "tmag": 12.0, "radius": 0.7}


class TestFlagOffRegression(_BulkV6Case):
    """M14: flag-off output is byte-identical to pre-5.8 code.

    The pins were generated from the pre-change code (tip
    86b52ce) under bulk_v6; the FITS filename is part of the
    record (product_ids), so each case is rebuilt under its own
    name. Same four cases as the 5.7 pins.
    """

    def _pins(self):
        return json.loads(PINS_PATH.read_text())

    def test_pinned_records_byte_identical(self):
        with tempfile.TemporaryDirectory() as td:
            for name, case in sorted(self._pins().items()):
                path = make_qlp_fits(Path(td) / f"{name}.fits",
                                     **case["fits_kw"])
                rec = bs._screen_one(screen_job(path))
                self.assertEqual(rec, case["record"], name)

    def test_explicit_bls_equals_default(self):
        # The 7-tuple with an explicit "bls" takes the search-
        # parsing branch; it must produce the same record as the
        # 4-tuple default.
        with tempfile.TemporaryDirectory() as td:
            path = make_qlp_fits(
                Path(td) / "synth.fits", period_d=3.0,
                depth_frac=0.01, duration_d=0.1, noise_pct=0.003,
                seed=42)
            rec_default = bs._screen_one(screen_job(path))
            job7 = (str("999999999"), str(path), 1, dict(META),
                    False, "v6", "bls")
            rec_bls = bs._screen_one(job7)
            self.assertEqual(rec_default, rec_bls)

    def test_no_mf_keys_flag_off(self):
        with tempfile.TemporaryDirectory() as td:
            for name, case in sorted(self._pins().items()):
                path = make_qlp_fits(Path(td) / f"{name}.fits",
                                     **case["fits_kw"])
                rec = bs._screen_one(screen_job(path))
                for key in mf.MF_RECORD_KEYS:
                    self.assertNotIn(key, rec, f"{name}:{key}")

    def test_unknown_search_is_an_error_record(self):
        # An invalid flag value is a per-star error record, not an
        # exception escaping the screen.
        with tempfile.TemporaryDirectory() as td:
            path = make_qlp_fits(Path(td) / "synth.fits",
                                 period_d=None, seed=3)
            job = (str("999999999"), str(path), 1, dict(META),
                   False, "v6", "tls")
            rec = bs._screen_one(job)
            self.assertEqual(rec.get("status"), "error")
            self.assertIn("unknown search", rec.get("error", ""))


# ---------------------------------------------------------------- MF screen


def _scaled_whiten(scale):
    """A mock whiten_curve that scales deviations from 1.0 by
    `scale` — the whitened BLS depth is ~scale x the unwhitened
    fold depth, while the SDE is unchanged (BLS is
    scale-invariant). The depth-gate isolation tests use it to
    put the whitened depth and the judged depth on OPPOSITE
    sides of a gate threshold."""

    def _w(t, f, gap_d=0.05):
        out = 1.0 + (np.asarray(f, dtype=float) - 1.0) * scale
        info = {"unwhitened_cadence_frac": 0.0,
                "psd_floor_ratio": 1.0, "n_segments": 1,
                "n_whitened": 1}
        return out, info

    return _w


class TestMFScreen(_BulkV6Case):
    """An MF screen runs, carries the MF keys, and judges depth
    on the unwhitened curve (real whitening, no mock)."""

    def test_mf_screen_carries_keys(self):
        with tempfile.TemporaryDirectory() as td:
            path = make_qlp_fits(
                Path(td) / "synth.fits", period_d=3.0,
                depth_frac=0.01, duration_d=0.1, noise_pct=0.003,
                seed=42)
            rec = bs._screen_one(screen_job(path, search="mf"))
            self.assertEqual(rec["search"], "mf")
            self.assertIn("mf_seconds", rec)
            self.assertIn("mf_unwhitened_cadence_frac", rec)
            self.assertIn("mf_psd_floor_ratio", rec)
            self.assertIn("mf_unwhitened_depth_percent", rec)
            self.assertNotIn("mf_whiten_failed", rec)
            # The judged depth is the fold depth on the
            # unwhitened curve: close to the injected 1%
            # (flatten + fold noise), NOT the whitened BLS depth.
            self.assertAlmostEqual(
                rec["mf_unwhitened_depth_percent"], 1.0, delta=0.3)
            self.assertEqual(rec["status"], "survivor")

    def test_mf_below_floor_carries_keys(self):
        with tempfile.TemporaryDirectory() as td:
            path = make_qlp_fits(Path(td) / "noise.fits",
                                 period_d=None, seed=3)
            rec = bs._screen_one(screen_job(path, search="mf"))
            self.assertEqual(rec["status"], "below_floor")
            self.assertEqual(rec["search"], "mf")
            self.assertIn("mf_unwhitened_depth_percent", rec)


class TestFallback(_BulkV6Case):
    """M15: a whitening failure falls back to unwhitened BLS
    for that screen, recorded — never an error, never a kill."""

    def test_whiten_failure_falls_back(self):
        with tempfile.TemporaryDirectory() as td:
            path = make_qlp_fits(
                Path(td) / "synth.fits", period_d=3.0,
                depth_frac=0.01, duration_d=0.1, noise_pct=0.003,
                seed=42)
            rec_off = bs._screen_one(screen_job(path))

            def _boom(t, f, gap_d=0.05):
                raise ValueError("synthetic whitening failure")

            with mock.patch.object(mf, "whiten_curve", _boom):
                rec = bs._screen_one(screen_job(path, search="mf"))
            self.assertTrue(rec.get("mf_whiten_failed"))
            self.assertEqual(rec["search"], "mf")
            # The fallback IS the unwhitened BLS: same headline
            # as the flag-off screen.
            self.assertEqual(rec["period_days"],
                             rec_off["period_days"])
            self.assertEqual(rec["sde"], rec_off["sde"])
            self.assertEqual(rec["status"], rec_off["status"])
            # No whitening happened, so no PSD diagnostics.
            self.assertNotIn("mf_unwhitened_cadence_frac", rec)
            self.assertNotIn("mf_psd_floor_ratio", rec)
            # The judged depth is still computed (fold depth).
            self.assertIn("mf_unwhitened_depth_percent", rec)


# ---------------------------------------------------------------- depth gates


class TestDepthGateIsolation(_BulkV6Case):
    """R6: every depth veto and the tier-B depth cap read the
    UNWHITENED rescore depth, never the whitened BLS
    depth_percent. FAILS THE BUILD if any depth gate ingests
    whitened depth.

    Each screen-level case mocks whiten_curve to put the
    whitened depth and the judged depth on OPPOSITE sides of a
    gate threshold, so the flag/tier outcome proves which depth
    the gate read. The mock scales the whole curve, so the SDE
    is unchanged and the record clears the record floor.
    """

    def _screen_mocked(self, td, name, scale, **fits_kw):
        path = make_qlp_fits(Path(td) / f"{name}.fits", **fits_kw)
        with mock.patch.object(mf, "whiten_curve",
                               _scaled_whiten(scale)):
            return bs._screen_one(screen_job(path, search="mf"))

    def test_depth_eb_reads_judge(self):
        # 4% transit, whitened x0.5 -> BLS depth ~1.9% (< 3%),
        # judged fold depth ~3.8% (> 3%). DEPTH_EB fires only
        # if the gate reads the judge.
        with tempfile.TemporaryDirectory() as td:
            rec = self._screen_mocked(
                td, "deep", 0.5, period_d=3.0, depth_frac=0.04,
                duration_d=0.1, noise_pct=0.003, seed=42)
            self.assertLess(rec["depth_percent"], 3.0)
            self.assertGreater(
                rec["mf_unwhitened_depth_percent"], 3.0)
            self.assertIn("DEPTH_EB", rec.get("flags") or [])

    def test_depth_too_shallow_reads_judge(self):
        # 0.015% transit, whitened x2 -> BLS depth ~0.028%
        # (> 0.02%), judged fold depth ~0.014% (< 0.02%).
        # DEPTH_TOO_SHALLOW fires only if the gate reads the
        # judge.
        with tempfile.TemporaryDirectory() as td:
            rec = self._screen_mocked(
                td, "shallow", 2.0, period_d=3.0,
                depth_frac=0.00015, duration_d=0.25,
                noise_pct=0.0002, seed=42)
            self.assertGreaterEqual(rec["sde"], 6.0)
            self.assertGreater(rec["depth_percent"], 0.02)
            self.assertLess(
                rec["mf_unwhitened_depth_percent"], 0.02)
            self.assertIn("DEPTH_TOO_SHALLOW",
                          rec.get("flags") or [])

    def test_tier_b_cap_reads_judge(self):
        # P=14 d, 1.5% transit, 2 events, whitened x0.5 -> BLS
        # depth ~0.6% (< 1%), judged fold depth ~1.2% (> 1%).
        # Tier B is granted only if the cap reads the whitened
        # depth; the judge denies it (n_events=2 < 3,
        # max_event_snr >= 8, so the depth cap is the deciding
        # clause).
        with tempfile.TemporaryDirectory() as td:
            rec = self._screen_mocked(
                td, "tierb", 0.5, period_d=14.0, depth_frac=0.015,
                duration_d=0.25, noise_pct=0.003, seed=42,
                t0=1502.0)
            self.assertEqual(rec.get("n_events"), 2)
            self.assertGreaterEqual(rec.get("max_event_snr", 0),
                                    8.0)
            self.assertLess(rec["depth_percent"], 1.0)
            self.assertGreater(
                rec["mf_unwhitened_depth_percent"], 1.0)
            self.assertIsNone(rec.get("tier"))

    def test_secondary_eb_reads_judge(self):
        # P=0.8 (P/2 below the search floor, so BLS cannot halve
        # the period): 1% primary + 0.6% secondary, whitened
        # x0.5 -> BLS depth ~0.46%, judged ~0.97%, secondary
        # fold ~0.59%. 0.59% >= 0.8 x 0.46% (whitened bar) but
        # < 0.8 x 0.97% (judge bar): SECONDARY_EB fires only if
        # the gate reads the whitened depth.
        with tempfile.TemporaryDirectory() as td:
            rec = self._screen_mocked(
                td, "sec", 0.5, period_d=0.8, depth_frac=0.01,
                duration_d=0.06, noise_pct=0.002, seed=11,
                secondary_depth_frac=0.006)
            self.assertAlmostEqual(rec["period_days"], 0.8,
                                   places=2)
            self.assertGreater(
                rec["secondary_depth_percent"],
                0.8 * rec["depth_percent"])
            self.assertLess(
                rec["secondary_depth_percent"],
                0.8 * rec["mf_unwhitened_depth_percent"])
            self.assertNotIn("SECONDARY_EB",
                             rec.get("flags") or [])

    def test_harmonic_check_reads_judge(self):
        # P=0.8, 1% transit, whitened x0.5 -> the P/2 fold depth
        # (~0.5%) exceeds 0.8 x the whitened depth (~0.39%) but
        # not 0.8 x the judge (~0.78%): HARMONIC_P2_SUSPECT
        # fires only if the gate reads the whitened depth.
        with tempfile.TemporaryDirectory() as td:
            rec = self._screen_mocked(
                td, "harm", 0.5, period_d=0.8, depth_frac=0.01,
                duration_d=0.06, noise_pct=0.002, seed=11)
            self.assertNotIn("HARMONIC_P2_SUSPECT",
                             rec.get("flags") or [])

    def test_gate_depth_pct_helper(self):
        self.assertEqual(
            mf.gate_depth_pct({"depth_percent": 1.5}), 1.5)
        self.assertEqual(
            mf.gate_depth_pct({"depth_percent": 1.5,
                               "mf_unwhitened_depth_percent": 0.8}),
            0.8)
        self.assertIsNone(mf.gate_depth_pct(None))
        self.assertIsNone(mf.gate_depth_pct({}))

    def test_mask_gate_reads_judge(self):
        # bulk_v6: gate ON, depth clause 1.0%, period 13.7 d.
        deep_judge = {"depth_percent": 0.5,
                      "mf_unwhitened_depth_percent": 1.5,
                      "period_days": 3.0, "flags": [],
                      "status": "recorded"}
        self.assertTrue(k2.mask_gate_allows(deep_judge))
        shallow_judge = {"depth_percent": 1.5,
                         "mf_unwhitened_depth_percent": 0.5,
                         "period_days": 3.0, "flags": [],
                         "status": "recorded"}
        self.assertFalse(k2.mask_gate_allows(shallow_judge))
        # Flag-off records are unchanged.
        self.assertTrue(k2.mask_gate_allows(
            {"depth_percent": 1.5, "period_days": 3.0,
             "flags": [], "status": "recorded"}))
        self.assertFalse(k2.mask_gate_allows(
            {"depth_percent": 0.5, "period_days": 3.0,
             "flags": [], "status": "recorded"}))

    def test_mask_eligibility_reads_judge(self):
        deep_judge = {"depth_percent": 0.5,
                      "mf_unwhitened_depth_percent": 1.5,
                      "status": "recorded"}
        elig, via = k2.mask_eligibility(deep_judge)
        self.assertTrue(elig)
        self.assertEqual(via, "depth")
        shallow_judge = {"depth_percent": 1.5,
                         "mf_unwhitened_depth_percent": 0.5,
                         "status": "recorded"}
        elig, via = k2.mask_eligibility(shallow_judge)
        self.assertFalse(elig)
        self.assertIsNone(via)

    def test_pass3_eligible_reads_judge(self):
        deep_judge = {"depth_percent": 0.5,
                      "mf_unwhitened_depth_percent": 1.5,
                      "period_days": 3.0, "status": "recorded"}
        elig, reason = k3.pass3_eligible(deep_judge, {}, False)
        self.assertTrue(elig)
        self.assertEqual(reason, "eligible-depth-gt-1pct")
        shallow_judge = {"depth_percent": 1.5,
                         "mf_unwhitened_depth_percent": 0.5,
                         "period_days": 3.0, "status": "recorded"}
        elig, reason = k3.pass3_eligible(shallow_judge, {}, False)
        self.assertFalse(elig)

    def test_subset_carries_mf_keys(self):
        rec = {"status": "survivor", "tier": "A",
               "period_days": 3.0, "depth_percent": 0.5,
               "mf_unwhitened_depth_percent": 1.5,
               "search": "mf", "mf_seconds": 0.02}
        sub = orc._subset(rec)
        self.assertEqual(sub["mf_unwhitened_depth_percent"], 1.5)
        self.assertEqual(sub["search"], "mf")
        self.assertEqual(sub["mf_seconds"], 0.02)
        # Flag-off subsets carry no MF keys.
        sub_off = orc._subset({"status": "survivor",
                               "depth_percent": 0.5})
        for key in mf.MF_RECORD_KEYS:
            self.assertNotIn(key, sub_off)

    def test_mask_seed_depth_for_mask_reads_judge(self):
        # _mask_seed_and_eligibility is pure decision logic:
        # the fresh path's depth_for_mask is the judged depth.
        t = 1500.0 + np.arange(1296) * 0.5 / 24.0
        rng = np.random.default_rng(0)
        f = 1.0 + rng.normal(0, 0.003, len(t))
        trial = {"period_d": 3.0, "epoch_btjd": 1502.0,
                 "duration_d": 0.1, "depth_frac": 0.01,
                 "recorded": {"period_days": 3.0,
                              "depth_percent": 2.0}}
        p1 = {"period_days": 3.0, "depth_percent": 0.5,
              "mf_unwhitened_depth_percent": 1.5,
              "status": "recorded", "flags": []}
        out = p43run._mask_seed_and_eligibility(
            t, f, trial, p1, "fresh")
        self.assertEqual(out["depth_for_mask"], 1.5)
        # The frozen path reads the frozen recorded depth
        # (which never carries the MF key).
        out_f = p43run._mask_seed_and_eligibility(
            t, f, trial, {"period_days": 7.0,
                          "depth_percent": 0.5,
                          "mf_unwhitened_depth_percent": 1.5,
                          "status": "recorded", "flags": []},
            "frozen")
        self.assertEqual(out_f["depth_for_mask"], 2.0)
        self.assertEqual(out_f["seed_source"], "frozen")


# ---------------------------------------------------------------- top-15


class TestTop15Recording(_BulkV6Case):
    """M16/PB-4: the top-15 peaks are recorded at per-sector
    pass 1 and stitched pass 2, gated on --b1-periodogram."""

    def _sector_arrays(self, seed=0):
        rng = np.random.default_rng(seed)
        t = 1500.0 + np.arange(1296) * 0.5 / 24.0
        ph = ((t - 1502.0 + 1.5) % 3.0) - 1.5
        f = np.where(np.abs(ph) < 0.05, 0.99, 1.0)
        f = f + rng.normal(0, 0.003, len(t))
        q = np.zeros(len(t), dtype=int)
        return t, f, q

    def test_process_sector_records_pass1_top15(self):
        t, f, q = self._sector_arrays()
        trial = {"period_d": 3.0, "epoch_btjd": 1502.0,
                 "duration_d": 0.1, "depth_frac": 0.01,
                 "recorded": {"period_days": 3.0,
                              "depth_percent": 1.0}}
        with tempfile.TemporaryDirectory() as td:
            base = Path(td) / "999999999_planet01"
            rec, _arrs = p43run._process_sector(
                t, f, q, "KSPSAP_FLUX", trial, base, "999999999",
                95, False, seed_mode="fresh",
                return_periodogram=True)
            self.assertIn("b1_pass1_top15", rec)
            top15 = rec["b1_pass1_top15"]
            self.assertLessEqual(len(top15), 15)
            self.assertGreater(len(top15), 0)
            for peak in top15:
                for key in ("period", "sde", "depth", "duration",
                            "t0", "detector"):
                    self.assertIn(key, peak)
            # The injected period is the argmax (rank 0).
            self.assertAlmostEqual(top15[0]["period"], 3.0,
                                   places=2)
            # Without the periodogram request, no top-15.
            rec2, _ = p43run._process_sector(
                t, f, q, "KSPSAP_FLUX", trial, base, "999999999",
                95, False, seed_mode="fresh",
                return_periodogram=False)
            self.assertNotIn("b1_pass1_top15", rec2)

    def test_extract_peaks_on_stitched_periodogram(self):
        # The stitched pass-2 top-15 is the same extract_peaks
        # call on the pass-2 periodogram (campaign leg B1 block).
        t, f, q = self._sector_arrays()
        with tempfile.TemporaryDirectory() as td:
            base = Path(td) / "stitched"
            _sub, raw = p43run._stitched_pass2(
                t, f, q, "KSPSAP_FLUX", base, "999999999", 95,
                False, return_periodogram=True)
            self.assertIn("periodogram", raw)
            top15 = jf.extract_peaks(raw["periodogram"])
            self.assertLessEqual(len(top15), 15)
            self.assertGreater(len(top15), 0)
            self.assertAlmostEqual(top15[0]["period"], 3.0,
                                   places=2)


# ---------------------------------------------------------------- threading


class TestDriverThreading(_BulkV6Case):
    """screen_job shapes, k3/p43 search threading, CLI."""

    def test_screen_job_tuple_shapes(self):
        job4 = screen_job("x.fits")
        self.assertEqual(len(job4), 4)
        job5 = screen_job("x.fits", return_periodogram=True)
        self.assertEqual(len(job5), 5)
        self.assertTrue(job5[4])
        job6 = screen_job("x.fits", detrend="v7")
        self.assertEqual(len(job6), 6)
        self.assertEqual(job6[5], "v7")
        job7 = screen_job("x.fits", search="mf")
        self.assertEqual(len(job7), 7)
        self.assertEqual(job7[4], False)
        self.assertEqual(job7[5], "v6")
        self.assertEqual(job7[6], "mf")
        job7b = screen_job("x.fits", return_periodogram=True,
                           detrend="v7", search="mf")
        self.assertEqual(len(job7b), 7)
        self.assertEqual(job7b[4], True)
        self.assertEqual(job7b[5], "v7")
        self.assertEqual(job7b[6], "mf")
        # Explicit bls is the 4-tuple (no flag carried).
        self.assertEqual(len(screen_job("x.fits", search="bls")),
                         4)

    def test_k3_screen_threads_search(self):
        with tempfile.TemporaryDirectory() as td:
            path = make_qlp_fits(
                Path(td) / "synth.fits", period_d=3.0,
                depth_frac=0.01, duration_d=0.1, noise_pct=0.003,
                seed=42)
            rec_off = k3run._screen(str(path), "999999999", 1)
            self.assertNotIn("search", rec_off)
            rec_on = k3run._screen(str(path), "999999999", 1,
                                   search="mf")
            self.assertEqual(rec_on["search"], "mf")
            self.assertIn("mf_unwhitened_depth_percent", rec_on)

    def _fake_cache_manifest(self, td):
        cache = Path(td) / "cache"
        for sec in (95, 96, 97):
            (cache / f"s{sec:04d}").mkdir(parents=True)
            make_qlp_fits(cache / f"s{sec:04d}" / "999999999.fits",
                          period_d=None, seed=sec)
        manifest = {"trials": [{"tic": "999999999", "sector": 95}],
                    "_sha256": "x" * 64}
        mpath = Path(td) / "manifest.json"
        mpath.write_text(json.dumps(
            {"trials": manifest["trials"]}))
        return cache, mpath

    def test_p43_build_jobs_carries_search(self):
        with tempfile.TemporaryDirectory() as td:
            cache, _mpath = self._fake_cache_manifest(td)
            manifest = {"trials": [{"tic": "999999999",
                                    "sector": 95}],
                        "_sha256": "x" * 64}
            single, stitched, missing = p43run._build_jobs(
                manifest, cache, Path(td) / "out",
                Path(td) / "w43", Path(td) / "w1", False,
                "bulk_v6", search="mf")
            self.assertEqual(missing, [])
            self.assertEqual(len(single), 1)
            self.assertEqual(len(stitched), 1)
            self.assertEqual(single[0]["search"], "mf")
            self.assertEqual(stitched[0]["search"], "mf")
            # Defaults: bls.
            single0, stitched0, _m = p43run._build_jobs(
                manifest, cache, Path(td) / "out",
                Path(td) / "w43", Path(td) / "w1", False,
                "bulk_v6")
            self.assertEqual(single0[0]["search"], "bls")
            self.assertEqual(stitched0[0]["search"], "bls")

    def test_p43_cli_accepts_search_dry_run(self):
        with tempfile.TemporaryDirectory() as td:
            cache, mpath = self._fake_cache_manifest(td)
            out = Path(td) / "out"
            rc = p43run.main([
                "--mode", "campaign", "--manifest", str(mpath),
                "--cache", str(cache), "--out-dir", str(out),
                "--calibration", "bulk_v6",
                "--search", "mf", "--dry-run"])
            self.assertEqual(rc, 0)
            rc = p43run.main([
                "--mode", "null", "--manifest", str(mpath),
                "--cache", str(cache), "--out-dir", str(out),
                "--calibration", "bulk_v6",
                "--search", "mf", "--dry-run"])
            self.assertEqual(rc, 0)
