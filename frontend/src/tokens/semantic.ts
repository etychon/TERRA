/**
 * Semantic layer — purpose-driven tokens referencing primitives only.
 */

import {
  primitiveBrand,
  primitiveMotion,
  primitivePalette,
  primitiveRadii,
  primitiveSignal,
  primitiveSpace,
} from "./primitives";

export const semanticColor = {
  surface: {
    canvas: primitivePalette.basalt[900],
    raised: primitivePalette.basalt[800],
    inset: primitivePalette.basalt[950],
    overlay: primitivePalette.basalt[700],
  },
  text: {
    default: primitivePalette.sandbar[200],
    muted: primitivePalette.sandbar[300],
    inverse: primitivePalette.basalt[900],
  },
  border: {
    subtle: primitivePalette.basalt[700],
    strong: primitivePalette.basalt[600],
  },
  brand: {
    primary: primitiveBrand.ciscoBlue500,
    accent: primitiveBrand.ciscoBlue400,
    deep: primitiveBrand.ciscoTeal600,
  },
  risk: {
    warn: primitivePalette.sandbar[500],
    ok: primitivePalette.lichen[500],
    critical: primitiveSignal.flare700,
  },
} as const;

export const semanticSpace = {
  /** Inset scale aligned to 8px grid; use px4 only for micro nudges. */
  inset: {
    xxs: primitiveSpace.px4,
    xs: primitiveSpace.px8,
    sm: primitiveSpace.px12,
    md: primitiveSpace.px16,
    lg: primitiveSpace.px24,
    xl: primitiveSpace.px32,
    xxl: primitiveSpace.px40,
  },
  stack: {
    tight: primitiveSpace.px8,
    comfy: primitiveSpace.px16,
    loose: primitiveSpace.px24,
  },
} as const;

export const semanticRadius = {
  sm: primitiveRadii.r4,
  md: primitiveRadii.r8,
  lg: primitiveRadii.r12,
} as const;

export const semanticMotion = {
  ambientGradientCycleS: primitiveMotion.ambientGradientCycleS,
  instantMs: primitiveMotion.instantMs,
} as const;
