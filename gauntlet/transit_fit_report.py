#!/usr/bin/env python3
"""Derived values + plots from a transit-fit MCMC chain.

Reads mcmc_chain.npz (from transit_fit.py mcmc). Writes
transit_fit.json, fit_transit.png (per-sector folded data + model +
residuals) and fit_profile_compare.png (combined fold vs the fitted
model, plus an optional desk box-like comparison model).

Derived quantities are computed per-sample from the chain (Rp, a,
Teq, circular-orbit stellar density) with Monte-Carlo stellar
parameters; the mass and RV semi-amplitude use the Chen & Kipping
(2017) Neptunian mass-radius relation and are labelled
model_dependent — at Rp ~ 14 R_earth the prediction sits at the
Neptunian/Jovian transition, so the mass is highly model-dependent.

Usage:
  transit_fit_report.py TIC --chain mcmc_chain.npz --data-dir data/ \\
      --qlp-sectors 32 98 --tesscut-sectors 107 108 \\
      --period P --t0 T0 --duration DUR \\
      --r-star 0.673 --r-star-err 0.04 --m-star 0.81 --m-star-err 0.08 \\
      --teff 4917 --teff-err 122 --outdir work/TIC \\
      [--desk-rp 0.1015 --desk-a 5.1 --desk-b 0.3] \\
      [--stellar-errors-adopted]

Generalised from transit_fit_report.py (TIC 423498314, 2026-11-13):
hardcoded star/sectors/stellar values became CLI arguments; the
derived-value code (including the seed-7 Monte Carlo) is unchanged.
The figure layout generalises to N sectors (the original had 4).
"""
import os
import sys

os.environ.setdefault('SETUPTOOLS_USE_DISTUTILS', 'local')
import setuptools  # noqa: F401
import argparse
import json

import numpy as np
import matplotlib

matplotlib.use('Agg')
import matplotlib.pyplot as plt

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from gauntlet.transit_fit import (RSUN_AU, RSUN_RE, FitModel,
                                      load_data, parse_supersample,
                                      t14_days)
except ImportError:  # run as a plain script from the gauntlet dir
    from transit_fit import (RSUN_AU, RSUN_RE, FitModel, load_data,
                             parse_supersample, t14_days)

G = 6.67430e-11
RHO_SUN = 1408.0  # kg/m^3
MJUP_ME = 317.828  # M_jup in M_earth


def qsum(x):
    med = float(np.median(x))
    return (med, float(med - np.percentile(x, 16)),
            float(np.percentile(x, 84) - med))


def main(argv=None):
    ap = argparse.ArgumentParser(
        description='Derived values + plots from a transit-fit MCMC '
                    'chain.')
    ap.add_argument('tic')
    ap.add_argument('--chain', required=True,
                    help='mcmc_chain.npz from transit_fit.py mcmc')
    ap.add_argument('--data-dir', required=True)
    ap.add_argument('--qlp-sectors', type=int, nargs='*', default=[])
    ap.add_argument('--tesscut-sectors', type=int, nargs='*', default=[])
    ap.add_argument('--period', type=float, required=True)
    ap.add_argument('--t0', type=float, required=True)
    ap.add_argument('--duration', type=float, required=True)
    ap.add_argument('--variant', default='detrended',
                    choices=['detrended', 'bgreg'])
    ap.add_argument('--supersample', default='')
    ap.add_argument('--r-star', type=float, required=True)
    ap.add_argument('--r-star-err', type=float, required=True)
    ap.add_argument('--m-star', type=float, required=True)
    ap.add_argument('--m-star-err', type=float, required=True)
    ap.add_argument('--teff', type=float, required=True)
    ap.add_argument('--teff-err', type=float, required=True)
    ap.add_argument('--ld-u1', type=float, default=0.4)
    ap.add_argument('--ld-u2', type=float, default=0.2)
    ap.add_argument('--desk-rp', type=float, default=None,
                    help='desk box-like comparison model Rp/R*')
    ap.add_argument('--desk-a', type=float, default=None)
    ap.add_argument('--desk-b', type=float, default=None)
    ap.add_argument('--stellar-errors-adopted', action='store_true',
                    help='note that the stellar errors are adopted, not '
                         'catalogued (TIC publishes no R*/M* errors for '
                         'some stars)')
    ap.add_argument('--walkers', type=int, default=28,
                    help='MCMC walker count (provenance only)')
    ap.add_argument('--steps', type=int, default=3000,
                    help='MCMC production steps (provenance only)')
    ap.add_argument('--outdir', required=True)
    args = ap.parse_args(argv)
    os.makedirs(args.outdir, exist_ok=True)

    R_STAR, R_STAR_ERR = args.r_star, args.r_star_err
    M_STAR, M_STAR_ERR = args.m_star, args.m_star_err
    TEFF, TEFF_ERR = args.teff, args.teff_err

    z = np.load(args.chain)
    chain = z['chain']  # (nsamp, 5): P, T0, rp, a, b
    print(f"chain: {chain.shape}, tau={z['tau']}")
    P, T0, rp, a, b = chain.T
    rng = np.random.default_rng(7)
    n = len(chain)

    # --- derived quantities, per-sample ---
    t14 = np.array([t14_days(p, r, aa, bb) for p, r, aa, bb in
                    zip(P, rp, a, b)]) * 24.0  # hours
    rstar = rng.normal(R_STAR, R_STAR_ERR, n)
    mstar = rng.normal(M_STAR, M_STAR_ERR, n)
    teff = rng.normal(TEFF, TEFF_ERR, n)
    Rp = rp * rstar * RSUN_RE                       # R_earth
    a_au = a * rstar * RSUN_AU                      # AU
    a_rsun = a * rstar                              # R_sun
    teq = teff * np.sqrt(rstar * RSUN_AU / (2 * a_au))  # A=0
    rho_star = (3 * np.pi * a ** 3 / (G * (P * 86400.0) ** 2)
                / RHO_SUN)  # rho_sun
    inc = np.degrees(np.arccos(np.clip(b / a, -1, 1)))

    # Chen & Kipping (2017) Neptunian branch: R = 0.81 * M^0.59 (R in
    # R_e, M in M_e); invert. MC over Rp samples + hyperparameter
    # errors (C = 0.81 +- 0.05, S = 0.59 +- 0.035).
    C = rng.normal(0.81, 0.05, n)
    S = rng.normal(0.59, 0.035, n)
    Mp = (Rp / C) ** (1.0 / S)                      # M_earth
    # RV semi-amplitude (circular, sin i ~ 1)
    K = (28.4329 * (Mp / MJUP_ME) * (P / 365.25) ** (-1.0 / 3.0)
         * (mstar) ** (-2.0 / 3.0))

    out = {'fitted': {}, 'derived': {}, 'model_dependent': {}}
    for name, arr, unit in [('P_d', P, 'd'), ('T0_BTJD', T0, 'BTJD'),
                            ('Rp_Rstar', rp, ''), ('a_Rstar', a, ''),
                            ('b', b, ''), ('inc_deg', inc, 'deg'),
                            ('T14_h', t14, 'h')]:
        med, lo, hi = qsum(arr)
        out['fitted'][name] = {'median': med, 'minus': lo, 'plus': hi,
                               'unit': unit}
    for name, arr, unit in [('Rp_Rearth', Rp, 'R_earth'),
                            ('a_AU', a_au, 'AU'),
                            ('a_Rsun', a_rsun, 'R_sun'),
                            ('Teq_K', teq, 'K'),
                            ('rho_star_rhosun', rho_star, 'rho_sun')]:
        med, lo, hi = qsum(arr)
        out['derived'][name] = {'median': med, 'minus': lo, 'plus': hi,
                                'unit': unit}
    for name, arr, unit in [('Mp_Mearth_CK17_Neptunian', Mp, 'M_earth'),
                            ('K_ms', K, 'm/s')]:
        med, lo, hi = qsum(arr)
        out['model_dependent'][name] = {'median': med, 'minus': lo,
                                        'plus': hi, 'unit': unit}
    # model depth at mid-transit (fine grid, median params)
    import batman
    p = batman.TransitParams()
    med = np.median(chain, axis=0)
    p.t0, p.per, p.rp, p.a = med[1], med[0], med[2], med[3]
    p.inc = float(np.median(inc))
    p.ecc, p.w = 0.0, 90.0
    p.limb_dark, p.u = 'quadratic', [args.ld_u1, args.ld_u2]
    tg = np.linspace(med[1] - 0.1, med[1] + 0.1, 4000)
    m = batman.TransitModel(p, tg)
    depth = float(1 - m.light_curve(p).min())
    out['derived']['model_depth_pct'] = {'value': depth * 100, 'unit': '%'}
    notes = [
        'Teq assumes albedo 0 and full redistribution.',
        'Mass/K use Chen & Kipping (2017) Neptunian branch '
        'R=0.81*M^0.59; at Rp~14 R_earth the prediction sits at the '
        'Neptunian/Jovian transition (~132 M_earth), so the mass is '
        'highly model-dependent and the quoted error covers only Rp + '
        'hyperparameter uncertainty, NOT the intrinsic scatter of the '
        'relation or the regime ambiguity.',
    ]
    if args.stellar_errors_adopted:
        notes.insert(0, 'R*/M* errors are ADOPTED (TIC gives no errors '
                        'for this star): 6% R*, 10% M*.')
    out['meta'] = {
        'model': ('batman quadratic LD, circular orbit, fixed LD '
                  f'u1={args.ld_u1} u2={args.ld_u2}'),
        'data': (f"QLP s{'+s'.join(map(str, args.qlp_sectors))} "
                 f'(transit-masked SG-flattened) + TESSCut '
                 f"s{'+s'.join(map(str, args.tesscut_sectors))} "
                 f'({args.variant})'),
        'n_samples': int(n),
        'n_walkers': args.walkers,
        'n_steps_production': args.steps,
        'autocorr_time': ([float(v) for v in z['tau']]
                          if len(z['tau']) else None),
        'stellar_assumed': {'Rstar_Rsun': R_STAR,
                            'Rstar_err_Rsun': R_STAR_ERR,
                            'Mstar_Msun': M_STAR,
                            'Mstar_err_Msun': M_STAR_ERR,
                            'Teff_K': TEFF, 'Teff_err_K': TEFF_ERR},
        'notes': notes,
    }
    json.dump(out, open(os.path.join(args.outdir, 'transit_fit.json'),
                        'w'), indent=2)
    for k, v in out['fitted'].items():
        print(f"{k}: {v['median']:.6g} +{v['plus']:.3g} "
              f"-{v['minus']:.3g} {v['unit']}")
    for k, v in out['derived'].items():
        if 'value' in v:
            print(f"{k}: {v['value']:.4g} {v['unit']}")
        else:
            print(f"{k}: {v['median']:.6g} +{v['plus']:.3g} "
                  f"-{v['minus']:.3g} {v['unit']}")
    for k, v in out['model_dependent'].items():
        print(f"{k}: {v['median']:.6g} +{v['plus']:.3g} "
              f"-{v['minus']:.3g} {v['unit']}")

    # --- plots ---
    data = load_data(args.data_dir, args.qlp_sectors,
                     args.tesscut_sectors, args.period, args.t0,
                     args.duration, variant=args.variant,
                     supersample=parse_supersample(args.supersample))
    th_med = np.concatenate([med, [0.4, 0.3]])
    fm = FitModel(data, args.period, args.t0,
                  fixed_ld=(args.ld_u1, args.ld_u2))
    models = fm.model_all(th_med)

    # Fig 1: per-sector phase-folded binned data + model + residuals
    nsec = len(data)
    fig, axes = plt.subplots(nsec, 2, figsize=(10, 2.5 * nsec),
                             gridspec_kw={'width_ratios': [3, 1],
                                          'hspace': 0.35, 'wspace': 0.12})
    if nsec == 1:
        axes = axes.reshape(1, 2)
    for i, (d, mod) in enumerate(zip(data, models)):
        ph = (((d['t'] - med[1]) / med[0] + 0.5) % 1.0) - 0.5
        x = ph * med[0] * 24.0
        ax = axes[i, 0]
        ax.plot(x, (d['f'] - 1) * 100, '.', ms=1.0, alpha=0.2,
                color='#888888')
        eb = np.linspace(-1.5, 1.5, 61)
        idx = np.digitize(x, eb)
        bc, bd, be = [], [], []
        for j in range(1, len(eb)):
            msk = idx == j
            if msk.sum() > 5:
                bc.append(0.5 * (eb[j - 1] + eb[j]))
                bd.append(np.median((d['f'][msk] - 1) * 100))
                be.append(1.4826 * np.median(np.abs(
                    d['f'][msk] - np.median(d['f'][msk]))) * 100
                    / np.sqrt(msk.sum()))
        ax.errorbar(bc, bd, yerr=be, fmt='o', ms=3.5, color='#1f77b4',
                    lw=1)
        order = np.argsort(x)
        ax.plot(x[order], (mod[order] - 1) * 100, color='#d62728', lw=1.5)
        ax.set_xlim(-1.5, 1.5)
        ax.set_ylabel('Flux (%)')
        ax.set_title(f"Sector {d['sector']}  (n={len(d['t'])})",
                     loc='left', fontsize=10)
        ax.grid(alpha=0.25)
        axr = axes[i, 1]
        off = float(np.mean(d['f'] - mod))
        resid = (d['f'] - mod - off) * 100
        axr.plot(x, resid, '.', ms=1.0, alpha=0.2, color='#888888')
        axr.axhline(0, color='#d62728', lw=1)
        axr.set_xlim(-1.5, 1.5)
        axr.set_ylim(-2, 2)
        axr.set_title('resid (%)', fontsize=10)
        axr.grid(alpha=0.25)
        if i == nsec - 1:
            ax.set_xlabel('Phase (hours from transit centre)')
            axr.set_xlabel('Phase (h)')
    fig.suptitle(f"TIC {args.tic} — transit fit (fixed LD "
                 f"u1={args.ld_u1}, u2={args.ld_u2})", fontsize=12)
    fig.savefig(os.path.join(args.outdir, 'fit_transit.png'), dpi=130)
    plt.close(fig)

    # Fig 2: combined fold — data vs fitted model (+ optional desk model)
    t_all = np.concatenate([d['t'] for d in data])
    f_all = np.concatenate([d['f'] for d in data])
    ph = (((t_all - med[1]) / med[0] + 0.5) % 1.0) - 0.5
    x = ph * med[0] * 24.0
    fig, ax = plt.subplots(figsize=(9, 4.6))
    eb = np.linspace(-1.5, 1.5, 61)
    idx = np.digitize(x, eb)
    bc, bd, be = [], [], []
    for j in range(1, len(eb)):
        msk = idx == j
        if msk.sum() > 5:
            bc.append(0.5 * (eb[j - 1] + eb[j]))
            bd.append((1 - np.median(f_all[msk])) * 100)
            be.append(1.4826 * np.median(np.abs(
                f_all[msk] - np.median(f_all[msk]))) * 100
                / np.sqrt(msk.sum()))
    ax.errorbar(bc, bd, yerr=be, fmt='o', ms=4, color='#1f77b4', lw=1,
                label=f'Combined fold ({nsec} sectors, binned)')
    tg = np.linspace(med[1] - 0.08, med[1] + 0.08, 2000)
    xg = (tg - med[1]) * 24.0
    p2 = batman.TransitParams()
    p2.t0, p2.per, p2.rp, p2.a, p2.inc = (med[1], med[0], med[2], med[3],
                                          float(np.median(inc)))
    p2.ecc, p2.w = 0.0, 90.0
    p2.limb_dark, p2.u = 'quadratic', [args.ld_u1, args.ld_u2]
    m2 = batman.TransitModel(p2, tg)
    ax.plot(xg, (1 - m2.light_curve(p2)) * 100, color='#d62728', lw=1.8,
            label=f'Best fit (b={med[4]:.2f}, Rp/R*={med[2]:.3f})')
    if args.desk_rp is not None and args.desk_a is not None \
            and args.desk_b is not None:
        p3 = batman.TransitParams()
        p3.t0, p3.per, p3.rp, p3.a = (med[1], med[0], args.desk_rp,
                                      args.desk_a)
        p3.inc = float(np.degrees(np.arccos(args.desk_b / args.desk_a)))
        p3.ecc, p3.w = 0.0, 90.0
        p3.limb_dark, p3.u = 'quadratic', [args.ld_u1, args.ld_u2]
        m3 = batman.TransitModel(p3, tg)
        ax.plot(xg, (1 - m3.light_curve(p3)) * 100, color='#2ca02c',
                lw=1.5, ls='--',
                label=f'Desk model (b={args.desk_b}, '
                      f'Rp/R*={args.desk_rp})')
    ax.set_xlim(-1.5, 1.5)
    ax.set_xlabel('Phase (hours from transit centre)')
    ax.set_ylabel('Depth (%)')
    ax.set_title(f'TIC {args.tic} — combined transit profile')
    ax.legend(fontsize=9)
    ax.grid(alpha=0.25)
    fig.tight_layout()
    fig.savefig(os.path.join(args.outdir, 'fit_profile_compare.png'),
                dpi=130)
    plt.close(fig)
    print('wrote transit_fit.json, fit_transit.png, '
          'fit_profile_compare.png')


if __name__ == '__main__':
    main()
