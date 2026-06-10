# Telemetry storage (VictoriaMetrics + Postgres)

## Intent

Store **high-volume time series** (performance, bandwidth, CPU, memory, cellular KPIs, tunnel counters, optional GPS samples) in **VictoriaMetrics** with a **Prometheus-compatible** query API. Keep **authoritative relational state** (users, RBAC, Manager registry, inventory projections, threshold configs, audit pointers) in **PostgreSQL**.

This split avoids SQLite/Postgres bloat from per-minute samples at **20k+ device** scale.

## Ingestion (Phase 1)

- **Protocol:** `POST` to VictoriaMetrics **`/api/v1/import/prometheus`** with **Prometheus text exposition** lines (optionally with millisecond timestamps). Implemented in code as a small HTTP client (`terra.telemetry_vm`); see repo for exact payload shape.
- **Initial gauges (inventory sync batch):** `terra_inventory_device_count`, `terra_sdwan_sync_instance_ok`, and `terra_sdwan_batch_managers_processed` (labels per the **Naming and labels** section below).
- **Cellular RF history (EIOLTE):** `terra_cellular_rssi`, `terra_cellular_rsrp`, `terra_cellular_rsrq` — one sample per histogram bucket from `POST /dataservice/statistics/eiolte/uniqueAggregation`, labels `manager_id`, `cluster`, `device_id`, `device_uuid`, `slot`, `active_sim`; timestamp = bucket `entry_time` (ms). Ingested by **`collector`** after each successful inventory sync ([`sdwan_cellular_history.py`](../src/terra_sdwan/sdwan_cellular_history.py)).
- **Producers:** the **`collector`** service is the primary writer after SD-WAN pulls. The **`core`** API may emit sparse operational gauges (for example after on-demand sync) without duplicating high-frequency device polling.
- **Network:** VictoriaMetrics listens only on the **Compose internal network** by default. Do not publish `8428` to the Internet without TLS and auth fronting.

## Naming and labels (conventions)

- **Metric names:** `terra_*` prefix for application-emitted series (e.g. `terra_inventory_device_count`, `terra_sdwan_sync_last_success_unix`).
- **Required labels (when applicable):** `manager_id`, `sdwan_instance_id` (numeric FK as string), `cluster` (display name, low cardinality).
- **Device-scoped samples:** `device_id` (TERRA `SyncedDevice.id`), `device_uuid` (`source_device_uuid`), plus `slot` / `active_sim` for cellular series. Avoid hostnames as label values. `tenant_id` label reserved for future use (empty for single-tenant).

## Retention and downsampling

- **Default retention:** **30 days** on the VictoriaMetrics single-node flag (`-retentionPeriod=30d`) in Compose. Operators may raise/lower per deployment.
- **GPS / location:** Prefer **Cisco Manager historical APIs** where they exist and are licensed for the deployment. For gaps or OT map playback that Manager does not retain, store **normalized location samples** in VictoriaMetrics with the same retention; apply **coarser scrape intervals** (minutes) and optional recording rules later to cap cardinality.
- **Downsampling:** not required in v1; revisit when raw series volume threatens disk SLOs.

## Source of truth

- **Latest inventory row / enrichment blob:** Postgres — projection for list and detail pages.
- **Historical cellular RF (RSRP/RSRQ/RSSI):** VictoriaMetrics — EIOLTE statistics ingest; UI reads via `GET /api/v1/me/devices/{id}/cellular/history` and batch sparklines.
- **Historical CPU, memory, bandwidth (future):** VictoriaMetrics — normalized gauges/counters from the collector.
- **User sessions, RBAC, audit metadata:** Postgres — durable dashboard audit trail (not the admin ring buffer).
- **Short-lived operator HTTP trace:** in-memory ring — see [`specs/logging-ui.md`](logging-ui.md).

## Query path (core → VM)

- **`core`** queries VictoriaMetrics over the internal URL (e.g. `http://victoriametrics:8428/prometheus/api/v1/query` for PromQL instant queries). Wire **read-only** dashboards first; enforce **RBAC** in `core` before proxying arbitrary PromQL from browsers.
- **Optional Grafana:** Compose profile `grafana` starts Grafana with a provisioned Prometheus datasource pointing at the internal VictoriaMetrics `/prometheus` prefix. Use for partner / power-user dashboards during build-out.

## Security

- No credentials in metric labels or help strings.
- SD-WAN Manager passwords must never appear in logs or samples (see `specs/architecture.md` secrets checklist).

## Considered / rejected

- **Storing all raw dataservice JSON as time series** — rejected: unbounded payload size and poor query ergonomics; store normalized fields or selected JSON in Postgres snapshots instead.
- **Prometheus server as the only store** — rejected for this repo default: VictoriaMetrics gives simpler long-retention single-binary ops for on-prem while staying PromQL-compatible.

Update this file when ingestion switches to OpenTelemetry, remote_write, or clustered VM.
