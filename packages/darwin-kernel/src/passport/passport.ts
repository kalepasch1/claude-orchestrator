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
import { canonicalize, sha256Canonical, contentId } from '../crypto/hash.ts';
import { signDigest, verifyDigest, type Signature } from '../crypto/signing.ts';
import type { ProductId } from '../types.ts';

/** What a passport can attest. Additive — new claim kinds are non-breaking. */
export type ClaimKind =
  | 'kyc_verified' // identity proofed (galop/jumio, tomorrow ECP intake)
  | 'ecp_eligible' // eligible contract participant (tomorrow)
  | 'accredited' // accredited / qualified investor (pareto, tomorrow)
  | 'geo_allowed' // jurisdiction/geo cleared (galop)
  | 'credit_quality' // composite credit score 0..1 (tomorrow)
  | 'financial_profile' // net worth band, liquidity band (pareto)
  | 'reliability' // counterparty/sender reliability 0..1 (smarter)
  | 'guardian_verified' // verified parent/guardian (hisanta)
  | 'sanctions_clear'; // sanctions screen passed

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
  const liveClaims = passport.claims.filter((c) => Date.parse(c.expiresAt) > now);
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
