/**
 * Causal incident model — correlation groups events that co-occur; this learns a CAUSAL
 * graph from the log so the plane distinguishes "these share a cause" from "this one CAUSED
 * that one." Then propagation targets the true upstream fix and blast modelling follows real
 * downstream cascades instead of concentration heuristics. Pure + zero-dep.
 *
 * Method (transparent, not a black box): for ordered category pairs A→B within a window,
 * lift = P(B soon after A) / P(B baseline); an edge is kept when lift and support clear
 * thresholds AND A reliably precedes B.
 */
import type { AdminEvent } from './types.ts';

export interface CausalEdge {
  from: string; // category A (the cause)
  to: string; // category B (the effect)
  lift: number; // P(B|A within window) / P(B)
  support: number; // # of A→B co-occurrences observed
  confidence: number; // P(B|A within window)
}

export interface CausalConfig {
  windowMs: number;
  minSupport: number;
  minLift: number;
}
export const DEFAULT_CAUSAL_CONFIG: CausalConfig = { windowMs: 30 * 60 * 1000, minSupport: 3, minLift: 1.5 };

/** Learn directed causal edges between event categories from the event stream. */
export function learnCausalGraph(events: AdminEvent[], cfg: CausalConfig = DEFAULT_CAUSAL_CONFIG): CausalEdge[] {
  const sorted = [...events].sort((a, b) => Date.parse(a.at) - Date.parse(b.at));
  const total = sorted.length || 1;
  const countCat = new Map<string, number>();
  for (const e of sorted) countCat.set(e.category, (countCat.get(e.category) ?? 0) + 1);

  // Co-occurrence: for each A, count distinct later B within window.
  const coAB = new Map<string, number>(); // `A>B` → count
  const countA = new Map<string, number>();
  for (let i = 0; i < sorted.length; i++) {
    const a = sorted[i]!;
    countA.set(a.category, (countA.get(a.category) ?? 0) + 1);
    const at = Date.parse(a.at);
    const seen = new Set<string>();
    for (let j = i + 1; j < sorted.length; j++) {
      const b = sorted[j]!;
      if (Date.parse(b.at) - at > cfg.windowMs) break;
      if (b.category === a.category || seen.has(b.category)) continue;
      seen.add(b.category);
      const key = `${a.category}>${b.category}`;
      coAB.set(key, (coAB.get(key) ?? 0) + 1);
    }
  }

  const edges: CausalEdge[] = [];
  for (const [key, support] of coAB) {
    if (support < cfg.minSupport) continue;
    const [from, to] = key.split('>') as [string, string];
    const pB = (countCat.get(to) ?? 0) / total;
    const pBgivenA = support / (countA.get(from) ?? 1);
    const lift = pB > 0 ? pBgivenA / pB : 0;
    if (lift < cfg.minLift) continue;
    // Keep only the dominant direction if both A→B and B→A cleared thresholds.
    const reverse = coAB.get(`${to}>${from}`) ?? 0;
    if (reverse > support) continue;
    edges.push({ from, to, lift: Math.round(lift * 100) / 100, support, confidence: Math.round(pBgivenA * 100) / 100 });
  }
  return edges.sort((a, b) => b.lift - a.lift);
}

/**
 * Given the events of one incident + a causal graph, return the ROOT-CAUSE event: the
 * category that causes others in the incident but is itself uncaused (topological source),
 * tie-broken by earliest timestamp.
 */
export function rootCause(incidentEvents: AdminEvent[], graph: CausalEdge[]): AdminEvent | null {
  if (incidentEvents.length === 0) return null;
  const cats = new Set<string>(incidentEvents.map((e) => e.category as string));
  const inDegree = new Map<string, number>();
  for (const c of cats) inDegree.set(c, 0);
  for (const e of graph) {
    if (cats.has(e.from) && cats.has(e.to)) inDegree.set(e.to, (inDegree.get(e.to) ?? 0) + 1);
  }
  // Prefer a category that causes ≥1 other in the incident and has no incoming edge.
  const sources = [...cats].filter((c) => (inDegree.get(c) ?? 0) === 0 && graph.some((e) => e.from === c && cats.has(e.to)));
  const chosenCats = sources.length ? sources : [...cats];
  const candidates = incidentEvents
    .filter((e) => chosenCats.includes(e.category))
    .sort((a, b) => Date.parse(a.at) - Date.parse(b.at));
  return candidates[0] ?? null;
}
