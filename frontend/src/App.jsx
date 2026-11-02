import React, { useCallback, useState } from 'react';
import { Activity, BarChart2, Compass, CheckCircle2, History, Radar } from 'lucide-react';
import Scanner from './views/Scanner.jsx';
import Observatory from './views/Observatory.jsx';
import Sweeper from './views/Sweeper.jsx';
import QaBenchmarks from './views/QaBenchmarks.jsx';
import HistoryView from './views/HistoryView.jsx';
import { SliderEnds } from './components.jsx';

const PIPELINES = ['SPOC', 'TESS-SPOC', 'QLP'];

export default function App() {
  // Stage 4: the Scanner (v1's simple front door) is the home view;
  // the workstation views live under "Advanced tools".
  const [view, setView] = useState('scanner');

  // Global settings (sidebar). These are sent with every analyze run —
  // see the honesty note under the pipeline checkboxes.
  const [pipelines, setPipelines] = useState({ SPOC: true, 'TESS-SPOC': true, QLP: true });
  const [blsPoints, setBlsPoints] = useState(25000);
  const [detrendWindow, setDetrendWindow] = useState(101);
  const settings = { pipelines, blsPoints, detrendWindow };

  // Seed for opening a target/run in the Observatory from other views.
  const [obsSeed, setObsSeed] = useState(null);
  const openTarget = useCallback((tic, radius) => {
    setObsSeed({ tic, radius, jobId: null, nonce: Date.now() });
    setView('observatory');
  }, []);
  const openJob = useCallback((run) => {
    setObsSeed({
      tic: run.params?.tic_id,
      radius: run.params?.host_radius,
      jobId: run.job_id,
      nonce: Date.now(),
    });
    setView('observatory');
  }, []);

  const advancedNav = [
    { id: 'observatory', label: 'Diagnostic Observatory', icon: BarChart2 },
    { id: 'sweeper', label: 'Sky Sweeper', icon: Compass },
    { id: 'benchmarks', label: 'QA Benchmarks', icon: CheckCircle2 },
    { id: 'history', label: 'History & Discoveries', icon: History },
  ];

  const navBtn = (tab) => (
    <button key={tab.id} onClick={() => setView(tab.id)}
      className={`w-full flex items-center gap-2 px-3 py-2 text-xs font-medium rounded-sm transition-colors ${
        view === tab.id
          ? 'bg-blue-900/30 text-blue-400 border border-blue-800/50'
          : 'text-zinc-400 hover:bg-zinc-800/50 hover:text-zinc-200 border border-transparent'
      }`}>
      <tab.icon className="h-4 w-4" /> {tab.label}
    </button>
  );

  return (
    <div className="flex h-screen bg-zinc-950 text-zinc-300 font-sans overflow-hidden">
      <aside className="w-64 border-r border-zinc-800 bg-zinc-900 flex flex-col flex-shrink-0">
        <div className="p-4 border-b border-zinc-800 flex items-center gap-2">
          <Activity className="h-5 w-5 text-blue-500" />
          <span className="font-bold text-sm tracking-tight text-zinc-100 leading-tight">
            Exoplanet Hunter<br />
            <span className="text-[10px] text-zinc-500 font-normal">Terminal Workstation · real TESS data</span>
          </span>
        </div>

        <nav className="flex-1 overflow-y-auto p-3 space-y-1">
          <div className="text-[10px] font-bold uppercase text-zinc-500 mb-2 mt-1 px-2 tracking-wider">Start here</div>
          {navBtn({ id: 'scanner', label: 'Deep Space Scanner', icon: Radar })}

          <div className="text-[10px] font-bold uppercase text-zinc-500 mb-2 mt-4 px-2 tracking-wider border-t border-zinc-800 pt-3">Advanced tools</div>
          {advancedNav.map(navBtn)}

          <div className="border-t border-zinc-800 my-4 pt-4">
            <div className="text-[10px] font-bold uppercase text-zinc-500 mb-3 px-2 tracking-wider">Global Settings</div>
            <div className="px-2 space-y-4">
              <div className="flex flex-col gap-1">
                <label className="text-[10px] text-zinc-400 font-semibold">Allowed Pipelines</label>
                <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs">
                  {PIPELINES.map((p) => (
                    <label key={p} className="flex items-center gap-1 cursor-pointer hover:text-white">
                      <input type="checkbox" checked={!!pipelines[p]}
                        onChange={(e) => setPipelines((prev) => ({ ...prev, [p]: e.target.checked }))}
                        className="accent-blue-600" /> {p}
                    </label>
                  ))}
                </div>
                <p className="text-[10px] text-zinc-600 leading-snug mt-1">
                  Sent with each run and recorded in its history. Note: the engine currently always
                  searches SPOC + TESS-SPOC + QLP with an unfiltered fallback — unticking a box does
                  not yet change the engine's search.
                </p>
              </div>

              <div className="flex flex-col gap-1">
                <label className="text-[10px] text-zinc-400 font-semibold flex justify-between">
                  BLS Grid Density <span className="font-mono">{blsPoints.toLocaleString()} pts</span>
                </label>
                <input type="range" min="5000" max="50000" step="5000" value={blsPoints}
                  onChange={(e) => setBlsPoints(Number(e.target.value))} className="accent-blue-600" />
                <SliderEnds min="5,000" max="50,000" />
              </div>

              <div className="flex flex-col gap-1">
                <label className="text-[10px] text-zinc-400 font-semibold flex justify-between">
                  Detrend Window <span className="font-mono">{detrendWindow}</span>
                </label>
                <input type="range" min="31" max="201" step="10" value={detrendWindow}
                  onChange={(e) => setDetrendWindow(Number(e.target.value))} className="accent-blue-600" />
                <SliderEnds min="31" max="201" />
              </div>
            </div>
          </div>
        </nav>

        <div className="p-3 border-t border-zinc-800 text-[10px] text-zinc-600 leading-snug">
          Engine: hunter.py (lightkurve + astropy BLS) via the job-queue API.
          One job runs at a time; history is saved in the app.
        </div>
      </aside>

      <main className="flex-1 flex flex-col h-full overflow-y-auto bg-zinc-950">
        {view === 'scanner' && <Scanner settings={settings} onOpenTarget={openTarget} />}
        {view === 'observatory' && <Observatory settings={settings} seed={obsSeed} />}
        {view === 'sweeper' && <Sweeper settings={settings} onOpenTarget={openTarget} />}
        {view === 'benchmarks' && <QaBenchmarks onOpenTarget={openTarget} />}
        {view === 'history' && <HistoryView onOpenJob={openJob} />}
      </main>
    </div>
  );
}
