import { getFleetCostSummary, getAppCosts, getCachedSummary } from '~/server/utils/costOptimizer'

export default defineEventHandler(async (event) => {
  const query = getQuery(event)
  const useCached = query.cached === 'true'

  if (useCached) {
    const { summary, lastFetch } = getCachedSummary()
    if (summary) {
      return { summary, costs: [], lastFetch, cached: true }
    }
  }

  try {
    const costs = await getAppCosts(Number(query.months) || 1)
    const summary = await getFleetCostSummary()
    return { summary, costs, lastFetch: new Date().toISOString(), cached: false }
  } catch (e: any) {
    console.error('[CostOptimizer] fetch error:', e)
    throw createError({ statusCode: 500, message: e.message || 'Cost fetch failed' })
  }
})
