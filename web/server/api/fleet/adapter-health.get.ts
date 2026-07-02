// GET /api/fleet/adapter-health — self-healing adapters: which apps' execute endpoints are
// failing, with a drafted code-fix task for the orchestrator runner on any that are failing.
import { assessAdapterHealth } from '@darwin/kernel/fleetAdmin';
import { serviceClient } from '../../utils/fleetSupabase';
import { executionOutcomes } from '../../utils/fleetReads';

export default defineEventHandler(async () => {
  const sb = serviceClient();
  const reports = assessAdapterHealth(await executionOutcomes(sb));
  return { reports, failing: reports.filter((r) => r.status === 'failing') };
});
