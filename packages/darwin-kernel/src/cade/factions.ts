/**
 * Emergent factions + convergence.
 *
 * Factions are not pre-assigned: we cluster argument embeddings (greedy cosine
 * threshold) so agreement-on-a-basis emerges, and factions can MERGE into evolved
 * syntheses (the winner can be a position nobody held at the start). Convergence is
 * measured (Jensen–Shannon divergence between round distributions) plus a jackknife
 * robustness check (the lead must survive dropping any single source).
 */
import { centroid, cosine } from './vectors.ts';
import type { Faction, PersonaPosition } from './types.ts';

export function clusterFactions(
  positions: PersonaPosition[],
  reliabilityOf: (personaId: string) => number,
  threshold = 0.6,
): Faction[] {
  const factions: Faction[] = [];
  for (const pos of positions) {
    let placed = false;
    for (const f of factions) {
      if (cosine(pos.embedding, f.centroid) >= threshold) {
        f.memberIds.push(pos.personaId);
        f.support += pos.confidence * reliabilityOf(pos.personaId);
        f.centroid = centroid(
          f.memberIds.map((id) => positions.find((p) => p.personaId === id)?.embedding ?? []),
        );
        placed = true;
        break;
      }
    }
    if (!placed) {
      factions.push({
        id: `f${factions.length + 1}`,
        memberIds: [pos.personaId],
        centroid: pos.embedding,
        support: pos.confidence * reliabilityOf(pos.personaId),
        positionSummary: pos.text.slice(0, 280),
      });
    }
  }
  return factions.sort((a, b) => b.support - a.support);
}

/** Support-normalized distribution over factions, aligned to a reference set. */
export function factionDistribution(factions: Faction[]): number[] {
  const total = factions.reduce((s, f) => s + f.support, 0) || 1;
  return factions.map((f) => f.support / total);
}

/** Jensen–Shannon divergence between two distributions (auto-padded/aligned). */
export function jsDivergence(p: number[], q: number[]): number {
  const n = Math.max(p.length, q.length);
  const P = pad(p, n);
  const Q = pad(q, n);
  const M = P.map((x, i) => (x + (Q[i] ?? 0)) / 2);
  return 0.5 * kl(P, M) + 0.5 * kl(Q, M);
}

function pad(a: number[], n: number): number[] {
  const out = a.slice(0, n);
  while (out.length < n) out.push(0);
  const s = out.reduce((x, y) => x + y, 0) || 1;
  return out.map((x) => x / s);
}

function kl(a: number[], b: number[]): number {
  let s = 0;
  for (let i = 0; i < a.length; i++) {
    const ai = a[i] ?? 0;
    const bi = b[i] ?? 0;
    if (ai > 0 && bi > 0) s += ai * Math.log2(ai / bi);
  }
  return s;
}

/**
 * Jackknife robustness: drop each persona once, re-cluster, and confirm the lead
 * faction's position survives (its centroid stays the top-supported cluster).
 */
export function jackknifeRobust(
  positions: PersonaPosition[],
  reliabilityOf: (id: string) => number,
  threshold = 0.6,
): { robust: boolean; leadCentroid: number[] } {
  const full = clusterFactions(positions, reliabilityOf, threshold);
  const lead = full[0];
  if (!lead) return { robust: false, leadCentroid: [] };
  if (positions.length <= 2) return { robust: true, leadCentroid: lead.centroid };
  for (let i = 0; i < positions.length; i++) {
    const dropped = positions.filter((_, j) => j !== i);
    const re = clusterFactions(dropped, reliabilityOf, threshold);
    const newLead = re[0];
    if (!newLead || cosine(newLead.centroid, lead.centroid) < threshold) {
      return { robust: false, leadCentroid: lead.centroid };
    }
  }
  return { robust: true, leadCentroid: lead.centroid };
}

export function hasConverged(prev: number[], cur: number[], epsilon: number): boolean {
  return jsDivergence(prev, cur) <= epsilon;
}

/** Propose an evolved synthesis seed from two factions (text-level; the product's
 *  invoker fleshes it out into a real argument). */
export function synthesisSeed(a: Faction, b: Faction): { summary: string; evolvedFrom: string[] } {
  return {
    summary: `Synthesis of ${a.id}+${b.id}: ${a.positionSummary} — reconciled with — ${b.positionSummary}`,
    evolvedFrom: [a.id, b.id],
  };
}
