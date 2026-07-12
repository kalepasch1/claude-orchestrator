import { scanAllTrends, getCachedTrends } from '~/server/utils/predictiveDetection'

export default defineEventHandler(async (event) => {
  const query = getQuery(event)
  const appFilter = query.app as string | undefined
  const fresh = query.fresh === 'true'

  try {
    let trends = fresh ? await scanAllTrends() : getCachedTrends()

    // If no cached trends, run a scan
    if (!fresh && trends.length === 0) {
      trends = await scanAllTrends()
    }

    if (appFilter) {
      trends = trends.filter(t => t.app.toLowerCase() === appFilter.toLowerCase())
    }

    return { trends, total: trends.length }
  } catch (e: any) {
    console.error('[PredictiveDetection] trends error:', e)
    throw createError({
      statusCode: 500,
      message: e.message || 'Trend analysis failed',
    })
  }
})
