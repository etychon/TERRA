/**
 * Primitives — raw values only (no product semantics like "danger" or "canvas").
 * Reconcile chroma with Cisco Brand Center before production.
 * ESLint allows raw hex / hsl components here only (see eslint.config.mjs).
 */

/** 8px grid with 4px sub-grid (values in px). */
export const primitiveSpace = {
  px0: 0,
  px4: 4,
  px8: 8,
  px12: 12,
  px16: 16,
  px20: 20,
  px24: 24,
  px32: 32,
  px40: 40,
  px48: 48,
  px56: 56,
  px64: 64,
} as const;

/** Nature-named ramps (numeric steps only; names are labels, not UI semantics). */
export const primitivePalette = {
  basalt: {
    950: "#05080c",
    900: "#0b1520",
    800: "#102536",
    700: "#16344a",
    600: "#1f4a63",
  },
  tidePool: {
    600: "#03658c",
    500: "#0487b1",
    400: "#0aa3cf",
    300: "#45c4e0",
    200: "#8bdff0",
  },
  lichen: {
    700: "#1f5c37",
    600: "#2f7a47",
    500: "#3fa15d",
    400: "#6edc8f",
  },
  sandbar: {
    500: "#c49a6c",
    400: "#d9b48a",
    300: "#e9d2b8",
    200: "#f3e6d8",
  },
} as const;

/** Cisco-adjacent brand anchors (verify against Brand Center swatches). */
export const primitiveBrand = {
  ciscoBlue500: "#049fd9",
  ciscoBlue400: "#00bce7",
  ciscoTeal600: "#00778f",
} as const;

/** Signal chroma (still primitive — not yet "risk.critical" semantics). */
export const primitiveSignal = {
  flare700: "#d23f31",
} as const;

export const primitiveMotion = {
  /** Decorative gradient loop (seconds) — keep slow and low-contrast. */
  ambientGradientCycleS: 22,
  /** Micro interaction baseline. */
  instantMs: 120,
} as const;

export const primitiveRadii = {
  r4: 4,
  r8: 8,
  r12: 12,
} as const;
