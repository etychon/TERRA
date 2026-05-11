# Engineering style (TERRA)

## Principles

- **Boring over clever:** predictable modules, explicit boundaries, tests that read like examples.
- **Types:** strict typing for application Python once `src/` packages exist; tests may stay pragmatic.
- **Lint:** Ruff is canonical for Python; avoid fighting the formatter.
- **Commits / PRs:** explain *why* and user-visible *what*; link issues when available.

## UI and design system

- **Canonical spec:** `specs/design-system.md` (spacing, theme, motion, Cisco brand rules, guardrails).
- **Implementation SSOT:** `frontend/src/tokens/` (`primitives.ts` → `semantic.ts` → `components.ts`) and `frontend/src/styles/globals.css` (CSS variables, `:root` / `.dark`).
- **Stack:** Tailwind + shadcn-style semantic variables; see `LLM_CONTEXT.md` § UI stack.

## Specs

- Short files, updated with behavior changes. Prefer tables and bullet lists over prose walls.

## Considered / discarded

- **“No types until later”** — rejected for `src/` once code exists; retro-fitting strict mypy is expensive.
- **“Ad hoc hex colors in components”** — rejected; violates token + ESLint contract (see `specs/design-system.md`).
