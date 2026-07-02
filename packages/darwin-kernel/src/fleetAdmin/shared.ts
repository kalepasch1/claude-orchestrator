/**
 * Shared fleetAdmin primitives — the single source of truth for values that were previously
 * duplicated across modules (the autonomy tier ordering, the harm-score heuristic, amount
 * bucketing). Consolidated so one change propagates everywhere and there is exactly one
 * definition to audit. Pure + zero-dep.
 */
import type { AutonomyTier, Reversibility, BlastRadius } from './types.ts';

/** Canonical autonomy ordering (human < co_pilot < auto). Used by every clamp/compose step. */
export const TIER_ORDER: Record<AutonomyTier, number> = { human: 0, co_pilot: 1, auto: 2 };

/** Return the LESS-autonomous of two tiers (used to clamp). */
export function minTier(a: AutonomyTier, b: AutonomyTier): AutonomyTier {
  return TIER_ORDER[a] <= TIER_ORDER[b] ? a : b;
}

/**
 * The one harm-score heuristic (0..1) used by the red-team, co-evolution, and bounty market.
 * Reversibility + blast radius + money magnitude. Previously copied in three places.
 */
export function fleetHarmScore(a: { amountUsd?: number; reversibility: Reversibility; blastRadius: BlastRadius }): number {
  const rev = a.reversibility === 'irreversible' ? 0.4 : a.reversibility === 'hard_to_reverse' ? 0.25 : 0;
  const blast = { single: 0, small: 0.1, large: 0.3, fleet: 0.45 }[a.blastRadius];
  const money = Math.min(0.3, (a.amountUsd ?? 0) / 3000);
  return Math.round(Math.min(1, rev + blast + money) * 100) / 100;
}

/** Coarse 0..4 money bucket used by precedent similarity. */
export function amountBucket5(v: number | undefined): number {
  const a = v ?? 0;
  if (a <= 0) return 0;
  if (a <= 50) return 1;
  if (a <= 500) return 2;
  if (a <= 5000) return 3;
  return 4;
}
