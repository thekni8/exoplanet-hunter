import React from 'react';

// Beginner's Guide — static teaching page, no API calls, no data.
// Every range stated here matches the "Range:" hint printed above the
// matching input (see RANGE_LABELS_REPORT.md) so the two never disagree,
// and every number quoted (thresholds, the WASP-126 b check) is a real,
// verified value from the engine's own test runs.
//
// Readability pass (Dev, 2026-11-02): this page opts out of the narrow
// centred column the other views use — it spans the full content width
// and uses large type throughout. The shared Panel header is 11px, so
// this file uses a local GuidePanel variant instead of restyling the
// shared component (other views keep their compact look).

function GuidePanel({ title, children }) {
  return (
    <div className="bg-zinc-900 border border-zinc-800 rounded-sm overflow-hidden">
      {title && (
        <div className="px-5 py-3 border-b border-zinc-800 flex items-center justify-between bg-zinc-950/50">
          <span className="text-xl font-bold text-zinc-100">{title}</span>
        </div>
      )}
      {children}
    </div>
  );
}

function Step({ n, children }) {
  return (
    <li className="flex gap-4">
      <span className="flex-shrink-0 w-8 h-8 rounded-full bg-blue-900/40 border border-blue-800/60 text-blue-300 text-base font-bold flex items-center justify-center mt-1">{n}</span>
      <div className="text-lg text-zinc-400 leading-8">{children}</div>
    </li>
  );
}

function ConceptCard({ name, what, range, pick }) {
  return (
    <div className="bg-zinc-900 border border-zinc-800 rounded-sm p-6 flex flex-col gap-3">
      <div className="text-xl font-bold text-zinc-100">{name}</div>
      <p className="text-lg text-zinc-400 leading-8">{what}</p>
      {range && <div className="text-sm text-zinc-500 font-mono">Range: {range}</div>}
      {pick && (
        <p className="text-lg leading-8">
          <span className="text-blue-400 font-semibold">Beginner pick: </span>
          <span className="text-zinc-400">{pick}</span>
        </p>
      )}
    </div>
  );
}

function SectionTitle({ children, sub }) {
  return (
    <div className="pt-4">
      <h3 className="text-3xl font-bold text-zinc-100">{children}</h3>
      {sub && <p className="text-lg text-zinc-500 mt-2 leading-8">{sub}</p>}
    </div>
  );
}

const CONCEPTS = [
  {
    name: 'RA — Right Ascension (deg)',
    what: "The sky's version of longitude: it says how far around the sky to point, measured in degrees. Together with Dec it is the address of the patch of sky you want to search.",
    range: '0 – 360',
    pick: 'Leave the Scanner’s pre-filled 124.456 for your first scans — it is a known, well-behaved patch.',
  },
  {
    name: 'Dec — Declination (deg)',
    what: "The sky's version of latitude: how far north (+) or south (−) of the sky's equator to point. RA + Dec together are a full sky address, like latitude + longitude on Earth.",
    range: '−90 – +90',
    pick: 'The pre-filled −67.568 (a southern patch) pairs with the default RA. Negative is fine — it just means south.',
  },
  {
    name: 'Search radius / Cone radius (deg)',
    what: 'How wide a circle around your RA/Dec the app searches for stars. A bigger circle means more stars to check — and a longer scan.',
    range: 'Scanner 0.01 – 1.00° · Sweeper cone 0.01 – 2°',
    pick: '0.10° on the Scanner, 0.15° on the Sweeper. Only widen it once you are happy waiting longer.',
  },
  {
    name: 'Stars to scan / Max Stars',
    what: 'How many of the screened stars actually get the full treatment: downloading their real TESS data and running the planet search on each one. Every star is real work for the machine.',
    range: 'Scanner 5 – 100 · Sweeper 1 – 1,000 (whole number)',
    pick: '20 on the Scanner, 8 on the Sweeper. Scans run in the background and always finish the whole list, so bigger is allowed — just slower.',
  },
  {
    name: 'TIC ID',
    what: "A star's catalog number in the TESS Input Catalog — its ID card. The Observatory needs one to study a single star. You get TIC numbers from Scanner/Sweeper hit cards, so you never have to memorise any.",
    range: 'positive whole number',
    pick: 'For practice, use 25155310 — that is WASP-126 b, a star with a known planet (see the walkthrough below).',
  },
  {
    name: 'Tmag — star brightness',
    what: 'How bright the star looks to TESS. It works backwards, like golf scores: a LOWER number is a BRIGHTER star. Very bright stars can overwhelm the camera; very faint ones are noisy.',
    range: '0 – 20 (Min must be ≤ Max)',
    pick: 'Keep the Sweeper defaults, Min 11.5 / Max 15. The Scanner quietly uses its own proven screen (13.5 – 15.4) so you don’t have to think about this there.',
  },
  {
    name: 'Star radius / Host Radius (R☉)',
    what: 'How big the star is, measured in Suns — 1.0 means exactly the size of our Sun. The app needs the star’s size to turn a light dip into a planet size. On the Sweeper these boxes screen which star sizes to include; on the Observatory, Host Radius is the size of the one star you are studying.',
    range: '0.1 – 10 (Min must be ≤ Max on the Sweeper)',
    pick: 'Sweeper defaults 0.5 – 1.8 cover Sun-like stars and smaller. Observatory practice value for WASP-126 b: 1.30.',
  },
  {
    name: 'Sector Cap — and what a "sector" is',
    what: 'TESS stares at one strip of sky for about 27 days at a time; each of those observation chunks is called a sector. A star can have data from many sectors. The cap says how many chunks to use per star: more sectors = more data and a stronger signal, but a slower run.',
    range: '1 – 20, or All (Observatory)',
    pick: '2. It is the setting behind every verified result in this app, including the WASP-126 b check. Raise it for a second, deeper look at a promising star.',
  },
  {
    name: 'BLS Grid Points — "how hard the app thinks"',
    what: 'BLS is the name of the dip-hunting search the engine runs. The grid points are how many different planet periods it tries before picking the best one. More points = a finer, more careful search = slower.',
    range: 'Sweeper box 1,000 – 100,000 · Sidebar slider 5,000 – 50,000',
    pick: '10,000 when sweeping many stars; 25,000 (the sidebar default) when studying one star properly. There is rarely a reason to touch this as a beginner.',
  },
  {
    name: 'Detrend Window',
    what: 'Before hunting dips, the app irons out slow wobbles in the starlight (from the spacecraft and the star itself) so the fast planet dips stand out — that ironing is called detrending or flattening, and the window is how wide the iron is, in data points. It must be an odd number; the app handles that for you.',
    range: '31 – 201 (odd)',
    pick: '101 — the default. Every verified run used it. Leave it alone until you know exactly why you are changing it.',
  },
  {
    name: 'Period (days) — Min / Max Period',
    what: 'How many days pass between one dip and the next — in other words, the length of the planet’s year. On the Observatory, Min and Max Period tell the search which year-lengths to try: it tests everything between them.',
    range: '0.1 – 100 each, and Min must be less than Max',
    pick: 'The defaults, 0.5 – 25, cover most planets TESS can see. A found period is also printed on every result — WASP-126 b’s came back as about 3.29 days.',
  },
  {
    name: 'SDE — the strength score',
    what: 'Every result gets an SDE score: how clearly the best dip stands out from random noise. It is a score the app gives you, not a number you type in. Roughly: below 8.5 is treated as noise, 8.5 – 11 is a weaker signal worth a second look, and 11 or more is a strong signal. For scale, the known planet WASP-126 b scores about 21.9.',
    range: null,
    pick: 'Anything scoring 8.5 or more is saved to Discoveries automatically. Treat 11+ as "drop everything and run the fake-check".',
  },
  {
    name: 'Transit depth %',
    what: 'How much the star’s light drops during a dip, as a percentage. A bigger planet (compared to its star) blocks more light, so a deeper dip usually means a bigger planet. This is a result, not a setting.',
    range: null,
    pick: 'Honest warning: this app’s depths currently read LOW compared to published catalog values — a known limitation being investigated. Compare dips to each other, not to textbooks, for now.',
  },
  {
    name: 'Planet radius (R⊕)',
    what: 'The estimated size of the planet, in Earth radii — 1.0 would be an Earth twin, about 11 would be a Jupiter. The app works it out from the dip depth and the star’s radius.',
    range: null,
    pick: 'Because depths read low (see above), treat sizes as "at least this big" rather than exact. WASP-126 b measures about 6.4 R⊕ here versus about 10.7 R⊕ in the catalog.',
  },
  {
    name: '"Is it a fake?" — the odd/even verdicts',
    what: 'The most common impostor is an eclipsing binary: two stars eclipsing each other, mimicking a planet. This test folds the data at twice the period and compares alternate dips. A real planet blocks the same amount of light every orbit, so its odd and even dips match. Two different stars usually eclipse by different amounts, so theirs don’t.',
    range: null,
    pick: 'Planet-like = the two dips match (within 25% of each other) — encouraging, not proof. Likely eclipsing binary = the dips differ by more than 25% — probably two stars. Inconclusive = no clear dip could be measured at either spot, so the test can’t judge.',
  },
];

export default function Guide() {
  return (
    <div className="p-4 sm:p-6 lg:p-8 space-y-8 w-full">
      <div>
        <h2 className="text-4xl font-bold text-zinc-100 tracking-tight">Beginner’s Guide</h2>
        <p className="text-lg text-zinc-400 mt-3 leading-8">
          Everything in this app explained in plain words — what each value means, what to type,
          and how to read what comes back. No astrophysics degree required.
        </p>
      </div>

      <GuidePanel title="Start here — what this app does">
        <div className="p-6 space-y-5">
          <p className="text-lg text-zinc-400 leading-8">
            Exoplanet Hunter searches <span className="text-zinc-200 font-semibold">real data from NASA’s TESS
            space telescope</span> for planets orbiting other stars. A planet crossing its star makes the
            starlight dip by a tiny amount, over and over — the app hunts for those repeating dips.
            Nothing here is simulated: if a scan finds nothing, that patch of sky was genuinely quiet.
          </p>
          <div className="text-sm font-bold uppercase tracking-wider text-zinc-500">Your normal hunt, step by step</div>
          <ol className="space-y-4">
            <Step n={1}>Open the <span className="text-zinc-200 font-semibold">Deep Space Scanner</span> (it’s the home screen). It comes pre-filled with a patch of sky — you can leave every value exactly as it is.</Step>
            <Step n={2}>Press <span className="text-zinc-200 font-semibold">Initialize Scan</span>. The app picks suitable stars in that patch, skips any that people have already flagged, downloads their real TESS data and searches each one. One job runs at a time, and a scan always finishes its whole list.</Step>
            <Step n={3}>Watch the progress bar, or come back later — the result waits for you. When it finishes you’ll see a plain summary: how many stars were scanned and how many strong signals were found.</Step>
            <Step n={4}>If a <span className="text-zinc-200 font-semibold">🎯 hit card</span> appears, that star scored SDE 11 or more — a strong, new signal nobody has flagged. Weaker signals (8.5 – 11) are listed quietly below the hits.</Step>
            <Step n={5}>On the hit card, press <span className="text-zinc-200 font-semibold">“Is it a fake? →”</span>. The app runs the odd/even test automatically and answers in plain words: planet-like, likely a binary-star fake, or inconclusive.</Step>
            <Step n={6}>Press <span className="text-zinc-200 font-semibold">“Open in Observatory”</span> on the same card to study that star in depth — full charts, the works. Either way, the hit is already saved for you under <span className="text-zinc-200 font-semibold">History &amp; Discoveries</span>.</Step>
          </ol>
        </div>
      </GuidePanel>

      <SectionTitle sub="Every value in the app, one card each — what it is, the exact range the boxes accept (the same ranges printed above each input), and a safe beginner value.">
        What every value means
      </SectionTitle>
      <div className="grid grid-cols-1 lg:grid-cols-2 2xl:grid-cols-3 gap-5">
        {CONCEPTS.map((c) => <ConceptCard key={c.name} {...c} />)}
      </div>

      <SectionTitle sub="When you’re ready to go past the Scanner. Both walkthroughs use safe values — the first one is a star with a KNOWN planet, so you can watch the app succeed before trusting it on unknown sky.">
        Your first advanced run, step by step
      </SectionTitle>

      <GuidePanel title="Walkthrough A — study one star in the Observatory (WASP-126 b)">
        <div className="p-6">
          <ol className="space-y-4">
            <Step n={1}>In the left nav, under <span className="text-zinc-200 font-semibold">Advanced tools</span>, open <span className="text-zinc-200 font-semibold">Diagnostic Observatory</span>.</Step>
            <Step n={2}>Set <span className="text-zinc-200 font-semibold">Target TIC ID</span> to <span className="font-mono text-zinc-200">25155310</span> — that’s WASP-126 b, a real known planet, so this run is a practice target with a known right answer.</Step>
            <Step n={3}>Set <span className="text-zinc-200 font-semibold">Host Radius</span> to <span className="font-mono text-zinc-200">1.30</span>. Leave <span className="text-zinc-200 font-semibold">Min Period 0.5</span> and <span className="text-zinc-200 font-semibold">Max Period 25</span> as they are.</Step>
            <Step n={4}>Set the <span className="text-zinc-200 font-semibold">Sector Cap</span> slider to <span className="font-mono text-zinc-200">2</span> and leave the “All” box unticked. Leave the sidebar settings alone too (BLS Grid Density 25,000, Detrend Window 101).</Step>
            <Step n={5}>Press <span className="text-zinc-200 font-semibold">Run Analysis</span> and watch the job progress log. It downloads the star’s real TESS light curves — this takes a little while, and only one job runs at a time.</Step>
            <Step n={6}>Read the result: you should get a <span className="text-zinc-200 font-semibold">period of about 3.29 days</span> (published value: 3.2822) and an <span className="text-zinc-200 font-semibold">SDE of about 21.9</span>. The four charts show the raw starlight, the flattened version, the period search, and the dips all lined up in phase. If your numbers look like these — congratulations, you just re-found a planet.</Step>
          </ol>
        </div>
      </GuidePanel>

      <GuidePanel title="Walkthrough B — your own custom sky sweep in the Sweeper">
        <div className="p-6">
          <ol className="space-y-4">
            <Step n={1}>Open <span className="text-zinc-200 font-semibold">Sky Sweeper</span> under Advanced tools. The difference from the Scanner: here YOU choose the star filters instead of using the Scanner’s built-in recipe.</Step>
            <Step n={2}>For a first sweep, change nothing. The built-in starter values are: RA <span className="font-mono text-zinc-200">83.82</span>, Dec <span className="font-mono text-zinc-200">−5.39</span>, Cone Radius <span className="font-mono text-zinc-200">0.15</span>, Min Tmag <span className="font-mono text-zinc-200">11.5</span>, Max Tmag <span className="font-mono text-zinc-200">15</span>, Min Star Radius <span className="font-mono text-zinc-200">0.5</span>, Max Star Radius <span className="font-mono text-zinc-200">1.8</span>, Max Stars <span className="font-mono text-zinc-200">8</span>, Sector Cap <span className="font-mono text-zinc-200">2</span>, BLS Grid Points <span className="font-mono text-zinc-200">10,000</span>.</Step>
            <Step n={3}>Press <span className="text-zinc-200 font-semibold">Launch Sweep</span>. If you typed anything outside its range, the app refuses politely and tells you the correct range — nothing is submitted and nothing is silently “fixed” for you.</Step>
            <Step n={4}>Follow the progress log as each star is downloaded and searched. Any star scoring SDE 8.5 or more appears in the hits table — and is saved to Discoveries at the same moment.</Step>
            <Step n={5}>Found a hit? Press <span className="text-zinc-200 font-semibold">Open in Observatory</span> next to it to study that star closely — its TIC and radius are carried over for you, and the charts will show you the dip with your own eyes. (The one-click “Is it a fake?” button lives on Scanner hit cards; for a Sweeper hit, the Observatory deep-dive is your study tool.)</Step>
            <Step n={6}>Later, change ONE thing at a time — a new RA/Dec patch, or Max Stars up to 20 — so you learn what each value actually does.</Step>
          </ol>
          <p className="text-base text-zinc-500 leading-7 mt-5">
            One difference to know: the Sweeper does not do the Scanner’s automatic “already known” skip — that
            Zooniverse check is a Scanner feature. In the Sweeper, a strong hit might be a planet someone else
            already found — the Observatory deep-dive is how you inspect it with your own eyes.
          </p>
        </div>
      </GuidePanel>

      <SectionTitle>Reading your results</SectionTitle>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        <div className="bg-zinc-900 border border-green-900/60 rounded-sm p-6">
          <div className="text-xl font-bold text-green-300 mb-3">A promising candidate looks like…</div>
          <ul className="text-lg text-zinc-400 leading-8 space-y-2.5 list-disc pl-6">
            <li>SDE of 11 or more (the Scanner raises a 🎯 for exactly this).</li>
            <li>A clean, repeating dip in the phase-folded chart — same depth, same shape, lining up neatly.</li>
            <li>The fake-check says <span className="text-zinc-200">planet-like</span>: odd and even dips the same size.</li>
            <li>A sensible period (roughly 0.5 – 25 days is TESS’s sweet spot) and a planet size that isn’t absurd.</li>
          </ul>
        </div>
        <div className="bg-zinc-900 border border-red-900/60 rounded-sm p-6">
          <div className="text-xl font-bold text-red-300 mb-3">A likely fake looks like…</div>
          <ul className="text-lg text-zinc-400 leading-8 space-y-2.5 list-disc pl-6">
            <li>The fake-check says <span className="text-zinc-200">likely eclipsing binary</span>: alternate dips are different sizes — that’s two stars, not a planet.</li>
            <li>SDE under 8.5: not even saved. That’s the app calling it noise, and it’s usually right.</li>
            <li>A messy phase-folded chart where the “dip” is really scattered points that don’t line up.</li>
            <li>V-shaped, very deep dips (several percent) — classic eclipsing-binary shape.</li>
          </ul>
        </div>
      </div>
      <GuidePanel title="Where your finds live">
        <div className="p-6 space-y-4">
          <p className="text-lg text-zinc-400 leading-8">
            Every run is recorded under <span className="text-zinc-200 font-semibold">History &amp; Discoveries</span>,
            and every star that scores <span className="text-zinc-200 font-semibold">SDE 8.5 or more is saved to
            Discoveries the moment it’s found</span>. You never save anything by hand, and re-running a scan never
            wipes an old find — that was the old app’s worst habit, and this one was built specifically to fix it.
          </p>
          <p className="text-lg text-zinc-400 leading-8">
            Last honesty note: a “planet-like” verdict means the signal survived the tests this app can run —
            it makes a star a <span className="text-zinc-200 font-semibold">candidate</span>, not a confirmed
            planet. Confirmation is a job for professional follow-up telescopes. What you have is a real,
            evidence-backed shortlist — which is exactly how the professionals start, too.
          </p>
        </div>
      </GuidePanel>
    </div>
  );
}
