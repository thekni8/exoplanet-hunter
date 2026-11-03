import React, { useEffect, useState } from 'react';
import { Waves, Loader2 } from 'lucide-react';
import { postJob, getJobResult } from './api.js';
import { useJobPolling } from './useJob.js';
import { fmtNum } from './components.jsx';
import { DoublePeriodChart } from './charts.jsx';

// ---------------------------------------------------------------------------
// Shared "Double-period check" (ellipsoidal / twin-star test) — the
// companion family to fakecheck.jsx's odd/even check, built to the
// same three-piece pattern:
//   DoublePeriodToggleButton — the sky button (its visual identity)
//   DoublePeriodCheck        — runs one /api/doubleperiod job on
//                              mount and renders the running state, a
//                              failure, or the verdict box (plain
//                              verdict sentence + numbers + fold chart)
//   DoublePeriodButton       — the one-piece widget: toggle + inline
//                              panel, for block-layout contexts
// Where the odd/even check compares the two dips, this one inspects
// the light BETWEEN them on the RAW (unflattened) curve: twin stars
// brighten at the quarter-orbit points, a planet leaves them flat.
// It is the check that unmasked TIC 308851365 — odd/even said
// "planet-like", the quadrature wave said "twin stars".
// ---------------------------------------------------------------------------

export function DoublePeriodToggleButton({ open, busy, onToggle }) {
  return (
    <button onClick={onToggle} disabled={busy}
      className="inline-flex items-center gap-1.5 px-3 py-1.5 border border-sky-700/60 bg-sky-950/40 hover:bg-sky-900/40 rounded-sm text-[11px] font-semibold text-sky-200 disabled:opacity-50">
      <Waves className="w-3.5 h-3.5" /> Double-period check
    </button>
  );
}

// Runs an /api/doubleperiod job for one candidate and shows the
// phase-fold chart + verdict in plain words. Auto-starts on mount;
// unmounting abandons the local watch (the job itself stays in
// History). onBusyChange(busy) lets the owning toggle disable itself
// while the check is queued/running, so one instance never starts a
// second job.
export function DoublePeriodCheck({ tic, period, onBusyChange }) {
  const [jobId, setJobId] = useState(null);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const { job, pollError } = useJobPolling(jobId);

  useEffect(() => {
    let live = true;
    postJob('/api/doubleperiod', { tic: String(tic), period: Number(period), sector_cap: 2 })
      .then(({ job_id }) => { if (live) setJobId(job_id); })
      .catch((e) => { if (live) setError(e.message || String(e)); });
    return () => { live = false; };
  }, [tic, period]);

  useEffect(() => {
    if (!job || job.status !== 'done' || result) return;
    let live = true;
    getJobResult(job.job_id)
      .then((data) => { if (live) setResult(data); })
      .catch((e) => { if (live) setError(e.message || String(e)); });
    return () => { live = false; };
  }, [job, result]);

  const failed = job?.status === 'failed';
  const busy = !result && !error && !failed;
  useEffect(() => {
    if (onBusyChange) onBusyChange(busy);
  }, [busy, onBusyChange]);
  useEffect(() => () => { if (onBusyChange) onBusyChange(false); }, [onBusyChange]);

  if (error) {
    return <div className="text-xs text-red-400 font-mono mt-3">Double-period check failed: {error}</div>;
  }
  if (failed) {
    return <div className="text-xs text-red-400 font-mono mt-3">Double-period check failed: {job.error || 'the job failed'}</div>;
  }
  if (!result) {
    return (
      <div className="text-xs text-zinc-400 font-mono mt-3 flex items-center gap-2">
        <Loader2 className="w-3.5 h-3.5 animate-spin" />
        {job?.status === 'queued' ? 'Double-period check queued — waiting for the engine…'
          : 'Running the double-period test on the RAW TESS light curve (looking for the twin-star wave between the eclipses)…'}
        {pollError && <span className="text-red-400">({pollError})</span>}
      </div>
    );
  }

  const m = result.metrics;
  const verdict = m?.verdict || 'inconclusive';
  const tone = verdict === 'no-ellipsoidal-signal'
    ? 'border-green-900 bg-green-950/30'
    : verdict === 'likely-binary'
      ? 'border-red-900 bg-red-950/30'
      : 'border-zinc-700 bg-zinc-950/50';
  const delta = m?.delta_percent;
  const deltaText = delta == null ? '—'
    : `${delta >= 0 ? '+' : '−'}${fmtNum(Math.abs(delta), 2)}%`;

  return (
    <div className={`mt-3 border rounded-sm p-3 space-y-3 ${tone}`}>
      <div>
        <div className={`text-sm font-bold ${verdict === 'no-ellipsoidal-signal' ? 'text-green-300' : verdict === 'likely-binary' ? 'text-red-300' : 'text-zinc-200'}`}>
          {m?.verdict_text}
        </div>
        <div className="text-[11px] text-zinc-400 font-mono mt-1">
          Quadratures: {fmtNum(m?.quadrature_median, 5)} · Shoulders: {fmtNum(m?.shoulder_median, 5)} ·
          wave {deltaText} at {fmtNum(Math.abs(m?.delta_sigma || 0), 0)}σ ·
          folded at {fmtNum(m?.period_2p_refined_days, 5)} d over {m?.sectors_used} sector(s) of raw TESS data.
        </div>
      </div>
      <DoublePeriodChart folded={result.folded} />
    </div>
  );
}

// One-piece widget for block layouts: the toggle button with the
// result expanding inline directly beneath it.
export function DoublePeriodButton({ tic, period }) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  return (
    <>
      <DoublePeriodToggleButton open={open} busy={busy} onToggle={() => setOpen((v) => !v)} />
      {open && <DoublePeriodCheck tic={tic} period={period} onBusyChange={setBusy} />}
    </>
  );
}
