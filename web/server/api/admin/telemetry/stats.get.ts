import { getRetentionStats, getMetricNames } from '~/server/utils/telemetryLake'

export default defineEventHandler(async () => {
  try {
    const [stats, metricNames] = await Promise.all([
      getRetentionStats(),
      getMetricNames(),
    ])

    return {
      ...stats,
      metricNames,
      timestamp: new Date().toISOString(),
    }
  } catch (e: any) {
    console.error('[TelemetryLake] stats error:', e)
    throw createError({
      statusCode: 500,
      message: e.message || 'Failed to fetch telemetry stats',
    })
  }
})
