import { getAppClient, type AppId } from '../../../utils/appClients'

interface ProxyQuery {
  table: string
  select?: string
  filters?: Array<{ column: string; op: 'eq' | 'neq' | 'gt' | 'lt' | 'gte' | 'lte' | 'like' | 'ilike' | 'in'; value: any }>
  order?: { column: string; ascending?: boolean }
  limit?: number
  offset?: number
}

export default defineEventHandler(async (event) => {
  const appId = getRouterParam(event, 'app') as AppId
  const client = getAppClient(appId)
  if (!client) {
    throw createError({ statusCode: 404, message: `app "${appId}" not configured` })
  }

  const body = await readBody<ProxyQuery>(event)
  if (!body?.table) {
    throw createError({ statusCode: 400, message: 'table is required' })
  }

  let query = client.from(body.table).select(body.select || '*', { count: 'exact' })

  if (body.filters) {
    for (const f of body.filters) {
      if (f.op === 'in') {
        query = query.in(f.column, Array.isArray(f.value) ? f.value : [f.value])
      } else {
        query = (query as any)[f.op](f.column, f.value)
      }
    }
  }

  if (body.order) {
    query = query.order(body.order.column, { ascending: body.order.ascending ?? false })
  }

  query = query.range(body.offset || 0, (body.offset || 0) + (body.limit || 50) - 1)

  const { data, error, count } = await query
  if (error) throw createError({ statusCode: 500, message: error.message })

  return { data, count, app: appId, table: body.table }
})
