# Lightweight, production-ready Dockerfile for PocketLab
# AutoDock Vina runs directly in the user's browser via WebAssembly (Webina) -> 0 MB server RAM for docking!

FROM node:22-slim AS frontend-builder
WORKDIR /frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.11-slim
WORKDIR /app

# Install OpenBabel + RDKit graphics deps (no heavy server docking binary needed!)
RUN apt-get update && apt-get install -y --no-install-recommends \
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
ENV MAX_CONCURRENT_DOCKS=2
ENV SESSION_TTL_SECONDS=3600

EXPOSE 10000

CMD ["sh", "-c", "uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port ${PORT:-10000}"]
