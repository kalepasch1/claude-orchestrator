// POST /api/fleet/world-model  { product, expected: ExpectedType[] }
// Pre-launch simulator: project a new app's day-one autonomy rate, blast, and treasury from
// its expected event mix + the federated priors it would borrow. Quantifies launch decisions.
import { projectNewApp, buildFederatedPrecedent, seedFromFederated, DEFAULT_DOMAIN_POLICIES, type ExpectedType, type AdminDomain } from '@darwin/kernel/fleetAdmin';
import { serviceClient } from '../../utils/fleetSupabase';
import { appTypeStats } from '../../utils/fleetReads';

export default defineEventHandler(async (event) => {
  const body = (await readBody(event)) as { product?: string; expected?: ExpectedType[] };
  if (!body?.product || !Array.isArray(body.expected)) throw createError({ statusCode: 400, message: 'product + expected[] required' });

  const sb = serviceClient();
  const federatedSeed = seedFromFederated(buildFederatedPrecedent(await appTypeStats(sb)));
  return projectNewApp({ product: body.product, expected: body.expected, federatedSeed, ceilingOf: (d: AdminDomain) => DEFAULT_DOMAIN_POLICIES[d].ceiling });
});
