/**
 * Fleet Admin Control Plane — the orchestration loop now lives in the kernel
 * (zero-dep + unit-tested). This module just re-exports it so the Nitro endpoints
 * have a stable local import, and `fleetSupabase.ts` supplies the Supabase/fetch
 * ports it runs on.
 */
export {
  governAndRoute,
  ingestEvent,
  handleDecision,
  planeChainFor,
  type PlanePorts,
  type PlaneConfig,
} from '@darwin/kernel/fleetAdmin';
