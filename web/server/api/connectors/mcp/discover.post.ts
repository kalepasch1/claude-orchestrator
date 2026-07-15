import { discoverMcp } from '../../../utils/connectorFabric'

export default defineEventHandler(async (event) => {
  const body = await readBody<any>(event)
  if (!body?.server_url) throw createError({ statusCode: 400, message: 'server_url_required' })
  return discoverMcp(event, body.name, body.server_url)
})
