import { stopRecording } from '~/server/utils/actionReplay'

export default defineEventHandler(async (event) => {
  try {
    const body = await readBody(event)
    if (!body?.id) {
      throw createError({ statusCode: 400, message: 'Recording id is required' })
    }

    const recording = stopRecording(body.id)
    if (!recording) {
      throw createError({ statusCode: 404, message: `Recording ${body.id} not found` })
    }

    return { recording, timestamp: new Date().toISOString() }
  } catch (e: any) {
    if (e.statusCode) throw e
    console.error('[ActionReplay] stop error:', e)
    throw createError({ statusCode: 500, message: e.message || 'Failed to stop recording' })
  }
})
