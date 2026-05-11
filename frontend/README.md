# TERRA frontend (dashboard UI)

## Setup

```bash
cd frontend
npm install
```

## Checks (run locally and in CI)

```bash
npm run lint
npm run typecheck
```

`npm run lint` runs **`tsc --noEmit`**, **ESLint** (including repo-local design rules), and **`scripts/verify-design-contract.mjs`**.

## Design system entrypoints

- **Spec:** `../specs/design-system.md`
- **Tokens:** `src/tokens/primitives.ts` → `semantic.ts` → `components.ts`
- **Theme variables:** `src/styles/globals.css` (`:root`, `.dark`)
- **Tailwind:** `tailwind.config.ts` maps semantic colors to `hsl(var(--…))` (shadcn-style)

When the application shell is scaffolded, initialize **shadcn/ui** with the official CLI and keep generated components wired to the same CSS variables (do not fork a second ad-hoc color system in JSX).

## Cisco logo

Place **approved** logo assets from **Cisco Brand Center** under `public/brand/` per `public/brand/README.md`. Do not ship unapproved marks.
