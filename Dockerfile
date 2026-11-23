# Lightweight, production-ready Dockerfile for PocketLab
# Optimized for Render.com Free Tier (512 MB RAM) and any cloud VPS
# Preserves 100% of scientific accuracy: AutoDock Vina, OpenBabel, RDKit, Meeko, BioPython

FROM node:22-slim AS frontend-builder
WORKDIR /frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.11-slim
WORKDIR /app

# Install native scientific engines (AutoDock Vina + OpenBabel) + RDKit graphics deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    autodock-vina \
    openbabel \
    libxrender1 \
    libxext6 \
    libexpat1 \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./backend/
COPY --from=frontend-builder /frontend/dist ./frontend_dist

ENV PORT=10000
ENV MAX_CONCURRENT_DOCKS=1
ENV VINA_CPU_THREADS=1
ENV SESSION_TTL_SECONDS=3600

EXPOSE 10000

CMD ["sh", "-c", "uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port ${PORT:-10000}"]
