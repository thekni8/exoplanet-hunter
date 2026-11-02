# Exoplanet Hunter — single-container build (API now, UI served by the
# same app in Stage 3). Host-agnostic: python:3.12-slim runs on ARM and
# x86_64, so the hosting target can change without a rebuild.
FROM python:3.12-slim

WORKDIR /app

# Dependencies first (layer caching). requirements.txt is shared with the
# CLI (hunter.py) and the API (api.py) — one dependency list for the project.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY hunter.py api.py ./

# Runtime state (SQLite history, result JSONs, plates) lives in /app/data —
# mount a volume there to keep history across container rebuilds.
RUN mkdir -p /app/data/results /app/data/plates /app/reports

EXPOSE 8000
CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"]

# Build & run:
#   docker build -t exoplanet-hunter .
#   docker run -p 8000:8000 -v hunter-data:/app/data exoplanet-hunter
