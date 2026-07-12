import { replayRecording } from '~/server/utils/actionReplay'

export default defineEventHandler(async (event) => {
  try {
    const id = getRouterParam(event, 'id')
    if (!id) {
      throw createError({ statusCode: 400, message: 'Recording id is required' })
    }

    const body = await readBody(event) || {}

    const result = await replayRecording(id, {
      dryRun: body.dryRun ?? false,
      skipExecutes: body.skipExecutes ?? false,
    })

    return { result, timestamp: new Date().toISOString() }
  } catch (e: any) {
    if (e.statusCode) throw e
    console.error('[ActionReplay] replay error:', e)
    throw createError({ statusCode: 500, message: e.message || 'Failed to replay recording' })
  }
})
