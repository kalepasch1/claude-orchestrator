import { getAllCircuitStates } from '~/server/utils/apiGateway'

export default defineEventHandler(async () => {
  try {
    return {
      circuits: getAllCircuitStates(),
      timestamp: new Date().toISOString(),
    }
  } catch (e: any) {
    console.error('[Gateway] circuits error:', e)
    throw createError({
      statusCode: 500,
      message: e.message || 'Failed to fetch circuit states',
    })
  }
})
