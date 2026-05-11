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
- **Platforms:** **macOS**, **Linux**, and **Windows** (support **Docker Desktop** with the WSL2-backed engine as the documented Windows model).
- **CPU:** images and Compose must support **amd64** and **arm64** (including **Apple Silicon** Macs).

## Considered / discarded

- **“Screen scrape the Manager WebUI”** — rejected: brittle, auth-coupled, and hostile to multi-cluster scale.
- **“Embed Manager UI in an iframe”** — rejected: does not meet the “simple, intern-friendly” bar and blurs security boundaries.
- **“Bare-metal / native install as the only supported path”** — rejected as the **primary** story: operators and agents need a single, repeatable Compose-based entrypoint; native installs may exist later as optional extras if justified.

## Open points

- Deployment topology (single-tenant SaaS vs customer-hosted vs hybrid).
- Time-series technology for GPS and interface metrics.

When implementation choices land, update this file in the same PR.
