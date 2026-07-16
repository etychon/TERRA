# SD-WAN governance events (alarms, events, audit)

## Scope

- **Ingest (collector):** read-only `POST` queries to Cisco Catalyst SD-WAN Manager for **alarms**, **platform events**, and **audit logs** (see [`specs/sdwan-manager-api.md`](sdwan-manager-api.md)).
- **Serve (core):** paginated read APIs and UI from **Postgres** projections — no Manager HTTP on page load.
- **Out of scope v1:** syslog push/SIEM receiver, alarm mutations (clear/mark viewed), TERRA dashboard RBAC audit trail (see [`specs/logging-ui.md`](logging-ui.md)).

Recipe reference: [syslog-alarms-audit-rbac](https://github.com/etychon/Catalyst-SD-WAN-API-User-Recipe/blob/main/docs/recipes/syslog-alarms-audit-rbac.md).

## Streams

| `stream_kind` | Manager API | Audience |
|---------------|-------------|----------|
| `alarm` | `POST /dataservice/alarms` | NOC — active/cleared problems |
| `event` | `POST /dataservice/events` (fallback `GET /event` on 404) | Operations — platform events |
| `audit` | `POST /dataservice/auditlog` | Security — who changed what on Manager |

## Storage

- **`sdwan_governance_events`** — normalized rows; dedupe via `source_key` (unique per instance+tenant+stream).
- **`sdwan_governance_sync_state`** — per `(sdwan_instance_id, sdwan_tenant_id, stream_kind)` cursor (`last_entry_time_ms`).
- **Retention:** 30 days (purge in collector tick).
- **Device linkage:** resolve `synced_device_id` from inventory on `system_ip` / `vdevice_name` / `logdeviceid`.

## Ingestion

- **`collector`** runs `sync_governance_for_connected_managers` on `TERRA_GOVERNANCE_SYNC_INTERVAL_SECONDS` (default **300**), separate from inventory sync.
- First pull: `TERRA_GOVERNANCE_BACKFILL_HOURS` (default **24**); incremental pulls use cursor with 15-minute overlap.
- Multitenant: `switch_tenant` + `VSessionId` before queries per tenant (same as inventory/cellular).
- Logging: component **`sdwan_governance_sync`** (batch summary in admin Logs UI).

## Read API

Prefix: `/api/v1/me/governance`

| Route | Role |
|-------|------|
| `GET /events` | Paginated grid (server sort/filter/search) |
| `GET /events/facets` | Distinct severities, streams, clusters, tenants |
| `GET /events/{id}` | Detail row + `raw_json` |
| `GET /devices/{device_id}/events` | Device-scoped recent rows (alias on `api_me` router) |

Signed-in users see events for the full fabric (same visibility model as Devices grid).

## UI defaults

- **Events page (`/events`):** last **24h**, streams `alarm+event`, sort by time descending.
- **Device detail panel:** last **24h**, top **25** rows; link to Events page with `device_id` filter.
- **Severity / stream / active:** Material 3 pill chips (Cisco palette — no purple family).

## Considered / rejected

- **Browser polling Manager for events** — rejected; duplicates collector work and hits rate limits.
- **Storing only in VictoriaMetrics** — rejected for tabular audit/alarm rows; Postgres is the projection store.
