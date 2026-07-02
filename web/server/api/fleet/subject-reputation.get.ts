// GET /api/fleet/subject-reputation — fleet-wide subject reputation fused from every app's
// signals (fraud/chargeback/abuse vs. verified/good-standing), riskiest first. A bad actor
// flagged in one app is flagged everywhere.
import { fuseReputation, type SubjectSignal } from '@darwin/kernel/fleetAdmin';
import { serviceClient } from '../../utils/fleetSupabase';

const KIND: Record<string, SubjectSignal['kind']> = {
  fraud_signal: 'fraud', chargeback: 'chargeback', abuse_report: 'abuse', moderation_appeal: 'dispute', kyc_identity: 'verified',
};

export default defineEventHandler(async () => {
  const sb = serviceClient();
  const { data } = await sb
    .from('fleet_admin_events')
    .select('product,category,subject_id,at')
    .not('subject_id', 'is', null)
    .limit(5000);
  const signals: SubjectSignal[] = (data ?? [])
    .filter((r: any) => KIND[r.category])
    .map((r: any) => ({ subjectId: r.subject_id, product: r.product, kind: KIND[r.category]!, at: r.at }));
  const reputations = fuseReputation(signals);
  return { reputations, atRisk: reputations.filter((r) => r.score < 0.3) };
});
