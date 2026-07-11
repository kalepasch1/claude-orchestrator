import { getPortfolioSummary } from '~/server/utils/revenueFabric'

export default defineEventHandler(async (event) => {
  const query = getQuery(event)
  const months = Math.min(Math.max(Number(query.months) || 6, 1), 24)

  try {
    const summary = await getPortfolioSummary(months)
    return summary
  } catch (err: any) {
    throw createError({
      statusCode: 500,
      statusMessage: `Revenue aggregation failed: ${err?.message ?? 'unknown error'}`,
    })
  }
})
