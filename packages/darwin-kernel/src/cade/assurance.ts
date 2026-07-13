/**
 * CADE assurance primitives — the L0 machine-proved tier, outcome-driven
 * reliability calibration, and precedent-concentration systemic risk. All pure.
 */

/** A clause reduced to propositional obligations for the L0 checker. */
export interface LogicClause {
  id: string;
  /** propositions this clause requires to hold. */
  requires?: string[];
  /** propositions this clause requires to NOT hold. */
  forbids?: string[];
}

export interface MachineCheckResult {
  tier: 'L0';
  consistent: boolean;
  /** propositions that are simultaneously required and forbidden (the proof of
   *  inconsistency); empty when consistent. */
  conflicts: { proposition: string; requiredBy: string[]; forbiddenBy: string[] }[];
}

/**
 * #2 L0 machine-proved tier: a bounded, dependency-free consistency check over
 * propositional obligations. Detects unsatisfiable clause sets (a proposition both
 * required and forbidden) — a machine proof of contradiction that ranks ABOVE
 * oracle consensus. Honest scope: propositional/deontic contradictions, not full
 * first-order theorem proving.
 */
export function machineCheck(clauses: LogicClause[]): MachineCheckResult {
  const requiredBy = new Map<string, string[]>();
  const forbiddenBy = new Map<string, string[]>();
  for (const c of clauses) {
    for (const p of c.requires ?? []) requiredBy.set(p, [...(requiredBy.get(p) ?? []), c.id]);
    for (const p of c.forbids ?? []) forbiddenBy.set(p, [...(forbiddenBy.get(p) ?? []), c.id]);
  }
  const conflicts: MachineCheckResult['conflicts'] = [];
  for (const [p, rb] of requiredBy) {
    const fb = forbiddenBy.get(p);
    if (fb && fb.length > 0) conflicts.push({ proposition: p, requiredBy: rb, forbiddenBy: fb });
  }
  return { tier: 'L0', consistent: conflicts.length === 0, conflicts };
}

export interface OutcomeEvent {
  /** the determination was later overturned (proven wrong). */
  overturned: boolean;
  /** confidence [0,1] of the update (e.g. how authoritative the overturning was). */
  weight?: number;
}

/**
 * #6 Reputation-as-stake reliability update from a realized outcome. EWMA toward
 * 1 on a correct determination and toward 0 on an overturn. Deterministic, bounded.
 */
export function updateReliabilityFromOutcome(prior: number, ev: OutcomeEvent): number {
  const w = Math.max(0, Math.min(1, ev.weight ?? 0.2));
  const target = ev.overturned ? 0 : 1;
  const next = prior + w * (target - prior);
  return Math.max(0, Math.min(1, next));
}

export interface PrecedentEdge {
  precedentId: string;
  contractId: string;
  notionalUsd: number;
}

export interface ConcentrationResult {
  /** Herfindahl index over precedent notional share, [0,1]. */
  hhi: number;
  byPrecedent: { precedentId: string; notionalUsd: number; share: number }[];
  /** the single precedent whose overturn would hit the most notional. */
  mostConcentrated?: { precedentId: string; notionalUsd: number; share: number };
}

/**
 * #4 Precedent-correlation systemic risk: how concentrated the book's settlement is
 * on any single precedent/oracle. Feeds risk ratings; the hedge itself is a separate
 * bilateral ECP swap between participants.
 */
export function precedentConcentration(edges: PrecedentEdge[]): ConcentrationResult {
  const totals = new Map<string, number>();
  let gross = 0;
  for (const e of edges) {
    const n = Math.max(0, e.notionalUsd);
    totals.set(e.precedentId, (totals.get(e.precedentId) ?? 0) + n);
    gross += n;
  }
  if (gross === 0) return { hhi: 0, byPrecedent: [] };
  const byPrecedent = [...totals.entries()]
    .map(([precedentId, notionalUsd]) => ({ precedentId, notionalUsd, share: notionalUsd / gross }))
    .sort((a, b) => b.notionalUsd - a.notionalUsd);
  const hhi = byPrecedent.reduce((s, p) => s + p.share * p.share, 0);
  return { hhi, byPrecedent, mostConcentrated: byPrecedent[0] };
}
