#!/usr/bin/env bash
# Start TERRA via Docker Compose with the debug overlay (Claude / local troubleshooting).
#
# - Publishes the API on the host (default all interfaces, port 18434 — not host 8000). Override with TERRA_DEBUG_HOST_BIND=127.0.0.1 for loopback-only.
# - Sets TERRA_DEBUG_EXPOSE_INTERNALS and a TERRA_DEBUG_TOKEN for /debug/* (see README).
#
# Usage:
#   ./scripts/launch-terra-debug.sh              # detached (-d)
#   ./scripts/launch-terra-debug.sh --build      # rebuild images, detached
#   ./scripts/launch-terra-debug.sh --no-detach # foreground (logs in terminal)
#
# After start:
#   curl -sS -H "X-Terra-Debug-Token: $TERRA_DEBUG_TOKEN" "http://127.0.0.1:${TERRA_DEBUG_API_PORT}/debug/summary"
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# Inside the container the API still listens on :8000; on the *host* we map a different port.
: "${TERRA_DEBUG_API_PORT:=18434}"
if [[ "$TERRA_DEBUG_API_PORT" == "8000" ]]; then
  echo "launch-terra-debug: host port 8000 is not used (often busy); defaulting TERRA_DEBUG_API_PORT=18434." >&2
  TERRA_DEBUG_API_PORT=18434
fi
export TERRA_DEBUG_API_PORT

: "${TERRA_DEBUG_HOST_BIND:=0.0.0.0}"
export TERRA_DEBUG_HOST_BIND

if [[ -z "${TERRA_DEBUG_TOKEN:-}" ]]; then
  if command -v openssl >/dev/null 2>&1; then
    export TERRA_DEBUG_TOKEN="$(openssl rand -hex 16)"
  else
    export TERRA_DEBUG_TOKEN="$(python3 -c 'import secrets; print(secrets.token_hex(16))')"
  fi
  echo "launch-terra-debug: generated TERRA_DEBUG_TOKEN (save/export to reuse in new shells):"
  echo "  export TERRA_DEBUG_TOKEN='${TERRA_DEBUG_TOKEN}'"
else
  echo "launch-terra-debug: using TERRA_DEBUG_TOKEN from the environment."
fi

# Persist for local agents / scripts (gitignored); same value the api container receives on next `up`.
RUN_DIR="$ROOT/.run"
mkdir -p "$RUN_DIR"
printf '%s\n' "$TERRA_DEBUG_TOKEN" >"$RUN_DIR/terra-debug.token"
chmod 600 "$RUN_DIR/terra-debug.token"
echo "launch-terra-debug: token saved to .run/terra-debug.token (chmod 600, gitignored)."

COMPOSE=(docker compose -f docker-compose.yml -f docker-compose.debug.yml)

detach=true
compose_args=()
for arg in "$@"; do
  if [[ "$arg" == "--no-detach" ]]; then
    detach=false
  elif [[ "$arg" == "-d" || "$arg" == "--detach" ]]; then
    : # detached mode is the default; avoid passing duplicate -d to compose
  else
    compose_args+=("$arg")
  fi
done

if $detach; then
  "${COMPOSE[@]}" up --build -d "${compose_args[@]}"
  echo ""
  echo "launch-terra-debug: stack is up (detached)."
else
  exec "${COMPOSE[@]}" up --build "${compose_args[@]}"
fi

echo ""
echo "Debug API (host bind ${TERRA_DEBUG_HOST_BIND}, port ${TERRA_DEBUG_API_PORT} — not 8000):"
echo "  http://127.0.0.1:${TERRA_DEBUG_API_PORT}/debug/summary"
if [[ "${TERRA_DEBUG_HOST_BIND}" != "127.0.0.1" ]]; then
  echo "  (LAN) http://<this-host-ip>:${TERRA_DEBUG_API_PORT}/debug/summary  e.g. http://192.168.2.3:${TERRA_DEBUG_API_PORT}/debug/summary"
fi
echo "Example:"
echo "  curl -sS -H \"X-Terra-Debug-Token: \${TERRA_DEBUG_TOKEN}\" \"http://127.0.0.1:${TERRA_DEBUG_API_PORT}/debug/summary\""
echo "Logs: docker compose -f docker-compose.yml -f docker-compose.debug.yml logs -f api"
