# Integration requirements (TERRA)

## Cisco Catalyst SD-WAN Manager (initial)

- **Read-heavy** usage: inventory, device status, interfaces, performance/cellular telemetry where APIs expose it, IOx status where available, events/alerts feeds if exposed.
- **Auth:** service credentials stored in secure runtime configuration; rotate without code changes.
- **Scale:** multiple Manager endpoints must be representable without forking the UI.

## Cisco Catalyst Center (future)

- **Connector-only** expansion: do not entangle Manager-specific DTOs into the entire UI.
- Expect different **identity keys** and **telemetry cadence**; plan for a **normalized device record** internally.

## Dashboard-local auth

- First-class **users, roles, sessions** (exact mechanism TBD: OIDC vs local-only vs hybrid).
- **Audit** dashboard actions that touch sensitive views (location history, exports).

## Third-party / infra

- Maps for GPS require a **tile provider policy** (privacy, cost, air-gapped customers) — decide before embedding vendor SDKs.

## Considered / discarded

- **Using end-user Manager accounts as dashboard SSO without scoping** — risky; likely needs hardening or mapping layer. Revisit explicitly if proposed.

Update this file when API versions or auth flows are pinned.
