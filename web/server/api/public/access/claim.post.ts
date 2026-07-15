import { getHeader, readBody } from 'h3'
import { accessHash, limitPublicAdmission } from '~/server/utils/accessAdmission'
import { organizationContext } from '~/server/utils/adaptiveFabric'
import { serviceClient } from '~/server/utils/fleetSupabase'

export default defineEventHandler(async event => {
  limitPublicAdmission(event)
  const authorization = getHeader(event, 'authorization') || ''
  const accessToken = authorization.startsWith('Bearer ') ? authorization.slice(7) : ''
  if (!accessToken) throw createError({ statusCode: 401, message: 'Authenticated session required.' })
  const sb = serviceClient()
  const { data: auth, error: authError } = await sb.auth.getUser(accessToken)
  if (authError || !auth.user) throw createError({ statusCode: 401, message: 'Invalid or expired session.' })
  const body = await readBody<any>(event)
  const token = String(body?.grant_token || '')
  const { data: grant, error } = await sb.from('orchestrator_access_grants').select('id,referral_code_id,status,expires_at').eq('token_hash', accessHash(token)).maybeSingle()
  if (error || !grant || grant.status !== 'issued' || new Date(grant.expires_at).getTime() <= Date.now()) throw createError({ statusCode: 403, message: 'Referral grant is invalid or expired.' })
  const context = await organizationContext(auth.user)
  const claimedAt = new Date().toISOString()
  const { error: claimError } = await sb.from('orchestrator_access_grants').update({ status: 'claimed', claimed_by: auth.user.id, claimed_at: claimedAt }).eq('id', grant.id).eq('status', 'issued')
  if (claimError) throw createError({ statusCode: 409, message: 'Referral grant could not be claimed.' })
  const { data: referral } = await sb.from('orchestrator_referral_codes').select('use_count,max_uses').eq('id', grant.referral_code_id).single()
  if (referral) await sb.from('orchestrator_referral_codes').update({ use_count: Math.min(referral.max_uses, referral.use_count + 1), status: referral.use_count + 1 >= referral.max_uses ? 'exhausted' : 'active' }).eq('id', grant.referral_code_id)
  return { admitted: true, organization_id: context.membership.organization_id, role: context.membership.role }
})
