// POST /api/fleet/time-travel  { fromIso, toIso }
// Rewind: replay every decision in a past window under the CURRENT law and report what the
// plane would decide now — the basis for auditing drift and rolling back a culpable change.
import { replayWindow, fleetAdminConstitution, type AdminAction } from '@darwin/kernel/fleetAdmin';
import { serviceClient } from '../../utils/fleetSupabase';

export default defineEventHandler(async (event) => {
  const { fromIso, toIso } = (await readBody(event)) as { fromIso?: string; toIso?: string };
  if (!fromIso || !toIso) throw createError({ statusCode: 400, message: 'fromIso + toIso required' });
  const sb = serviceClient();
  const { data } = await sb
    .from('fleet_admin_actions')
    .select('id,product,domain,type,actor,subject_id,amount_usd,confidence,reversibility,blast_radius,intent,created_at')
    .gte('created_at', fromIso).lt('created_at', toIso).limit(5000);
  const actions: AdminAction[] = (data ?? []).map((r: any) => ({
    id: r.id, product: r.product, domain: r.domain, type: r.type, actor: r.actor, subjectId: r.subject_id ?? undefined,
    amountUsd: r.amount_usd ?? undefined, confidence: Number(r.confidence), reversibility: r.reversibility,
    blastRadius: r.blast_radius, intent: r.intent, at: r.created_at,
  }));
  return replayWindow(actions, { fromIso, toIso }, { constitution: fleetAdminConstitution() });
});
