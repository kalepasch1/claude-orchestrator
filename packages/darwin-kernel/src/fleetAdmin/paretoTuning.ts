/**
 * Multi-objective Pareto tuning — the economic autopilot minimizes ONE cost function; this
 * surfaces the whole trade-off frontier across four competing objectives (cost, risk
 * exposure, approver load, latency) so you pick the POINT on the curve rather than trusting
 * one weighting. Points our `pareto` app's competency inward at our own operations.
 * Pure + zero-dep.
 */
import type { AdminDomain, AutonomyTier } from './types.ts';
import type { TypeCostInput, EconomicConfig } from './economicAutopilot.ts';
import { DEFAULT_ECONOMIC_CONFIG } from './economicAutopilot.ts';

/** All objectives are "lower is better." */
export interface ObjectiveVector {
  cost: number; // total $ (auto errors + human handling)
  risk: number; // $ exposure auto-run unattended
  approverLoad: number; // approver-minutes required
  latency: number; // $ latency-risk from decisions waiting on a human
}

export interface DialCandidate {
  id: string;
  /** false-positive tolerance used to derive this candidate's auto set */
  fpTolerance: number;
  autoTypes: string[]; // `${domain}::${type}` chosen for auto
  objectives: ObjectiveVector;
}

function scoreCandidate(
  inputs: TypeCostInput[],
  autoSet: Set<string>,
  cfg: EconomicConfig,
): ObjectiveVector {
  let cost = 0;
  let risk = 0;
  let approverLoad = 0;
  let latency = 0;
  const minuteCost = (cfg.perDecisionMinutes / 60) * cfg.hourlyValueUsd;
  for (const inp of inputs) {
    const key = `${inp.domain}::${inp.actionType}`;
    const fp = 1 - inp.cleanRate;
    if (autoSet.has(key)) {
      const errCost = cfg.errorBaseUsd + cfg.errorAmountShare * (inp.avgAmountUsd ?? 0);
      cost += inp.volume * fp * errCost;
      risk += inp.volume * (inp.avgAmountUsd ?? 0);
    } else {
      const lat = cfg.avgWaitHours * (cfg.latencyRiskPerHourUsd[inp.domain] ?? 5);
      cost += inp.volume * (minuteCost + lat);
      approverLoad += inp.volume * cfg.perDecisionMinutes;
      latency += inp.volume * lat;
    }
  }
  return { cost: Math.round(cost), risk: Math.round(risk), approverLoad: Math.round(approverLoad), latency: Math.round(latency) };
}

/** Sweep false-positive tolerance to generate candidate dials. */
export function generateDialCandidates(
  inputs: TypeCostInput[],
  ceilingOf: (d: AdminDomain) => AutonomyTier,
  fpGrid: number[] = [0, 0.005, 0.01, 0.02, 0.05, 0.1],
  cfg: EconomicConfig = DEFAULT_ECONOMIC_CONFIG,
): DialCandidate[] {
  return fpGrid.map((t, i) => {
    const autoTypes = inputs
      .filter((inp) => ceilingOf(inp.domain) === 'auto' && 1 - inp.cleanRate <= t)
      .map((inp) => `${inp.domain}::${inp.actionType}`);
    const autoSet = new Set(autoTypes);
    return { id: `cand_${i}_fp${t}`, fpTolerance: t, autoTypes, objectives: scoreCandidate(inputs, autoSet, cfg) };
  });
}

function dominates(a: ObjectiveVector, b: ObjectiveVector): boolean {
  const keys: (keyof ObjectiveVector)[] = ['cost', 'risk', 'approverLoad', 'latency'];
  const noWorse = keys.every((k) => a[k] <= b[k]);
  const strictlyBetter = keys.some((k) => a[k] < b[k]);
  return noWorse && strictlyBetter;
}

/** Non-dominated set: no other candidate is better on every objective. */
export function paretoFrontier(candidates: DialCandidate[]): { frontier: DialCandidate[]; dominated: DialCandidate[] } {
  const frontier: DialCandidate[] = [];
  const dominated: DialCandidate[] = [];
  for (const c of candidates) {
    if (candidates.some((o) => o.id !== c.id && dominates(o.objectives, c.objectives))) dominated.push(c);
    else frontier.push(c);
  }
  return { frontier, dominated };
}
