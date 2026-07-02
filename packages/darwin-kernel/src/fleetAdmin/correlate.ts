/**
 * Cross-app incident correlation — the unique payoff of ONE control plane seeing every
 * app at once. A Supabase blip in apparently and a payment failure in pareto that share
 * a root cause become ONE incident, not four disconnected cards. No per-app tool can do
 * this. Pure + zero-dep (union-find over shared correlation signals within a time window).
 */
import type { AdminEvent } from './types.ts';

export interface Incident {
  id: string;
  events: string[]; // event ids
  products: string[];
  domains: string[];
  /** the shared signal(s) that tied these events together */
  rootCauseSignals: string[];
  severityMax: number;
  fromIso: string;
  toIso: string;
  summary: string;
}

/** Signals that, when shared by two events close in time, imply a common cause. */
export function correlationKeys(e: AdminEvent): string[] {
  const keys: string[] = [];
  const d = e.details ?? {};
  for (const k of ['signal', 'provider', 'errorSignature', 'dependency', 'region', 'incidentKey']) {
    const v = (d as Record<string, unknown>)[k];
    if (typeof v === 'string' && v) keys.push(`${k}:${v}`);
  }
  // Same subject touched across apps is itself a correlation signal.
  if (e.subjectId) keys.push(`subject:${e.subjectId}`);
  return keys;
}

class UnionFind {
  private parent = new Map<string, string>();
  find(x: string): string {
    if (!this.parent.has(x)) this.parent.set(x, x);
    let root = x;
    while (this.parent.get(root) !== root) root = this.parent.get(root)!;
    this.parent.set(x, root);
    return root;
  }
  union(a: string, b: string): void {
    const ra = this.find(a);
    const rb = this.find(b);
    if (ra !== rb) this.parent.set(ra, rb);
  }
}

/**
 * Correlate events into incidents. Two events are linked if they share a correlation
 * key AND occur within `windowMs` of each other. Singletons are not incidents.
 */
export function correlateEvents(events: AdminEvent[], windowMs = 15 * 60 * 1000): Incident[] {
  const uf = new UnionFind();
  const byKey = new Map<string, { id: string; at: number }[]>();

  for (const e of events) {
    uf.find(e.id); // ensure present
    const at = Date.parse(e.at);
    for (const key of correlationKeys(e)) {
      const arr = byKey.get(key) ?? [];
      for (const prior of arr) {
        if (Math.abs(prior.at - at) <= windowMs) uf.union(prior.id, e.id);
      }
      arr.push({ id: e.id, at });
      byKey.set(key, arr);
    }
  }

  const byId = new Map(events.map((e) => [e.id, e]));
  const groups = new Map<string, string[]>();
  for (const e of events) {
    const root = uf.find(e.id);
    const g = groups.get(root) ?? [];
    g.push(e.id);
    groups.set(root, g);
  }

  const incidents: Incident[] = [];
  for (const [root, ids] of groups) {
    if (ids.length < 2) continue; // an incident needs correlated events
    const evs = ids.map((id) => byId.get(id)!).sort((a, b) => Date.parse(a.at) - Date.parse(b.at));
    const products = [...new Set(evs.map((e) => e.product))];
    const domains = [...new Set(evs.map((e) => e.domain))];
    const signals = [...new Set(evs.flatMap(correlationKeys))];
    const shared = signals.filter((s) => evs.filter((e) => correlationKeys(e).includes(s)).length >= 2);
    incidents.push({
      id: `incident_${root}`,
      events: ids,
      products,
      domains,
      rootCauseSignals: shared,
      severityMax: Math.max(...evs.map((e) => e.severity)),
      fromIso: evs[0]!.at,
      toIso: evs[evs.length - 1]!.at,
      summary: `${evs.length} correlated events across ${products.join(', ')} — shared ${shared.join(', ') || 'timing'}`,
    });
  }
  return incidents.sort((a, b) => b.severityMax - a.severityMax);
}
