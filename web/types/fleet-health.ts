import type { Ref } from 'vue'

/** Exact JSON returned by GET /api/fleet-health. */
export interface FleetHealth {
  db_up: boolean
  status: 'healthy' | 'degraded' | 'down' | 'unknown'
  heartbeat_seconds: number | null
  machines_live: number
  contract_consistent: boolean
}

/** Public composable contract used by the authenticated dashboard. */
export interface FleetHealthComposable {
  dbUp: Ref<boolean | null>
  health: Ref<FleetHealth | null>
  refresh: () => Promise<void>
}
