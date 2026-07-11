import { getAppClient, type AppId } from '../../../utils/appClients'

export default defineEventHandler(async (event) => {
  const appId = getRouterParam(event, 'app') as AppId
  const client = getAppClient(appId)
  if (!client) {
    throw createError({ statusCode: 404, message: `app "${appId}" not configured` })
  }

  // Query pg_catalog for table names in the public schema
  const { data, error } = await client.rpc('get_table_names').select('*')

  // Fallback: if the RPC doesn't exist, return a static list
  if (error) {
    return { tables: [], error: 'get_table_names RPC not available — add it to enable table discovery', app: appId }
  }

  return { tables: data, app: appId }
})
