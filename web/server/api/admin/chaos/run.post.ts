import { createExperiment, runExperiment } from '~/server/utils/chaosMonkey'

export default defineEventHandler(async (event) => {
  const body = await readBody(event)
  const { name, targetApp, failureType, config } = body || {}

  if (!name || !targetApp || !failureType) {
    throw createError({
      statusCode: 400,
      message: 'Missing required fields: name, targetApp, failureType',
    })
  }

  try {
    const experiment = createExperiment(name, targetApp, failureType, config || {})
    const started = await runExperiment(experiment.id)
    return started
  } catch (e: any) {
    console.error('[ChaosMonkey] run error:', e)
    throw createError({
      statusCode: 500,
      message: e.message || 'Failed to run chaos experiment',
    })
  }
})
