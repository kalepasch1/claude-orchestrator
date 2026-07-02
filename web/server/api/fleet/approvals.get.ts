// GET /api/fleet/approvals?status=pending — the single fleet-wide human queue.
// Ordered by Bear's LEARNED attention (approver model), not just raw priority: things he
// scrutinizes or is unlikely to rubber-stamp float up; reliable rubber-stamps sink (they
// are promotion candidates anyway). Each row carries a predicted decision + prefill hint.
import { serviceClient } from '../../utils/fleetSupabase';
import { buildApproverProfile, predictDecision, prefillEdit, orderQueueForApprover } from '@darwin/kernel/fleetAdmin';
import { approverDecisions } from '../../utils/fleetReads';

export default defineEventHandler(async (event) => {
  const status = (getQuery(event).status as string) ?? 'pending';
  const sb = serviceClient();
  const [{ data, error }, decisions] = await Promise.all([
    sb.from('fleet_approvals').select('*').eq('status', status).order('priority', { ascending: false }).limit(200),
    approverDecisions(sb),
  ]);
  if (error) throw createError({ statusCode: 500, message: error.message });

  const rows = data ?? [];
  const profile = buildApproverProfile(decisions);

  // Derive each row's (domain, actionType) from its title suffix `product · domain · type`.
  const enriched = rows.map((r: any) => {
    const parts = String(r.title ?? '').split('·').map((s) => s.trim());
    const domain = r.domain;
    const actionType = parts[2] ?? '';
    const prediction = predictDecision(profile, domain, actionType);
    return { ...r, actionType, prediction, prefill: prefillEdit(profile, domain, actionType) };
  });

  const ordered = orderQueueForApprover(profile, enriched as any);
  return { items: ordered, total: ordered.length, approverModelReady: profile.totalDecisions >= 3 };
});
