import React, { useEffect, useState } from 'react';
import { Play, Download } from 'lucide-react';
import { postJob, getJob, getJobResult, plateUrl } from '../api.js';
import { useJobPolling } from '../useJob.js';
import { Field, Metric, Panel, ProgressLog, fmtNum, inputCls } from '../components.jsx';
import { RawChart, FlatChart, BlsChart, PhaseChart } from '../charts.jsx';

// seed: { tic, radius, jobId|null, nonce } — set by App when a sweep hit
// or a history run should be opened here. jobId present = load that
// finished run's real result + plate; jobId null = just prefill inputs.
export default function Observatory({ settings, seed }) {
  const [tic, setTic] = useState('322307342');
  const [radius, setRadius] = useState(1.20);
  const [minPeriod, setMinPeriod] = useState(0.5);
  const [maxPeriod, setMaxPeriod] = useState(25.0);
  const [sectorCap, setSectorCap] = useState(2);
  const [allSectors, setAllSectors] = useState(false);

  const [jobId, setJobId] = useState(null);
  const [submitError, setSubmitError] = useState(null);
  const [result, setResult] = useState(null);      // full analyze_target_json payload
  const [resultJobId, setResultJobId] = useState(null);
  const [plateError, setPlateError] = useState(false);

  const { job, pollError } = useJobPolling(jobId);

  // Prefill / load from seed (sweep hit or history click).
  useEffect(() => {
    if (!seed) return;
    if (seed.tic) setTic(String(seed.tic));
    if (seed.radius) setRadius(Number(seed.radius));
    setResult(null);
    setResultJobId(null);
    setPlateError(false);
    setSubmitError(null);
    if (seed.jobId) {
      setJobId(seed.jobId);
    } else {
      setJobId(null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [seed?.nonce]);

  // When the polled job finishes, pull its full result JSON.
  useEffect(() => {
    if (!job || job.status !== 'done' || resultJobId === job.job_id) return;
    let cancelled = false;
    getJobResult(job.job_id)
      .then((data) => {
        if (!cancelled) {
          setResult(data);
          setResultJobId(job.job_id);
        }
      })
      .catch(() => { /* summary metrics still show from job.result */ });
    return () => { cancelled = true; };
  }, [job, resultJobId]);

  const run = async () => {
    setSubmitError(null);
    setResult(null);
    setResultJobId(null);
    setPlateError(false);
    try {
      const pipelines = Object.keys(settings.pipelines).filter((k) => settings.pipelines[k]);
      const { job_id } = await postJob('/api/analyze', {
        tic_id: String(tic).trim(),
        host_radius: Number(radius),
        sector_cap: allSectors ? null : Number(sectorCap),
        bls_points: Number(settings.blsPoints),
        detrend_window: Number(settings.detrendWindow),
        min_period: Number(minPeriod),
        max_period: Number(maxPeriod),
        pipelines,
      });
      setJobId(job_id);
    } catch (e) {
      setSubmitError(e.message || String(e));
    }
  };

  const busy = job && (job.status === 'queued' || job.status === 'running');
  const metrics = result?.metrics || (job?.status === 'done' ? job.result : null);
  const showJob = jobId && job;

  return (
    <div className="p-4 space-y-4 max-w-7xl mx-auto w-full">
      <Panel>
        <div className="p-3 flex flex-wrap items-end gap-3">
          <div className="w-44"><Field label="Target TIC ID"><input className={inputCls} value={tic} onChange={(e) => setTic(e.target.value)} /></Field></div>
          <div className="w-28"><Field label="Host Radius (R☉)"><input className={inputCls} type="number" step="0.05" value={radius} onChange={(e) => setRadius(e.target.value)} /></Field></div>
          <div className="w-28"><Field label="Min Period (d)"><input className={inputCls} type="number" step="0.1" value={minPeriod} onChange={(e) => setMinPeriod(e.target.value)} /></Field></div>
          <div className="w-28"><Field label="Max Period (d)"><input className={inputCls} type="number" step="0.5" value={maxPeriod} onChange={(e) => setMaxPeriod(e.target.value)} /></Field></div>
          <div className="w-52">
            <Field label={allSectors ? 'Sectors: ALL' : `Sector Cap: ${sectorCap}`}>
              <div className="flex items-center gap-2">
                <input type="range" min="1" max="20" step="1" value={sectorCap} disabled={allSectors}
                  onChange={(e) => setSectorCap(Number(e.target.value))} className="accent-blue-600 flex-1 disabled:opacity-40" />
                <label className="flex items-center gap-1 text-[11px] text-zinc-400 cursor-pointer whitespace-nowrap">
                  <input type="checkbox" checked={allSectors} onChange={(e) => setAllSectors(e.target.checked)} className="accent-blue-600" /> All
                </label>
              </div>
            </Field>
          </div>
          <button onClick={run} disabled={busy}
            className="ml-auto bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white text-xs font-bold py-1.5 px-6 rounded-sm border border-blue-500 flex items-center gap-2">
            <Play className="h-3.5 w-3.5" /> {busy ? 'Running…' : 'Run Analysis'}
          </button>
        </div>
        {submitError && <div className="px-3 pb-3 text-xs text-red-400 font-mono">Submit failed: {submitError}</div>}
      </Panel>

      {showJob && <ProgressLog job={job} pollError={pollError} />}

      {metrics && (
        <>
          <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-px bg-zinc-800 border border-zinc-800 rounded-sm">
            <Metric label="Orbital Period" value={`${fmtNum(metrics.best_period_days, 5)} d`} />
            <Metric label="Signal SDE" value={fmtNum(metrics.sde, 1)} accent={metrics.sde >= 8.5 ? 'text-green-400' : 'text-zinc-200'} />
            <Metric label="Transit Depth" value={`${fmtNum(metrics.depth_percent, 4)}%`} />
            <Metric label="Duration" value={`${fmtNum(metrics.duration_hours, 2)} h`} />
            <Metric label="Est. Planet Size" value={`${fmtNum(metrics.planet_radius_earth, 2)} R⊕`} accent="text-blue-400" />
            <Metric label="Data Points" value={`${Number(metrics.total_points || 0).toLocaleString()} · ${metrics.sectors_analyzed} sec`} />
          </div>
          <div className="text-[11px] text-zinc-500 font-mono">
            Classification (engine): {metrics.classification || '—'} · Best period from real BLS over {metrics.sectors_analyzed} sector(s) of NASA TESS data.
          </div>
        </>
      )}

      {resultJobId && !plateError && (
        <Panel title={`Diagnostic Plate — TIC ${metrics?.tic_id || ''} (300 DPI, engine-rendered)`}
          right={<a className="text-[11px] text-blue-400 hover:text-blue-300 inline-flex items-center gap-1" href={plateUrl(resultJobId)} download><Download className="w-3.5 h-3.5" /> Download PNG</a>}>
          <img src={plateUrl(resultJobId)} alt="Diagnostic plate rendered by the engine from real TESS data"
            className="w-full" onError={() => setPlateError(true)} />
        </Panel>
      )}
      {resultJobId && plateError && (
        <div className="text-xs text-zinc-500 font-mono">No diagnostic plate was stored for this run.</div>
      )}

      {result && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <div className="space-y-4">
            <RawChart raw={result.raw} />
            <FlatChart flat={result.flattened} />
          </div>
          <div className="space-y-4">
            <BlsChart bls={result.bls} peakPeriod={result.metrics?.best_period_days} sde={result.metrics?.sde} />
            <PhaseChart phaseFolded={result.phase_folded} />
          </div>
        </div>
      )}

      {!showJob && !metrics && (
        <div className="text-xs text-zinc-500 font-mono border border-dashed border-zinc-800 rounded-sm p-6 text-center">
          No run yet. Enter a TIC ID and press Run Analysis — results here are computed from real NASA TESS data by the Python engine, nothing is simulated.
        </div>
      )}
    </div>
  );
}
