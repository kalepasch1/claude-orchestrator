// GET /api/fleet/proof/:actionId — regulator-grade, offline-verifiable proof for a single
// admin decision: constitution version + autonomy computation + CADE deliberation + signed
// receipt, plus a self-check. The artifact an auditor/regulator/acquirer can validate with
// no DB and no secret.
import { governFleetAction, fleetAdminConstitution, buildApprovalCard, buildDecisionProof, verifyDecisionProof, type AdminAction } from '@darwin/kernel/fleetAdmin';
import { serviceClient } from '../../../utils/fleetSupabase';

export default defineEventHandler(async (event) => {
  const actionId = getRouterParam(event, 'actionId')!;
  const sb = serviceClient();
  const { data: r } = await sb.from('fleet_admin_actions').select('*').eq('id', actionId).maybeSingle();
  if (!r) throw createError({ statusCode: 404, message: 'action not found' });

  const action: AdminAction = {
    id: r.id, product: r.product, domain: r.domain, type: r.type, actor: r.actor,
    eventId: r.event_id ?? undefined, subjectId: r.subject_id ?? undefined, amountUsd: r.amount_usd ?? undefined,
    confidence: Number(r.confidence), reversibility: r.reversibility, blastRadius: r.blast_radius,
    intent: r.intent, params: r.params ?? {}, ifNotDone: r.if_not_done ?? undefined, at: r.created_at,
  };

  // Re-derive the verdict deterministically under the recorded constitution version.
  const constitution = fleetAdminConstitution();
  const verdict = governFleetAction({ action, constitution });
  const card = buildApprovalCard({ action, verdict, callbackUrl: '' });
  const proof = buildDecisionProof({ action, verdict, constitutionVersion: constitution.version, deliberation: card.deliberation });

  return { proof, verification: verifyDecisionProof(proof) };
});
