import { startRecording } from '~/server/utils/actionReplay'

export default defineEventHandler(async (event) => {
  try {
    const body = await readBody(event)
    if (!body?.name) {
      throw createError({ statusCode: 400, message: 'Recording name is required' })
    }

    const recording = startRecording(
      body.name,
      body.description || '',
      body.createdBy || 'admin'
    )

    return { recording, timestamp: new Date().toISOString() }
  } catch (e: any) {
    if (e.statusCode) throw e
    console.error('[ActionReplay] start error:', e)
    throw createError({ statusCode: 500, message: e.message || 'Failed to start recording' })
  }
})
