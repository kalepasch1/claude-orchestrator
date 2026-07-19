import { serverSupabaseUser } from '#supabase/server'
import { createHash } from 'node:crypto'
import { serviceClient } from '../utils/fleetSupabase'

export default defineEventHandler(async (event) => {
  const user = await serverSupabaseUser(event)
  if (!user) throw createError({ statusCode: 401, message: 'authentication_required' })
  const body = await readBody<any>(event)
  const experiment = String(body?.experiment || 'orchestrator_navigation_v1').slice(0, 120)
  const metric = String(body?.metric || 'page_view').slice(0, 120)
  const subject = `${user.id}:${body?.subject || ''}`
  const digest = createHash('sha256').update(`${experiment}:${subject}`).digest('hex')
  const variant = body?.variant || (parseInt(digest.slice(0, 8), 16) % 100 < 90 ? 'treatment' : 'control')
  const { error } = await serviceClient().from('product_metric_events').insert({
    experiment, metric, variant, subject_hash: createHash('sha256').update(subject).digest('hex').slice(0, 24),
    value: Number.isFinite(Number(body?.value)) ? Number(body.value) : 1,
    guardrail: !!body?.guardrail, metadata: { route: String(body?.route || '').slice(0, 300) },
  })
  if (error) throw createError({ statusCode: 500, message: 'metric_persistence_failed' })
  return { recorded: true, variant }
})
