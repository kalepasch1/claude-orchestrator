/**
 * Counterfactual human model — "what would Bear have done?" run on EVERY auto action, in
 * shadow. Where the calibrated model predicts he would NOT have clean-approved what the plane
 * auto-ran, that's a real-time divergence — a self-supervised regret signal that doesn't wait
 * for a chargeback to fire. Feeds the regret ledger + tightens precedent immediately. Pure +
 * zero-dep; consumes the learned approver profile.
 */
import type { AdminDomain } from './types.ts';
import { predictDecision, type ApproverProfile } from './approverModel.ts';

export interface AutoDecisionRef {
  actionId: string;
  domain: AdminDomain;
  actionType: string;
}

export interface CounterfactualFlag {
  actionId: string;
  domain: AdminDomain;
  actionType: string;
  /** what the model thinks the human would have done */
  predicted: 'approve' | 'modify' | 'reject' | 'uncertain';
  confidence: number;
  /** true when the plane auto-ran something the human likely would NOT have clean-approved */
  divergence: boolean;
}

export interface CounterfactualReport {
  flags: CounterfactualFlag[];
  autoCount: number;
  divergences: number;
  /** shadow divergence rate among auto-runs — an early-warning regret proxy */
  divergenceRate: number;
}

/**
 * Score every auto action against the approver model. A divergence is flagged only when the
 * model is confident the human would have edited or rejected (>= `minConfidence`) — so we don't
 * cry wolf on uncertain predictions.
 */
export function counterfactualReview(
  autos: AutoDecisionRef[],
  profile: ApproverProfile,
  minConfidence = 0.6,
): CounterfactualReport {
  const flags: CounterfactualFlag[] = autos.map((a) => {
    const p = predictDecision(profile, a.domain, a.actionType);
    const divergence = (p.likely === 'reject' || p.likely === 'modify') && p.confidence >= minConfidence;
    return { actionId: a.actionId, domain: a.domain, actionType: a.actionType, predicted: p.likely, confidence: p.confidence, divergence };
  });
  const divergences = flags.filter((f) => f.divergence).length;
  return {
    flags: flags.filter((f) => f.divergence).concat(flags.filter((f) => !f.divergence)),
    autoCount: autos.length,
    divergences,
    divergenceRate: autos.length ? Math.round((divergences / autos.length) * 1000) / 1000 : 0,
  };
}
