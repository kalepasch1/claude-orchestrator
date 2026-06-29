/**
 * Compliance receipts — every governed action emits a hash-chained, Ed25519-signed,
 * content-addressed receipt. Generalized from Tomorrow's P1 receipt log + C1 proof.
 *
 * Two properties make this portfolio-grade:
 *   1. Hash chain: each receipt carries prevHash, so a per-subject sequence is
 *      tamper-evident — you cannot delete or reorder a receipt without breaking
 *      the chain.
 *   2. Stateless verify: anyone can re-derive the digest from the public payload
 *      and check the signature against the embedded key. No DB, no secret.
 */
import { sha256Canonical, contentId } from '../crypto/hash.ts';
import { signDigest, verifyDigest, type Signature } from '../crypto/signing.ts';
import type { AgentAction, Decision } from '../types.ts';
import type { ConstitutionDecision } from './constitution.ts';

export interface Receipt {
  id: string;
  /** chain key: usually `${product}:${subjectId}` */
  chain: string;
  seq: number;
  prevHash: string | null;
  action: AgentAction;
  decision: Decision;
  ruleId: string | null;
  reason: string;
  /** ISO time the receipt was minted */
  at: string;
  /** SHA-256 over the canonical receipt body (everything above) */
  digest: string;
  signature: Signature;
}

interface ReceiptBody {
  chain: string;
  seq: number;
  prevHash: string | null;
  action: AgentAction;
  decision: Decision;
  ruleId: string | null;
  reason: string;
  at: string;
}

/** Mint a signed receipt that links to the previous receipt in its chain. */
export function buildReceipt(params: {
  chain: string;
  action: AgentAction;
  verdict: ConstitutionDecision;
  prev?: Receipt | null;
  at?: string;
}): Receipt {
  const prev = params.prev ?? null;
  const body: ReceiptBody = {
    chain: params.chain,
    seq: prev ? prev.seq + 1 : 0,
    prevHash: prev ? prev.digest : null,
    action: params.action,
    decision: params.verdict.decision,
    ruleId: params.verdict.ruleId,
    reason: params.verdict.reason,
    at: params.at ?? new Date().toISOString(),
  };
  const digest = sha256Canonical(body);
  return {
    id: contentId('rcpt', body),
    ...body,
    digest,
    signature: signDigest(digest),
  };
}

/** Verify a single receipt: digest matches the body AND signature validates. */
export function verifyReceipt(receipt: Receipt): boolean {
  const { id: _id, digest, signature, ...body } = receipt;
  const recomputed = sha256Canonical(body);
  if (recomputed !== digest) return false;
  return verifyDigest(digest, signature);
}

/** Verify a whole per-subject chain: each receipt valid + linkage intact. */
export function verifyChain(receipts: Receipt[]): { ok: boolean; brokenAt: number | null } {
  let prevHash: string | null = null;
  for (let i = 0; i < receipts.length; i++) {
    const r = receipts[i]!;
    if (!verifyReceipt(r)) return { ok: false, brokenAt: i };
    if (r.seq !== i) return { ok: false, brokenAt: i };
    if (r.prevHash !== prevHash) return { ok: false, brokenAt: i };
    prevHash = r.digest;
  }
  return { ok: true, brokenAt: null };
}
