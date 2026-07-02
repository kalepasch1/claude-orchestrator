// GET /api/fleet/pareto-tuning — the trade-off frontier across cost / risk / approver-load /
// latency, so Bear picks a POINT on the curve instead of trusting one weighting.
import { generateDialCandidates, paretoFrontier, DEFAULT_DOMAIN_POLICIES, type TypeCostInput, type AdminDomain } from '@darwin/kernel/fleetAdmin';
import { serviceClient } from '../../utils/fleetSupabase';
import { ledgerEntries } from '../../utils/fleetReads';

export default defineEventHandler(async () => {
  const sb = serviceClient();
  const entries = await ledgerEntries(sb);
  const inputs: TypeCostInput[] = entries.filter((e) => e.total > 0).map((e) => ({ domain: e.domain, actionType: e.actionType, volume: e.total, cleanRate: e.cleanApprovals / e.total }));
  const candidates = generateDialCandidates(inputs, (d: AdminDomain) => DEFAULT_DOMAIN_POLICIES[d].ceiling);
  const { frontier, dominated } = paretoFrontier(candidates);
  return { frontier, dominated, total: candidates.length };
});
