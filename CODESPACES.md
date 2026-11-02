# Running Exoplanet Hunter on GitHub Codespaces (Dev's chosen host, 2026-11-02)

Why: free on Dev's existing GitHub account (120 core-hours/month on GitHub Free =
~60 hours/month on the 2-core / 8GB machine), no card, no new signup. The app is
live at a public forwarded-port link ONLY while a Codespace session is running.

## Launch (Dev, ~2 minutes, one-time per session)
1. Go to https://github.com/thekni8/exoplanet-hunter
2. Green **Code** button → **Codespaces** tab → **Create codespace on main**.
3. Wait for the editor to load. Setup is now deliberately minimal (no hidden
   installs behind the "Setting up" screen — that design hung Dev's first
   launch on 2026-11-02), so this should be quick.
4. Start the app (Terminal in the Codespace):
   `bash run.sh`
   (Use `bash run.sh`, not `./run.sh` — the file is stored in git without its
   executable bit, and GitHub's API pushes can't set it; `bash` doesn't care.)
   On the FIRST run this installs the Python dependencies and builds the
   React UI **in the terminal, visibly** (a few minutes — watch it, errors
   show here instead of hiding), then serves UI + API together on port 8000.
   Later starts skip the installs/build — just `./run.sh` again.
5. The port-8000 browser tab should open automatically. If the link only works
   while logged in as Dev, set it public by hand: **Ports** panel → right-click
   port 8000 → **Port Visibility → Public**. That link is the one anyone can open.
6. When done: github.com/codespaces → **... → Stop codespace** (stopping is what
   saves the monthly hours; it also auto-stops after ~30 min idle).

## Limits that shape how the app behaves here
- 2-core / 8GB RAM machine → the job queue (one analysis at a time) is mandatory,
  and the sector slider matters. 8GB is 8x Streamlit Cloud, but not unlimited.
- ~60 machine-hours/month free → sessions are events, not always-on. History and
  discoveries persist in the repo-side SQLite data only if committed/pushed back
  or exported — treat the Codespace disk as temporary across deleted codespaces
  (a stopped codespace keeps its disk; a deleted one does not).
- 15GB storage quota across Codespaces → MAST cache policy (keep hits, purge junk)
  is what keeps this viable.
- Codespaces get auto-deleted after a retention period of inactivity (~30 days
  by default) — the CODE is safe in the repo; only the machine is disposable.

## Status
- Stages 1–3 built, tested and pushed (2026-11-02). First launch attempt the
  same day hung on the "Setting up your codespace" screen; the fix (minimal
  devcontainer, installs moved into `run.sh`) was pushed the same morning.
  If a Codespace ever hangs at "Setting up" again: Stop it from
  github.com/codespaces, start it again; if that fails, Delete + recreate —
  recreation always pulls the current repo config.
- Port 8000's protocol must stay **HTTP** (the app serves plain HTTP; GitHub
  adds the HTTPS layer outside). An earlier config set `protocol: https`,
  which made the tunnel speak TLS to uvicorn: browser got HTTP 502 and the
  terminal filled with "Invalid HTTP request received" warnings. If that
  ever recurs in a live session: Ports tab → right-click 8000 → Change Port
  Protocol → HTTP, then reload.
- Dev's home ISP DNS (Jio) REFUSES `*.app.github.dev` lookups — forwarded
  links fail with a fake "NXDOMAIN/typo" error in Chrome until DNS is routed
  around it (Chrome Secure DNS → Cloudflare 1.1.1.1, or a macOS DNS override).
