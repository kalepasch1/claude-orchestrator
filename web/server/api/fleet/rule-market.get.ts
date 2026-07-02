// GET /api/fleet/rule-market — competing constitutions (tight/balanced/lean) backtested
// against real history; the winner is the law best fitting your actual decisions.
import { factionVariants, runRuleMarket } from '@darwin/kernel/fleetAdmin';
import { serviceClient } from '../../utils/fleetSupabase';
import { historyWithOutcomes } from '../../utils/fleetReads';

export default defineEventHandler(async () => {
  const sb = serviceClient();
  const { actions, outcomes } = await historyWithOutcomes(sb);
  const result = runRuleMarket(factionVariants(), actions, outcomes);
  return { ...result, sample: actions.length };
});
