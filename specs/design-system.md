# Design system (single source of truth)

This file is the **canonical product spec** for TERRA visual and interaction consistency. Implementation lives under `frontend/` (tokens, `globals.css`, Tailwind, shadcn-style variables) **and** server-rendered pages under `src/terra/static/css/` (`terra-auth.css`, `terra-devices.css`). Agents: also read `.cursor/skills/terra-ui-design-system/SKILL.md` and `LLM_CONTEXT.md` (UI stack section).

## Material Design 3 (structure)

TERRA UI follows **Material Design 3** for **interaction, shape, typography, and state layers** (see [Material Design 3](https://m3.material.io/)). Cisco brand rules below still govern **hue families and logo** usage.

- **Type:** **Roboto** and **Roboto Mono**, **self-hosted** from `src/terra/static/fonts/` via `src/terra/static/css/terra-fonts.css` (linked in `base.html` before `terra-auth.css`). No runtime requests to Google Fonts. The dashboard package should mirror the same pairing if it ships webfonts.
- **Shape:** corner tokens `--md-sys-shape-corner-*` and component radii (e.g. **full** for standard buttons, **large** for cards and data surfaces).
- **Components:** buttons use M3 **filled** / **outlined** / **filled tonal** patterns; tables and chips use **surface container** hierarchy and **label** / **body** type roles—not legacy all-caps table chrome unless a specific spec requires it.

## Brand and trust

- **Cisco marks:** use the **official Cisco logo** and palette values from **Cisco Brand Center** (do not invent unofficial logos in production). Until assets are added, see `frontend/public/brand/README.md`.
- **Palette discipline:** primary chroma stays within **Cisco-approved blues / teals / neutrals / greens / ambers** as defined in Brand Center. **Do not use purple or indigo** (including Tailwind `purple-*`, `indigo-*`, `violet-*`, `fuchsia-*`) unless an explicit, documented exception is approved and recorded here.
- **Nature-derived extensions:** secondary accents may be named and tuned from **nature references** (tide, basalt, lichen, sandbar, etc.) but must still meet **contrast-first** requirements and remain on-brand (no purple family).

## Theme and motion

- **Dark theme** is a first-class requirement; light theme may follow later using the same semantic tokens.
- **Theme switching** uses **CSS only:** custom properties on `:root` and `.dark` in `frontend/src/styles/globals.css`. **No JavaScript is required** to toggle theme; the document root carries `class="dark"` when dark mode is active (frameworks may set that class—logic is still “CSS variables + class”, not runtime color math in JS).
- **Ambient motion:** decorative surfaces may use **slow, low-amplitude pulsating gradients** (long duration, subtle opacity or stop shifts). Motion must respect `prefers-reduced-motion` (provide reduced or static fallbacks).

## Density and layout

- **Information-dense** dashboard UI (operators scan many devices).
- **Spacing:** **8px base grid** with steps `8, 16, 24, 32, 40, 48, …` exposed as tokens.
- **Sub-grid:** **4px** for fine adjustments only (icon nudges, border alignment), never as the primary layout rhythm.

## Technical stack (AI-optimized)

- **Tailwind CSS** + **shadcn/ui variable pattern:** one **semantic** token system mapped through **CSS custom properties**; Tailwind reads `hsl(var(--token) / <alpha-value>)` style values. Do not teach parallel ad-hoc “light hex palette + dark hex palette” in components.
- **TypeScript token layers** (strict separation):
  - `frontend/src/tokens/primitives.ts` — raw numbers / hex / HSL components; **no product meaning**.
  - `frontend/src/tokens/semantic.ts` — imports primitives; assigns **purpose** (surface, border, risk, brand).
  - `frontend/src/tokens/components.ts` — imports primitives + semantic; **composes** component recipes (cards, shells, tables).

## Guardrails (must run in CI and pre-commit)

- **ESLint** (repo-local rules under `frontend/eslint/`) enforces: no disallowed Tailwind hue classes; no raw `#hex` in TS/TSX outside `primitives.ts` (tests may be excluded as documented in ESLint config).
- **`npm run lint`** also runs **`scripts/verify-design-contract.mjs`** for CSS and cross-file checks (e.g. forbidden hue keywords in `globals.css`).
- **Pre-commit** invokes frontend lint when `frontend/` changes.

## Devices grid (React island)

- **Location:** `/devices` mounts a Vite-built bundle (`src/terra/static/dist/devices-grid.js`) on `#terra-devices-grid-root`.
- **Column contract:** stable ids in `frontend/src/devices/columnMeta.ts` (`cluster`, `tenant`, `hostname`, `cellular`, …). Bump `terra.devicesGrid.prefs.v1` only when adding/removing column ids.
- **Custom cells:** React components under `frontend/src/devices/cells/` (e.g. cellular sparkline + RSSI dot). Do not use HTML string formatters or table-wide `redraw()` for async graphics.
- **Cellular sparklines:** [Datatype](https://franktisellano.github.io/datatype/) variable font (`{l:…}` ligatures) self-hosted in `static/fonts/`; `.terra-dg-datatype-spark` must set `font-feature-settings: "liga" 1, "calt" 1` and `letter-spacing: 0` (see [integration guide](https://franktisellano.github.io/datatype/integrations.html)); RSSI dBm mapped to 0–100 heights in `datatypeSparkline.ts`.
- **Data:** `GET /api/v1/me/devices` (paginated); never embed the full fleet in Jinja JSON.
- **Styling:** `frontend/src/devices/devices-grid.css` uses parent page semantic HSL tokens from `terra-auth.css` (`--foreground`, `--surface-container-*`, `--primary`, …). No purple/indigo; no light-theme hex fallbacks.

## Considered / discarded

- **Dual parallel palettes in components (light vs dark hex in JSX)** — rejected; conflicts with shadcn-style semantic CSS variables and doubles AI error surface.
- **JS-driven theme color computation** as the default — rejected for theme colors; class + CSS variables only for color theming.
- **Tabulator + monolithic `terra-devices-home.js` for `/devices`** — rejected; replaced by typed React island + TanStack Table (2025) due to fragile persistence, HTML formatters, and gesture conflicts.

When visual rules change, update this file in the **same PR** as token or CSS changes.
