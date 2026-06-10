# syntax=docker/dockerfile:1
# Multi-arch base (amd64 + arm64) for dev laptops and Linux servers.

FROM node:20-bookworm-slim AS frontend-build
WORKDIR /app
COPY package.json package-lock.json ./
COPY frontend/package.json frontend/
RUN npm ci
COPY frontend/ frontend/
RUN npm run build -w terra-dashboard-frontend

FROM python:3.11-slim-bookworm AS runtime

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md /app/
COPY src/ /app/src/
COPY --from=frontend-build /app/src/terra/static/dist /app/src/terra/static/dist
COPY docker/api/entrypoint.sh /entrypoint.sh

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir . \
    && chmod +x /entrypoint.sh

# Writable DB path (bind mount or named volume at /data).
ENV TERRA_DATABASE_URL=sqlite:////data/terra.db

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/health >/dev/null || exit 1

ENTRYPOINT ["/entrypoint.sh"]
