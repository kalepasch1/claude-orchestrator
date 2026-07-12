import { generateSnapshot } from '~/server/utils/regulatorySnapshot'

export default defineEventHandler(async (event) => {
  const body = await readBody(event).catch(() => ({}))
  const period = body?.from || body?.to
    ? { from: body.from, to: body.to }
    : undefined

  try {
    const snapshot = await generateSnapshot(period)
    return snapshot
  } catch (err: any) {
    throw createError({
      statusCode: 500,
      statusMessage: `Snapshot generation failed: ${err?.message ?? 'unknown error'}`,
    })
  }
})
