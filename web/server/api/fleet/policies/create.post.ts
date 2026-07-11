import { serviceClient } from '../../../utils/fleetSupabase'

export default defineEventHandler(async (event) => {
  const body = await readBody<any>(event)
  if (!body?.name) throw createError({ statusCode: 400, message: 'name required' })

  const sb = serviceClient()
  const policy = {
    id: `policy-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    name: body.name,
    description: body.description || '',
    product: body.product || '*',
    domain: body.domain || 'infra',
    trigger: body.trigger || {},
    conditions: body.conditions || [],
    actions: body.actions || [],
    enabled: true,
    auto_execute: body.autoExecute ?? false,
    created_at: new Date().toISOString(),
    match_count: 0,
    success_count: 0,
  }

  const { error } = await sb.from('fleet_policies').insert(policy)
  if (error) throw createError({ statusCode: 500, message: error.message })
  return { ok: true, policy }
})
