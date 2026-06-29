/**
 * Unit economics ledger (new improvement #1) — rolls signed usage records into a
 * per-capability and per-product gross-margin view. Because every cross-product
 * call is already a signed UsageRecord (revenue) and we attach a cost model, true
 * unit economics fall out for free: which capability is most consumed, what it
 * actually costs to serve, and the margin on the internal/external API economy.
 *
 * Pure. Tampered usage records are excluded (they never verify).
 */
import type { ProductId } from '../types.ts';
import { verifyUsageRecord, type UsageRecord } from './metering.ts';

export interface CostModel {
  /** owner-side cost in USD-cents per unit served, by capability id */
  costPerUnitCents: Record<string, number>;
  fallbackCostPerUnitCents: number;
}

export const DEFAULT_COST_MODEL: CostModel = { costPerUnitCents: {}, fallbackCostPerUnitCents: 0 };

export interface CapabilityEconomics {
  capabilityId: string;
  owner: ProductId;
  calls: number;
  units: number;
  revenueCents: number;
  costCents: number;
  marginCents: number;
  marginPct: number; // 0..1 (revenue 0 => 0)
  avgLatencyMs: number;
}

export interface ProductEconomics {
  product: ProductId;
  /** earned as a capability owner (payee) */
  revenueCents: number;
  costCents: number;
  marginCents: number;
  /** spent as a caller (consuming others' capabilities) */
  spendCents: number;
  /** net = revenue - spend (cross-product transfer P&L) */
  netCents: number;
}

function costFor(capabilityId: string, units: number, model: CostModel): number {
  const per = model.costPerUnitCents[capabilityId] ?? model.fallbackCostPerUnitCents;
  return Math.round(per * units);
}

/** Per-capability gross margin. */
export function capabilityEconomics(
  records: UsageRecord[],
  model: CostModel = DEFAULT_COST_MODEL,
): CapabilityEconomics[] {
  const acc = new Map<string, CapabilityEconomics & { latencySum: number }>();
  for (const r of records) {
    if (!verifyUsageRecord(r)) continue;
    const e =
      acc.get(r.capabilityId) ??
      {
        capabilityId: r.capabilityId,
        owner: r.owner,
        calls: 0,
        units: 0,
        revenueCents: 0,
        costCents: 0,
        marginCents: 0,
        marginPct: 0,
        avgLatencyMs: 0,
        latencySum: 0,
      };
    e.calls += 1;
    e.units += r.units;
    e.revenueCents += r.amountCents;
    e.costCents += costFor(r.capabilityId, r.units, model);
    e.latencySum += r.latencyMs;
    acc.set(r.capabilityId, e);
  }
  return [...acc.values()]
    .map((e) => {
      e.marginCents = e.revenueCents - e.costCents;
      e.marginPct = e.revenueCents > 0 ? e.marginCents / e.revenueCents : 0;
      e.avgLatencyMs = e.calls > 0 ? e.latencySum / e.calls : 0;
      const { latencySum: _l, ...rest } = e;
      return rest;
    })
    .sort((a, b) => b.marginCents - a.marginCents);
}

/** Per-product P&L: revenue as owner, spend as caller, net transfer P&L. */
export function productEconomics(
  records: UsageRecord[],
  model: CostModel = DEFAULT_COST_MODEL,
): ProductEconomics[] {
  const acc = new Map<ProductId, ProductEconomics>();
  const ensure = (p: ProductId) =>
    acc.get(p) ?? { product: p, revenueCents: 0, costCents: 0, marginCents: 0, spendCents: 0, netCents: 0 };
  for (const r of records) {
    if (!verifyUsageRecord(r)) continue;
    const owner = ensure(r.owner);
    owner.revenueCents += r.amountCents;
    owner.costCents += costFor(r.capabilityId, r.units, model);
    acc.set(r.owner, owner);
    const caller = ensure(r.caller);
    caller.spendCents += r.amountCents;
    acc.set(r.caller, caller);
  }
  return [...acc.values()]
    .map((p) => {
      p.marginCents = p.revenueCents - p.costCents;
      p.netCents = p.revenueCents - p.spendCents;
      return p;
    })
    .sort((a, b) => b.netCents - a.netCents);
}
