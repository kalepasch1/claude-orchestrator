/**
 * Identity rollups (improvement #5) — because subjects are deterministic and
 * linkable, you get household graphs (Hisanta family ↔ Pareto household) and
 * entity graphs (Smarter counterparty ↔ Tomorrow ECP ↔ Apparently licensee) for
 * free. This is the substrate for "one relationship, every product" reporting that
 * no single-vertical competitor can assemble.
 *
 * Pure graph rollup over typed edges. No PII — operates on opaque subject ids.
 */
import type { ProductId } from '../types.ts';

export type EdgeKind = 'guardian_of' | 'spouse_of' | 'member_of' | 'controls' | 'advises';

export interface IdentityEdge {
  from: string; // subject id
  to: string; // subject id
  kind: EdgeKind;
}

export interface RollupNode {
  subject: string;
  products: ProductId[]; // products this subject is active on
}

export interface Rollup {
  /** the root the rollup is anchored on */
  root: string;
  /** all subjects in the connected group (root + reachable via edges) */
  members: string[];
  /** union of products any member touches */
  products: ProductId[];
  /** distinct product count — the "relationship breadth" metric */
  breadth: number;
  /** edges internal to the group */
  edges: IdentityEdge[];
}

/**
 * Roll up the connected group reachable from `root` via the given edge kinds
 * (undirected traversal over those kinds). E.g. household = {guardian_of, spouse_of, member_of}.
 */
export function rollup(params: {
  root: string;
  nodes: RollupNode[];
  edges: IdentityEdge[];
  via: EdgeKind[];
}): Rollup {
  const via = new Set(params.via);
  const adj = new Map<string, string[]>();
  const internalEdges: IdentityEdge[] = [];
  for (const e of params.edges) {
    if (!via.has(e.kind)) continue;
    adj.set(e.from, [...(adj.get(e.from) ?? []), e.to]);
    adj.set(e.to, [...(adj.get(e.to) ?? []), e.from]);
  }
  // BFS
  const seen = new Set<string>([params.root]);
  const queue = [params.root];
  while (queue.length) {
    const cur = queue.shift()!;
    for (const nxt of adj.get(cur) ?? []) {
      if (!seen.has(nxt)) {
        seen.add(nxt);
        queue.push(nxt);
      }
    }
  }
  for (const e of params.edges) {
    if (via.has(e.kind) && seen.has(e.from) && seen.has(e.to)) internalEdges.push(e);
  }
  const nodeBySubject = new Map(params.nodes.map((n) => [n.subject, n]));
  const products = new Set<ProductId>();
  for (const s of seen) for (const p of nodeBySubject.get(s)?.products ?? []) products.add(p);

  return {
    root: params.root,
    members: [...seen],
    products: [...products],
    breadth: products.size,
    edges: internalEdges,
  };
}

/** Convenience: household rollup = guardian_of + spouse_of + member_of. */
export function householdRollup(root: string, nodes: RollupNode[], edges: IdentityEdge[]): Rollup {
  return rollup({ root, nodes, edges, via: ['guardian_of', 'spouse_of', 'member_of'] });
}

/** Convenience: control/entity rollup = controls + advises. */
export function entityRollup(root: string, nodes: RollupNode[], edges: IdentityEdge[]): Rollup {
  return rollup({ root, nodes, edges, via: ['controls', 'advises'] });
}
