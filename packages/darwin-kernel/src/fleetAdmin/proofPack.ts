/**
 * Regulator-grade per-decision proof — one artifact that proves a single admin decision
 * was made inside the law: the constitution version, the autonomy computation, the CADE
 * deliberation, and the signed hash-chained receipt. STATELESS verify (no DB, no secret)
 * so a regulator, auditor, or acquirer can validate it offline. Turns the admin layer
 * into a compliance product, not just internal ops.
 */
import { sha256Canonical } from '../crypto/hash.ts';
import { verifyReceipt, type Receipt } from '../governance/receipts.ts';
import type { AdminAction } from './types.ts';
import type { FleetVerdict } from './govern.ts';
import type { Deliberation } from './deliberation.ts';

export interface DecisionProof {
  action: AdminAction;
  decision: FleetVerdict['decision'];
  tier: FleetVerdict['tier'];
  constitutionVersion: number;
  constitutionReason: string;
  autonomyReasons: string[];
  precedent?: FleetVerdict['precedent'];
  deliberation?: Deliberation;
  /** the signed, hash-chained receipt for this decision */
  receipt: Receipt;
  /** digest over the whole pack body — pins the contents */
  digest: string;
}

/** Build the proof pack for one governed decision. */
export function buildDecisionProof(params: {
  action: AdminAction;
  verdict: FleetVerdict;
  constitutionVersion: number;
  deliberation?: Deliberation;
}): DecisionProof {
  const { action, verdict } = params;
  const body = {
    action,
    decision: verdict.decision,
    tier: verdict.tier,
    constitutionVersion: params.constitutionVersion,
    constitutionReason: verdict.constitution.reason,
    autonomyReasons: verdict.autonomy.reasons,
    precedent: verdict.precedent,
    deliberation: params.deliberation,
    receipt: verdict.receipt,
  };
  return { ...body, digest: sha256Canonical(body) };
}

export interface ProofVerification {
  valid: boolean;
  digestOk: boolean;
  receiptOk: boolean;
  reason: string;
}

/** Stateless, offline verification: pack digest intact AND the receipt signature valid. */
export function verifyDecisionProof(proof: DecisionProof): ProofVerification {
  const { digest, ...body } = proof;
  const digestOk = sha256Canonical(body) === digest;
  const receiptOk = verifyReceipt(proof.receipt);
  return {
    valid: digestOk && receiptOk,
    digestOk,
    receiptOk,
    reason: digestOk ? (receiptOk ? 'ok' : 'receipt_signature_invalid') : 'pack_digest_mismatch',
  };
}
