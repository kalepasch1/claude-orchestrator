import { serviceClient } from '../../../utils/fleetSupabase'
import { requireConnectorUser } from '../../../utils/connectorFabric'

/** Lifecycle of one db_sources row: { action: 'pause' | 'resume' | 'remove' }. Removing cascades to its findings and snapshots. */
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i
export default defineEventHandler(async (event) => {
  await requireConnectorUser(event); const id = String(getRouterParam(event, 'id') || ''); const body = await readBody<any>(event) || {}
  if (!UUID.test(id)) throw createError({ statusCode: 422, message: 'valid_source_id_required' })
  const action = String(body.action || ''); const sb = serviceClient(); const now = new Date().toISOString()
  const patch = action === 'pause' ? { enabled: false, status: 'paused', updated_at: now } : action === 'resume' ? { enabled: true, status: 'active', consecutive_failures: 0, last_error: null, updated_at: now } : null
  if (action === 'remove') { const { error } = await sb.from('db_sources').delete().eq('id', id); if (error) throw createError({ statusCode: 500, message: 'db_source_delete_failed' }); return { ok: true, action } }
  if (!patch) throw createError({ statusCode: 422, message: 'valid_action_required' })
  const { data, error } = await sb.from('db_sources').update(patch).eq('id', id).select('id').maybeSingle()
  if (error) throw createError({ statusCode: 500, message: 'db_source_update_failed' })
  if (!data) throw createError({ statusCode: 404, message: 'db_source_not_found' })
  return { ok: true, action }
})
