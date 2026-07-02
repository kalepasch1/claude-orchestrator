// POST /api/fleet/incident-commander  { query }
// Conversational incident command: ask in English ("root cause of the supabase-east
// incident?", "what's the one fix?") and get a causal-graph-backed answer + one-tap fix.
import { commandIncident, type AdminEvent } from '@darwin/kernel/fleetAdmin';
import { serviceClient } from '../../utils/fleetSupabase';

export default defineEventHandler(async (event) => {
  const { query } = (await readBody(event)) as { query?: string };
  if (!query) throw createError({ statusCode: 400, message: 'query required' });
  const sb = serviceClient();
  const { data } = await sb
    .from('fleet_admin_events')
    .select('id,product,domain,category,severity,title,summary,subject_id,details,at')
    .order('at', { ascending: false })
    .limit(2000);
  const events = (data ?? []).map((r: any) => ({ ...r, subjectId: r.subject_id })) as AdminEvent[];
  return commandIncident(query, events);
});
