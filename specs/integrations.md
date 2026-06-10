# Integration requirements (TERRA)

## Cisco Catalyst SD-WAN Manager (initial)

**Canonical dataservice / HTTP map (endpoints, auth ladder, code pointers):** [`specs/sdwan-manager-api.md`](sdwan-manager-api.md).

- **Read-heavy** usage: inventory, device status, interfaces, performance/cellular telemetry where APIs expose it, IOx status where available, events/alerts feeds if exposed.
- **Auth:** service credentials stored in secure runtime configuration; rotate without code changes.
- **Scale:** multiple Manager endpoints must be representable without forking the UI.
- **Background / bulk inventory:** Periodic and “sync all” paths run **bounded parallel** pulls per Manager (`TERRA_SDWAN_BATCH_MAX_CONCURRENT_MANAGERS`) with **isolated DB sessions** per worker; operator logs use component **`sdwan_sync_batch`** with a **`run_id`** per tick (see `specs/logging-ui.md`). Inventory-phase HTTP uses **`TERRA_SDWAN_SYNC_INVENTORY_TIMEOUT_SECONDS`** per request (separate from the long-lived httpx client default).

## Multitenant Manager (provider + tenants)

- **Discovery:** `GET /dataservice/tenant` returns tenant rows on multitenant builds; **400/403/404/405** or an empty list is treated as **single-tenant** (legacy path: `GET /dataservice/device` only). Some lab or single-tenant builds answer **400** or **405** on the tenant endpoint when it is not in use.
- **Per-tenant inventory:** For each tenant with a resolvable switch id, TERRA calls **`POST /dataservice/tenant/{tenantId}/switch`**, captures **`VSessionId`** from the response (header or JSON), and sets it on the httpx client. With tenant scope active, inventory is merged from **`GET /dataservice/system/device/vedges`** and **`GET /dataservice/system/device/controllers`** (not from **`GET /dataservice/device`**, which is often empty when `VSessionId` is set). Single-tenant Managers still use **`GET /dataservice/device`** first; if that list has no WAN edges, TERRA also tries the vedges path before the full empty-list fallback ladder. Session cookies and `X-XSRF-TOKEN` from `open_manager_http_client` apply to the switch POST.
- **JWT + multitenant:** Bearer tokens still need **`X-XSRF-TOKEN`** aligned with the Manager session. TERRA refreshes it from **`GET /dataservice/client/server`** (`data.CSRFToken` or `data[0].CSRFToken`) before tenant switches. Provider multitenant pulls without `VSessionId` may still see only control-plane rows on `/dataservice/device`; the switch response’s `VSessionId` is required for WAN-edge lists on many production clusters (see [Catalyst SD-WAN API recipes — multitenant](https://github.com/etychon/Catalyst-SD-WAN-API-User-Receipe/blob/main/docs/multitenant-clusters.md)).
- **Persistence:** Each `synced_devices` row stores **`sdwan_tenant_id`** (switch id, empty when not multitenant) and **`sdwan_tenant_name`** (display label from the tenant row). Uniqueness is **`(sdwan_instance_id, source_device_uuid, sdwan_tenant_id)`** so the same hardware UUID may appear once per tenant. The **cluster** label in the UI is the Manager instance **`display_name`** (existing field).
- **Stale rows:** After a full successful multitenant pull (no tenant switch or inventory transport errors), rows for that Manager that were **not** in the merged inventory are **deleted**. If any tenant phase errors occur, pruning is skipped for that sync to avoid mass-removal on partial failures.
- **Live dataservice from the browser:** “Show live data” uses a fresh authenticated client and does not yet replay tenant switch; multitenant live reads may require a follow-up that stores tenant scope on the session or server-side proxy.
- **Administration — credential scope (per registered Manager):** After a successful **Verify**, TERRA probes `GET /dataservice/tenant` and a bounded number of `POST …/tenant/{id}/switch` calls (with JWT CSRF refresh). Results are stored on `SdWanManagerInstance` and shown on the SD-WAN administration table: **non-multitenant cluster** (no tenant registry), **multitenant · provider / all tenants** (multiple successful switches, or switches fail but provider-level `GET /dataservice/device` still works when multiple tenants are listed), **multitenant · single-tenant token** (multiple tenants listed but only one distinct switch succeeds), **multitenant · one tenant visible** (one tenant row — cannot distinguish provider-with-one-customer vs tenant token), or **unknown**. This is heuristic; unusual Manager policies or partial RBAC may misclassify until behavior is tightened with more signals.

Official reference: [Tenant — Cisco Catalyst SD-WAN Manager API](https://developer.cisco.com/docs/sdwan/20-16/tenant/).

## Manager dataservice: interface IPv4 gaps (cellular / dual-stack)

The primary table TERRA uses today is **`GET /dataservice/device/interface`** (and **`.../interface/synced`**), merged into inventory as `deviceInterface` (`src/terra_sdwan/sdwan_device_live.py`).

**Why `Cellular0/4/0` can show no IPv4 in that payload**

- Cisco’s **Get Device Interface** model is **per address family**: the same `ifname` often appears **twice** with different **`af-type`** (`ipv4` vs `ipv6`). The IPv4 row carries **`ip-address`** (sometimes with prefix, e.g. `10.101.3.3/16`); the IPv6 row may show **`ip-address": "-"`** with IPv6 in **`ipv6-address`**. If only one row is present, or keys differ by release, the IPv4 field can be empty even though the device has a usable address elsewhere.
- **Carrier / PDP** addresses are frequently **not** duplicated on the generic interface row; they appear under **cellular** realtime endpoints (same DevNet “Device Realtime Monitoring” family).

**Other dataservice APIs worth correlating by `deviceId` + interface name** (read-only monitoring; exact fields vary by IOS-XE / Manager release — validate against your Manager):

| Use | Path (prefix `GET …/dataservice`) |
|-----|-------------------------------------|
| Cellular PDP / session IPv4 (and related) | `/device/cellular/sessions` |
| Cellular attachment / network-side hints | `/device/cellular/network`, `/device/cellular/status`, `/device/cellular/modem` |
| DHCP client addresses per interface | `/device/dhcp/interface` |
| IPv4↔interface / L2 resolution | `/device/arp` |
| Local connected / interface-linked prefixes | `/device/ip/routetable`, `/device/ip/fib` |

**Operational note:** TERRA already fetches several **`/device/cellular/*`** paths during live poll / sync enrichment, but only stores them under `terraEnrichedFromSync.cellular_dataservice` — they are **not** joined back into `deviceInterface` rows for the device detail table. A future improvement is to **merge** session/network rows into interface rows by `ifname` / `ifName` / `interface` keys.

## Cellular RF history (EIOLTE statistics)

- **Source:** `POST /dataservice/statistics/eiolte/uniqueAggregation` (not the live `/device/cellular/*` GETs). Device scope uses query rule **`vdevice_name`** = inventory **system IP**. Request body must include **`aggregation`** (`field`, `metrics`, `histogram` on `entry_time`).
- **Ingest:** After each successful background inventory sync per Manager, **`collector`** pulls history for cellular-capable WAN edges (enrichment, cellular interface name, or model hint), **dedupes** buckets by `(entry_time, slot, active_sim)`, and pushes **`terra_cellular_*`** gauges to VictoriaMetrics. Per-device **`cellular_stats_cursor`** in Postgres tracks the last ingested bucket per dimension for incremental lookback.
- **Multitenant:** Same **`switch_tenant` + `VSessionId`** pattern as inventory before statistics POSTs per tenant group.
- **UI:** Device detail — interactive ECharts chart (RSRP/RSRQ toggle, zoom/brush). Devices table — Datatype RSSI sparkline (15-minute EIOLTE buckets; grid queries **24h** lookback, last 20 points) + **RSSI** quality dot (configurable dBm thresholds). APIs: `GET /api/v1/me/devices/{id}/cellular/history`, `GET /api/v1/me/devices/cellular/sparklines`.
- **Recipe:** [cellular-signal-thresholds](https://github.com/etychon/Catalyst-SD-WAN-API-User-Receipe/blob/main/docs/recipes/cellular-signal-thresholds.md).

Official reference: [Cisco Catalyst SD-WAN Manager — Device Realtime Monitoring](https://developer.cisco.com/docs/sdwan/device-realtime-monitoring/) (lists the paths above); [Get Device Interface](https://developer.cisco.com/docs/sdwan/20-16/get-device-interface/) (shows `af-type`, `ip-address`, `ipv6-address` patterns).

## Cisco Catalyst Center (future)

- **Connector-only** expansion: do not entangle Manager-specific DTOs into the entire UI.
- Expect different **identity keys** and **telemetry cadence**; plan for a **normalized device record** internally.

## Dashboard-local auth

- First-class **users, roles, sessions** (exact mechanism TBD: OIDC vs local-only vs hybrid).
- **Audit** dashboard actions that touch sensitive views (location history, exports).

## Third-party / infra

- **Local / demo runtime:** the runnable stack is delivered via **`docker compose up --build -d`** from the repo root (`docker-compose.yml`). The **default WebUI** is **HTTPS on port 4434** with a **self-signed** cert unless `docker/certs/` contains operator-supplied PEMs; any new dependency service (cache, broker, tile proxy) must be reflected in Compose when required for default operation.
- **Data tier (default Compose):** **`postgres`** holds relational projections (users, RBAC, inventory rows); **`victoriametrics`** holds long-retention metrics (see [`specs/telemetry-storage.md`](telemetry-storage.md)). **`core`** serves HTTP; **`collector`** runs periodic SD-WAN sync and metric push.
- **Grafana (optional):** `docker compose --profile grafana up -d` starts Grafana on **`TERRA_GRAFANA_PORT`** (default **3000**) with a provisioned Prometheus datasource pointing at VictoriaMetrics — useful for partner-built dashboards without blocking the main TERRA UI.
- **Syslog / alarms / audit streams:** treat Manager as the **source of truth** where APIs exist; normalize into Postgres **events** tables and/or VictoriaMetrics **counters** in the **`collector`** once concrete dataservice paths are pinned (see [`specs/sdwan-manager-api.md`](sdwan-manager-api.md) “Planned additions”). Distinguish **network events** from **dashboard RBAC audit** (Postgres-backed durable trail — not the admin ring buffer).
- Maps for GPS require a **tile provider policy** (privacy, cost, air-gapped customers) — decide before embedding vendor SDKs.

## Considered / discarded

- **Using end-user Manager accounts as dashboard SSO without scoping** — risky; likely needs hardening or mapping layer. Revisit explicitly if proposed.

Update this file when API versions or auth flows are pinned.
