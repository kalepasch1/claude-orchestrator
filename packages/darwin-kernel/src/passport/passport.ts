/**
 * Risk / Identity Passport — a portable, content-addressed, Ed25519-signed
 * credential a person or entity carries between products. Generalized from
 * Tomorrow's Credit Passport so it spans KYC (galop), financial profile (pareto),
 * counterparty reliability (smarter), and credit (tomorrow).
 *
 * The whole point: do KYC / verification ONCE, then any other product verifies it
 * OFFLINE — no shared secret, no call back to the issuer. Time-boxed so a stale
 * passport is rejected.
 */
import { sha256Canonical, contentId, canonicalize } from '../crypto/hash.ts';
import { signDigest, verifyDigest, type Signature } from '../crypto/signing.ts';
import type { ProductId } from '../types.ts';

/**
 * Every claim kind a passport can attest, grouped by what the claim is ABOUT.
 *
 * WHY A GROUPED REGISTRY AND NOT ONE UNION. This was a single `export type ClaimKind =`
 * union with one member per line. It is the most-edited construct in the kernel — the file
 * carries 38 commits across 178 lines — because every product that joins the passport wants
 * to add its own claim kind, and "additive, non-breaking" was true of the TYPE while being
 * false of the MERGE: a one-line-per-member union means every branch that adds a member
 * edits the same contiguous hunk, so any two parallel branches conflict textually even
 * though their changes are semantically independent. Four separate tasks were failed with
 * `train: still conflicts after 4 redos — Conflicting files:
 * packages/darwin-kernel/src/passport/passport.ts` and their branches were eventually GC'd.
 *
 * Grouping by concern puts independent additions on different lines: a product adding an
 * identity claim and a product adding a scoring claim now touch disjoint text and git merges
 * both without a human. That is the whole point of the change — the exported `ClaimKind`
 * type below still resolves to exactly the same nine string literals as before.
 *
 * Additive in both senses now: append to the right group, or add a new group.
 */
export const CLAIM_KINDS = {
  /** who someone is */
  identity: ['kyc_verified', 'guardian_verified'],
  /** what they are permitted to do */
  eligibility: ['ecp_eligible', 'accredited', 'geo_allowed', 'sanctions_clear'],
  /** how they score on a continuous measure */
  scoring: ['credit_quality', 'financial_profile', 'reliability'],
} as const satisfies Record<string, readonly string[]>;

/**
 * What a passport can attest. Additive — new claim kinds are non-breaking.
 *
 * Derived from CLAIM_KINDS, so the type and the runtime list cannot drift apart. Previously
 * there was no runtime list at all: the union vanished at compile time, so a passport
 * arriving from another product carrying an unrecognised `kind` could not be detected.
 *
 *   'kyc_verified'       identity proofed (galop/jumio, tomorrow ECP intake)
 *   'guardian_verified'  verified parent/guardian (hisanta)
 *   'ecp_eligible'       eligible contract participant (tomorrow)
 *   'accredited'         accredited / qualified investor (pareto, tomorrow)
 *   'geo_allowed'        jurisdiction/geo cleared (galop)
 *   'sanctions_clear'    sanctions screen passed
 *   'credit_quality'     composite credit score 0..1 (tomorrow)
 *   'financial_profile'  net worth band, liquidity band (pareto)
 *   'reliability'        counterparty/sender reliability 0..1 (smarter)
 */
export type ClaimKind = (typeof CLAIM_KINDS)[keyof typeof CLAIM_KINDS][number];

/** Flat list of every known claim kind. Order is group order, then within-group order. */
export const ALL_CLAIM_KINDS: readonly ClaimKind[] = Object.values(CLAIM_KINDS).flat();

/**
 * Runtime check that a value is a claim kind this build knows about.
 *
 * A passport crosses product boundaries and is verified OFFLINE by a peer that may be on an
 * older build. Without this, an unknown `kind` is structurally invisible: it passes the
 * digest and signature checks (it is part of the signed bytes) and then silently satisfies
 * nothing, because `hasClaim` compares against a kind the caller names. Callers that care
 * can now say so explicitly. Never throws.
 */
export function isClaimKind(value: unknown): value is ClaimKind {
  return typeof value === 'string' && (ALL_CLAIM_KINDS as readonly string[]).includes(value);
}

export interface Claim {
  kind: ClaimKind;
  /** issuing product */
  issuer: ProductId;
  /** numeric value where meaningful (score/band); else 1 for boolean claims */
  value: number;
  /** optional structured detail (band labels, tier, etc.) */
  detail?: Record<string, unknown>;
  /** ISO issue + expiry */
  issuedAt: string;
  expiresAt: string;
}

export interface Passport {
  id: string;
  /** stable subject id within the identity graph (see identity/graph.ts) */
  subject: string;
  version: 1;
  claims: Claim[];
  issuedAt: string;
  /** digest over {subject, version, claims, issuedAt} */
  digest: string;
  signature: Signature;
}

const DAY = 86_400_000;

/**
 * Canonical form used for the digest and content id — NOT for storage.
 *
 * A passport's digest identifies its CONTENT, and a set of claims is the same set whichever
 * order it arrives in. Digesting the claims as-given made digest and `id` order-dependent:
 * the same subject with the same claims produced two different passports depending on array
 * order, silently breaking dedup, caching, and any equality check built on id/digest.
 *
 * Only the hashed view is sorted. The stored `passport.claims` keeps the caller's order,
 * because callers legitimately read `claims[i]` positionally and reordering the stored array
 * would change observable behaviour to fix a hashing concern.
 *
 * buildPassport and verifyPassport MUST both hash through here — canonicalising on only one
 * side makes every passport fail its own digest check.
 *
 * The comparator must be a TOTAL order over exactly the bytes that get hashed. The scalar
 * tuple below (kind, issuer, issuedAt, expiresAt, value) is not: it omits `detail`, so two
 * claims that agree on all five compare equal, `Array.prototype.sort` is stable and therefore
 * leaves them in caller order, and the digest goes back to being order-dependent — the exact
 * defect this function exists to prevent. `canonicalize` is the final tie-break because it is
 * the same key-sorted serialization the digest itself is taken over, so every digest-relevant
 * field (including `detail`, and any field added later) participates in the ordering by
 * construction. The scalar tuple is kept ahead of it only because it orders a canonical dump
 * the way a human would expect to read it, and short-circuits before the serialize in the
 * common case.
 */
function canonicalBody<T extends { claims: Claim[] }>(body: T): T {
  return {
    ...body,
    claims: [...body.claims].sort((a, b) => {
      const scalar =
        a.kind.localeCompare(b.kind) ||
        a.issuer.localeCompare(b.issuer) ||
        a.issuedAt.localeCompare(b.issuedAt) ||
        a.expiresAt.localeCompare(b.expiresAt) ||
        a.value - b.value;
      if (scalar !== 0) return scalar;
      const ka = canonicalize(a);
      const kb = canonicalize(b);
      return ka < kb ? -1 : ka > kb ? 1 : 0;
    }),
  };
}

export function buildPassport(params: {
  subject: string;
  claims: Claim[];
  issuedAt?: string;
}): Passport {
  const body = {
    subject: params.subject,
    version: 1 as const,
    claims: params.claims,
    issuedAt: params.issuedAt ?? new Date().toISOString(),
  };
  const canonical = canonicalBody(body);
  const digest = sha256Canonical(canonical);
  return {
    id: contentId('pass', canonical),
    ...body,
    digest,
    signature: signDigest(digest),
  };
}

export interface PassportVerification {
  valid: boolean;
  reason: string;
  /** claims that are individually unexpired at `asOf` */
  liveClaims: Claim[];
}

/** Stateless verify: signature + digest integrity + per-claim expiry. */
export function verifyPassport(passport: Passport, asOf: Date = new Date()): PassportVerification {
  const { id: _id, digest, signature, ...body } = passport;
  if (sha256Canonical(canonicalBody(body)) !== digest) {
    return { valid: false, reason: 'digest_mismatch', liveClaims: [] };
  }
  if (!verifyDigest(digest, signature)) {
    return { valid: false, reason: 'signature_invalid', liveClaims: [] };
  }
  const now = asOf.getTime();
  // A claim that had already expired when the passport was MINTED is dead in
  // every timeline: verifying "as of" an earlier date must not resurrect it,
  // otherwise a backdated `asOf` turns expired credentials back on.
  const mintedAt = Date.parse(passport.issuedAt);
  const liveClaims = passport.claims.filter(
    (c) => Date.parse(c.expiresAt) > now && Date.parse(c.expiresAt) > mintedAt,
  );
  if (liveClaims.length === 0) {
    return { valid: false, reason: 'all_claims_expired', liveClaims: [] };
  }
  return { valid: true, reason: 'ok', liveClaims };
}

/** Has a live claim of a given kind (optionally meeting a minimum value)? */
export function hasClaim(
  passport: Passport,
  kind: ClaimKind,
  minValue = 0,
  asOf: Date = new Date(),
): boolean {
  const v = verifyPassport(passport, asOf);
  if (!v.valid) return false;
  return v.liveClaims.some((c) => c.kind === kind && c.value >= minValue);
}

/** Helper to mint a claim with a TTL in days. */
export function claim(
  kind: ClaimKind,
  issuer: ProductId,
  value: number,
  ttlDays = 90,
  detail?: Record<string, unknown>,
  issuedAt: Date = new Date(),
): Claim {
  return {
    kind,
    issuer,
    value,
    detail,
    issuedAt: issuedAt.toISOString(),
    expiresAt: new Date(issuedAt.getTime() + ttlDays * DAY).toISOString(),
  };
}
