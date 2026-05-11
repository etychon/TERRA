/**
 * Component recipes — compose semantic + primitive values for recurring UI parts.
 */

import { primitiveSpace } from "./primitives";
import { semanticColor, semanticMotion, semanticRadius, semanticSpace } from "./semantic";

export const componentShell = {
  headerPaddingY: semanticSpace.inset.sm,
  headerPaddingX: semanticSpace.inset.lg,
  headerGap: semanticSpace.stack.tight,
  borderColor: semanticColor.border.subtle,
} as const;

export const componentDataTable = {
  rowHeightMin: primitiveSpace.px40,
  cellPaddingX: semanticSpace.inset.md,
  cellPaddingY: semanticSpace.inset.xs,
  headerBackground: semanticColor.surface.raised,
  zebra: semanticColor.surface.inset,
} as const;

export const componentCard = {
  padding: semanticSpace.inset.lg,
  radius: semanticRadius.md,
  border: semanticColor.border.subtle,
  background: semanticColor.surface.raised,
} as const;

export const componentAmbient = {
  /** Decorative gradient timing — pair with CSS keyframes in globals.css. */
  gradientCycleS: semanticMotion.ambientGradientCycleS,
} as const;
