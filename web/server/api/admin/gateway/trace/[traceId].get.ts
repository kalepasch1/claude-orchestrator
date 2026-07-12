import { getTraceLog } from '~/server/utils/apiGateway'

export default defineEventHandler(async (event) => {
  const traceId = getRouterParam(event, 'traceId')

  if (!traceId) {
    throw createError({
      statusCode: 400,
      message: 'Missing traceId parameter',
    })
  }

  try {
    const trace = getTraceLog(traceId)
    if (!trace) {
      throw createError({
        statusCode: 404,
        message: `No trace found for ID: ${traceId}`,
      })
    }
    return {
      ...trace,
      timestamp: new Date().toISOString(),
    }
  } catch (e: any) {
    if (e.statusCode) throw e
    console.error('[Gateway] trace error:', e)
    throw createError({
      statusCode: 500,
      message: e.message || 'Failed to fetch trace',
    })
  }
})
