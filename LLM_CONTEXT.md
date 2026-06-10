# LLM_CONTEXT.md

> **Audience:** coding agents and LLM-assisted workflows. This file is dense and intentionally overlaps only minimally with `README.md` and `specs/`. Humans should prefer `README.md` + `specs/`.

> **Mandatory default run:** from repo root, **`docker compose up --build -d`** — then **`https://localhost:4434`** (TLS via `web` → **`core`**; override host port with `TERRA_HTTPS_PORT` in `.env`). Default TLS is **self-signed** unless `docker/certs/server.crt` and `server.key` are supplied. Do not document or implement a different “official” bring-up path without updating this file, `README.md`, `AGENTS.md`, and `specs/architecture.md` in the same change.

## Codename and positioning

- **Product codename:** TERRA — *Dashboard Telemetry for Edge and Remote Routable Assets*.
- **Primary user:** operators with **limited SD-WAN depth** (intern-friendly). They need **real-time situational awareness**, not another full Manager workflow.
- **Primary mode:** **monitor** and **report**. **Configuration, policy deployment, and golden-template Manager tasks** remain **Cisco Catalyst SD-WAN Manager** responsibilities unless product direction explicitly expands scope later.

## Problem framing

- Cisco Catalyst SD-WAN WebUI is powerful but **navigation-heavy** for recurring operational questions across fleets (including **mobile / IR1800-on-bus** style deployments with **single SIM** uplinks).
- TERRA aggregates **multiple SD-WAN clusters / Manager tenants** (exact tenancy model TBD in code) into **one dashboard** with first-class **dashboard-local authN/authZ** and user lifecycle.

## Telemetry and UX expectations (v1 direction)

Surface **compact** device cards or equivalents, not Manager clone screens:

- **Identity / inventory:** hostname, site, model, role, Bus_ID (or equivalent asset tag), SIM path context where relevant.
- **Software:** IOS-XE / image track on cEdge; **highlight EOL or policy-violating / out-of-date** versions vs an operator-defined policy matrix (details in `specs/domain.md`).
- **Health:** CPU, memory, disk, process or platform pressure signals available from APIs.
- **Transport:** WAN interface utilization; **cellular** signal/quality and detailed drill-down view; single-uplink scenarios must degrade gracefully (no false “all green” when the only path is marginal).
- **Edge compute:** IOx application status when exposed via APIs/device model.
- **~30-day GPS / metrics retention:** default Compose includes **VictoriaMetrics** (see `specs/telemetry-storage.md`); prefer Cisco Manager historical APIs when they cover the window.
- **Reporting / audit:** scheduled or on-demand exports, **events**, **alerts**, audit trails of dashboard actions (not Manager audit unless explicitly integrated).

## UI stack, design system, and AI ergonomics

**Single source of truth:** `specs/design-system.md` is the product-level spec. **`frontend/src/tokens/`** + **`frontend/src/styles/globals.css`** are the SSOT for the **TypeScript / Tailwind** dashboard. **`src/terra/static/css/terra-auth.css`** (+ page-specific CSS such as **`terra-devices.css`**) are the SSOT for **server-rendered** Jinja UI; keep tokens, shape scale, and Cisco hue rules aligned across both.

### Visual language

- **Material Design 3:** follow M3 for **typography** (Roboto / Roboto Mono **self-hosted** under `src/terra/static/fonts/`, loaded via `terra-fonts.css` from `base.html` — no Google Fonts at runtime), **shape** (`--md-sys-shape-corner-*`, pill buttons, rounded cards/surfaces), **elevation / surface roles** (surface containers for chrome, headers, and data tables), and **button variants** (filled, outlined, filled tonal). Canonical reference: [Material Design 3](https://m3.material.io/). Product rules still live in `specs/design-system.md`.
- **Cisco brand:** apply **Cisco’s official color palette** and **logo** per Brand Center (no unofficial logo marks in production). Token **names** are semantic; **values** in `primitives.ts` must be reconciled with Brand Center swatches before GA.
- **Banned hues:** **do not use purple or indigo** (includes Tailwind `purple-*`, `indigo-*`, `violet-*`, `fuchsia-*`) unless an approved exception is recorded in `specs/design-system.md`. Same rule in **CSS and TS** outside sanctioned primitive definitions.
- **Nature palettes:** secondary ramps may be **generated as unique ramps from nature references** (e.g. tide, basalt, lichen) while staying inside approved hue families and **contrast-first** constraints (WCAG-minded pairing for text vs surface).
- **Dark theme:** required. **Theme = CSS custom properties** on `:root` and `.dark` in `globals.css`; **no JavaScript requirement** for switching theme colors (browser owns variables; root `class="dark"` toggles dark set). **Server-rendered** pages use the same HSL-variable pattern in `src/terra/static/css/terra-auth.css`.
- **Motion:** allow **slow pulsating color gradients** on decorative layers only; always provide **`prefers-reduced-motion`** safe reduction (static or nearly static).
- **Density:** UI is **dense**; use the **8px spacing scale** (`8, 16, 24, 32, 40, 48, …`) as the primary rhythm, with a **4px sub-grid** only for micro alignment.

### Token architecture (TypeScript)

Mirror abstraction in **three files only** at this layer:

1. **`frontend/src/tokens/primitives.ts`** — raw values only (spacing integers, hex/HSL components, motion durations). **No semantic names** like “danger” here.
2. **`frontend/src/tokens/semantic.ts`** — imports `primitives`; assigns **purpose** (`surface.canvas`, `text.muted`, `risk.critical`, `brand.primary`, …).
3. **`frontend/src/tokens/components.ts`** — imports **both**; defines **component recipes** (e.g. `dataTable.rowHeight`, `shell.headerPadding`).

**Tailwind + shadcn/ui pattern:** Tailwind theme maps to **`hsl(var(--…))`** (or equivalent) so agents learn **one semantic system** that works in light/dark. Extend shadcn components using the same variables—avoid teaching “separate light and dark color systems” in JSX.

### Automated guardrails (blocking)

- **ESLint** custom rules under `frontend/eslint/` catch **forbidden Tailwind hues** and **raw hex literals** outside `primitives.ts` (see `frontend/eslint.config.mjs`).
- **`npm run lint`** runs ESLint **and** `frontend/scripts/verify-design-contract.mjs` (CSS / cross-cutting checks).
- **Pre-commit** runs frontend lint when files under `frontend/` change.

Agents must run **`cd frontend && npm run lint`** (or rely on pre-commit / CI) before treating UI work as complete.

## Integrations

- **Now:** Cisco Catalyst **SD-WAN Manager REST** (and related control/data APIs as productized by Cisco for telemetry/inventory). Treat rate limits, pagination, and **multi-tenant** Manager instances as first-class design inputs.
- **Later:** **Cisco Catalyst Center** connector behind the same **abstract “campus / WAN fabric source”** boundary so UI and domain models are not Manager-shaped at the core.

## Delivery: Docker Compose and portability (mandatory)

The **delivered runnable application** (services, backing stores, and the app’s default “bring up the stack” path) **must** be orchestrated with **Docker Compose** so operators and developers share one obvious entrypoint.

### Canonical bootstrap (enforced)

From the **repository root**, the **primary** way to run the stack is a **single command**:

```bash
docker compose up --build -d
```

After images build, open **`https://localhost:4434`** (or `TERRA_HTTPS_PORT` from `.env`). **TLS:** self-signed by default (generated under `docker/certs/` on first run); replace with **externally issued** PEMs (`server.crt`, `server.key`) as documented in `docker/certs/README.md`. **Health:** `GET /health` on the HTTPS edge (Compose healthchecks use `curl -k` against the `web` service).

- **Do not** position `pip install`, `venv`, or `terra-serve` as the default operator runbook in docs, README opening, or agent guidance—those are **contributor / CI** paths unless explicitly labeled “local Python development.”
- **New runnable services or daemons** (APIs, workers, databases, edge proxies) **must** be wired into `docker-compose.yml` (or an included Compose file) in the **same PR** as the code that introduces them, with **healthchecks** where applicable and **documented ports / env** in `README.md` + this file.
- **CI** must validate Compose configuration (e.g. `docker compose config`) so broken Compose cannot merge silently.

The legacy standalone binary `docker-compose` (hyphen) may exist on older hosts; the documented command is **`docker compose`** (Docker CLI plugin).

**CPU architectures:** images and Compose definitions **must** support **both**:

- **x86-64** (`amd64`) — typical Linux servers and Intel/AMD desktops and laptops.
- **ARM64** (`arm64`) — **Apple Silicon** (M-series Macs) and common ARM cloud instances.

Use **multi-arch base images** and/or explicit `platform` policies only where necessary; prefer builds that **do not** force a single architecture in a way that breaks the other family.

**Host operating systems** for running Compose **must** be supported:

- **macOS** (Intel and Apple Silicon).
- **Linux** (common distributions used in dev and small on-prem footprints).
- **Windows** (via **Docker Desktop** / WSL2-backed engine as the supported model; document this expectation).

**Agent implementation hints:** avoid host-specific bind mounts and path assumptions that break Windows or macOS file sharing; document any **privileged** ports, **localhost** vs `host.docker.internal` differences, and line-ending or volume-permission caveats in `README.md` / `AGENTS.md` when adding services. CI **must** validate Compose **config** (`docker compose config` in `.github/workflows/ci.yml`); add **arm64** image build coverage when runners are available.

## Explicit non-goals (current)

- Replacing Manager for **full configuration** or advanced troubleshooting workflows.
- Teaching customers **inter-WAN architecture** concepts unless needed for a specific widget.
- Storing long-lived **secrets** in-repo or in notebooks.

## Compliance and safety defaults for agents

- No hardcoded credentials, tokens, or private keys (`AGENTS.md`, org policy).
- Minimize PII in fixtures; prefer synthetic IDs for Bus_ID / GPS in `data/` samples.
- When calling external systems in tests, use **recorded fixtures** or **mock servers**; default CI must stay **offline-deterministic**.

## Repository mechanical map

- **`specs/`:** keep short; update with behavioral PRs. **`specs/design-system.md`** owns UI SSOT rules. **`specs/sdwan-manager-api.md`** maps which **Cisco Catalyst SD-WAN Manager** dataservice paths TERRA uses (auth, inventory, live reads); deeper multitenant/interface narrative lives in **`specs/integrations.md`**.
- **`frontend/`:** dashboard UI, Tailwind + shadcn-oriented setup, **tokens** (`src/tokens/`), **globals.css**, ESLint design guardrails.
- **`.cursor/skills/terra-ui-design-system/`:** Cursor **SKILL** for agents implementing UI (loads detailed guardrails + file paths).
- **`src/terra_sdwan/`:** SD-WAN Manager HTTP client, inventory sync, live dataservice reads — shared by **`core`** and **`collector`**.
- **`src/terra/`:** FastAPI **`core`** app (auth, RBAC, APIs, Jinja UI); **must** remain reachable via the Compose **`core`** service and `/health`.
- **`docker-compose.yml` + `Dockerfile` + `docker/web/`:** mandatory operator entrypoint; **HTTPS on host port 4434** by default (`web` nginx terminates TLS; **`core`** is internal HTTP on :8000). Default Compose adds **`postgres`**, **`victoriametrics`**, and **`collector`** (see `specs/architecture.md`). Keep defaults dev-safe and document production overrides (`TERRA_SECRET_KEY`, external certs in `docker/certs/`, etc.).
- **`frontend/`:** dashboard design-system package (tokens, lint); when a **runnable** SPA or static server is added, it **must** ship in Compose alongside **`core`** (same single `docker compose up` story).
- **`tests/`:** unit, integration, smoke; smoke proves “wires connected” (Compose files present; app boots; **`GET /health`** when the API test client is used).
- **`notebooks/`:** exploratory only; not production paths.
- **`data/`:** fixtures and anonymized samples only.
- **`models/`:** optional ML artifacts or JSON schema bundles — not required for MVP dashboard.

## Open questions (do not guess into code without spec update)

- Exact **Manager API** surface versions per supported release train.
- **Multi-cluster** auth model (one dashboard user spanning N Managers vs federation).
- **IOS-XE currency rules** (Cisco PSIRT vs field policy vs static allowlist).

When resolving any open question, **edit the relevant `specs/*.md` in the same PR** as the code that encodes the decision.
