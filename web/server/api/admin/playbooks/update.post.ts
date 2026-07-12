import { updatePlaybook, createPlaybook } from '~/server/utils/autoRemediation'

export default defineEventHandler(async (event) => {
  const body = await readBody(event)
  const { id, create, ...updates } = body || {}

  try {
    if (create) {
      const playbook = createPlaybook(updates as any)
      return { playbook, created: true }
    }

    if (!id) {
      throw createError({ statusCode: 400, message: 'id is required for updates' })
    }

    const playbook = updatePlaybook(id, updates)
    return { playbook, updated: true }
  } catch (e: any) {
    throw createError({ statusCode: 500, message: e.message || 'Playbook update failed' })
  }
})
