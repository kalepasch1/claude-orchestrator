// POST /api/fleet/portfolio-objective  { goal, constraints? }
// Steer the whole plane toward one business objective: choose the dial from the Pareto frontier
// that maximizes the goal (min_cost | max_autonomy | min_risk | balanced) under hard constraints.
import { generateDialCandidates, selectPortfolioConfig, DEFAULT_DOMAIN_POLICIES, type TypeCostInput, type AdminDomain, type PortfolioObjective } from '@darwin/kernel/fleetAdmin';
import { serviceClient } from '../../utils/fleetSupabase';
import { ledgerEntries } from '../../utils/fleetReads';

export default defineEventHandler(async (event) => {
  const objective = (await readBody(event)) as PortfolioObjective;
  if (!objective?.goal) throw createError({ statusCode: 400, message: 'goal required' });
  const sb = serviceClient();
  const inputs: TypeCostInput[] = (await ledgerEntries(sb)).filter((e) => e.total > 0).map((e) => ({ domain: e.domain, actionType: e.actionType, volume: e.total, cleanRate: e.cleanApprovals / e.total }));
  const candidates = generateDialCandidates(inputs, (d: AdminDomain) => DEFAULT_DOMAIN_POLICIES[d].ceiling);
  return selectPortfolioConfig(candidates, objective);
});
