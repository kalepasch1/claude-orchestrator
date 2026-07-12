import { getRecordings, getActiveRecording } from '~/server/utils/actionReplay'

export default defineEventHandler(async (event) => {
  try {
    const q = getQuery(event)
    const tags = q.tags ? (q.tags as string).split(',').map(t => t.trim()).filter(Boolean) : undefined
    const recordings = getRecordings(tags)
    const active = getActiveRecording()

    return {
      recordings,
      activeRecording: active ? { id: active.id, name: active.name, actionCount: active.actions.length, startedAt: active.createdAt } : null,
      total: recordings.length,
      timestamp: new Date().toISOString(),
    }
  } catch (e: any) {
    console.error('[ActionReplay] list error:', e)
    throw createError({ statusCode: 500, message: e.message || 'Failed to list recordings' })
  }
})
