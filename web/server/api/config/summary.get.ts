// GET /api/config/summary — one call backing the config-change monitoring dashboard.
//
// The per-request endpoints (requests.get, :id/approvals.get) already existed but nothing
// on the web rendered them, so the state of a config change was only observable by hand-
// querying Supabase. This aggregates the three things an operator actually watches —
// what is pending on them, what has synchronized, and what errored — into a single
// poll-friendly payload so the dashboard needs one request per refresh, not one per card.
import { serviceClient } from '../../utils/fleetSupabase';
import { summarizeConfigChanges } from '../../utils/configChangeSummary';

export default defineEventHandler(async () => {
  const sb = serviceClient();

  const [reqRes, apprRes] = await Promise.all([
    sb.from('config_requests').select('*').order('created_at', { ascending: false }).limit(200),
    sb.from('config_approvals').select('*').order('decided_at', { ascending: false }).limit(100),
  ]);

  // Fail soft per-source: a dashboard that renders the half it could read is more useful
  // than one that 500s because a single table was briefly unavailable.
  const errors: string[] = [];
  if (reqRes.error) errors.push(`config_requests: ${reqRes.error.message}`);
  if (apprRes.error) errors.push(`config_approvals: ${apprRes.error.message}`);

  return summarizeConfigChanges(reqRes.data ?? [], apprRes.data ?? [], Date.now(), errors);
});
