import { fetchAppRevenue } from '~/server/utils/revenueFabric'
import { type AppId, ALL_APP_IDS } from '~/server/utils/appClients'

export default defineEventHandler(async (event) => {
  const appId = getRouterParam(event, 'app') as AppId
  if (!ALL_APP_IDS.includes(appId)) {
    throw createError({ statusCode: 400, statusMessage: `Unknown app: ${appId}` })
  }

  const query = getQuery(event)
  const months = Math.min(Math.max(Number(query.months) || 6, 1), 24)

  try {
    const result = await fetchAppRevenue(appId, months)
    return result
  } catch (err: any) {
    throw createError({
      statusCode: 500,
      statusMessage: `Revenue query failed for ${appId}: ${err?.message ?? 'unknown error'}`,
    })
  }
})
