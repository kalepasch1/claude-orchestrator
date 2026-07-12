import { executePlaybook } from '~/server/utils/autoRemediation'

export default defineEventHandler(async (event) => {
  const body = await readBody(event)
  const { playbookId, triggeredBy } = body || {}

  if (!playbookId) {
    throw createError({ statusCode: 400, message: 'playbookId is required' })
  }

  try {
    const execution = await executePlaybook(playbookId, triggeredBy || 'manual')
    return { execution }
  } catch (e: any) {
    throw createError({ statusCode: 500, message: e.message || 'Playbook execution failed' })
  }
})
