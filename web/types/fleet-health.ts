import type { Ref } from 'vue'

/** Exact JSON returned by GET /api/fleet-health. */
export interface FleetHealth {
  db_up: boolean
}

/** Public composable contract used by the authenticated dashboard. */
export interface FleetHealthComposable {
  dbUp: Ref<boolean | null>
  refresh: () => Promise<void>
}
