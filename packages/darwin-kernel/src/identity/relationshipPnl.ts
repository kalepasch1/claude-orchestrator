/**
 * Relationship P&L (new improvement #5) — combines an identity rollup (who is
 * connected) with metering usage records + data-coop rewards (what they consume
 * and earn) to produce lifetime value and cost-to-serve at the RELATIONSHIP level
 * (household / controlled-entity group) across all products. This is the single
 * number that tells you which cross-sell routes actually pay off — making the
 * flywheel self-optimizing.
 *
 * Pure. Keyed on subject ids that belong to a rollup's `members`.
 */
import type { Rollup } from './rollups.ts';
import { verifyUsageRecord, type UsageRecord } from '../orchestratorClient/metering.ts';
import type { RewardLedgerEntry, RewardCurrency } from '../dataCoop/dataCoop.ts';
import { toUsdCents, type RateTable, DEFAULT_RATES } from '../dataCoop/exchange.ts';
import type { CostModel } from '../orchestratorClient/economics.ts';

/** A usage record attributed to a subject (the member who triggered the call). */
export interface AttributedUsage {
  subject: string;
  record: UsageRecord;
}

export interface RelationshipPnl {
  root: string;
  members: string[];
  breadth: number; // distinct products touched
  /** gross revenue attributed to this relationship's calls (USD-cents) */
  revenueCents: number;
  /** cost to serve those calls (USD-cents) */
  costCents: number;
  /** rewards paid out to the relationship (USD-cents, fungible) */
  rewardsPaidCents: number;
  /** net contribution = revenue - cost - rewards */
  netContributionCents: number;
  /** simple LTV proxy: net contribution × breadth (multi-product stickiness) */
  ltvProxyCents: number;
}

function costOf(rec: UsageRecord, model: CostModel): number {
  const per = model.costPerUnitCents[rec.capabilityId] ?? model.fallbackCostPerUnitCents;
  return Math.round(per * rec.units);
}

export function relationshipPnl(params: {
  rollup: Rollup;
  usage: AttributedUsage[];
  rewards: { subject: string; entry: RewardLedgerEntry }[];
  costModel?: CostModel;
  rates?: RateTable;
}): RelationshipPnl {
  const members = new Set(params.rollup.members);
  const model = params.costModel ?? { costPerUnitCents: {}, fallbackCostPerUnitCents: 0 };
  const rates = params.rates ?? DEFAULT_RATES;

  let revenueCents = 0;
  let costCents = 0;
  for (const u of params.usage) {
    if (!members.has(u.subject)) continue;
    if (!verifyUsageRecord(u.record)) continue;
    revenueCents += u.record.amountCents;
    costCents += costOf(u.record, model);
  }

  let rewardsPaidCents = 0;
  for (const r of params.rewards) {
    if (!members.has(r.subject)) continue;
    rewardsPaidCents += toUsdCents(r.entry.amount, r.entry.currency as RewardCurrency, rates);
  }

  const netContributionCents = revenueCents - costCents - rewardsPaidCents;
  return {
    root: params.rollup.root,
    members: params.rollup.members,
    breadth: params.rollup.breadth,
    revenueCents,
    costCents,
    rewardsPaidCents,
    netContributionCents,
    ltvProxyCents: netContributionCents * Math.max(1, params.rollup.breadth),
  };
}
