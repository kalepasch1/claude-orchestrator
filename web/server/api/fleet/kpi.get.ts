// GET /api/fleet/kpi — the north-star: answered-from-plane rate (autonomy %) with a
// by-domain breakdown and a period-over-period trend (this fortnight vs. the last).
import { computeNorthStar, type RoutedActionSummary } from '@darwin/kernel/fleetAdmin';
import { serviceClient } from '../../utils/fleetSupabase';

export default defineEventHandler(async () => {
  const sb = serviceClient();
  const { data } = await sb
    .from('fleet_admin_actions')
    .select('domain,decision,tier,created_at')
    .not('decision', 'is', null)
    .order('created_at', { ascending: false })
    .limit(10000);
  const actions: RoutedActionSummary[] = (data ?? []).map((r: any) => ({
    domain: r.domain, decision: r.decision, tier: r.tier ?? 'human', at: r.created_at,
  }));
  const splitAt = new Date(Date.now() - 14 * 24 * 3600 * 1000).toISOString();
  return computeNorthStar(actions, splitAt);
});
