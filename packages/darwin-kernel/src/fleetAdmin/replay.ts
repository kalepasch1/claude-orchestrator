/**
 * Counterfactual replay — before promoting an action-type to `auto`, replay it against
 * the ENTIRE historical decision log: "had this run unattended, here is every call it
 * would have made and where it would have diverged from what you actually decided."
 * Promotion stops being a leap of faith — you approve autonomy with a measured
 * false-positive rate. Pure + zero-dep.
 */
import type { AdminDomain, AutonomyTier } from './types.ts';
import type { ResolvedCase } from './precedent.ts';

export interface ReplayResult {
  domain: AdminDomain;
  actionType: string;
  proposedTier: AutonomyTier;
  /** cases this promotion would have run unattended */
  wouldAutoRun: number;
  /** of those, how many the human actually edited or rejected (the mistakes) */
  divergences: number;
  /** divergences / wouldAutoRun — the measured error rate of the promotion */
  falsePositiveRate: number;
  /** clean approvals it would have correctly automated */
  correctlyAutomated: number;
  sampleSize: number;
  recommendation: 'safe_to_promote' | 'hold' | 'insufficient_history';
  reason: string;
}

export interface ReplayConfig {
  minSample: number;
  /** the highest false-positive rate you'll accept for a promotion */
  maxFalsePositiveRate: number;
}

export const DEFAULT_REPLAY_CONFIG: ReplayConfig = { minSample: 10, maxFalsePositiveRate: 0.02 };

/**
 * Replay a candidate promotion for (domain, actionType) against resolved history.
 * Only `auto`/`co_pilot` promotions are replayable; a divergence is any case the human
 * did NOT clean-approve (edit or reject) that the promotion would have run.
 */
export function replayPromotion(
  params: { domain: AdminDomain; actionType: string; proposedTier: AutonomyTier },
  history: ResolvedCase[],
  cfg: ReplayConfig = DEFAULT_REPLAY_CONFIG,
): ReplayResult {
  const matches = history.filter((c) => c.domain === params.domain && c.type === params.actionType);
  const base = { domain: params.domain, actionType: params.actionType, proposedTier: params.proposedTier };

  if (matches.length < cfg.minSample) {
    return {
      ...base, wouldAutoRun: 0, divergences: 0, falsePositiveRate: 0,
      correctlyAutomated: 0, sampleSize: matches.length,
      recommendation: 'insufficient_history', reason: `only ${matches.length} historical cases`,
    };
  }

  // Under `auto`, every matching case runs unattended; under `co_pilot` the human still
  // sees it, so there is no counterfactual divergence to score.
  const wouldAutoRun = params.proposedTier === 'auto' ? matches.length : 0;
  const divergences = params.proposedTier === 'auto' ? matches.filter((c) => c.outcome !== 'approve').length : 0;
  const correctlyAutomated = wouldAutoRun - divergences;
  const falsePositiveRate = wouldAutoRun ? divergences / wouldAutoRun : 0;

  let recommendation: ReplayResult['recommendation'];
  let reason: string;
  if (params.proposedTier !== 'auto') {
    recommendation = 'safe_to_promote';
    reason = 'co_pilot keeps a human in the loop — no unattended divergence risk';
  } else if (falsePositiveRate <= cfg.maxFalsePositiveRate) {
    recommendation = 'safe_to_promote';
    reason = `${divergences}/${wouldAutoRun} would have diverged (${(falsePositiveRate * 100).toFixed(1)}% ≤ ${(cfg.maxFalsePositiveRate * 100).toFixed(1)}% ceiling)`;
  } else {
    recommendation = 'hold';
    reason = `${divergences}/${wouldAutoRun} would have diverged (${(falsePositiveRate * 100).toFixed(1)}% > ${(cfg.maxFalsePositiveRate * 100).toFixed(1)}% ceiling)`;
  }

  return {
    ...base, wouldAutoRun, divergences,
    falsePositiveRate: Math.round(falsePositiveRate * 1000) / 1000,
    correctlyAutomated, sampleSize: matches.length, recommendation, reason,
  };
}
