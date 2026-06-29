/**
 * Attestation bus (improvement #3) — the generalization of the passport. ANY
 * product can attest ANYTHING portable, and any other product verifies it OFFLINE
 * from the embedded key. The passport is just the identity-flavored specialization
 * of this; the same envelope carries far more:
 *   - tomorrow:  'trigger_rating' (a parametric trigger is AAA), 'clause_at_market'
 *   - smarter:   'clause_at_market', 'counterparty_reliable'
 *   - galop:     'kyc_verified', 'provably_fair_result'
 *   - apparently:'opinion_grounded', 'license_valid'
 *   - hisanta:   'content_safe', 'guardian_verified'
 *   - barks:     'shelter_verified', 'donation_delivered'
 *
 * An Attestation is content-addressed + Ed25519-signed + time-boxed. The kind is a
 * free string namespaced `product:kind` so the bus is open/extensible without
 * touching the kernel.
 */
import { sha256Canonical, contentId } from '../crypto/hash.ts';
import { signDigest, verifyDigest, type Signature } from '../crypto/signing.ts';
import type { ProductId } from '../types.ts';

export interface Attestation<T = Record<string, unknown>> {
  id: string;
  /** namespaced kind, e.g. 'tomorrow:trigger_rating' */
  kind: string;
  issuer: ProductId;
  /** what is being attested about (subject id, clause id, trigger id, shelter id) */
  about: string;
  /** the claim payload (kept opaque/structural) */
  payload: T;
  issuedAt: string;
  expiresAt: string;
  digest: string;
  signature: Signature;
}

const DAY = 86_400_000;

export function attest<T extends Record<string, unknown>>(params: {
  kind: string;
  issuer: ProductId;
  about: string;
  payload: T;
  ttlDays?: number;
  issuedAt?: Date;
}): Attestation<T> {
  const issuedAt = params.issuedAt ?? new Date();
  const body = {
    kind: params.kind,
    issuer: params.issuer,
    about: params.about,
    payload: params.payload,
    issuedAt: issuedAt.toISOString(),
    expiresAt: new Date(issuedAt.getTime() + (params.ttlDays ?? 365) * DAY).toISOString(),
  };
  const digest = sha256Canonical(body);
  return { id: contentId('att', body), ...body, digest, signature: signDigest(digest) };
}

export interface AttestationCheck {
  valid: boolean;
  reason: string;
}

export function verifyAttestation(att: Attestation, asOf: Date = new Date()): AttestationCheck {
  const { id: _id, digest, signature, ...body } = att;
  if (sha256Canonical(body) !== digest) return { valid: false, reason: 'digest_mismatch' };
  if (!verifyDigest(digest, signature)) return { valid: false, reason: 'signature_invalid' };
  if (Date.parse(att.expiresAt) <= asOf.getTime()) return { valid: false, reason: 'expired' };
  return { valid: true, reason: 'ok' };
}

/** Filter a bag of attestations to the live, valid ones of a given kind about a subject. */
export function liveAttestations(
  atts: Attestation[],
  opts: { kind?: string; about?: string; asOf?: Date } = {},
): Attestation[] {
  const asOf = opts.asOf ?? new Date();
  return atts.filter(
    (a) =>
      (!opts.kind || a.kind === opts.kind) &&
      (!opts.about || a.about === opts.about) &&
      verifyAttestation(a, asOf).valid,
  );
}
