import { getGraphStats, CROSS_APP_RELATIONSHIPS } from '~/server/utils/knowledgeGraph'

export default defineEventHandler(async () => {
  try {
    const stats = getGraphStats()

    return {
      ...stats,
      relationships: CROSS_APP_RELATIONSHIPS,
      timestamp: new Date().toISOString(),
    }
  } catch (e: any) {
    console.error('[KnowledgeGraph] stats error:', e)
    throw createError({
      statusCode: 500,
      message: e.message || 'Failed to get graph stats',
    })
  }
})
