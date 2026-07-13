/**
 * CADE loop-closure primitives — living-determination propagation, dispute→instrument
 * gap mining, and the certified-determination service tier. All pure.
 */

export interface StoredDetermination {
  id: string;
  citedAuthorityIds: string[];
  /** perpetual leg bound to this determination, if any. */
  legId?: string;
}

export interface PropagationResult {
  /** determinations whose basis cited the changed authority → must re-run. */
  affectedDeterminationIds: string[];
  /** perpetual legs of affected determinations → must re-strike. */
  legsToRestrike: string[];
}

/**
 * #3 Living loop: when a monitored authority changes (Legal Radar / regulator feed),
 * compute which stored determinations must re-run and which perpetual legs re-strike.
 * Pure graph pass; the re-run + re-strike + settlement are the app's job.
 */
export function propagateAuthorityChange(
  determinations: StoredDetermination[],
  changedAuthorityIds: string[],
): PropagationResult {
  const changed = new Set(changedAuthorityIds);
  const affected = determinations.filter((d) => d.citedAuthorityIds.some((a) => changed.has(a)));
  return {
    affectedDeterminationIds: affected.map((d) => d.id),
    legsToRestrike: affected.map((d) => d.legId).filter((x): x is string => !!x),
  };
}

export interface LegalEventLoss {
  eventType: string;
  lossUsd: number;
}
export interface InstrumentCoverage {
  coversEventType: string;
}
export interface InstrumentGap {
  eventType: string;
  unhedgedLossUsd: number;
  /** a candidate parametric instrument spec seed for the foundry. */
  candidate: { kind: 'parametric_event'; trigger: string; suggestedNotionalUsd: number };
}

/**
 * #9 Dispute→instrument discovery: event types with realized losses but no covering
 * instrument become ranked candidate parametric instruments for the foundry.
 */
export function mineInstrumentGaps(
  losses: LegalEventLoss[],
  instruments: InstrumentCoverage[],
): InstrumentGap[] {
  const covered = new Set(instruments.map((i) => i.coversEventType));
  const totals = new Map<string, number>();
  for (const l of losses) {
    if (covered.has(l.eventType)) continue;
    totals.set(l.eventType, (totals.get(l.eventType) ?? 0) + Math.max(0, l.lossUsd));
  }
  return [...totals.entries()]
    .filter(([, v]) => v > 0)
    .sort((a, b) => b[1] - a[1])
    .map(([eventType, unhedgedLossUsd]) => ({
      eventType,
      unhedgedLossUsd,
      candidate: {
        kind: 'parametric_event' as const,
        trigger: `observed:${eventType}`,
        suggestedNotionalUsd: unhedgedLossUsd,
      },
    }));
}

export type ServiceTier = 'oracle' | 'panel' | 'certified';

export interface ServicePrice {
  tier: ServiceTier;
  priceUsd: number;
  includesCertificate: boolean;
}

/**
 * #10 Certified-determination RaaS pricing: meter by tier × difficulty; the certified
 * tier returns the signed optimality certificate. Calc-only metering — never custody,
 * never an order.
 */
export function priceDeterminationService(
  difficulty: number,
  tier: ServiceTier,
  base: { oracle?: number; panel?: number; certified?: number } = {},
): ServicePrice {
  const d = Math.max(0, Math.min(1, difficulty));
  const table = { oracle: base.oracle ?? 1, panel: base.panel ?? 25, certified: base.certified ?? 100 };
  const priceUsd = table[tier] * (1 + d);
  return { tier, priceUsd, includesCertificate: tier === 'certified' };
}
