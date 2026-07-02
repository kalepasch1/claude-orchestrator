/**
 * Case-based autonomy — set an action's tier from how the most-similar PAST cases
 * actually resolved, instead of relying only on static confidence floors. This turns
 * the receipt/decision log into a live precedent index: the flywheel's memory becomes
 * the dial's input.
 *
 * Pure + zero-dep. Similarity is feature-based (domain, verb, money bucket,
 * reversibility, blast) — deterministic and well-suited to structured admin actions
 * (no embeddings needed, though a product may inject them later). FAIL CLOSED:
 * sparse or mixed precedent NEVER upgrades autonomy — it can only hold or lower it.
 */
import type { AdminAction, AutonomyTier } from './types.ts';
import { minTier } from './shared.ts';

export interface ResolvedCase {
  domain: AdminAction['domain'];
  type: string;
  amountUsd?: number;
  reversibility: AdminAction['reversibility'];
  blastRadius: AdminAction['blastRadius'];
  /** the human outcome from the queue */
  outcome: 'approve' | 'modify' | 'reject';
  at: string;
}

export interface PrecedentAdvice {
  /** the tier the precedent SUPPORTS (never above what the dial already allows) */
  suggestedTier: AutonomyTier;
  /** fraction of similar past cases approved without edit */
  cleanRate: number;
  sampleSize: number;
  reason: string;
}

function amountBucket(v: number | undefined): number {
  const a = v ?? 0;
  if (a <= 0) return 0;
  if (a <= 50) return 1;
  if (a <= 500) return 2;
  if (a <= 5000) return 3;
  return 4;
}

/** 0..1 similarity between an action and a past case. Verb + domain dominate. */
export function caseSimilarity(action: AdminAction, c: ResolvedCase): number {
  let score = 0;
  if (c.domain === action.domain) score += 0.3;
  if (c.type === action.type) score += 0.4;
  if (amountBucket(c.amountUsd) === amountBucket(action.amountUsd)) score += 0.1;
  if (c.reversibility === action.reversibility) score += 0.1;
  if (c.blastRadius === action.blastRadius) score += 0.1;
  return score;
}

export interface PrecedentConfig {
  k: number; // nearest neighbours to consider
  minSample: number; // below this, precedent is too sparse to matter
  minSim: number; // ignore cases below this similarity
  autoCleanRate: number; // clean-rate to support 'auto'
  coPilotCleanRate: number; // clean-rate to support 'co_pilot'
}

export const DEFAULT_PRECEDENT_CONFIG: PrecedentConfig = {
  k: 20,
  minSample: 5,
  minSim: 0.7, // same verb + domain at least
  autoCleanRate: 0.95,
  coPilotCleanRate: 0.6,
};

/**
 * Rank precedents and derive advice. With too few similar cases the advice is
 * 'human' with a low sample — i.e. "no basis to trust autonomy yet."
 */
export function precedentAdvice(
  action: AdminAction,
  cases: ResolvedCase[],
  cfg: PrecedentConfig = DEFAULT_PRECEDENT_CONFIG,
): PrecedentAdvice {
  const scored = cases
    .map((c) => ({ c, sim: caseSimilarity(action, c) }))
    .filter((x) => x.sim >= cfg.minSim)
    .sort((a, b) => b.sim - a.sim)
    .slice(0, cfg.k);

  const sampleSize = scored.length;
  if (sampleSize < cfg.minSample) {
    return { suggestedTier: 'human', cleanRate: 0, sampleSize, reason: 'insufficient_precedent' };
  }
  const clean = scored.filter((x) => x.c.outcome === 'approve').length;
  const cleanRate = clean / sampleSize;

  let suggestedTier: AutonomyTier;
  if (cleanRate >= cfg.autoCleanRate) suggestedTier = 'auto';
  else if (cleanRate >= cfg.coPilotCleanRate) suggestedTier = 'co_pilot';
  else suggestedTier = 'human';

  return {
    suggestedTier,
    cleanRate,
    sampleSize,
    reason: `${clean}/${sampleSize} similar cases clean-approved`,
  };
}

/**
 * Compose precedent with the dial's tier: the RESULT is the MINIMUM of the two
 * (precedent can only hold or lower autonomy, never raise it above what the dial
 * already granted). This keeps the fail-closed guarantee intact.
 */
export function applyPrecedent(dialTier: AutonomyTier, advice: PrecedentAdvice): AutonomyTier {
  return minTier(dialTier, advice.suggestedTier);
}
