// GET /api/fleet/economic-autopilot — solves the autonomy dial against a realized-cost
// loss function: which action-types are cheaper to auto-run (within the FP tolerance +
// domain ceiling), and the total $ saved. A materiality-gated tuning proposal.
import { optimizeDial, DEFAULT_DOMAIN_POLICIES, type TypeCostInput, type AdminDomain } from '@darwin/kernel/fleetAdmin';
import { serviceClient } from '../../utils/fleetSupabase';
import { ledgerEntries } from '../../utils/fleetReads';

export default defineEventHandler(async () => {
  const sb = serviceClient();
  const entries = await ledgerEntries(sb);
  const inputs: TypeCostInput[] = entries
    .filter((e) => e.total > 0)
    .map((e) => ({ domain: e.domain, actionType: e.actionType, volume: e.total, cleanRate: e.cleanApprovals / e.total }));
  const dial = optimizeDial(inputs, (d: AdminDomain) => DEFAULT_DOMAIN_POLICIES[d].ceiling);
  return dial;
});
