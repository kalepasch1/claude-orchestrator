import { serviceClient } from '../../utils/fleetSupabase'
import { requireConnectorUser } from '../../utils/connectorFabric'

/**
 * Wave-0 review gate (spec item 4): read attributed steering history.
 * Filters: ?task_id=&approval_id=&project=&event_type=&limit=
 * Auth-gated like every /api/ route (madeus.cc stays private).
 */
export default defineEventHandler(async (event) => {
  await requireConnectorUser(event)
  const q = getQuery(event)
  const limit = Math.min(Math.max(Number(q.limit) || 100, 1), 500)
  const sb = serviceClient()
  let query = sb
    .from('steering_events')
    .select('id,task_id,approval_id,project,actor_id,actor_label,event_type,rationale,payload,created_at')
    .order('created_at', { ascending: false })
    .limit(limit)
  if (q.task_id) query = query.eq('task_id', String(q.task_id))
  if (q.approval_id) query = query.eq('approval_id', String(q.approval_id))
  if (q.project) query = query.eq('project', String(q.project))
  if (q.event_type) query = query.eq('event_type', String(q.event_type))
  const { data, error } = await query
  if (error) throw createError({ statusCode: 500, message: error.message })
  return { ok: true, events: data || [] }
})
