/**
 * Portable determination credential (a.k.a. the "certainty passport") + reusable
 * determination-template matching.
 *
 * A credential is a content-addressed, optionally-signed, product-agnostic summary
 * of a Determination that any app (Apparently/Tomorrow/smarter/Pareto) or external
 * venue can consume and verify offline — the interoperable unit of legal truth.
 * Pure; signing uses the shared kernel Ed25519 anchor.
 */
import { sha256Canonical, contentId } from '../crypto/hash.ts';
import { signDigest, verifyDigest } from '../crypto/signing.ts';
import type { ProductId } from '../types.ts';
import type { Determination, IssueSpec } from './types.ts';

export interface DeterminationCredential {
  id: string;            // content id of the core
  issueId: string;
  position: string;
  value?: number;
  confidence: number;
  provedTier?: 'L0' | 'panel';
  evidenceDigest: string; // the proof digest
  precedentId: string;
  issuedBy: ProductId;
  issuedAt: string;
  coreDigest: string;
  signature?: string;
  publicKeyPem?: string;
}

/** Build a portable, verifiable credential from a Determination. */
export function toDeterminationCredential(
  det: Determination,
  opts: { issuedBy: ProductId; at: string; provedTier?: 'L0' | 'panel'; sign?: boolean },
): DeterminationCredential {
  const core = {
    issueId: det.issueId,
    position: det.position,
    value: det.value,
    confidence: det.certificate.confidence,
    provedTier: opts.provedTier,
    evidenceDigest: det.proof.digest,
    precedentId: det.proof.id,
    issuedBy: opts.issuedBy,
    issuedAt: opts.at,
  };
  const coreDigest = sha256Canonical(core);
  const id = contentId('cred', core);
  let signature: string | undefined;
  let publicKeyPem: string | undefined;
  if (opts.sign) {
    const sig = signDigest(coreDigest);
    if (sig.algorithm !== 'none') {
      signature = sig.value;
      publicKeyPem = sig.publicKeyPem;
    }
  }
  return { id, ...core, coreDigest, signature, publicKeyPem };
}

/** Offline verification: recompute the core digest and (if present) check the sig. */
export function verifyDeterminationCredential(cred: DeterminationCredential): boolean {
  const core = {
    issueId: cred.issueId,
    position: cred.position,
    value: cred.value,
    confidence: cred.confidence,
    provedTier: cred.provedTier,
    evidenceDigest: cred.evidenceDigest,
    precedentId: cred.precedentId,
    issuedBy: cred.issuedBy,
    issuedAt: cred.issuedAt,
  };
  if (sha256Canonical(core) !== cred.coreDigest) return false;
  if (!cred.signature) return true; // content-addressed only
  return verifyDigest(cred.coreDigest, {
    algorithm: 'ed25519',
    value: cred.signature,
    publicKeyPem: cred.publicKeyPem ?? '',
  });
}

/** A reusable, marketplace-listable determination template. */
export interface DeterminationTemplate {
  templateId: string;
  signature: string; // stable competence/kind signature
  credential: DeterminationCredential;
}

/** Stable signature of an issue for template matching (kind + competence keys + class). */
export function determinationSignature(issue: IssueSpec): string {
  const keys = Object.keys(issue.requiredCompetence).sort().join(',');
  return `${issue.kind}|${issue.rosterClass ?? ''}|${keys}`;
}

/** Jaccard over signature tokens. */
function jaccard(a: string, b: string): number {
  const sa = new Set(a.split(/[|,]/).filter(Boolean));
  const sb = new Set(b.split(/[|,]/).filter(Boolean));
  if (sa.size === 0 && sb.size === 0) return 1;
  let inter = 0;
  for (const t of sa) if (sb.has(t)) inter++;
  return inter / (sa.size + sb.size - inter);
}

/**
 * Template reuse (marketplace liquidity + self-precedent): return the best template
 * whose signature is similar enough to reuse instead of re-running a determination.
 */
export function matchTemplate(
  issue: IssueSpec,
  templates: DeterminationTemplate[],
  threshold = 0.85,
): DeterminationTemplate | undefined {
  const sig = determinationSignature(issue);
  let best: DeterminationTemplate | undefined;
  let bestScore = threshold;
  for (const t of templates) {
    const s = jaccard(sig, t.signature);
    if (s >= bestScore) {
      bestScore = s;
      best = t;
    }
  }
  return best;
}
