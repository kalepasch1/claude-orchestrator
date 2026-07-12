import { getRecording } from '~/server/utils/actionReplay'

export default defineEventHandler(async (event) => {
  try {
    const id = getRouterParam(event, 'id')
    if (!id) {
      throw createError({ statusCode: 400, message: 'Recording id is required' })
    }

    const recording = getRecording(id)
    if (!recording) {
      throw createError({ statusCode: 404, message: `Recording ${id} not found` })
    }

    return { recording, timestamp: new Date().toISOString() }
  } catch (e: any) {
    if (e.statusCode) throw e
    console.error('[ActionReplay] get error:', e)
    throw createError({ statusCode: 500, message: e.message || 'Failed to get recording' })
  }
})
