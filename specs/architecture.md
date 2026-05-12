# Architecture decisions (TERRA)

## Intent

Build a **multi-cluster monitoring dashboard** with **dashboard-owned authentication**, consuming **Cisco Catalyst SD-WAN Manager APIs** first. **Configuration** remains primarily in Manager.

## High-level shape (target)

- **Connectors** abstract upstream systems:
  - `sdwan-manager` (initial)
  - `catalyst-center` (future; may share device identity concepts but different APIs and scope)
- **Ingestion / sync** jobs pull device and telemetry primitives on sane intervals; respect API rate limits and pagination.
- **Projection layer** (read models) powers UI lists, maps, and history charts without hammering upstream on every page load.
- **Alerting** combines upstream events with dashboard-defined thresholds (details TBD).

## Runtime and packaging

- **Operator UI** follows `specs/design-system.md` (Tailwind + shadcn-style CSS variables, token layers, automated guardrails) and ships with the same **Compose**-first story as the API services.
- **Docker Compose** is the **mandatory** default way to run the delivered application stack (services, dependencies, documented `up` / `down` workflow).
- **Canonical command (repo root):** `docker compose up --build -d` — brings up all defined services; default **user-facing WebUI** is **`https://localhost:4434`** (nginx TLS edge → FastAPI; avoids clashing with common **8000** usage). Override host port via `TERRA_HTTPS_PORT` in `.env`. Default certificate is **self-signed**; operators may drop **`server.crt` / `server.key`** PEMs into `docker/certs/` before start. Liveness: **`GET /health`** through the HTTPS edge.
- **Admin operator logs:** in-memory ring buffer with `/admin/logs` and `GET /api/v1/admin/logs` (see `specs/logging-ui.md`); not a durable audit trail across process restarts.
- **Platforms:** **macOS**, **Linux**, and **Windows** (support **Docker Desktop** with the WSL2-backed engine as the documented Windows model).
- **CPU:** images and Compose must support **amd64** and **arm64** (including **Apple Silicon** Macs).

### SD-WAN multi-manager inventory sync

- **SQLite** (default dev DB): raising **`TERRA_SDWAN_BATCH_MAX_CONCURRENT_MANAGERS`** increases parallel inventory writers and may cause `database is locked`; keep the default low or use PostgreSQL for heavy multi-Manager parallel sync.

## Considered / discarded

- **“Screen scrape the Manager WebUI”** — rejected: brittle, auth-coupled, and hostile to multi-cluster scale.
- **“Embed Manager UI in an iframe”** — rejected: does not meet the “simple, intern-friendly” bar and blurs security boundaries.
- **“Bare-metal / native install as the only supported path”** — rejected as the **primary** story: operators and agents need a single, repeatable Compose-based entrypoint; native installs may exist later as optional extras if justified.

## Open points

- Deployment topology (single-tenant SaaS vs customer-hosted vs hybrid).
- Time-series technology for GPS and interface metrics.

When implementation choices land, update this file in the same PR.
