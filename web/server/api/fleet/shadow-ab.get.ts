// GET /api/fleet/shadow-ab — continuous constitution A/B: score the reigning champion (the
// current fleet law) against a tighter challenger on live traffic, and recommend promotion
// when the challenger wins by a margin. The law improves from production, not backtests.
import { runShadowAB, fleetAdminConstitution, factionVariants } from '@darwin/kernel/fleetAdmin';
import { serviceClient } from '../../utils/fleetSupabase';
import { historyWithOutcomes } from '../../utils/fleetReads';

export default defineEventHandler(async () => {
  const sb = serviceClient();
  const { actions, outcomes } = await historyWithOutcomes(sb);
  const base = fleetAdminConstitution();
  // Challenger = the "tight" faction variant (fewer routine allows → more escalation).
  const tight = factionVariants(base).find((f) => f.name === 'tight')!;
  const result = runShadowAB({
    champion: { name: 'champion (current law)', constitution: base },
    challenger: { name: 'challenger (tight)', constitution: tight.constitution },
    history: actions, outcomes,
  });
  return result;
});
