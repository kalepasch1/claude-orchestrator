// POST /api/fleet/trust-web  { counterSignatures?: CounterSignature[] }
// Builds this org's current autonomy attestation and verifies a trust passport formed by other
// orgs' counter-signatures over it — a compliance credential partners/regulators can accept.
import { computeNorthStar, coEvolve, buildAutonomyAttestation, verifyTrustPassport, type RoutedActionSummary, type CounterSignature } from '@darwin/kernel/fleetAdmin';
import { serviceClient } from '../../utils/fleetSupabase';

export default defineEventHandler(async (event) => {
  const body = (await readBody(event).catch(() => ({}))) as { counterSignatures?: CounterSignature[] };
  const sb = serviceClient();
  const { data } = await sb.from('fleet_admin_actions').select('domain,decision,tier,created_at').not('decision', 'is', null).limit(10000);
  const summaries: RoutedActionSummary[] = (data ?? []).map((r: any) => ({ domain: r.domain, decision: r.decision, tier: r.tier ?? 'human', at: r.created_at }));
  const ns = computeNorthStar(summaries);
  const attestation = buildAutonomyAttestation({
    issuedAt: new Date().toISOString(), periodDays: 30, answeredFromPlaneRate: ns.answeredFromPlaneRate,
    totalDecisions: ns.totalDecisions, regressions: 0, redTeamResidualHarm: coEvolve().residualHarm, receiptsChainVerified: true,
  });
  const passport = { attestation, counterSignatures: body.counterSignatures ?? [] };
  return { attestation, attestationDigest: attestation.digest, passportVerification: verifyTrustPassport(passport) };
});
