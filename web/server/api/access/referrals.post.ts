import { readBody } from 'h3'
import { accessHash, referralCode } from '~/server/utils/accessAdmission'
import { requireConnectorUser } from '~/server/utils/connectorFabric'
import { serviceClient } from '~/server/utils/fleetSupabase'

export default defineEventHandler(async event => {
  const user = await requireConnectorUser(event)
  const body = await readBody<any>(event)
  const maxUses = Math.max(1, Math.min(10, Number(body?.max_uses || 3)))
  const days = Math.max(1, Math.min(90, Number(body?.expires_in_days || 30)))
  const code = referralCode()
  const { data, error } = await serviceClient().from('orchestrator_referral_codes').insert({ owner_user_id: user.id, code_hash: accessHash(code), label: String(body?.label || 'Member referral').slice(0, 120), max_uses: maxUses, expires_at: new Date(Date.now() + days * 86400_000).toISOString() }).select('id,label,max_uses,expires_at,created_at').single()
  if (error) throw createError({ statusCode: 500, message: 'Referral code could not be created.' })
  return { referral: { ...data, code }, warning: 'This code is shown once. Share it only with the intended founder.' }
})
