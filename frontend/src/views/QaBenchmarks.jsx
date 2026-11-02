import React, { useState } from 'react';
import { Play, CheckCircle2, AlertTriangle } from 'lucide-react';
import { postJob } from '../api.js';
import { useJobPolling } from '../useJob.js';
import { Panel, ProgressLog, Field, rangeError, inputCls, fmtNum } from '../components.jsx';

// Known reference values (published periods) — the only hardcoded
// numbers in the app, clearly labelled as the benchmark truth the
// engine's recovered periods are checked against.
export const BENCHMARKS = [
  { id: '322307342', name: 'TOI-114', type: 'Hot Sub-Neptune', period: 3.5941, starRadius: 1.20, planetRadius: 1.77, note: 'Clean hot sub-Neptune transit inside the Fulton radius valley.' },
  { id: '261136679', name: 'Pi Mensae c', type: 'Super-Earth', period: 6.2679, starRadius: 1.14, planetRadius: 2.04, note: 'Famous multi-sector target, first TESS planet in a multi-planet system.' },
  { id: '25155310', name: 'WASP-126 b', type: 'Inflated Hot Saturn', period: 3.2822, starRadius: 1.30, planetRadius: 10.70, note: 'Deep, high-SNR transit signature — ideal pipeline sanity check.' },
];

export default function QaBenchmarks({ onOpenTarget }) {
  const [jobId, setJobId] = useState(null);
  const [submitError, setSubmitError] = useState(null);
  const { job, pollError } = useJobPolling(jobId);

  const run = async () => {
    setSubmitError(null);
    try {
      const { job_id } = await postJob('/api/qa', {});
      setJobId(job_id);
    } catch (e) {
      setSubmitError(e.message || String(e));
    }
  };

  const busy = job && (job.status === 'queued' || job.status === 'running');
  const summary = job?.status === 'done' ? job.result : null;
  const byTic = {};
  (summary?.benchmarks || []).forEach((b) => { byTic[b.tic_id] = b; });

  // "Check your own star": a custom QA target run as its own job
  // through the same endpoint (POST /api/qa {"custom": {...}}),
  // judged by the same PASS rule as the benchmarks.
  const [customTic, setCustomTic] = useState('');
  const [customPeriod, setCustomPeriod] = useState('');
  const [customJobId, setCustomJobId] = useState(null);
  const [customSubmitError, setCustomSubmitError] = useState(null);
  const { job: customJob, pollError: customPollError } = useJobPolling(customJobId);

  const runCustom = async () => {
    setCustomSubmitError(null);
    // Gentle out-of-bounds guard: check typed values before submitting.
    const ticNum = Number(String(customTic).trim());
    const oob =
      (!Number.isInteger(ticNum) || ticNum <= 0
        ? 'TIC ID must be a positive whole number'
        : null) ||
      rangeError('Expected period', customPeriod, 0.1, 100);
    if (oob) {
      setCustomSubmitError(oob);
      return;
    }
    try {
      const { job_id } = await postJob('/api/qa', {
        custom: { tic: String(customTic).trim(), expected_period_days: Number(customPeriod) },
      });
      setCustomJobId(job_id);
    } catch (e) {
      setCustomSubmitError(e.message || String(e));
    }
  };

  const customBusy = customJob && (customJob.status === 'queued' || customJob.status === 'running');
  const customResult = customJob?.status === 'done' ? (customJob.result?.benchmarks || [])[0] : null;

  return (
    <div className="p-4 space-y-4 max-w-5xl mx-auto w-full">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-sm font-bold text-zinc-200">Verified Mission Standards</h2>
          <p className="text-[11px] text-zinc-500 mt-0.5">
            Runs the engine's fixed QA settings (1–2 sectors, 10,000-point BLS grid). PASS = recovered period within 0.05 d of the known period.
          </p>
        </div>
        <button onClick={run} disabled={busy}
          className="bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white text-xs font-bold py-1.5 px-6 rounded-sm border border-blue-500 flex items-center gap-2">
          <Play className="h-3.5 w-3.5" /> {busy ? 'Running QA…' : 'Run QA Suite'}
        </button>
      </div>
      {submitError && <div className="text-xs text-red-400 font-mono">Submit failed: {submitError}</div>}

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {BENCHMARKS.map((b) => {
          const r = byTic[b.id];
          return (
            <div key={b.id} className="bg-zinc-900 border border-zinc-800 rounded-sm p-4 flex flex-col justify-between">
              <div>
                <div className="text-[10px] font-bold text-zinc-500 mb-1">TIC {b.id}</div>
                <h3 className="text-sm font-bold text-zinc-100 mb-2">{b.name}</h3>
                <p className="text-[11px] text-zinc-500 mb-3">{b.note}</p>
                <div className="bg-zinc-950 border border-zinc-800 p-2 rounded-sm text-[11px] text-zinc-400 font-mono space-y-1 mb-3">
                  <div className="flex justify-between"><span>Class</span><span className="text-zinc-200">{b.type}</span></div>
                  <div className="flex justify-between"><span>Known period</span><span className="text-zinc-200">{b.period} d</span></div>
                  <div className="flex justify-between"><span>Planet radius</span><span className="text-zinc-200">{b.planetRadius} R⊕</span></div>
                  <div className="flex justify-between"><span>Host radius</span><span className="text-zinc-200">{b.starRadius} R☉</span></div>
                </div>
                {r && (
                  <div className={`border p-2 rounded-sm text-[11px] font-mono space-y-1 mb-3 ${r.status === 'PASS' ? 'border-green-900 bg-green-950/30 text-green-300' : 'border-yellow-900 bg-yellow-950/30 text-yellow-300'}`}>
                    <div className="flex justify-between items-center">
                      <span>Result</span>
                      <span className="inline-flex items-center gap-1 font-bold">
                        {r.status === 'PASS' ? <CheckCircle2 className="w-3.5 h-3.5" /> : <AlertTriangle className="w-3.5 h-3.5" />} {r.status}
                      </span>
                    </div>
                    <div className="flex justify-between"><span>Recovered</span><span>{fmtNum(r.recovered_period_days, 5)} d</span></div>
                    <div className="flex justify-between"><span>Δ vs known</span><span>{fmtNum(r.diff_days, 5)} d</span></div>
                    {r.sde != null && <div className="flex justify-between"><span>SDE</span><span>{fmtNum(r.sde, 1)}</span></div>}
                    {r.error && <div className="text-red-400 whitespace-pre-wrap break-words">{r.error}</div>}
                  </div>
                )}
              </div>
              <button onClick={() => onOpenTarget(b.id, b.starRadius)}
                className="w-full py-1.5 text-xs font-semibold border border-zinc-700 bg-zinc-800 hover:bg-zinc-700 text-zinc-200 rounded-sm">
                Load in Observatory
              </button>
            </div>
          );
        })}
      </div>

      {jobId && job && <ProgressLog job={job} pollError={pollError} />}
      {summary && (
        <div className="text-xs font-mono text-zinc-400">
          QA suite finished: <span className={summary.passed === summary.total ? 'text-green-400' : 'text-yellow-300'}>{summary.passed} of {summary.total} benchmarks PASS</span>.
        </div>
      )}

      <Panel title="Check your own star">
        <div className="p-3 space-y-3">
          <p className="text-[11px] text-zinc-500">
            Found a candidate somewhere else? Type its TIC ID and the period you expect — the app re-runs the detection and tells you if it matches.
          </p>
          <div className="flex flex-wrap items-end gap-3">
            <div className="w-44">
              <Field label="TIC ID" range="positive whole number">
                <input className={inputCls} value={customTic} onChange={(e) => setCustomTic(e.target.value)} placeholder="e.g. 25155310" />
              </Field>
            </div>
            <div className="w-40">
              <Field label="Expected period (days)" range="0.1 – 100">
                <input className={inputCls} type="number" step="0.0001" min="0.1" max="100" value={customPeriod} onChange={(e) => setCustomPeriod(e.target.value)} placeholder="e.g. 3.2822" />
              </Field>
            </div>
            <button onClick={runCustom} disabled={customBusy}
              className="bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white text-xs font-bold py-1.5 px-6 rounded-sm border border-blue-500 flex items-center gap-2">
              <Play className="h-3.5 w-3.5" /> {customBusy ? 'Running QA…' : 'Run QA check'}
            </button>
          </div>
          {customSubmitError && <div className="text-xs text-red-400 font-mono">Submit failed: {customSubmitError}</div>}
          {customResult && (
            <div className="bg-zinc-950 border border-zinc-800 rounded-sm p-3 max-w-md">
              <div className="text-[10px] font-bold text-zinc-500 mb-1">TIC {customResult.tic_id}</div>
              <h3 className="text-sm font-bold text-zinc-100 mb-2">{customResult.name}</h3>
              <div className="bg-zinc-900 border border-zinc-800 p-2 rounded-sm text-[11px] text-zinc-400 font-mono space-y-1 mb-3">
                <div className="flex justify-between"><span>Expected period</span><span className="text-zinc-200">{fmtNum(customResult.expected_period_days, 4)} d</span></div>
              </div>
              <div className={`border p-2 rounded-sm text-[11px] font-mono space-y-1 ${customResult.status === 'PASS' ? 'border-green-900 bg-green-950/30 text-green-300' : 'border-yellow-900 bg-yellow-950/30 text-yellow-300'}`}>
                <div className="flex justify-between items-center">
                  <span>Result</span>
                  <span className="inline-flex items-center gap-1 font-bold">
                    {customResult.status === 'PASS' ? <CheckCircle2 className="w-3.5 h-3.5" /> : <AlertTriangle className="w-3.5 h-3.5" />} {customResult.status}
                  </span>
                </div>
                <div className="flex justify-between"><span>Recovered</span><span>{fmtNum(customResult.recovered_period_days, 5)} d</span></div>
                <div className="flex justify-between"><span>Δ vs expected</span><span>{fmtNum(customResult.diff_days, 5)} d</span></div>
                {customResult.sde != null && <div className="flex justify-between"><span>SDE</span><span>{fmtNum(customResult.sde, 1)}</span></div>}
                {customResult.error && <div className="text-red-400 whitespace-pre-wrap break-words">{customResult.error}</div>}
              </div>
            </div>
          )}
        </div>
      </Panel>
      {customJobId && customJob && <ProgressLog job={customJob} pollError={customPollError} />}
    </div>
  );
}
