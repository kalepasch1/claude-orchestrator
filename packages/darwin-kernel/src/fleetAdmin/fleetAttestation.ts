/**
 * Proof-of-autonomy attestation — a continuously-updated, SIGNED statement of how the plane
 * is governed: the answered-from-plane rate, the zero-regression record, and the adversarial
 * red-team envelope. Partners, auditors, and acquirers verify it offline (no DB, no secret).
 * Provably-governed automation becomes an external trust product. Pure + zero-dep.
 */
import { sha256Canonical } from '../crypto/hash.ts';
import { signDigest, verifyDigest, getPublicKeyPem, type Signature } from '../crypto/signing.ts';

export interface AutonomyAttestationBody {
  issuedAt: string;
  periodDays: number;
  answeredFromPlaneRate: number;
  totalDecisions: number;
  /** regressions detected in the period (auto-ran something later found wrong) — target 0 */
  regressions: number;
  /** residual harm the red-team can still get to auto-run (the safe envelope, target < 0.3) */
  redTeamResidualHarm: number;
  /** true when the constitution + receipts chain verified end-to-end for the period */
  receiptsChainVerified: boolean;
  publicKeyPem: string;
}

export interface AutonomyAttestation extends AutonomyAttestationBody {
  digest: string;
  signature: Signature;
}

/** Mint a signed attestation. */
export function buildAutonomyAttestation(body: Omit<AutonomyAttestationBody, 'publicKeyPem'>): AutonomyAttestation {
  const full: AutonomyAttestationBody = { ...body, publicKeyPem: getPublicKeyPem() };
  const digest = sha256Canonical(full);
  return { ...full, digest, signature: signDigest(digest) };
}

export interface AttestationCheck {
  valid: boolean;
  digestOk: boolean;
  signatureOk: boolean;
  /** independent read on whether the numbers meet a "trustworthy" bar */
  meetsBar: boolean;
  reason: string;
}

/** Stateless verification + a plain read on whether the attestation clears a trust bar. */
export function verifyAutonomyAttestation(
  att: AutonomyAttestation,
  bar = { maxResidualHarm: 0.3, maxRegressions: 0 },
): AttestationCheck {
  const { digest, signature, ...body } = att;
  const digestOk = sha256Canonical(body) === digest;
  const signatureOk = verifyDigest(digest, signature);
  const meetsBar = att.regressions <= bar.maxRegressions && att.redTeamResidualHarm < bar.maxResidualHarm && att.receiptsChainVerified;
  return {
    valid: digestOk && signatureOk,
    digestOk,
    signatureOk,
    meetsBar,
    reason: !digestOk ? 'digest_mismatch' : !signatureOk ? 'signature_invalid' : meetsBar ? 'ok' : 'valid_but_below_trust_bar',
  };
}
