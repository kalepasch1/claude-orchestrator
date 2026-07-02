// GET /api/fleet/amendments — the self-rewriting constitution: patterns Bear consistently
// rejects, drafted as materiality-gated amendment proposals (never auto-applied).
import { proposeAmendments } from '@darwin/kernel/fleetAdmin';
import { serviceClient } from '../../utils/fleetSupabase';
import { resolvedHistory } from '../../utils/fleetReads';

export default defineEventHandler(async () => {
  const sb = serviceClient();
  const history = await resolvedHistory(sb);
  const proposals = proposeAmendments(history);
  return { proposals, total: proposals.length, basisSample: history.length };
});
