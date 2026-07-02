// POST /api/fleet/market-economics  { stakes: StakePosition[], outcomes: InstallOutcome[] }
// Settle a marketplace round: revenue-share good installs, slash + downrate bad ones, and rank
// publishers by reputation × net earnings. Turns governance artifacts into a priced network.
import { settleMarket, type StakePosition, type InstallOutcome } from '@darwin/kernel/fleetAdmin';

export default defineEventHandler(async (event) => {
  const body = (await readBody(event)) as { stakes?: StakePosition[]; outcomes?: InstallOutcome[] };
  if (!Array.isArray(body?.stakes) || !Array.isArray(body?.outcomes)) throw createError({ statusCode: 400, message: 'stakes[] + outcomes[] required' });
  return settleMarket(body.stakes, body.outcomes);
});
