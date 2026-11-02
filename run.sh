#!/usr/bin/env bash
# Exoplanet Hunter — one-command start (Dev's requirement 16A).
# Builds the React UI if needed, then serves UI + API together on :8000.
# In a Codespace:  ./run.sh   then open the forwarded port-8000 link.
set -euo pipefail
cd "$(dirname "$0")"

# --- Frontend: build only if dist is missing (don't rebuild every start) ---
if [ ! -f frontend/dist/index.html ]; then
  if command -v npm >/dev/null 2>&1; then
    echo "[run.sh] Building frontend (first run only)..."
    (cd frontend && { [ -d node_modules ] || npm install; } && npm run build)
  else
    echo "[run.sh] WARNING: npm not found and frontend/dist missing — API only, no UI."
  fi
fi

# --- Python env: prefer the project venv if present ---
if [ -x .venv/bin/uvicorn ]; then
  UVICORN=.venv/bin/uvicorn
else
  UVICORN=uvicorn
fi

echo "[run.sh] Starting Exoplanet Hunter on http://0.0.0.0:8000"
exec "$UVICORN" api:app --host 0.0.0.0 --port 8000
