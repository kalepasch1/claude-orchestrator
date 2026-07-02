// GET /api/fleet/federated-precedent — privacy-walled cross-app precedent (k-anonymity +
// DP). A new app can borrow these priors to launch already-smart. Raw decisions never leave
// their app; only DP-noised aggregate clean-rates are shared.
import { buildFederatedPrecedent, seedFromFederated } from '@darwin/kernel/fleetAdmin';
import { serviceClient } from '../../utils/fleetSupabase';
import { appTypeStats } from '../../utils/fleetReads';

export default defineEventHandler(async () => {
  const sb = serviceClient();
  const precedent = buildFederatedPrecedent(await appTypeStats(sb));
  return { precedent, seedForNewApp: seedFromFederated(precedent), total: precedent.length };
});
