// POST /api/fleet/federation  { signals: FederatedSignal[], allPlaneIds?: string[] }
// Merge cross-plane threat signals into federated threats (elevated when seen on >=2 planes) and
// list the planes to pre-emptively warn. An attack learned anywhere is defended everywhere.
import { mergeFederatedThreats, planesToWarn, type FederatedSignal } from '@darwin/kernel/fleetAdmin';

export default defineEventHandler(async (event) => {
  const body = (await readBody(event)) as { signals?: FederatedSignal[]; allPlaneIds?: string[] };
  if (!Array.isArray(body?.signals)) throw createError({ statusCode: 400, message: 'signals[] required' });
  const threats = mergeFederatedThreats(body.signals);
  const withWarn = threats.map((t) => ({ ...t, warn: body.allPlaneIds ? planesToWarn(t, body.allPlaneIds) : [] }));
  return { threats: withWarn, elevated: withWarn.filter((t) => t.elevated).length };
});
