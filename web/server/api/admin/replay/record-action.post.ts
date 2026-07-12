import { addAction } from '~/server/utils/actionReplay'

export default defineEventHandler(async (event) => {
  try {
    const body = await readBody(event)
    if (!body?.recordingId || !body?.type) {
      throw createError({ statusCode: 400, message: 'recordingId and type are required' })
    }

    addAction(body.recordingId, {
      type: body.type,
      timestamp: new Date().toISOString(),
      input: body.input || {},
      output: body.output,
      app: body.app,
      duration_ms: body.duration_ms,
    })

    return { ok: true, timestamp: new Date().toISOString() }
  } catch (e: any) {
    if (e.statusCode) throw e
    console.error('[ActionReplay] record-action error:', e)
    throw createError({ statusCode: 500, message: e.message || 'Failed to record action' })
  }
})
