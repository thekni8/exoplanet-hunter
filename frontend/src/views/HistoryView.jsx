import React, { useCallback, useEffect, useRef, useState } from 'react';
import { RefreshCw, Crosshair, FileText } from 'lucide-react';
import { getHistory, getDiscoveries, getJob } from '../api.js';
import { Panel, StatusBadge, fmtNum, fmtTime } from '../components.jsx';
import { FakeCheck, FakeCheckToggleButton } from '../fakecheck.jsx';
import { DoublePeriodCheck, DoublePeriodToggleButton } from '../doubleperiod.jsx';

// One discovery: the data row plus, when one of its checks is opened,
// a full-width expansion row carrying the shared check panel.
function DiscoveryRow({ d }) {
  const [showCheck, setShowCheck] = useState(false);
  const [checkBusy, setCheckBusy] = useState(false);
  const [showDp, setShowDp] = useState(false);
  const [dpBusy, setDpBusy] = useState(false);
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
          <div className="flex flex-wrap gap-1.5">
            <FakeCheckToggleButton open={showCheck} busy={checkBusy} onToggle={() => setShowCheck((v) => !v)} />
            <DoublePeriodToggleButton open={showDp} busy={dpBusy} onToggle={() => setShowDp((v) => !v)} />
          </div>
        </td>
      </tr>
      {showCheck && (
        <tr className="bg-zinc-950/40">
          <td colSpan={9} className="px-4 py-2">
            <FakeCheck tic={d.tic_id} period={d.period_days} onBusyChange={setCheckBusy} />
          </td>
        </tr>
      )}
      {showDp && (
        <tr className="bg-zinc-950/40">
          <td colSpan={9} className="px-4 py-2">
            <DoublePeriodCheck tic={d.tic_id} period={d.period_days} onBusyChange={setDpBusy} />
          </td>
        </tr>
      )}
    </>
  );
}

// One past run: the data row plus, when its Log is opened, a full-width
// expansion row carrying the job's full error and every progress line.
// The log is fetched lazily (first open) via getJob — the history list
// itself only carries the 160-char error snippet, so a dead run's record
// used to be unopenable; this is the way in. Once open, the log stays
// live two ways: the page Refresh button bumps refreshTick (passed from
// HistoryView), which refetches any open log; and while the fetched job
// is still queued/running the row re-polls getJob every 5 s on its own.
// Polling stops at a terminal status, when the log closes, and on
// unmount — closed rows and finished jobs never fetch.
function RunRow({ r, onOpenJob, refreshTick }) {
  const [showLog, setShowLog] = useState(false);
  const [log, setLog] = useState(null); // null = not fetched yet
  const [logError, setLogError] = useState(null);
  const attemptedRef = useRef(false); // a fetch has been tried at least once

  const fetchLog = useCallback(async () => {
    attemptedRef.current = true;
    try {
      setLog(await getJob(r.job_id));
      setLogError(null);
    } catch (e) {
      setLogError(e.message || String(e));
    }
  }, [r.job_id]);

  const toggleLog = () => {
    const opening = !showLog;
    setShowLog(opening);
    if (opening && !attemptedRef.current) {
      fetchLog();
    }
  };

  // Page Refresh (or the initial load) bumped refreshTick: if this log
  // is open and has been fetched before, refetch so it doesn't sit
  // frozen at open-time. Tick changes while closed only move the
  // baseline — no fetch.
  const prevTickRef = useRef(refreshTick);
  useEffect(() => {
    const tickChanged = refreshTick !== prevTickRef.current;
    prevTickRef.current = refreshTick;
    if (tickChanged && showLog && attemptedRef.current) {
      fetchLog();
    }
  }, [refreshTick, showLog, fetchLog]);

  // Self-poll while open on a live job. When a poll sees a terminal
  // status, setLog flips isLive false and this effect's cleanup clears
  // the interval; closing the row or unmounting cleans up the same way.
  const isLive = log !== null && (log.status === 'queued' || log.status === 'running');
  useEffect(() => {
    if (!showLog || !isLive) return undefined;
    const id = setInterval(fetchLog, 5000);
    return () => clearInterval(id);
  }, [showLog, isLive, fetchLog]);

  return (
    <>
      <tr className="hover:bg-zinc-800/50">
        <td className="px-4 py-2 text-zinc-400 whitespace-nowrap">{fmtTime(r.created_at)}</td>
        <td className="px-4 py-2 uppercase text-zinc-400">{r.type}</td>
        <td className="px-4 py-2 font-bold text-blue-400">{r.target}</td>
        <td className="px-4 py-2"><StatusBadge status={r.status} />{r.status === 'failed' && r.error && <div className="text-red-400/80 text-[10px] mt-0.5 max-w-xs whitespace-pre-wrap break-words">{String(r.error).slice(0, 160)}</div>}</td>
        <td className="px-4 py-2">{r.period != null ? fmtNum(r.period, 4) : '—'}</td>
        <td className="px-4 py-2">{r.sde != null ? fmtNum(r.sde, 1) : '—'}</td>
        <td className="px-4 py-2">
          <div className="flex flex-wrap gap-1.5">
            <button onClick={toggleLog}
              className="inline-flex items-center gap-1 px-2 py-1 border border-zinc-700 bg-zinc-800 hover:bg-zinc-700 rounded-sm text-[11px] font-sans font-semibold text-zinc-200">
              <FileText className="w-3 h-3" /> Log
            </button>
            {r.type === 'analyze' && r.status === 'done' && (
              <button onClick={() => onOpenJob(r)}
                className="inline-flex items-center gap-1 px-2 py-1 border border-zinc-700 bg-zinc-800 hover:bg-zinc-700 rounded-sm text-[11px] font-sans font-semibold text-zinc-200">
                <Crosshair className="w-3 h-3" /> View result
              </button>
            )}
          </div>
        </td>
      </tr>
      {showLog && (
        <tr className="bg-zinc-950/40">
          <td colSpan={7} className="px-4 py-2">
            {logError !== null ? (
              <div className="text-[11px] text-zinc-400 font-mono">Could not load this run's log: {logError}</div>
            ) : log === null ? (
              <div className="text-[11px] text-zinc-500 font-mono">Loading log…</div>
            ) : (
              <div className="space-y-1">
                {log.error && (
                  <div className="text-[11px] text-red-400 font-mono whitespace-pre-wrap break-words">{String(log.error)}</div>
                )}
                {log.progress && log.progress.length > 0 ? (
                  log.progress.map((line, i) => (
                    <div key={i} className="text-[11px] text-zinc-400 font-mono whitespace-pre-wrap break-words">{line}</div>
                  ))
                ) : (
                  <div className="text-[11px] text-zinc-500 font-mono">No progress lines recorded for this run.</div>
                )}
              </div>
            )}
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
  // Bumped on every load() — the mount load and every Refresh click —
  // and handed to each RunRow so an open log refetches instead of
  // staying frozen at the moment it was first opened.
  const [refreshTick, setRefreshTick] = useState(0);

  const load = useCallback(async () => {
    setRefreshTick((t) => t + 1);
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
                <RunRow key={r.job_id} r={r} onOpenJob={onOpenJob} refreshTick={refreshTick} />
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
