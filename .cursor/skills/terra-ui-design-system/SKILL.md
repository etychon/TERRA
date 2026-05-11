---
name: terra-ui-design-system
description: >-
  Implements or reviews TERRA dashboard UI using the Cisco-aligned design system,
  Tailwind + shadcn-style CSS variables, three-layer TypeScript tokens, dark theme,
  8px/4px spacing, and automated ESLint/pre-commit guardrails. Use when editing
  frontend/, tokens, globals.css, Tailwind config, shadcn components, dashboard
  layout, theme, colors, motion, or accessibility; or when the user mentions
  TERRA UI, design tokens, Cisco palette, dark mode, or pulsating gradients.
disable-model-invocation: false
---

# TERRA UI design system (agent skill)

## Read first (in order)

1. `specs/design-system.md` — **canonical** product rules (brand, banned hues, density, motion, guardrails).
2. `LLM_CONTEXT.md` — § **UI stack, design system, and AI ergonomics** for stack rationale and file map.
3. `frontend/README.md` — install and lint commands.

## Non-negotiables

- **Cisco brand:** official **logo** and palette values from **Cisco Brand Center**; reconcile token values in `frontend/src/tokens/primitives.ts` with published swatches before production.
- **No purple family:** do **not** use `purple`, `indigo`, `violet`, or `fuchsia` as Tailwind hue stems or raw design colors unless `specs/design-system.md` records an approved exception.
- **Theme colors:** live in **`frontend/src/styles/globals.css`** as **CSS custom properties** on `:root` and `.dark`. **No JS is required** for theme color switching—toggle `class="dark"` on the root; variables swap.
- **Semantic-first for AI:** extend **one semantic system** (`semantic.ts` + CSS vars consumed by Tailwind/shadcn); do not duplicate parallel light/dark hex systems in JSX.
- **Spacing:** primary rhythm **8px grid** (`8, 16, 24, …`); **4px** only for micro nudges.
- **Motion:** optional **slow pulsating gradients** on decorative surfaces; always respect **`prefers-reduced-motion`**.

## Token file contract

| File | Role |
|------|------|
| `frontend/src/tokens/primitives.ts` | Raw values only (no `surface.*` / `text.*` semantics). **Only file** where arbitrary hex/HSL literals are allowed by ESLint. |
| `frontend/src/tokens/semantic.ts` | Imports `primitives`; assigns **meaning** (`surface.canvas`, `text.default`, …). |
| `frontend/src/tokens/components.ts` | Imports **both**; builds **component recipes** (shell, table, card). |

## Before you finish a UI PR

- Run `cd frontend && npm run lint` (`tsc --noEmit`, ESLint, and the design contract script).
- Run `cd frontend && npm run typecheck` only when you want TypeScript alone (it is already part of `npm run lint`).
- If rules in `specs/design-system.md` changed, update that spec in the **same PR**.

## Further reference

- ESLint rules: `frontend/eslint/terra-design-plugin.mjs`
- Contract script: `frontend/scripts/verify-design-contract.mjs`
