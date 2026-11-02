# Running Exoplanet Hunter on GitHub Codespaces (Dev's chosen host, 2026-11-02)

Why: free on Dev's existing GitHub account (120 core-hours/month on GitHub Free =
~60 hours/month on the 2-core / 8GB machine), no card, no new signup. The app is
live at a public forwarded-port link ONLY while a Codespace session is running.

## Launch (Dev, ~2 minutes, one-time per session)
1. Go to https://github.com/thekni8/exoplanet-hunter
2. Green **Code** button → **Codespaces** tab → **Create codespace on main**.
3. Wait for the build: the devcontainer installs `requirements.txt` automatically.
4. Start the app (Terminal in the Codespace):
   `./run.sh`
   This builds the React UI on first run, then serves UI + API together on
   port 8000. Later starts skip the build — just `./run.sh` again.
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

## What Pingu still owes before the first launch
- Stage 2 (api.py) finished + tested, Stage 3 (React UI wired to the API).
- A one-command start script (`./run.sh`) so step 4 above becomes a single click/command (Dev's requirement 16A).
- Dev's go-ahead to push hunter.py / api.py / frontend / .devcontainer to the repo —
  Codespaces can only run what's on GitHub.
