import React from 'react';
import { CheckCircle2, Loader2, XCircle, Clock } from 'lucide-react';

export function Panel({ title, right, children, className = '' }) {
  return (
    <div className={`bg-zinc-900 border border-zinc-800 rounded-sm overflow-hidden ${className}`}>
      {(title || right) && (
        <div className="px-3 py-1.5 border-b border-zinc-800 flex items-center justify-between bg-zinc-950/50">
          <span className="text-[11px] font-semibold text-zinc-300">{title}</span>
          {right}
        </div>
      )}
      {children}
    </div>
  );
}

export function Field({ label, children }) {
  return (
    <div className="flex flex-col">
      <label className="text-[10px] text-zinc-400 mb-1 font-semibold">{label}</label>
      {children}
    </div>
  );
}

export const inputCls =
  'bg-zinc-950 border border-zinc-700 text-zinc-200 px-2 py-1 text-xs font-mono rounded-none focus:border-blue-500 outline-none w-full';

export function Metric({ label, value, accent }) {
  return (
    <div className="bg-zinc-900 p-3">
      <div className="text-[10px] text-zinc-500 font-bold uppercase tracking-wider mb-1">{label}</div>
      <div className={`text-lg font-mono ${accent || 'text-zinc-200'}`}>{value}</div>
    </div>
  );
}

export function StatusBadge({ status }) {
  if (status === 'done')
    return <span className="inline-flex items-center gap-1 text-green-400 text-[11px] font-semibold"><CheckCircle2 className="w-3.5 h-3.5" /> Done</span>;
  if (status === 'failed')
    return <span className="inline-flex items-center gap-1 text-red-400 text-[11px] font-semibold"><XCircle className="w-3.5 h-3.5" /> Failed</span>;
  if (status === 'running')
    return <span className="inline-flex items-center gap-1 text-blue-400 text-[11px] font-semibold"><Loader2 className="w-3.5 h-3.5 animate-spin" /> Running</span>;
  return <span className="inline-flex items-center gap-1 text-zinc-400 text-[11px] font-semibold"><Clock className="w-3.5 h-3.5" /> Queued</span>;
}

// Live log of the real progress messages streamed from the engine
// (via the API's progress list), plus terminal error/done states.
export function ProgressLog({ job, pollError }) {
  if (pollError && !job) {
    return <div className="text-xs text-red-400 font-mono px-1 py-2">Could not reach the API: {pollError}</div>;
  }
  if (!job) {
    return <div className="text-xs text-zinc-500 font-mono px-1 py-2 flex items-center gap-2"><Loader2 className="w-3.5 h-3.5 animate-spin" /> Contacting job queue…</div>;
  }
  const lines = job.progress || [];
  return (
    <Panel title="Job progress" right={<StatusBadge status={job.status} />}>
      <div className="max-h-56 overflow-y-auto px-3 py-2 font-mono text-[11px] leading-relaxed text-zinc-400">
        {lines.length === 0 && <div className="text-zinc-600">No progress messages yet.</div>}
        {lines.map((line, i) => (
          <div key={i} className={i === lines.length - 1 && job.status === 'running' ? 'text-zinc-200' : ''}>
            <span className="text-zinc-600 mr-2">{String(i + 1).padStart(2, '0')}</span>{line}
          </div>
        ))}
        {job.status === 'failed' && job.error && (
          <div className="text-red-400 mt-2 whitespace-pre-wrap break-words">Error: {job.error}</div>
        )}
        {job.status === 'done' && (
          <div className="text-green-400 mt-2">✓ Job complete.</div>
        )}
      </div>
    </Panel>
  );
}

export function fmtNum(v, digits = 2) {
  if (v === null || v === undefined || Number.isNaN(Number(v))) return '—';
  return Number(v).toLocaleString('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

export function fmtTime(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
}
