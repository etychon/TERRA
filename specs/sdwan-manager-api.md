# Cisco Catalyst SD-WAN Manager — API surface (TERRA)

Opinionated **map of what TERRA calls**, in what order, and where it lives in code. This is not a full DevNet reference: use Cisco’s docs for field schemas and release notes; use this file for **repo decisions**, **impact analysis** when Manager changes APIs, and **entry points**.

**Deeper product narrative** (multitenant semantics, interface/cellular modeling, credential-scope heuristics): [`specs/integrations.md`](integrations.md).

**Connector / future split**: [`specs/architecture.md`](architecture.md).

## Complete HTTP inventory (cookbook)

All URLs are resolved as **`{manager_base_url}{path}`** with no extra path prefix on the stored base URL. Per-device dataservice reads add **`?deviceId=<candidate>`** (candidates from inventory: `system-ip`, `uuid`, etc. — see [`src/terra/sdwan_device_live.py`](../src/terra/sdwan_device_live.py) `vmanage_device_id_candidates`).

| Method | Path | Role in TERRA | Primary code |
|--------|------|----------------|----------------|
| `POST` | `/j_security_check` | Session auth (form `j_username` / `j_password`); establishes cookie session. | [`sdwan_http.py`](../src/terra/sdwan_http.py) `_session_login`; [`sdwan_client.py`](../src/terra/sdwan_client.py) `probe_session` |
| `GET` | `/dataservice/client/token` | After session login: read XSRF (`X-XSRF-TOKEN` header or JSON `token` / `xsrf_token` / `xsrfToken`). | [`sdwan_http.py`](../src/terra/sdwan_http.py); [`sdwan_client.py`](../src/terra/sdwan_client.py) `probe_session` |
| `GET` | `/dataservice/client/server` | **(a)** JWT connectivity probe + version string; **(b)** after session probe; **(c)** `read_manager_version` during inventory; **(d)** JWT multitenant: refresh `X-XSRF-TOKEN` from `data.CSRFToken` / `data[0].CSRFToken` before tenant switch; **(e)** credential-scope checks that reuse CSRF refresh. | [`sdwan_client.py`](../src/terra/sdwan_client.py) `probe_jwt`, `probe_session`, `read_manager_version`; [`sdwan_http.py`](../src/terra/sdwan_http.py) `refresh_sdwan_dataservice_csrf_header`; [`sdwan_sync.py`](../src/terra/sdwan_sync.py) (version after sync); [`sdwan_credential_scope.py`](../src/terra/sdwan_credential_scope.py) |
| `GET` | `/dataservice/tenant` | Multitenant discovery; empty or 400/403/404/405 ⇒ single-tenant mode. | [`sdwan_sync.py`](../src/terra/sdwan_sync.py) `fetch_tenant_list` |
| `POST` | `/dataservice/tenant/{tenantId}/switch` | Switch Manager session to tenant context before per-tenant inventory. | [`sdwan_sync.py`](../src/terra/sdwan_sync.py) `post_tenant_switch` |
| `GET` | `/dataservice/device` | Primary full-device inventory (normalized to `SyncedDevice`). | [`sdwan_sync.py`](../src/terra/sdwan_sync.py) `fetch_device_inventory_rows` |
| `GET` | `/dataservice/system/device/vedges` | Fallback inventory when primary device list is empty (lab/CVD builds). Constant `_FALLBACK_DEVICE_PATHS[0]`. | [`sdwan_sync.py`](../src/terra/sdwan_sync.py) |
| `GET` | `/dataservice/system/device/controllers` | Fallback inventory (same as above). Constant `_FALLBACK_DEVICE_PATHS[1]`. | [`sdwan_sync.py`](../src/terra/sdwan_sync.py) |
| `GET` | `/dataservice/device/interface` | Live device poll + optional sync enrichment → interface table / `raw_json`. | [`sdwan_device_live.py`](../src/terra/sdwan_device_live.py) `_INTERFACE_PATHS` |
| `GET` | `/dataservice/device/interface/synced` | Same as interface path (synced variant). | [`sdwan_device_live.py`](../src/terra/sdwan_device_live.py) `_INTERFACE_PATHS` |
| `GET` | `/dataservice/device/cellular/modem` | Live + optional sync enrichment; cellular snapshots under enrichment keys. | [`sdwan_device_live.py`](../src/terra/sdwan_device_live.py) `_CELLULAR_PATHS` |
| `GET` | `/dataservice/device/cellular/network` | Same. | [`sdwan_device_live.py`](../src/terra/sdwan_device_live.py) |
| `GET` | `/dataservice/device/cellular/radio` | Same. | [`sdwan_device_live.py`](../src/terra/sdwan_device_live.py) |
| `GET` | `/dataservice/device/cellular/status` | Same. | [`sdwan_device_live.py`](../src/terra/sdwan_device_live.py) |
| `GET` | `/dataservice/device/cellular/sessions` | Same. | [`sdwan_device_live.py`](../src/terra/sdwan_device_live.py) |
| `GET` | `/dataservice/device/cellular/profiles` | Same. | [`sdwan_device_live.py`](../src/terra/sdwan_device_live.py) |
| `GET` | `/dataservice/device/control/waninterface` | Live + optional sync enrichment; WAN hint (`_EXTRA_PATHS`). | [`sdwan_device_live.py`](../src/terra/sdwan_device_live.py) |

**Count:** 17 distinct path templates (plus dynamic `{tenantId}` on tenant switch). Anything not listed here is **out of scope** for current TERRA code unless this table is updated.

**Official references (not exhaustive):** [Tenant](https://developer.cisco.com/docs/sdwan/20-16/tenant/); [Device realtime monitoring](https://developer.cisco.com/docs/sdwan/device-realtime-monitoring/); [Get device interface](https://developer.cisco.com/docs/sdwan/20-16/get-device-interface/).

## Keeping this file current

When adding or removing Manager HTTP usage:

1. **Update this table** in the same PR as the code (per [`AGENTS.md`](../AGENTS.md) spec discipline).
2. **Update** [`specs/integrations.md`](integrations.md) if multitenant behavior, credential scope, or UI-facing semantics change.
3. **Verify the repo list** (paths only; tests may mock the same URLs):

   ```bash
   rg '/dataservice/|j_security_check' src/terra --glob '*.py'
   ```

   Constants that centralize path strings: `_FALLBACK_DEVICE_PATHS` in [`sdwan_sync.py`](../src/terra/sdwan_sync.py); `_INTERFACE_PATHS`, `_CELLULAR_PATHS`, `_EXTRA_PATHS` in [`sdwan_device_live.py`](../src/terra/sdwan_device_live.py).

## Scope and non-goals

- **In scope:** read-only **inventory sync**, **per-device enrichment**, **live dataservice reads** for the dashboard, **Verify/probe** flows, and **admin operator logs** tied to Manager HTTP.
- **Out of scope here:** OpenAPI-style field catalogs per endpoint; **Cisco Catalyst Center** (future connector only — not documented in this file).
- **Still Manager’s job:** full configuration, policy push, and golden-template workflows unless product direction explicitly expands TERRA.

## Auth surfaces (HTTP)

| Mode | Steps (summary) | Code |
|------|-----------------|------|
| **JWT** | `Authorization: Bearer …` on a short-lived `httpx.Client`; for multitenant inventory, **`X-XSRF-TOKEN`** is refreshed from `GET /dataservice/client/server` before `POST …/tenant/…/switch`. | [`sdwan_http.py`](../src/terra/sdwan_http.py), [`sdwan_client.py`](../src/terra/sdwan_client.py) |
| **Session** | `POST /j_security_check` → `GET /dataservice/client/token` → JSON calls with cookies + `X-XSRF-TOKEN`. | Same modules |

**TLS:** per-instance `verify_tls` is honored on the client.

**Timeouts:** inventory-phase `GET`/`POST` use **`TERRA_SDWAN_SYNC_INVENTORY_TIMEOUT_SECONDS`** where implemented; see [`config.py`](../src/terra/config.py). Per-device enrich and live polls: `TERRA_SDWAN_SYNC_ENRICH_*`, `TERRA_DEVICE_LIVE_HTTP_TIMEOUT_SECONDS`.

## Inventory sync ladder

Implemented in [`sdwan_sync.py`](../src/terra/sdwan_sync.py). Endpoint order and fallbacks match the **cookbook table** above (`/tenant` → optional `/tenant/{id}/switch` → `/device` → system device fallbacks).

**Operational quirks:** do not send **`VSessionId`** on `/dataservice/device` after tenant switch on some builds; rely on switch + cookies. Details: [`specs/integrations.md`](integrations.md).

## Sync enrichment and live dataservice reads

[`sdwan_device_live.py`](../src/terra/sdwan_device_live.py) implements all **`GET /dataservice/device/...`** rows in the cookbook (interface, cellular, WAN). **Cellular** responses are stored under enrichment keys in `raw_json` (not fully merged into interface rows today — see integrations).

## Background batch and async jobs

- **Periodic + “sync all” managers:** bounded parallel workers, **`sdwan_sync_batch`** logs with `run_id` — [`specs/logging-ui.md`](logging-ui.md), [`sdwan_sync.py`](../src/terra/sdwan_sync.py).
- **Per-manager async job (Administration UI):** **`sdwan_sync_job`** — [`sdwan_sync_job_runner.py`](../src/terra/sdwan_sync_job_runner.py) (orchestrates sync; **no extra dataservice paths** beyond modules above).
- **Outbound Manager HTTP (summary lines):** component **`sdwan_http`** — [`specs/logging-ui.md`](logging-ui.md); path filtering in [`sdwan_operator_log.py`](../src/terra/sdwan_operator_log.py).

## Agent checklist (new dataservice usage)

1. **Trust boundary:** keep assumptions behind the connector pattern; extend **this table** + `integrations.md` when behavior changes.
2. **Auth:** JWT vs session — CSRF and cookies where required; multitenant switch order.
3. **Timeouts:** pick inventory vs enrich vs live timeout deliberately; do not rely only on the long-lived client default.
4. **Logging:** avoid flooding the admin ring buffer (`sdwan_operator_log` summarizes deep device paths).
5. **SQLite / concurrency:** parallel Manager syncs increase lock pressure — see [`specs/architecture.md`](architecture.md) and `TERRA_SDWAN_BATCH_MAX_CONCURRENT_MANAGERS`.

When implementation lands, update **this file** and **`specs/integrations.md`** in the same PR if operator-visible or multitenant semantics change.
