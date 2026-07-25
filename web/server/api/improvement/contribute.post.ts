import { requireConnectorUser } from '../../utils/connectorFabric'
import { serviceClient } from '../../utils/fleetSupabase'

export default defineEventHandler(async event => {
  const user = await requireConnectorUser(event)
  const body = await readBody<any>(event)
  const sb = serviceClient()
  const { data: loop } = await sb.from('scoped_improvement_loops').select('*').eq('id', body?.loop_id).eq('owner_id', user.id).maybeSingle()
  if (!loop) throw createError({ statusCode: 404, message: 'Improvement loop not found.' })
  const evidence = loop.last_evaluation || {}
  if (loop.status !== 'graduated' && !evidence?.verified) throw createError({ statusCode: 409, message: 'Only independently verified improvements can enter the shared validation pool.' })
  const { data, error } = await sb.from('hivemind_contributions').insert({ owner_id: user.id, loop_id: loop.id, title: loop.label, evidence, reusable_scope: body?.reusable_scope || 'pattern_only', status: 'validating', privacy_reviewed: true }).select().single()
  if (error) throw createError({ statusCode: 500, message: error.message })
  return { ok: true, contribution: data, rebate: { state: 'pending_blind_validation', formula: 'verified downstream value × contribution share' } }
})

