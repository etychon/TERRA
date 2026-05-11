# TERRA

**T**elemetry for **E**dge and **R**emote **R**outable **A**ssets — a Cisco Catalyst SD-WAN–oriented operations dashboard for non-expert users.

## Run everything (Docker Compose)

From the **repository root** (Docker Desktop or Docker Engine with the Compose v2 plugin):

```bash
docker compose up --build -d
```

Older Docker installs may use the same flags with the standalone binary: `docker-compose up --build -d`.

Then open **`https://localhost:4434`** (self-signed certificate on first run; your browser will warn until you accept the risk or replace certs — see `docker/certs/README.md`). **Liveness:** `GET /health` (e.g. `curl -sk https://localhost:4434/health`).

### Debug diagnostics (Compose overlay, lab only)

For **local inspection** (DB URL redacted, table row counts, SD-WAN manager rows without credentials, device samples), use the debug Compose overlay. It enables `TERRA_DEBUG_EXPOSE_INTERNALS` and publishes the **API** on the host at **`TERRA_DEBUG_API_PORT`** (default **`18434`** — avoids host **8000**). By default **`TERRA_DEBUG_HOST_BIND`** is **`0.0.0.0`**, so the debug API is reachable on the LAN as **`http://<host-ip>:18434`** (for example `http://192.168.2.3:18434`). Set **`TERRA_DEBUG_HOST_BIND=127.0.0.1`** to listen on loopback only. Container port remains **8000** inside the Docker network. Endpoints are gated by **`TERRA_DEBUG_TOKEN`** (`X-Terra-Debug-Token` header or `?debug_token=`).

**Recommended (script sets port + token + default LAN bind):**

```bash
./scripts/launch-terra-debug.sh
curl -sS -H "X-Terra-Debug-Token: $TERRA_DEBUG_TOKEN" "http://127.0.0.1:${TERRA_DEBUG_API_PORT:-18434}/debug/summary"
# Same host on LAN (example IP):
curl -sS -H "X-Terra-Debug-Token: $TERRA_DEBUG_TOKEN" "http://192.168.2.3:${TERRA_DEBUG_API_PORT:-18434}/debug/summary"
```

The script also writes the same token to **`.run/terra-debug.token`** (mode `600`, gitignored) so tools can read it without `docker exec`.

**Manual:**

```bash
export TERRA_DEBUG_TOKEN="$(openssl rand -hex 16)"
export TERRA_DEBUG_API_PORT=18434
export TERRA_DEBUG_HOST_BIND=0.0.0.0
docker compose -f docker-compose.yml -f docker-compose.debug.yml up --build -d
curl -sS -H "X-Terra-Debug-Token: $TERRA_DEBUG_TOKEN" "http://127.0.0.1:${TERRA_DEBUG_API_PORT}/debug/summary"
```

**Lab only:** LAN binding exposes `/debug/*` to every device that can route to that port. Protection is the shared token plus your network boundary — do not use this overlay on production-facing hosts.

### Default admin credentials (first sign-in)

Unless you set overrides in `.env` **before the first database seed**, the bootstrap superuser is:

| | Value |
|---|--------|
| **Sign-in URL** | `https://localhost:4434/auth/login` |
| **User admin (after sign-in, admin role)** | `https://localhost:4434/admin/users` |
| **Email** | `admin@terra.local` |
| **Password** | `ChangeMe!Admin-1st-login` |

These match `TERRA_ADMIN_EMAIL` and `TERRA_ADMIN_PASSWORD` in `docker-compose.yml` / `.env.example`. Change them for any shared or non-local environment; the seed step only creates this user when the database has no matching admin yet.

- **TLS material:** `docker/certs/` is bind-mounted into the `web` container. If `server.crt` and `server.key` are absent, a **dev self-signed** pair is generated on first start. For production or corporate PKI, place your own PEM files there (same names) before starting Compose.
- **Stop:** `docker compose down` (add `-v` to remove the SQLite volume).
- **Follow logs:** `docker compose logs -f web` and/or `docker compose logs -f api`.
- **Different HTTPS host port:** set `TERRA_HTTPS_PORT` in `.env` (default **4434** avoids common conflicts with **8000**).

The dashboard **React SPA** is still evolving under `frontend/` (tokens and lint today). Compose runs the **full backend** (auth, RBAC, Jinja UI) and persists SQLite under a Docker volume. **Contributors** may still use local `pip` / `npm`; **operators and agents** default to Compose — see `LLM_CONTEXT.md` and `AGENTS.md`.

## Goals (summary)

- Monitor **multiple** SD-WAN environments from one place using **Cisco Catalyst SD-WAN Manager APIs** (configuration stays in Manager).
- Present a **compact, high-level** view of cEdge health: IOS-XE version (with **out-of-date** highlighting), CPU, memory, link usage, cellular quality, disk, IOx app status, GPS history, alerts/events, and related reporting.
- First-class **authentication and user management** in the dashboard (not delegated to SD-WAN WebUI for day-to-day monitoring).
- Design for a future **Cisco Catalyst Center** connector without locking the core model to Manager-only assumptions.

## Repository layout

| Path | Purpose |
|------|---------|
| `src/terra/` | FastAPI backend: session auth, RBAC, user admin API, Cisco-themed auth pages. |
| `tests/` | Unit, integration, and smoke tests. |
| `data/` | Local datasets, fixtures, and cached samples (no secrets). |
| `notebooks/` | Exploratory analysis and prototyping. |
| `models/` | Serialized models or schema artifacts if/when needed. |
| `docs/` | Human-facing documentation beyond the README. |
| `specs/` | Short, authoritative product and engineering specs. |
| `package.json` (root) | Proxies `npm run lint` / `npm run typecheck` to `frontend/` so you can run them from the repo root. |
| `docker-compose.yml`, `docker-compose.debug.yml`, `Dockerfile` | **Canonical** full-stack bootstrap; optional **debug** overlay for `/debug/*` (default bind **0.0.0.0:18434** on the host). |
| `scripts/launch-terra-debug.sh` | One-shot **debug Compose** (API on **18434**, not **8000**; LAN-reachable unless `TERRA_DEBUG_HOST_BIND=127.0.0.1`; writes `.run/terra-debug.token`). |
| `docker/web/` | **HTTPS edge** (nginx TLS on **4434** → `api`). |
| `docker/certs/` | TLS PEMs (`server.crt`, `server.key`); optional bind mount for **externally issued** certs. |
| `frontend/` | Dashboard UI: Tailwind + shadcn-style CSS variables, token layers, ESLint design guardrails. |
| `.cursor/skills/terra-ui-design-system/` | Cursor **SKILL** for UI work (loads design-system rules). |
| `LLM_CONTEXT.md` | **LLM-oriented** project context (not a substitute for `specs/`). |

## Prerequisites

- **Docker** with the **Compose v2** plugin (`docker compose`), for the default run path above.
- Python **3.11+** (local tooling, tests, `pip install -e ".[dev]"`).
- **Node.js 18+** and **npm** (dashboard design-system package; **20 LTS** recommended to match `frontend/.nvmrc`).

## Install (development tooling)

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### Optional: Git hooks (Ruff)

```bash
pip install pre-commit
pre-commit install
```

On a brand-new clone, `pre-commit` runs against tracked files; after the first `git add` / commit, hooks behave as usual.

## Run tests

```bash
pytest
```

Smoke checks live under `tests/` and validate that the repository and expected entry-point files remain coherent as the tree evolves.

## Lint and type check

```bash
ruff check src/terra tests
mypy src/terra tests
```

## Frontend (design system + guardrails)

This repo uses **npm workspaces** (`frontend/` is a workspace). From the **repo root**:

```bash
npm install
npm run lint
```

(`npm run lint` runs `tsc`, ESLint, and the design contract script on the workspace package. Use `npm run typecheck` only if you want TypeScript alone.)

Authoritative UI rules: `specs/design-system.md`. TypeScript tokens live in `frontend/src/tokens/` (`primitives.ts` → `semantic.ts` → `components.ts`); theme colors are **CSS custom properties** in `frontend/src/styles/globals.css` (`:root` / `.dark`).

## Backend (authentication and RBAC)

The FastAPI app lives under `src/terra`. **Prefer running via Docker Compose** (above). For **local Python development** after `pip install -e ".[dev]"`:

```bash
terra-serve
# or: uvicorn terra.main:app --reload --host 127.0.0.1 --port 8000
```

- **Web UI:** `/auth/login` (Cisco-aligned dark theme via `src/terra/static/css/terra-auth.css`), `/` when signed in.
- **JSON API:** `/api/v1/auth/*` (login, logout, forgot/reset, verify, `me`) and `/api/v1/admin/users*` for admin CRUD, roles, and bulk updates (public **register** is disabled; admins create users).
- **Admin Web UI:** signed-in users with the **admin** role can open **`/admin/users`** to add/remove users, reset passwords, and assign roles (same capabilities as the admin JSON API).
- **Bootstrap admin:** see **Default admin credentials** above when using Compose; for custom seeds set `TERRA_ADMIN_EMAIL` / `TERRA_ADMIN_PASSWORD` before first boot.
- **Configuration:** set `TERRA_SECRET_KEY` (≥32 characters), `TERRA_DATABASE_URL` (default `sqlite:///./data/terra.db`). With `TERRA_MAIL_MODE=log` (default), password-reset and email-verification tokens are written to logs instead of SMTP.
- **Plain HTTP local dev:** keep `TERRA_SESSION_COOKIE_SECURE=false` (default when not using Compose) so session cookies work over `http://127.0.0.1:8000`; Compose sets it to **true** behind the HTTPS edge.

## Agent and automation entry points

- **`AGENTS.md`** — concise guidance for coding agents (workflows, PR expectations, spec discipline).
- **`LLM_CONTEXT.md`** — dense machine-oriented context for models assisting on this repo.
- **`.cursor/skills/terra-ui-design-system/SKILL.md`** — agent skill for dashboard UI (Cisco-aligned tokens, Tailwind + shadcn variable pattern, ESLint/pre-commit guardrails).
- **Slash `/commit`** — verifies tests/lint, summarizes changes since `HEAD`, and guides a public-safe `git commit` (see `.cursor/commands/commit.md`).

## License

This sample is distributed under the **Cisco Sample Code License, Version 1.1**; see `LICENSE`.
