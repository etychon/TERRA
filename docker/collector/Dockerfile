# syntax=docker/dockerfile:1
# Collector worker: periodic SD-WAN sync + VictoriaMetrics push (amd64 + arm64).
FROM python:3.11-slim-bookworm AS runtime

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md /app/
COPY src/ /app/src/

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir .

ENV TERRA_SDWAN_BACKGROUND_SYNC=true

CMD ["python", "-m", "terra.collector"]
