import { recordShadowDecision, recordHumanDecision } from '~/server/utils/shadowDecisions'

export default defineEventHandler(async (event) => {
  const body = await readBody(event)
  const { type } = body || {}

  if (type === 'human') {
    const { eventId, humanDecision } = body
    if (!eventId || !humanDecision) {
      throw createError({ statusCode: 400, statusMessage: 'eventId and humanDecision are required' })
    }
    const result = recordHumanDecision(eventId, humanDecision)
    if (!result) {
      throw createError({ statusCode: 404, statusMessage: 'Shadow decision not found for eventId' })
    }
    return result
  }

  // Default: record a shadow (AI) decision
  const { eventId, app, domain, aiDecision, confidence, policyId, details } = body
  if (!eventId || !app || !domain || !aiDecision) {
    throw createError({ statusCode: 400, statusMessage: 'eventId, app, domain, and aiDecision are required' })
  }

  return recordShadowDecision(eventId, app, domain, aiDecision, confidence ?? 0.5, policyId, details)
})
