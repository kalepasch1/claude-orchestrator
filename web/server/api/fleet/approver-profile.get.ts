// GET /api/fleet/approver-profile — the plane's learned model of Bear: per-type approval
// rates, domains he always scrutinizes, active hours, and common edits.
import { buildApproverProfile } from '@darwin/kernel/fleetAdmin';
import { serviceClient } from '../../utils/fleetSupabase';
import { approverDecisions } from '../../utils/fleetReads';

export default defineEventHandler(async () => {
  const sb = serviceClient();
  const profile = buildApproverProfile(await approverDecisions(sb));
  return profile;
});
