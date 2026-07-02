/**
 * Portfolio-level objective — everything else optimizes locally; this steers the WHOLE plane
 * toward one business goal ("maximize autonomy at ≤ X risk", "minimize cost", "balance"). It
 * selects the dial from the Pareto frontier that maximizes the chosen objective subject to hard
 * constraints, so the plane pursues a goal instead of merely clearing a queue. Pure + zero-dep.
 */
import type { DialCandidate } from './paretoTuning.ts';

export type ObjectiveGoal = 'min_cost' | 'max_autonomy' | 'min_risk' | 'balanced';

export interface ObjectiveConstraints {
  maxCost?: number;
  maxRisk?: number;
  maxApproverLoad?: number;
  maxLatency?: number;
}

export interface PortfolioObjective {
  goal: ObjectiveGoal;
  constraints?: ObjectiveConstraints;
}

export interface ChosenConfig {
  chosen: DialCandidate | null;
  feasibleCount: number;
  objectiveValue: number | null;
  rationale: string;
}

function feasible(c: DialCandidate, k: ObjectiveConstraints = {}): boolean {
  const o = c.objectives;
  return (k.maxCost === undefined || o.cost <= k.maxCost) &&
    (k.maxRisk === undefined || o.risk <= k.maxRisk) &&
    (k.maxApproverLoad === undefined || o.approverLoad <= k.maxApproverLoad) &&
    (k.maxLatency === undefined || o.latency <= k.maxLatency);
}

/** Score a candidate for the goal (higher = better). */
function score(c: DialCandidate, goal: ObjectiveGoal): number {
  const o = c.objectives;
  switch (goal) {
    case 'min_cost': return -o.cost;
    case 'min_risk': return -o.risk;
    case 'max_autonomy': return c.autoTypes.length;
    case 'balanced': return -(o.cost + o.risk + o.approverLoad + o.latency);
  }
}

/** Select the best feasible dial for the objective. */
export function selectPortfolioConfig(candidates: DialCandidate[], objective: PortfolioObjective): ChosenConfig {
  const feasibleSet = candidates.filter((c) => feasible(c, objective.constraints));
  if (feasibleSet.length === 0) {
    return { chosen: null, feasibleCount: 0, objectiveValue: null, rationale: 'no candidate satisfies the constraints — relax a limit' };
  }
  const chosen = feasibleSet.reduce((best, c) => (score(c, objective.goal) > score(best, objective.goal) ? c : best));
  return {
    chosen,
    feasibleCount: feasibleSet.length,
    objectiveValue: Math.round(score(chosen, objective.goal) * 100) / 100,
    rationale: `${objective.goal}: chose fp-tolerance ${chosen.fpTolerance} (${chosen.autoTypes.length} auto types, cost $${chosen.objectives.cost}, risk $${chosen.objectives.risk}) among ${feasibleSet.length} feasible options`,
  };
}
