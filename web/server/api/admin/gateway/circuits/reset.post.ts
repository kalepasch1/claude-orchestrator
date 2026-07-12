import { resetCircuit, getCircuitState } from '~/server/utils/apiGateway'

export default defineEventHandler(async (event) => {
  const body = await readBody(event)
  const { app } = body || {}

  if (!app) {
    throw createError({
      statusCode: 400,
      message: 'Missing required field: app',
    })
  }

  try {
    resetCircuit(app)
    return {
      success: true,
      circuit: getCircuitState(app),
      timestamp: new Date().toISOString(),
    }
  } catch (e: any) {
    console.error('[Gateway] circuit reset error:', e)
    throw createError({
      statusCode: 500,
      message: e.message || 'Failed to reset circuit',
    })
  }
})
