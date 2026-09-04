// GET /api/embed/status — the fleet-status / approvals strip, tenant-scoped.
//
// Every query below filters on the tenant the KEY authenticated as. That is the
// only reason this endpoint is safe to expose to a third-party origin.
import { serviceClient } from '../../utils/fleetSupabase'
import { handleStatus } from '../../utils/embedHandlers'
import { loadEmbedKeys } from '../../utils/embedKeys'

export default defineEventHandler(async event => {
  const key = getHeader(event, 'x-madeus-embed-key')
  const origin = getHeader(event, 'origin')
  const surface = getHeader(event, 'x-madeus-surface') || 'strip'

  const sb = serviceClient()
  const keys = await loadEmbedKeys(async () => {
    const { data } = await sb.from('embed_keys').select('*')
    return data || []
  })

  const result = await handleStatus({ key, origin, surface }, {
    keys,
    fetchStatus: async tenantId => {
      const [running, queued, approvals] = await Promise.all([
        sb.from('tasks').select('id', { count: 'exact', head: true })
          .eq('tenant_id', tenantId).eq('state', 'RUNNING'),
        sb.from('tasks').select('id', { count: 'exact', head: true })
          .eq('tenant_id', tenantId).eq('state', 'QUEUED'),
        sb.from('approvals').select('id, summary')
          .eq('tenant_id', tenantId).eq('state', 'pending').limit(20),
      ])
      return {
        runningTasks: running.count ?? 0,
        queuedTasks: queued.count ?? 0,
        pendingApprovals: (approvals.data || []).map((a: any) => ({
          id: String(a.id), summary: String(a.summary ?? ''),
        })),
      }
    },
  })

  setResponseStatus(event, result.status)
  return result.body
})
