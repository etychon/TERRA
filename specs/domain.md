# Domain concepts (TERRA)

## Core nouns

- **Cluster:** an SD-WAN Manager domain the dashboard monitors (exact mapping to “tenant” / “provider” language TBD).
- **Device (cEdge):** routed appliance under management; primary telemetry subject.
- **Asset / Bus_ID:** customer-owned identifier for rolling stock or field asset correlation (display + search + reports).
- **Uplink profile:** especially **single cellular SIM** scenarios (IR1800 on buses); UI must not assume dual-transport diversity.
- **Release posture:** IOS-XE / image version compared to an operator policy (**out of date** / **unsupported** / **security exception**).

## User journeys (MVP bias)

1. **Morning check:** fleet health, red/yellow/green, version outliers, SIM-heavy sites.
2. **Incident:** drill into **cellular** stats, recent **alarms/events** (Events page + device detail panel), **alerts**, last known **GPS**.
3. **Compliance / audit:** who acknowledged what, export for operations review.

## Reporting

- **GPS / location history:** prefer **Cisco Manager** historical or streaming APIs where the deployment exposes them and licensing allows — authoritative for “what Manager saw.” For **OT map playback** and **~30-day** stretches when Manager retention is shorter or unavailable, store **normalized samples** in VictoriaMetrics (minutes-level cadence; see [`specs/telemetry-storage.md`](telemetry-storage.md)).
- **Events / alerts:** must be explainable in plain language for non-experts; syslog and alarm feeds remain **connector-owned** until paths are listed in [`specs/sdwan-manager-api.md`](sdwan-manager-api.md).

## Personas (monitoring product)

- **OT operators:** need **simple, customizable** workflows (inventory health, cellular, site topology) without full Manager navigation — supported by dashboard projections and future **saved OT views** (configuration TBD in Postgres).
- **IT / NOC operators:** need a **single pane** across **many clusters** and headroom toward **20k+ devices** — requires Postgres + **`collector`** scale-out story in [`specs/architecture.md`](architecture.md), not SQLite-only defaults.

## Device inventory (UI)

The **Devices** home grid uses Tabulator with **browser localStorage** persistence for column **order**, **width**, **visibility**, and **sort**. Operators add or remove fields via the **Columns** control. **Tenant** defaults visible next to **Manager** so multi-tenant Manager inventory is readable at a glance (rows without tenant scope show "—"). **Control-plane** nodes (vManage, vSmart, vBond, etc.) are **hidden by default** in the grid; a toolbar toggle shows them and remembers the choice per browser.

## Non-domain (explicit)

- Full SD-WAN **control-plane configuration** education is not a goal.

Update this file when customer language (e.g., Bus_ID rules) stabilizes.
