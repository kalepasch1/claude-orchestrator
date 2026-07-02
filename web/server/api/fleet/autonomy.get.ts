// GET /api/fleet/autonomy — the north-star: fleet-wide "% autonomous" (weighted by
// volume) + promotion candidates the flywheel has earned. Trends up as Bear resolves
// the queue; this is the number that proves the 5/95 dial is compounding.
import { serviceClient } from '../../utils/fleetSupabase';

export default defineEventHandler(async () => {
  const sb = serviceClient();
  const { data } = await sb.from('fleet_autonomy_ledger').select('*');
  const rows = data ?? [];
  let clean = 0;
  let total = 0;
  const candidates: any[] = [];
  for (const r of rows) {
    clean += r.clean_approvals;
    total += r.total;
    if (!r.promoted_at && r.streak >= 20 && r.total > 0 && r.clean_approvals / r.total >= 0.95) {
      candidates.push({ domain: r.domain, actionType: r.action_type, streak: r.streak, agreementRate: r.clean_approvals / r.total });
    }
  }
  return {
    autonomyRate: total ? clean / total : 0,
    totalDecisions: total,
    promotionCandidates: candidates.sort((a, b) => b.streak - a.streak),
    ledger: rows,
  };
});
