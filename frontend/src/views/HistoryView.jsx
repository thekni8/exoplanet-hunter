import React, { useCallback, useEffect, useState } from 'react';
import { RefreshCw, Crosshair } from 'lucide-react';
import { getHistory, getDiscoveries } from '../api.js';
import { Panel, StatusBadge, fmtNum, fmtTime } from '../components.jsx';
import { FakeCheck, FakeCheckToggleButton } from '../fakecheck.jsx';

// One discovery: the data row plus, when its fake-check is opened, a
// full-width expansion row carrying the shared odd/even panel.
function DiscoveryRow({ d }) {
  const [showCheck, setShowCheck] = useState(false);
  const [checkBusy, setCheckBusy] = useState(false);
  return (
    <>
      <tr className="hover:bg-zinc-800/50">
        <td className="px-4 py-2 text-zinc-400 whitespace-nowrap">{fmtTime(d.created_at)}</td>
        <td className="px-4 py-2 uppercase text-zinc-400">{d.source}</td>
        <td className="px-4 py-2 font-bold text-blue-400">{d.tic_id}</td>
        <td className="px-4 py-2">{fmtNum(d.period_days, 4)}</td>
        <td className="px-4 py-2 text-green-400">{fmtNum(d.sde, 1)}</td>
        <td className="px-4 py-2">{fmtNum(d.depth_percent, 4)}</td>
        <td className="px-4 py-2">{fmtNum(d.planet_radius_re)}</td>
        <td className="px-4 py-2 text-zinc-400">{d.sectors ?? '—'}</td>
        <td className="px-4 py-2">
          <FakeCheckToggleButton open={showCheck} busy={checkBusy} onToggle={() => setShowCheck((v) => !v)} />
        </td>
      </tr>
      {showCheck && (
        <tr className="bg-zinc-950/40">
          <td colSpan={9} className="px-4 py-2">
            <FakeCheck tic={d.tic_id} period={d.period_days} onBusyChange={setCheckBusy} />
          </td>
        </tr>
      )}
    </>
  );
}

export default function HistoryView({ onOpenJob }) {
  const [runs, setRuns] = useState(null);
  const [discoveries, setDiscoveries] = useState(null);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const [h, d] = await Promise.all([getHistory(50), getDiscoveries(100)]);
      setRuns(h);
      setDiscoveries(d);
    } catch (e) {
      setError(e.message || String(e));
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  return (
    <div className="p-4 space-y-4 max-w-7xl mx-auto w-full">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-sm font-bold text-zinc-200">Run History</h2>
          <p className="text-[11px] text-zinc-500 mt-0.5">Every run through the API, newest first — persisted in the app's database, so it survives restarts.</p>
        </div>
        <button onClick={load} className="inline-flex items-center gap-2 px-3 py-1.5 text-xs font-semibold border border-zinc-700 bg-zinc-800 hover:bg-zinc-700 text-zinc-200 rounded-sm">
          <RefreshCw className="w-3.5 h-3.5" /> Refresh
        </button>
      </div>

      {error && <div className="text-xs text-red-400 font-mono">Could not load history: {error}</div>}

      <Panel title="Past Runs">
        {runs === null ? (
          <div className="p-3 text-xs text-zinc-500 font-mono">Loading…</div>
        ) : runs.length === 0 ? (
          <div className="p-3 text-xs text-zinc-500 font-mono">No runs recorded yet.</div>
        ) : (
          <table className="w-full text-xs text-left text-zinc-300 font-mono">
            <thead className="bg-zinc-950 text-zinc-500 uppercase border-b border-zinc-800">
              <tr>
                <th className="px-4 py-2">When</th><th className="px-4 py-2">Type</th>
                <th className="px-4 py-2">Target</th><th className="px-4 py-2">Status</th>
                <th className="px-4 py-2">Period (d)</th><th className="px-4 py-2">SDE</th><th className="px-4 py-2"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-800">
              {runs.map((r) => (
                <tr key={r.job_id} className="hover:bg-zinc-800/50">
                  <td className="px-4 py-2 text-zinc-400 whitespace-nowrap">{fmtTime(r.created_at)}</td>
                  <td className="px-4 py-2 uppercase text-zinc-400">{r.type}</td>
                  <td className="px-4 py-2 font-bold text-blue-400">{r.target}</td>
                  <td className="px-4 py-2"><StatusBadge status={r.status} />{r.status === 'failed' && r.error && <div className="text-red-400/80 text-[10px] mt-0.5 max-w-xs whitespace-pre-wrap break-words">{String(r.error).slice(0, 160)}</div>}</td>
                  <td className="px-4 py-2">{r.period != null ? fmtNum(r.period, 4) : '—'}</td>
                  <td className="px-4 py-2">{r.sde != null ? fmtNum(r.sde, 1) : '—'}</td>
                  <td className="px-4 py-2">
                    {r.type === 'analyze' && r.status === 'done' && (
                      <button onClick={() => onOpenJob(r)}
                        className="inline-flex items-center gap-1 px-2 py-1 border border-zinc-700 bg-zinc-800 hover:bg-zinc-700 rounded-sm text-[11px] font-sans font-semibold text-zinc-200">
                        <Crosshair className="w-3 h-3" /> View result
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Panel>

      <Panel title="Discoveries — hits only (SDE ≥ 8.5)">
        {discoveries === null ? (
          <div className="p-3 text-xs text-zinc-500 font-mono">Loading…</div>
        ) : discoveries.length === 0 ? (
          <div className="p-3 text-xs text-zinc-500 font-mono">No hits recorded yet. Runs that don't cross the threshold are treated as noise and are not logged here.</div>
        ) : (
          <table className="w-full text-xs text-left text-zinc-300 font-mono">
            <thead className="bg-zinc-950 text-zinc-500 uppercase border-b border-zinc-800">
              <tr>
                <th className="px-4 py-2">When</th><th className="px-4 py-2">Source</th>
                <th className="px-4 py-2">TIC ID</th><th className="px-4 py-2">Period (d)</th>
                <th className="px-4 py-2">SDE</th><th className="px-4 py-2">Depth %</th>
                <th className="px-4 py-2">Size (R⊕)</th><th className="px-4 py-2">Sectors</th>
                <th className="px-4 py-2"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-800">
              {discoveries.map((d) => (
                <DiscoveryRow key={d.id} d={d} />
              ))}
            </tbody>
          </table>
        )}
      </Panel>
    </div>
  );
}
