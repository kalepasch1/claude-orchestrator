import { undoAction } from '~/server/utils/temporalAdmin'

export default defineEventHandler(async (event) => {
  const body = await readBody(event)
  const { receiptId, undoneBy } = body || {}

  if (!receiptId) {
    throw createError({ statusCode: 400, statusMessage: 'receiptId is required' })
  }

  const result = await undoAction(receiptId, undoneBy || 'operator')
  if (!result.success) {
    throw createError({ statusCode: 422, statusMessage: result.error || 'Undo failed' })
  }

  return { success: true, receiptId }
})
