import { acknowledgePrediction, getActivePredictions } from '~/server/utils/predictiveDetection'

export default defineEventHandler(async (event) => {
  const body = await readBody(event)
  const { id } = body || {}

  if (!id) {
    throw createError({
      statusCode: 400,
      message: 'Missing prediction id',
    })
  }

  acknowledgePrediction(id)

  return { acknowledged: true, id, remaining: getActivePredictions().length }
})
