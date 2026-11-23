# Lightweight, production-ready Dockerfile for PocketLab
# Optimized for 512 MB RAM Free Tiers (SnapDeploy / Render) and any cloud VPS
# Uses smina (AutoDock Vina engine, ~35 MB RAM vs Vina 1.2's 550 MB lookup table)

FROM node:22-slim AS frontend-builder
WORKDIR /frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.11-slim
WORKDIR /app

# Install OpenBabel, RDKit graphics deps, and low-RAM 64-bit Smina (Vina-compatible engine)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    openbabel \
    libxrender1 \
    libxext6 \
    libexpat1 \
    && curl -L -o /usr/local/bin/vina "https://sourceforge.net/projects/smina/files/smina.static/download" \
    && chmod +x /usr/local/bin/vina \
    && /usr/local/bin/vina --version \
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
