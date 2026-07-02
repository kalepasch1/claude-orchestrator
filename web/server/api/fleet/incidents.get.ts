// GET /api/fleet/incidents?windowMin=15 — cross-app incident correlation: group events
// from different apps that share a root-cause signal into ONE incident.
import { correlateEvents, type AdminEvent } from '@darwin/kernel/fleetAdmin';
import { serviceClient } from '../../utils/fleetSupabase';

export default defineEventHandler(async (event) => {
  const windowMs = Number(getQuery(event).windowMin ?? 15) * 60 * 1000;
  const sb = serviceClient();
  const { data } = await sb
    .from('fleet_admin_events')
    .select('id,product,domain,category,severity,title,summary,subject_id,details,at')
    .order('at', { ascending: false })
    .limit(2000);
  const events = (data ?? []).map((r: any) => ({ ...r, subjectId: r.subject_id })) as AdminEvent[];
  const incidents = correlateEvents(events, windowMs);
  return { incidents, total: incidents.length };
});
