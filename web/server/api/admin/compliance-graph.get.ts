import { getGraph, getImpactHistory } from '~/server/utils/complianceGraph'

export default defineEventHandler(async () => {
  try {
    const graph = getGraph()
    const history = getImpactHistory()
    return {
      ...graph,
      history,
      timestamp: new Date().toISOString(),
    }
  } catch (e: any) {
    console.error('[ComplianceGraph] fetch error:', e)
    throw createError({
      statusCode: 500,
      message: e.message || 'Failed to fetch compliance graph',
    })
  }
})
