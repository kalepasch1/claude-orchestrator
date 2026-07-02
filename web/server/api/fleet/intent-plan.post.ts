// POST /api/fleet/intent-plan  { goal, subjectId?, product, amountUsd?, exemplars? }
// Learned intent planner: compose an open-ended goal into a bounded step plan from past
// successful exemplars (or a template), then govern the whole plan as ONE decision.
import { composeIntentPlan, governIntent } from '@darwin/kernel/fleetAdmin';

export default defineEventHandler(async (event) => {
  const secret = getHeader(event, 'x-fleet-secret') ?? '';
  if ((process.env.FLEET_SHARED_SECRET ?? '') && secret !== process.env.FLEET_SHARED_SECRET) {
    throw createError({ statusCode: 401, message: 'bad_fleet_secret' });
  }
  const body = (await readBody(event)) as any;
  if (!body?.goal || !body?.product) throw createError({ statusCode: 400, message: 'goal + product required' });
  const composed = composeIntentPlan({ goal: body.goal, subjectId: body.subjectId, product: body.product, amountUsd: body.amountUsd, exemplars: body.exemplars });
  const verdict = governIntent({ plan: composed.plan });
  return { composed, verdict };
});
