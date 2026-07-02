// GET /api/fleet/dependency-queue — the pending queue bundled by subject: related decisions
// on the same user/account are collapsed so Bear decides the subject's fate once.
import { bundleQueue } from '@darwin/kernel/fleetAdmin';
import { serviceClient } from '../../utils/fleetSupabase';
import { pendingDecisions } from '../../utils/fleetReads';

export default defineEventHandler(async () => {
  const sb = serviceClient();
  const { bundles, standalone } = bundleQueue(await pendingDecisions(sb));
  return { bundles, standalone, bundledSubjects: bundles.length };
});
