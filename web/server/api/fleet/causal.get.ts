// GET /api/fleet/causal — the learned causal graph over event categories (A causes B),
// plus the true root-cause event for each current cross-app incident.
import { learnCausalGraph, correlateEvents, rootCause, type AdminEvent } from '@darwin/kernel/fleetAdmin';
import { serviceClient } from '../../utils/fleetSupabase';

export default defineEventHandler(async () => {
  const sb = serviceClient();
  const { data } = await sb
    .from('fleet_admin_events')
    .select('id,product,domain,category,severity,title,summary,subject_id,details,at')
    .order('at', { ascending: false })
    .limit(3000);
  const events = (data ?? []).map((r: any) => ({ ...r, subjectId: r.subject_id })) as AdminEvent[];
  const graph = learnCausalGraph(events);
  const incidents = correlateEvents(events).map((inc) => {
    const evs = inc.events.map((id) => events.find((e) => e.id === id)!).filter(Boolean);
    const rc = rootCause(evs, graph);
    return { id: inc.id, products: inc.products, rootCause: rc ? { id: rc.id, product: rc.product, category: rc.category, at: rc.at } : null };
  });
  return { graph, incidents, edges: graph.length };
});
