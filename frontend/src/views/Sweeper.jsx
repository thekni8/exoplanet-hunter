import React, { useState } from 'react';
import { Search, Crosshair, CheckCircle2 } from 'lucide-react';
import { postJob } from '../api.js';
import { useJobPolling } from '../useJob.js';
import { Field, Panel, ProgressLog, rangeError, fmtNum, inputCls } from '../components.jsx';
import { FakeCheck, FakeCheckToggleButton } from '../fakecheck.jsx';
import { DoublePeriodCheck, DoublePeriodToggleButton } from '../doubleperiod.jsx';

// One sweep hit: the data row plus, when one of its checks is opened,
// a full-width expansion row carrying the shared check panel.
function HitRow({ h, onOpenTarget }) {
  const [showCheck, setShowCheck] = useState(false);
  const [checkBusy, setCheckBusy] = useState(false);
  const [showDp, setShowDp] = useState(false);
  const [dpBusy, setDpBusy] = useState(false);
  return (
    <>
      <tr className="hover:bg-zinc-800/50">
        <td className="px-4 py-2"><span className="text-green-400 font-semibold inline-flex items-center gap-1"><CheckCircle2 className="w-3 h-3" /> Hit</span></td>
        <td className="px-4 py-2 font-bold text-blue-400">{h.tic_id}</td>
        <td className="px-4 py-2 text-zinc-400">{fmtNum(h.tmag)}</td>
        <td className="px-4 py-2 text-zinc-400">{fmtNum(h.star_radius_rsun)}</td>
        <td className="px-4 py-2 font-bold">{fmtNum(h.period_days, 4)}</td>
        <td className="px-4 py-2">{fmtNum(h.sde, 1)}</td>
        <td className="px-4 py-2">{fmtNum(h.planet_radius_re)}</td>
        <td className="px-4 py-2 text-zinc-400">{h.sectors_analyzed}</td>
        <td className="px-4 py-2">
          <div className="flex flex-wrap gap-1.5">
            <FakeCheckToggleButton open={showCheck} busy={checkBusy} onToggle={() => setShowCheck((v) => !v)} />
            <DoublePeriodToggleButton open={showDp} busy={dpBusy} onToggle={() => setShowDp((v) => !v)} />
            <button onClick={() => onOpenTarget(h.tic_id, h.star_radius_rsun)}
              className="inline-flex items-center gap-1 px-2 py-1 border border-zinc-700 bg-zinc-800 hover:bg-zinc-700 rounded-sm text-[11px] font-sans font-semibold text-zinc-200">
              <Crosshair className="w-3 h-3" /> Open in Observatory
            </button>
          </div>
        </td>
      </tr>
      {showCheck && (
        <tr className="bg-zinc-950/40">
          <td colSpan={9} className="px-4 py-2">
            <FakeCheck tic={h.tic_id} period={h.period_days} onBusyChange={setCheckBusy} />
          </td>
        </tr>
      )}
      {showDp && (
        <tr className="bg-zinc-950/40">
          <td colSpan={9} className="px-4 py-2">
            <DoublePeriodCheck tic={h.tic_id} period={h.period_days} onBusyChange={setDpBusy} />
          </td>
        </tr>
      )}
    </>
  );
}

export default function Sweeper({ settings, onOpenTarget }) {
  const [ra, setRa] = useState(83.82);
  const [dec, setDec] = useState(-5.39);
  const [cone, setCone] = useState(0.15);
  const [minMag, setMinMag] = useState(11.5);
  const [maxMag, setMaxMag] = useState(15.0);
  const [minRad, setMinRad] = useState(0.5);
  const [maxRad, setMaxRad] = useState(1.8);
  const [limit, setLimit] = useState(8);
  const [sectorCap, setSectorCap] = useState(2);
  const [blsPoints, setBlsPoints] = useState(10000);

  const [jobId, setJobId] = useState(null);
  const [submitError, setSubmitError] = useState(null);
  const { job, pollError } = useJobPolling(jobId);

  const run = async () => {
    setSubmitError(null);
    // Gentle out-of-bounds guard: check every typed value (and the
    // min/max pairs) before submitting — no silent clamping.
    const oob =
      rangeError('RA', ra, 0, 360) ||
      rangeError('Dec', dec, -90, 90) ||
      rangeError('Cone Radius', cone, 0.01, 2) ||
      rangeError('Max Stars', limit, 1, 1000, true) ||
      rangeError('Min Tmag', minMag, 0, 20) ||
      rangeError('Max Tmag', maxMag, 0, 20) ||
      rangeError('Min Star Radius', minRad, 0.1, 10) ||
      rangeError('Max Star Radius', maxRad, 0.1, 10) ||
      rangeError('Sector Cap', sectorCap, 1, 20, true) ||
      rangeError('BLS Grid Points', blsPoints, 1000, 100000, true) ||
      (Number(minMag) > Number(maxMag) ? 'Min Tmag must not be greater than Max Tmag' : null) ||
      (Number(minRad) > Number(maxRad) ? 'Min Star Radius must not be greater than Max Star Radius' : null);
    if (oob) {
      setSubmitError(oob);
      return;
    }
    try {
      const { job_id } = await postJob('/api/sweep', {
        ra: Number(ra), dec: Number(dec), cone: Number(cone), limit: Number(limit),
        min_mag: Number(minMag), max_mag: Number(maxMag),
        min_rad: Number(minRad), max_rad: Number(maxRad),
        bls_points: Number(blsPoints), sector_cap: Number(sectorCap),
        detrend_window: Number(settings.detrendWindow),
      });
      setJobId(job_id);
    } catch (e) {
      setSubmitError(e.message || String(e));
    }
  };

  const busy = job && (job.status === 'queued' || job.status === 'running');
  const summary = job?.status === 'done' ? job.result : null;
  const hits = summary?.hits || [];

  return (
    <div className="p-4 space-y-4 max-w-7xl mx-auto w-full">
      <Panel title="Sweep Parameters">
        <div className="p-3">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <Field label="RA (deg)" range="0 – 360"><input className={inputCls} type="number" step="0.01" min="0" max="360" value={ra} onChange={(e) => setRa(e.target.value)} /></Field>
            <Field label="Dec (deg)" range="−90 – +90"><input className={inputCls} type="number" step="0.01" min="-90" max="90" value={dec} onChange={(e) => setDec(e.target.value)} /></Field>
            <Field label="Cone Radius (deg)" range="0.01 – 2"><input className={inputCls} type="number" step="0.05" min="0.01" max="2" value={cone} onChange={(e) => setCone(e.target.value)} /></Field>
            <Field label="Max Stars" range="1 – 1,000"><input className={inputCls} type="number" step="1" min="1" max="1000" value={limit} onChange={(e) => setLimit(e.target.value)} /></Field>
            <Field label="Min Tmag" range="0 – 20"><input className={inputCls} type="number" step="0.5" min="0" max="20" value={minMag} onChange={(e) => setMinMag(e.target.value)} /></Field>
            <Field label="Max Tmag" range="0 – 20"><input className={inputCls} type="number" step="0.5" min="0" max="20" value={maxMag} onChange={(e) => setMaxMag(e.target.value)} /></Field>
            <Field label="Min Star Radius (R☉)" range="0.1 – 10"><input className={inputCls} type="number" step="0.1" min="0.1" max="10" value={minRad} onChange={(e) => setMinRad(e.target.value)} /></Field>
            <Field label="Max Star Radius (R☉)" range="0.1 – 10"><input className={inputCls} type="number" step="0.1" min="0.1" max="10" value={maxRad} onChange={(e) => setMaxRad(e.target.value)} /></Field>
            <Field label="Sector Cap (per star)" range="1 – 20"><input className={inputCls} type="number" step="1" min="1" max="20" value={sectorCap} onChange={(e) => setSectorCap(e.target.value)} /></Field>
            <Field label="BLS Grid Points (per star)" range="1,000 – 100,000"><input className={inputCls} type="number" step="1000" min="1000" max="100000" value={blsPoints} onChange={(e) => setBlsPoints(e.target.value)} /></Field>
          </div>
          <div className="mt-3 flex items-center justify-between">
            <span className="text-[11px] text-zinc-500">The sweep always works through the full screened list — it runs as a background job.</span>
            <button onClick={run} disabled={busy}
              className="bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white text-xs font-bold py-1.5 px-6 rounded-sm border border-blue-500 flex items-center gap-2">
              <Search className="h-3.5 w-3.5" /> {busy ? 'Sweeping…' : 'Launch Sweep'}
            </button>
          </div>
          {submitError && <div className="mt-2 text-xs text-red-400 font-mono">Submit failed: {submitError}</div>}
        </div>
      </Panel>

      {jobId && job && <ProgressLog job={job} pollError={pollError} />}

      {summary && (
        <Panel title={`Sweep Results — ${summary.hits?.length || 0} hit(s) of ${summary.targets_total} screened target(s)`}>
          {hits.length === 0 ? (
            <div className="p-3 text-xs text-zinc-500 font-mono">
              No target crossed the SDE ≥ 8.5 hit threshold in this sweep ({summary.targets_analyzed} analysed, {summary.errors?.length || 0} errors — see progress log).
            </div>
          ) : (
            <table className="w-full text-xs text-left text-zinc-300 font-mono">
              <thead className="bg-zinc-950 text-zinc-500 uppercase border-b border-zinc-800">
                <tr>
                  <th className="px-4 py-2">Status</th><th className="px-4 py-2">TIC ID</th>
                  <th className="px-4 py-2">Tmag</th><th className="px-4 py-2">Star Rad (R☉)</th>
                  <th className="px-4 py-2">Period (d)</th><th className="px-4 py-2">SDE</th>
                  <th className="px-4 py-2">Size (R⊕)</th><th className="px-4 py-2">Sectors</th><th className="px-4 py-2"></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-800">
                {hits.map((h) => (
                  <HitRow key={h.tic_id} h={h} onOpenTarget={onOpenTarget} />
                ))}
              </tbody>
            </table>
          )}
        </Panel>
      )}
    </div>
  );
}
