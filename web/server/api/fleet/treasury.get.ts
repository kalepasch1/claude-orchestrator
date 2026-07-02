// GET /api/fleet/treasury — admin ops as a live P&L: approver time saved + incident loss
// avoided, netted against escalation cost, with a by-domain breakdown.
import { buildTreasury } from '@darwin/kernel/fleetAdmin';
import { serviceClient } from '../../utils/fleetSupabase';
import { settledDecisions } from '../../utils/fleetReads';

export default defineEventHandler(async () => {
  const sb = serviceClient();
  return buildTreasury(await settledDecisions(sb));
});
