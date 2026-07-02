// POST /api/fleet/callback  { decision: ApprovalDecision }
// Smarter posts Bear's decision back here. We verify the approver against the
// allowlist, execute if approved/modified, and feed the escalation-learning flywheel.
import { handleDecision } from '../../utils/fleetPlane';
import { serviceClient, supabasePorts } from '../../utils/fleetSupabase';

export default defineEventHandler(async (event) => {
  const secret = getHeader(event, 'x-fleet-secret') ?? '';
  if ((process.env.FLEET_SHARED_SECRET ?? '') && secret !== process.env.FLEET_SHARED_SECRET) {
    throw createError({ statusCode: 401, message: 'bad_fleet_secret' });
  }
  const body = await readBody(event);
  const decision = body?.decision;
  if (!decision?.actionId || !decision?.decision || !decision?.approver) {
    throw createError({ statusCode: 400, message: 'decision {actionId, decision, approver} required' });
  }
  const ports = supabasePorts(serviceClient());
  const result = await handleDecision(ports, { at: new Date().toISOString(), ...decision });
  return result;
});
