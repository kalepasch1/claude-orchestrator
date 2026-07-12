import { getExperiments, getTemplates, getChaosStatus } from '~/server/utils/chaosMonkey'

export default defineEventHandler(async () => {
  try {
    return {
      experiments: getExperiments(),
      templates: getTemplates(),
      chaosStatus: getChaosStatus(),
      timestamp: new Date().toISOString(),
    }
  } catch (e: any) {
    console.error('[ChaosMonkey] fetch error:', e)
    throw createError({
      statusCode: 500,
      message: e.message || 'Failed to fetch chaos data',
    })
  }
})
