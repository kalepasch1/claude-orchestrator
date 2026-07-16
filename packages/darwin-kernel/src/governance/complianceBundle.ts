/**
 * Compliance evidence bundle — assembles a PolicyService compliance pack +
 * selected attestation-feed entries into a single signed, offline-verifiable
 * evidence bundle per product.
 *
 * Includes a stateless verifier that checks the pack, attestations, and
 * bundle-level signature without requiring DB access.
 */
import { sha256Canonical } from '../crypto/hash.ts';
import { signDigest, verifyDigest, type Signature } from '../crypto/signing.ts';
import { type CompliancePack, verifyCompliancePack } from './policyService.ts';
import { type Attestation, verifyAttestation } from '../attestation/attestation.ts';

export interface EvidenceBundle {
  /** Product this bundle covers. */
  product: string;
  /** ISO timestamp when the bundle was assembled. */
  assembledAt: string;
  /** The compliance pack from PolicyService. */
  compliancePack: CompliancePack;
  /** Selected attestation-feed entries included as evidence. */
  attestations: Attestation[];
  /** SHA-256 digest over the canonical bundle body. */
  digest: string;
  /** Ed25519 signature over the digest. */
  signature: Signature;
}

export interface BundleVerification {
  /** Overall validity. */
  ok: boolean;
  /** Whether the bundle-level digest + signature are valid. */
  signatureValid: boolean;
  /** Whether the embedded compliance pack is valid. */
  packValid: boolean;
  /** Per-attestation validity results. */
  attestationResults: { subject: string; valid: boolean }[];
  /** Human-readable issues. */
  issues: string[];
}

/** Assemble a signed evidence bundle from a compliance pack + attestations. */
export function assembleBundle(params: {
  product: string;
  compliancePack: CompliancePack;
  attestations: Attestation[];
}): EvidenceBundle {
  const assembledAt = new Date().toISOString();
  const body = {
    product: params.product,
    assembledAt,
    compliancePack: params.compliancePack,
    attestations: params.attestations,
  };
  const digest = sha256Canonical(body);
  const signature = signDigest(digest);
  return { ...body, digest, signature };
}

/** Stateless verification of an evidence bundle — no DB required. */
export function verifyBundle(bundle: EvidenceBundle): BundleVerification {
  const issues: string[] = [];

  // 1. Verify bundle-level signature
  const { digest, signature, ...body } = bundle;
  const recomputed = sha256Canonical(body);
  const signatureValid = recomputed === digest && verifyDigest(digest, signature);
  if (!signatureValid) issues.push('Bundle signature invalid or digest mismatch');

  // 2. Verify compliance pack
  const packResult = verifyCompliancePack(bundle.compliancePack);
  const packValid = packResult.valid && packResult.chainOk;
  if (!packValid) issues.push('Compliance pack verification failed');

  // 3. Verify each attestation
  const attestationResults = bundle.attestations.map((att) => {
    const check = verifyAttestation(att);
    if (!check.valid) issues.push(`Attestation ${att.about} invalid: ${check.reason}`);
    return { subject: att.about, valid: check.valid };
  });

  const ok = signatureValid && packValid && attestationResults.every((r) => r.valid);
  return { ok, signatureValid, packValid, attestationResults, issues };
}
