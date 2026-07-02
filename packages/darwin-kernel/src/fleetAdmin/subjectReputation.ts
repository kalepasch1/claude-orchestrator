/**
 * Cross-app subject reputation — the same user / hotel / counterparty / regulator appears
 * across galop, pareto, apparently, tomorrow. Fuse their signals into ONE reputation so a
 * fraud signal in one app pre-emptively tightens autonomy for that subject EVERYWHERE. One
 * bad actor caught once is caught fleet-wide. Pure + zero-dep; consumes the consent-scoped
 * identity graph's resolved subject id.
 */
import type { AutonomyTier } from './types.ts';

export interface SubjectSignal {
  subjectId: string; // resolved cross-app id
  product: string;
  kind: 'fraud' | 'chargeback' | 'abuse' | 'dispute' | 'good_standing' | 'verified';
  at: string;
}

const WEIGHT: Record<SubjectSignal['kind'], number> = {
  fraud: -0.5,
  chargeback: -0.25,
  abuse: -0.4,
  dispute: -0.1,
  good_standing: 0.15,
  verified: 0.2,
};

export interface SubjectReputation {
  subjectId: string;
  /** 0..1 — 1 is trusted, 0 is high-risk. Starts neutral at 0.5. */
  score: number;
  appsSeen: string[];
  negativeFlags: SubjectSignal['kind'][];
  signalCount: number;
}

/** Fuse a subject's signals from every app into one reputation. */
export function fuseReputation(signals: SubjectSignal[]): SubjectReputation[] {
  const bySubject = new Map<string, SubjectSignal[]>();
  for (const s of signals) (bySubject.get(s.subjectId) ?? bySubject.set(s.subjectId, []).get(s.subjectId)!).push(s);

  const out: SubjectReputation[] = [];
  for (const [subjectId, arr] of bySubject) {
    let score = 0.5;
    for (const s of arr) score += WEIGHT[s.kind];
    score = Math.max(0, Math.min(1, Math.round(score * 100) / 100));
    out.push({
      subjectId,
      score,
      appsSeen: [...new Set(arr.map((s) => s.product))],
      negativeFlags: [...new Set(arr.filter((s) => WEIGHT[s.kind] < 0).map((s) => s.kind))],
      signalCount: arr.length,
    });
  }
  return out.sort((a, b) => a.score - b.score); // riskiest first
}

const TIER_ORDER: Record<AutonomyTier, number> = { human: 0, co_pilot: 1, auto: 2 };

/**
 * Clamp autonomy for an action based on the subject's fleet-wide reputation. Low reputation
 * forces a human; medium caps at co-pilot. Can only LOWER autonomy (fail-closed), and only
 * when we actually have a reputation for the subject.
 */
export function reputationAdjustedTier(
  dialTier: AutonomyTier,
  rep: SubjectReputation | undefined,
  thresholds = { human: 0.3, coPilot: 0.6 },
): { tier: AutonomyTier; reason: string } {
  if (!rep) return { tier: dialTier, reason: 'no_reputation' };
  let cap: AutonomyTier = 'auto';
  if (rep.score < thresholds.human) cap = 'human';
  else if (rep.score < thresholds.coPilot) cap = 'co_pilot';
  const tier = TIER_ORDER[cap] < TIER_ORDER[dialTier] ? cap : dialTier;
  return {
    tier,
    reason: tier === dialTier ? `reputation ${rep.score} within tolerance` : `subject reputation ${rep.score} (${rep.negativeFlags.join(',') || 'low'}) → capped at ${cap}`,
  };
}
