/**
 * Compliance SKU — package the signed autonomy attestation + a sample of per-decision proof
 * packs into an external-facing "Provably-Governed AI Operations" report other regulated
 * companies would pay for. The admin layer becomes revenue, not just cost avoidance. Pure +
 * zero-dep; the report embeds everything a third party needs to verify it offline.
 */
import type { AutonomyAttestation } from './fleetAttestation.ts';
import { verifyAutonomyAttestation } from './fleetAttestation.ts';
import type { DecisionProof } from './proofPack.ts';
import { verifyDecisionProof } from './proofPack.ts';

export interface ComplianceReport {
  orgName: string;
  issuedAt: string;
  periodDays: number;
  attestation: AutonomyAttestation;
  attestationValid: boolean;
  attestationMeetsBar: boolean;
  /** a representative sample of signed per-decision proofs */
  sampleProofs: DecisionProof[];
  sampleAllValid: boolean;
  headline: string;
}

/** Assemble the sellable report from an attestation + sample proofs. */
export function buildComplianceReport(params: {
  orgName: string;
  attestation: AutonomyAttestation;
  sampleProofs: DecisionProof[];
}): ComplianceReport {
  const attCheck = verifyAutonomyAttestation(params.attestation);
  const sampleAllValid = params.sampleProofs.every((p) => verifyDecisionProof(p).valid);
  return {
    orgName: params.orgName,
    issuedAt: new Date().toISOString(),
    periodDays: params.attestation.periodDays,
    attestation: params.attestation,
    attestationValid: attCheck.valid,
    attestationMeetsBar: attCheck.meetsBar,
    sampleProofs: params.sampleProofs,
    sampleAllValid,
    headline: `${params.orgName}: ${Math.round(params.attestation.answeredFromPlaneRate * 100)}% of admin decisions governed autonomously, ` +
      `${params.attestation.regressions} regressions, red-team envelope ${params.attestation.redTeamResidualHarm} — ` +
      `${attCheck.meetsBar ? 'meets the trust bar' : 'below the trust bar'}, cryptographically verifiable.`,
  };
}

/** Render the report as external-facing Markdown (the deliverable a buyer/auditor reads). */
export function renderComplianceReportMarkdown(r: ComplianceReport): string {
  const a = r.attestation;
  return [
    `# Provably-Governed AI Operations — ${r.orgName}`,
    ``,
    `**Issued:** ${r.issuedAt}  ·  **Period:** ${r.periodDays} days`,
    ``,
    `## Attestation`,
    `- Answered-from-plane rate: **${Math.round(a.answeredFromPlaneRate * 100)}%** over ${a.totalDecisions} decisions`,
    `- Regressions in period: **${a.regressions}**`,
    `- Adversarial red-team residual harm: **${a.redTeamResidualHarm}** (safe envelope < 0.30)`,
    `- Receipt chain verified: **${a.receiptsChainVerified ? 'yes' : 'no'}**`,
    `- Signature valid: **${r.attestationValid ? 'yes' : 'NO'}**  ·  Meets trust bar: **${r.attestationMeetsBar ? 'yes' : 'no'}**`,
    ``,
    `## Sample of signed per-decision proofs (${r.sampleProofs.length})`,
    ...r.sampleProofs.map((p) => `- \`${p.action.product}/${p.action.domain}/${p.action.type}\` → ${p.decision}/${p.tier} · receipt \`${p.receipt.digest.slice(0, 16)}…\``),
    `- All sampled proofs verify offline: **${r.sampleAllValid ? 'yes' : 'NO'}**`,
    ``,
    `## How to verify`,
    `Every artifact here is content-addressed and Ed25519-signed. Recompute the SHA-256 over each`,
    `body and check the signature against the embedded public key — no database or shared secret`,
    `required. The attestation and each proof are independently verifiable by any third party.`,
    ``,
    `> ${r.headline}`,
  ].join('\n');
}
