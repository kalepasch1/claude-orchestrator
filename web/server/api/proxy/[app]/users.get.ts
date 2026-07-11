import { getAppClient, type AppId } from '../../../utils/appClients'

export default defineEventHandler(async (event) => {
  const appId = getRouterParam(event, 'app') as AppId
  const client = getAppClient(appId)
  if (!client) {
    throw createError({ statusCode: 404, message: `app "${appId}" not configured` })
  }

  const { email, limit } = getQuery(event) as { email?: string; limit?: string }

  const { data, error } = await client.auth.admin.listUsers({
    perPage: parseInt(limit || '50'),
  })

  if (error) throw createError({ statusCode: 500, message: error.message })

  let users = data.users
  if (email) {
    users = users.filter(u => u.email?.toLowerCase().includes(email.toLowerCase()))
  }

  return {
    users: users.map(u => ({
      id: u.id,
      email: u.email,
      created_at: u.created_at,
      last_sign_in_at: u.last_sign_in_at,
      provider: u.app_metadata?.provider,
    })),
    total: users.length,
    app: appId,
  }
})
