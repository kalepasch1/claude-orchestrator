/**
 * GET /api/fleet/analytics?rangeDays=7&sync=false
 *
 * Returns fleet-wide Vercel Web Analytics for all apps.
 * Pass ?sync=true to also write the metrics into the telemetry lake.
 */
import { fetchFleetAnalytics, syncToTelemetryLake } from '../../utils/vercelAnalytics'

export default defineEventHandler(async (event) => {
  const query = getQuery(event)
  const rangeDays = Math.min(Math.max(Number(query.rangeDays) || 7, 1), 90)
  const sync = query.sync === 'true' || query.sync === '1'

  const fleet = await fetchFleetAnalytics(rangeDays)

  if (sync) {
    const { synced } = await syncToTelemetryLake(rangeDays)
    return { ...fleet, telemetrySynced: synced }
  }

  return fleet
})
