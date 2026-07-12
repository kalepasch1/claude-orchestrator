import { analyzeImpact } from '~/server/utils/complianceGraph'

export default defineEventHandler(async (event) => {
  const body = await readBody(event)

  const { triggerApp, triggerAction, entityType, entityId } = body || {}

  if (!triggerApp || !triggerAction || !entityType) {
    throw createError({
      statusCode: 400,
      message: 'Missing required fields: triggerApp, triggerAction, entityType',
    })
  }

  try {
    const analysis = analyzeImpact(triggerApp, triggerAction, entityType, entityId)
    return analysis
  } catch (e: any) {
    console.error('[ComplianceGraph] impact analysis error:', e)
    throw createError({
      statusCode: 500,
      message: e.message || 'Impact analysis failed',
    })
  }
})
