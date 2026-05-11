# AGENTS.md — guidance for automated coding agents

## Read first

1. `README.md` — human + agent orientation, commands, layout.
2. `LLM_CONTEXT.md` — codename, scope, integrations, UI stack, and non-goals in machine-oriented form.
3. `specs/` — **short** canonical decisions. If behavior or architecture changes, update specs in the **same PR**. (Runtime defaults such as **Docker Compose** and cross-platform targets are summarized in `specs/architecture.md` and detailed for agents in `LLM_CONTEXT.md`.)
4. **UI work:** read `specs/design-system.md` and use the Cursor skill `.cursor/skills/terra-ui-design-system/SKILL.md` (tokens + Tailwind/shadcn CSS-variable pattern + guardrails).

## Specs discipline

- Prefer small files in `specs/` over long design dumps.
- When you discard an approach, add a one-paragraph “considered / rejected” note in the relevant spec so future agents do not re-litigate silently.

## Quality bar (when code exists)

- **Lint:** `ruff check .`
- **Types:** `mypy tests` today; extend to `src/` once packages exist (update `pyproject.toml` + CI together).
- **Frontend:** from **repo root**, `npm install` (workspaces) then `npm run lint` (runs `tsc --noEmit`, ESLint, design contract script on `terra-dashboard-frontend`). Use `npm run typecheck` alone when you only need TypeScript.
- **Tests:** `pytest` (unit + integration as applicable; keep **smoke** tests fast and deterministic).
- **Runbook:** document how to start the app and hit health or key endpoints in `README.md` once those exist.

## CI

GitHub Actions workflow: `.github/workflows/ci.yml`. A red CI run means the change set is not merge-ready.

## Secrets and customer data

- Never commit credentials, tokens, private keys, or customer exports.
- Use environment variables or a secrets manager; provide `.env.example` **without** real values when wiring configuration.

## Cisco Catalyst Center (future)

- Keep Manager API assumptions behind a **connector** boundary; see `specs/architecture.md`.

## Pre-PR checklist (agent)

- [ ] Tests updated or added for behavior changes.
- [ ] `specs/` updated if decisions, integrations, domain language, or **design system** rules changed.
- [ ] `README.md` updated if commands, ports, or run steps changed.
- [ ] **UI changes:** `npm run lint` in `frontend/` passes; no forbidden hues or raw hex outside `primitives.ts`.
- [ ] No secrets or customer PII added to the repo.
