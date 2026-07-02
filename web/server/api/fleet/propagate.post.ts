// POST /api/fleet/propagate  { fixingActionId }
// Given an action that resolved one event of a cross-app incident, propose the SAME
// remediation to every other app whose open event shares the incident's root-cause
// signal. One approval → N apps fixed. Returns proposals for review (not auto-ingested).
import { correlateEvents, propagateFix, type AdminAction, type AdminEvent } from '@darwin/kernel/fleetAdmin';
import { serviceClient } from '../../utils/fleetSupabase';

export default defineEventHandler(async (event) => {
  const secret = getHeader(event, 'x-fleet-secret') ?? '';
  if ((process.env.FLEET_SHARED_SECRET ?? '') && secret !== process.env.FLEET_SHARED_SECRET) {
    throw createError({ statusCode: 401, message: 'bad_fleet_secret' });
  }
  const { fixingActionId } = (await readBody(event)) as { fixingActionId?: string };
  if (!fixingActionId) throw createError({ statusCode: 400, message: 'fixingActionId required' });

  const sb = serviceClient();
  const { data: actRow } = await sb.from('fleet_admin_actions').select('*').eq('id', fixingActionId).maybeSingle();
  if (!actRow) throw createError({ statusCode: 404, message: 'action not found' });

  const { data: evRows } = await sb
    .from('fleet_admin_events')
    .select('id,product,domain,category,severity,title,summary,subject_id,details,at')
    .order('at', { ascending: false })
    .limit(2000);
  const events = (evRows ?? []).map((r: any) => ({ ...r, subjectId: r.subject_id })) as AdminEvent[];

  const fixing: AdminAction = {
    id: actRow.id, product: actRow.product, domain: actRow.domain, type: actRow.type, actor: actRow.actor,
    eventId: actRow.event_id ?? undefined, subjectId: actRow.subject_id ?? undefined,
    amountUsd: actRow.amount_usd ?? undefined, confidence: Number(actRow.confidence),
    reversibility: actRow.reversibility, blastRadius: actRow.blast_radius, intent: actRow.intent,
    params: actRow.params ?? {}, at: actRow.created_at,
  };

  const incidents = correlateEvents(events);
  const incident = incidents.find((i) => fixing.eventId && i.events.includes(fixing.eventId));
  if (!incident) return { proposals: [], total: 0, reason: 'fixing action not part of a correlated incident' };

  const proposals = propagateFix(incident, fixing, events);
  return { incidentId: incident.id, proposals, total: proposals.length };
});
