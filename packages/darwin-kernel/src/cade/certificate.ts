/**
 * The Optimality Certificate + the signed, replayable Proof Pack.
 *
 * The certificate is the customer-facing guarantee — NOT "infallible", but the
 * defensible, auditable claim: of N considered minds, K were seated; the strongest
 * EXCLUDED mind is bounded to move this by < ε; the answer saturated; every position
 * had its strongest opponent. The proof pack content-addresses the whole record and
 * (optionally) signs it so a third party can verify offline.
 */
import { contentId, sha256Canonical } from '../crypto/hash.ts';
import { signDigest } from '../crypto/signing.ts';
import type {
  Faction,
  IssueSpec,
  OptimalityCertificate,
  ProofPack,
  ProofRecord,
  RedTeamHit,
} from './types.ts';

export interface CertificateInputs {
  rosterClass?: string;
  rosterComplete?: boolean;
  consideredCount: number;
  seatedCount: number;
  marginalValueBound: number;
  saturated: boolean;
  adversariallyComplete: boolean;
  leadSupport: number;     // [0,1] share of the winning faction
  jackknifeRobust: boolean;
}

export function buildCertificate(inp: CertificateInputs): OptimalityCertificate {
  // Confidence blends lead support, robustness, saturation and how small ε is.
  const epsTerm = 1 - Math.min(1, inp.marginalValueBound);
  const confidence = clamp01(
    0.4 * inp.leadSupport +
      0.25 * (inp.jackknifeRobust ? 1 : 0.4) +
      0.2 * (inp.saturated ? 1 : 0.5) +
      0.15 * epsTerm,
  );
  const statement =
    `Of ${inp.consideredCount} relevance-matched minds, ${inp.seatedCount} deliberated. ` +
    `The strongest excluded mind is bounded to change this determination by < ` +
    `${inp.marginalValueBound.toFixed(3)} (ε). ` +
    `${inp.saturated ? 'The answer saturated (added minds stopped moving it). ' : ''}` +
    `${inp.adversariallyComplete ? 'Every surviving position had its strongest opponent seated. ' : ''}` +
    `${inp.rosterComplete && inp.rosterClass ? `Authority class '${inp.rosterClass}' is provably covered. ` : ''}` +
    `No stronger assemblable panel was found within the measured bound.`;
  return {
    rosterComplete: inp.rosterComplete ?? false,
    rosterClass: inp.rosterClass,
    consideredCount: inp.consideredCount,
    seatedCount: inp.seatedCount,
    marginalValueBound: inp.marginalValueBound,
    confidence,
    saturated: inp.saturated,
    adversariallyComplete: inp.adversariallyComplete,
    statement,
  };
}

export function buildProofPack(
  args: {
    issue: IssueSpec;
    consideredPersonaIds: string[];
    excludedPersonaIds: string[];
    seatedPersonaIds: string[];
    rounds: number;
    factions: Faction[];
    redTeam: RedTeamHit[];
    certificate: OptimalityCertificate;
    councils?: ProofPack[];
    distribution?: IssueSpec['distribution'];
    createdAt: string;
  },
  sign = false,
): ProofPack {
  const record: ProofRecord = {
    issue: args.issue,
    consideredPersonaIds: args.consideredPersonaIds,
    excludedPersonaIds: args.excludedPersonaIds,
    seatedPersonaIds: args.seatedPersonaIds,
    rounds: args.rounds,
    factions: args.factions,
    redTeam: args.redTeam,
    distribution: args.distribution,
    certificate: args.certificate,
    councils: args.councils,
    createdAt: args.createdAt,
  };
  const digest = sha256Canonical(record);
  const id = contentId('cade', record);
  let signature: string | undefined;
  let publicKeyPem: string | undefined;
  if (sign) {
    const sig = signDigest(digest);
    if (sig.algorithm !== 'none') {
      signature = sig.value;
      publicKeyPem = sig.publicKeyPem;
    }
  }
  return { id, issueId: args.issue.id, digest, signature, publicKeyPem, record };
}

function clamp01(x: number): number {
  return Math.max(0, Math.min(1, x));
}
