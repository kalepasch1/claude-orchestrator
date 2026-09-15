import { requireConnectorUser } from '../../utils/connectorFabric'
import { executeLegalAction } from '../../utils/legalContractWorkspace'
import { processBatch } from '../../utils/legal-batch'

export default defineEventHandler(async event => {
  const user = await requireConnectorUser(event)
  const body = await readBody(event)
  const items = Array.isArray(body?.items) ? body.items : []

  if (!items.length) {
    throw createError({
      statusCode: 422,
      message: 'batch_items_required'
    })
  }

  return processBatch(event, items, async (_, item) => {
    return executeLegalAction(user, {
      action: item.action,
      values: item.values
    })
  })
})
