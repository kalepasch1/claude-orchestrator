import { beginMcpOAuth } from '../../../utils/connectorFabric'

export default defineEventHandler(async (event) => {
  const body = await readBody<any>(event)
  if (!body?.server_id) throw createError({ statusCode: 400, message: 'server_id_required' })
  return beginMcpOAuth(event, body.server_id, Array.isArray(body.scopes) ? body.scopes : [])
})
