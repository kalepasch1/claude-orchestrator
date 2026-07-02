/**
 * Cross-org trust web — the signed autonomy attestation is offline-verifiable, so orgs can
 * COUNTER-SIGN each other's attestations to build a trust graph: "these N companies attest that
 * this org runs provably-governed autonomy at this bar." A trust passport (attestation + its
 * counter-signatures) becomes a compliance credential partners + regulators accept, and a moat
 * competitors can't fake. Pure + zero-dep.
 */
import { sha256Canonical } from '../crypto/hash.ts';
import { signDigest, verifyDigest, getPublicKeyPem, type Signature } from '../crypto/signing.ts';
import type { AutonomyAttestation } from './fleetAttestation.ts';
import { verifyAutonomyAttestation } from './fleetAttestation.ts';

export interface CounterSignatureBody {
  attestationDigest: string;
  byOrg: string;
  at: string;
  publicKeyPem: string;
}
export interface CounterSignature extends CounterSignatureBody {
  digest: string;
  signature: Signature;
}

/** One org counter-signs another org's attestation (by its digest). */
export function counterSign(attestationDigest: string, byOrg: string, at?: string): CounterSignature {
  const body: CounterSignatureBody = { attestationDigest, byOrg, at: at ?? new Date().toISOString(), publicKeyPem: getPublicKeyPem() };
  const digest = sha256Canonical(body);
  return { ...body, digest, signature: signDigest(digest) };
}

/** Verify a counter-signature is intact + validly signed. */
export function verifyCounterSignature(cs: CounterSignature): boolean {
  const { digest, signature, ...body } = cs;
  if (sha256Canonical(body) !== digest) return false;
  return verifyDigest(digest, signature);
}

export interface TrustPassport {
  attestation: AutonomyAttestation;
  counterSignatures: CounterSignature[];
}

export interface PassportVerification {
  valid: boolean;
  attestationValid: boolean;
  attestationMeetsBar: boolean;
  validCosigners: string[];
  invalidCosigners: string[];
  reason: string;
}

/**
 * Verify a whole trust passport: the attestation itself, plus each counter-signature that
 * actually references THIS attestation's digest. Cosigners that reference a different digest or
 * fail signature checks are rejected (never silently counted).
 */
export function verifyTrustPassport(passport: TrustPassport): PassportVerification {
  const attCheck = verifyAutonomyAttestation(passport.attestation);
  const validCosigners: string[] = [];
  const invalidCosigners: string[] = [];
  for (const cs of passport.counterSignatures) {
    const ok = cs.attestationDigest === passport.attestation.digest && verifyCounterSignature(cs);
    (ok ? validCosigners : invalidCosigners).push(cs.byOrg);
  }
  const valid = attCheck.valid && invalidCosigners.length === 0;
  return {
    valid,
    attestationValid: attCheck.valid,
    attestationMeetsBar: attCheck.meetsBar,
    validCosigners: [...new Set(validCosigners)],
    invalidCosigners: [...new Set(invalidCosigners)],
    reason: !attCheck.valid ? 'attestation_invalid' : invalidCosigners.length ? 'some_countersignatures_invalid' : `attested + counter-signed by ${validCosigners.length} org(s)`,
  };
}
