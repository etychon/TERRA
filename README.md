# TERRA

**T**elemetry for **E**dge and **R**emote **R**outable **A**ssets — a Cisco Catalyst SD-WAN–oriented operations dashboard for non-expert users.

This repository is intentionally **scaffolding only** at this stage: documentation, specifications, LLM-oriented context, and automation hooks. Application services, UI, and SD-WAN integration code will land in follow-up changes.

## Goals (summary)

- Monitor **multiple** SD-WAN environments from one place using **Cisco Catalyst SD-WAN Manager APIs** (configuration stays in Manager).
- Present a **compact, high-level** view of cEdge health: IOS-XE version (with **out-of-date** highlighting), CPU, memory, link usage, cellular quality, disk, IOx app status, GPS history, alerts/events, and related reporting.
- First-class **authentication and user management** in the dashboard (not delegated to SD-WAN WebUI for day-to-day monitoring).
- Design for a future **Cisco Catalyst Center** connector without locking the core model to Manager-only assumptions.

## Repository layout

| Path | Purpose |
|------|---------|
| `src/` | Application code, ingestion, API clients, services (to be added). |
| `tests/` | Unit, integration, and smoke tests. |
| `data/` | Local datasets, fixtures, and cached samples (no secrets). |
| `notebooks/` | Exploratory analysis and prototyping. |
| `models/` | Serialized models or schema artifacts if/when needed. |
| `docs/` | Human-facing documentation beyond the README. |
| `specs/` | Short, authoritative product and engineering specs. |
| `package.json` (root) | Proxies `npm run lint` / `npm run typecheck` to `frontend/` so you can run them from the repo root. |
| `frontend/` | Dashboard UI: Tailwind + shadcn-style CSS variables, token layers, ESLint design guardrails. |
| `.cursor/skills/terra-ui-design-system/` | Cursor **SKILL** for UI work (loads design-system rules). |
| `LLM_CONTEXT.md` | **LLM-oriented** project context (not a substitute for `specs/`). |

## Prerequisites

- Python **3.11+** (tooling and future backend/tests).
- **Node.js 18+** and **npm** (dashboard UI; **20 LTS** recommended to match `frontend/.nvmrc` and avoid upstream engine warnings).

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
ruff check .
mypy tests
```

> **Note:** `mypy` is strict on `tests/` today. Once application packages exist under `src/`, extend `pyproject.toml` (`files` / `packages`) and CI so `src/` is type-checked as well.

## Frontend (design system + guardrails)

This repo uses **npm workspaces** (`frontend/` is a workspace). From the **repo root**:

```bash
npm install
npm run lint
```

(`npm run lint` runs `tsc`, ESLint, and the design contract script on the workspace package. Use `npm run typecheck` only if you want TypeScript alone.)

Authoritative UI rules: `specs/design-system.md`. TypeScript tokens live in `frontend/src/tokens/` (`primitives.ts` → `semantic.ts` → `components.ts`); theme colors are **CSS custom properties** in `frontend/src/styles/globals.css` (`:root` / `.dark`).

## Application entry points

There is **no runnable application** yet. When services and UI are added, this README will document how to start them and which URLs or CLIs to hit for smoke verification.

## Agent and automation entry points

- **`AGENTS.md`** — concise guidance for coding agents (workflows, PR expectations, spec discipline).
- **`LLM_CONTEXT.md`** — dense machine-oriented context for models assisting on this repo.
- **`.cursor/skills/terra-ui-design-system/SKILL.md`** — agent skill for dashboard UI (Cisco-aligned tokens, Tailwind + shadcn variable pattern, ESLint/pre-commit guardrails).

## License

This sample is distributed under the **Cisco Sample Code License, Version 1.1**; see `LICENSE`.
