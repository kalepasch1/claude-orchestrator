import { scanAllApps, getRecentAlerts } from '~/server/utils/anomalyRadar'

export default defineEventHandler(async (event) => {
  const query = getQuery(event)
  const useCached = query.cached === 'true'

  if (useCached) {
    const { alerts, lastScan } = getRecentAlerts()
    return { alerts, lastScan, cached: true }
  }

  try {
    const alerts = await scanAllApps()
    return { alerts, lastScan: new Date().toISOString(), cached: false }
  } catch (e: any) {
    console.error('[AnomalyRadar] scan error:', e)
    throw createError({
      statusCode: 500,
      message: e.message || 'Anomaly scan failed',
    })
  }
})
