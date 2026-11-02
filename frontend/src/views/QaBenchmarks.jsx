import React, { useState } from 'react';
import { Play, CheckCircle2, AlertTriangle } from 'lucide-react';
import { postJob } from '../api.js';
import { useJobPolling } from '../useJob.js';
import { Panel, ProgressLog, fmtNum } from '../components.jsx';

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
    </div>
  );
}
