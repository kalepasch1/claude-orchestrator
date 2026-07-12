import { getRecentSessions } from '~/server/utils/sessionReplay'

export default defineEventHandler(async (event) => {
  try {
    const q = getQuery(event)
    const limit = parseInt(q.limit as string) || 20

    const recentUsers = await getRecentSessions(limit)

    return {
      users: recentUsers,
      timestamp: new Date().toISOString(),
    }
  } catch (e: any) {
    console.error('[SessionReplay] recent error:', e)
    throw createError({
      statusCode: 500,
      message: e.message || 'Failed to fetch recent sessions',
    })
  }
})
