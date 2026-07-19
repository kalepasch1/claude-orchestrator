import { readBody } from 'h3'
import { accessHash, grantToken, limitPublicAdmission } from '~/server/utils/accessAdmission'
import { serviceClient } from '~/server/utils/fleetSupabase'

export default defineEventHandler(async event => {
  limitPublicAdmission(event)
  const body = await readBody<any>(event)
  const code = String(body?.code || '').trim()
  if (!/^MDS-[A-Z0-9-]{6,32}$/i.test(code)) throw createError({ statusCode: 400, message: 'Enter a valid Madeus referral code.' })
  const sb = serviceClient()
  const { data: referral, error } = await sb.from('orchestrator_referral_codes').select('id,status,max_uses,use_count,expires_at').eq('code_hash', accessHash(code)).maybeSingle()
  if (error) throw createError({ statusCode: 503, message: 'Referral admission is not available yet.' })
  const unavailable = !referral || referral.status !== 'active' || referral.use_count >= referral.max_uses || (referral.expires_at && new Date(referral.expires_at).getTime() <= Date.now())
  if (unavailable) throw createError({ statusCode: 403, message: 'This referral is invalid, expired, or fully used.' })
  const token = grantToken()
  const { error: grantError } = await sb.from('orchestrator_access_grants').insert({ referral_code_id: referral.id, token_hash: accessHash(token), expires_at: new Date(Date.now() + 30 * 60_000).toISOString() })
  if (grantError) throw createError({ statusCode: 500, message: 'Could not issue an access grant.' })
  return { grant_token: token, expires_in_seconds: 1800, next: 'google_oauth' }
})
