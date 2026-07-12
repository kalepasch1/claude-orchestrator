import {
  generateIncidentResponseTemplate,
  generateAuditTemplate,
  generateOnboardingTemplate,
} from '~/server/utils/actionReplay'

export default defineEventHandler(async () => {
  try {
    const templates = [
      generateIncidentResponseTemplate(),
      generateAuditTemplate(),
      generateOnboardingTemplate(),
    ]

    return { templates, timestamp: new Date().toISOString() }
  } catch (e: any) {
    console.error('[ActionReplay] templates error:', e)
    throw createError({ statusCode: 500, message: e.message || 'Failed to generate templates' })
  }
})
