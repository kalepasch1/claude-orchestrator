import { scanAllApps } from '~/server/utils/anomalyRadar'

export default defineEventHandler(async () => {
  try {
    const alerts = await scanAllApps()
    return {
      alerts,
      lastScan: new Date().toISOString(),
      scannedApps: alerts.length > 0
        ? [...new Set(alerts.map(a => a.app))]
        : [],
      summary: {
        total: alerts.length,
        critical: alerts.filter(a => a.severity === 'critical').length,
        warning: alerts.filter(a => a.severity === 'warning').length,
        info: alerts.filter(a => a.severity === 'info').length,
      },
    }
  } catch (e: any) {
    console.error('[AnomalyRadar] full scan error:', e)
    throw createError({
      statusCode: 500,
      message: e.message || 'Full anomaly scan failed',
    })
  }
})
