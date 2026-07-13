/**
 * Precedent-weighted pricing input + determination-driven capital optimization.
 * Both are advisory calc — Tomorrow computes; it never holds, lends, or moves funds.
 */

/**
 * #5 Precedent-weighted pricing: widen the spread (bps) as the referenced precedent
 * is more concentrated (fragile) and its determination source less reliable. Feeds
 * the pricing oracle; the market thereby prices legal fragility.
 */
export function precedentPricingAdjustmentBps(
  concentrationHhi: number,
  sourceReliability: number,
  opts: { baseBps?: number; concentrationBps?: number; unreliabilityBps?: number } = {},
): number {
  const base = opts.baseBps ?? 0;
  const cW = opts.concentrationBps ?? 50;
  const rW = opts.unreliabilityBps ?? 50;
  const hhi = clamp01(concentrationHhi);
  const unreliab = 1 - clamp01(sourceReliability);
  return Math.max(0, base + cW * hhi + rW * unreliab);
}

export interface CapitalPosition {
  positionId: string;
  /** baseline initial margin the position would require without certification. */
  baselineImUsd: number;
  /** certified enforceability haircut multiplier in [floor,1] (lower = more certain). */
  haircutMultiplier: number;
}

export interface CapitalOptimization {
  freedUsd: number;
  byPosition: { positionId: string; freedUsd: number }[];
  optimizedImUsd: number;
}

/**
 * #7 Determination-driven capital optimization: a certified determination lowers the
 * haircut, freeing initial margin. Pure aggregation of the advisory haircuts.
 */
export function optimizeCapitalTreatment(positions: CapitalPosition[]): CapitalOptimization {
  let freedUsd = 0;
  let optimizedImUsd = 0;
  const byPosition = positions.map((p) => {
    const mult = Math.max(0, Math.min(1, p.haircutMultiplier));
    const optimized = p.baselineImUsd * mult;
    const freed = Math.max(0, p.baselineImUsd - optimized);
    freedUsd += freed;
    optimizedImUsd += optimized;
    return { positionId: p.positionId, freedUsd: freed };
  });
  return { freedUsd, byPosition, optimizedImUsd };
}

function clamp01(x: number): number {
  return Math.max(0, Math.min(1, x));
}
