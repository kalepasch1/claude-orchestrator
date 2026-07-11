import { ALL_APP_IDS, getAppClient, getAppConfig, type AppId } from '../../../utils/appClients'

export default defineEventHandler(async (event) => {
  const { email } = getQuery(event) as { email?: string }
  if (!email) throw createError({ statusCode: 400, message: 'email query param required' })

  const results: Array<{ app: AppId; appName: string; user: any }> = []

  await Promise.allSettled(
    ALL_APP_IDS.map(async (appId) => {
      const client = getAppClient(appId)
      if (!client) return
      try {
        const { data } = await client.auth.admin.listUsers({ perPage: 1000 })
        const match = data.users.find(u => u.email?.toLowerCase() === email.toLowerCase())
        if (match) {
          results.push({
            app: appId,
            appName: getAppConfig(appId).name,
            user: {
              id: match.id,
              email: match.email,
              created_at: match.created_at,
              last_sign_in_at: match.last_sign_in_at,
              provider: match.app_metadata?.provider,
            },
          })
        }
      } catch {}
    })
  )

  return { email, found: results.length, results }
})
