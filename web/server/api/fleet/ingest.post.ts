// POST /api/fleet/ingest  { event: AdminEvent, proposedActions: AdminAction[] }
// Apps (or their adapters / domain swarms) push admin events + proposed remediations
// here. The plane governs each, auto-runs the safe ones, and raises approvals for the
// rest (mirroring them into Bear's Smarter inbox).
import { ingestEvent, type PlaneConfig } from '../../utils/fleetPlane';
import { serviceClient, supabasePorts } from '../../utils/fleetSupabase';
import { ingestTelemetryEvent } from '../../utils/telemetryLake';

export default defineEventHandler(async (event) => {
  const secret = getHeader(event, 'x-fleet-secret') ?? '';
  if ((process.env.FLEET_SHARED_SECRET ?? '') && secret !== process.env.FLEET_SHARED_SECRET) {
    throw createError({ statusCode: 401, message: 'bad_fleet_secret' });
  }
  const body = await readBody(event);
  if (!body?.event) throw createError({ statusCode: 400, message: 'event required' });

  const ports = supabasePorts(serviceClient());
  const cfg: PlaneConfig = {
    callbackUrl: `${process.env.ORCHESTRATOR_BASE_URL ?? ''}/api/fleet/callback`,
    // Onboard a new app safely: set FLEET_SHADOW_MODE=true to govern + record without executing
    // or bugging a human, until the agreement rate justifies granting real autonomy.
    shadowMode: process.env.FLEET_SHADOW_MODE === 'true',
  };
  const { verdicts } = await ingestEvent(ports, cfg, body.event, body.proposedActions ?? []);
  // Telemetry is observational and must never make the governed control-plane
  // mutation fail if the analytics table is temporarily unavailable.
  await ingestTelemetryEvent(body.event).catch(() => undefined);
  return {
    ok: true,
    routed: verdicts.map((v) => ({ decision: v.decision, tier: v.tier, summary: v.summary })),
  };
});
