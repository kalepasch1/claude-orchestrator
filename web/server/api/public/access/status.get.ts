import { getHeader } from 'h3'
import { limitPublicAdmission } from '~/server/utils/accessAdmission'
import { serviceClient } from '~/server/utils/fleetSupabase'

const DEFAULT_OPS_EMAILS = 'kalepasch@gmail.com,kale@smrter.us,kale@heretomorrow.us'

export default defineEventHandler(async event => {
  limitPublicAdmission(event, 30)
  const authorization = getHeader(event, 'authorization') || ''
  const accessToken = authorization.startsWith('Bearer ') ? authorization.slice(7) : ''
  if (!accessToken) throw createError({ statusCode: 401, message: 'Authenticated session required.' })
  const sb = serviceClient()
  const { data: auth, error } = await sb.auth.getUser(accessToken)
  if (error || !auth.user) throw createError({ statusCode: 401, message: 'Invalid or expired session.' })
  const email = auth.user.email?.toLowerCase() || ''
  const operators = new Set((process.env.OPS_EMAILS || DEFAULT_OPS_EMAILS).split(',').map(value => value.trim().toLowerCase()).filter(Boolean))
  if (operators.has(email)) return { admitted: true, role: 'operator' }
  const { data: membership } = await sb.from('orchestrator_org_memberships').select('role,organization_id').eq('user_id', auth.user.id).eq('status', 'active').limit(1).maybeSingle()
  if (!membership) throw createError({ statusCode: 403, message: 'A valid Madeus referral or approved membership is required.' })
  return { admitted: true, role: membership.role, organization_id: membership.organization_id }
})
