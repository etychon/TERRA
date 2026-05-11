---
name: terra-ui-design-system
description: >-
  Implements or reviews TERRA UI using Material Design 3 (shape, type, state layers),
  Cisco-aligned semantic colors (no purple/indigo), Roboto + Roboto Mono, and the
  shared token/CSS-variable model. Covers frontend/ (Tailwind + shadcn-style tokens)
  and server-rendered Jinja pages (src/terra/static/css/, base.html). Use when
  editing theme, tables, Tabulator, auth shell, sidebar, buttons, chips, motion, or
  accessibility; or when the user mentions TERRA UI, Material 3, M3, design tokens,
  Cisco palette, dark mode, or pulsating gradients.
disable-model-invocation: false
---

# TERRA UI design system (agent skill)

## Read first (in order)

1. `specs/design-system.md` — **canonical** product rules (Material 3 structure, Cisco brand, banned hues, density, motion, guardrails).
2. `LLM_CONTEXT.md` — § **UI stack, design system, and AI ergonomics** for stack rationale and file map.
3. `frontend/README.md` — install and lint commands for the `frontend/` package.

## Non-negotiables

- **Material 3:** use M3 **type scale** roles (e.g. title-medium, headline-small, label-large for buttons), **shape tokens** (`--md-sys-shape-corner-*`, full corner for pill buttons), and **surface container** hierarchy for cards, headers, and dense tables. Reference: [m3.material.io](https://m3.material.io/).
- **Cisco brand:** official **logo** and palette values from **Cisco Brand Center**; reconcile token values in `frontend/src/tokens/primitives.ts` with published swatches before production.
- **No purple family:** do **not** use `purple`, `indigo`, `violet`, or `fuchsia` as Tailwind hue stems or raw design colors unless `specs/design-system.md` records an approved exception.
- **Theme colors:** live in **`frontend/src/styles/globals.css`** as **CSS custom properties** on `:root` and `.dark`. Server-rendered pages mirror semantics in **`src/terra/static/css/terra-auth.css`** (same HSL triplet pattern where possible). **No JS is required** for theme color switching—toggle `class="dark"` on the root; variables swap.
- **Semantic-first for AI:** extend **one semantic system** (`semantic.ts` + CSS vars consumed by Tailwind/shadcn); do not duplicate parallel light/dark hex systems in JSX.
- **Spacing:** primary rhythm **8px grid** (`8, 16, 24, …`); **4px** only for micro nudges.
- **Motion:** optional **slow pulsating gradients** on decorative surfaces; always respect **`prefers-reduced-motion`**.

## Where implementation lives

| Area | Files |
|------|--------|
| SPA / Tailwind dashboard | `frontend/src/tokens/`, `frontend/src/styles/globals.css`, shadcn-style components |
| FastAPI Jinja UI (auth, home, admin, device pages) | `src/terra/templates/base.html`, `src/terra/static/css/terra-fonts.css` (self-hosted Roboto / Roboto Mono), `src/terra/static/css/terra-auth.css`, `src/terra/static/css/terra-devices.css`, `src/terra/static/vendor/tabulator.min.css` + scoped overrides |
| Device grid JS | `src/terra/static/js/terra-devices-home.js` (formatters; keep HTML escaped in formatters) |

## Token file contract (TypeScript dashboard)

| File | Role |
|------|------|
| `frontend/src/tokens/primitives.ts` | Raw values only (no `surface.*` / `text.*` semantics). **Only file** where arbitrary hex/HSL literals are allowed by ESLint. |
| `frontend/src/tokens/semantic.ts` | Imports `primitives`; assigns **meaning** (`surface.canvas`, `text.default`, …). |
| `frontend/src/tokens/components.ts` | Imports **both**; builds **component recipes** (shell, table, card). |

## Before you finish a UI PR

- Run `cd frontend && npm run lint` (`tsc --noEmit`, ESLint, and the design contract script) when `frontend/` changes.
- Run `pytest`, `ruff check src tests`, and `mypy src` when Python or templates change.
- If rules in `specs/design-system.md` changed, update that spec in the **same PR**.

## Further reference

- ESLint rules: `frontend/eslint/terra-design-plugin.mjs`
- Contract script: `frontend/scripts/verify-design-contract.mjs`
