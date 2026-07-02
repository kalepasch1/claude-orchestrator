// GET /api/fleet/capabilities — the plane published as Darwin capabilities. Any orchestrator
// (this portfolio or a future one) discovers these and instantiates governed admin autonomy
// in one line, pointing at this deployment's /api/fleet/* endpoints.
import { fleetAdminCapabilities, fleetGovernCapabilityId } from '@darwin/kernel/fleetAdmin';

export default defineEventHandler(() => {
  const baseUrl = process.env.ORCHESTRATOR_BASE_URL ?? '';
  return { capabilities: fleetAdminCapabilities(baseUrl), governCapabilityId: fleetGovernCapabilityId(baseUrl) };
});
