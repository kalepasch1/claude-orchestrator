import { getAppConfig, type AppId } from '../../../utils/appClients'

export default defineEventHandler(async (event) => {
  const appId = getRouterParam(event, 'app') as AppId
  const config = getAppConfig(appId)
  if (!config.baseUrl) {
    throw createError({ statusCode: 404, message: `no base URL configured for "${appId}"` })
  }

  const body = await readBody<{ action: any }>(event)

  try {
    const res = await fetch(`${config.baseUrl}/api/fleet/execute`, {
      method: 'POST',
      headers: {
        'content-type': 'application/json',
        'x-fleet-secret': process.env.FLEET_SHARED_SECRET ?? '',
      },
      body: JSON.stringify(body),
    })
    const data = await res.json()
    return data
  } catch (e: any) {
    return { ok: false, error: e.message }
  }
})
