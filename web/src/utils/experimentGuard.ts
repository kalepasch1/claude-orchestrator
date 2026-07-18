/**
 * experimentGuard.ts — Guard for autonomous experimentation.
 * Prevents experiments from exceeding resource or risk budgets.
 */
export const EXPERIMENT_GUARD_ENABLED = process.env.EXPERIMENT_GUARD_ENABLED === '1'

export interface ExperimentBudget {
  maxConcurrent: number
  maxDailyRuns: number
  maxCostUsd: number
}

export const DEFAULT_BUDGET: ExperimentBudget = {
  maxConcurrent: 3,
  maxDailyRuns: 20,
  maxCostUsd: 50,
}

export function canRunExperiment(
  currentConcurrent: number,
  dailyRuns: number,
  spentUsd: number,
  budget: ExperimentBudget = DEFAULT_BUDGET,
): { allowed: boolean; reason: string } {
  if (currentConcurrent >= budget.maxConcurrent) return { allowed: false, reason: 'Max concurrent reached' }
  if (dailyRuns >= budget.maxDailyRuns) return { allowed: false, reason: 'Daily run limit reached' }
  if (spentUsd >= budget.maxCostUsd) return { allowed: false, reason: 'Cost budget exhausted' }
  return { allowed: true, reason: 'Within budget' }
}
