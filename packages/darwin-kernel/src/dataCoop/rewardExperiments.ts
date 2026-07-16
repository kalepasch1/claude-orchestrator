/**
 * A/B reward-experiment harness — moves users between products via the
 * exchange rate table, measured in one normalized currency, with
 * significance tracking.
 *
 * Cross-product effects flow only through darwin_* tables (the exchange rate
 * table). Kernel is local — import directly. Additive.
 */
import type { RewardCurrency, RewardLedgerEntry } from './dataCoop.ts';
import { toUsdCents, type RateTable, DEFAULT_RATES } from './exchange.ts';

/** An experiment variant (arm). */
export interface ExperimentArm {
  name: string;
  /** Source product currency the user earns in. */
  earnCurrency: RewardCurrency;
  /** Target product currency the reward is paid in. */
  redeemCurrency: RewardCurrency;
  /** Reward amount in earnCurrency per completed action. */
  rewardPerAction: number;
}

/** A user assignment to an experiment arm. */
export interface Assignment {
  subject: string;
  arm: string;
  actionsCompleted: number;
}

/** Per-arm aggregate result. */
export interface ArmResult {
  arm: string;
  n: number;
  totalActions: number;
  meanActions: number;
  /** Total reward value in normalized USD-cents. */
  totalNormalizedCents: number;
  /** Mean normalized cents per subject. */
  meanNormalizedCents: number;
  ledgerEntries: RewardLedgerEntry[];
}

/** Full experiment result with significance metric. */
export interface ExperimentResult {
  experimentId: string;
  arms: ArmResult[];
  /** Welch's t-test p-value between first two arms (NaN if < 2 arms or insufficient data). */
  significance: number;
}

/**
 * Run one experiment end-to-end: compute normalized-currency deltas per arm
 * and a significance metric (Welch's t-test between first two arms).
 */
export function runExperiment(params: {
  experimentId: string;
  arms: ExperimentArm[];
  assignments: Assignment[];
  rates?: RateTable;
}): ExperimentResult {
  const rates = params.rates ?? DEFAULT_RATES;
  const armMap = new Map(params.arms.map((a) => [a.name, a]));
  const armSubjects = new Map<string, Assignment[]>();

  for (const a of params.assignments) {
    const list = armSubjects.get(a.arm) ?? [];
    list.push(a);
    armSubjects.set(a.arm, list);
  }

  const armResults: ArmResult[] = params.arms.map((armDef) => {
    const subjects = armSubjects.get(armDef.name) ?? [];
    const ledgerEntries: RewardLedgerEntry[] = [];
    let totalActions = 0;
    let totalNormalizedCents = 0;

    for (const subj of subjects) {
      const earnedNative = subj.actionsCompleted * armDef.rewardPerAction;
      const normalizedCents = toUsdCents(earnedNative, armDef.earnCurrency, rates);
      totalActions += subj.actionsCompleted;
      totalNormalizedCents += normalizedCents;
      ledgerEntries.push({
        subject: subj.subject,
        currency: armDef.redeemCurrency,
        amount: earnedNative * (rates[armDef.earnCurrency] / rates[armDef.redeemCurrency]),
        reason: `experiment:${params.experimentId}:${armDef.name}`,
      });
    }

    return {
      arm: armDef.name,
      n: subjects.length,
      totalActions,
      meanActions: subjects.length > 0 ? totalActions / subjects.length : 0,
      totalNormalizedCents,
      meanNormalizedCents: subjects.length > 0 ? totalNormalizedCents / subjects.length : 0,
      ledgerEntries,
    };
  });

  const significance = computeSignificance(armResults, params.assignments, armMap, rates);
  return { experimentId: params.experimentId, arms: armResults, significance };
}

/** Welch's t-test between first two arms on normalized cents per subject. */
function computeSignificance(
  armResults: ArmResult[],
  assignments: Assignment[],
  armMap: Map<string, ExperimentArm>,
  rates: RateTable,
): number {
  if (armResults.length < 2) return NaN;
  const [a, b] = [armResults[0]!, armResults[1]!];
  if (a.n < 2 || b.n < 2) return NaN;

  const valuesA = getNormalizedValues(assignments, a.arm, armMap, rates);
  const valuesB = getNormalizedValues(assignments, b.arm, armMap, rates);

  const meanA = mean(valuesA);
  const meanB = mean(valuesB);
  const varA = variance(valuesA, meanA);
  const varB = variance(valuesB, meanB);

  const se = Math.sqrt(varA / valuesA.length + varB / valuesB.length);
  if (se === 0) return valuesA.every((v, i) => v === valuesB[i]) ? 1.0 : 0.0;
  const t = Math.abs(meanA - meanB) / se;
  // Approximate two-tailed p-value using normal distribution for large samples
  return 2 * (1 - normalCdf(t));
}

function getNormalizedValues(
  assignments: Assignment[],
  armName: string,
  armMap: Map<string, ExperimentArm>,
  rates: RateTable,
): number[] {
  const armDef = armMap.get(armName)!;
  return assignments
    .filter((a) => a.arm === armName)
    .map((a) => toUsdCents(a.actionsCompleted * armDef.rewardPerAction, armDef.earnCurrency, rates));
}

function mean(values: number[]): number {
  return values.reduce((s, v) => s + v, 0) / values.length;
}

function variance(values: number[], m: number): number {
  return values.reduce((s, v) => s + (v - m) ** 2, 0) / (values.length - 1);
}

/** Standard normal CDF approximation (Abramowitz & Stegun 26.2.17). */
function normalCdf(x: number): number {
  const a1 = 0.254829592, a2 = -0.284496736, a3 = 1.421413741, a4 = -1.453152027, a5 = 1.061405429;
  const p = 0.3275911;
  const sign = x < 0 ? -1 : 1;
  x = Math.abs(x) / Math.SQRT2;
  const t = 1 / (1 + p * x);
  const y = 1 - ((((a5 * t + a4) * t + a3) * t + a2) * t + a1) * t * Math.exp(-x * x);
  return 0.5 * (1 + sign * y);
}
