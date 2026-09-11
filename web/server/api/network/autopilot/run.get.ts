import { timingSafeEqual } from 'node:crypto'
import { runScheduledAutopilot } from '../../../utils/hivemindControlPlane'

function authorized(event: any) {
  const secret = process.env.CRON_SECRET
  const authorization = getRequestHeader(event, 'authorization') || ''
  if (!secret || !authorization.startsWith('Bearer ')) return false
  const supplied = Buffer.from(authorization.slice(7))
  const expected = Buffer.from(secret)
  return supplied.length === expected.length && timingSafeEqual(supplied, expected)
}

export default defineEventHandler(async event => {
  if (!authorized(event)) throw createError({ statusCode: 401, message: 'cron_authorization_required' })
  return runScheduledAutopilot()
})
