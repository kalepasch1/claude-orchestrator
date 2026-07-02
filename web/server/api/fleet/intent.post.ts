// POST /api/fleet/intent  { goal, subjectId?, product, amountUsd? }
// Intent-level autonomy: plan a multi-step remediation for a goal and govern it as ONE
// decision, with the constitution bounding the whole plan. Returns the plan + the single verdict.
import { planIntent, governIntent } from '@darwin/kernel/fleetAdmin';

export default defineEventHandler(async (event) => {
  const secret = getHeader(event, 'x-fleet-secret') ?? '';
  if ((process.env.FLEET_SHARED_SECRET ?? '') && secret !== process.env.FLEET_SHARED_SECRET) {
    throw createError({ statusCode: 401, message: 'bad_fleet_secret' });
  }
  const body = (await readBody(event)) as { goal?: string; subjectId?: string; product?: string; amountUsd?: number };
  if (!body?.goal || !body?.product) throw createError({ statusCode: 400, message: 'goal + product required' });
  const plan = planIntent({ goal: body.goal, subjectId: body.subjectId, product: body.product as any, amountUsd: body.amountUsd });
  const verdict = governIntent({ plan });
  return { plan, verdict };
});
