import { detectCostAnomalies } from '~/server/utils/costOptimizer'

export default defineEventHandler(async () => {
  try {
    const anomalies = await detectCostAnomalies()
    return { anomalies }
  } catch (e: any) {
    console.error('[CostOptimizer] anomaly detection error:', e)
    throw createError({ statusCode: 500, message: e.message || 'Cost anomaly detection failed' })
  }
})
