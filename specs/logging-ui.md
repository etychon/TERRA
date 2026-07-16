# Application logs (admin)

## Scope

- **Admin-only** HTML at `/admin/logs` and JSON feed at `GET /api/v1/admin/logs` (requires `admin` role or superuser session).
- Logs are **in-memory** (ring buffer, default 3000 rows) and reset on process restart — suitable for operator troubleshooting, **not** compliance archival or security forensics.
- **Durable audit** (who changed RBAC, who exported sensitive reports) belongs in **PostgreSQL** (or an external SIEM) once productized; do not treat this ring buffer as the audit system of record — see [`specs/architecture.md`](architecture.md) secrets and service boundaries.
- **HTTP access lines** (component `http`) are captured for selected paths; high-frequency pollers (`/sync-sdwan-jobs/`, `/api/v1/admin/logs`, `/api/v1/admin/collector-status`, `/map-devices-telemetry`) are excluded to avoid buffer flooding.

## Feed order

- **API and UI** present the merged feed **newest-first**. Incremental polling uses two cursors: `since` (in-memory ring `seq`) and `since_db` (persisted `app_log_events.id`). Persisted collector rows use synthetic `seq = 1_000_000_000 + id` for stable ordering in the UI.

## Collector visibility

- **`collector`** (Compose) writes a Postgres singleton **`collector_status`** (heartbeat + last periodic batch summary) and persists **`sdwan_sync_batch`** rows with `batch_kind=periodic` into **`app_log_events`** so **`core`** can show them on `/admin/logs`.
- **`GET /api/v1/admin/collector-status`** returns `state` (`alive` | `stale` | `never`): **stale** when `now - last_heartbeat_at > 2 × interval_seconds`.
- Logs page shows a **Background collector** status strip (heartbeat, interval, last batch ok/warn/err/rows, cellular bucket counts) and a **Show batch logs** shortcut (`*sdwan_sync_batch*`).

## SD-WAN context in logs

- **Outbound Manager API** calls (httpx, component `sdwan_http`) append a short `detail` with **cluster display name** and **tenant** when a tenant-scoped client is in use. Deep `/dataservice/device/...` paths are summarized to avoid flooding the buffer.
- **Inbound HTTP** lines for SD-WAN-related routes (sync, live snapshot) set `detail` with **cluster** and **tenant** when the path identifies a manager instance (and tenant for live snapshot).

## SD-WAN periodic batch (`sdwan_sync_batch`)

- Emitted when **all connected managers** are synced (**`collector`** background loop in default Compose) or when a user runs **Sync all** (`POST /api/v1/me/sync-sdwan-devices`) on **`core`**.
- **Detail** conventions (plain text, grep-friendly): `run_id=<hex>` (correlates one batch tick), `managers=<n>`, `max_concurrent=<k>`, `batch_kind=periodic|user_bulk`, per-instance lines include `instance_id`, `cluster="..."`, `duration_ms`, `rows`, optional `error=`, and when cellular ran: `cellular_buckets=`, `cellular_errors=`, `cellular_fetched=`.
- **Levels**: `INFO` batch start/end and per-manager success; `WARNING` per-manager sync returned an error string; `ERROR` worker crash / future failure.

## Search

Wildcards use Python `fnmatch` semantics (`*`, `?`) over **component + message + detail** (case-insensitive).

## SD-WAN sync progress

`POST /api/v1/me/sync-sdwan-devices/{id}/async` queues a background job; the Administration UI polls `GET /api/v1/me/sync-sdwan-jobs/{job_id}` for `phase`, `percent`, and `message`. Progress is shown **inline** under the manager row (not a modal). Inventory sync **commits the WAN edge list first** (phase **saving** with message like “WAN edge list saved”) then continues **enriching** per-device dataservice merges so operators see edges before slow enrich finishes. While the job is **not** in a terminal state, the UI persists **`job_id`** in **`sessionStorage`** per manager row so navigating away and back **resumes** polling and shows in-progress status until **done / failed / cancelled** (see `src/terra/static/js/terra-sdwan-admin.js`). On **bfcache** restores (browser Back/Forward), `pageshow` with `persisted` re-runs resume because `DOMContentLoaded` does not fire again; duplicate polling for the same `job_id` is skipped via a row attribute. `POST /api/v1/me/sync-sdwan-jobs/{job_id}/cancel` requests cooperative cancellation (the worker checks between inventory / enrich / save steps). The legacy blocking `POST …/sync-sdwan-devices/{id}` remains for scripts.
