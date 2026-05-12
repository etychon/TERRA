# Application logs (admin)

## Scope

- **Admin-only** HTML at `/admin/logs` and JSON feed at `GET /api/v1/admin/logs` (requires `admin` role or superuser session).
- Logs are **in-memory** (ring buffer, default 3000 rows) and reset on process restart — suitable for operator troubleshooting, not compliance archival.
- **HTTP access lines** (component `http`) are captured for selected paths; high-frequency pollers (`/sync-sdwan-jobs/`, `/api/v1/admin/logs`, `/map-devices-telemetry`) are excluded to avoid buffer flooding.

## Feed order

- **API and UI** present the ring buffer **newest-first** (highest `seq` first). Incremental polling still uses `since_seq`; the server returns only rows with `seq > since_seq`, ordered newest-first within the batch.

## SD-WAN context in logs

- **Outbound Manager API** calls (httpx, component `sdwan_http`) append a short `detail` with **cluster display name** and **tenant** when a tenant-scoped client is in use. Deep `/dataservice/device/...` paths are summarized to avoid flooding the buffer.
- **Inbound HTTP** lines for SD-WAN-related routes (sync, live snapshot) set `detail` with **cluster** and **tenant** when the path identifies a manager instance (and tenant for live snapshot).

## SD-WAN periodic batch (`sdwan_sync_batch`)

- Emitted when **all connected managers** are synced (background loop) or when a user runs **Sync all** (`POST /api/v1/me/sync-sdwan-devices`).
- **Detail** conventions (plain text, grep-friendly): `run_id=<hex>` (correlates one batch tick), `managers=<n>`, `max_concurrent=<k>`, `batch_kind=periodic|user_bulk`, per-instance lines include `instance_id`, `cluster="..."`, `duration_ms`, `rows`, and optional `error=`.
- **Levels**: `INFO` batch start/end and per-manager success; `WARNING` per-manager sync returned an error string; `ERROR` worker crash / future failure.

## Search

Wildcards use Python `fnmatch` semantics (`*`, `?`) over **component + message + detail** (case-insensitive).

## SD-WAN sync progress

`POST /api/v1/me/sync-sdwan-devices/{id}/async` queues a background job; the Administration UI polls `GET /api/v1/me/sync-sdwan-jobs/{job_id}` for `phase`, `percent`, and `message`. Progress is shown **inline** under the manager row (not a modal). `POST /api/v1/me/sync-sdwan-jobs/{job_id}/cancel` requests cooperative cancellation (the worker checks between inventory / enrich / save steps). The legacy blocking `POST …/sync-sdwan-devices/{id}` remains for scripts.
