import React, { useEffect, useState } from 'react';
import { ShieldAlert, Loader2 } from 'lucide-react';
import { postJob, getJobResult } from './api.js';
import { useJobPolling } from './useJob.js';
import { fmtNum } from './components.jsx';
import { OddEvenChart } from './charts.jsx';

// ---------------------------------------------------------------------------
// Shared "Is it a fake?" odd/even check (Stage 4 flow, extracted from
// Scanner so every view can offer it). Three pieces:
//   FakeCheckToggleButton — the amber button (one visual identity app-wide)
//   FakeCheck             — runs one /api/oddeven job on mount and renders
//                           the running state, a failure, or the verdict
//                           box (plain sentence + depths + OddEvenChart)
//   FakeCheckButton       — the one-piece widget: toggle + inline panel,
//                           for block-layout contexts (Observatory)
// Table views (Sweeper, History) compose the toggle + FakeCheck with
// their own open state so the panel can span a full-width row.
// ---------------------------------------------------------------------------

const VERDICT_PLAIN = {
  'planet-like': 'The two dips match — this looks planet-like.',
  'likely-eclipsing-binary': 'The dips are different sizes — this is likely a binary star faking a planet.',
  'inconclusive': "No clear dip could be measured at either spot — this check can't judge the signal.",
};

export function FakeCheckToggleButton({ open, busy, onToggle }) {
  return (
    <button onClick={onToggle} disabled={busy}
      className="inline-flex items-center gap-1.5 px-3 py-1.5 border border-amber-700/60 bg-amber-950/40 hover:bg-amber-900/40 rounded-sm text-[11px] font-semibold text-amber-200 disabled:opacity-50">
      <ShieldAlert className="w-3.5 h-3.5" /> Is it a fake? →
    </button>
  );
}

// Runs an /api/oddeven job for one candidate and shows the odd/even
// chart + verdict in plain words. Auto-starts on mount; unmounting
// abandons the local watch (the job itself stays in History).
// onBusyChange(busy) lets the owning toggle disable itself while the
// check is queued/running, so one instance never starts a second job.
export function FakeCheck({ tic, period, onBusyChange }) {
  const [jobId, setJobId] = useState(null);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const { job, pollError } = useJobPolling(jobId);

  useEffect(() => {
    let live = true;
    postJob('/api/oddeven', { tic: String(tic), period: Number(period), sector_cap: 2 })
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
    return <div className="text-xs text-red-400 font-mono mt-3">Fake-check failed: {error}</div>;
  }
  if (failed) {
    return <div className="text-xs text-red-400 font-mono mt-3">Fake-check failed: {job.error || 'the job failed'}</div>;
  }
  if (!result) {
    return (
      <div className="text-xs text-zinc-400 font-mono mt-3 flex items-center gap-2">
        <Loader2 className="w-3.5 h-3.5 animate-spin" />
        {job?.status === 'queued' ? 'Fake-check queued — waiting for the engine…'
          : 'Running the odd/even test on real TESS data (comparing alternate dips)…'}
        {pollError && <span className="text-red-400">({pollError})</span>}
      </div>
    );
  }

  const m = result.metrics;
  const verdict = m?.verdict || 'inconclusive';
  const sentence = VERDICT_PLAIN[verdict] || m?.verdict_text;
  const tone = verdict === 'planet-like'
    ? 'border-green-900 bg-green-950/30'
    : verdict === 'likely-eclipsing-binary'
      ? 'border-red-900 bg-red-950/30'
      : 'border-zinc-700 bg-zinc-950/50';

  return (
    <div className={`mt-3 border rounded-sm p-3 space-y-3 ${tone}`}>
      <div>
        <div className={`text-sm font-bold ${verdict === 'planet-like' ? 'text-green-300' : verdict === 'likely-eclipsing-binary' ? 'text-red-300' : 'text-zinc-200'}`}>
          {sentence}
        </div>
        <div className="text-[11px] text-zinc-400 font-mono mt-1">
          Odd dips: {fmtNum(m?.depth_odd_percent, 3)}% deep · Even dips: {fmtNum(m?.depth_even_percent, 3)}% deep ·
          difference {fmtNum((m?.depth_rel_diff || 0) * 100, 0)}% · tested at {fmtNum(m?.period_fit_days, 4)} d
          over {m?.sectors_analyzed} sector(s) of real TESS data.
        </div>
      </div>
      <OddEvenChart folded={result.folded} />
    </div>
  );
}

// One-piece widget for block layouts: the toggle button with the
// result expanding inline directly beneath it.
export function FakeCheckButton({ tic, period }) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  return (
    <>
      <FakeCheckToggleButton open={open} busy={busy} onToggle={() => setOpen((v) => !v)} />
      {open && <FakeCheck tic={tic} period={period} onBusyChange={setBusy} />}
    </>
  );
}
