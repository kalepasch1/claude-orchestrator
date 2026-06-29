/**
 * Cross-product identity graph — the connective tissue for the "one identity,
 * many products" account fabric (opportunity #12). A single subject can be linked
 * to per-product local ids, and a CONSENT layer governs what each product may
 * read about the subject from the others.
 *
 * This module is pure/in-memory by design: each product persists the graph in its
 * own store (Supabase) and uses these functions to reason about links + consent.
 * Nothing here moves PII — it links opaque ids and records consent scopes.
 */
import type { ProductId } from '../types.ts';
import { contentId } from '../crypto/hash.ts';
import type { ClaimKind } from '../passport/passport.ts';

/** A canonical person/entity. `subject` is the stable cross-product key. */
export interface IdentityNode {
  subject: string;
  /** product -> local id within that product */
  localIds: Partial<Record<ProductId, string>>;
  createdAt: string;
}

/** Consent grant: subject allows `to` to read `scopes` sourced from `from`. */
export interface ConsentGrant {
  subject: string;
  from: ProductId;
  to: ProductId;
  scopes: ClaimKind[];
  grantedAt: string;
  /** ISO; absent = no expiry */
  expiresAt?: string;
  revoked?: boolean;
}

/** Deterministically derive a subject id from a strong identifier (e.g. a hash
 *  of verified email/govID). Never store the raw identifier — store the subject. */
export function deriveSubject(strongIdentifier: string): string {
  return contentId('sub', strongIdentifier.trim().toLowerCase());
}

export function linkLocalId(
  node: IdentityNode,
  product: ProductId,
  localId: string,
): IdentityNode {
  return { ...node, localIds: { ...node.localIds, [product]: localId } };
}

/** Is product `to` currently allowed to read `scope` about `subject` from `from`? */
export function consentAllows(
  grants: ConsentGrant[],
  params: { subject: string; from: ProductId; to: ProductId; scope: ClaimKind; asOf?: Date },
): boolean {
  const now = (params.asOf ?? new Date()).getTime();
  return grants.some(
    (g) =>
      !g.revoked &&
      g.subject === params.subject &&
      g.from === params.from &&
      g.to === params.to &&
      g.scopes.includes(params.scope) &&
      (!g.expiresAt || Date.parse(g.expiresAt) > now),
  );
}

/**
 * The cross-sell routing primitive: given live passport claims about a subject and
 * the set of products they are NOT yet on, suggest which product to route them to.
 * Pure heuristic — products supply the candidate rules.
 */
export interface RouteSuggestion {
  to: ProductId;
  reason: string;
  /** 0..1 confidence */
  score: number;
}

export interface RouteRule {
  to: ProductId;
  /** claim that triggers the suggestion */
  requires: ClaimKind;
  minValue?: number;
  reason: string;
  score: number;
}

/** Default cross-product routing rules — the flywheel encoded as data. */
export const DEFAULT_ROUTE_RULES: RouteRule[] = [
  { to: 'tomorrow', requires: 'financial_profile', minValue: 0.7, reason: 'High net worth / concentrated exposure → hedging', score: 0.8 },
  { to: 'pareto', requires: 'kyc_verified', reason: 'KYC-verified individual → wealth & retirement planning', score: 0.6 },
  { to: 'tomorrow', requires: 'ecp_eligible', reason: 'ECP-eligible entity → OTC risk products', score: 0.85 },
  { to: 'pareto', requires: 'guardian_verified', reason: 'Verified parent → household & college planning', score: 0.7 },
  { to: 'apparently', requires: 'reliability', minValue: 0.5, reason: 'Active counterparty → legal/regulatory services', score: 0.5 },
];

export function suggestRoutes(params: {
  liveClaimKinds: { kind: ClaimKind; value: number }[];
  alreadyOn: ProductId[];
  rules?: RouteRule[];
}): RouteSuggestion[] {
  const rules = params.rules ?? DEFAULT_ROUTE_RULES;
  const on = new Set(params.alreadyOn);
  const out: RouteSuggestion[] = [];
  for (const r of rules) {
    if (on.has(r.to)) continue;
    const match = params.liveClaimKinds.find(
      (c) => c.kind === r.requires && c.value >= (r.minValue ?? 0),
    );
    if (match) out.push({ to: r.to, reason: r.reason, score: r.score });
  }
  return out.sort((a, b) => b.score - a.score);
}

export function newIdentity(subject: string, createdAt: string = new Date().toISOString()): IdentityNode {
  return { subject, localIds: {}, createdAt };
}
