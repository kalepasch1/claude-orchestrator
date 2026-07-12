import { getStats } from '~/server/utils/apiGateway'

export default defineEventHandler(async () => {
  try {
    return {
      ...getStats(),
      timestamp: new Date().toISOString(),
    }
  } catch (e: any) {
    console.error('[Gateway] stats error:', e)
    throw createError({
      statusCode: 500,
      message: e.message || 'Failed to fetch gateway stats',
    })
  }
})
