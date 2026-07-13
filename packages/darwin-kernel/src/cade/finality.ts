/**
 * Determination-finality netting: a DAG of determinations where finality propagates.
 * If every dependency of a node is final, the node inherits finality — so settled
 * sub-questions are never re-litigated. Cycle-safe. Pure.
 */

export interface FinalityNode {
  id: string;
  dependsOn: string[];
  /** already settled/final (a seed). */
  final: boolean;
}

export interface FinalityResult {
  finalIds: string[];
  newlyFinal: string[];
  /** ids involved in a dependency cycle (can never auto-finalize). */
  cyclic: string[];
}

/**
 * Propagate finality to fixpoint: a node becomes final when all its dependencies are
 * final. Returns the full final set, the newly-derived finals, and any cyclic ids.
 */
export function propagateFinality(nodes: FinalityNode[]): FinalityResult {
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const final = new Set(nodes.filter((n) => n.final).map((n) => n.id));
  const seeded = new Set(final);

  let changed = true;
  while (changed) {
    changed = false;
    for (const n of nodes) {
      if (final.has(n.id)) continue;
      const depsResolvable = n.dependsOn.every((d) => byId.has(d));
      if (depsResolvable && n.dependsOn.every((d) => final.has(d))) {
        final.add(n.id);
        changed = true;
      }
    }
  }

  // cyclic = not final AND reachable-into a cycle (any non-final node whose deps
  // are all present but not all final, after fixpoint, is blocked — includes cycles).
  const cyclic: string[] = [];
  for (const n of nodes) {
    if (!final.has(n.id) && n.dependsOn.length > 0 && n.dependsOn.every((d) => byId.has(d))) {
      if (isInCycle(n.id, byId)) cyclic.push(n.id);
    }
  }

  return {
    finalIds: [...final],
    newlyFinal: [...final].filter((id) => !seeded.has(id)),
    cyclic,
  };
}

function isInCycle(start: string, byId: Map<string, FinalityNode>): boolean {
  const seen = new Set<string>();
  const stack = [start];
  let first = true;
  while (stack.length) {
    const cur = stack.pop() as string;
    if (!first && cur === start) return true;
    first = false;
    if (seen.has(cur)) continue;
    seen.add(cur);
    const node = byId.get(cur);
    if (node) for (const d of node.dependsOn) stack.push(d);
  }
  return false;
}
