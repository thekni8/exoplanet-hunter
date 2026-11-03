import React, { useEffect, useRef } from 'react';

// Static, draw-once canvas charts rendered from the REAL result arrays
// returned by the API (analyze_target_json payload). No interactivity
// is promised for v1 (Dev's requirements answer 12B) — each chart draws
// once when its data arrives.

function setup(canvas, height) {
  const width = canvas.parentElement.clientWidth;
  const dpr = window.devicePixelRatio || 1;
  canvas.width = width * dpr;
  canvas.height = height * dpr;
  const ctx = canvas.getContext('2d');
  ctx.scale(dpr, dpr);
  ctx.clearRect(0, 0, width, height);
  return { ctx, width, height };
}

function axes(ctx, width, height, pad, xMin, xMax, yMin, yMax, xFmt, yFmt) {
  const plotW = width - pad.l - pad.r;
  const plotH = height - pad.t - pad.b;
  ctx.strokeStyle = '#3f3f46';
  ctx.lineWidth = 1;
  ctx.font = '10px monospace';
  ctx.fillStyle = '#a1a1aa';
  for (let i = 0; i <= 4; i++) {
    const v = yMin + (i / 4) * (yMax - yMin);
    const y = pad.t + (1 - i / 4) * plotH;
    ctx.beginPath(); ctx.moveTo(pad.l, y); ctx.lineTo(width - pad.r, y); ctx.stroke();
    ctx.fillText(yFmt(v), 4, y + 3);
  }
  for (let i = 0; i <= 5; i++) {
    const v = xMin + (i / 5) * (xMax - xMin);
    const x = pad.l + (i / 5) * plotW;
    ctx.beginPath(); ctx.moveTo(x, pad.t); ctx.lineTo(x, height - pad.b); ctx.stroke();
    ctx.fillText(xFmt(v), x - 12, height - pad.b + 14);
  }
  return {
    toX: (v) => pad.l + ((v - xMin) / (xMax - xMin)) * plotW,
    toY: (v) => pad.t + (1 - (v - yMin) / (yMax - yMin)) * plotH,
  };
}

function rangeOf(arrays, padFrac = 0.08) {
  let lo = Infinity, hi = -Infinity;
  for (const a of arrays) {
    for (let i = 0; i < a.length; i++) {
      if (a[i] < lo) lo = a[i];
      if (a[i] > hi) hi = a[i];
    }
  }
  const pad = (hi - lo) * padFrac || 0.001;
  return [lo - pad, hi + pad];
}

function ChartShell({ title, right, children }) {
  return (
    <div className="w-full bg-zinc-900 border border-zinc-800 rounded-sm overflow-hidden">
      <div className="px-3 py-1.5 border-b border-zinc-800 flex justify-between bg-zinc-950/50 text-[11px] text-zinc-400">
        <span className="font-semibold text-zinc-300">{title}</span>
        {right}
      </div>
      <div className="p-1">{children}</div>
    </div>
  );
}

const PAD = { l: 52, r: 14, t: 12, b: 28 };

export function RawChart({ raw, height = 210 }) {
  const ref = useRef(null);
  useEffect(() => {
    const canvas = ref.current;
    if (!canvas || !raw || !raw.time?.length) return;
    const { ctx, width } = setup(canvas, height);
    const [yMin, yMax] = rangeOf([raw.flux]);
    const { toX, toY } = axes(ctx, width, height, PAD, raw.time[0], raw.time[raw.time.length - 1], yMin, yMax,
      (v) => v.toFixed(0), (v) => v.toFixed(3));
    const step = Math.max(1, Math.floor(raw.time.length / 3500));
    ctx.fillStyle = 'rgba(161,161,170,0.45)';
    for (let i = 0; i < raw.time.length; i += step) {
      ctx.fillRect(toX(raw.time[i]), toY(raw.flux[i]), 1.4, 1.4);
    }
    if (raw.trend_time?.length) {
      ctx.strokeStyle = '#ef4444';
      ctx.lineWidth = 1.2;
      ctx.beginPath();
      for (let i = 0; i < raw.trend_time.length; i += step * 2) {
        const x = toX(raw.trend_time[i]), y = toY(raw.trend_flux[i]);
        if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
      }
      ctx.stroke();
    }
  }, [raw, height]);
  return (
    <ChartShell title="1 · Raw Photometry & Stellar Trend"
      right={<span className="flex gap-3 text-[10px]"><span>■ Flux</span><span className="text-red-400">— Trend</span></span>}>
      <canvas ref={ref} style={{ width: '100%', height }} />
    </ChartShell>
  );
}

export function FlatChart({ flat, height = 190 }) {
  const ref = useRef(null);
  useEffect(() => {
    const canvas = ref.current;
    if (!canvas || !flat || !flat.time?.length) return;
    const { ctx, width } = setup(canvas, height);
    const [yMin, yMax] = rangeOf([flat.flux]);
    const { toX, toY } = axes(ctx, width, height, PAD, flat.time[0], flat.time[flat.time.length - 1], yMin, yMax,
      (v) => v.toFixed(0), (v) => v.toFixed(3));
    ctx.strokeStyle = '#71717a';
    ctx.setLineDash([4, 4]);
    ctx.beginPath(); ctx.moveTo(PAD.l, toY(1.0)); ctx.lineTo(width - PAD.r, toY(1.0)); ctx.stroke();
    ctx.setLineDash([]);
    const step = Math.max(1, Math.floor(flat.time.length / 3500));
    ctx.fillStyle = 'rgba(96,165,250,0.5)';
    for (let i = 0; i < flat.time.length; i += step) {
      ctx.fillRect(toX(flat.time[i]), toY(flat.flux[i]), 1.4, 1.4);
    }
  }, [flat, height]);
  return (
    <ChartShell title="2 · Flattened Light Curve (Detrended Residuals)">
      <canvas ref={ref} style={{ width: '100%', height }} />
    </ChartShell>
  );
}

export function BlsChart({ bls, peakPeriod, sde, height = 190 }) {
  const ref = useRef(null);
  useEffect(() => {
    const canvas = ref.current;
    if (!canvas || !bls || !bls.periods?.length) return;
    const { ctx, width } = setup(canvas, height);
    const maxPow = Math.max(...bls.powers) * 1.12;
    const { toX, toY } = axes(ctx, width, height, PAD, bls.periods[0], bls.periods[bls.periods.length - 1], 0, maxPow,
      (v) => v.toFixed(1) + 'd', (v) => v.toFixed(2));
    ctx.strokeStyle = '#34d399';
    ctx.lineWidth = 1.1;
    ctx.beginPath();
    for (let i = 0; i < bls.periods.length; i++) {
      const x = toX(bls.periods[i]), y = toY(bls.powers[i]);
      if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    }
    ctx.stroke();
    if (peakPeriod) {
      const x = toX(peakPeriod);
      ctx.strokeStyle = '#ef4444';
      ctx.setLineDash([4, 4]);
      ctx.beginPath(); ctx.moveTo(x, PAD.t); ctx.lineTo(x, height - PAD.b); ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = '#ef4444';
      ctx.font = 'bold 10px monospace';
      ctx.fillText(`Peak ${Number(peakPeriod).toFixed(4)}d`, Math.min(x + 5, width - 110), PAD.t + 10);
    }
  }, [bls, peakPeriod, height]);
  return (
    <ChartShell title="3 · BLS Power Spectrum" right={<span className="text-[10px]">SDE: {sde != null ? Number(sde).toFixed(1) : '—'}</span>}>
      <canvas ref={ref} style={{ width: '100%', height }} />
    </ChartShell>
  );
}

// Stage 4: odd/even fake-check chart (v1's QA Validation Lab plot).
// Folded at 2x the candidate period, so real planet transits appear as
// TWO equal dips at -P/2 (odd transits) and +P/2 (even transits); an
// eclipsing binary shows two dips of clearly different depths.
// Rendered from the REAL folded arrays of an /api/oddeven job result.
export function OddEvenChart({ folded, height = 240 }) {
  const ref = useRef(null);
  useEffect(() => {
    const canvas = ref.current;
    if (!canvas || !folded || !folded.points?.time_days?.length) return;
    const { ctx, width } = setup(canvas, height);
    const P = folded.range_days || 1;
    const pts = folded.points;
    const binned = folded.binned;
    // Plot brightness drop in percent, like v1: (flux - 1) * 100.
    const toPct = (v) => (v - 1) * 100;
    let yLo = Infinity, yHi = -Infinity;
    const scan = (arr) => {
      for (let i = 0; i < arr.length; i++) {
        const v = toPct(arr[i]);
        if (v < yLo) yLo = v;
        if (v > yHi) yHi = v;
      }
    };
    if (binned?.flux?.length) scan(binned.flux); else scan(pts.flux);
    if (!Number.isFinite(yLo)) { yLo = -0.1; yHi = 0.1; }
    const padY = Math.max((yHi - yLo) * 0.25, 0.01);
    yLo -= padY; yHi = Math.max(yHi + padY, padY * 0.5);
    const { toX, toY } = axes(ctx, width, height, PAD, -P, P, yLo, yHi,
      (v) => v.toFixed(1) + 'd', (v) => v.toFixed(2) + '%');
    // zero line (star's normal brightness)
    ctx.strokeStyle = '#52525b';
    ctx.setLineDash([4, 4]);
    ctx.beginPath(); ctx.moveTo(PAD.l, toY(0)); ctx.lineTo(width - PAD.r, toY(0)); ctx.stroke();
    ctx.setLineDash([]);
    // cadence scatter
    ctx.fillStyle = 'rgba(161,161,170,0.35)';
    for (let i = 0; i < pts.time_days.length; i++) {
      ctx.fillRect(toX(pts.time_days[i]), toY(toPct(pts.flux[i])), 1.4, 1.4);
    }
    // binned medians as a connected line + dots (v1's "averaged dip")
    if (binned?.flux?.length) {
      ctx.strokeStyle = '#f43f5e';
      ctx.lineWidth = 1.8;
      ctx.beginPath();
      binned.flux.forEach((fv, i) => {
        const x = toX(binned.time_days[i]), y = toY(toPct(fv));
        if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
      });
      ctx.stroke();
      ctx.fillStyle = '#f43f5e';
      binned.flux.forEach((fv, i) => {
        ctx.fillRect(toX(binned.time_days[i]) - 1.5, toY(toPct(fv)) - 1.5, 3, 3);
      });
    }
    // dip-center markers
    const centers = [
      { v: folded.center_odd_days, color: '#ef4444', label: 'Odd dips' },
      { v: folded.center_even_days, color: '#60a5fa', label: 'Even dips' },
    ];
    ctx.font = 'bold 10px monospace';
    centers.forEach(({ v, color, label }) => {
      if (v == null) return;
      const x = toX(v);
      ctx.strokeStyle = color;
      ctx.setLineDash([5, 4]);
      ctx.beginPath(); ctx.moveTo(x, PAD.t); ctx.lineTo(x, height - PAD.b); ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = color;
      ctx.fillText(label, Math.min(Math.max(x - 24, PAD.l), width - 90), PAD.t + 10);
    });
  }, [folded, height]);
  return (
    <ChartShell title="Odd / Even Dip Comparison — folded at twice the period"
      right={<span className="flex gap-3 text-[10px]"><span>■ Cadence</span><span className="text-rose-400">— Binned median</span></span>}>
      <canvas ref={ref} style={{ width: '100%', height }} />
    </ChartShell>
  );
}

// Double-period (ellipsoidal / twin-star) chart: the RAW light curve
// folded at twice the candidate period, phase 0..1. Eclipse windows
// are shaded red, quadrature windows green — twin stars show the
// binned median riding HIGH through the green zones (tidally squeezed
// stars presenting their wide sides); a planet's fold stays flat
// between the dips. Rendered from the binned curve of an
// /api/doubleperiod job result (same canvas approach as OddEvenChart).
export function DoublePeriodChart({ folded, height = 240 }) {
  const ref = useRef(null);
  useEffect(() => {
    const canvas = ref.current;
    if (!canvas || !folded || !folded.binned?.phase?.length) return;
    const { ctx, width } = setup(canvas, height);
    const binned = folded.binned;
    // Plot brightness relative to the star's normal level, in percent.
    const toPct = (v) => (v - 1) * 100;
    let yLo = Infinity, yHi = -Infinity;
    for (let i = 0; i < binned.median_flux.length; i++) {
      const v = toPct(binned.median_flux[i]);
      if (v < yLo) yLo = v;
      if (v > yHi) yHi = v;
    }
    if (!Number.isFinite(yLo)) { yLo = -0.1; yHi = 0.1; }
    const padY = Math.max((yHi - yLo) * 0.25, 0.01);
    yLo -= padY; yHi += padY;
    const { toX, toY } = axes(ctx, width, height, PAD, 0, 1, yLo, yHi,
      (v) => v.toFixed(1), (v) => v.toFixed(2) + '%');
    // measurement windows, shaded under the data
    const shade = (lo, hi, color) => {
      ctx.fillStyle = color;
      ctx.fillRect(toX(lo), PAD.t, toX(hi) - toX(lo), height - PAD.t - PAD.b);
    };
    shade(0.94, 1.0, 'rgba(239,68,68,0.14)');
    shade(0.0, 0.06, 'rgba(239,68,68,0.14)');
    shade(0.44, 0.56, 'rgba(239,68,68,0.14)');
    shade(0.19, 0.31, 'rgba(34,197,94,0.14)');
    shade(0.69, 0.81, 'rgba(34,197,94,0.14)');
    ctx.font = 'bold 9px monospace';
    ctx.fillStyle = '#f87171';
    ctx.fillText('ECLIPSE', toX(0.462), PAD.t + 10);
    ctx.fillText('ECLIPSE', toX(0.943), PAD.t + 10);
    ctx.fillStyle = '#4ade80';
    ctx.fillText('QUADRATURE', toX(0.198), PAD.t + 10);
    ctx.fillText('QUADRATURE', toX(0.698), PAD.t + 10);
    // zero line (star's normal brightness)
    ctx.strokeStyle = '#52525b';
    ctx.setLineDash([4, 4]);
    ctx.beginPath(); ctx.moveTo(PAD.l, toY(0)); ctx.lineTo(width - PAD.r, toY(0)); ctx.stroke();
    ctx.setLineDash([]);
    // binned medians as a connected line + dots
    ctx.strokeStyle = '#38bdf8';
    ctx.lineWidth = 1.8;
    ctx.beginPath();
    binned.median_flux.forEach((fv, i) => {
      const x = toX(binned.phase[i]), y = toY(toPct(fv));
      if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    });
    ctx.stroke();
    ctx.fillStyle = '#38bdf8';
    binned.median_flux.forEach((fv, i) => {
      ctx.fillRect(toX(binned.phase[i]) - 1.5, toY(toPct(fv)) - 1.5, 3, 3);
    });
  }, [folded, height]);
  return (
    <ChartShell title="Double-Period Fold — raw light curve at twice the period"
      right={<span className="flex gap-3 text-[10px]"><span className="text-red-400">■ Eclipses</span><span className="text-green-400">■ Quadratures</span><span className="text-sky-400">— Binned median</span></span>}>
      <canvas ref={ref} style={{ width: '100%', height }} />
    </ChartShell>
  );
}

export function PhaseChart({ phaseFolded, height = 220 }) {
  const ref = useRef(null);
  useEffect(() => {
    const canvas = ref.current;
    if (!canvas || !phaseFolded || !phaseFolded.points?.phase_hours?.length) return;
    const { ctx, width } = setup(canvas, height);
    const zoom = phaseFolded.zoom_hours || 10;
    const pts = phaseFolded.points;
    const binned = phaseFolded.binned;
    let yLo = Infinity, yHi = -Infinity;
    if (binned?.flux_mean?.length) {
      for (let i = 0; i < binned.flux_mean.length; i++) {
        const lo = binned.flux_mean[i] - (binned.flux_sem?.[i] || 0);
        const hi = binned.flux_mean[i] + (binned.flux_sem?.[i] || 0);
        if (lo < yLo) yLo = lo;
        if (hi > yHi) yHi = hi;
      }
    } else {
      [yLo, yHi] = rangeOf([pts.flux]);
    }
    const padY = (yHi - yLo) * 0.15 || 0.001;
    const { toX, toY } = axes(ctx, width, height, PAD, -zoom, zoom, yLo - padY, Math.max(yHi + padY, 1.001),
      (v) => v.toFixed(1) + 'h', (v) => v.toFixed(4));
    ctx.strokeStyle = '#52525b';
    ctx.setLineDash([4, 4]);
    ctx.beginPath(); ctx.moveTo(toX(0), PAD.t); ctx.lineTo(toX(0), height - PAD.b); ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = 'rgba(161,161,170,0.30)';
    for (let i = 0; i < pts.phase_hours.length; i++) {
      ctx.fillRect(toX(pts.phase_hours[i]), toY(pts.flux[i]), 1.4, 1.4);
    }
    if (binned?.flux_mean?.length) {
      binned.flux_mean.forEach((mean, i) => {
        const bx = toX(binned.phase_hours[i]);
        const by = toY(mean);
        const sem = binned.flux_sem?.[i] || 0;
        const yTop = toY(mean + sem), yBot = toY(mean - sem);
        ctx.strokeStyle = '#ef4444';
        ctx.lineWidth = 1.1;
        ctx.beginPath();
        ctx.moveTo(bx, yTop); ctx.lineTo(bx, yBot);
        ctx.moveTo(bx - 2, yTop); ctx.lineTo(bx + 2, yTop);
        ctx.moveTo(bx - 2, yBot); ctx.lineTo(bx + 2, yBot);
        ctx.stroke();
        ctx.fillStyle = '#ef4444';
        ctx.fillRect(bx - 1.5, by - 1.5, 3, 3);
      });
    }
  }, [phaseFolded, height]);
  return (
    <ChartShell title="4 · Phase-Folded Transit Profile"
      right={<span className="flex gap-3 text-[10px]"><span>■ Cadence</span><span className="text-red-400">■ Binned ±SEM</span></span>}>
      <canvas ref={ref} style={{ width: '100%', height }} />
    </ChartShell>
  );
}
