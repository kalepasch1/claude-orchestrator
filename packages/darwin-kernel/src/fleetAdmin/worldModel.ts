/**
 * Pre-launch world model — before a new app (#11, #12, …) writes a line of adapter code,
 * project its day-one behaviour on the plane: its autonomy rate, its blast concentration,
 * and its treasury contribution, given an expected event mix and the federated priors it
 * would borrow. Launch decisions become quantified instead of hopeful. Pure + zero-dep.
 */
import type { AdminDomain, AutonomyTier } from './types.ts';
import { simulateBlast, type BlastAssessment } from './blastSimulator.ts';
import { buildTreasury, type TreasuryStatement, type SettledDecision } from './treasury.ts';

export interface ExpectedType {
  domain: AdminDomain;
  actionType: string;
  /** projected decisions per day for this type */
  dailyVolume: number;
  /** expected clean-approval rate (from a comparable app or a guess) */
  expectedCleanRate: number;
  avgAmountUsd?: number;
}

export interface WorldModelProjection {
  product: string;
  projectedAutonomyRate: number;
  /** which types would run unattended day one (borrowed from federated priors) */
  autoTypes: string[];
  dailyDecisions: number;
  blast: BlastAssessment[];
  treasury: TreasuryStatement;
  summary: string;
}

/**
 * Project a new app. `federatedSeed` maps `${domain}::${type}` → the tier the cross-app
 * cohort supports (from `seedFromFederated`); types without a prior default to human.
 */
export function projectNewApp(params: {
  product: string;
  expected: ExpectedType[];
  federatedSeed?: Record<string, AutonomyTier>;
  ceilingOf: (d: AdminDomain) => AutonomyTier;
}): WorldModelProjection {
  const seed = params.federatedSeed ?? {};
  const decisions: SettledDecision[] = [];
  const autoTypes: string[] = [];
  let autoVol = 0;
  let totalVol = 0;

  for (const t of params.expected) {
    const key = `${t.domain}::${t.actionType}`;
    const priorTier = seed[key] ?? 'human';
    const runsAuto = priorTier === 'auto' && params.ceilingOf(t.domain) === 'auto';
    totalVol += t.dailyVolume;
    if (runsAuto) {
      autoTypes.push(key);
      autoVol += t.dailyVolume;
      for (let i = 0; i < t.dailyVolume; i++) decisions.push({ domain: t.domain, tier: 'auto', decision: 'allow', amountUsd: t.avgAmountUsd });
    } else {
      const rejects = Math.round(t.dailyVolume * (1 - t.expectedCleanRate));
      for (let i = 0; i < t.dailyVolume; i++) {
        decisions.push({ domain: t.domain, tier: 'human', decision: 'escalate', outcome: i < rejects ? 'reject' : 'approve', amountUsd: t.avgAmountUsd });
      }
    }
  }

  const projectedAutonomyRate = totalVol ? Math.round((autoVol / totalVol) * 100) / 100 : 0;
  const blast = params.expected.map((t) =>
    simulateBlast(
      { domain: t.domain, actionType: t.actionType },
      Array.from({ length: t.dailyVolume }, () => ({ product: params.product, amountUsd: t.avgAmountUsd, at: '2026-07-01T00:00:00.000Z' })),
    ),
  );
  const treasury = buildTreasury(decisions);

  return {
    product: params.product,
    projectedAutonomyRate,
    autoTypes,
    dailyDecisions: totalVol,
    blast,
    treasury,
    summary:
      `${params.product} projects ${Math.round(projectedAutonomyRate * 100)}% day-one autonomy across ${totalVol} daily decisions ` +
      `(${autoTypes.length} type(s) borrow auto from federated priors), net treasury ~$${treasury.netUsd}/period.`,
  };
}
