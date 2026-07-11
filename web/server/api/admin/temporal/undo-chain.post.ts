import { undoChain } from '~/server/utils/temporalAdmin'

export default defineEventHandler(async (event) => {
  const body = await readBody(event)
  const { chainId, undoneBy } = body || {}

  if (!chainId) {
    throw createError({ statusCode: 400, statusMessage: 'chainId is required' })
  }

  const result = await undoChain(chainId, undoneBy || 'operator')
  return result
})
