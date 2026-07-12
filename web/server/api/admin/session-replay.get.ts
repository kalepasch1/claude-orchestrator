import { traceUser, compareUsers } from '~/server/utils/sessionReplay'

export default defineEventHandler(async (event) => {
  try {
    const q = getQuery(event)

    if (!q.email) {
      throw createError({
        statusCode: 400,
        message: 'Query parameter "email" is required',
      })
    }

    // Support comparing multiple users: ?email=a@x.com,b@x.com
    const emails = (q.email as string).split(',').map(e => e.trim()).filter(Boolean)

    if (emails.length > 1) {
      const sessions = await compareUsers(emails)
      return {
        mode: 'compare',
        sessions,
        timestamp: new Date().toISOString(),
      }
    }

    const session = await traceUser(emails[0])
    return {
      mode: 'single',
      session,
      timestamp: new Date().toISOString(),
    }
  } catch (e: any) {
    if (e.statusCode) throw e
    console.error('[SessionReplay] trace error:', e)
    throw createError({
      statusCode: 500,
      message: e.message || 'Failed to trace user session',
    })
  }
})
