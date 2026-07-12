import { abortExperiment } from '~/server/utils/chaosMonkey'

export default defineEventHandler(async (event) => {
  const body = await readBody(event)
  const { id } = body || {}

  if (!id) {
    throw createError({
      statusCode: 400,
      message: 'Missing required field: id',
    })
  }

  try {
    const experiment = abortExperiment(id)
    return experiment
  } catch (e: any) {
    console.error('[ChaosMonkey] abort error:', e)
    throw createError({
      statusCode: e.message?.includes('not found') || e.message?.includes('not running') ? 400 : 500,
      message: e.message || 'Failed to abort experiment',
    })
  }
})
