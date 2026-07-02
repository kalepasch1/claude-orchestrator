/**
 * Predictive admin — forecast likely admin events BEFORE they fire, and pre-stage the
 * remediation as a co-pilot card so the fix is approved before the incident lands.
 *
 * Pure + zero-dep. Per (product, domain, category) stream we model inter-arrival with
 * an EWMA and score imminence from recency + volume. Deterministic and testable; a
 * product can swap in a richer model without changing the interface. FAIL SAFE: a
 * forecast is only ever a co-pilot PROPOSAL, never an auto action.
 */
import type { AdminDomain, AdminEvent } from './types.ts';

export interface ForecastInput {
  product: string;
  domain: AdminDomain;
  category: string;
  /** ISO timestamps of past occurrences of this stream, ascending */
  occurrences: string[];
}

export interface ForecastResult {
  product: string;
  domain: AdminDomain;
  category: string;
  /** 0..1 likelihood of a recurrence within the horizon */
  risk: number;
  /** predicted next occurrence (ISO) or null if not enough history */
  etaIso: string | null;
  meanIntervalMs: number | null;
  reason: string;
}

const HALF_LIFE = 5; // EWMA weighting over the most recent intervals

/** EWMA of inter-arrival gaps → mean interval → risk from recency vs. that interval. */
export function forecastStream(input: ForecastInput, nowIso: string): ForecastResult {
  const base = { product: input.product, domain: input.domain, category: input.category };
  const ts = [...input.occurrences].map((t) => Date.parse(t)).filter((n) => Number.isFinite(n)).sort((a, b) => a - b);
  if (ts.length < 3) {
    return { ...base, risk: 0, etaIso: null, meanIntervalMs: null, reason: 'insufficient_history' };
  }
  const gaps: number[] = [];
  for (let i = 1; i < ts.length; i++) gaps.push(ts[i]! - ts[i - 1]!);

  // EWMA over gaps (recent gaps weighted more).
  const alpha = 1 - Math.pow(0.5, 1 / HALF_LIFE);
  let ewma = gaps[0]!;
  for (let i = 1; i < gaps.length; i++) ewma = alpha * gaps[i]! + (1 - alpha) * ewma;

  const now = Date.parse(nowIso);
  const sinceLast = now - ts[ts.length - 1]!;
  const etaIso = new Date(ts[ts.length - 1]! + ewma).toISOString();

  // Risk rises as elapsed time approaches (and passes) the expected interval.
  const ratio = ewma > 0 ? sinceLast / ewma : 0;
  const risk = Math.max(0, Math.min(1, ratio)); // 0 just happened → ~1 overdue
  return {
    ...base,
    risk: Math.round(risk * 100) / 100,
    etaIso,
    meanIntervalMs: Math.round(ewma),
    reason: ratio >= 1 ? 'overdue_recurrence' : 'approaching_expected_interval',
  };
}

/** Build streams from a flat event log, then forecast each. */
export function forecastFromEvents(events: AdminEvent[], nowIso: string, minRisk = 0.5): ForecastResult[] {
  const streams = new Map<string, ForecastInput>();
  for (const e of events) {
    const key = `${e.product}::${e.domain}::${e.category}`;
    const s = streams.get(key) ?? { product: e.product, domain: e.domain, category: e.category, occurrences: [] };
    s.occurrences.push(e.at);
    streams.set(key, s);
  }
  return [...streams.values()]
    .map((s) => forecastStream(s, nowIso))
    .filter((r) => r.risk >= minRisk)
    .sort((a, b) => b.risk - a.risk);
}
