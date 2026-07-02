// POST /api/fleet/treatment-effect  { observations: Observation[] }
// Difference-in-differences: the measured causal effect of a promotion on a metric (regret, cost)
// vs. untreated controls, net of the common trend. Grounds promotion decisions econometrically.
import { differenceInDifferences, type Observation } from '@darwin/kernel/fleetAdmin';

export default defineEventHandler(async (event) => {
  const body = (await readBody(event)) as { observations?: Observation[] };
  if (!Array.isArray(body?.observations)) throw createError({ statusCode: 400, message: 'observations[] required' });
  return differenceInDifferences(body.observations);
});
