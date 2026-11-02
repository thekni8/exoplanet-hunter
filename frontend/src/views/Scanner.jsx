import React, { useEffect, useState } from 'react';
import { Rocket, Crosshair, ShieldAlert, Loader2, ChevronDown } from 'lucide-react';
import { postJob, getJob, getJobResult, getHistory } from '../api.js';
import { useJobPolling } from '../useJob.js';
import { Field, Panel, ProgressLog, fmtNum, fmtTime, inputCls } from '../components.jsx';
import { OddEvenChart } from '../charts.jsx';

// Stage 4 — the Scanner is Gemini v1's "Deep Space Scanner" rebuilt on
// the Stage 2/3 backend: point at a patch of sky, press one button, and
// only NEW, unflagged signals surface. Already-known stars are skipped
// by the backend (Zooniverse check) before any data is downloaded, and
// every scan is a persisted job — results live in History & Discoveries
// forever instead of vanishing when the page reruns (v1's fatal pain).

const STRONG_SDE = 11.0; // v1's alarm bar for "NEW UNFLAGGED SIGNAL"
const HIT_SDE = 8.5;     // backend discoveries threshold (weaker list)

const VERDICT_PLAIN = {
  'planet-like': 'The two dips match — this looks planet-like.',
  'likely-eclipsing-binary': 'The dips are different sizes — this is likely a binary star faking a planet.',
  'inconclusive': "No clear dip could be measured at either spot — this check can't judge the signal.",
};

// ---------------------------------------------------------------------------
// "Is it a fake?" — runs an /api/oddeven job for one candidate and shows
// the odd/even chart + verdict in plain words. Auto-starts on mount.
// ---------------------------------------------------------------------------
function FakeCheck({ tic, period }) {
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

  if (error) {
    return <div className="text-xs text-red-400 font-mono mt-3">Fake-check failed: {error}</div>;
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

// ---------------------------------------------------------------------------
// One signal card (strong hit) / row (weaker signal), with the two
// one-click follow-ups v1 made you retype by hand: fake-check and
// "open in Observatory" (which carries TIC + star radius across).
// ---------------------------------------------------------------------------
function SignalEntry({ hit, strong, onOpenTarget }) {
  const [showCheck, setShowCheck] = useState(false);
  const buttons = (
    <div className="flex flex-wrap gap-2">
      <button onClick={() => setShowCheck((v) => !v)}
        className="inline-flex items-center gap-1.5 px-3 py-1.5 border border-amber-700/60 bg-amber-950/40 hover:bg-amber-900/40 rounded-sm text-[11px] font-semibold text-amber-200">
        <ShieldAlert className="w-3.5 h-3.5" /> Is it a fake? →
      </button>
      <button onClick={() => onOpenTarget(hit.tic_id, hit.star_radius_rsun)}
        className="inline-flex items-center gap-1.5 px-3 py-1.5 border border-zinc-700 bg-zinc-800 hover:bg-zinc-700 rounded-sm text-[11px] font-semibold text-zinc-200">
        <Crosshair className="w-3.5 h-3.5" /> Open in Observatory
      </button>
    </div>
  );

  if (!strong) {
    return (
      <div className="px-3 py-2 border-b border-zinc-800/70 last:border-b-0">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          <span className="font-mono font-bold text-blue-400 text-xs">TIC {hit.tic_id}</span>
          <span className="font-mono text-xs text-zinc-400">Period {fmtNum(hit.period_days, 4)} d</span>
          <span className="font-mono text-xs text-zinc-400">SDE {fmtNum(hit.sde, 1)}</span>
          <span className="font-mono text-xs text-zinc-400">≈ {fmtNum(hit.planet_radius_re)} R⊕</span>
          <span className="ml-auto">{buttons}</span>
        </div>
        {showCheck && <FakeCheck tic={hit.tic_id} period={hit.period_days} />}
      </div>
    );
  }

  return (
    <div className="bg-zinc-900 border border-rose-900/60 rounded-sm p-4">
      <div className="text-sm font-bold text-rose-300 tracking-tight">
        🎯 NEW UNFLAGGED SIGNAL — TIC {hit.tic_id}
      </div>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mt-3 font-mono text-xs">
        <div><div className="text-[10px] text-zinc-500 font-sans font-bold uppercase tracking-wider">Period</div>
          <div className="text-zinc-100 text-sm mt-0.5">{fmtNum(hit.period_days, 4)} days</div></div>
        <div><div className="text-[10px] text-zinc-500 font-sans font-bold uppercase tracking-wider">Approx. planet size</div>
          <div className="text-zinc-100 text-sm mt-0.5">{fmtNum(hit.planet_radius_re)} R⊕</div></div>
        <div><div className="text-[10px] text-zinc-500 font-sans font-bold uppercase tracking-wider">Signal strength (SDE)</div>
          <div className="text-zinc-100 text-sm mt-0.5">{fmtNum(hit.sde, 1)}</div></div>
        <div><div className="text-[10px] text-zinc-500 font-sans font-bold uppercase tracking-wider">Star</div>
          <div className="text-zinc-100 text-sm mt-0.5">{fmtNum(hit.star_radius_rsun)} R☉ · Tmag {fmtNum(hit.tmag, 1)}</div></div>
      </div>
      <div className="mt-3">{buttons}</div>
      {showCheck && <FakeCheck tic={hit.tic_id} period={hit.period_days} />}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Friendly progress (v1-style narration) derived from the job's real
// progress stream — the raw log stays available under the expander.
// ---------------------------------------------------------------------------
function friendlyProgress(job) {
  const lines = job?.progress || [];
  let current = null, total = null, skipped = 0;
  let lastMeaningful = '';
  for (const line of lines) {
    const m = line.match(/Target (\d+) of (\d+)/);
    if (m) { current = Number(m[1]); total = Number(m[2]); }
    if (/already known on Zooniverse/i.test(line)) skipped += 1;
    if (!/^Job .* started/.test(line)) lastMeaningful = line;
  }
  const fraction = job?.status === 'done' ? 1
    : (current && total) ? Math.min(1, current / total) : null;
  let text;
  if (!job) text = 'Contacting the job queue…';
  else if (job.status === 'queued') text = 'Your scan is in the queue — the engine runs one job at a time.';
  else if (job.status === 'failed') text = 'The scan stopped with an error — details are in the log below.';
  else if (job.status === 'done') text = 'Scan complete.';
  else if (/already known/i.test(lastMeaningful)) text = `Skipping stars that are already known… (${skipped} skipped so far)`;
  else if (current && total) text = `Scanning star ${current} of ${total}…`;
  else if (/catalog/i.test(lastMeaningful)) text = "Asking NASA's star catalog what's in that patch of sky…";
  else text = 'Working through the star list…';
  return { fraction, text, skipped };
}

function countLine(summary) {
  const hits = summary.hits || [];
  const strong = hits.filter((h) => h.sde >= STRONG_SDE).length;
  const nothing = Math.max(0, (summary.targets_analyzed || 0) - hits.length);
  const noDataOrKnown = (summary.skipped_known || 0) + (summary.errors?.length || 0);
  return `Scanned ${summary.targets_total} · ${noDataOrKnown} already known / no usable data · ${nothing} nothing found · ${strong} strong signal${strong === 1 ? '' : 's'}`;
}

function ScanResults({ summary, onOpenTarget }) {
  const hits = summary?.hits || [];
  const strong = hits.filter((h) => h.sde >= STRONG_SDE);
  const weaker = hits.filter((h) => h.sde >= HIT_SDE && h.sde < STRONG_SDE);
  return (
    <div className="space-y-3">
      <div className="text-xs font-mono text-zinc-400">{countLine(summary)}</div>
      {strong.length === 0 && weaker.length === 0 && (
        <div className="text-xs text-zinc-500 font-mono border border-dashed border-zinc-800 rounded-sm p-4">
          No new unflagged signals in this patch of sky. Every star was either already known,
          had no usable data, or showed nothing strong enough — that's a normal scan.
        </div>
      )}
      {strong.map((h) => <SignalEntry key={h.tic_id} hit={h} strong onOpenTarget={onOpenTarget} />)}
      {weaker.length > 0 && (
        <Panel title={`Weaker signals (SDE ${HIT_SDE}–${STRONG_SDE}) — saved in Discoveries, worth a second look`}>
          <div>
            {weaker.map((h) => <SignalEntry key={h.tic_id} hit={h} strong={false} onOpenTarget={onOpenTarget} />)}
          </div>
        </Panel>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
export default function Scanner({ settings, onOpenTarget }) {
  const [ra, setRa] = useState(124.456);
  const [dec, setDec] = useState(-67.568);
  const [radius, setRadius] = useState(0.10);
  const [maxStars, setMaxStars] = useState(20);

  const [jobId, setJobId] = useState(null);
  const [submitError, setSubmitError] = useState(null);
  const { job, pollError } = useJobPolling(jobId);

  // The most recent finished scan, loaded from History on mount — so a
  // scan's hits are still here when you come back (v1 lost them).
  const [lastScan, setLastScan] = useState(null);
  useEffect(() => {
    let live = true;
    (async () => {
      try {
        const runs = await getHistory(50);
        const prev = runs.find((r) => r.type === 'sweep' && r.params?.scanner === true && r.status === 'done');
        if (!prev || !live) return;
        const full = await getJob(prev.job_id);
        if (live && full?.result) {
          setLastScan({ jobId: prev.job_id, createdAt: prev.created_at, summary: full.result });
        }
      } catch (_) { /* no previous scan — nothing to show */ }
    })();
    return () => { live = false; };
  }, []);

  const run = async () => {
    setSubmitError(null);
    setLastScan(null);
    try {
      const { job_id } = await postJob('/api/sweep', {
        ra: Number(ra), dec: Number(dec), cone: Number(radius), limit: Number(maxStars),
        scanner: true,
        bls_points: 10000, sector_cap: 2,
        detrend_window: Number(settings.detrendWindow),
      });
      setJobId(job_id);
    } catch (e) {
      setSubmitError(e.message || String(e));
    }
  };

  const busy = job && (job.status === 'queued' || job.status === 'running');
  const summary = job?.status === 'done' ? job.result : null;
  const friendly = friendlyProgress(job);

  return (
    <div className="p-4 space-y-4 max-w-5xl mx-auto w-full">
      <div>
        <h2 className="text-base font-bold text-zinc-100 tracking-tight">Deep Space Scanner</h2>
        <p className="text-xs text-zinc-400 mt-1 leading-relaxed max-w-3xl">
          Point this at a patch of sky and it hunts for <span className="text-zinc-200 font-semibold">new planet signals
          nobody has flagged yet</span>. It checks each star against real NASA TESS data, automatically skips stars
          that are already known, and only bothers you when it finds something strong. Every scan is saved —
          your hits stay in History &amp; Discoveries even after you close the page.
        </p>
      </div>

      <Panel title="Where should we look?">
        <div className="p-3 space-y-3">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <Field label="Right Ascension — RA (deg)"><input className={inputCls} type="number" step="0.01" value={ra} onChange={(e) => setRa(e.target.value)} /></Field>
            <Field label="Declination — Dec (deg)"><input className={inputCls} type="number" step="0.01" value={dec} onChange={(e) => setDec(e.target.value)} /></Field>
            <Field label={`Search radius: ${Number(radius).toFixed(2)}°`}>
              <input type="range" min="0.01" max="1.0" step="0.01" value={radius}
                onChange={(e) => setRadius(Number(e.target.value))} className="accent-blue-600 w-full mt-2" />
            </Field>
            <Field label={`Stars to scan: ${maxStars}`}>
              <input type="range" min="5" max="100" step="5" value={maxStars}
                onChange={(e) => setMaxStars(Number(e.target.value))} className="accent-blue-600 w-full mt-2" />
            </Field>
          </div>
          <p className="text-[11px] text-zinc-500 leading-snug">
            Pre-filled with the patch of sky the original scanner used. Bigger radius / more stars = longer scan —
            it runs in the background, so you can watch or come back later; it always finishes the whole list.
          </p>
          <button onClick={run} disabled={busy}
            className="w-full sm:w-auto bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white text-sm font-bold py-2.5 px-10 rounded-sm border border-blue-500 flex items-center justify-center gap-2">
            <Rocket className="h-4 w-4" /> {busy ? 'Scanning…' : 'Initialize Scan'}
          </button>
          {submitError && <div className="text-xs text-red-400 font-mono">Submit failed: {submitError}</div>}
        </div>
      </Panel>

      {jobId && job && (
        <Panel title="Scan progress" right={<span className="text-[11px] font-mono text-zinc-400">{friendly.skipped > 0 ? `${friendly.skipped} known star(s) skipped` : ''}</span>}>
          <div className="p-3 space-y-2">
            <div className="h-2 bg-zinc-800 rounded-sm overflow-hidden">
              <div className={`h-full bg-blue-500 transition-all duration-500 ${friendly.fraction === null ? 'w-full animate-pulse opacity-60' : ''}`}
                style={friendly.fraction !== null ? { width: `${Math.round(friendly.fraction * 100)}%` } : undefined} />
            </div>
            <div className="text-xs text-zinc-300 font-mono flex items-center gap-2">
              {busy && <Loader2 className="w-3.5 h-3.5 animate-spin text-blue-400" />}
              {friendly.text}
            </div>
            {pollError && <div className="text-[11px] text-red-400 font-mono">Polling hiccup: {pollError}</div>}
            <details className="pt-1">
              <summary className="text-[11px] text-zinc-500 cursor-pointer hover:text-zinc-300 inline-flex items-center gap-1">
                <ChevronDown className="w-3 h-3" /> Detailed log (for the curious)
              </summary>
              <div className="mt-2"><ProgressLog job={job} pollError={pollError} /></div>
            </details>
          </div>
        </Panel>
      )}

      {job?.status === 'failed' && job.error && !summary && (
        <div className="text-xs text-red-400 font-mono border border-red-900/60 bg-red-950/30 rounded-sm p-3">
          Scan failed: {job.error}
        </div>
      )}

      {summary && <ScanResults summary={summary} onOpenTarget={onOpenTarget} />}

      {!summary && lastScan && (
        <div className="space-y-3">
          <h3 className="text-xs font-bold text-zinc-300">
            Your last scan <span className="text-zinc-500 font-normal">— {fmtTime(lastScan.createdAt)} · RA {lastScan.summary.ra}, Dec {lastScan.summary.dec} · saved automatically</span>
          </h3>
          <ScanResults summary={lastScan.summary} onOpenTarget={onOpenTarget} />
        </div>
      )}
    </div>
  );
}
