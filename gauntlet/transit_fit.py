#!/usr/bin/env python3
"""Formal transit fit (gauntlet step 6): batman + emcee.

Data: pipeline sectors (transit-masked SG-flattened raw flux) +
TESSCut sectors (flux_detrended, or flux_bgreg with --variant bgreg).
Model: batman quadratic limb darkening, circular orbit, one model per
sector (own exposure time / supersampling), per-sector offsets solved
analytically.

Stages:
  ls    — least-squares fit, free limb darkening (Kipping q1, q2).
          Writes ls_fit.json. Fast.
  mcmc  — emcee run from the fixed-LD least-squares solution (the
          primary posterior: free LD runs to unphysical values for a
          grazing transit and is not used for the primary posterior).
          Per-sector sigmas are rescaled by the LS chi2_red. Writes
          mcmc_chain.npz. Slow (~15 min on a laptop; longer on a
          weak VM — run in the background).

Requires SETUPTOOLS_USE_DISTUTILS=local in the environment (batman
2.5.x imports distutils, removed from Python 3.12 stdlib; setuptools
69 shims it) — set automatically here.

Usage:
  transit_fit.py TIC ls --period P --t0 T0 --duration DUR \\
      --data-dir data/ --qlp-sectors 32 98 --tesscut-sectors 107 108 \\
      --depth-pct 1.03 --r-star 0.673 --m-star 0.81 --outdir work/TIC
  transit_fit.py TIC mcmc ... (same arguments) [--seed SEED]
      [--mcmc-start P,T0,rp,a,b] [--walkers 28 --burn 500 --steps 3000]

Generalised from transit_fit_423498314.py (2026-11-13): hardcoded
star/sectors/stellar values/bounds became CLI arguments. The model,
residuals (with the analytic-offset recipe — see the comment in
FitModel.residuals), bounds derivation (P +/- 0.00015 d, T0 +/- 0.02
d), density prior (a/R* from M/R/P, sigma from the stellar errors)
and MCMC setup are unchanged. Exposure times are inferred from the
median cadence of each sector's data; supersampling defaults to 2
with per-sector overrides (--supersample "32:3").
"""
import os

os.environ.setdefault('SETUPTOOLS_USE_DISTUTILS', 'local')
import setuptools  # noqa: F401  (shims distutils for batman)
import argparse
import json

import numpy as np
from scipy.optimize import least_squares
from scipy.signal import savgol_filter

RSUN_RE = 109.2                    # R_sun in R_earth
RSUN_AU = 0.00465047               # R_sun in AU


def flatten_qlp(t, f, period, t0, duration_d, window=1.5):
    """Transit-masked Savitzky-Golay flatten (the holdout recipe)."""
    order = np.argsort(t)
    t, f = t[order], f[order]
    dt = np.median(np.diff(t))
    w = int(window / dt)
    w = w if w % 2 == 1 else w + 1
    w = max(w, 51)
    ph = (((t - t0) / period + 0.5) % 1.0) - 0.5
    m = np.abs(ph) < (duration_d / period)
    f2 = np.where(m, np.nan, f)
    good = np.isfinite(f2)
    f_fill = np.interp(t, t[good], f2[good])
    trend = savgol_filter(f_fill, w, 3)
    return t, f / trend


def parse_supersample(spec):
    """'32:3,98:2' -> {32: 3, 98: 2}."""
    out = {}
    for part in (spec or '').split(','):
        part = part.strip()
        if not part:
            continue
        sec, val = part.split(':')
        out[int(sec)] = int(val)
    return out


def load_data(data_dir, qlp_sectors, tesscut_sectors, period, t0,
              duration_d, variant='detrended', supersample=None,
              supersample_default=2):
    """Return list of dicts: sector, t, f, sigma, exp_time_d,
    supersample. Exposure times are inferred from the median cadence
    of each sector's data."""
    supersample = supersample or {}
    out = []
    for sec in qlp_sectors:
        z = np.load(os.path.join(data_dir, f'qlp_s{sec:03d}.npz'))
        t = np.asarray(z['time'], float)
        f = np.asarray(z['flux'], float)
        exp_s = float(np.median(np.diff(np.sort(t))) * 86400.0)
        t, f = flatten_qlp(t, f, period, t0, duration_d)
        out.append(dict(sector=sec, t=t, f=f,
                        exp_time_d=exp_s / 86400.0,
                        supersample=supersample.get(sec,
                                                    supersample_default)))
    key = 'flux_detrended' if variant == 'detrended' else 'flux_bgreg'
    for sec in tesscut_sectors:
        z = np.load(os.path.join(data_dir, f'tesscut_s{sec:03d}.npz'))
        t = np.asarray(z['time'], float)
        f = np.asarray(z[key], float)
        exp_s = float(np.median(np.diff(np.sort(t))) * 86400.0)
        out.append(dict(sector=sec, t=t, f=f,
                        exp_time_d=exp_s / 86400.0,
                        supersample=supersample.get(sec,
                                                    supersample_default)))
    # per-sector: median-normalise, asymmetric sigma-clip 5 sigma (MAD),
    # sigma from out-of-transit MAD. The lower cut is floored at 10%
    # below the median (2026-11-14, TIC 139526205 — same fix as
    # rawflux_check.py): a symmetric 5-sigma cut deletes real transits
    # on quiet stars before the fit, biasing depth / Rp low.
    for d in out:
        d['f'] = d['f'] / np.median(d['f'])
        med = np.median(d['f'])
        mad = 1.4826 * np.median(np.abs(d['f'] - med))
        keep = (d['f'] < med + 5 * mad) & (d['f'] > med - max(5 * mad, 0.10))
        d['t'], d['f'] = d['t'][keep], d['f'][keep]
        ph = (((d['t'] - t0) / period + 0.5) % 1.0) - 0.5
        oot = np.abs(ph) > 0.08
        d['sigma'] = float(1.4826 * np.median(np.abs(
            d['f'][oot] - np.median(d['f'][oot]))))
        d['n_clipped'] = int((~keep).sum())
    return out


def q_to_u(q1, q2):
    s = np.sqrt(max(q1, 0.0))
    return 2 * s * q2, s * (1 - 2 * q2)


def a_prior_from_stellar(m_star, m_star_err, r_star, r_star_err, period):
    """Stellar-density prior on a/R* for a circular orbit:
    (a/R*)^3 = rho* G P^2 / (3 pi). Returns (a_prior, a_prior_sigma),
    with sigma from the stellar mass/radius errors
    (sigma(rho)/rho = sqrt((dM/M)^2 + (3 dR/R)^2); sigma(a)/a = that/3).
    """
    a_prior = 4.2083 * (m_star ** (1.0 / 3.0)) * (period ** (2.0 / 3.0)) / r_star
    sig_rho_frac = np.sqrt((m_star_err / m_star) ** 2
                           + (3 * r_star_err / r_star) ** 2)
    return a_prior, a_prior * sig_rho_frac / 3.0


class FitModel:
    """batman models, one per sector (own exposure time / supersampling)."""

    def __init__(self, data, period0, t0_0, fixed_ld=None):
        import batman
        self.batman = batman
        self.data = data
        self.fixed_ld = fixed_ld  # (u1, u2) or None for free LD
        self.models = []
        for d in data:
            p = batman.TransitParams()
            p.t0, p.per, p.rp, p.a, p.inc = t0_0, period0, 0.10, 5.1, 87.0
            p.ecc, p.w = 0.0, 90.0
            p.limb_dark = 'quadratic'
            p.u = [0.4, 0.2]
            m = batman.TransitModel(p, d['t'], exp_time=d['exp_time_d'],
                                    supersample_factor=d['supersample'])
            self.models.append((p, m))

    def model_all(self, theta):
        """theta = [P, T0, rp, a, b, q1, q2] (q's ignored if fixed_ld)."""
        P, T0, rp, a, b = theta[:5]
        if self.fixed_ld is not None:
            u1, u2 = self.fixed_ld
        else:
            u1, u2 = q_to_u(theta[5], theta[6])
        inc = np.degrees(np.arccos(np.clip(b / a, -1, 1)))
        out = []
        for (p, m), d in zip(self.models, self.data):
            p.t0, p.per, p.rp, p.a, p.inc = T0, P, rp, a, inc
            p.u = [u1, u2]
            out.append(m.light_curve(p))
        return out

    def residuals(self, theta, sigmas=None, return_models=False):
        """Residuals with per-sector offsets solved analytically."""
        models = self.model_all(theta)
        res = []
        offs = []
        for mod, d in zip(models, self.data):
            sig = d['sigma'] if sigmas is None else sigmas[d['sector']]
            # sigma is constant per sector, so the weighted mean is the
            # plain mean (np.sum of a scalar weight is the weight itself,
            # NOT weight*n — do not "simplify" this back to a ratio of sums)
            off = float(np.mean(d['f'] - mod))
            offs.append(off)
            res.append((d['f'] - mod - off) / sig)
        if return_models:
            return np.concatenate(res), offs, models
        return np.concatenate(res)

    def chi2_per_sector(self, theta, sigmas=None):
        models = self.model_all(theta)
        out = {}
        for mod, d in zip(models, self.data):
            sig = d['sigma'] if sigmas is None else sigmas[d['sector']]
            off = float(np.mean(d['f'] - mod))
            chi2 = float(np.sum(((d['f'] - mod - off) / sig) ** 2))
            out[d['sector']] = dict(chi2=chi2, n=len(d['t']),
                                    chi2_red=chi2 / len(d['t']))
        return out


def bounds_theta0(period, t0, depth_pct, a_prior):
    """Bounds and starting point, derived from the ephemeris:
    P +/- 0.00015 d, T0 +/- 0.02 d, rp 0.05-0.40 (start sqrt(depth)),
    a 2-15 (start the density-prior value), b 0-1.30 (start 0.3),
    q1/q2 0-1 (start 0.4/0.3)."""
    lo = np.array([period - 0.00015, t0 - 0.02, 0.05, 2.0, 0.0, 0.0, 0.0])
    hi = np.array([period + 0.00015, t0 + 0.02, 0.40, 15.0, 1.30, 1.0, 1.0])
    th0 = np.array([period, t0, np.sqrt(depth_pct / 100.0), a_prior,
                    0.3, 0.4, 0.3])
    return lo, hi, th0


def run_ls(data, period, t0, bounds_lo, bounds_hi, theta0,
           fixed_ld=None, density_prior=False, a_prior=None,
           a_prior_sig=None):
    fm = FitModel(data, period, t0, fixed_ld=fixed_ld)

    def resid_with_prior(th):
        r = fm.residuals(th)
        if density_prior:
            r = np.concatenate([r, [(th[3] - a_prior) / a_prior_sig]])
        return r

    if fixed_ld is not None:
        def resid5(x):
            return resid_with_prior(np.concatenate([x, [0.4, 0.3]]))
        r = least_squares(resid5, theta0[:5],
                          bounds=(bounds_lo[:5], bounds_hi[:5]),
                          xtol=1e-12, ftol=1e-12)
        theta = np.concatenate([r.x, [0.4, 0.3]])
    else:
        r = least_squares(resid_with_prior, theta0,
                          bounds=(bounds_lo, bounds_hi),
                          xtol=1e-12, ftol=1e-12)
        theta = r.x
    chi2 = float(np.sum(fm.residuals(theta) ** 2))
    npts = sum(len(d['t']) for d in data)
    return fm, theta, chi2, npts


def t14_days(P, rp, a, b):
    """Full transit duration (Mandel & Agol geometry, circular orbit)."""
    inc = np.arccos(np.clip(b / a, -1, 1))
    arg = np.sqrt(max((1 + rp) ** 2 - b ** 2, 0.0)) / (a * np.sin(inc))
    return (P / np.pi) * np.arcsin(np.clip(arg, -1, 1))


def build_parser():
    ap = argparse.ArgumentParser(
        description='Formal transit fit (batman + emcee): ls = free-LD '
                    'least squares; mcmc = fixed-LD emcee from the LS '
                    'solution.')
    ap.add_argument('tic')
    ap.add_argument('stage', choices=['ls', 'mcmc'])
    ap.add_argument('--period', type=float, required=True)
    ap.add_argument('--t0', type=float, required=True)
    ap.add_argument('--duration', type=float, required=True,
                    help='transit duration in days (flatten mask)')
    ap.add_argument('--data-dir', required=True)
    ap.add_argument('--qlp-sectors', type=int, nargs='*', default=[],
                    help='pipeline sectors to flatten from raw flux')
    ap.add_argument('--tesscut-sectors', type=int, nargs='*', default=[],
                    help='TESSCut sectors (flux_detrended / flux_bgreg)')
    ap.add_argument('--variant', default='detrended',
                    choices=['detrended', 'bgreg'],
                    help='TESSCut flux variant (default detrended)')
    ap.add_argument('--depth-pct', type=float, default=1.0,
                    help='observed depth in percent (sets the rp start)')
    ap.add_argument('--r-star', type=float, required=True)
    ap.add_argument('--r-star-err', type=float, required=True)
    ap.add_argument('--m-star', type=float, required=True)
    ap.add_argument('--m-star-err', type=float, required=True)
    ap.add_argument('--ld-u1', type=float, default=0.4,
                    help='fixed limb-darkening u1 for the MCMC stage')
    ap.add_argument('--ld-u2', type=float, default=0.2,
                    help='fixed limb-darkening u2 for the MCMC stage')
    ap.add_argument('--supersample', default='',
                    help='per-sector supersampling overrides, "32:3,98:2"')
    ap.add_argument('--seed', type=int, default=None,
                    help='MCMC walker-init seed (default: TIC id)')
    ap.add_argument('--mcmc-start', default=None,
                    help='fixed-LD LS starting point for the MCMC stage, '
                         '"P,T0,rp,a,b" (default: the free-LD LS theta)')
    ap.add_argument('--walkers', type=int, default=28)
    ap.add_argument('--burn', type=int, default=500)
    ap.add_argument('--steps', type=int, default=3000)
    ap.add_argument('--outdir', required=True)
    return ap


def main(argv=None):
    args = build_parser().parse_args(argv)
    os.makedirs(args.outdir, exist_ok=True)
    a_prior, a_prior_sig = a_prior_from_stellar(
        args.m_star, args.m_star_err, args.r_star, args.r_star_err,
        args.period)
    lo, hi, th0 = bounds_theta0(args.period, args.t0, args.depth_pct,
                                a_prior)
    print(f'density prior: a/R* = {a_prior:.2f} +- {a_prior_sig:.2f}',
          flush=True)
    data = load_data(args.data_dir, args.qlp_sectors,
                     args.tesscut_sectors, args.period, args.t0,
                     args.duration, variant=args.variant,
                     supersample=parse_supersample(args.supersample))
    for d in data:
        print(f"sector {d['sector']}: n={len(d['t'])} "
              f"sigma={d['sigma'] * 100:.3f}% clipped={d['n_clipped']} "
              f"span={d['t'].min():.1f}-{d['t'].max():.1f}",
              flush=True)
    if args.stage == 'ls':
        fm, theta, chi2, npts = run_ls(data, args.period, args.t0,
                                       lo, hi, th0)
        print('LS theta:', theta, flush=True)
        print(f'chi2={chi2:.1f} npts={npts} dof={npts - 7} '
              f'chi2_red={chi2 / (npts - 7):.3f}', flush=True)
        print('per-sector chi2:',
              json.dumps(fm.chi2_per_sector(theta), indent=1), flush=True)
        t14 = t14_days(theta[0], theta[2], theta[3], theta[4])
        print(f'T14 = {t14:.4f} d = {t14 * 24:.3f} h', flush=True)
        u1, u2 = q_to_u(theta[5], theta[6])
        print(f'LD: u1={u1:.3f} u2={u2:.3f} '
              f'(q1={theta[5]:.3f} q2={theta[6]:.3f})', flush=True)
        json.dump({'theta_ls': [float(x) for x in theta], 'chi2': chi2,
                   'npts': npts,
                   'chi2_per_sector': fm.chi2_per_sector(theta)},
                  open(os.path.join(args.outdir, 'ls_fit.json'), 'w'),
                  indent=2)
        print('wrote ls_fit.json', flush=True)
    elif args.stage == 'mcmc':
        # PRIMARY MCMC: fixed physical limb darkening, no density
        # prior — the data's preferred solution (grazing, for
        # 423498314). Free LD runs to unphysical values and is not
        # used for the primary posterior.
        import emcee
        ls = json.load(open(os.path.join(args.outdir, 'ls_fit.json')))
        theta_ls = np.array(ls['theta_ls'])
        if args.mcmc_start:
            start = np.array([float(v)
                              for v in args.mcmc_start.split(',')])
            start7 = np.concatenate([start, [0.4, 0.3]])
        else:
            start7 = theta_ls
        fm0, th_fix, chi2_fix, _ = run_ls(
            data, args.period, args.t0, lo, hi, start7,
            fixed_ld=(args.ld_u1, args.ld_u2))
        print(f'fixed-LD LS start: P={th_fix[0]:.6f} rp={th_fix[2]:.4f} '
              f'a={th_fix[3]:.3f} b={th_fix[4]:.3f} chi2={chi2_fix:.1f}',
              flush=True)
        sigmas = {}
        for d in data:
            r = ls['chi2_per_sector'][str(d['sector'])]['chi2_red']
            sigmas[d['sector']] = d['sigma'] * np.sqrt(max(r, 1.0))
            print(f"sector {d['sector']}: chi2_red={r:.3f} -> "
                  f"sigma x{np.sqrt(max(r, 1.0)):.3f}", flush=True)
        fm = FitModel(data, args.period, args.t0,
                      fixed_ld=(args.ld_u1, args.ld_u2))
        lo5, hi5 = lo[:5], hi[:5]

        def log_prior(th5):
            if np.all(th5 >= lo5) and np.all(th5 <= hi5):
                return 0.0
            return -np.inf

        def log_prob(th5):
            lp = log_prior(th5)
            if not np.isfinite(lp):
                return -np.inf
            th = np.concatenate([th5, [0.4, 0.3]])
            res = fm.residuals(th, sigmas=sigmas)
            return -0.5 * np.sum(res ** 2)

        ndim, nwalk = 5, args.walkers
        seed = args.seed if args.seed is not None else int(args.tic)
        rng = np.random.default_rng(seed)
        spread = np.array([2e-6, 2e-4, 0.01, 0.15, 0.05])
        p0 = th_fix[:5] + spread * rng.standard_normal((nwalk, ndim))
        p0 = np.clip(p0, lo5 + 1e-9, hi5 - 1e-9)
        sampler = emcee.EnsembleSampler(nwalk, ndim, log_prob)
        print(f'burn-in {args.burn}...', flush=True)
        p0, _, _ = sampler.run_mcmc(p0, args.burn, progress=False)
        sampler.reset()
        print(f'production {args.steps}...', flush=True)
        sampler.run_mcmc(p0, args.steps, progress=False)
        print('acceptance:', np.round(sampler.acceptance_fraction, 3),
              flush=True)
        try:
            tau = sampler.get_autocorr_time()
            print('autocorr times:', np.round(tau, 1), flush=True)
        except Exception as e:
            print('autocorr failed:', e, flush=True)
            tau = None
        chain = sampler.get_chain(flat=True)
        sectors = [d['sector'] for d in data]
        np.savez(os.path.join(args.outdir, 'mcmc_chain.npz'), chain=chain,
                 theta_ls=th_fix,
                 sigmas=np.array([sigmas[s] for s in sectors]),
                 tau=np.array(tau) if tau is not None else np.array([]),
                 fixed_ld=np.array([args.ld_u1, args.ld_u2]))
        med = np.median(chain, axis=0)
        lo_q = np.percentile(chain, 16, axis=0)
        hi_q = np.percentile(chain, 84, axis=0)
        names = ['P', 'T0', 'rp', 'a', 'b']
        for n, m, l, h in zip(names, med, lo_q, hi_q):
            print(f'{n}: {m:.6g} +{h - m:.3g} -{m - l:.3g}', flush=True)
        print('wrote mcmc_chain.npz', flush=True)


if __name__ == '__main__':
    main()
