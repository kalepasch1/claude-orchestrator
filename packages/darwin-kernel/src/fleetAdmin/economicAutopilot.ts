/**
 * Economic autopilot — optimize the autonomy dial against a realized-cost LOSS FUNCTION
 * instead of hand-set thresholds. For each action-type it prices the two worlds:
 *   auto  → volume × false-positive-rate × expected error cost
 *   human → volume × (approver-minute cost + latency-risk while it waits)
 * and recommends `auto` only when it's cheaper AND within your false-positive tolerance
 * AND the domain ceiling allows it. Autonomy stops being tuned and starts being solved.
 * Pure + zero-dep. Output is a materiality-gated proposal — a human still confirms.
 */
import type { AdminDomain, AutonomyTier } from './types.ts';

export interface TypeCostInput {
  domain: AdminDomain;
  actionType: string;
  /** decisions per period */
  volume: number;
  /** historical clean-approval rate 0..1 (1 - fpRate) */
  cleanRate: number;
  /** average $ magnitude of the action (drives error cost) */
  avgAmountUsd?: number;
}

export interface EconomicConfig {
  perDecisionMinutes: number;
  hourlyValueUsd: number;
  avgWaitHours: number;
  latencyRiskPerHourUsd: Record<AdminDomain, number>;
  /** expected cost of one wrong auto action = base + share of the amount */
  errorBaseUsd: number;
  errorAmountShare: number;
  /** max false-positive rate you'll tolerate for an auto promotion */
  maxFalsePositiveRate: number;
}

export const DEFAULT_ECONOMIC_CONFIG: EconomicConfig = {
  perDecisionMinutes: 3,
  hourlyValueUsd: 200,
  avgWaitHours: 4,
  latencyRiskPerHourUsd: { users_access: 2, billing: 8, trust_safety: 5, infra: 12 },
  errorBaseUsd: 40,
  errorAmountShare: 1.0,
  maxFalsePositiveRate: 0.02,
};

export interface EconomicRecommendation {
  domain: AdminDomain;
  actionType: string;
  recommend: 'auto' | 'keep_human';
  fpRate: number;
  autoCostUsd: number;
  humanCostUsd: number;
  /** humanCost - autoCost per period (positive = savings from going auto) */
  expectedSavingUsd: number;
  reason: string;
}

export interface OptimizedDial {
  perType: EconomicRecommendation[];
  totalExpectedSavingUsd: number;
}

function costOfAuto(inp: TypeCostInput, cfg: EconomicConfig): number {
  const fp = 1 - inp.cleanRate;
  const errorCost = cfg.errorBaseUsd + cfg.errorAmountShare * (inp.avgAmountUsd ?? 0);
  return inp.volume * fp * errorCost;
}
function costOfHuman(inp: TypeCostInput, cfg: EconomicConfig): number {
  const minuteCost = (cfg.perDecisionMinutes / 60) * cfg.hourlyValueUsd;
  const latency = cfg.avgWaitHours * (cfg.latencyRiskPerHourUsd[inp.domain] ?? 5);
  return inp.volume * (minuteCost + latency);
}

/** Solve the dial: recommend auto per type only when cheaper + within FP tolerance + ceiling allows. */
export function optimizeDial(
  inputs: TypeCostInput[],
  ceilingOf: (d: AdminDomain) => AutonomyTier,
  cfg: EconomicConfig = DEFAULT_ECONOMIC_CONFIG,
): OptimizedDial {
  const perType: EconomicRecommendation[] = inputs.map((inp) => {
    const fpRate = Math.round((1 - inp.cleanRate) * 1000) / 1000;
    const autoCost = Math.round(costOfAuto(inp, cfg));
    const humanCost = Math.round(costOfHuman(inp, cfg));
    const saving = humanCost - autoCost;
    const ceilingAllowsAuto = ceilingOf(inp.domain) === 'auto';

    let recommend: 'auto' | 'keep_human';
    let reason: string;
    if (!ceilingAllowsAuto) {
      recommend = 'keep_human';
      reason = `domain ceiling is not auto`;
    } else if (fpRate > cfg.maxFalsePositiveRate) {
      recommend = 'keep_human';
      reason = `fp ${(fpRate * 100).toFixed(1)}% > tolerance ${(cfg.maxFalsePositiveRate * 100).toFixed(1)}%`;
    } else if (saving > 0) {
      recommend = 'auto';
      reason = `auto saves $${saving}/period at ${(fpRate * 100).toFixed(1)}% fp`;
    } else {
      recommend = 'keep_human';
      reason = `auto not cheaper (saving $${saving})`;
    }

    return { domain: inp.domain, actionType: inp.actionType, recommend, fpRate, autoCostUsd: autoCost, humanCostUsd: humanCost, expectedSavingUsd: saving, reason };
  });

  const totalExpectedSavingUsd = perType
    .filter((r) => r.recommend === 'auto')
    .reduce((s, r) => s + r.expectedSavingUsd, 0);

  return { perType: perType.sort((a, b) => b.expectedSavingUsd - a.expectedSavingUsd), totalExpectedSavingUsd };
}
