/**
 * The north-star: "answered-from-plane rate" — the single number proving the 5/95 is
 * trending toward 2/98 across the whole portfolio. It's the share of admin decisions
 * the plane resolved WITHOUT a human, weighted by volume, plus the trend over time and
 * a by-domain breakdown. Pure + zero-dep.
 */
import type { AdminDomain } from './types.ts';

/** One routed action's summary (from fleet_admin_actions). */
export interface RoutedActionSummary {
  domain: AdminDomain;
  decision: 'allow' | 'escalate' | 'deny';
  tier: 'auto' | 'co_pilot' | 'human';
  at: string;
}

export interface KpiBreakdown {
  domain: AdminDomain;
  total: number;
  autonomous: number;
  rate: number;
}

export interface NorthStar {
  /** autonomous (auto-run) / (auto-run + escalated) — denials excluded */
  answeredFromPlaneRate: number;
  totalDecisions: number;
  autonomous: number;
  escalated: number;
  denied: number;
  byDomain: KpiBreakdown[];
  /** period-over-period trend on the rate (this window vs. the previous window) */
  trend: { current: number; previous: number; deltaPct: number } | null;
}

function rateOf(actions: RoutedActionSummary[]): { rate: number; auto: number; esc: number; denied: number } {
  let auto = 0;
  let esc = 0;
  let denied = 0;
  for (const a of actions) {
    if (a.decision === 'deny') denied++;
    else if (a.tier === 'auto') auto++;
    else esc++;
  }
  const denom = auto + esc;
  return { rate: denom ? auto / denom : 0, auto, esc, denied };
}

/**
 * Compute the north-star over a set of routed actions. If `splitAtIso` is given, the
 * trend compares actions at/after it (current) vs. before it (previous).
 */
export function computeNorthStar(actions: RoutedActionSummary[], splitAtIso?: string): NorthStar {
  const overall = rateOf(actions);

  const domains = new Map<AdminDomain, RoutedActionSummary[]>();
  for (const a of actions) {
    const arr = domains.get(a.domain) ?? [];
    arr.push(a);
    domains.set(a.domain, arr);
  }
  const byDomain: KpiBreakdown[] = [...domains.entries()].map(([domain, arr]) => {
    const r = rateOf(arr);
    return { domain, total: r.auto + r.esc, autonomous: r.auto, rate: Math.round(r.rate * 100) / 100 };
  });

  let trend: NorthStar['trend'] = null;
  if (splitAtIso) {
    const split = Date.parse(splitAtIso);
    const prev = rateOf(actions.filter((a) => Date.parse(a.at) < split));
    const cur = rateOf(actions.filter((a) => Date.parse(a.at) >= split));
    trend = {
      current: Math.round(cur.rate * 100) / 100,
      previous: Math.round(prev.rate * 100) / 100,
      deltaPct: Math.round((cur.rate - prev.rate) * 100),
    };
  }

  return {
    answeredFromPlaneRate: Math.round(overall.rate * 100) / 100,
    totalDecisions: actions.length,
    autonomous: overall.auto,
    escalated: overall.esc,
    denied: overall.denied,
    byDomain: byDomain.sort((a, b) => b.total - a.total),
    trend,
  };
}
