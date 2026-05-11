#!/bin/sh
set -e
# Trust reverse-proxy headers (nginx TLS terminator in Compose).
exec uvicorn terra.main:app \
  --host 0.0.0.0 \
  --port 8000 \
  --forwarded-allow-ips "${TERRA_FORWARDED_ALLOW_IPS:-*}"
